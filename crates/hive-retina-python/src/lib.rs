#![doc = "Bounded Python 3.12 shared-buffer adapter for the model-free R3 probe."]

use hive_retina_runtime::{
    evaluate_step_policy as evaluate_step_policy_core, InputProfile, PixelBox, R3CandidateSummary,
    StepDirective, StepObservation, C1_REASON_RUST_PANIC, C1_STEP_POLICY_ABI_VERSION,
};
use pyo3::buffer::PyBuffer;
use pyo3::exceptions::{PyRuntimeError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBytes, PyDict, PyModule};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::time::Instant;

const WIDTH: usize = 1920;
const HEIGHT: usize = 1080;
const FRAMES: usize = 8;
const BYTE_LENGTH: usize = WIDTH * HEIGHT * FRAMES;

fn set_summary(dict: &Bound<'_, PyDict>, summary: &R3CandidateSummary) -> PyResult<()> {
    dict.set_item("candidate_id", &summary.candidate_id)?;
    dict.set_item("topology", &summary.topology)?;
    dict.set_item("semantic_hash", &summary.semantic_hash)?;
    dict.set_item("input_sha256", &summary.input_sha256)?;
    dict.set_item("eye_count", summary.eye_count)?;
    dict.set_item("observation_count", summary.observation_count)?;
    dict.set_item("fused_region_count", summary.fused_region_count)?;
    dict.set_item("compute_unit_count", summary.compute_unit_count)?;
    dict.set_item("dirty_region_count", summary.dirty_region_count)?;
    dict.set_item("stable_region_count", summary.stable_region_count)?;
    dict.set_item("uncertain_region_count", summary.uncertain_region_count)?;
    dict.set_item("generate_unit_count", summary.generate_unit_count)?;
    dict.set_item("reuse_cache_unit_count", summary.reuse_cache_unit_count)?;
    dict.set_item("reconcile_unit_count", summary.reconcile_unit_count)?;
    dict.set_item("pipeline_total_ns", summary.pipeline_total_ns)?;
    dict.set_item("logical_bytes_read", summary.logical_bytes_read)?;
    dict.set_item("bytes_copied", summary.bytes_copied)?;
    dict.set_item("temporary_buffer_bytes", summary.temporary_buffer_bytes)?;
    Ok(())
}

