#![doc = "Bounded Python 3.12 shared-buffer adapter for the model-free R3 probe."]

use hive_retina_runtime::{
    evaluate_c3_frozen_block_plan as evaluate_c3_frozen_block_plan_core,
    evaluate_compound_eye_shadow_policy as evaluate_compound_eye_shadow_policy_core,
    evaluate_reuse_plan as evaluate_reuse_plan_core,
    evaluate_step_policy as evaluate_step_policy_core, C3FrozenBlockPlanDirective,
    C3FrozenBlockPlanObservation, CompoundEyeShadowDirective, CompoundEyeShadowObservation,
    InputProfile, PixelBox, R3CandidateSummary, ReusePlanDirective, ReusePlanObservation,
    StepDirective, StepObservation, C1_REASON_RUST_PANIC, C1_STEP_POLICY_ABI_VERSION,
    C2_COMPOUND_EYE_SHADOW_ABI_VERSION, C2_EYE_COUNT, C2_REASON_RUST_PANIC, C2_SKETCH_VALUE_COUNT,
    C2_STABLE_VALIDATION_LIMIT_PPM, C3_R1_BLOCK_COUNT, C3_R1_BLOCK_PLAN_ABI_VERSION,
    C3_R1_CANDIDATE_BLOCK_COUNT, C3_R1_CANDIDATE_BLOCK_END, C3_R1_CANDIDATE_BLOCK_START,
    C3_R1_FROZEN_SCHEDULE, C3_R1_REASON_RUST_PANIC, C3_R1_TOTAL_STEPS, C3_R2_REASON_RUST_PANIC,
    C3_R2_REUSE_PLAN_ABI_VERSION,
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

fn fixed_sketch(values: Vec<i32>, name: &str) -> PyResult<[i32; C2_SKETCH_VALUE_COUNT]> {
    values.try_into().map_err(|values: Vec<i32>| {
        PyValueError::new_err(format!(
            "{name} must contain exactly {C2_SKETCH_VALUE_COUNT} values; got {}.",
            values.len()
        ))
    })
}

fn set_c2_directive(
    dict: &Bound<'_, PyDict>,
    directive: &CompoundEyeShadowDirective,
) -> PyResult<()> {
    dict.set_item("abi_version", directive.abi_version)?;
    dict.set_item("struct_size", directive.struct_size)?;
    dict.set_item("decision_code", directive.decision_code)?;
    dict.set_item("reason_code", directive.reason_code)?;
    dict.set_item("unsupported_flags", directive.unsupported_flags)?;
    dict.set_item("eye_state", directive.eye_state.to_vec())?;
    dict.set_item("eye_confidence_ppm", directive.eye_confidence_ppm.to_vec())?;
    dict.set_item("eye_change_ppm", directive.eye_change_ppm.to_vec())?;
    dict.set_item("stable_eye_count", directive.stable_eye_count)?;
    dict.set_item("active_eye_count", directive.active_eye_count)?;
    dict.set_item("uncertain_eye_count", directive.uncertain_eye_count)?;
    dict.set_item(
        "candidate_generate_count",
        directive.candidate_generate_count,
    )?;
    dict.set_item("candidate_reuse_count", directive.candidate_reuse_count)?;
    dict.set_item(
        "candidate_reconcile_count",
        directive.candidate_reconcile_count,
    )?;
    dict.set_item("global_invalidation", directive.global_invalidation)?;
    dict.set_item("overlap_conflict_mask", directive.overlap_conflict_mask)?;
    dict.set_item(
        "shared_visual_state_digest",
        PyBytes::new(dict.py(), &directive.shared_visual_state_digest),
    )?;
    dict.set_item(
        "compute_plan_digest",
        PyBytes::new(dict.py(), &directive.compute_plan_digest),
    )?;
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

/// One in-process C2 shadow-policy call. Only two fixed 48-value sketches and
/// fixed metadata cross the boundary; tensors and CUDA pointers are rejected
/// by construction.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn evaluate_compound_eye_shadow_policy<'py>(
    py: Python<'py>,
    abi_version: u32,
    struct_size: u32,
    run_digest: &Bound<'py, PyBytes>,
    workflow_revision_digest: &Bound<'py, PyBytes>,
    settings_digest: &Bound<'py, PyBytes>,
    step_index: u32,
    total_steps: u32,
    topology_id: u32,
    sketch_source_id: u32,
    quantization_scale: u32,
    previous_available: bool,
    uncertainty_flags: u32,
    invalidation_flags: u32,
    full_compute_supported: bool,
    fallback_supported: bool,
    receipt_required: bool,
    unsupported_flags: u32,
    current_sketch_q: Vec<i32>,
    previous_sketch_q: Vec<i32>,
) -> PyResult<Bound<'py, PyDict>> {
    let observation = CompoundEyeShadowObservation {
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
        topology_id,
        sketch_source_id,
        quantization_scale,
        previous_available: u32::from(previous_available),
        uncertainty_flags,
        invalidation_flags,
        full_compute_supported: u32::from(full_compute_supported),
        fallback_supported: u32::from(fallback_supported),
        receipt_required: u32::from(receipt_required),
        unsupported_flags,
        current_sketch_q: fixed_sketch(current_sketch_q, "current_sketch_q")?,
        previous_sketch_q: fixed_sketch(previous_sketch_q, "previous_sketch_q")?,
    };
    let started = Instant::now();
    let evaluated = catch_unwind(AssertUnwindSafe(|| {
        evaluate_compound_eye_shadow_policy_core(&observation)
    }));
    let rust_policy_ns = started.elapsed().as_nanos();
    let result = PyDict::new(py);
    match evaluated {
        Ok(directive) => {
            result.set_item("ffi_status", 0)?;
            set_c2_directive(&result, &directive)?;
        }
        Err(_) => {
            result.set_item("ffi_status", 1)?;
            set_c2_directive(
                &result,
                &CompoundEyeShadowDirective::fail_open(C2_REASON_RUST_PANIC),
            )?;
        }
    }
    result.set_item("rust_policy_ns", rust_policy_ns)?;
    Ok(result)
}

