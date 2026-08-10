#include "conditional_omission.h"

#include <stdexcept>
#include <string>

namespace {

constexpr int kThreads = 256;
constexpr int kReplayCount = 4;

void check_cuda(cudaError_t status, const char* operation) {
    if (status != cudaSuccess) {
        throw std::runtime_error(std::string(operation) + ": " + cudaGetErrorString(status));
    }
}

__device__ __forceinline__ std::uint32_t exact_transform(std::uint32_t value, std::uint32_t index) {
    #pragma unroll 8
    for (int round = 0; round < 128; ++round) {
        value = value * 1664525U + 1013904223U + index + static_cast<std::uint32_t>(round);
        value ^= value >> 13;
        value = (value << 7) | (value >> 25);
    }
    return value;
}

__global__ void guard_kernel(
    cudaGraphConditionalHandle reuse_handle,
    cudaGraphConditionalHandle exact_handle,
    const std::int32_t* flags,
    const std::int32_t* launch_index) {
    if (blockIdx.x == 0 && threadIdx.x == 0) {
        const bool safe = flags[*launch_index] == 1;
        cudaGraphSetConditional(reuse_handle, safe ? 1U : 0U);
        cudaGraphSetConditional(exact_handle, safe ? 0U : 1U);
    }
}

__global__ void reuse_body_kernel(
    const std::int32_t* input,
    std::int32_t* outputs,
    std::int32_t* body_counts,
    std::int32_t* branch_history,
    std::int32_t* launch_index,
    std::int64_t element_count) {
    __shared__ std::int32_t output_slot;
    if (threadIdx.x == 0) {
        output_slot = atomicAdd(launch_index, 1);
        if (blockIdx.x == 0) {
            atomicAdd(&body_counts[0], 1);
            branch_history[output_slot] = 0;
        }
    }
    __syncthreads();
    for (std::int64_t offset = threadIdx.x; offset < element_count; offset += blockDim.x) {
        const auto value = static_cast<std::uint32_t>(input[offset]);
        outputs[static_cast<std::int64_t>(output_slot) * element_count + offset] =
            static_cast<std::int32_t>(value ^ 0x5A5A5A5AU);
    }
}

__global__ void exact_body_kernel(
    const std::int32_t* input,
    std::int32_t* outputs,
    std::int32_t* body_counts,
    std::int32_t* branch_history,
    std::int32_t* launch_index,
    std::int64_t element_count) {
    __shared__ std::int32_t output_slot;
    if (threadIdx.x == 0) {
        output_slot = atomicAdd(launch_index, 1);
        if (blockIdx.x == 0) {
            atomicAdd(&body_counts[1], 1);
            branch_history[output_slot] = 1;
        }
    }
    __syncthreads();
    for (std::int64_t offset = threadIdx.x; offset < element_count; offset += blockDim.x) {
        const auto value = static_cast<std::uint32_t>(input[offset]);
        outputs[static_cast<std::int64_t>(output_slot) * element_count + offset] =
            static_cast<std::int32_t>(exact_transform(value, static_cast<std::uint32_t>(offset)));
    }
}

__global__ void reuse_reference_kernel(
    const std::int32_t* input,
    std::int32_t* output,
    std::int64_t element_count) {
    const auto offset = static_cast<std::int64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    if (offset < element_count) {
        output[offset] = static_cast<std::int32_t>(
            static_cast<std::uint32_t>(input[offset]) ^ 0x5A5A5A5AU);
    }
}

__global__ void exact_reference_kernel(
    const std::int32_t* input,
    std::int32_t* output,
    std::int64_t element_count) {
    const auto offset = static_cast<std::int64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    if (offset < element_count) {
        output[offset] = static_cast<std::int32_t>(exact_transform(
            static_cast<std::uint32_t>(input[offset]), static_cast<std::uint32_t>(offset)));
    }
}

__global__ void parity_kernel(
    const std::int32_t* outputs,
    const std::int32_t* reuse_reference,
    const std::int32_t* exact_reference,
    std::int32_t* parity,
    std::int64_t element_count) {
    const auto offset = static_cast<std::int64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    if (offset >= element_count) {
        return;
    }
    for (int replay = 0; replay < kReplayCount; ++replay) {
        const auto* reference = (replay % 2 == 0) ? reuse_reference : exact_reference;
        if (outputs[static_cast<std::int64_t>(replay) * element_count + offset] != reference[offset]) {
            atomicExch(&parity[replay], -1);
        }
    }
}

cudaGraphNode_t add_conditional_body(
    cudaGraph_t graph,
    cudaGraphNode_t guard_node,
    cudaGraphConditionalHandle handle,
    void* kernel,
    void** kernel_args,
    dim3 grid) {
    cudaGraphNodeParams conditional_params{};
    conditional_params.type = cudaGraphNodeTypeConditional;
    conditional_params.conditional.handle = handle;
    conditional_params.conditional.type = cudaGraphCondTypeIf;
    conditional_params.conditional.size = 1;

    cudaGraphNode_t conditional_node{};
    check_cuda(
        cudaGraphAddNode(&conditional_node, graph, &guard_node, nullptr, 1, &conditional_params),
        "cudaGraphAddNode(conditional)");

    cudaKernelNodeParams body_params{};
    body_params.func = kernel;
    body_params.gridDim = grid;
    body_params.blockDim = dim3(kThreads);
    body_params.kernelParams = kernel_args;
    cudaGraphNode_t body_node{};
    check_cuda(
        cudaGraphAddKernelNode(
            &body_node,
            conditional_params.conditional.phGraph_out[0],
            nullptr,
            0,
            &body_params),
        "cudaGraphAddKernelNode(conditional body)");
    return conditional_node;
}

}  // namespace