#[pyfunction]
fn run_candidate<'py>(
    py: Python<'py>,
    input: &Bound<'py, PyAny>,
    candidate_id: &str,
    profile_id: &str,
    width: usize,
    height: usize,
    frames: usize,
    seed: u64,
) -> PyResult<Bound<'py, PyDict>> {
    let function_started = Instant::now();
    let acquisition_started = Instant::now();
    let buffer = PyBuffer::<u8>::get(input)
        .map_err(|error| PyTypeError::new_err(format!("uint8 buffer required: {error}")))?;
    let buffer_acquisition_ns = acquisition_started.elapsed().as_nanos();

    let validation_started = Instant::now();
    if profile_id != "case-b-high-resolution-local-change" {
        return Err(PyValueError::new_err(
            "R3 is restricted to the existing Case B profile.",
        ));
    }
    if (width, height, frames) != (WIDTH, HEIGHT, FRAMES) {
        return Err(PyValueError::new_err(
            "R3 requires the exact Case B shape 8x1080x1920.",
        ));
    }
    if !matches!(candidate_id, "T0" | "T1" | "T2") {
        return Err(PyValueError::new_err("R3 admits exactly T0, T1, or T2."));
    }
    if !buffer.readonly() {
        return Err(PyValueError::new_err(
            "R3 requires a read-only exported buffer.",
        ));
    }
    if !buffer.is_c_contiguous() || buffer.item_size() != 1 || buffer.len_bytes() != BYTE_LENGTH {
        return Err(PyValueError::new_err(
            "R3 requires a C-contiguous packed uint8 Case B buffer.",
        ));
    }
    if buffer.dimensions() != 3 || buffer.shape() != [FRAMES, HEIGHT, WIDTH] {
        return Err(PyValueError::new_err(
            "R3 buffer shape must be [8, 1080, 1920].",
        ));
    }
    let cells = buffer
        .as_slice(py)
        .ok_or_else(|| PyValueError::new_err("R3 buffer cannot be borrowed as a C-order slice."))?;
    let argument_validation_ns = validation_started.elapsed().as_nanos();

    // SAFETY: PyBuffer has validated an item-size-1, C-contiguous u8 export. The
    // exporter is read-only, remains owned by `buffer`, and the GIL stays held for
    // the complete Rust call. ReadOnlyCell<u8> is repr(transparent) in PyO3. No
    // Python callback or mutation occurs while this borrowed slice is live.
    let sequence = unsafe { std::slice::from_raw_parts(cells.as_ptr().cast::<u8>(), cells.len()) };
    let profile = InputProfile::new(
        profile_id,
        width,
        height,
        frames,
        seed,
        vec![PixelBox::new(968, 238, 72, 84).map_err(PyValueError::new_err)?],
    )
    .map_err(PyValueError::new_err)?;
    let core_started = Instant::now();
    let summary = hive_retina_runtime::run_r3_candidate(&profile, candidate_id, sequence)
        .map_err(PyRuntimeError::new_err)?;
    let rust_core_ns = core_started.elapsed().as_nanos();

    let marshal_started = Instant::now();
    let result = PyDict::new(py);
    set_summary(&result, &summary)?;
    result.set_item("input_borrowed", true)?;
    result.set_item("input_readonly", true)?;
    result.set_item("input_c_contiguous", true)?;
    result.set_item("input_copy_bytes", 0)?;
    result.set_item("input_handoff_bytes", BYTE_LENGTH)?;
    result.set_item("ffi_calls", 1)?;
    result.set_item("subprocess_count", 0)?;
    result.set_item("temporary_file_count", 0)?;
    result.set_item("gil_policy", "held_for_complete_call")?;
    result.set_item("allocation_count", py.None())?;
    result.set_item("allocation_count_status", "not_collected")?;
    result.set_item(
        "allocation_count_reason",
        "The Rust global allocator is not instrumented in R3.",
    )?;
    let output_marshal_ns = marshal_started.elapsed().as_nanos();
    result.set_item("buffer_acquisition_ns", buffer_acquisition_ns)?;
    result.set_item("argument_validation_ns", argument_validation_ns)?;
    result.set_item("rust_core_ns", rust_core_ns)?;
    result.set_item("output_marshal_ns", output_marshal_ns)?;
    result.set_item(
        "rust_function_span_ns",
        function_started.elapsed().as_nanos(),
    )?;
    Ok(result)
}

#[pyfunction]
fn empty_boundary_probe() -> u8 {
    0
}

fn fixed_digest(value: &Bound<'_, PyBytes>, name: &str) -> PyResult<[u8; 32]> {
    value
        .as_bytes()
        .try_into()
        .map_err(|_| PyValueError::new_err(format!("{name} must contain exactly 32 bytes.")))
}

fn set_directive(dict: &Bound<'_, PyDict>, directive: &StepDirective) -> PyResult<()> {
    dict.set_item("abi_version", directive.abi_version)?;
    dict.set_item("struct_size", directive.struct_size)?;
    dict.set_item("decision_code", directive.decision_code)?;
    dict.set_item("reason_code", directive.reason_code)?;
    dict.set_item("unsupported_flags", directive.unsupported_flags)?;
    dict.set_item(
        "decision_digest",
        PyBytes::new(dict.py(), &directive.decision_digest),
    )?;
    dict.set_item("skipped_step_count", directive.skipped_step_count)?;
    dict.set_item("skipped_block_count", directive.skipped_block_count)?;
    dict.set_item("skipped_token_count", directive.skipped_token_count)?;
    dict.set_item("skipped_latent_count", directive.skipped_latent_count)?;
    dict.set_item("reused_cache_count", directive.reused_cache_count)?;
    dict.set_item("partial_compute_count", directive.partial_compute_count)?;
    Ok(())
}