#[pyfunction]
fn compound_eye_shadow_contract<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("abi_version", C2_COMPOUND_EYE_SHADOW_ABI_VERSION)?;
    result.set_item(
        "observation_struct_size",
        CompoundEyeShadowObservation::contract_size(),
    )?;
    result.set_item(
        "directive_struct_size",
        CompoundEyeShadowDirective::contract_size(),
    )?;
    result.set_item("eye_count", C2_EYE_COUNT)?;
    result.set_item("sketch_value_count", C2_SKETCH_VALUE_COUNT)?;
    result.set_item("max_rust_calls_per_callback", 1)?;
    result.set_item("host_scalar_bytes_per_callback", C2_SKETCH_VALUE_COUNT * 4)?;
    result.set_item(
        "stable_validation_limit_ppm",
        C2_STABLE_VALIDATION_LIMIT_PPM,
    )?;
    result.set_item("tensor_bytes_per_callback", 0)?;
    Ok(result)
}

fn set_c3_r1_directive(
    dict: &Bound<'_, PyDict>,
    directive: &C3FrozenBlockPlanDirective,
) -> PyResult<()> {
    dict.set_item("abi_version", directive.abi_version)?;
    dict.set_item("struct_size", directive.struct_size)?;
    dict.set_item("decision_code", directive.decision_code)?;
    dict.set_item("reason_code", directive.reason_code)?;
    dict.set_item("target_step", directive.target_step)?;
    dict.set_item("bypass_mask", directive.bypass_mask)?;
    dict.set_item("bypass_count", directive.bypass_count)?;
    dict.set_item("fallback_required", directive.fallback_required)?;
    dict.set_item("unsupported_flags", directive.unsupported_flags)?;
    dict.set_item(
        "decision_digest",
        PyBytes::new(dict.py(), &directive.decision_digest),
    )?;
    Ok(())
}

