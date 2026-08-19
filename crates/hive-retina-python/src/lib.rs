#![doc = "Bounded Python 3.12 shared-buffer adapter for the model-free R3 probe."]

use hive_retina_runtime::cache_plan_v2::{
    compile_cache_plan_v2 as compile_cache_plan_v2_core, fail_open_cache_plan_v2, CacheCandidateV2,
    CacheInventoryEntryV2, CachePlanPerformanceReceiptV2, GenerationCachePlanRequest,
    GenerationCachePlanV2, GenerationEvidenceBatchHeader, GenerationEvidenceBatchV2,
    GenerationIdentityV2, HardwareProfileV2, ReceiptMetricU64, CACHE_PLAN_ABI_V2_VERSION,
    CACHE_PLAN_V2_CONTRACT_VERSION, CACHE_PLAN_V2_MAX_BATCH_BYTES, CACHE_PLAN_V2_MAX_INVENTORY,
    CACHE_PLAN_V2_MAX_RECORDS, CACHE_PLAN_V2_REASON_BATCH_MALFORMED,
    CACHE_PLAN_V2_REASON_RUST_PANIC,
};
use hive_retina_runtime::{
    evaluate_attention_region_plan as evaluate_attention_region_plan_core,
    evaluate_c3_frozen_block_plan as evaluate_c3_frozen_block_plan_core,
    evaluate_compound_eye_shadow_policy as evaluate_compound_eye_shadow_policy_core,
    evaluate_correction_plan as evaluate_correction_plan_core,
    evaluate_reuse_plan as evaluate_reuse_plan_core,
    evaluate_step_policy as evaluate_step_policy_core, AttentionRegionPlanDirective,
    AttentionRegionPlanObservation, C3FrozenBlockPlanDirective, C3FrozenBlockPlanObservation,
    CompoundEyeShadowDirective, CompoundEyeShadowObservation, CorrectionPlanDirective,
    CorrectionPlanObservation, InputProfile, PixelBox, R3CandidateSummary, ReusePlanDirective,
    ReusePlanObservation, StepDirective, StepObservation, A1_ATTENTION_REGION_PLAN_ABI_VERSION,
    A1_EYE_COUNT, A1_REASON_RUST_PANIC, A1_REGION_COUNT, C1_REASON_RUST_PANIC,
    C1_STEP_POLICY_ABI_VERSION, C2_COMPOUND_EYE_SHADOW_ABI_VERSION, C2_EYE_COUNT,
    C2_REASON_RUST_PANIC, C2_SKETCH_VALUE_COUNT, C2_STABLE_VALIDATION_LIMIT_PPM, C3_R1_BLOCK_COUNT,
    C3_R1_BLOCK_PLAN_ABI_VERSION, C3_R1_CANDIDATE_BLOCK_COUNT, C3_R1_CANDIDATE_BLOCK_END,
    C3_R1_CANDIDATE_BLOCK_START, C3_R1_FROZEN_SCHEDULE, C3_R1_REASON_RUST_PANIC, C3_R1_TOTAL_STEPS,
    C3_R2_REASON_RUST_PANIC, C3_R2_REUSE_PLAN_ABI_VERSION, C3_R3_CORRECTION_PLAN_ABI_VERSION,
    C3_R3_REASON_RUST_PANIC,
};
use pyo3::buffer::PyBuffer;
use pyo3::exceptions::{PyRuntimeError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBytes, PyDict, PyList, PyModule};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Instant;

static MODULE_LOAD_COUNT: AtomicU64 = AtomicU64::new(0);
static MODULE_LOAD_TIME_NS: AtomicU64 = AtomicU64::new(0);

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

