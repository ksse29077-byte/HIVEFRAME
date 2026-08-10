#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "conditional_omission.h"

#include <cstdint>
#include <stdexcept>
#include <string>

namespace {

bool python_truth_attribute(PyObject* value, const char* name) {
    PyObject* attribute = PyObject_GetAttrString(value, name);
    if (attribute == nullptr) {
        throw std::runtime_error(std::string("missing tensor attribute: ") + name);
    }
    const int truth = PyObject_IsTrue(attribute);
    Py_DECREF(attribute);
    if (truth < 0) {
        throw std::runtime_error(std::string("invalid tensor attribute: ") + name);
    }
    return truth == 1;
}

long long python_integer_method(PyObject* value, const char* name) {
    PyObject* result = PyObject_CallMethod(value, name, nullptr);
    if (result == nullptr) {
        throw std::runtime_error(std::string("tensor method failed: ") + name);
    }
    const long long integer = PyLong_AsLongLong(result);
    Py_DECREF(result);
    if (PyErr_Occurred()) {
        throw std::runtime_error(std::string("tensor method was not integral: ") + name);
    }
    return integer;
}

void* tensor_data_ptr(PyObject* value) {
    PyObject* result = PyObject_CallMethod(value, "data_ptr", nullptr);
    if (result == nullptr) {
        throw std::runtime_error("tensor data_ptr() failed");
    }
    const auto pointer = PyLong_AsUnsignedLongLong(result);
    Py_DECREF(result);
    if (PyErr_Occurred()) {
        throw std::runtime_error("tensor data_ptr() was not an address");
    }
    return reinterpret_cast<void*>(static_cast<std::uintptr_t>(pointer));
}

bool tensor_is_int32(PyObject* value) {
    PyObject* dtype = PyObject_GetAttrString(value, "dtype");
    if (dtype == nullptr) {
        throw std::runtime_error("tensor dtype is unavailable");
    }
    PyObject* text = PyObject_Str(dtype);
    Py_DECREF(dtype);
    if (text == nullptr) {
        throw std::runtime_error("tensor dtype string is unavailable");
    }
    const char* utf8 = PyUnicode_AsUTF8(text);
    const bool valid = utf8 != nullptr && std::string(utf8) == "torch.int32";
    Py_DECREF(text);
    return valid;
}

void validate_tensor(
    PyObject* value,
    const char* name,
    long long expected_numel,
    long long expected_device) {
    if (!python_truth_attribute(value, "is_cuda")) {
        throw std::runtime_error(std::string(name) + " must be a CUDA tensor");
    }
    if (!tensor_is_int32(value)) {
        throw std::runtime_error(std::string(name) + " must use torch.int32");
    }
    PyObject* contiguous = PyObject_CallMethod(value, "is_contiguous", nullptr);
    if (contiguous == nullptr) {
        throw std::runtime_error(std::string(name) + " contiguity is unavailable");
    }
    const int contiguous_truth = PyObject_IsTrue(contiguous);
    Py_DECREF(contiguous);
    if (contiguous_truth != 1) {
        throw std::runtime_error(std::string(name) + " must be contiguous");
    }
    if (python_integer_method(value, "numel") != expected_numel) {
        throw std::runtime_error(std::string(name) + " has an invalid element count");
    }
    if (python_integer_method(value, "get_device") != expected_device) {
        throw std::runtime_error(std::string(name) + " is on a different CUDA device");
    }
}

PyObject* run_sequence(PyObject*, PyObject* args) {
    PyObject* input = nullptr;
    PyObject* flags = nullptr;
    PyObject* outputs = nullptr;
    PyObject* reuse_reference = nullptr;
    PyObject* exact_reference = nullptr;
    PyObject* parity = nullptr;
    PyObject* body_counts = nullptr;
    PyObject* branch_history = nullptr;
    PyObject* launch_index = nullptr;
    unsigned long long stream_pointer = 0;
    if (!PyArg_ParseTuple(
            args,
            "OOOOOOOOOK",
            &input,
            &flags,
            &outputs,
            &reuse_reference,
            &exact_reference,
            &parity,
            &body_counts,
            &branch_history,
            &launch_index,
            &stream_pointer)) {
        return nullptr;
    }

    try {
        if (!python_truth_attribute(input, "is_cuda") || !tensor_is_int32(input)) {
            throw std::runtime_error("input must be a torch.int32 CUDA tensor");
        }
        const long long element_count = python_integer_method(input, "numel");
        const long long device = python_integer_method(input, "get_device");
        if (element_count <= 0) {
            throw std::runtime_error("input must not be empty");
        }
        validate_tensor(flags, "flags", 4, device);
        validate_tensor(outputs, "outputs", 4 * element_count, device);
        validate_tensor(reuse_reference, "reuse_reference", element_count, device);
        validate_tensor(exact_reference, "exact_reference", element_count, device);
        validate_tensor(parity, "parity", 4, device);
        validate_tensor(body_counts, "body_counts", 2, device);
        validate_tensor(branch_history, "branch_history", 4, device);
        validate_tensor(launch_index, "launch_index", 1, device);
        const auto summary = run_a3_g0_conditional_sequence(
            static_cast<const std::int32_t*>(tensor_data_ptr(input)),
            static_cast<const std::int32_t*>(tensor_data_ptr(flags)),
            static_cast<std::int32_t*>(tensor_data_ptr(outputs)),
            static_cast<std::int32_t*>(tensor_data_ptr(reuse_reference)),
            static_cast<std::int32_t*>(tensor_data_ptr(exact_reference)),
            static_cast<std::int32_t*>(tensor_data_ptr(parity)),
            static_cast<std::int32_t*>(tensor_data_ptr(body_counts)),
            static_cast<std::int32_t*>(tensor_data_ptr(branch_history)),
            static_cast<std::int32_t*>(tensor_data_ptr(launch_index)),
            element_count,
            reinterpret_cast<cudaStream_t>(static_cast<std::uintptr_t>(stream_pointer)));
        return Py_BuildValue(
            "{s:i,s:i,s:i,s:i,s:O,s:O}",
            "graph_launch_count",
            summary.graph_launch_count,
            "explicit_hot_path_cpu_sync_count",
            summary.explicit_hot_path_cpu_sync_count,
            "final_evidence_sync_count",
            summary.final_evidence_sync_count,
            "conditional_body_allocation_count",
            summary.conditional_body_allocation_count,
            "current_pytorch_stream_used",
            Py_True,
            "separate_cuda_context_created",
            Py_False);
    } catch (const std::exception& error) {
        PyErr_SetString(PyExc_RuntimeError, error.what());
        return nullptr;
    }
}

PyMethodDef module_methods[] = {
    {"run_sequence", run_sequence, METH_VARARGS, "Run the fixed conditional replay sequence."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef module_definition = {
    PyModuleDef_HEAD_INIT,
    "hiveframe_a3_g0_cuda",
    "HIVEFRAME A3-G0 GPU-native conditional omission primitive",
    -1,
    module_methods,
};

}  // namespace

PyMODINIT_FUNC PyInit_hiveframe_a3_g0_cuda() {
    return PyModule_Create(&module_definition);
}