/// One fixed-metadata C3-R1 call per consumed callback observation. No tensor,
/// pointer, block activation, prompt, or CUDA address crosses this boundary.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn evaluate_c3_frozen_block_plan<'py>(
    py: Python<'py>,
    abi_version: u32,
    struct_size: u32,
    run_digest: &Bound<'py, PyBytes>,
    workflow_revision_digest: &Bound<'py, PyBytes>,
    settings_digest: &Bound<'py, PyBytes>,
    model_revision_digest: &Bound<'py, PyBytes>,
    predicted_execution_step: u32,
    total_steps: u32,
    block_count: u32,
    frozen_schedule_member: bool,
    stable_mask: u32,
    stable_count: u32,
    active_mask: u32,
    active_count: u32,
    uncertain_mask: u32,
    uncertain_count: u32,
    global_invalidation: bool,
    overlap_conflict_mask: u32,
    prediction_valid: bool,
    source_valid: bool,
    selective_supported: bool,
    fallback_supported: bool,
    fatal_flags: u32,
    unsupported_flags: u32,
) -> PyResult<Bound<'py, PyDict>> {
    let observation = C3FrozenBlockPlanObservation {
        abi_version,
        struct_size,
        run_digest: fixed_digest(run_digest, "run_digest")?,
        workflow_revision_digest: fixed_digest(
            workflow_revision_digest,
            "workflow_revision_digest",
        )?,
        settings_digest: fixed_digest(settings_digest, "settings_digest")?,
        model_revision_digest: fixed_digest(model_revision_digest, "model_revision_digest")?,
        predicted_execution_step,
        total_steps,
        block_count,
        frozen_schedule_member: u32::from(frozen_schedule_member),
        stable_mask,
        stable_count,
        active_mask,
        active_count,
        uncertain_mask,
        uncertain_count,
        global_invalidation: u32::from(global_invalidation),
        overlap_conflict_mask,
        prediction_valid: u32::from(prediction_valid),
        source_valid: u32::from(source_valid),
        selective_supported: u32::from(selective_supported),
        fallback_supported: u32::from(fallback_supported),
        fatal_flags,
        unsupported_flags,
    };
    let started = Instant::now();
    let evaluated = catch_unwind(AssertUnwindSafe(|| {
        evaluate_c3_frozen_block_plan_core(&observation)
    }));
    let rust_policy_ns = started.elapsed().as_nanos();
    let result = PyDict::new(py);
    match evaluated {
        Ok(directive) => {
            result.set_item("ffi_status", 0)?;
            set_c3_r1_directive(&result, &directive)?;
        }
        Err(_) => {
            result.set_item("ffi_status", 1)?;
            set_c3_r1_directive(
                &result,
                &C3FrozenBlockPlanDirective::fail_open(
                    C3_R1_REASON_RUST_PANIC,
                    predicted_execution_step,
                    [0; 32],
                ),
            )?;
        }
    }
    result.set_item("rust_policy_ns", rust_policy_ns)?;
    Ok(result)
}

#[pyfunction]
fn c3_frozen_block_plan_contract<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("abi_version", C3_R1_BLOCK_PLAN_ABI_VERSION)?;
    result.set_item(
        "observation_struct_size",
        C3FrozenBlockPlanObservation::contract_size(),
    )?;
    result.set_item(
        "directive_struct_size",
        C3FrozenBlockPlanDirective::contract_size(),
    )?;
    result.set_item("total_steps", C3_R1_TOTAL_STEPS)?;
    result.set_item("block_count", C3_R1_BLOCK_COUNT)?;
    result.set_item("frozen_schedule", C3_R1_FROZEN_SCHEDULE.to_vec())?;
    result.set_item("candidate_block_start", C3_R1_CANDIDATE_BLOCK_START)?;
    result.set_item("candidate_block_end", C3_R1_CANDIDATE_BLOCK_END)?;
    result.set_item("candidate_block_count", C3_R1_CANDIDATE_BLOCK_COUNT)?;
    result.set_item("max_rust_calls_per_callback", 1)?;
    result.set_item("max_rust_calls_per_block", 0)?;
    result.set_item("tensor_bytes_per_call", 0)?;
    Ok(result)
}

fn set_reuse_plan_directive(
    dict: &Bound<'_, PyDict>,
    directive: &ReusePlanDirective,
) -> PyResult<()> {
    dict.set_item("abi_version", directive.abi_version)?;
    dict.set_item("struct_size", directive.struct_size)?;
    dict.set_item("decision_code", directive.decision_code)?;
    dict.set_item("reason_code", directive.reason_code)?;
    dict.set_item("target_execution_step", directive.target_execution_step)?;
    dict.set_item("source_execution_step", directive.source_execution_step)?;
    dict.set_item("fallback_required", directive.fallback_required)?;
    dict.set_item("unsupported_flags", directive.unsupported_flags)?;
    dict.set_item(
        "decision_digest",
        PyBytes::new(dict.py(), &directive.decision_digest),
    )?;
    Ok(())
}