A3G0NativeRunSummary run_a3_g0_conditional_sequence(
    const std::int32_t* input,
    const std::int32_t* flags,
    std::int32_t* outputs,
    std::int32_t* reuse_reference,
    std::int32_t* exact_reference,
    std::int32_t* parity,
    std::int32_t* body_counts,
    std::int32_t* branch_history,
    std::int32_t* launch_index,
    std::int64_t element_count,
    cudaStream_t stream) {
    const dim3 grid(static_cast<unsigned int>((element_count + kThreads - 1) / kThreads));

    reuse_reference_kernel<<<grid, kThreads, 0, stream>>>(input, reuse_reference, element_count);
    check_cuda(cudaGetLastError(), "reuse_reference_kernel launch");
    exact_reference_kernel<<<grid, kThreads, 0, stream>>>(input, exact_reference, element_count);
    check_cuda(cudaGetLastError(), "exact_reference_kernel launch");

    cudaGraph_t graph{};
    cudaGraphExec_t graph_exec{};
    check_cuda(cudaGraphCreate(&graph, 0), "cudaGraphCreate");
    try {
        cudaGraphConditionalHandle reuse_handle{};
        cudaGraphConditionalHandle exact_handle{};
        check_cuda(
            cudaGraphConditionalHandleCreate(&reuse_handle, graph, 0, cudaGraphCondAssignDefault),
            "cudaGraphConditionalHandleCreate(reuse)");
        check_cuda(
            cudaGraphConditionalHandleCreate(&exact_handle, graph, 0, cudaGraphCondAssignDefault),
            "cudaGraphConditionalHandleCreate(exact)");

        auto flags_arg = flags;
        auto launch_index_arg = launch_index;
        void* guard_args[] = {&reuse_handle, &exact_handle, &flags_arg, &launch_index_arg};
        cudaKernelNodeParams guard_params{};
        guard_params.func = reinterpret_cast<void*>(guard_kernel);
        guard_params.gridDim = dim3(1);
        guard_params.blockDim = dim3(1);
        guard_params.kernelParams = guard_args;
        cudaGraphNode_t guard_node{};
        check_cuda(
            cudaGraphAddKernelNode(&guard_node, graph, nullptr, 0, &guard_params),
            "cudaGraphAddKernelNode(guard)");

        auto input_arg = input;
        auto outputs_arg = outputs;
        auto counts_arg = body_counts;
        auto history_arg = branch_history;
        auto count_arg = element_count;
        void* reuse_args[] = {
            &input_arg, &outputs_arg, &counts_arg, &history_arg, &launch_index_arg, &count_arg};
        add_conditional_body(
            graph,
            guard_node,
            reuse_handle,
            reinterpret_cast<void*>(reuse_body_kernel),
            reuse_args,
            dim3(1));

        void* exact_args[] = {
            &input_arg, &outputs_arg, &counts_arg, &history_arg, &launch_index_arg, &count_arg};
        add_conditional_body(
            graph,
            guard_node,
            exact_handle,
            reinterpret_cast<void*>(exact_body_kernel),
            exact_args,
            dim3(1));

        check_cuda(cudaGraphInstantiate(&graph_exec, graph, 0), "cudaGraphInstantiate");
        for (int replay = 0; replay < kReplayCount; ++replay) {
            check_cuda(cudaGraphLaunch(graph_exec, stream), "cudaGraphLaunch");
        }

        parity_kernel<<<grid, kThreads, 0, stream>>>(
            outputs, reuse_reference, exact_reference, parity, element_count);
        check_cuda(cudaGetLastError(), "parity_kernel launch");
        check_cuda(cudaStreamSynchronize(stream), "final evidence cudaStreamSynchronize");
    } catch (...) {
        if (graph_exec != nullptr) {
            cudaGraphExecDestroy(graph_exec);
        }
        cudaGraphDestroy(graph);
        throw;
    }
    check_cuda(cudaGraphExecDestroy(graph_exec), "cudaGraphExecDestroy");
    check_cuda(cudaGraphDestroy(graph), "cudaGraphDestroy");

    return A3G0NativeRunSummary{
        kReplayCount,
        0,
        1,
        0,
    };
}