fn fixed_eye_values(values: Vec<u32>, name: &str) -> PyResult<[u32; A1_EYE_COUNT]> {
    values.try_into().map_err(|values: Vec<u32>| {
        PyValueError::new_err(format!(
            "{name} must contain exactly {A1_EYE_COUNT} values; got {}.",
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

fn set_a1_directive(
    dict: &Bound<'_, PyDict>,
    directive: &AttentionRegionPlanDirective,
) -> PyResult<()> {
    dict.set_item("abi_version", directive.abi_version)?;
    dict.set_item("struct_size", directive.struct_size)?;
    dict.set_item("decision_code", directive.decision_code)?;
    dict.set_item("reason_code", directive.reason_code)?;
    dict.set_item("target_step", directive.target_step)?;
    dict.set_item("stable_region_mask", directive.stable_region_mask)?;
    dict.set_item(
        "full_compute_region_mask",
        directive.full_compute_region_mask,
    )?;
    dict.set_item("refresh_region_mask", directive.refresh_region_mask)?;
    dict.set_item("fallback_required", directive.fallback_required)?;
    dict.set_item("unsupported_flags", directive.unsupported_flags)?;
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
    Ok(())
}

/// Compile one ready C2 observation into a metadata-only A1 region plan.
/// Model-specific token-row mapping remains outside Rust.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn evaluate_attention_region_plan<'py>(
    py: Python<'py>,
    abi_version: u32,
    struct_size: u32,
    run_digest: &Bound<'py, PyBytes>,
    workflow_revision_digest: &Bound<'py, PyBytes>,
    settings_digest: &Bound<'py, PyBytes>,
    model_revision_digest: &Bound<'py, PyBytes>,
    observed_step: u32,
    predicted_execution_step: u32,
    total_steps: u32,
    topology_id: u32,
    eye_state: Vec<u32>,
    eye_confidence_ppm: Vec<u32>,
    eye_change_ppm: Vec<u32>,
    stable_mask: u32,
    stable_count: u32,
    active_mask: u32,
    active_count: u32,
    uncertain_mask: u32,
    uncertain_count: u32,
    global_invalidation: bool,
    overlap_conflict_mask: u32,
    anchor_step: bool,
    cooldown_mask: u32,
    refresh_required_mask: u32,
    source_valid: bool,
    prediction_valid: bool,
    selective_supported: bool,
    fallback_supported: bool,
    fatal_flags: u32,
    unsupported_flags: u32,
) -> PyResult<Bound<'py, PyDict>> {
    let observation = AttentionRegionPlanObservation {
        abi_version,
        struct_size,
        run_digest: fixed_digest(run_digest, "run_digest")?,
        workflow_revision_digest: fixed_digest(
            workflow_revision_digest,
            "workflow_revision_digest",
        )?,
        settings_digest: fixed_digest(settings_digest, "settings_digest")?,
        model_revision_digest: fixed_digest(model_revision_digest, "model_revision_digest")?,
        observed_step,
        predicted_execution_step,
        total_steps,
        topology_id,
        eye_state: fixed_eye_values(eye_state, "eye_state")?,
        eye_confidence_ppm: fixed_eye_values(eye_confidence_ppm, "eye_confidence_ppm")?,
        eye_change_ppm: fixed_eye_values(eye_change_ppm, "eye_change_ppm")?,
        stable_mask,
        stable_count,
        active_mask,
        active_count,
        uncertain_mask,
        uncertain_count,
        global_invalidation: u32::from(global_invalidation),
        overlap_conflict_mask,
        anchor_step: u32::from(anchor_step),
        cooldown_mask,
        refresh_required_mask,
        source_valid: u32::from(source_valid),
        prediction_valid: u32::from(prediction_valid),
        selective_supported: u32::from(selective_supported),
        fallback_supported: u32::from(fallback_supported),
        fatal_flags,
        unsupported_flags,
    };
    let started = Instant::now();
    let evaluated = catch_unwind(AssertUnwindSafe(|| {
        evaluate_attention_region_plan_core(&observation)
    }));
    let rust_policy_ns = started.elapsed().as_nanos();
    let result = PyDict::new(py);
    match evaluated {
        Ok(directive) => {
            result.set_item("ffi_status", 0)?;
            set_a1_directive(&result, &directive)?;
        }
        Err(_) => {
            result.set_item("ffi_status", 1)?;
            set_a1_directive(
                &result,
                &AttentionRegionPlanDirective::fail_open(
                    A1_REASON_RUST_PANIC,
                    predicted_execution_step,
                ),
            )?;
        }
    }
    result.set_item("rust_policy_ns", rust_policy_ns)?;
    Ok(result)
}

#[pyfunction]
fn attention_region_plan_contract<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("abi_version", A1_ATTENTION_REGION_PLAN_ABI_VERSION)?;
    result.set_item(
        "observation_struct_size",
        AttentionRegionPlanObservation::contract_size(),
    )?;
    result.set_item(
        "directive_struct_size",
        AttentionRegionPlanDirective::contract_size(),
    )?;
    result.set_item("eye_count", A1_EYE_COUNT)?;
    result.set_item("region_count", A1_REGION_COUNT)?;
    result.set_item("max_rust_calls_per_ready_observation", 1)?;
    result.set_item("max_rust_calls_per_block", 0)?;
    result.set_item("max_rust_calls_per_token", 0)?;
    result.set_item("tensor_bytes_per_call", 0)?;
    result.set_item("prediction_horizon_steps", 2)?;
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

fn set_correction_plan_directive(
    dict: &Bound<'_, PyDict>,
    directive: &CorrectionPlanDirective,
) -> PyResult<()> {
    dict.set_item("abi_version", directive.abi_version)?;
    dict.set_item("struct_size", directive.struct_size)?;
    dict.set_item("decision_code", directive.decision_code)?;
    dict.set_item("reason_code", directive.reason_code)?;
    dict.set_item("target_execution_step", directive.target_execution_step)?;
    dict.set_item(
        "first_source_execution_step",
        directive.first_source_execution_step,
    )?;
    dict.set_item(
        "second_source_execution_step",
        directive.second_source_execution_step,
    )?;
    dict.set_item("fallback_required", directive.fallback_required)?;
    dict.set_item("unsupported_flags", directive.unsupported_flags)?;
    dict.set_item(
        "decision_digest",
        PyBytes::new(dict.py(), &directive.decision_digest),
    )?;
    Ok(())
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn evaluate_correction_plan<'py>(
    py: Python<'py>,
    abi_version: u32,
    struct_size: u32,
    run_digest: &Bound<'py, PyBytes>,
    workflow_revision_digest: &Bound<'py, PyBytes>,
    settings_digest: &Bound<'py, PyBytes>,
    model_revision_digest: &Bound<'py, PyBytes>,
    segment_logical_digest: &Bound<'py, PyBytes>,
    target_execution_step: u32,
    first_source_execution_step: u32,
    second_source_execution_step: u32,
    total_steps: u32,
    cache_available: bool,
    predictor_available: bool,
    predictor_provenance_valid: bool,
    corrected_similarity_admitted: bool,
    correction_metadata_valid: bool,
    calibrated_target: bool,
    full_compute_seed_count: u32,
    reseed_required: bool,
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
    let observation = CorrectionPlanObservation {
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
        first_source_execution_step,
        second_source_execution_step,
        total_steps,
        cache_available: u32::from(cache_available),
        predictor_available: u32::from(predictor_available),
        predictor_provenance_valid: u32::from(predictor_provenance_valid),
        corrected_similarity_admitted: u32::from(corrected_similarity_admitted),
        correction_metadata_valid: u32::from(correction_metadata_valid),
        calibrated_target: u32::from(calibrated_target),
        full_compute_seed_count,
        reseed_required: u32::from(reseed_required),
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
    let evaluated = catch_unwind(AssertUnwindSafe(|| {
        evaluate_correction_plan_core(&observation)
    }));
    let rust_policy_ns = started.elapsed().as_nanos();
    let result = PyDict::new(py);
    match evaluated {
        Ok(directive) => {
            result.set_item("ffi_status", 0)?;
            set_correction_plan_directive(&result, &directive)?;
        }
        Err(_) => {
            result.set_item("ffi_status", 1)?;
            set_correction_plan_directive(
                &result,
                &CorrectionPlanDirective::fail_open(
                    C3_R3_REASON_RUST_PANIC,
                    target_execution_step,
                    first_source_execution_step,
                    second_source_execution_step,
                    [0; 32],
                ),
            )?;
        }
    }
    result.set_item("rust_policy_ns", rust_policy_ns)?;
    Ok(result)
}

#[pyfunction]
fn correction_plan_contract<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("abi_version", C3_R3_CORRECTION_PLAN_ABI_VERSION)?;
    result.set_item(
        "observation_struct_size",
        CorrectionPlanObservation::contract_size(),
    )?;
    result.set_item(
        "directive_struct_size",
        CorrectionPlanDirective::contract_size(),
    )?;
    result.set_item("max_rust_calls_per_callback", 1)?;
    result.set_item("max_rust_calls_per_block", 0)?;
    result.set_item("tensor_bytes_per_call", 0)?;
    result.set_item("full_compute_seeds_required", 2)?;
    Ok(result)
}

fn required_item<'py>(dict: &Bound<'py, PyDict>, name: &str) -> PyResult<Bound<'py, PyAny>> {
    dict.get_item(name)?
        .ok_or_else(|| PyValueError::new_err(format!("missing required field: {name}")))
}

fn dict_u32(dict: &Bound<'_, PyDict>, name: &str) -> PyResult<u32> {
    required_item(dict, name)?.extract::<u32>()
}

fn dict_i32(dict: &Bound<'_, PyDict>, name: &str) -> PyResult<i32> {
    required_item(dict, name)?.extract::<i32>()
}

fn dict_u64(dict: &Bound<'_, PyDict>, name: &str) -> PyResult<u64> {
    required_item(dict, name)?.extract::<u64>()
}

fn dict_digest(dict: &Bound<'_, PyDict>, name: &str) -> PyResult<[u8; 32]> {
    let value = required_item(dict, name)?;
    let bytes = value
        .cast::<PyBytes>()
        .map_err(|_| PyTypeError::new_err(format!("{name} must be bytes")))?;
    fixed_digest(bytes, name)
}

fn parse_cache_plan_request(dict: &Bound<'_, PyDict>) -> PyResult<GenerationCachePlanRequest> {
    Ok(GenerationCachePlanRequest {
        abi_version: dict_u32(dict, "abi_version")?,
        struct_size: dict_u32(dict, "struct_size")?,
        contract_version: dict_u32(dict, "contract_version")?,
        overflow_policy: dict_u32(dict, "overflow_policy")?,
        generation_id: dict_u64(dict, "generation_id")?,
        current_step: dict_u32(dict, "current_step")?,
        maximum_batch_records: dict_u32(dict, "maximum_batch_records")?,
        maximum_batch_bytes: dict_u64(dict, "maximum_batch_bytes")?,
        total_full_q_rows: dict_u64(dict, "total_full_q_rows")?,
        unsupported_flags: dict_u32(dict, "unsupported_flags")?,
    })
}

fn parse_generation_identity(dict: &Bound<'_, PyDict>) -> PyResult<GenerationIdentityV2> {
    Ok(GenerationIdentityV2 {
        run_digest: dict_digest(dict, "run_digest")?,
        workflow_digest: dict_digest(dict, "workflow_digest")?,
        model_digest: dict_digest(dict, "model_digest")?,
        model_revision_digest: dict_digest(dict, "model_revision_digest")?,
        settings_digest: dict_digest(dict, "settings_digest")?,
        source_plan_digest: dict_digest(dict, "source_plan_digest")?,
        layout_digest: dict_digest(dict, "layout_digest")?,
        input_identity_digest: dict_digest(dict, "input_identity_digest")?,
        generation_id: dict_u64(dict, "generation_id")?,
        scheduler_id: dict_u32(dict, "scheduler_id")?,
        total_steps: dict_u32(dict, "total_steps")?,
        width: dict_u32(dict, "width")?,
        height: dict_u32(dict, "height")?,
        frame_count: dict_u32(dict, "frame_count")?,
        fps_numerator: dict_u32(dict, "fps_numerator")?,
        fps_denominator: dict_u32(dict, "fps_denominator")?,
    })
}

fn parse_hardware_profile(dict: &Bound<'_, PyDict>) -> PyResult<HardwareProfileV2> {
    Ok(HardwareProfileV2 {
        abi_version: dict_u32(dict, "abi_version")?,
        struct_size: dict_u32(dict, "struct_size")?,
        profile_id: dict_u32(dict, "profile_id")?,
        precision: dict_u32(dict, "precision")?,
        quantization: dict_u32(dict, "quantization")?,
        offload_policy: dict_u32(dict, "offload_policy")?,
        resolution_class: dict_u32(dict, "resolution_class")?,
        cache_age: dict_u32(dict, "cache_age")?,
        vram_budget_bytes: dict_u64(dict, "vram_budget_bytes")?,
        host_cache_budget_bytes: dict_u64(dict, "host_cache_budget_bytes")?,
        gpu_staging_budget_bytes: dict_u64(dict, "gpu_staging_budget_bytes")?,
        minimum_reserve_bytes: dict_u64(dict, "minimum_reserve_bytes")?,
        maximum_transfer_bytes: dict_u64(dict, "maximum_transfer_bytes")?,
        maximum_candidates: dict_u32(dict, "maximum_candidates")?,
        maximum_selected_regions: dict_u32(dict, "maximum_selected_regions")?,
        maximum_batch_bytes: dict_u64(dict, "maximum_batch_bytes")?,
        maximum_work_units: dict_u32(dict, "maximum_work_units")?,
        resolution_width: dict_u32(dict, "resolution_width")?,
        resolution_height: dict_u32(dict, "resolution_height")?,
        frame_budget: dict_u32(dict, "frame_budget")?,
    })
}

fn parse_batch_header(dict: &Bound<'_, PyDict>) -> PyResult<GenerationEvidenceBatchHeader> {
    Ok(GenerationEvidenceBatchHeader {
        abi_version: dict_u32(dict, "abi_version")?,
        struct_size: dict_u32(dict, "struct_size")?,
        generation_id: dict_u64(dict, "generation_id")?,
        record_count: dict_u32(dict, "record_count")?,
        maximum_records: dict_u32(dict, "maximum_records")?,
        batch_bytes: dict_u64(dict, "batch_bytes")?,
        overflowed: dict_u32(dict, "overflowed")?,
        truncated: dict_u32(dict, "truncated")?,
        tensor_bytes: dict_u64(dict, "tensor_bytes")?,
        unsupported_flags: dict_u32(dict, "unsupported_flags")?,
    })
}

fn parse_cache_candidate(dict: &Bound<'_, PyDict>) -> PyResult<CacheCandidateV2> {
    Ok(CacheCandidateV2 {
        target_step: dict_u32(dict, "target_step")?,
        source_step: dict_u32(dict, "source_step")?,
        block_index: dict_u32(dict, "block_index")?,
        region: dict_u32(dict, "region")?,
        packed_row_start: dict_u32(dict, "packed_row_start")?,
        packed_row_count: dict_u32(dict, "packed_row_count")?,
        state: dict_u32(dict, "state")?,
        actual_safety_state: dict_u32(dict, "actual_safety_state")?,
        safety_evidence_present: dict_u32(dict, "safety_evidence_present")?,
        uncertainty_ppm: dict_u32(dict, "uncertainty_ppm")?,
        motion_ppm: dict_u32(dict, "motion_ppm")?,
        cosine_ppm: dict_i32(dict, "cosine_ppm")?,
        corrected_nl2_ppm: dict_u32(dict, "corrected_nl2_ppm")?,
        false_safe_count: dict_u32(dict, "false_safe_count")?,
        nonfinite_count: dict_u32(dict, "nonfinite_count")?,
        cache_age: dict_u32(dict, "cache_age")?,
        source_kind: dict_u32(dict, "source_kind")?,
        shape_rows: dict_u32(dict, "shape_rows")?,
        shape_width: dict_u32(dict, "shape_width")?,
        dtype: dict_u32(dict, "dtype")?,
        device_class: dict_u32(dict, "device_class")?,
        precision: dict_u32(dict, "precision")?,
        quantization: dict_u32(dict, "quantization")?,
        admission_eligible: dict_u32(dict, "admission_eligible")?,
        rejection_reason: dict_u32(dict, "rejection_reason")?,
        planned_q_rows: dict_u64(dict, "planned_q_rows")?,
        full_q_rows: dict_u64(dict, "full_q_rows")?,
        payload_bytes: dict_u64(dict, "payload_bytes")?,
        effect_numerator: dict_u64(dict, "effect_numerator")?,
        effect_denominator: dict_u64(dict, "effect_denominator")?,
        planned_d2h_bytes: dict_u64(dict, "planned_d2h_bytes")?,
        planned_h2d_bytes: dict_u64(dict, "planned_h2d_bytes")?,
        shape_digest: dict_digest(dict, "shape_digest")?,
        packed_row_digest: dict_digest(dict, "packed_row_digest")?,
        lineage_digest: dict_digest(dict, "lineage_digest")?,
    })
}

fn parse_inventory_entry(dict: &Bound<'_, PyDict>) -> PyResult<CacheInventoryEntryV2> {
    Ok(CacheInventoryEntryV2 {
        block_index: dict_u32(dict, "block_index")?,
        region: dict_u32(dict, "region")?,
        source_step: dict_u32(dict, "source_step")?,
        cache_age: dict_u32(dict, "cache_age")?,
        valid: dict_u32(dict, "valid")?,
        payload_bytes: dict_u64(dict, "payload_bytes")?,
        planned_q_rows: dict_u64(dict, "planned_q_rows")?,
        lineage_digest: dict_digest(dict, "lineage_digest")?,
    })
}

fn parse_dict_list<T>(
    values: &Bound<'_, PyList>,
    parser: impl Fn(&Bound<'_, PyDict>) -> PyResult<T>,
) -> PyResult<Vec<T>> {
    values
        .iter()
        .map(|value| {
            let dict = value
                .cast::<PyDict>()
                .map_err(|_| PyTypeError::new_err("batch records must be dictionaries"))?;
            parser(dict)
        })
        .collect()
}

fn metric_status_label(status: u32) -> &'static str {
    match status {
        1 => "MEASURED",
        2 => "STRUCTURAL_ZERO",
        3 => "UNKNOWN",
        4 => "NOT_EXECUTED",
        _ => "INVALID",
    }
}

fn set_receipt_metric(
    parent: &Bound<'_, PyDict>,
    name: &str,
    metric: ReceiptMetricU64,
) -> PyResult<()> {
    let item = PyDict::new(parent.py());
    match metric.value {
        Some(value) => item.set_item("value", value)?,
        None => item.set_item("value", parent.py().None())?,
    }
    item.set_item("status", metric_status_label(metric.status))?;
    parent.set_item(name, item)
}

fn performance_receipt_dict<'py>(
    py: Python<'py>,
    receipt: &CachePlanPerformanceReceiptV2,
) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    for (name, metric) in [
        ("rust_module_load_count", receipt.rust_module_load_count),
        ("rust_module_load_time_ns", receipt.rust_module_load_time_ns),
        ("rust_process_spawn_count", receipt.rust_process_spawn_count),
        ("calls_per_generation", receipt.calls_per_generation),
        ("calls_per_step", receipt.calls_per_step),
        ("calls_per_block", receipt.calls_per_block),
        ("calls_per_region", receipt.calls_per_region),
        ("calls_per_row", receipt.calls_per_row),
        ("evidence_record_count", receipt.evidence_record_count),
        ("evidence_batch_bytes", receipt.evidence_batch_bytes),
        ("pyo3_conversion_time_ns", receipt.pyo3_conversion_time_ns),
        ("rust_plan_time_ns", receipt.rust_plan_time_ns),
        ("ffi_total_time_ns", receipt.ffi_total_time_ns),
        ("serialization_time_ns", receipt.serialization_time_ns),
        ("rust_transfer_bytes", receipt.rust_transfer_bytes),
        (
            "gpu_to_cpu_metadata_bytes",
            receipt.gpu_to_cpu_metadata_bytes,
        ),
        ("gpu_to_cpu_tensor_bytes", receipt.gpu_to_cpu_tensor_bytes),
        (
            "cpu_to_gpu_metadata_bytes",
            receipt.cpu_to_gpu_metadata_bytes,
        ),
        ("cpu_to_gpu_tensor_bytes", receipt.cpu_to_gpu_tensor_bytes),
        ("cuda_sync_count", receipt.cuda_sync_count),
        ("selected_payload_bytes", receipt.selected_payload_bytes),
        ("planned_d2h_bytes", receipt.planned_d2h_bytes),
        ("planned_h2d_bytes", receipt.planned_h2d_bytes),
        ("actual_d2h_bytes", receipt.actual_d2h_bytes),
        ("actual_h2d_bytes", receipt.actual_h2d_bytes),
        ("d2h_estimate_error_bytes", receipt.d2h_estimate_error_bytes),
        ("h2d_estimate_error_bytes", receipt.h2d_estimate_error_bytes),
        ("fallback_count", receipt.fallback_count),
        (
            "partial_full_recovery_count",
            receipt.partial_full_recovery_count,
        ),
        ("rust_overhead_ratio_ppm", receipt.rust_overhead_ratio_ppm),
    ] {
        set_receipt_metric(&result, name, metric)?;
    }
    Ok(result)
}