/// One generic, fixed-width metadata call per consumed callback. Activations,
/// residual buffers, model names, paths, and CUDA pointers remain in Python's
/// model-adapter boundary.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn evaluate_reuse_plan<'py>(
    py: Python<'py>,
    abi_version: u32,
    struct_size: u32,
    run_digest: &Bound<'py, PyBytes>,
    workflow_revision_digest: &Bound<'py, PyBytes>,
    settings_digest: &Bound<'py, PyBytes>,
    model_revision_digest: &Bound<'py, PyBytes>,
    segment_logical_digest: &Bound<'py, PyBytes>,
    target_execution_step: u32,
    source_execution_step: u32,
    total_steps: u32,
    cache_age: u32,
    cache_available: bool,
    cache_provenance_valid: bool,
    residual_similarity_admitted: bool,
    calibrated_target: bool,
    prior_step_reused: bool,
    stable_mask: u32,
    stable_count: u32,
    active_mask: u32,
    active_count: u32,
    uncertain_mask: u32,
    uncertain_count: u32,
    global_invalidation: bool,
    overlap_conflict_mask: u32,
    prediction_valid: bool,
    source_valid: bool,
    finite: bool,
    fallback_supported: bool,
    fatal_flags: u32,
    unsupported_flags: u32,
) -> PyResult<Bound<'py, PyDict>> {
    let observation = ReusePlanObservation {
        abi_version,
        struct_size,
        run_digest: fixed_digest(run_digest, "run_digest")?,
        workflow_revision_digest: fixed_digest(
            workflow_revision_digest,
            "workflow_revision_digest",
        )?,
        settings_digest: fixed_digest(settings_digest, "settings_digest")?,
        model_revision_digest: fixed_digest(model_revision_digest, "model_revision_digest")?,
        segment_logical_digest: fixed_digest(segment_logical_digest, "segment_logical_digest")?,
        target_execution_step,
        source_execution_step,
        total_steps,
        cache_age,
        cache_available: u32::from(cache_available),
        cache_provenance_valid: u32::from(cache_provenance_valid),
        residual_similarity_admitted: u32::from(residual_similarity_admitted),
        calibrated_target: u32::from(calibrated_target),
        prior_step_reused: u32::from(prior_step_reused),
        stable_mask,
        stable_count,
        active_mask,
        active_count,
        uncertain_mask,
        uncertain_count,
        global_invalidation: u32::from(global_invalidation),
        overlap_conflict_mask,
        prediction_valid: u32::from(prediction_valid),
        source_valid: u32::from(source_valid),
        finite: u32::from(finite),
        fallback_supported: u32::from(fallback_supported),
        fatal_flags,
        unsupported_flags,
    };
    let started = Instant::now();
    let evaluated = catch_unwind(AssertUnwindSafe(|| evaluate_reuse_plan_core(&observation)));
    let rust_policy_ns = started.elapsed().as_nanos();
    let result = PyDict::new(py);
    match evaluated {
        Ok(directive) => {
            result.set_item("ffi_status", 0)?;
            set_reuse_plan_directive(&result, &directive)?;
        }
        Err(_) => {
            result.set_item("ffi_status", 1)?;
            set_reuse_plan_directive(
                &result,
                &ReusePlanDirective::fail_open(
                    C3_R2_REASON_RUST_PANIC,
                    target_execution_step,
                    source_execution_step,
                    [0; 32],
                ),
            )?;
        }
    }
    result.set_item("rust_policy_ns", rust_policy_ns)?;
    Ok(result)
}

#[pyfunction]
fn reuse_plan_contract<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("abi_version", C3_R2_REUSE_PLAN_ABI_VERSION)?;
    result.set_item(
        "observation_struct_size",
        ReusePlanObservation::contract_size(),
    )?;
    result.set_item("directive_struct_size", ReusePlanDirective::contract_size())?;
    result.set_item("max_rust_calls_per_callback", 1)?;
    result.set_item("max_rust_calls_per_block", 0)?;
    result.set_item("tensor_bytes_per_call", 0)?;
    result.set_item("cache_age_required", 1)?;
    Ok(result)
}

#[pymodule]
fn _hive_retina_boundary(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(run_candidate, module)?)?;
    module.add_function(wrap_pyfunction!(empty_boundary_probe, module)?)?;
    module.add_function(wrap_pyfunction!(evaluate_step_policy, module)?)?;
    module.add_function(wrap_pyfunction!(step_policy_contract, module)?)?;
    module.add_function(wrap_pyfunction!(step_policy_panic_boundary_probe, module)?)?;
    module.add_function(wrap_pyfunction!(
        evaluate_compound_eye_shadow_policy,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(compound_eye_shadow_contract, module)?)?;
    module.add_function(wrap_pyfunction!(evaluate_c3_frozen_block_plan, module)?)?;
    module.add_function(wrap_pyfunction!(c3_frozen_block_plan_contract, module)?)?;
    module.add_function(wrap_pyfunction!(evaluate_reuse_plan, module)?)?;
    module.add_function(wrap_pyfunction!(reuse_plan_contract, module)?)?;
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    module.add("pyo3_version", "0.29.0")?;
    module.add("python_abi", "abi3-py312")?;
    Ok(())
}