/// One in-process, fixed-metadata policy call. No Python callback, file I/O,
/// network I/O, lock, sleep, tensor, model state, or CUDA address crosses it.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn evaluate_step_policy<'py>(
    py: Python<'py>,
    abi_version: u32,
    struct_size: u32,
    run_digest: &Bound<'py, PyBytes>,
    workflow_revision_digest: &Bound<'py, PyBytes>,
    settings_digest: &Bound<'py, PyBytes>,
    step_index: u32,
    total_steps: u32,
    sampler_logical_id: u32,
    scheduler_logical_id: u32,
    timestep_available: bool,
    timestep_bits: u64,
    sigma_available: bool,
    sigma_bits: u64,
    uncertainty_flags: u32,
    invalidation_flags: u32,
    full_compute_supported: bool,
    fallback_supported: bool,
    cache_available: bool,
    receipt_required: bool,
    unsupported_flags: u32,
) -> PyResult<Bound<'py, PyDict>> {
    let observation = StepObservation {
        abi_version,
        struct_size,
        run_digest: fixed_digest(run_digest, "run_digest")?,
        workflow_revision_digest: fixed_digest(
            workflow_revision_digest,
            "workflow_revision_digest",
        )?,
        settings_digest: fixed_digest(settings_digest, "settings_digest")?,
        step_index,
        total_steps,
        sampler_logical_id,
        scheduler_logical_id,
        timestep_available: u32::from(timestep_available),
        timestep_bits,
        sigma_available: u32::from(sigma_available),
        sigma_bits,
        uncertainty_flags,
        invalidation_flags,
        full_compute_supported: u32::from(full_compute_supported),
        fallback_supported: u32::from(fallback_supported),
        cache_available: u32::from(cache_available),
        receipt_required: u32::from(receipt_required),
        unsupported_flags,
    };
    let started = Instant::now();
    let evaluated = catch_unwind(AssertUnwindSafe(|| evaluate_step_policy_core(&observation)));
    let rust_policy_ns = started.elapsed().as_nanos();
    let result = PyDict::new(py);
    match evaluated {
        Ok(directive) => {
            result.set_item("ffi_status", 0)?;
            set_directive(&result, &directive)?;
        }
        Err(_) => {
            result.set_item("ffi_status", 1)?;
            set_directive(
                &result,
                &StepDirective::fail_open(C1_REASON_RUST_PANIC, [0; 32]),
            )?;
        }
    }
    result.set_item("rust_policy_ns", rust_policy_ns)?;
    Ok(result)
}

#[pyfunction]
fn step_policy_contract<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("abi_version", C1_STEP_POLICY_ABI_VERSION)?;
    result.set_item("observation_struct_size", StepObservation::contract_size())?;
    result.set_item("directive_struct_size", StepDirective::contract_size())?;
    result.set_item("max_rust_calls_per_callback", 1)?;
    result.set_item("tensor_bytes_per_callback", 0)?;
    Ok(result)
}

#[pyfunction]
fn step_policy_panic_boundary_probe() -> u32 {
    let result = catch_unwind(|| panic!("C1 panic-boundary probe"));
    u32::from(result.is_err())
}

#[pymodule]
fn _hive_retina_boundary(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(run_candidate, module)?)?;
    module.add_function(wrap_pyfunction!(empty_boundary_probe, module)?)?;
    module.add_function(wrap_pyfunction!(evaluate_step_policy, module)?)?;
    module.add_function(wrap_pyfunction!(step_policy_contract, module)?)?;
    module.add_function(wrap_pyfunction!(step_policy_panic_boundary_probe, module)?)?;
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    module.add("pyo3_version", "0.29.0")?;
    module.add("python_abi", "abi3-py312")?;
    Ok(())
}