fn cache_plan_result<'py>(
    py: Python<'py>,
    plan: &GenerationCachePlanV2,
    ffi_status: u32,
) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("ffi_status", ffi_status)?;
    result.set_item("abi_version", plan.abi_version)?;
    result.set_item("decision_code", plan.decision_code)?;
    result.set_item("reason_code", plan.reason_code)?;
    result.set_item("fallback_required", plan.fallback_required)?;
    result.set_item("total_selected_bytes", plan.total_selected_bytes)?;
    result.set_item("total_planned_q_rows", plan.total_planned_q_rows)?;
    result.set_item("total_full_q_rows", plan.total_full_q_rows)?;
    result.set_item("planned_reduction_ppm", plan.planned_reduction_ppm)?;
    result.set_item("total_planned_d2h_bytes", plan.total_planned_d2h_bytes)?;
    result.set_item("total_planned_h2d_bytes", plan.total_planned_h2d_bytes)?;
    result.set_item("plan_digest", PyBytes::new(py, &plan.plan_digest))?;
    result.set_item("lineage_digest", PyBytes::new(py, &plan.lineage_digest))?;

    let selected = PyList::empty(py);
    for item in &plan.selected {
        let row = PyDict::new(py);
        row.set_item("block_index", item.block_index)?;
        row.set_item("region", item.region)?;
        row.set_item("payload_bytes", item.payload_bytes)?;
        row.set_item("planned_q_rows", item.planned_q_rows)?;
        row.set_item("planned_d2h_bytes", item.planned_d2h_bytes)?;
        row.set_item("planned_h2d_bytes", item.planned_h2d_bytes)?;
        row.set_item("effect_numerator", item.effect_numerator)?;
        row.set_item("effect_denominator", item.effect_denominator)?;
        row.set_item("transfer_effect_numerator", item.transfer_effect_numerator)?;
        row.set_item(
            "transfer_effect_denominator",
            item.transfer_effect_denominator,
        )?;
        row.set_item(
            "selection_lineage_digest",
            PyBytes::new(py, &item.selection_lineage_digest),
        )?;
        selected.append(row)?;
    }
    result.set_item("selected", selected)?;

    let rejected = PyList::empty(py);
    for item in &plan.rejected {
        let row = PyDict::new(py);
        row.set_item("block_index", item.block_index)?;
        row.set_item("region", item.region)?;
        row.set_item("reason_code", item.reason_code)?;
        rejected.append(row)?;
    }
    result.set_item("rejected", rejected)?;

    let evictions = PyList::empty(py);
    for item in &plan.eviction_order {
        let row = PyDict::new(py);
        row.set_item("block_index", item.block_index)?;
        row.set_item("region", item.region)?;
        row.set_item("reason_code", item.reason_code)?;
        evictions.append(row)?;
    }
    result.set_item("eviction_order", evictions)?;
    result.set_item(
        "performance_receipt",
        performance_receipt_dict(py, &plan.receipt)?,
    )?;
    Ok(result)
}

fn profile_dict<'py>(py: Python<'py>, profile: &HardwareProfileV2) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("abi_version", profile.abi_version)?;
    result.set_item("struct_size", profile.struct_size)?;
    result.set_item("profile_id", profile.profile_id)?;
    result.set_item("precision", profile.precision)?;
    result.set_item("quantization", profile.quantization)?;
    result.set_item("offload_policy", profile.offload_policy)?;
    result.set_item("resolution_class", profile.resolution_class)?;
    result.set_item("cache_age", profile.cache_age)?;
    result.set_item("vram_budget_bytes", profile.vram_budget_bytes)?;
    result.set_item("host_cache_budget_bytes", profile.host_cache_budget_bytes)?;
    result.set_item("gpu_staging_budget_bytes", profile.gpu_staging_budget_bytes)?;
    result.set_item("minimum_reserve_bytes", profile.minimum_reserve_bytes)?;
    result.set_item("maximum_transfer_bytes", profile.maximum_transfer_bytes)?;
    result.set_item("maximum_candidates", profile.maximum_candidates)?;
    result.set_item("maximum_selected_regions", profile.maximum_selected_regions)?;
    result.set_item("maximum_batch_bytes", profile.maximum_batch_bytes)?;
    result.set_item("maximum_work_units", profile.maximum_work_units)?;
    result.set_item("resolution_width", profile.resolution_width)?;
    result.set_item("resolution_height", profile.resolution_height)?;
    result.set_item("frame_budget", profile.frame_budget)?;
    Ok(result)
}

#[pyfunction]
fn cache_plan_v2_contract<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("abi_version", CACHE_PLAN_ABI_V2_VERSION)?;
    result.set_item("contract_version", CACHE_PLAN_V2_CONTRACT_VERSION)?;
    result.set_item(
        "request_struct_size",
        GenerationCachePlanRequest::contract_size(),
    )?;
    result.set_item(
        "identity_struct_size",
        GenerationIdentityV2::contract_size(),
    )?;
    result.set_item("profile_struct_size", HardwareProfileV2::contract_size())?;
    result.set_item(
        "batch_header_struct_size",
        GenerationEvidenceBatchHeader::contract_size(),
    )?;
    result.set_item("candidate_struct_size", CacheCandidateV2::contract_size())?;
    result.set_item(
        "inventory_struct_size",
        CacheInventoryEntryV2::contract_size(),
    )?;
    result.set_item("maximum_records", CACHE_PLAN_V2_MAX_RECORDS)?;
    result.set_item("maximum_inventory_records", CACHE_PLAN_V2_MAX_INVENTORY)?;
    result.set_item("maximum_batch_bytes", CACHE_PLAN_V2_MAX_BATCH_BYTES)?;
    result.set_item("tensor_bytes_per_call", 0)?;
    result.set_item("maximum_calls_per_generation", 1)?;
    result.set_item("maximum_calls_per_step", 0)?;
    result.set_item("maximum_calls_per_block", 0)?;
    result.set_item("maximum_calls_per_region", 0)?;
    result.set_item("maximum_calls_per_row", 0)?;
    result.set_item(
        "balanced_12gb",
        profile_dict(py, &HardwareProfileV2::balanced_12gb())?,
    )?;
    result.set_item(
        "quality_24gb_plus",
        profile_dict(py, &HardwareProfileV2::quality_24gb_plus())?,
    )?;
    Ok(result)
}

#[pyfunction]
fn compile_cache_plan_v2<'py>(
    py: Python<'py>,
    request: &Bound<'py, PyDict>,
    identity: &Bound<'py, PyDict>,
    profile: &Bound<'py, PyDict>,
    batch_header: &Bound<'py, PyDict>,
    candidates: &Bound<'py, PyList>,
    inventory: &Bound<'py, PyList>,
) -> PyResult<Bound<'py, PyDict>> {
    let ffi_started = Instant::now();
    let conversion_started = Instant::now();
    let parsed = (|| -> PyResult<_> {
        let request = parse_cache_plan_request(request)?;
        let identity = parse_generation_identity(identity)?;
        let profile = parse_hardware_profile(profile)?;
        let header = parse_batch_header(batch_header)?;
        let records = parse_dict_list(candidates, parse_cache_candidate)?;
        let inventory = parse_dict_list(inventory, parse_inventory_entry)?;
        Ok((
            request,
            identity,
            profile,
            GenerationEvidenceBatchV2 { header, records },
            inventory,
        ))
    })();
    let conversion_ns = conversion_started.elapsed().as_nanos() as u64;
    let plan_started = Instant::now();
    let (mut plan, ffi_status) = match parsed {
        Ok((request, identity, profile, batch, inventory)) => {
            match catch_unwind(AssertUnwindSafe(|| {
                compile_cache_plan_v2_core(&request, &identity, &profile, &batch, &inventory)
            })) {
                Ok(plan) => (plan, 0),
                Err(_) => (fail_open_cache_plan_v2(CACHE_PLAN_V2_REASON_RUST_PANIC), 1),
            }
        }
        Err(_) => (
            fail_open_cache_plan_v2(CACHE_PLAN_V2_REASON_BATCH_MALFORMED),
            1,
        ),
    };
    let plan_ns = plan_started.elapsed().as_nanos() as u64;
    plan.receipt.rust_module_load_count =
        ReceiptMetricU64::measured(MODULE_LOAD_COUNT.load(Ordering::Relaxed));
    plan.receipt.rust_module_load_time_ns =
        ReceiptMetricU64::measured(MODULE_LOAD_TIME_NS.load(Ordering::Relaxed));
    plan.receipt.pyo3_conversion_time_ns = ReceiptMetricU64::measured(conversion_ns);
    plan.receipt.rust_plan_time_ns = ReceiptMetricU64::measured(plan_ns);
    plan.receipt.ffi_total_time_ns =
        ReceiptMetricU64::measured(ffi_started.elapsed().as_nanos() as u64);
    cache_plan_result(py, &plan, ffi_status)
}

#[pyfunction]
fn cache_plan_v2_panic_boundary_probe<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
    let evaluated = catch_unwind(AssertUnwindSafe(|| panic!("cache plan V2 panic probe")));
    let plan = match evaluated {
        Ok(()) => fail_open_cache_plan_v2(CACHE_PLAN_V2_REASON_BATCH_MALFORMED),
        Err(_) => fail_open_cache_plan_v2(CACHE_PLAN_V2_REASON_RUST_PANIC),
    };
    cache_plan_result(py, &plan, 1)
}

#[pymodule]
fn _hive_retina_boundary(module: &Bound<'_, PyModule>) -> PyResult<()> {
    let load_started = Instant::now();
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
    module.add_function(wrap_pyfunction!(evaluate_attention_region_plan, module)?)?;
    module.add_function(wrap_pyfunction!(attention_region_plan_contract, module)?)?;
    module.add_function(wrap_pyfunction!(evaluate_c3_frozen_block_plan, module)?)?;
    module.add_function(wrap_pyfunction!(c3_frozen_block_plan_contract, module)?)?;
    module.add_function(wrap_pyfunction!(evaluate_reuse_plan, module)?)?;
    module.add_function(wrap_pyfunction!(reuse_plan_contract, module)?)?;
    module.add_function(wrap_pyfunction!(evaluate_correction_plan, module)?)?;
    module.add_function(wrap_pyfunction!(correction_plan_contract, module)?)?;
    module.add_function(wrap_pyfunction!(compile_cache_plan_v2, module)?)?;
    module.add_function(wrap_pyfunction!(cache_plan_v2_contract, module)?)?;
    module.add_function(wrap_pyfunction!(
        cache_plan_v2_panic_boundary_probe,
        module
    )?)?;
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    module.add("pyo3_version", "0.29.0")?;
    module.add("python_abi", "abi3-py312")?;
    MODULE_LOAD_COUNT.fetch_add(1, Ordering::Relaxed);
    MODULE_LOAD_TIME_NS.store(load_started.elapsed().as_nanos() as u64, Ordering::Relaxed);
    Ok(())
}
