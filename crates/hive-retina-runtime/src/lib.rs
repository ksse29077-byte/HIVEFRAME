#![doc = "Model-free Compound I/O routing, fusion, planning, and admission evidence."]

pub mod cache_plan_v2;
pub mod locality;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::hint::black_box;
use std::time::Instant;

pub const SCHEMA_VERSION: &str = "0.1.0";
pub const RUN_KIND: &str = "rust_io_admission_probe";
pub const TOPOLOGIES: [&str; 5] = [
    "mono_1x1",
    "uniform_2x2",
    "uniform_4x4",
    "overlap_2x2",
    "motion_focused",
];

pub const C1_STEP_POLICY_ABI_VERSION: u32 = 1;
pub const C1_DECISION_FULL_COMPUTE: u32 = 0;
pub const C1_DECISION_ESCALATE_FULL_COMPUTE: u32 = 1;
pub const C1_REASON_NONE: u32 = 0;
pub const C1_REASON_ABI_MISMATCH: u32 = 1;
pub const C1_REASON_STRUCT_SIZE_MISMATCH: u32 = 2;
pub const C1_REASON_STEP_RANGE_INVALID: u32 = 3;
pub const C1_REASON_DIGEST_MISSING: u32 = 4;
pub const C1_REASON_FULL_COMPUTE_UNSUPPORTED: u32 = 5;
pub const C1_REASON_UNCERTAINTY_PRESENT: u32 = 6;
pub const C1_REASON_INVALIDATION_PRESENT: u32 = 7;
pub const C1_REASON_UNSUPPORTED_METADATA: u32 = 8;
pub const C1_REASON_FALLBACK_UNSUPPORTED: u32 = 9;
pub const C1_REASON_RUST_PANIC: u32 = 10;

pub const C2_COMPOUND_EYE_SHADOW_ABI_VERSION: u32 = 1;
pub const C2_TOPOLOGY_OVERLAP_2X2: u32 = 1;
pub const C2_SKETCH_SOURCE_X0: u32 = 1;
pub const C2_SKETCH_VALUE_COUNT: usize = 48;
pub const C2_EYE_COUNT: usize = 5;
pub const C2_EYE_STATE_STABLE: u32 = 0;
pub const C2_EYE_STATE_ACTIVE: u32 = 1;
pub const C2_EYE_STATE_UNCERTAIN: u32 = 2;
pub const C2_DECISION_FULL_COMPUTE: u32 = 0;
pub const C2_DECISION_ESCALATE_FULL_COMPUTE: u32 = 1;
pub const C2_REASON_NONE: u32 = 0;
pub const C2_REASON_ABI_MISMATCH: u32 = 1;
pub const C2_REASON_STRUCT_SIZE_MISMATCH: u32 = 2;
pub const C2_REASON_STEP_RANGE_INVALID: u32 = 3;
pub const C2_REASON_DIGEST_MISSING: u32 = 4;
pub const C2_REASON_TOPOLOGY_UNSUPPORTED: u32 = 5;
pub const C2_REASON_SKETCH_UNSUPPORTED: u32 = 6;
pub const C2_REASON_QUANTIZATION_INVALID: u32 = 7;
pub const C2_REASON_FULL_COMPUTE_UNSUPPORTED: u32 = 8;
pub const C2_REASON_FALLBACK_UNSUPPORTED: u32 = 9;
pub const C2_REASON_UNSUPPORTED_METADATA: u32 = 10;
pub const C2_REASON_RUST_PANIC: u32 = 11;

/// Predeclared fixed-point thresholds. Values are parts per million of the
/// previous quantized sketch magnitude and are not adjusted after a run.
pub const C2_STABLE_DELTA_LIMIT_PPM: u32 = 20_000;
pub const C2_ACTIVE_DELTA_LIMIT_PPM: u32 = 80_000;
pub const C2_GLOBAL_INVALIDATION_LIMIT_PPM: u32 = 150_000;
pub const C2_STABLE_VALIDATION_LIMIT_PPM: u32 = 30_000;
pub const C2_LOCAL_TO_GLOBAL_LIMIT_PPM: u32 = 950_000;
pub const C2_MIN_WARMUP_CALLBACKS: u32 = 2;

pub const C3_R1_BLOCK_PLAN_ABI_VERSION: u32 = 1;
pub const C3_R1_TOTAL_STEPS: u32 = 20;
pub const C3_R1_BLOCK_COUNT: u32 = 50;
pub const C3_R1_FROZEN_SCHEDULE: [u32; 6] = [5, 6, 8, 13, 16, 17];
pub const C3_R1_CANDIDATE_BLOCK_START: u32 = 12;
pub const C3_R1_CANDIDATE_BLOCK_END: u32 = 48;
pub const C3_R1_CANDIDATE_BLOCK_COUNT: u32 = 37;
pub const C3_R1_CANDIDATE_BLOCK_MASK: u64 = (1_u64 << 49) - (1_u64 << 12);
pub const C3_R1_DECISION_FULL_COMPUTE: u32 = 0;
pub const C3_R1_DECISION_SELECTIVE_BLOCK_BYPASS: u32 = 1;
pub const C3_R1_DECISION_ESCALATE_FULL_COMPUTE: u32 = 2;
pub const C3_R1_REASON_NONE: u32 = 0;
pub const C3_R1_REASON_ABI_MISMATCH: u32 = 1;
pub const C3_R1_REASON_STRUCT_SIZE_MISMATCH: u32 = 2;
pub const C3_R1_REASON_STEP_RANGE_INVALID: u32 = 3;
pub const C3_R1_REASON_DIGEST_MISSING: u32 = 4;
pub const C3_R1_REASON_EXECUTION_CONTRACT_MISMATCH: u32 = 5;
pub const C3_R1_REASON_EYE_METADATA_INVALID: u32 = 6;
pub const C3_R1_REASON_SELECTIVE_UNSUPPORTED: u32 = 7;
pub const C3_R1_REASON_FALLBACK_UNSUPPORTED: u32 = 8;
pub const C3_R1_REASON_UNSUPPORTED_METADATA: u32 = 9;
pub const C3_R1_REASON_SCHEDULE_FLAG_MISMATCH: u32 = 10;
pub const C3_R1_REASON_NOT_FROZEN_TARGET: u32 = 11;
pub const C3_R1_REASON_SOURCE_INVALID: u32 = 12;
pub const C3_R1_REASON_PREDICTION_INVALID: u32 = 13;
pub const C3_R1_REASON_STABLE_COUNT_LOW: u32 = 14;
pub const C3_R1_REASON_ACTIVE_PRESENT: u32 = 15;
pub const C3_R1_REASON_GLOBAL_INVALIDATION: u32 = 16;
pub const C3_R1_REASON_OVERLAP_CONFLICT: u32 = 17;
pub const C3_R1_REASON_FATAL_FLAG: u32 = 18;
pub const C3_R1_REASON_RUST_PANIC: u32 = 19;

pub const C3_R2_REUSE_PLAN_ABI_VERSION: u32 = 1;
pub const C3_R2_DECISION_FULL_COMPUTE: u32 = 0;
pub const C3_R2_DECISION_REUSE_TRANSFORM: u32 = 1;
pub const C3_R2_DECISION_ESCALATE_FULL_COMPUTE: u32 = 2;
pub const C3_R2_REASON_NONE: u32 = 0;
pub const C3_R2_REASON_ABI_MISMATCH: u32 = 1;
pub const C3_R2_REASON_STRUCT_SIZE_MISMATCH: u32 = 2;
pub const C3_R2_REASON_STEP_RANGE_INVALID: u32 = 3;
pub const C3_R2_REASON_DIGEST_MISSING: u32 = 4;
pub const C3_R2_REASON_METADATA_INVALID: u32 = 5;
pub const C3_R2_REASON_NOT_CALIBRATED: u32 = 6;
pub const C3_R2_REASON_CACHE_MISSING: u32 = 7;
pub const C3_R2_REASON_CACHE_AGE_INVALID: u32 = 8;
pub const C3_R2_REASON_PROVENANCE_INVALID: u32 = 9;
pub const C3_R2_REASON_SIMILARITY_REJECTED: u32 = 10;
pub const C3_R2_REASON_SOURCE_INVALID: u32 = 11;
pub const C3_R2_REASON_PREDICTION_INVALID: u32 = 12;
pub const C3_R2_REASON_STABLE_COUNT_LOW: u32 = 13;
pub const C3_R2_REASON_ACTIVE_PRESENT: u32 = 14;
pub const C3_R2_REASON_GLOBAL_INVALIDATION: u32 = 15;
pub const C3_R2_REASON_OVERLAP_CONFLICT: u32 = 16;
pub const C3_R2_REASON_FATAL_FLAG: u32 = 17;
pub const C3_R2_REASON_CONSECUTIVE_REUSE: u32 = 18;
pub const C3_R2_REASON_FALLBACK_UNSUPPORTED: u32 = 19;
pub const C3_R2_REASON_UNSUPPORTED_METADATA: u32 = 20;
pub const C3_R2_REASON_RUST_PANIC: u32 = 21;

pub const C3_R3_CORRECTION_PLAN_ABI_VERSION: u32 = 1;
pub const C3_R3_DECISION_FULL_COMPUTE: u32 = 0;
pub const C3_R3_DECISION_REUSE_CORRECTED_TRANSFORM: u32 = 1;
pub const C3_R3_DECISION_ESCALATE_FULL_COMPUTE: u32 = 2;
pub const C3_R3_REASON_NONE: u32 = 0;
pub const C3_R3_REASON_ABI_MISMATCH: u32 = 1;
pub const C3_R3_REASON_STRUCT_SIZE_MISMATCH: u32 = 2;
pub const C3_R3_REASON_STEP_RANGE_INVALID: u32 = 3;
pub const C3_R3_REASON_DIGEST_MISSING: u32 = 4;
pub const C3_R3_REASON_METADATA_INVALID: u32 = 5;
pub const C3_R3_REASON_NOT_CALIBRATED: u32 = 6;
pub const C3_R3_REASON_CACHE_MISSING: u32 = 7;
pub const C3_R3_REASON_PREDICTOR_MISSING: u32 = 8;
pub const C3_R3_REASON_PROVENANCE_INVALID: u32 = 9;
pub const C3_R3_REASON_SIMILARITY_REJECTED: u32 = 10;
pub const C3_R3_REASON_SOURCE_INVALID: u32 = 11;
pub const C3_R3_REASON_PREDICTION_INVALID: u32 = 12;
pub const C3_R3_REASON_STABLE_COUNT_LOW: u32 = 13;
pub const C3_R3_REASON_ACTIVE_PRESENT: u32 = 14;
pub const C3_R3_REASON_GLOBAL_INVALIDATION: u32 = 15;
pub const C3_R3_REASON_OVERLAP_CONFLICT: u32 = 16;
pub const C3_R3_REASON_FATAL_FLAG: u32 = 17;
pub const C3_R3_REASON_RESEED_REQUIRED: u32 = 18;
pub const C3_R3_REASON_FALLBACK_UNSUPPORTED: u32 = 19;
pub const C3_R3_REASON_UNSUPPORTED_METADATA: u32 = 20;
pub const C3_R3_REASON_RUST_PANIC: u32 = 21;

pub const A1_ATTENTION_REGION_PLAN_ABI_VERSION: u32 = 1;
pub const A1_REGION_COUNT: usize = 4;
pub const A1_EYE_COUNT: usize = 5;
pub const A1_REGION_MASK: u32 = 0x0f;
pub const A1_DECISION_FULL_COMPUTE: u32 = 0;
pub const A1_DECISION_REGIONAL_ACTIVE_QUERY: u32 = 1;
pub const A1_DECISION_ESCALATE_FULL_COMPUTE: u32 = 2;
pub const A1_REASON_NONE: u32 = 0;
pub const A1_REASON_ABI_MISMATCH: u32 = 1;
pub const A1_REASON_STRUCT_SIZE_MISMATCH: u32 = 2;
pub const A1_REASON_STEP_RANGE_INVALID: u32 = 3;
pub const A1_REASON_DIGEST_MISSING: u32 = 4;
pub const A1_REASON_EYE_METADATA_INVALID: u32 = 5;
pub const A1_REASON_SOURCE_INVALID: u32 = 6;
pub const A1_REASON_PREDICTION_INVALID: u32 = 7;
pub const A1_REASON_GLOBAL_INVALIDATION: u32 = 8;
pub const A1_REASON_OVERLAP_CONFLICT: u32 = 9;
pub const A1_REASON_ANCHOR_STEP: u32 = 10;
pub const A1_REASON_REFRESH_REQUIRED: u32 = 11;
pub const A1_REASON_NO_STABLE_REGION: u32 = 12;
pub const A1_REASON_SELECTIVE_UNSUPPORTED: u32 = 13;
pub const A1_REASON_FALLBACK_UNSUPPORTED: u32 = 14;
pub const A1_REASON_FATAL_FLAG: u32 = 15;
pub const A1_REASON_UNSUPPORTED_METADATA: u32 = 16;
pub const A1_REASON_RUST_PANIC: u32 = 17;

/// Fixed-size, metadata-only callback observation for the C1 full-compute gate.
///
/// No tensor, prompt, filesystem path, media payload, CUDA pointer, model
/// weight, credential, or variable-length string is admitted by this contract.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct StepObservation {
    pub abi_version: u32,
    pub struct_size: u32,
    pub run_digest: [u8; 32],
    pub workflow_revision_digest: [u8; 32],
    pub settings_digest: [u8; 32],
    pub step_index: u32,
    pub total_steps: u32,
    pub sampler_logical_id: u32,
    pub scheduler_logical_id: u32,
    pub timestep_available: u32,
    pub timestep_bits: u64,
    pub sigma_available: u32,
    pub sigma_bits: u64,
    pub uncertainty_flags: u32,
    pub invalidation_flags: u32,
    pub full_compute_supported: u32,
    pub fallback_supported: u32,
    pub cache_available: u32,
    pub receipt_required: u32,
    pub unsupported_flags: u32,
}

impl StepObservation {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }
}

/// Fixed-size C1 directive. All skip/reuse/partial counters remain zero.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct StepDirective {
    pub abi_version: u32,
    pub struct_size: u32,
    pub decision_code: u32,
    pub reason_code: u32,
    pub unsupported_flags: u32,
    pub decision_digest: [u8; 32],
    pub skipped_step_count: u32,
    pub skipped_block_count: u32,
    pub skipped_token_count: u32,
    pub skipped_latent_count: u32,
    pub reused_cache_count: u32,
    pub partial_compute_count: u32,
}

impl StepDirective {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }

    pub fn fail_open(reason_code: u32, decision_digest: [u8; 32]) -> Self {
        Self::new(
            C1_DECISION_ESCALATE_FULL_COMPUTE,
            reason_code,
            decision_digest,
        )
    }

    fn new(decision_code: u32, reason_code: u32, decision_digest: [u8; 32]) -> Self {
        Self {
            abi_version: C1_STEP_POLICY_ABI_VERSION,
            struct_size: Self::contract_size(),
            decision_code,
            reason_code,
            unsupported_flags: 0,
            decision_digest,
            skipped_step_count: 0,
            skipped_block_count: 0,
            skipped_token_count: 0,
            skipped_latent_count: 0,
            reused_cache_count: 0,
            partial_compute_count: 0,
        }
    }
}

fn c1_observation_digest(observation: &StepObservation) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(observation.abi_version.to_le_bytes());
    hasher.update(observation.struct_size.to_le_bytes());
    hasher.update(observation.run_digest);
    hasher.update(observation.workflow_revision_digest);
    hasher.update(observation.settings_digest);
    hasher.update(observation.step_index.to_le_bytes());
    hasher.update(observation.total_steps.to_le_bytes());
    hasher.update(observation.sampler_logical_id.to_le_bytes());
    hasher.update(observation.scheduler_logical_id.to_le_bytes());
    hasher.update(observation.timestep_available.to_le_bytes());
    hasher.update(observation.timestep_bits.to_le_bytes());
    hasher.update(observation.sigma_available.to_le_bytes());
    hasher.update(observation.sigma_bits.to_le_bytes());
    hasher.update(observation.uncertainty_flags.to_le_bytes());
    hasher.update(observation.invalidation_flags.to_le_bytes());
    hasher.update(observation.full_compute_supported.to_le_bytes());
    hasher.update(observation.fallback_supported.to_le_bytes());
    hasher.update(observation.cache_available.to_le_bytes());
    hasher.update(observation.receipt_required.to_le_bytes());
    hasher.update(observation.unsupported_flags.to_le_bytes());
    hasher.finalize().into()
}

/// Deterministic C1 policy. It can only preserve full compute or fail open to
/// an explicit full-compute escalation; it cannot authorize selective work.
pub fn evaluate_step_policy(observation: &StepObservation) -> StepDirective {
    let digest = c1_observation_digest(observation);
    let reason = if observation.abi_version != C1_STEP_POLICY_ABI_VERSION {
        C1_REASON_ABI_MISMATCH
    } else if observation.struct_size != StepObservation::contract_size() {
        C1_REASON_STRUCT_SIZE_MISMATCH
    } else if observation.total_steps == 0 || observation.step_index >= observation.total_steps {
        C1_REASON_STEP_RANGE_INVALID
    } else if observation.run_digest == [0; 32]
        || observation.workflow_revision_digest == [0; 32]
        || observation.settings_digest == [0; 32]
    {
        C1_REASON_DIGEST_MISSING
    } else if observation.full_compute_supported != 1 {
        C1_REASON_FULL_COMPUTE_UNSUPPORTED
    } else if observation.fallback_supported != 1 {
        C1_REASON_FALLBACK_UNSUPPORTED
    } else if observation.uncertainty_flags != 0 {
        C1_REASON_UNCERTAINTY_PRESENT
    } else if observation.invalidation_flags != 0 {
        C1_REASON_INVALIDATION_PRESENT
    } else if observation.unsupported_flags != 0 {
        C1_REASON_UNSUPPORTED_METADATA
    } else {
        C1_REASON_NONE
    };
    if reason == C1_REASON_NONE {
        StepDirective::new(C1_DECISION_FULL_COMPUTE, reason, digest)
    } else {
        StepDirective::fail_open(reason, digest)
    }
}

/// Fixed-size C2 shadow observation. The only data-derived payload is two
/// 48-value fixed-point sketches; raw tensors and variable-length data are not
/// admitted by this ABI.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CompoundEyeShadowObservation {
    pub abi_version: u32,
    pub struct_size: u32,
    pub run_digest: [u8; 32],
    pub workflow_revision_digest: [u8; 32],
    pub settings_digest: [u8; 32],
    pub step_index: u32,
    pub total_steps: u32,
    pub topology_id: u32,
    pub sketch_source_id: u32,
    pub quantization_scale: u32,
    pub previous_available: u32,
    pub uncertainty_flags: u32,
    pub invalidation_flags: u32,
    pub full_compute_supported: u32,
    pub fallback_supported: u32,
    pub receipt_required: u32,
    pub unsupported_flags: u32,
    pub current_sketch_q: [i32; C2_SKETCH_VALUE_COUNT],
    pub previous_sketch_q: [i32; C2_SKETCH_VALUE_COUNT],
}

impl CompoundEyeShadowObservation {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }
}

/// Fixed-size C2 directive. Candidate fields are counterfactual only; all
/// fields that could represent actual selective execution remain zero.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CompoundEyeShadowDirective {
    pub abi_version: u32,
    pub struct_size: u32,
    pub decision_code: u32,
    pub reason_code: u32,
    pub unsupported_flags: u32,
    pub eye_state: [u32; C2_EYE_COUNT],
    pub eye_confidence_ppm: [u32; C2_EYE_COUNT],
    pub eye_change_ppm: [u32; C2_EYE_COUNT],
    pub stable_eye_count: u32,
    pub active_eye_count: u32,
    pub uncertain_eye_count: u32,
    pub candidate_generate_count: u32,
    pub candidate_reuse_count: u32,
    pub candidate_reconcile_count: u32,
    pub global_invalidation: u32,
    pub overlap_conflict_mask: u32,
    pub shared_visual_state_digest: [u8; 32],
    pub compute_plan_digest: [u8; 32],
    pub decision_digest: [u8; 32],
    pub skipped_step_count: u32,
    pub skipped_block_count: u32,
    pub skipped_token_count: u32,
    pub skipped_latent_count: u32,
    pub reused_cache_count: u32,
    pub partial_compute_count: u32,
}

impl CompoundEyeShadowDirective {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }

    pub fn fail_open(reason_code: u32) -> Self {
        let mut directive = evaluate_compound_eye_shadow_policy(&CompoundEyeShadowObservation {
            abi_version: C2_COMPOUND_EYE_SHADOW_ABI_VERSION,
            struct_size: CompoundEyeShadowObservation::contract_size(),
            run_digest: [1; 32],
            workflow_revision_digest: [1; 32],
            settings_digest: [1; 32],
            step_index: 0,
            total_steps: 1,
            topology_id: C2_TOPOLOGY_OVERLAP_2X2,
            sketch_source_id: C2_SKETCH_SOURCE_X0,
            quantization_scale: 1,
            previous_available: 0,
            uncertainty_flags: 1,
            invalidation_flags: 0,
            full_compute_supported: 1,
            fallback_supported: 1,
            receipt_required: 1,
            unsupported_flags: 0,
            current_sketch_q: [0; C2_SKETCH_VALUE_COUNT],
            previous_sketch_q: [0; C2_SKETCH_VALUE_COUNT],
        });
        directive.decision_code = C2_DECISION_ESCALATE_FULL_COMPUTE;
        directive.reason_code = reason_code;
        directive.decision_digest = c2_digest_parts(&[
            &directive.compute_plan_digest,
            &directive.decision_code.to_le_bytes(),
            &directive.reason_code.to_le_bytes(),
        ]);
        directive
    }
}

fn c2_observation_digest(observation: &CompoundEyeShadowObservation) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(observation.abi_version.to_le_bytes());
    hasher.update(observation.struct_size.to_le_bytes());
    hasher.update(observation.run_digest);
    hasher.update(observation.workflow_revision_digest);
    hasher.update(observation.settings_digest);
    for value in [
        observation.step_index,
        observation.total_steps,
        observation.topology_id,
        observation.sketch_source_id,
        observation.quantization_scale,
        observation.previous_available,
        observation.uncertainty_flags,
        observation.invalidation_flags,
        observation.full_compute_supported,
        observation.fallback_supported,
        observation.receipt_required,
        observation.unsupported_flags,
    ] {
        hasher.update(value.to_le_bytes());
    }
    for value in observation.current_sketch_q {
        hasher.update(value.to_le_bytes());
    }
    for value in observation.previous_sketch_q {
        hasher.update(value.to_le_bytes());
    }
    hasher.finalize().into()
}

const C2_REGIONAL_CELLS: [[usize; 9]; 4] = [
    [0, 1, 2, 4, 5, 6, 8, 9, 10],
    [1, 2, 3, 5, 6, 7, 9, 10, 11],
    [4, 5, 6, 8, 9, 10, 12, 13, 14],
    [5, 6, 7, 9, 10, 11, 13, 14, 15],
];

const C2_NEIGHBORS: [(usize, usize); 4] = [(0, 1), (0, 2), (1, 3), (2, 3)];

fn c2_delta_ppm(
    current: &[i32; C2_SKETCH_VALUE_COUNT],
    previous: &[i32; C2_SKETCH_VALUE_COUNT],
    cells: &[usize],
    quantization_scale: u32,
) -> u32 {
    let mut difference = 0_u128;
    let mut baseline = 0_u128;
    for cell in cells {
        for metric in 0..3 {
            let index = cell * 3 + metric;
            difference += i64::from(current[index])
                .saturating_sub(i64::from(previous[index]))
                .unsigned_abs() as u128;
            baseline += i64::from(previous[index])
                .unsigned_abs()
                .max(u64::from(quantization_scale)) as u128;
        }
    }
    if baseline == 0 {
        return if difference == 0 { 0 } else { u32::MAX };
    }
    ((difference.saturating_mul(1_000_000) / baseline).min(u128::from(u32::MAX))) as u32
}

fn c2_digest_parts(parts: &[&[u8]]) -> [u8; 32] {
    let mut hasher = Sha256::new();
    for part in parts {
        hasher.update(part);
    }
    hasher.finalize().into()
}

fn c2_invalid_reason(observation: &CompoundEyeShadowObservation) -> u32 {
    if observation.abi_version != C2_COMPOUND_EYE_SHADOW_ABI_VERSION {
        C2_REASON_ABI_MISMATCH
    } else if observation.struct_size != CompoundEyeShadowObservation::contract_size() {
        C2_REASON_STRUCT_SIZE_MISMATCH
    } else if observation.total_steps == 0 || observation.step_index >= observation.total_steps {
        C2_REASON_STEP_RANGE_INVALID
    } else if observation.run_digest == [0; 32]
        || observation.workflow_revision_digest == [0; 32]
        || observation.settings_digest == [0; 32]
    {
        C2_REASON_DIGEST_MISSING
    } else if observation.topology_id != C2_TOPOLOGY_OVERLAP_2X2 {
        C2_REASON_TOPOLOGY_UNSUPPORTED
    } else if observation.sketch_source_id != C2_SKETCH_SOURCE_X0 {
        C2_REASON_SKETCH_UNSUPPORTED
    } else if observation.quantization_scale == 0 {
        C2_REASON_QUANTIZATION_INVALID
    } else if observation.full_compute_supported != 1 {
        C2_REASON_FULL_COMPUTE_UNSUPPORTED
    } else if observation.fallback_supported != 1 {
        C2_REASON_FALLBACK_UNSUPPORTED
    } else if observation.unsupported_flags != 0 {
        C2_REASON_UNSUPPORTED_METADATA
    } else {
        C2_REASON_NONE
    }
}

/// Deterministic C2 shadow policy. It produces counterfactual regional states
/// and candidate counts but can only command full compute or full-compute
/// escalation.
pub fn evaluate_compound_eye_shadow_policy(
    observation: &CompoundEyeShadowObservation,
) -> CompoundEyeShadowDirective {
    let observation_digest = c2_observation_digest(observation);
    let reason_code = c2_invalid_reason(observation);
    let fail_open = reason_code != C2_REASON_NONE
        || observation.uncertainty_flags != 0
        || observation.invalidation_flags != 0;
    let mut eye_state = [C2_EYE_STATE_UNCERTAIN; C2_EYE_COUNT];
    let mut eye_confidence_ppm = [500_000; C2_EYE_COUNT];
    let mut eye_change_ppm = [0; C2_EYE_COUNT];
    let mut global_invalidation = 0;
    let mut overlap_conflict_mask = 0;

    if reason_code == C2_REASON_NONE && observation.previous_available == 1 {
        let all_cells = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15];
        let global_delta = c2_delta_ppm(
            &observation.current_sketch_q,
            &observation.previous_sketch_q,
            &all_cells,
            observation.quantization_scale,
        );
        eye_change_ppm[0] = global_delta;
        global_invalidation = u32::from(
            global_delta >= C2_GLOBAL_INVALIDATION_LIMIT_PPM || observation.invalidation_flags != 0,
        );
        eye_state[0] = if global_invalidation == 1 {
            C2_EYE_STATE_ACTIVE
        } else {
            C2_EYE_STATE_UNCERTAIN
        };
        eye_confidence_ppm[0] = if global_invalidation == 1 {
            1_000_000
        } else {
            500_000
        };

        for (regional, cells) in C2_REGIONAL_CELLS.iter().enumerate() {
            let eye = regional + 1;
            let delta = c2_delta_ppm(
                &observation.current_sketch_q,
                &observation.previous_sketch_q,
                cells,
                observation.quantization_scale,
            );
            eye_change_ppm[eye] = delta;
            let locally_below_global = (global_delta == 0 && delta == 0)
                || u128::from(delta).saturating_mul(1_000_000)
                    <= u128::from(global_delta)
                        .saturating_mul(u128::from(C2_LOCAL_TO_GLOBAL_LIMIT_PPM));
            if global_invalidation == 1 || delta >= C2_ACTIVE_DELTA_LIMIT_PPM {
                eye_state[eye] = C2_EYE_STATE_ACTIVE;
                eye_confidence_ppm[eye] = ((u128::from(delta) * 1_000_000
                    / u128::from(C2_ACTIVE_DELTA_LIMIT_PPM))
                .min(1_000_000)) as u32;
            } else if observation.step_index >= C2_MIN_WARMUP_CALLBACKS
                && delta <= C2_STABLE_DELTA_LIMIT_PPM
                && locally_below_global
                && !fail_open
            {
                eye_state[eye] = C2_EYE_STATE_STABLE;
                eye_confidence_ppm[eye] = 1_000_000_u32.saturating_sub(
                    ((u128::from(delta) * 500_000 / u128::from(C2_STABLE_DELTA_LIMIT_PPM))
                        .min(500_000)) as u32,
                );
            }
        }

        for (left, right) in C2_NEIGHBORS {
            let left_eye = left + 1;
            let right_eye = right + 1;
            if eye_state[left_eye] == C2_EYE_STATE_STABLE
                && eye_state[right_eye] == C2_EYE_STATE_ACTIVE
            {
                eye_state[left_eye] = C2_EYE_STATE_UNCERTAIN;
                overlap_conflict_mask |= 1 << left;
            }
            if eye_state[right_eye] == C2_EYE_STATE_STABLE
                && eye_state[left_eye] == C2_EYE_STATE_ACTIVE
            {
                eye_state[right_eye] = C2_EYE_STATE_UNCERTAIN;
                overlap_conflict_mask |= 1 << right;
            }
        }
    }

    if fail_open {
        eye_state = [C2_EYE_STATE_UNCERTAIN; C2_EYE_COUNT];
        eye_confidence_ppm = [0; C2_EYE_COUNT];
    }
    let regional = &eye_state[1..];
    let stable_eye_count = regional
        .iter()
        .filter(|&&state| state == C2_EYE_STATE_STABLE)
        .count() as u32;
    let active_eye_count = regional
        .iter()
        .filter(|&&state| state == C2_EYE_STATE_ACTIVE)
        .count() as u32;
    let uncertain_eye_count = regional
        .iter()
        .filter(|&&state| state == C2_EYE_STATE_UNCERTAIN)
        .count() as u32;

    let mut state_bytes = Vec::with_capacity(C2_EYE_COUNT * 12);
    for index in 0..C2_EYE_COUNT {
        state_bytes.extend_from_slice(&eye_state[index].to_le_bytes());
        state_bytes.extend_from_slice(&eye_confidence_ppm[index].to_le_bytes());
        state_bytes.extend_from_slice(&eye_change_ppm[index].to_le_bytes());
    }
    let shared_visual_state_digest = c2_digest_parts(&[&observation_digest, &state_bytes]);
    let counts = [
        active_eye_count,
        stable_eye_count,
        uncertain_eye_count,
        global_invalidation,
        overlap_conflict_mask,
    ];
    let mut count_bytes = Vec::with_capacity(counts.len() * 4);
    for count in counts {
        count_bytes.extend_from_slice(&count.to_le_bytes());
    }
    let compute_plan_digest = c2_digest_parts(&[&shared_visual_state_digest, &count_bytes]);
    let decision_code = if fail_open {
        C2_DECISION_ESCALATE_FULL_COMPUTE
    } else {
        C2_DECISION_FULL_COMPUTE
    };
    let decision_digest = c2_digest_parts(&[
        &compute_plan_digest,
        &decision_code.to_le_bytes(),
        &reason_code.to_le_bytes(),
    ]);
    CompoundEyeShadowDirective {
        abi_version: C2_COMPOUND_EYE_SHADOW_ABI_VERSION,
        struct_size: CompoundEyeShadowDirective::contract_size(),
        decision_code,
        reason_code,
        unsupported_flags: 0,
        eye_state,
        eye_confidence_ppm,
        eye_change_ppm,
        stable_eye_count,
        active_eye_count,
        uncertain_eye_count,
        candidate_generate_count: active_eye_count,
        candidate_reuse_count: stable_eye_count,
        candidate_reconcile_count: uncertain_eye_count,
        global_invalidation,
        overlap_conflict_mask,
        shared_visual_state_digest,
        compute_plan_digest,
        decision_digest,
        skipped_step_count: 0,
        skipped_block_count: 0,
        skipped_token_count: 0,
        skipped_latent_count: 0,
        reused_cache_count: 0,
        partial_compute_count: 0,
    }
}

/// Fixed-size A1 regional-attention observation.  Only C2-derived scalar
/// metadata and immutable digests cross the Python/Rust boundary.  Token
/// indices, tensors, CUDA pointers, prompts, and paths are intentionally not
/// representable.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AttentionRegionPlanObservation {
    pub abi_version: u32,
    pub struct_size: u32,
    pub run_digest: [u8; 32],
    pub workflow_revision_digest: [u8; 32],
    pub settings_digest: [u8; 32],
    pub model_revision_digest: [u8; 32],
    pub observed_step: u32,
    pub predicted_execution_step: u32,
    pub total_steps: u32,
    pub topology_id: u32,
    pub eye_state: [u32; A1_EYE_COUNT],
    pub eye_confidence_ppm: [u32; A1_EYE_COUNT],
    pub eye_change_ppm: [u32; A1_EYE_COUNT],
    pub stable_mask: u32,
    pub stable_count: u32,
    pub active_mask: u32,
    pub active_count: u32,
    pub uncertain_mask: u32,
    pub uncertain_count: u32,
    pub global_invalidation: u32,
    pub overlap_conflict_mask: u32,
    pub anchor_step: u32,
    pub cooldown_mask: u32,
    pub refresh_required_mask: u32,
    pub source_valid: u32,
    pub prediction_valid: u32,
    pub selective_supported: u32,
    pub fallback_supported: u32,
    pub fatal_flags: u32,
    pub unsupported_flags: u32,
}

impl AttentionRegionPlanObservation {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AttentionRegionPlanDirective {
    pub abi_version: u32,
    pub struct_size: u32,
    pub decision_code: u32,
    pub reason_code: u32,
    pub target_step: u32,
    pub stable_region_mask: u32,
    pub full_compute_region_mask: u32,
    pub refresh_region_mask: u32,
    pub fallback_required: u32,
    pub unsupported_flags: u32,
    pub shared_visual_state_digest: [u8; 32],
    pub compute_plan_digest: [u8; 32],
    pub decision_digest: [u8; 32],
}

impl AttentionRegionPlanDirective {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }

    pub fn fail_open(reason_code: u32, target_step: u32) -> Self {
        let shared = a1_digest_parts(&[b"a1-rust-panic"]);
        let plan = a1_digest_parts(&[&shared, &A1_REGION_MASK.to_le_bytes()]);
        let decision = a1_digest_parts(&[
            &plan,
            &A1_DECISION_ESCALATE_FULL_COMPUTE.to_le_bytes(),
            &reason_code.to_le_bytes(),
        ]);
        Self {
            abi_version: A1_ATTENTION_REGION_PLAN_ABI_VERSION,
            struct_size: Self::contract_size(),
            decision_code: A1_DECISION_ESCALATE_FULL_COMPUTE,
            reason_code,
            target_step,
            stable_region_mask: 0,
            full_compute_region_mask: A1_REGION_MASK,
            refresh_region_mask: 0,
            fallback_required: 1,
            unsupported_flags: 0,
            shared_visual_state_digest: shared,
            compute_plan_digest: plan,
            decision_digest: decision,
        }
    }
}

fn a1_digest_parts(parts: &[&[u8]]) -> [u8; 32] {
    let mut hasher = Sha256::new();
    for part in parts {
        hasher.update(part);
    }
    hasher.finalize().into()
}

fn a1_observation_digest(observation: &AttentionRegionPlanObservation) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(observation.abi_version.to_le_bytes());
    hasher.update(observation.struct_size.to_le_bytes());
    hasher.update(observation.run_digest);
    hasher.update(observation.workflow_revision_digest);
    hasher.update(observation.settings_digest);
    hasher.update(observation.model_revision_digest);
    for value in [
        observation.observed_step,
        observation.predicted_execution_step,
        observation.total_steps,
        observation.topology_id,
    ] {
        hasher.update(value.to_le_bytes());
    }
    for values in [
        observation.eye_state,
        observation.eye_confidence_ppm,
        observation.eye_change_ppm,
    ] {
        for value in values {
            hasher.update(value.to_le_bytes());
        }
    }
    for value in [
        observation.stable_mask,
        observation.stable_count,
        observation.active_mask,
        observation.active_count,
        observation.uncertain_mask,
        observation.uncertain_count,
        observation.global_invalidation,
        observation.overlap_conflict_mask,
        observation.anchor_step,
        observation.cooldown_mask,
        observation.refresh_required_mask,
        observation.source_valid,
        observation.prediction_valid,
        observation.selective_supported,
        observation.fallback_supported,
        observation.fatal_flags,
        observation.unsupported_flags,
    ] {
        hasher.update(value.to_le_bytes());
    }
    hasher.finalize().into()
}

fn a1_metadata_valid(observation: &AttentionRegionPlanObservation) -> bool {
    let masks_in_range = [
        observation.stable_mask,
        observation.active_mask,
        observation.uncertain_mask,
        observation.overlap_conflict_mask,
        observation.cooldown_mask,
        observation.refresh_required_mask,
    ]
    .into_iter()
    .all(|mask| mask & !A1_REGION_MASK == 0);
    let masks_disjoint = observation.stable_mask & observation.active_mask == 0
        && observation.stable_mask & observation.uncertain_mask == 0
        && observation.active_mask & observation.uncertain_mask == 0;
    let counts_match = observation.stable_count == observation.stable_mask.count_ones()
        && observation.active_count == observation.active_mask.count_ones()
        && observation.uncertain_count == observation.uncertain_mask.count_ones();
    let state_values_valid = observation
        .eye_state
        .into_iter()
        .all(|state| state <= C2_EYE_STATE_UNCERTAIN);
    let confidence_valid = observation
        .eye_confidence_ppm
        .into_iter()
        .all(|value| value <= 1_000_000);
    masks_in_range && masks_disjoint && counts_match && state_values_valid && confidence_valid
}

/// Compile a C2-derived semantic region state into an A1 attention plan.
/// Rust never maps regions to H3 token rows; that model-specific operation is
/// owned by the adapter and must fail open independently.
pub fn evaluate_attention_region_plan(
    observation: &AttentionRegionPlanObservation,
) -> AttentionRegionPlanDirective {
    let observation_digest = a1_observation_digest(observation);
    let structural_reason = if observation.abi_version != A1_ATTENTION_REGION_PLAN_ABI_VERSION {
        A1_REASON_ABI_MISMATCH
    } else if observation.struct_size != AttentionRegionPlanObservation::contract_size() {
        A1_REASON_STRUCT_SIZE_MISMATCH
    } else if observation.total_steps == 0
        || observation.observed_step >= observation.total_steps
        || observation.predicted_execution_step >= observation.total_steps
    {
        A1_REASON_STEP_RANGE_INVALID
    } else if observation.run_digest == [0; 32]
        || observation.workflow_revision_digest == [0; 32]
        || observation.settings_digest == [0; 32]
        || observation.model_revision_digest == [0; 32]
    {
        A1_REASON_DIGEST_MISSING
    } else if !a1_metadata_valid(observation) {
        A1_REASON_EYE_METADATA_INVALID
    } else if observation.source_valid != 1 {
        A1_REASON_SOURCE_INVALID
    } else if observation.prediction_valid != 1
        || observation.predicted_execution_step != observation.observed_step.saturating_add(2)
    {
        A1_REASON_PREDICTION_INVALID
    } else if observation.selective_supported != 1 {
        A1_REASON_SELECTIVE_UNSUPPORTED
    } else if observation.fallback_supported != 1 {
        A1_REASON_FALLBACK_UNSUPPORTED
    } else if observation.fatal_flags != 0 {
        A1_REASON_FATAL_FLAG
    } else if observation.unsupported_flags != 0 {
        A1_REASON_UNSUPPORTED_METADATA
    } else {
        A1_REASON_NONE
    };

    let unavailable = observation.active_mask
        | observation.uncertain_mask
        | observation.overlap_conflict_mask
        | observation.cooldown_mask
        | observation.refresh_required_mask;
    let stable_region_mask = observation.stable_mask & !unavailable & A1_REGION_MASK;
    let semantic_reason = if structural_reason != A1_REASON_NONE {
        structural_reason
    } else if observation.global_invalidation != 0 {
        A1_REASON_GLOBAL_INVALIDATION
    } else if observation.overlap_conflict_mask != 0 {
        A1_REASON_OVERLAP_CONFLICT
    } else if observation.anchor_step != 0 {
        A1_REASON_ANCHOR_STEP
    } else if observation.refresh_required_mask != 0 && stable_region_mask == 0 {
        A1_REASON_REFRESH_REQUIRED
    } else if stable_region_mask == 0 {
        A1_REASON_NO_STABLE_REGION
    } else {
        A1_REASON_NONE
    };
    let structural_failure = structural_reason != A1_REASON_NONE;
    let decision_code = if structural_failure {
        A1_DECISION_ESCALATE_FULL_COMPUTE
    } else if semantic_reason == A1_REASON_NONE {
        A1_DECISION_REGIONAL_ACTIVE_QUERY
    } else {
        A1_DECISION_FULL_COMPUTE
    };
    let admitted_stable = if decision_code == A1_DECISION_REGIONAL_ACTIVE_QUERY {
        stable_region_mask
    } else {
        0
    };
    let full_compute_region_mask = A1_REGION_MASK & !admitted_stable;

    let mut eye_bytes = Vec::with_capacity(A1_EYE_COUNT * 12);
    for index in 0..A1_EYE_COUNT {
        eye_bytes.extend_from_slice(&observation.eye_state[index].to_le_bytes());
        eye_bytes.extend_from_slice(&observation.eye_confidence_ppm[index].to_le_bytes());
        eye_bytes.extend_from_slice(&observation.eye_change_ppm[index].to_le_bytes());
    }
    let shared_visual_state_digest = a1_digest_parts(&[&observation_digest, &eye_bytes]);
    let compute_plan_digest = a1_digest_parts(&[
        &shared_visual_state_digest,
        &observation.predicted_execution_step.to_le_bytes(),
        &admitted_stable.to_le_bytes(),
        &full_compute_region_mask.to_le_bytes(),
        &observation.refresh_required_mask.to_le_bytes(),
    ]);
    let decision_digest = a1_digest_parts(&[
        &compute_plan_digest,
        &decision_code.to_le_bytes(),
        &semantic_reason.to_le_bytes(),
    ]);
    AttentionRegionPlanDirective {
        abi_version: A1_ATTENTION_REGION_PLAN_ABI_VERSION,
        struct_size: AttentionRegionPlanDirective::contract_size(),
        decision_code,
        reason_code: semantic_reason,
        target_step: observation.predicted_execution_step,
        stable_region_mask: admitted_stable,
        full_compute_region_mask,
        refresh_region_mask: observation.refresh_required_mask,
        fallback_required: u32::from(structural_failure),
        unsupported_flags: 0,
        shared_visual_state_digest,
        compute_plan_digest,
        decision_digest,
    }
}

/// Fixed-size C3-R1 frozen-replay observation.
///
/// This contract admits only scalar metadata and SHA-256 digests. It contains
/// no tensor, pointer, path, prompt, variable-length payload, or CUDA address.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct C3FrozenBlockPlanObservation {
    pub abi_version: u32,
    pub struct_size: u32,
    pub run_digest: [u8; 32],
    pub workflow_revision_digest: [u8; 32],
    pub settings_digest: [u8; 32],
    pub model_revision_digest: [u8; 32],
    pub predicted_execution_step: u32,
    pub total_steps: u32,
    pub block_count: u32,
    pub frozen_schedule_member: u32,
    pub stable_mask: u32,
    pub stable_count: u32,
    pub active_mask: u32,
    pub active_count: u32,
    pub uncertain_mask: u32,
    pub uncertain_count: u32,
    pub global_invalidation: u32,
    pub overlap_conflict_mask: u32,
    pub prediction_valid: u32,
    pub source_valid: u32,
    pub selective_supported: u32,
    pub fallback_supported: u32,
    pub fatal_flags: u32,
    pub unsupported_flags: u32,
}

impl C3FrozenBlockPlanObservation {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }
}

/// Fixed-size C3-R1 directive. The mask is block metadata, not tensor data.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct C3FrozenBlockPlanDirective {
    pub abi_version: u32,
    pub struct_size: u32,
    pub decision_code: u32,
    pub reason_code: u32,
    pub target_step: u32,
    pub bypass_mask: u64,
    pub bypass_count: u32,
    pub fallback_required: u32,
    pub unsupported_flags: u32,
    pub decision_digest: [u8; 32],
}

impl C3FrozenBlockPlanDirective {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }

    pub fn fail_open(reason_code: u32, target_step: u32, digest: [u8; 32]) -> Self {
        Self {
            abi_version: C3_R1_BLOCK_PLAN_ABI_VERSION,
            struct_size: Self::contract_size(),
            decision_code: C3_R1_DECISION_ESCALATE_FULL_COMPUTE,
            reason_code,
            target_step,
            bypass_mask: 0,
            bypass_count: 0,
            fallback_required: 1,
            unsupported_flags: 0,
            decision_digest: digest,
        }
    }
}

fn c3_r1_observation_digest(observation: &C3FrozenBlockPlanObservation) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(observation.abi_version.to_le_bytes());
    hasher.update(observation.struct_size.to_le_bytes());
    hasher.update(observation.run_digest);
    hasher.update(observation.workflow_revision_digest);
    hasher.update(observation.settings_digest);
    hasher.update(observation.model_revision_digest);
    for value in [
        observation.predicted_execution_step,
        observation.total_steps,
        observation.block_count,
        observation.frozen_schedule_member,
        observation.stable_mask,
        observation.stable_count,
        observation.active_mask,
        observation.active_count,
        observation.uncertain_mask,
        observation.uncertain_count,
        observation.global_invalidation,
        observation.overlap_conflict_mask,
        observation.prediction_valid,
        observation.source_valid,
        observation.selective_supported,
        observation.fallback_supported,
        observation.fatal_flags,
        observation.unsupported_flags,
    ] {
        hasher.update(value.to_le_bytes());
    }
    hasher.finalize().into()
}

fn c3_r1_directive(
    observation: &C3FrozenBlockPlanObservation,
    decision_code: u32,
    reason_code: u32,
    bypass_mask: u64,
) -> C3FrozenBlockPlanDirective {
    let observation_digest = c3_r1_observation_digest(observation);
    let decision_digest = c2_digest_parts(&[
        &observation_digest,
        &decision_code.to_le_bytes(),
        &reason_code.to_le_bytes(),
        &bypass_mask.to_le_bytes(),
    ]);
    C3FrozenBlockPlanDirective {
        abi_version: C3_R1_BLOCK_PLAN_ABI_VERSION,
        struct_size: C3FrozenBlockPlanDirective::contract_size(),
        decision_code,
        reason_code,
        target_step: observation.predicted_execution_step,
        bypass_mask,
        bypass_count: bypass_mask.count_ones(),
        fallback_required: u32::from(decision_code != C3_R1_DECISION_SELECTIVE_BLOCK_BYPASS),
        unsupported_flags: 0,
        decision_digest,
    }
}

fn c3_r1_contract_reason(observation: &C3FrozenBlockPlanObservation) -> u32 {
    let expected_schedule_member =
        u32::from(C3_R1_FROZEN_SCHEDULE.contains(&observation.predicted_execution_step));
    let eye_mask_union =
        observation.stable_mask | observation.active_mask | observation.uncertain_mask;
    if observation.abi_version != C3_R1_BLOCK_PLAN_ABI_VERSION {
        C3_R1_REASON_ABI_MISMATCH
    } else if observation.struct_size != C3FrozenBlockPlanObservation::contract_size() {
        C3_R1_REASON_STRUCT_SIZE_MISMATCH
    } else if observation.predicted_execution_step >= observation.total_steps {
        C3_R1_REASON_STEP_RANGE_INVALID
    } else if observation.run_digest == [0; 32]
        || observation.workflow_revision_digest == [0; 32]
        || observation.settings_digest == [0; 32]
        || observation.model_revision_digest == [0; 32]
    {
        C3_R1_REASON_DIGEST_MISSING
    } else if observation.total_steps != C3_R1_TOTAL_STEPS
        || observation.block_count != C3_R1_BLOCK_COUNT
    {
        C3_R1_REASON_EXECUTION_CONTRACT_MISMATCH
    } else if eye_mask_union & !0x0f != 0
        || (observation.stable_mask & observation.active_mask) != 0
        || (observation.stable_mask & observation.uncertain_mask) != 0
        || (observation.active_mask & observation.uncertain_mask) != 0
        || observation.stable_count != observation.stable_mask.count_ones()
        || observation.active_count != observation.active_mask.count_ones()
        || observation.uncertain_count != observation.uncertain_mask.count_ones()
    {
        C3_R1_REASON_EYE_METADATA_INVALID
    } else if observation.selective_supported != 1 {
        C3_R1_REASON_SELECTIVE_UNSUPPORTED
    } else if observation.fallback_supported != 1 {
        C3_R1_REASON_FALLBACK_UNSUPPORTED
    } else if observation.unsupported_flags != 0 {
        C3_R1_REASON_UNSUPPORTED_METADATA
    } else if observation.frozen_schedule_member != expected_schedule_member {
        C3_R1_REASON_SCHEDULE_FLAG_MISMATCH
    } else {
        C3_R1_REASON_NONE
    }
}

/// Deterministic C3-R1 frozen-replay policy. It never adds a target step: the
/// immutable schedule is the maximum ceiling and live metadata may only veto
/// a member back to ordinary full compute.
pub fn evaluate_c3_frozen_block_plan(
    observation: &C3FrozenBlockPlanObservation,
) -> C3FrozenBlockPlanDirective {
    let contract_reason = c3_r1_contract_reason(observation);
    if contract_reason != C3_R1_REASON_NONE {
        return c3_r1_directive(
            observation,
            C3_R1_DECISION_ESCALATE_FULL_COMPUTE,
            contract_reason,
            0,
        );
    }
    let veto_reason = if observation.frozen_schedule_member != 1 {
        C3_R1_REASON_NOT_FROZEN_TARGET
    } else if observation.source_valid != 1 {
        C3_R1_REASON_SOURCE_INVALID
    } else if observation.prediction_valid != 1 {
        C3_R1_REASON_PREDICTION_INVALID
    } else if observation.stable_count < 2 {
        C3_R1_REASON_STABLE_COUNT_LOW
    } else if observation.active_count != 0 {
        C3_R1_REASON_ACTIVE_PRESENT
    } else if observation.global_invalidation != 0 {
        C3_R1_REASON_GLOBAL_INVALIDATION
    } else if observation.overlap_conflict_mask != 0 {
        C3_R1_REASON_OVERLAP_CONFLICT
    } else if observation.fatal_flags != 0 {
        C3_R1_REASON_FATAL_FLAG
    } else {
        C3_R1_REASON_NONE
    };
    if veto_reason == C3_R1_REASON_NONE {
        c3_r1_directive(
            observation,
            C3_R1_DECISION_SELECTIVE_BLOCK_BYPASS,
            C3_R1_REASON_NONE,
            C3_R1_CANDIDATE_BLOCK_MASK,
        )
    } else {
        c3_r1_directive(observation, C3_R1_DECISION_FULL_COMPUTE, veto_reason, 0)
    }
}

/// Generic, metadata-only transform-reuse observation for C3-R2.
///
/// Model adapters own tensors and model-specific block ranges. Core receives
/// only fixed-width policy metadata and digests; no tensor, pointer, path,
/// prompt, CUDA address, or variable-length payload crosses this boundary.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReusePlanObservation {
    pub abi_version: u32,
    pub struct_size: u32,
    pub run_digest: [u8; 32],
    pub workflow_revision_digest: [u8; 32],
    pub settings_digest: [u8; 32],
    pub model_revision_digest: [u8; 32],
    pub segment_logical_digest: [u8; 32],
    pub target_execution_step: u32,
    pub source_execution_step: u32,
    pub total_steps: u32,
    pub cache_age: u32,
    pub cache_available: u32,
    pub cache_provenance_valid: u32,
    pub residual_similarity_admitted: u32,
    pub calibrated_target: u32,
    pub prior_step_reused: u32,
    pub stable_mask: u32,
    pub stable_count: u32,
    pub active_mask: u32,
    pub active_count: u32,
    pub uncertain_mask: u32,
    pub uncertain_count: u32,
    pub global_invalidation: u32,
    pub overlap_conflict_mask: u32,
    pub prediction_valid: u32,
    pub source_valid: u32,
    pub finite: u32,
    pub fallback_supported: u32,
    pub fatal_flags: u32,
    pub unsupported_flags: u32,
}

impl ReusePlanObservation {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReusePlanDirective {
    pub abi_version: u32,
    pub struct_size: u32,
    pub decision_code: u32,
    pub reason_code: u32,
    pub target_execution_step: u32,
    pub source_execution_step: u32,
    pub fallback_required: u32,
    pub unsupported_flags: u32,
    pub decision_digest: [u8; 32],
}

impl ReusePlanDirective {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }

    pub fn fail_open(
        reason_code: u32,
        target_execution_step: u32,
        source_execution_step: u32,
        digest: [u8; 32],
    ) -> Self {
        Self {
            abi_version: C3_R2_REUSE_PLAN_ABI_VERSION,
            struct_size: Self::contract_size(),
            decision_code: C3_R2_DECISION_ESCALATE_FULL_COMPUTE,
            reason_code,
            target_execution_step,
            source_execution_step,
            fallback_required: 1,
            unsupported_flags: 0,
            decision_digest: digest,
        }
    }
}

fn c3_r2_observation_digest(observation: &ReusePlanObservation) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(observation.abi_version.to_le_bytes());
    hasher.update(observation.struct_size.to_le_bytes());
    hasher.update(observation.run_digest);
    hasher.update(observation.workflow_revision_digest);
    hasher.update(observation.settings_digest);
    hasher.update(observation.model_revision_digest);
    hasher.update(observation.segment_logical_digest);
    for value in [
        observation.target_execution_step,
        observation.source_execution_step,
        observation.total_steps,
        observation.cache_age,
        observation.cache_available,
        observation.cache_provenance_valid,
        observation.residual_similarity_admitted,
        observation.calibrated_target,
        observation.prior_step_reused,
        observation.stable_mask,
        observation.stable_count,
        observation.active_mask,
        observation.active_count,
        observation.uncertain_mask,
        observation.uncertain_count,
        observation.global_invalidation,
        observation.overlap_conflict_mask,
        observation.prediction_valid,
        observation.source_valid,
        observation.finite,
        observation.fallback_supported,
        observation.fatal_flags,
        observation.unsupported_flags,
    ] {
        hasher.update(value.to_le_bytes());
    }
    hasher.finalize().into()
}

fn c3_r2_directive(
    observation: &ReusePlanObservation,
    decision_code: u32,
    reason_code: u32,
) -> ReusePlanDirective {
    let observation_digest = c3_r2_observation_digest(observation);
    let decision_digest = c2_digest_parts(&[
        &observation_digest,
        &decision_code.to_le_bytes(),
        &reason_code.to_le_bytes(),
    ]);
    ReusePlanDirective {
        abi_version: C3_R2_REUSE_PLAN_ABI_VERSION,
        struct_size: ReusePlanDirective::contract_size(),
        decision_code,
        reason_code,
        target_execution_step: observation.target_execution_step,
        source_execution_step: observation.source_execution_step,
        fallback_required: u32::from(decision_code != C3_R2_DECISION_REUSE_TRANSFORM),
        unsupported_flags: 0,
        decision_digest,
    }
}

fn c3_r2_contract_reason(observation: &ReusePlanObservation) -> u32 {
    let eye_mask_union =
        observation.stable_mask | observation.active_mask | observation.uncertain_mask;
    if observation.abi_version != C3_R2_REUSE_PLAN_ABI_VERSION {
        C3_R2_REASON_ABI_MISMATCH
    } else if observation.struct_size != ReusePlanObservation::contract_size() {
        C3_R2_REASON_STRUCT_SIZE_MISMATCH
    } else if observation.target_execution_step >= observation.total_steps
        || observation.source_execution_step >= observation.total_steps
    {
        C3_R2_REASON_STEP_RANGE_INVALID
    } else if observation.run_digest == [0; 32]
        || observation.workflow_revision_digest == [0; 32]
        || observation.settings_digest == [0; 32]
        || observation.model_revision_digest == [0; 32]
        || observation.segment_logical_digest == [0; 32]
    {
        C3_R2_REASON_DIGEST_MISSING
    } else if eye_mask_union & !0x0f != 0
        || (observation.stable_mask & observation.active_mask) != 0
        || (observation.stable_mask & observation.uncertain_mask) != 0
        || (observation.active_mask & observation.uncertain_mask) != 0
        || observation.stable_count != observation.stable_mask.count_ones()
        || observation.active_count != observation.active_mask.count_ones()
        || observation.uncertain_count != observation.uncertain_mask.count_ones()
    {
        C3_R2_REASON_METADATA_INVALID
    } else if observation.fallback_supported != 1 {
        C3_R2_REASON_FALLBACK_UNSUPPORTED
    } else if observation.unsupported_flags != 0 {
        C3_R2_REASON_UNSUPPORTED_METADATA
    } else {
        C3_R2_REASON_NONE
    }
}

/// Deterministic transform-reuse decision. A model adapter may execute reuse
/// only when this directive admits it and must otherwise fail open to its
/// ordinary Full Compute path.
pub fn evaluate_reuse_plan(observation: &ReusePlanObservation) -> ReusePlanDirective {
    let contract_reason = c3_r2_contract_reason(observation);
    if contract_reason != C3_R2_REASON_NONE {
        return c3_r2_directive(
            observation,
            C3_R2_DECISION_ESCALATE_FULL_COMPUTE,
            contract_reason,
        );
    }
    let veto_reason = if observation.calibrated_target != 1 {
        C3_R2_REASON_NOT_CALIBRATED
    } else if observation.cache_available != 1 {
        C3_R2_REASON_CACHE_MISSING
    } else if observation.cache_age != 1
        || observation.source_execution_step + 1 != observation.target_execution_step
    {
        C3_R2_REASON_CACHE_AGE_INVALID
    } else if observation.cache_provenance_valid != 1 || observation.finite != 1 {
        C3_R2_REASON_PROVENANCE_INVALID
    } else if observation.residual_similarity_admitted != 1 {
        C3_R2_REASON_SIMILARITY_REJECTED
    } else if observation.source_valid != 1 {
        C3_R2_REASON_SOURCE_INVALID
    } else if observation.prediction_valid != 1 {
        C3_R2_REASON_PREDICTION_INVALID
    } else if observation.stable_count < 2 {
        C3_R2_REASON_STABLE_COUNT_LOW
    } else if observation.active_count != 0 {
        C3_R2_REASON_ACTIVE_PRESENT
    } else if observation.global_invalidation != 0 {
        C3_R2_REASON_GLOBAL_INVALIDATION
    } else if observation.overlap_conflict_mask != 0 {
        C3_R2_REASON_OVERLAP_CONFLICT
    } else if observation.fatal_flags != 0 {
        C3_R2_REASON_FATAL_FLAG
    } else if observation.prior_step_reused != 0 {
        C3_R2_REASON_CONSECUTIVE_REUSE
    } else {
        C3_R2_REASON_NONE
    };
    if veto_reason == C3_R2_REASON_NONE {
        c3_r2_directive(
            observation,
            C3_R2_DECISION_REUSE_TRANSFORM,
            C3_R2_REASON_NONE,
        )
    } else {
        c3_r2_directive(observation, C3_R2_DECISION_FULL_COMPUTE, veto_reason)
    }
}

/// Generic, metadata-only admission observation for compact correction reuse.
/// Model adapters retain every tensor and all model-specific layout details.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CorrectionPlanObservation {
    pub abi_version: u32,
    pub struct_size: u32,
    pub run_digest: [u8; 32],
    pub workflow_revision_digest: [u8; 32],
    pub settings_digest: [u8; 32],
    pub model_revision_digest: [u8; 32],
    pub segment_logical_digest: [u8; 32],
    pub target_execution_step: u32,
    pub first_source_execution_step: u32,
    pub second_source_execution_step: u32,
    pub total_steps: u32,
    pub cache_available: u32,
    pub predictor_available: u32,
    pub predictor_provenance_valid: u32,
    pub corrected_similarity_admitted: u32,
    pub correction_metadata_valid: u32,
    pub calibrated_target: u32,
    pub full_compute_seed_count: u32,
    pub reseed_required: u32,
    pub stable_mask: u32,
    pub stable_count: u32,
    pub active_mask: u32,
    pub active_count: u32,
    pub uncertain_mask: u32,
    pub uncertain_count: u32,
    pub global_invalidation: u32,
    pub overlap_conflict_mask: u32,
    pub prediction_valid: u32,
    pub source_valid: u32,
    pub finite: u32,
    pub fallback_supported: u32,
    pub fatal_flags: u32,
    pub unsupported_flags: u32,
}

impl CorrectionPlanObservation {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CorrectionPlanDirective {
    pub abi_version: u32,
    pub struct_size: u32,
    pub decision_code: u32,
    pub reason_code: u32,
    pub target_execution_step: u32,
    pub first_source_execution_step: u32,
    pub second_source_execution_step: u32,
    pub fallback_required: u32,
    pub unsupported_flags: u32,
    pub decision_digest: [u8; 32],
}

impl CorrectionPlanDirective {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }

    pub fn fail_open(
        reason_code: u32,
        target_execution_step: u32,
        first_source_execution_step: u32,
        second_source_execution_step: u32,
        digest: [u8; 32],
    ) -> Self {
        Self {
            abi_version: C3_R3_CORRECTION_PLAN_ABI_VERSION,
            struct_size: Self::contract_size(),
            decision_code: C3_R3_DECISION_ESCALATE_FULL_COMPUTE,
            reason_code,
            target_execution_step,
            first_source_execution_step,
            second_source_execution_step,
            fallback_required: 1,
            unsupported_flags: 0,
            decision_digest: digest,
        }
    }
}

fn c3_r3_observation_digest(observation: &CorrectionPlanObservation) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(observation.abi_version.to_le_bytes());
    hasher.update(observation.struct_size.to_le_bytes());
    hasher.update(observation.run_digest);
    hasher.update(observation.workflow_revision_digest);
    hasher.update(observation.settings_digest);
    hasher.update(observation.model_revision_digest);
    hasher.update(observation.segment_logical_digest);
    for value in [
        observation.target_execution_step,
        observation.first_source_execution_step,
        observation.second_source_execution_step,
        observation.total_steps,
        observation.cache_available,
        observation.predictor_available,
        observation.predictor_provenance_valid,
        observation.corrected_similarity_admitted,
        observation.correction_metadata_valid,
        observation.calibrated_target,
        observation.full_compute_seed_count,
        observation.reseed_required,
        observation.stable_mask,
        observation.stable_count,
        observation.active_mask,
        observation.active_count,
        observation.uncertain_mask,
        observation.uncertain_count,
        observation.global_invalidation,
        observation.overlap_conflict_mask,
        observation.prediction_valid,
        observation.source_valid,
        observation.finite,
        observation.fallback_supported,
        observation.fatal_flags,
        observation.unsupported_flags,
    ] {
        hasher.update(value.to_le_bytes());
    }
    hasher.finalize().into()
}

fn c3_r3_directive(
    observation: &CorrectionPlanObservation,
    decision_code: u32,
    reason_code: u32,
) -> CorrectionPlanDirective {
    let observation_digest = c3_r3_observation_digest(observation);
    let decision_digest = c2_digest_parts(&[
        &observation_digest,
        &decision_code.to_le_bytes(),
        &reason_code.to_le_bytes(),
    ]);
    CorrectionPlanDirective {
        abi_version: C3_R3_CORRECTION_PLAN_ABI_VERSION,
        struct_size: CorrectionPlanDirective::contract_size(),
        decision_code,
        reason_code,
        target_execution_step: observation.target_execution_step,
        first_source_execution_step: observation.first_source_execution_step,
        second_source_execution_step: observation.second_source_execution_step,
        fallback_required: u32::from(decision_code != C3_R3_DECISION_REUSE_CORRECTED_TRANSFORM),
        unsupported_flags: 0,
        decision_digest,
    }
}

fn c3_r3_contract_reason(observation: &CorrectionPlanObservation) -> u32 {
    let eye_mask_union =
        observation.stable_mask | observation.active_mask | observation.uncertain_mask;
    if observation.abi_version != C3_R3_CORRECTION_PLAN_ABI_VERSION {
        C3_R3_REASON_ABI_MISMATCH
    } else if observation.struct_size != CorrectionPlanObservation::contract_size() {
        C3_R3_REASON_STRUCT_SIZE_MISMATCH
    } else if observation.target_execution_step >= observation.total_steps
        || observation.first_source_execution_step >= observation.total_steps
        || observation.second_source_execution_step >= observation.total_steps
        || observation.first_source_execution_step + 1 != observation.second_source_execution_step
        || observation.second_source_execution_step + 1 != observation.target_execution_step
    {
        C3_R3_REASON_STEP_RANGE_INVALID
    } else if observation.run_digest == [0; 32]
        || observation.workflow_revision_digest == [0; 32]
        || observation.settings_digest == [0; 32]
        || observation.model_revision_digest == [0; 32]
        || observation.segment_logical_digest == [0; 32]
    {
        C3_R3_REASON_DIGEST_MISSING
    } else if eye_mask_union & !0x0f != 0
        || (observation.stable_mask & observation.active_mask) != 0
        || (observation.stable_mask & observation.uncertain_mask) != 0
        || (observation.active_mask & observation.uncertain_mask) != 0
        || observation.stable_count != observation.stable_mask.count_ones()
        || observation.active_count != observation.active_mask.count_ones()
        || observation.uncertain_count != observation.uncertain_mask.count_ones()
    {
        C3_R3_REASON_METADATA_INVALID
    } else if observation.fallback_supported != 1 {
        C3_R3_REASON_FALLBACK_UNSUPPORTED
    } else if observation.unsupported_flags != 0 {
        C3_R3_REASON_UNSUPPORTED_METADATA
    } else {
        C3_R3_REASON_NONE
    }
}

/// Admit compact correction reuse only after two consecutive Full Compute
/// seeds and every quality/safety predicate pass. Otherwise fail open.
pub fn evaluate_correction_plan(
    observation: &CorrectionPlanObservation,
) -> CorrectionPlanDirective {
    let contract_reason = c3_r3_contract_reason(observation);
    if contract_reason != C3_R3_REASON_NONE {
        return c3_r3_directive(
            observation,
            C3_R3_DECISION_ESCALATE_FULL_COMPUTE,
            contract_reason,
        );
    }
    let veto_reason = if observation.calibrated_target != 1 {
        C3_R3_REASON_NOT_CALIBRATED
    } else if observation.cache_available != 1 {
        C3_R3_REASON_CACHE_MISSING
    } else if observation.predictor_available != 1 {
        C3_R3_REASON_PREDICTOR_MISSING
    } else if observation.predictor_provenance_valid != 1 || observation.finite != 1 {
        C3_R3_REASON_PROVENANCE_INVALID
    } else if observation.corrected_similarity_admitted != 1 {
        C3_R3_REASON_SIMILARITY_REJECTED
    } else if observation.correction_metadata_valid != 1 {
        C3_R3_REASON_METADATA_INVALID
    } else if observation.source_valid != 1 {
        C3_R3_REASON_SOURCE_INVALID
    } else if observation.prediction_valid != 1 {
        C3_R3_REASON_PREDICTION_INVALID
    } else if observation.full_compute_seed_count < 2 || observation.reseed_required != 0 {
        C3_R3_REASON_RESEED_REQUIRED
    } else if observation.stable_count < 2 {
        C3_R3_REASON_STABLE_COUNT_LOW
    } else if observation.active_count != 0 {
        C3_R3_REASON_ACTIVE_PRESENT
    } else if observation.global_invalidation != 0 {
        C3_R3_REASON_GLOBAL_INVALIDATION
    } else if observation.overlap_conflict_mask != 0 {
        C3_R3_REASON_OVERLAP_CONFLICT
    } else if observation.fatal_flags != 0 {
        C3_R3_REASON_FATAL_FLAG
    } else {
        C3_R3_REASON_NONE
    };
    if veto_reason == C3_R3_REASON_NONE {
        c3_r3_directive(
            observation,
            C3_R3_DECISION_REUSE_CORRECTED_TRANSFORM,
            C3_R3_REASON_NONE,
        )
    } else {
        c3_r3_directive(observation, C3_R3_DECISION_FULL_COMPUTE, veto_reason)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct PixelBox {
    pub x: usize,
    pub y: usize,
    pub width: usize,
    pub height: usize,
}

impl PixelBox {
    pub fn new(x: usize, y: usize, width: usize, height: usize) -> Result<Self, String> {
        if width == 0 || height == 0 {
            return Err("PixelBox dimensions must be positive.".to_string());
        }
        Ok(Self {
            x,
            y,
            width,
            height,
        })
    }

    pub fn x2(&self) -> usize {
        self.x + self.width
    }

    pub fn y2(&self) -> usize {
        self.y + self.height
    }

    pub fn area(&self) -> usize {
        self.width * self.height
    }

    pub fn contains(&self, other: &Self) -> bool {
        self.x <= other.x && self.y <= other.y && self.x2() >= other.x2() && self.y2() >= other.y2()
    }

    pub fn intersects(&self, other: &Self) -> bool {
        !(self.x2() <= other.x
            || other.x2() <= self.x
            || self.y2() <= other.y
            || other.y2() <= self.y)
    }

    pub fn expand(&self, halo: usize, width: usize, height: usize) -> Self {
        let x = self.x.saturating_sub(halo);
        let y = self.y.saturating_sub(halo);
        let x2 = self.x2().saturating_add(halo).min(width);
        let y2 = self.y2().saturating_add(halo).min(height);
        Self {
            x,
            y,
            width: x2 - x,
            height: y2 - y,
        }
    }
}

#[derive(Clone, Debug)]
pub struct InputProfile {
    pub profile_id: String,
    pub width: usize,
    pub height: usize,
    pub frames: usize,
    pub seed: u64,
    pub change_regions: Vec<PixelBox>,
}

impl InputProfile {
    pub fn named(name: &str, seed: u64) -> Result<Self, String> {
        let (width, height, frames, regions) = match name {
            "low" => (640, 384, 16, vec![PixelBox::new(324, 112, 24, 32)?]),
            "medium" => (
                1280,
                720,
                16,
                vec![
                    PixelBox::new(646, 176, 48, 52)?,
                    PixelBox::new(286, 364, 64, 48)?,
                ],
            ),
            "high" => (
                1920,
                1080,
                8,
                vec![
                    PixelBox::new(968, 238, 72, 84)?,
                    PixelBox::new(442, 544, 96, 68)?,
                    PixelBox::new(1420, 784, 110, 72)?,
                ],
            ),
            "extended" => (
                3840,
                2160,
                4,
                vec![
                    PixelBox::new(1932, 480, 128, 144)?,
                    PixelBox::new(872, 1092, 180, 100)?,
                ],
            ),
            _ => return Err(format!("Unknown input profile: {name}")),
        };
        Self::new(name, width, height, frames, seed, regions)
    }

    pub fn new(
        profile_id: &str,
        width: usize,
        height: usize,
        frames: usize,
        seed: u64,
        change_regions: Vec<PixelBox>,
    ) -> Result<Self, String> {
        if frames < 2 || width == 0 || height == 0 {
            return Err(
                "Input shape must contain at least two non-empty grayscale frames.".to_string(),
            );
        }
        let canvas = PixelBox::new(0, 0, width, height)?;
        if change_regions.iter().any(|region| !canvas.contains(region)) {
            return Err("Synthetic change region exceeds the input canvas.".to_string());
        }
        Ok(Self {
            profile_id: profile_id.to_string(),
            width,
            height,
            frames,
            seed,
            change_regions,
        })
    }

    pub fn pixels(&self) -> usize {
        self.width * self.height
    }

    pub fn byte_length(&self) -> usize {
        self.frames * self.pixels()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Topology {
    Mono1x1,
    Uniform2x2,
    Uniform4x4,
    Overlap2x2,
    MotionFocused,
}

impl Topology {
    pub fn parse(value: &str) -> Result<Self, String> {
        match value {
            "mono_1x1" => Ok(Self::Mono1x1),
            "uniform_2x2" => Ok(Self::Uniform2x2),
            "uniform_4x4" => Ok(Self::Uniform4x4),
            "overlap_2x2" => Ok(Self::Overlap2x2),
            "motion_focused" => Ok(Self::MotionFocused),
            _ => Err(format!("Unknown eye topology: {value}")),
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Mono1x1 => "mono_1x1",
            Self::Uniform2x2 => "uniform_2x2",
            Self::Uniform4x4 => "uniform_4x4",
            Self::Overlap2x2 => "overlap_2x2",
            Self::MotionFocused => "motion_focused",
        }
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct InputIdentity {
    pub width: usize,
    pub height: usize,
    pub frames: usize,
    pub seed: u64,
    pub byte_length: usize,
    pub sha256: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct EyeRoute {
    pub eye_id: String,
    pub eye_type: String,
    pub receptive_field: PixelBox,
    pub write_scope: Option<PixelBox>,
    pub local_to_global: [usize; 2],
    pub overlap: bool,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct Provenance {
    pub source_sequence_id: String,
    pub algorithm: String,
    pub input_sha256: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct Observation {
    pub observation_id: String,
    pub eye_id: String,
    pub state: String,
    pub changed_pixels: usize,
    pub motion_bbox: Option<PixelBox>,
    pub region_checksum: u64,
    pub confidence: f64,
    pub provenance: Provenance,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct FusedRegion {
    pub region_id: String,
    pub scope: PixelBox,
    pub state: String,
    pub confidence: f64,
    pub sources: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ComputeUnit {
    pub unit_id: String,
    pub action: String,
    pub scope: PixelBox,
    pub source_observation_ids: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct UnsupportedMetric {
    pub name: String,
    pub value: Option<f64>,
    pub unit: String,
    pub status: String,
    pub reason: String,
    pub method: String,
}

impl UnsupportedMetric {
    fn new(name: &str, unit: &str, status: &str, reason: &str, method: &str) -> Self {
        Self {
            name: name.to_string(),
            value: None,
            unit: unit.to_string(),
            status: status.to_string(),
            reason: reason.to_string(),
            method: method.to_string(),
        }
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ComputePlan {
    pub policy: String,
    pub units: Vec<ComputeUnit>,
    pub claims: Vec<UnsupportedMetric>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct SharedVisualState {
    pub policy: String,
    pub regions: Vec<FusedRegion>,
    pub observation_ids: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct SemanticResult {
    pub schema_version: String,
    pub profile_id: String,
    pub topology: String,
    pub input: InputIdentity,
    pub eyes: Vec<EyeRoute>,
    pub observations: Vec<Observation>,
    pub shared_visual_state: SharedVisualState,
    pub compute_plan: ComputePlan,
}

#[derive(Clone, Debug, Default)]
struct StageDurations {
    total_ns: u128,
    routing_ns: u128,
    coordinate_transform_ns: u128,
    observation_ns: u128,
    fusion_ns: u128,
    compute_plan_ns: u128,
}

#[derive(Clone, Debug, Default)]
struct Counters {
    logical_bytes_read: u64,
    bytes_copied: u64,
    temporary_buffer_bytes: u64,
    overlap_numerator: usize,
    overlap_denominator: usize,
}

#[derive(Clone, Debug)]
struct PipelineRun {
    semantic: SemanticResult,
    durations: StageDurations,
    counters: Counters,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Measurement {
    pub value: Option<f64>,
    pub unit: String,
    pub status: String,
    pub reason: Option<String>,
    pub method: String,
}

impl Measurement {
    fn collected(value: f64, unit: &str, method: &str) -> Self {
        Self {
            value: Some(value),
            unit: unit.to_string(),
            status: "collected".to_string(),
            reason: None,
            method: method.to_string(),
        }
    }

    fn unsupported(unit: &str, status: &str, reason: &str, method: &str) -> Self {
        Self {
            value: None,
            unit: unit.to_string(),
            status: status.to_string(),
            reason: Some(reason.to_string()),
            method: method.to_string(),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct BenchmarkCase {
    pub profile_id: String,
    pub topology: String,
    pub warmups: usize,
    pub repetitions: usize,
    pub eye_count: usize,
    pub semantic_hash: String,
    pub semantic_result: SemanticResult,
    pub metrics: BTreeMap<String, Measurement>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Environment {
    pub implementation: String,
    pub package_version: String,
    pub operating_system: String,
    pub architecture: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct SuiteReport {
    pub schema_version: String,
    pub kind: String,
    pub implementation: String,
    pub benchmark_status: String,
    pub official_wan_baseline: bool,
    pub environment: Environment,
    pub profiles: Vec<String>,
    pub topologies: Vec<String>,
    pub warmups: usize,
    pub repetitions: usize,
    pub core_suite_wall_seconds: f64,
    pub cases: Vec<BenchmarkCase>,
    pub unsupported_metrics: Vec<UnsupportedMetric>,
}

pub const R2_RUN_KIND: &str = "m1_p0_r2_rust_compound_runtime";

#[derive(Clone, Debug, Serialize)]
pub struct R2StageDurations {
    pub total_ns: u128,
    pub routing_ns: u128,
    pub coordinate_transform_ns: u128,
    pub observation_ns: u128,
    pub fusion_ns: u128,
    pub compute_plan_ns: u128,
    pub receipt_metadata_ns: u128,
}

#[derive(Clone, Debug, Serialize)]
pub struct R2Counters {
    pub logical_bytes_read: u64,
    pub bytes_copied: u64,
    pub temporary_buffer_bytes: u64,
}

#[derive(Clone, Debug, Serialize)]
pub struct R2Sample {
    pub block_index: usize,
    pub order_index: usize,
    pub candidate_id: String,
    pub topology: String,
    pub semantic_hash: String,
    pub durations_ns: R2StageDurations,
    pub counters: R2Counters,
}

#[derive(Clone, Debug, Serialize)]
pub struct R2BatchReport {
    pub schema_version: String,
    pub run_kind: String,
    pub implementation: String,
    pub profile_id: String,
    pub seed: u64,
    pub warmups: usize,
    pub repetitions: usize,
    pub input_bytes: usize,
    pub suite_internal_wall_ns: u128,
    pub semantic_results: BTreeMap<String, SemanticResult>,
    pub samples: Vec<R2Sample>,
    pub copied_bytes: u64,
    pub temporary_input_bytes: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct R3CandidateSummary {
    pub candidate_id: String,
    pub topology: String,
    pub semantic_hash: String,
    pub input_sha256: String,
    pub eye_count: usize,
    pub observation_count: usize,
    pub fused_region_count: usize,
    pub compute_unit_count: usize,
    pub dirty_region_count: usize,
    pub stable_region_count: usize,
    pub uncertain_region_count: usize,
    pub generate_unit_count: usize,
    pub reuse_cache_unit_count: usize,
    pub reconcile_unit_count: usize,
    pub pipeline_total_ns: u128,
    pub logical_bytes_read: u64,
    pub bytes_copied: u64,
    pub temporary_buffer_bytes: u64,
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut digest = Sha256::new();
    digest.update(bytes);
    format!("{:x}", digest.finalize())
}

pub fn semantic_hash(result: &SemanticResult) -> Result<String, String> {
    serde_json::to_vec(result)
        .map(|value| sha256_hex(&value))
        .map_err(|error| format!("Cannot serialize semantic result: {error}"))
}

pub fn generate_sequence(profile: &InputProfile) -> Result<Vec<u8>, String> {
    let total = profile.byte_length();
    let pixels = profile.pixels();
    let mut sequence = vec![0_u8; total];
    for frame in 0..profile.frames {
        let frame_offset = frame * pixels;
        for y in 0..profile.height {
            for x in 0..profile.width {
                let base = (profile
                    .seed
                    .wrapping_add((x as u64).wrapping_mul(3))
                    .wrapping_add((y as u64).wrapping_mul(5))
                    % 64) as u8;
                sequence[frame_offset + y * profile.width + x] = base;
            }
        }
    }
    for frame in (profile.frames / 2)..profile.frames {
        let frame_offset = frame * pixels;
        for region in &profile.change_regions {
            for y in region.y..region.y2() {
                for x in region.x..region.x2() {
                    let index = frame_offset + y * profile.width + x;
                    sequence[index] = sequence[index].saturating_add(160);
                }
            }
        }
    }
    validate_sequence(profile, &sequence)?;
    Ok(sequence)
}

pub fn validate_sequence(profile: &InputProfile, sequence: &[u8]) -> Result<(), String> {
    if profile.frames < 2 || profile.width == 0 || profile.height == 0 {
        return Err(
            "Input shape must contain at least two non-empty grayscale frames.".to_string(),
        );
    }
    if sequence.len() != profile.byte_length() {
        return Err(format!(
            "Input byte length {} does not match declared shape {}.",
            sequence.len(),
            profile.byte_length()
        ));
    }
    Ok(())
}

fn compute_motion_map(profile: &InputProfile, sequence: &[u8]) -> (Vec<u8>, u64) {
    let pixels = profile.pixels();
    let mut motion = vec![0_u8; pixels];
    let mut logical_reads = 0_u64;
    for frame in 1..profile.frames {
        let previous = (frame - 1) * pixels;
        let current = frame * pixels;
        for pixel in 0..pixels {
            logical_reads += 2;
            if sequence[previous + pixel] != sequence[current + pixel] {
                motion[pixel] = 1;
            }
        }
    }
    (motion, logical_reads)
}

fn motion_bbox(profile: &InputProfile, motion: &[u8]) -> Option<PixelBox> {
    let mut min_x = profile.width;
    let mut min_y = profile.height;
    let mut max_x = 0;
    let mut max_y = 0;
    let mut found = false;
    for y in 0..profile.height {
        for x in 0..profile.width {
            if motion[y * profile.width + x] != 0 {
                found = true;
                min_x = min_x.min(x);
                min_y = min_y.min(y);
                max_x = max_x.max(x);
                max_y = max_y.max(y);
            }
        }
    }
    found.then(|| PixelBox {
        x: min_x,
        y: min_y,
        width: max_x - min_x + 1,
        height: max_y - min_y + 1,
    })
}

fn grid_boxes(profile: &InputProfile, columns: usize, rows: usize) -> Vec<PixelBox> {
    let mut boxes = Vec::with_capacity(columns * rows);
    for row in 0..rows {
        let y = row * profile.height / rows;
        let y2 = (row + 1) * profile.height / rows;
        for column in 0..columns {
            let x = column * profile.width / columns;
            let x2 = (column + 1) * profile.width / columns;
            boxes.push(PixelBox {
                x,
                y,
                width: x2 - x,
                height: y2 - y,
            });
        }
    }
    boxes
}

fn eye_route(
    eye_id: String,
    eye_type: &str,
    receptive_field: PixelBox,
    write_scope: Option<PixelBox>,
    overlap: bool,
) -> EyeRoute {
    EyeRoute {
        eye_id,
        eye_type: eye_type.to_string(),
        local_to_global: [receptive_field.x, receptive_field.y],
        receptive_field,
        write_scope,
        overlap,
    }
}

fn route_eyes(
    profile: &InputProfile,
    topology: Topology,
    motion: Option<&[u8]>,
) -> Result<Vec<EyeRoute>, String> {
    let full = PixelBox::new(0, 0, profile.width, profile.height)?;
    let global = || {
        eye_route(
            "global-context".to_string(),
            "global_context",
            full.clone(),
            None,
            false,
        )
    };
    let routes = match topology {
        Topology::Mono1x1 => vec![eye_route(
            "mono-0".to_string(),
            "mono",
            full.clone(),
            Some(full),
            false,
        )],
        Topology::Uniform2x2 => {
            let mut items = vec![global()];
            items.extend(grid_boxes(profile, 2, 2).into_iter().enumerate().map(
                |(index, scope)| {
                    eye_route(
                        format!("regional-2x2-{index:02}"),
                        "regional",
                        scope.clone(),
                        Some(scope),
                        false,
                    )
                },
            ));
            items
        }
        Topology::Uniform4x4 => {
            let mut items = vec![global()];
            items.extend(grid_boxes(profile, 4, 4).into_iter().enumerate().map(
                |(index, scope)| {
                    eye_route(
                        format!("regional-4x4-{index:02}"),
                        "regional",
                        scope.clone(),
                        Some(scope),
                        false,
                    )
                },
            ));
            items
        }
        Topology::Overlap2x2 => {
            let halo = (profile.width.min(profile.height) / 32).max(4);
            let mut items = vec![global()];
            items.extend(grid_boxes(profile, 2, 2).into_iter().enumerate().map(
                |(index, scope)| {
                    let receptive = scope.expand(halo, profile.width, profile.height);
                    eye_route(
                        format!("overlap-2x2-{index:02}"),
                        "overlap_regional",
                        receptive,
                        Some(scope),
                        true,
                    )
                },
            ));
            items
        }
        Topology::MotionFocused => {
            let motion = motion.ok_or_else(|| {
                "motion_focused routing requires a frame-difference map.".to_string()
            })?;
            let mut items = vec![
                global(),
                eye_route(
                    "motion-detector".to_string(),
                    "motion_detector",
                    full.clone(),
                    None,
                    false,
                ),
            ];
            if let Some(scope) = motion_bbox(profile, motion) {
                let halo = (profile.width.min(profile.height) / 64).max(2);
                let expanded = scope.expand(halo, profile.width, profile.height);
                items.push(eye_route(
                    "motion-focus-00".to_string(),
                    "motion_focused",
                    expanded.clone(),
                    Some(expanded),
                    false,
                ));
            }
            items
        }
    };
    Ok(routes)
}

fn changed_count(profile: &InputProfile, motion: &[u8], region: &PixelBox) -> usize {
    let mut count = 0;
    for y in region.y..region.y2() {
        for x in region.x..region.x2() {
            count += usize::from(motion[y * profile.width + x] != 0);
        }
    }
    count
}

fn motion_bbox_in(profile: &InputProfile, motion: &[u8], region: &PixelBox) -> Option<PixelBox> {
    let mut min_x = region.x2();
    let mut min_y = region.y2();
    let mut max_x = region.x;
    let mut max_y = region.y;
    let mut found = false;
    for y in region.y..region.y2() {
        for x in region.x..region.x2() {
            if motion[y * profile.width + x] != 0 {
                found = true;
                min_x = min_x.min(x);
                min_y = min_y.min(y);
                max_x = max_x.max(x);
                max_y = max_y.max(y);
            }
        }
    }
    found.then(|| PixelBox {
        x: min_x,
        y: min_y,
        width: max_x - min_x + 1,
        height: max_y - min_y + 1,
    })
}

fn region_checksum(profile: &InputProfile, sequence: &[u8], region: &PixelBox) -> (u64, u64) {
    let pixels = profile.pixels();
    let mut checksum = 0_u64;
    let mut reads = 0_u64;
    for frame in 0..profile.frames {
        let frame_offset = frame * pixels;
        for y in region.y..region.y2() {
            for x in region.x..region.x2() {
                checksum = checksum
                    .wrapping_add(u64::from(sequence[frame_offset + y * profile.width + x]));
                reads += 1;
            }
        }
    }
    (checksum, reads)
}

fn observe(
    profile: &InputProfile,
    sequence: &[u8],
    input_sha256: &str,
    routes: &[EyeRoute],
    motion: &[u8],
) -> (Vec<Observation>, u64) {
    let mut logical_reads = 0_u64;
    let observations = routes
        .iter()
        .map(|route| {
            let receptive_changed = changed_count(profile, motion, &route.receptive_field);
            let write_changed = route
                .write_scope
                .as_ref()
                .map_or(0, |scope| changed_count(profile, motion, scope));
            let (checksum, reads) = region_checksum(profile, sequence, &route.receptive_field);
            logical_reads += reads;
            let state = if route.write_scope.is_none() {
                "uncertain"
            } else if write_changed > 0 {
                "dirty"
            } else if receptive_changed > 0 {
                "uncertain"
            } else {
                "stable"
            };
            let confidence = match state {
                "dirty" => 0.99,
                "stable" => 0.9,
                _ => 0.75,
            };
            Observation {
                observation_id: format!("{}:{}", profile.profile_id, route.eye_id),
                eye_id: route.eye_id.clone(),
                state: state.to_string(),
                changed_pixels: receptive_changed,
                motion_bbox: motion_bbox_in(profile, motion, &route.receptive_field),
                region_checksum: checksum,
                confidence,
                provenance: Provenance {
                    source_sequence_id: profile.profile_id.clone(),
                    algorithm: "packed_u8_frame_difference_v0".to_string(),
                    input_sha256: input_sha256.to_string(),
                },
            }
        })
        .collect();
    (observations, logical_reads)
}

fn fuse(routes: &[EyeRoute], observations: &[Observation]) -> SharedVisualState {
    let global_source = routes
        .iter()
        .find(|route| route.eye_type == "global_context")
        .map(|route| {
            format!(
                "{}:{}",
                observations[0].provenance.source_sequence_id, route.eye_id
            )
        });
    let motion_source = routes
        .iter()
        .find(|route| route.eye_type == "motion_detector")
        .map(|route| {
            format!(
                "{}:{}",
                observations[0].provenance.source_sequence_id, route.eye_id
            )
        });
    let mut regions = Vec::new();
    for (route_index, route) in routes.iter().enumerate() {
        let Some(scope) = route.write_scope.clone() else {
            continue;
        };
        let primary = &observations[route_index];
        let mut state = primary.state.clone();
        let mut sources = Vec::new();
        if let Some(source) = &global_source {
            sources.push(source.clone());
        }
        if let Some(source) = &motion_source {
            sources.push(source.clone());
        }
        sources.push(primary.observation_id.clone());
        if route.overlap {
            for (other_index, other_route) in routes.iter().enumerate() {
                if other_index == route_index || other_route.write_scope.is_none() {
                    continue;
                }
                let other = &observations[other_index];
                if other_route.receptive_field.intersects(&scope)
                    && other.changed_pixels > 0
                    && other.state != primary.state
                {
                    state = "uncertain".to_string();
                    sources.push(other.observation_id.clone());
                }
            }
        }
        sources.sort();
        sources.dedup();
        regions.push(FusedRegion {
            region_id: format!("fused:{}", route.eye_id),
            scope,
            state,
            confidence: primary.confidence,
            sources,
        });
    }
    let mut observation_ids = observations
        .iter()
        .map(|observation| observation.observation_id.clone())
        .collect::<Vec<_>>();
    observation_ids.sort();
    SharedVisualState {
        policy: "deterministic_conservative_io_v0".to_string(),
        regions,
        observation_ids,
    }
}

fn compile_plan(state: &SharedVisualState) -> ComputePlan {
    let units = state
        .regions
        .iter()
        .enumerate()
        .map(|(index, region)| ComputeUnit {
            unit_id: format!("unit-{index:03}"),
            action: match region.state.as_str() {
                "dirty" => "generate",
                "stable" => "reuse_cache",
                _ => "reconcile",
            }
            .to_string(),
            scope: region.scope.clone(),
            source_observation_ids: region.sources.clone(),
        })
        .collect();
    ComputePlan {
        policy: "backend_neutral_candidate_v0".to_string(),
        units,
        claims: vec![
            UnsupportedMetric::new(
                "actual_sparse_speedup",
                "ratio",
                "uncollected",
                "The admission probe does not execute a model backend.",
                "requires a same-condition backend experiment",
            ),
            UnsupportedMetric::new(
                "gpu_kernel_seconds",
                "seconds",
                "unsupported",
                "The admission probe has no CUDA execution path.",
                "requires a separate GPU profiler run",
            ),
        ],
    }
}

fn validate_semantic(result: &SemanticResult) -> Result<(), String> {
    if result.input.frames < 2 || result.input.width == 0 || result.input.height == 0 {
        return Err("Semantic result contains an invalid input shape.".to_string());
    }
    for route in &result.eyes {
        if route.local_to_global != [route.receptive_field.x, route.receptive_field.y] {
            return Err("Local-to-global offset differs from receptive origin.".to_string());
        }
        if let Some(scope) = &route.write_scope {
            if !route.receptive_field.contains(scope) {
                return Err("Write scope exceeds the eye receptive field.".to_string());
            }
        }
    }
    for claim in &result.compute_plan.claims {
        if claim.value.is_some() || !matches!(claim.status.as_str(), "unsupported" | "uncollected")
        {
            return Err("Unsupported metrics require null values and explicit status.".to_string());
        }
    }
    Ok(())
}

fn run_pipeline(
    profile: &InputProfile,
    topology: Topology,
    sequence: &[u8],
) -> Result<PipelineRun, String> {
    validate_sequence(profile, sequence)?;
    let total_start = Instant::now();
    let input_sha256 = sha256_hex(sequence);
    let mut counters = Counters::default();

    let routing_start = Instant::now();
    let precomputed_motion = if topology == Topology::MotionFocused {
        let (motion, reads) = compute_motion_map(profile, sequence);
        counters.logical_bytes_read += reads;
        counters.temporary_buffer_bytes += motion.len() as u64;
        Some(motion)
    } else {
        None
    };
    let routes = route_eyes(profile, topology, precomputed_motion.as_deref())?;
    let routing_ns = routing_start.elapsed().as_nanos();

    let coordinate_start = Instant::now();
    let transform_checksum = routes.iter().fold(0_usize, |sum, route| {
        sum.wrapping_add(route.local_to_global[0])
            .wrapping_add(route.local_to_global[1])
            .wrapping_add(route.receptive_field.width)
            .wrapping_add(route.receptive_field.height)
    });
    black_box(transform_checksum);
    let coordinate_transform_ns = coordinate_start.elapsed().as_nanos();

    let observation_start = Instant::now();
    let owned_motion;
    let motion = if let Some(motion) = precomputed_motion.as_deref() {
        motion
    } else {
        let (motion, reads) = compute_motion_map(profile, sequence);
        counters.logical_bytes_read += reads;
        counters.temporary_buffer_bytes += motion.len() as u64;
        owned_motion = motion;
        &owned_motion
    };
    let (observations, observation_reads) =
        observe(profile, sequence, &input_sha256, &routes, motion);
    counters.logical_bytes_read += observation_reads;
    let observation_ns = observation_start.elapsed().as_nanos();

    let fusion_start = Instant::now();
    let shared_visual_state = fuse(&routes, &observations);
    let fusion_ns = fusion_start.elapsed().as_nanos();

    let plan_start = Instant::now();
    let compute_plan = compile_plan(&shared_visual_state);
    let compute_plan_ns = plan_start.elapsed().as_nanos();

    for route in &routes {
        if let Some(scope) = &route.write_scope {
            counters.overlap_denominator += scope.area();
            counters.overlap_numerator += route.receptive_field.area().saturating_sub(scope.area());
        }
    }
    let semantic = SemanticResult {
        schema_version: SCHEMA_VERSION.to_string(),
        profile_id: profile.profile_id.clone(),
        topology: topology.as_str().to_string(),
        input: InputIdentity {
            width: profile.width,
            height: profile.height,
            frames: profile.frames,
            seed: profile.seed,
            byte_length: sequence.len(),
            sha256: input_sha256,
        },
        eyes: routes,
        observations,
        shared_visual_state,
        compute_plan,
    };
    validate_semantic(&semantic)?;
    Ok(PipelineRun {
        semantic,
        durations: StageDurations {
            total_ns: total_start.elapsed().as_nanos(),
            routing_ns,
            coordinate_transform_ns,
            observation_ns,
            fusion_ns,
            compute_plan_ns,
        },
        counters,
    })
}

pub fn run_r3_candidate(
    profile: &InputProfile,
    candidate_id: &str,
    sequence: &[u8],
) -> Result<R3CandidateSummary, String> {
    let topology = match candidate_id {
        "T0" => Topology::Mono1x1,
        "T1" => Topology::Uniform2x2,
        "T2" => Topology::MotionFocused,
        _ => return Err(format!("R3 does not admit candidate: {candidate_id}")),
    };
    let run = run_pipeline(profile, topology, sequence)?;
    let digest = semantic_hash(&run.semantic)?;
    let count_regions = |state: &str| {
        run.semantic
            .shared_visual_state
            .regions
            .iter()
            .filter(|region| region.state == state)
            .count()
    };
    let count_units = |action: &str| {
        run.semantic
            .compute_plan
            .units
            .iter()
            .filter(|unit| unit.action == action)
            .count()
    };
    Ok(R3CandidateSummary {
        candidate_id: candidate_id.to_string(),
        topology: topology.as_str().to_string(),
        semantic_hash: digest,
        input_sha256: run.semantic.input.sha256.clone(),
        eye_count: run.semantic.eyes.len(),
        observation_count: run.semantic.observations.len(),
        fused_region_count: run.semantic.shared_visual_state.regions.len(),
        compute_unit_count: run.semantic.compute_plan.units.len(),
        dirty_region_count: count_regions("dirty"),
        stable_region_count: count_regions("stable"),
        uncertain_region_count: count_regions("uncertain"),
        generate_unit_count: count_units("generate"),
        reuse_cache_unit_count: count_units("reuse_cache"),
        reconcile_unit_count: count_units("reconcile"),
        pipeline_total_ns: run.durations.total_ns,
        logical_bytes_read: run.counters.logical_bytes_read,
        bytes_copied: run.counters.bytes_copied,
        temporary_buffer_bytes: run.counters.temporary_buffer_bytes,
    })
}

fn r2_candidate_order(seed: u64, phase: &str, block_index: usize) -> Vec<(&'static str, Topology)> {
    let mut candidates = vec![
        ("T0", Topology::Mono1x1),
        ("T1", Topology::Uniform2x2),
        ("T2", Topology::MotionFocused),
    ];
    candidates.sort_by_key(|(candidate, _)| {
        let mut digest = Sha256::new();
        digest.update(format!("{seed}:{phase}:{block_index}:{candidate}").as_bytes());
        digest.finalize().to_vec()
    });
    candidates
}

pub fn benchmark_r2_batch(
    profile: &InputProfile,
    sequence: &[u8],
    warmups: usize,
    repetitions: usize,
) -> Result<R2BatchReport, String> {
    if warmups != 5 || repetitions != 20 {
        return Err("R2 is fixed at 5 warm-ups and 20 measured blocks.".to_string());
    }
    validate_sequence(profile, sequence)?;
    let suite_started = Instant::now();
    let mut expected_hashes = BTreeMap::new();
    let mut semantic_results = BTreeMap::new();
    for (candidate, topology) in r2_candidate_order(profile.seed, "baseline", 0) {
        let baseline = run_pipeline(profile, topology, sequence)?;
        let digest = semantic_hash(&baseline.semantic)?;
        expected_hashes.insert(candidate.to_string(), digest);
        semantic_results.insert(candidate.to_string(), baseline.semantic);
    }
    for block_index in 0..warmups {
        for (candidate, topology) in r2_candidate_order(profile.seed, "warmup", block_index) {
            let run = run_pipeline(profile, topology, sequence)?;
            if semantic_hash(&run.semantic)? != expected_hashes[candidate] {
                return Err(format!("R2 warm-up semantic hash changed for {candidate}."));
            }
        }
    }
    let mut samples = Vec::with_capacity(repetitions * 3);
    for block_index in 0..repetitions {
        for (order_index, (candidate, topology)) in
            r2_candidate_order(profile.seed, "measured", block_index)
                .into_iter()
                .enumerate()
        {
            let run = run_pipeline(profile, topology, sequence)?;
            let receipt_started = Instant::now();
            let digest = semantic_hash(&run.semantic)?;
            let receipt_metadata_ns = receipt_started.elapsed().as_nanos();
            if digest != expected_hashes[candidate] {
                return Err(format!(
                    "R2 measured semantic hash changed for {candidate}."
                ));
            }
            samples.push(R2Sample {
                block_index,
                order_index,
                candidate_id: candidate.to_string(),
                topology: topology.as_str().to_string(),
                semantic_hash: digest,
                durations_ns: R2StageDurations {
                    total_ns: run.durations.total_ns + receipt_metadata_ns,
                    routing_ns: run.durations.routing_ns,
                    coordinate_transform_ns: run.durations.coordinate_transform_ns,
                    observation_ns: run.durations.observation_ns,
                    fusion_ns: run.durations.fusion_ns,
                    compute_plan_ns: run.durations.compute_plan_ns,
                    receipt_metadata_ns,
                },
                counters: R2Counters {
                    logical_bytes_read: run.counters.logical_bytes_read,
                    bytes_copied: run.counters.bytes_copied,
                    temporary_buffer_bytes: run.counters.temporary_buffer_bytes,
                },
            });
        }
    }
    Ok(R2BatchReport {
        schema_version: SCHEMA_VERSION.to_string(),
        run_kind: R2_RUN_KIND.to_string(),
        implementation: "rust_coarse_process_batch_v0".to_string(),
        profile_id: profile.profile_id.clone(),
        seed: profile.seed,
        warmups,
        repetitions,
        input_bytes: sequence.len(),
        suite_internal_wall_ns: suite_started.elapsed().as_nanos(),
        semantic_results,
        samples,
        copied_bytes: 0,
        temporary_input_bytes: 0,
    })
}

fn percentile(values: &mut [u128], quantile: f64) -> u128 {
    values.sort_unstable();
    let rank = (quantile * values.len() as f64).ceil() as usize;
    values[rank.saturating_sub(1).min(values.len() - 1)]
}

fn mean_seconds(values: &[u128]) -> f64 {
    values.iter().sum::<u128>() as f64 / values.len() as f64 / 1_000_000_000.0
}

pub fn benchmark_case(
    profile: &InputProfile,
    topology: Topology,
    warmups: usize,
    repetitions: usize,
) -> Result<BenchmarkCase, String> {
    if repetitions == 0 {
        return Err("Measured repetitions must be positive.".to_string());
    }
    let sequence = generate_sequence(profile)?;
    let baseline = run_pipeline(profile, topology, &sequence)?;
    let expected_hash = semantic_hash(&baseline.semantic)?;
    for _ in 0..warmups {
        let warm = run_pipeline(profile, topology, &sequence)?;
        if semantic_hash(&warm.semantic)? != expected_hash {
            return Err("Warm-up semantic hash changed.".to_string());
        }
    }

    let mut totals = Vec::with_capacity(repetitions);
    let mut routing = Vec::with_capacity(repetitions);
    let mut coordinates = Vec::with_capacity(repetitions);
    let mut observations = Vec::with_capacity(repetitions);
    let mut fusion = Vec::with_capacity(repetitions);
    let mut planning = Vec::with_capacity(repetitions);
    let mut last_counters = Counters::default();
    for _ in 0..repetitions {
        let run = run_pipeline(profile, topology, &sequence)?;
        if semantic_hash(&run.semantic)? != expected_hash {
            return Err("Measured semantic hash changed.".to_string());
        }
        totals.push(run.durations.total_ns);
        routing.push(run.durations.routing_ns);
        coordinates.push(run.durations.coordinate_transform_ns);
        observations.push(run.durations.observation_ns);
        fusion.push(run.durations.fusion_ns);
        planning.push(run.durations.compute_plan_ns);
        last_counters = run.counters;
    }
    let p50_ns = percentile(&mut totals.clone(), 0.50);
    let p95_ns = percentile(&mut totals.clone(), 0.95);
    let p50_seconds = p50_ns as f64 / 1_000_000_000.0;
    let overlap_ratio = if last_counters.overlap_denominator == 0 {
        0.0
    } else {
        last_counters.overlap_numerator as f64 / last_counters.overlap_denominator as f64
    };

    let mut metrics = BTreeMap::new();
    metrics.insert(
        "total_wall_seconds_mean".to_string(),
        Measurement::collected(mean_seconds(&totals), "seconds", "steady_clock_mean"),
    );
    metrics.insert(
        "p50_latency_seconds".to_string(),
        Measurement::collected(p50_seconds, "seconds", "nearest_rank"),
    );
    metrics.insert(
        "p95_latency_seconds".to_string(),
        Measurement::collected(p95_ns as f64 / 1_000_000_000.0, "seconds", "nearest_rank"),
    );
    metrics.insert(
        "routing_seconds_mean".to_string(),
        Measurement::collected(mean_seconds(&routing), "seconds", "steady_clock_mean"),
    );
    metrics.insert(
        "coordinate_transform_seconds_mean".to_string(),
        Measurement::collected(mean_seconds(&coordinates), "seconds", "steady_clock_mean"),
    );
    metrics.insert(
        "observation_seconds_mean".to_string(),
        Measurement::collected(mean_seconds(&observations), "seconds", "steady_clock_mean"),
    );
    metrics.insert(
        "fusion_seconds_mean".to_string(),
        Measurement::collected(mean_seconds(&fusion), "seconds", "steady_clock_mean"),
    );
    metrics.insert(
        "compute_plan_seconds_mean".to_string(),
        Measurement::collected(mean_seconds(&planning), "seconds", "steady_clock_mean"),
    );
    metrics.insert(
        "frames_per_second".to_string(),
        Measurement::collected(
            profile.frames as f64 / p50_seconds,
            "frames/second",
            "frames divided by p50 core latency",
        ),
    );
    metrics.insert(
        "bytes_processed".to_string(),
        Measurement::collected(sequence.len() as f64, "bytes", "packed input length"),
    );
    metrics.insert(
        "logical_bytes_read".to_string(),
        Measurement::collected(
            last_counters.logical_bytes_read as f64,
            "bytes",
            "algorithmic read accounting",
        ),
    );
    metrics.insert(
        "bytes_copied".to_string(),
        Measurement::collected(
            last_counters.bytes_copied as f64,
            "bytes",
            "explicit pixel-buffer copies",
        ),
    );
    metrics.insert(
        "temporary_buffer_bytes".to_string(),
        Measurement::collected(
            last_counters.temporary_buffer_bytes as f64,
            "bytes",
            "dominant pixel-sized temporary buffers",
        ),
    );
    metrics.insert(
        "overlap_ratio".to_string(),
        Measurement::collected(overlap_ratio, "ratio", "extra receptive area / write area"),
    );
    metrics.insert(
        "peak_rss_bytes".to_string(),
        Measurement::unsupported(
            "bytes",
            "uncollected",
            "No dependency-free portable per-case peak RSS sampler is installed.",
            "requires a separate process sampler",
        ),
    );
    metrics.insert(
        "allocation_count".to_string(),
        Measurement::unsupported(
            "allocations",
            "unsupported",
            "The system allocator is not instrumented in this probe.",
            "requires an instrumented allocator",
        ),
    );
    metrics.insert(
        "process_cpu_seconds".to_string(),
        Measurement::unsupported(
            "seconds",
            "uncollected",
            "Portable process CPU timing is outside the dependency-free core.",
            "requires an operating-system process timer",
        ),
    );
    metrics.insert(
        "thread_count".to_string(),
        Measurement::unsupported(
            "threads",
            "uncollected",
            "The single-threaded contract is asserted by implementation, not sampled.",
            "requires an operating-system process sampler",
        ),
    );

    Ok(BenchmarkCase {
        profile_id: profile.profile_id.clone(),
        topology: topology.as_str().to_string(),
        warmups,
        repetitions,
        eye_count: baseline.semantic.eyes.len(),
        semantic_hash: expected_hash,
        semantic_result: baseline.semantic,
        metrics,
    })
}

pub fn benchmark_suite(
    profile_names: &[String],
    topology_names: &[String],
    seed: u64,
    warmups: usize,
    repetitions: usize,
) -> Result<SuiteReport, String> {
    let suite_start = Instant::now();
    let mut cases = Vec::new();
    for profile_name in profile_names {
        let profile = InputProfile::named(profile_name, seed)?;
        for topology_name in topology_names {
            cases.push(benchmark_case(
                &profile,
                Topology::parse(topology_name)?,
                warmups,
                repetitions,
            )?);
        }
    }
    Ok(SuiteReport {
        schema_version: SCHEMA_VERSION.to_string(),
        kind: RUN_KIND.to_string(),
        implementation: "rust".to_string(),
        benchmark_status: "model_free_orchestration_admission".to_string(),
        official_wan_baseline: false,
        environment: Environment {
            implementation: "rust".to_string(),
            package_version: env!("CARGO_PKG_VERSION").to_string(),
            operating_system: std::env::consts::OS.to_string(),
            architecture: std::env::consts::ARCH.to_string(),
        },
        profiles: profile_names.to_vec(),
        topologies: topology_names.to_vec(),
        warmups,
        repetitions,
        core_suite_wall_seconds: suite_start.elapsed().as_secs_f64(),
        cases,
        unsupported_metrics: vec![
            UnsupportedMetric::new(
                "ffi_end_to_end_seconds",
                "seconds",
                "uncollected",
                "PyO3 and FFI are outside this admission probe.",
                "requires a separate shared-buffer integration experiment",
            ),
            UnsupportedMetric::new(
                "estimated_wan_end_to_end_gain",
                "ratio",
                "uncollected",
                "M0 does not contain an eligible isolated input-orchestration span.",
                "requires an attributable same-condition M0 input-side span",
            ),
        ],
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn c1_observation() -> StepObservation {
        StepObservation {
            abi_version: C1_STEP_POLICY_ABI_VERSION,
            struct_size: StepObservation::contract_size(),
            run_digest: [1; 32],
            workflow_revision_digest: [2; 32],
            settings_digest: [3; 32],
            step_index: 7,
            total_steps: 20,
            sampler_logical_id: 1,
            scheduler_logical_id: 1,
            timestep_available: 0,
            timestep_bits: 0,
            sigma_available: 0,
            sigma_bits: 0,
            uncertainty_flags: 0,
            invalidation_flags: 0,
            full_compute_supported: 1,
            fallback_supported: 1,
            cache_available: 0,
            receipt_required: 1,
            unsupported_flags: 0,
        }
    }

    #[test]
    fn c1_full_compute_policy_is_deterministic_and_never_skips() {
        let observation = c1_observation();
        let first = evaluate_step_policy(&observation);
        let second = evaluate_step_policy(&observation);
        assert_eq!(first, second);
        assert_eq!(first.decision_code, C1_DECISION_FULL_COMPUTE);
        assert_eq!(first.reason_code, C1_REASON_NONE);
        assert_eq!(first.skipped_step_count, 0);
        assert_eq!(first.skipped_block_count, 0);
        assert_eq!(first.skipped_token_count, 0);
        assert_eq!(first.skipped_latent_count, 0);
        assert_eq!(first.reused_cache_count, 0);
        assert_eq!(first.partial_compute_count, 0);
    }

    #[test]
    fn c1_abnormal_metadata_escalates_to_full_compute() {
        let mut observation = c1_observation();
        observation.uncertainty_flags = 1;
        let result = evaluate_step_policy(&observation);
        assert_eq!(result.decision_code, C1_DECISION_ESCALATE_FULL_COMPUTE);
        assert_eq!(result.reason_code, C1_REASON_UNCERTAINTY_PRESENT);
        assert_eq!(result.skipped_step_count, 0);
        assert_eq!(result.reused_cache_count, 0);
        assert_eq!(result.partial_compute_count, 0);
    }

    #[test]
    fn c1_contract_sizes_are_fixed_and_self_describing() {
        assert_eq!(
            StepObservation::contract_size() as usize,
            std::mem::size_of::<StepObservation>()
        );
        assert_eq!(
            StepDirective::contract_size() as usize,
            std::mem::size_of::<StepDirective>()
        );
        assert!(StepObservation::contract_size() >= 128);
        assert!(StepDirective::contract_size() >= 64);
    }

    fn c2_observation() -> CompoundEyeShadowObservation {
        let mut previous = [4_096; C2_SKETCH_VALUE_COUNT];
        let mut current = previous;
        // Bottom-right receptive field changes clearly while the other three
        // regional views remain at or below the stable threshold.
        for metric in 0..3 {
            current[15 * 3 + metric] = 8_192;
        }
        previous[0] = 4_096;
        CompoundEyeShadowObservation {
            abi_version: C2_COMPOUND_EYE_SHADOW_ABI_VERSION,
            struct_size: CompoundEyeShadowObservation::contract_size(),
            run_digest: [4; 32],
            workflow_revision_digest: [5; 32],
            settings_digest: [6; 32],
            step_index: 7,
            total_steps: 20,
            topology_id: C2_TOPOLOGY_OVERLAP_2X2,
            sketch_source_id: C2_SKETCH_SOURCE_X0,
            quantization_scale: 4_096,
            previous_available: 1,
            uncertainty_flags: 0,
            invalidation_flags: 0,
            full_compute_supported: 1,
            fallback_supported: 1,
            receipt_required: 1,
            unsupported_flags: 0,
            current_sketch_q: current,
            previous_sketch_q: previous,
        }
    }

    #[test]
    fn c2_contract_is_fixed_and_distinct_from_c1() {
        assert_eq!(
            CompoundEyeShadowObservation::contract_size() as usize,
            std::mem::size_of::<CompoundEyeShadowObservation>()
        );
        assert_eq!(
            CompoundEyeShadowDirective::contract_size() as usize,
            std::mem::size_of::<CompoundEyeShadowDirective>()
        );
        assert_ne!(
            CompoundEyeShadowObservation::contract_size(),
            StepObservation::contract_size()
        );
        assert_ne!(
            CompoundEyeShadowDirective::contract_size(),
            StepDirective::contract_size()
        );
        assert_eq!(C2_SKETCH_VALUE_COUNT, 48);
        assert_eq!(C2_EYE_COUNT, 5);
    }

    #[test]
    fn c2_shadow_policy_is_deterministic_and_never_skips() {
        let observation = c2_observation();
        let first = evaluate_compound_eye_shadow_policy(&observation);
        let second = evaluate_compound_eye_shadow_policy(&observation);
        assert_eq!(first, second);
        assert_eq!(first.decision_code, C2_DECISION_FULL_COMPUTE);
        assert_eq!(first.skipped_step_count, 0);
        assert_eq!(first.skipped_block_count, 0);
        assert_eq!(first.skipped_token_count, 0);
        assert_eq!(first.skipped_latent_count, 0);
        assert_eq!(first.reused_cache_count, 0);
        assert_eq!(first.partial_compute_count, 0);
        assert_eq!(
            first.stable_eye_count + first.active_eye_count + first.uncertain_eye_count,
            4
        );
    }

    #[test]
    fn c2_first_and_warmup_callbacks_have_no_stable_eye() {
        let mut observation = c2_observation();
        observation.previous_available = 0;
        observation.step_index = 0;
        let first = evaluate_compound_eye_shadow_policy(&observation);
        assert_eq!(first.stable_eye_count, 0);
        assert_eq!(first.uncertain_eye_count, 4);

        observation.previous_available = 1;
        observation.step_index = 1;
        let warmup = evaluate_compound_eye_shadow_policy(&observation);
        assert_eq!(warmup.stable_eye_count, 0);
    }

    #[test]
    fn c2_synthetic_stable_active_and_uncertain_states_are_bounded() {
        let directive = evaluate_compound_eye_shadow_policy(&c2_observation());
        assert!(directive.eye_state[1..].iter().all(|state| matches!(
            *state,
            C2_EYE_STATE_STABLE | C2_EYE_STATE_ACTIVE | C2_EYE_STATE_UNCERTAIN
        )));
        assert_eq!(directive.eye_state[0], C2_EYE_STATE_UNCERTAIN);
        assert!(directive.stable_eye_count >= 1);
        assert!(directive.active_eye_count >= 1);
        assert!(directive.uncertain_eye_count >= 1);
        assert_eq!(directive.candidate_reuse_count, directive.stable_eye_count);
        assert_eq!(
            directive.candidate_generate_count,
            directive.active_eye_count
        );
        assert_eq!(
            directive.candidate_reconcile_count,
            directive.uncertain_eye_count
        );
    }

    #[test]
    fn c2_global_invalidation_disallows_stable_candidates() {
        let mut observation = c2_observation();
        observation.current_sketch_q.fill(16_384);
        let directive = evaluate_compound_eye_shadow_policy(&observation);
        assert_eq!(directive.global_invalidation, 1);
        assert_eq!(directive.stable_eye_count, 0);
        assert_eq!(directive.active_eye_count, 4);
    }

    #[test]
    fn c2_overlap_stable_active_conflict_escalates_stable_to_uncertain() {
        let mut observation = c2_observation();
        observation.current_sketch_q = observation.previous_sketch_q;
        // Drive only the top-right edge high enough that an adjacent low-change
        // regional candidate conflicts across its halo.
        for cell in [3, 7, 11] {
            for metric in 0..3 {
                observation.current_sketch_q[cell * 3 + metric] = 16_384;
            }
        }
        let directive = evaluate_compound_eye_shadow_policy(&observation);
        assert!(directive.overlap_conflict_mask != 0 || directive.stable_eye_count == 0);
        assert_eq!(directive.skipped_step_count, 0);
    }

    #[test]
    fn c2_invalid_metadata_and_nonfinite_flag_fail_open() {
        let mut invalid_abi = c2_observation();
        invalid_abi.abi_version = 99;
        let directive = evaluate_compound_eye_shadow_policy(&invalid_abi);
        assert_eq!(directive.decision_code, C2_DECISION_ESCALATE_FULL_COMPUTE);
        assert_eq!(directive.reason_code, C2_REASON_ABI_MISMATCH);

        let mut nonfinite = c2_observation();
        nonfinite.uncertainty_flags = 1;
        let directive = evaluate_compound_eye_shadow_policy(&nonfinite);
        assert_eq!(directive.decision_code, C2_DECISION_ESCALATE_FULL_COMPUTE);
        assert_eq!(directive.stable_eye_count, 0);
        assert_eq!(directive.skipped_step_count, 0);
    }

    fn a1_observation() -> AttentionRegionPlanObservation {
        AttentionRegionPlanObservation {
            abi_version: A1_ATTENTION_REGION_PLAN_ABI_VERSION,
            struct_size: AttentionRegionPlanObservation::contract_size(),
            run_digest: [11; 32],
            workflow_revision_digest: [12; 32],
            settings_digest: [13; 32],
            model_revision_digest: [14; 32],
            observed_step: 3,
            predicted_execution_step: 5,
            total_steps: 20,
            topology_id: C2_TOPOLOGY_OVERLAP_2X2,
            eye_state: [
                C2_EYE_STATE_UNCERTAIN,
                C2_EYE_STATE_STABLE,
                C2_EYE_STATE_ACTIVE,
                C2_EYE_STATE_UNCERTAIN,
                C2_EYE_STATE_STABLE,
            ],
            eye_confidence_ppm: [500_000, 900_000, 1_000_000, 500_000, 850_000],
            eye_change_ppm: [40_000, 5_000, 90_000, 30_000, 7_000],
            stable_mask: 0b1001,
            stable_count: 2,
            active_mask: 0b0010,
            active_count: 1,
            uncertain_mask: 0b0100,
            uncertain_count: 1,
            global_invalidation: 0,
            overlap_conflict_mask: 0,
            anchor_step: 0,
            cooldown_mask: 0,
            refresh_required_mask: 0,
            source_valid: 1,
            prediction_valid: 1,
            selective_supported: 1,
            fallback_supported: 1,
            fatal_flags: 0,
            unsupported_flags: 0,
        }
    }

    #[test]
    fn a1_region_plan_is_deterministic_and_metadata_only() {
        let observation = a1_observation();
        let first = evaluate_attention_region_plan(&observation);
        let second = evaluate_attention_region_plan(&observation);
        assert_eq!(first, second);
        assert_eq!(first.decision_code, A1_DECISION_REGIONAL_ACTIVE_QUERY);
        assert_eq!(first.stable_region_mask, 0b1001);
        assert_eq!(first.full_compute_region_mask, 0b0110);
        assert_eq!(first.fallback_required, 0);
        assert_eq!(
            AttentionRegionPlanObservation::contract_size() as usize,
            std::mem::size_of::<AttentionRegionPlanObservation>()
        );
    }

    #[test]
    fn a1_uncertain_active_conflict_anchor_and_refresh_never_become_selective() {
        let mut observation = a1_observation();
        observation.overlap_conflict_mask = 0b0001;
        let conflict = evaluate_attention_region_plan(&observation);
        assert_eq!(conflict.decision_code, A1_DECISION_FULL_COMPUTE);
        assert_eq!(conflict.stable_region_mask, 0);

        observation.overlap_conflict_mask = 0;
        observation.anchor_step = 1;
        let anchor = evaluate_attention_region_plan(&observation);
        assert_eq!(anchor.decision_code, A1_DECISION_FULL_COMPUTE);
        assert_eq!(anchor.stable_region_mask, 0);

        observation.anchor_step = 0;
        observation.refresh_required_mask = observation.stable_mask;
        let refresh = evaluate_attention_region_plan(&observation);
        assert_eq!(refresh.decision_code, A1_DECISION_FULL_COMPUTE);
        assert_eq!(refresh.full_compute_region_mask, A1_REGION_MASK);
    }

    #[test]
    fn a1_malformed_or_late_metadata_escalates_full_compute() {
        let mut observation = a1_observation();
        observation.prediction_valid = 0;
        let late = evaluate_attention_region_plan(&observation);
        assert_eq!(late.decision_code, A1_DECISION_ESCALATE_FULL_COMPUTE);
        assert_eq!(late.reason_code, A1_REASON_PREDICTION_INVALID);
        assert_eq!(late.full_compute_region_mask, A1_REGION_MASK);

        observation = a1_observation();
        observation.stable_count = 3;
        let malformed = evaluate_attention_region_plan(&observation);
        assert_eq!(malformed.decision_code, A1_DECISION_ESCALATE_FULL_COMPUTE);
        assert_eq!(malformed.reason_code, A1_REASON_EYE_METADATA_INVALID);
    }

    fn c3_r1_observation(step: u32) -> C3FrozenBlockPlanObservation {
        C3FrozenBlockPlanObservation {
            abi_version: C3_R1_BLOCK_PLAN_ABI_VERSION,
            struct_size: C3FrozenBlockPlanObservation::contract_size(),
            run_digest: [7; 32],
            workflow_revision_digest: [8; 32],
            settings_digest: [9; 32],
            model_revision_digest: [10; 32],
            predicted_execution_step: step,
            total_steps: C3_R1_TOTAL_STEPS,
            block_count: C3_R1_BLOCK_COUNT,
            frozen_schedule_member: u32::from(C3_R1_FROZEN_SCHEDULE.contains(&step)),
            stable_mask: 0b0011,
            stable_count: 2,
            active_mask: 0,
            active_count: 0,
            uncertain_mask: 0b1100,
            uncertain_count: 2,
            global_invalidation: 0,
            overlap_conflict_mask: 0,
            prediction_valid: 1,
            source_valid: 1,
            selective_supported: 1,
            fallback_supported: 1,
            fatal_flags: 0,
            unsupported_flags: 0,
        }
    }

    #[test]
    fn c3_r1_contract_is_fixed_metadata_only_and_distinct() {
        assert_eq!(C3_R1_FROZEN_SCHEDULE, [5, 6, 8, 13, 16, 17]);
        assert_eq!(C3_R1_CANDIDATE_BLOCK_COUNT, 37);
        assert_eq!(C3_R1_CANDIDATE_BLOCK_MASK.count_ones(), 37);
        assert_eq!(
            C3FrozenBlockPlanObservation::contract_size() as usize,
            std::mem::size_of::<C3FrozenBlockPlanObservation>()
        );
        assert_eq!(
            C3FrozenBlockPlanDirective::contract_size() as usize,
            std::mem::size_of::<C3FrozenBlockPlanDirective>()
        );
        assert_ne!(
            C3FrozenBlockPlanObservation::contract_size(),
            CompoundEyeShadowObservation::contract_size()
        );
    }

    #[test]
    fn c3_r1_frozen_plan_is_deterministic_and_mask_is_bounded() {
        let observation = c3_r1_observation(5);
        let first = evaluate_c3_frozen_block_plan(&observation);
        let second = evaluate_c3_frozen_block_plan(&observation);
        assert_eq!(first, second);
        assert_eq!(first.decision_code, C3_R1_DECISION_SELECTIVE_BLOCK_BYPASS);
        assert_eq!(first.bypass_mask, C3_R1_CANDIDATE_BLOCK_MASK);
        assert_eq!(first.bypass_count, 37);
        assert_eq!(first.bypass_mask & ((1_u64 << 12) - 1), 0);
        assert_eq!(first.bypass_mask >> 49, 0);
    }

    #[test]
    fn c3_r1_nonmember_and_live_safety_only_veto_to_full_compute() {
        let nonmember = evaluate_c3_frozen_block_plan(&c3_r1_observation(7));
        assert_eq!(nonmember.decision_code, C3_R1_DECISION_FULL_COMPUTE);
        assert_eq!(nonmember.reason_code, C3_R1_REASON_NOT_FROZEN_TARGET);
        assert_eq!(nonmember.bypass_count, 0);

        let mut cases = Vec::new();
        let mut source = c3_r1_observation(5);
        source.source_valid = 0;
        cases.push((source, C3_R1_REASON_SOURCE_INVALID));
        let mut prediction = c3_r1_observation(5);
        prediction.prediction_valid = 0;
        cases.push((prediction, C3_R1_REASON_PREDICTION_INVALID));
        let mut stable = c3_r1_observation(5);
        stable.stable_mask = 1;
        stable.stable_count = 1;
        stable.uncertain_mask = 0b1110;
        stable.uncertain_count = 3;
        cases.push((stable, C3_R1_REASON_STABLE_COUNT_LOW));
        let mut active = c3_r1_observation(5);
        active.active_mask = 0b0100;
        active.active_count = 1;
        active.uncertain_mask = 0b1000;
        active.uncertain_count = 1;
        cases.push((active, C3_R1_REASON_ACTIVE_PRESENT));
        let mut global = c3_r1_observation(5);
        global.global_invalidation = 1;
        cases.push((global, C3_R1_REASON_GLOBAL_INVALIDATION));
        let mut overlap = c3_r1_observation(5);
        overlap.overlap_conflict_mask = 1;
        cases.push((overlap, C3_R1_REASON_OVERLAP_CONFLICT));
        let mut fatal = c3_r1_observation(5);
        fatal.fatal_flags = 1;
        cases.push((fatal, C3_R1_REASON_FATAL_FLAG));
        for (observation, reason) in cases {
            let directive = evaluate_c3_frozen_block_plan(&observation);
            assert_eq!(directive.decision_code, C3_R1_DECISION_FULL_COMPUTE);
            assert_eq!(directive.reason_code, reason);
            assert_eq!(directive.bypass_mask, 0);
        }
    }

    #[test]
    fn c3_r1_invalid_contract_escalates_and_panic_boundary_is_fail_open() {
        let mut invalid_abi = c3_r1_observation(5);
        invalid_abi.abi_version = 99;
        let directive = evaluate_c3_frozen_block_plan(&invalid_abi);
        assert_eq!(
            directive.decision_code,
            C3_R1_DECISION_ESCALATE_FULL_COMPUTE
        );
        assert_eq!(directive.reason_code, C3_R1_REASON_ABI_MISMATCH);
        assert_eq!(directive.bypass_count, 0);

        let mut invalid_blocks = c3_r1_observation(5);
        invalid_blocks.block_count = 49;
        let directive = evaluate_c3_frozen_block_plan(&invalid_blocks);
        assert_eq!(
            directive.decision_code,
            C3_R1_DECISION_ESCALATE_FULL_COMPUTE
        );
        assert_eq!(
            directive.reason_code,
            C3_R1_REASON_EXECUTION_CONTRACT_MISMATCH
        );

        let fail_open = C3FrozenBlockPlanDirective::fail_open(C3_R1_REASON_RUST_PANIC, 5, [11; 32]);
        assert_eq!(
            fail_open.decision_code,
            C3_R1_DECISION_ESCALATE_FULL_COMPUTE
        );
        assert_eq!(fail_open.bypass_count, 0);
        assert_eq!(fail_open.fallback_required, 1);
    }

    fn c3_r2_observation() -> ReusePlanObservation {
        ReusePlanObservation {
            abi_version: C3_R2_REUSE_PLAN_ABI_VERSION,
            struct_size: ReusePlanObservation::contract_size(),
            run_digest: [1; 32],
            workflow_revision_digest: [2; 32],
            settings_digest: [3; 32],
            model_revision_digest: [4; 32],
            segment_logical_digest: [5; 32],
            target_execution_step: 5,
            source_execution_step: 4,
            total_steps: 20,
            cache_age: 1,
            cache_available: 1,
            cache_provenance_valid: 1,
            residual_similarity_admitted: 1,
            calibrated_target: 1,
            prior_step_reused: 0,
            stable_mask: 0b0011,
            stable_count: 2,
            active_mask: 0,
            active_count: 0,
            uncertain_mask: 0b1100,
            uncertain_count: 2,
            global_invalidation: 0,
            overlap_conflict_mask: 0,
            prediction_valid: 1,
            source_valid: 1,
            finite: 1,
            fallback_supported: 1,
            fatal_flags: 0,
            unsupported_flags: 0,
        }
    }

    #[test]
    fn c3_r2_contract_is_metadata_only_deterministic_and_admits_age_one() {
        let observation = c3_r2_observation();
        let first = evaluate_reuse_plan(&observation);
        let second = evaluate_reuse_plan(&observation);
        assert_eq!(first, second);
        assert_eq!(first.decision_code, C3_R2_DECISION_REUSE_TRANSFORM);
        assert_eq!(first.reason_code, C3_R2_REASON_NONE);
        assert_eq!(first.source_execution_step, 4);
        assert_ne!(
            ReusePlanObservation::contract_size(),
            C3FrozenBlockPlanObservation::contract_size()
        );
    }

    #[test]
    fn c3_r2_cache_age_missing_provenance_and_similarity_fail_open() {
        let mut cases = Vec::new();
        let mut age_zero = c3_r2_observation();
        age_zero.cache_age = 0;
        cases.push((age_zero, C3_R2_REASON_CACHE_AGE_INVALID));
        let mut age_two = c3_r2_observation();
        age_two.cache_age = 2;
        age_two.source_execution_step = 3;
        cases.push((age_two, C3_R2_REASON_CACHE_AGE_INVALID));
        let mut missing = c3_r2_observation();
        missing.cache_available = 0;
        cases.push((missing, C3_R2_REASON_CACHE_MISSING));
        let mut provenance = c3_r2_observation();
        provenance.cache_provenance_valid = 0;
        cases.push((provenance, C3_R2_REASON_PROVENANCE_INVALID));
        let mut similarity = c3_r2_observation();
        similarity.residual_similarity_admitted = 0;
        cases.push((similarity, C3_R2_REASON_SIMILARITY_REJECTED));
        for (observation, reason) in cases {
            let directive = evaluate_reuse_plan(&observation);
            assert_eq!(directive.decision_code, C3_R2_DECISION_FULL_COMPUTE);
            assert_eq!(directive.reason_code, reason);
            assert_eq!(directive.fallback_required, 1);
        }
    }

    #[test]
    fn c3_r2_live_safety_and_consecutive_reuse_only_veto() {
        let mut cases = Vec::new();
        let mut active = c3_r2_observation();
        active.active_mask = 0b0100;
        active.active_count = 1;
        active.uncertain_mask = 0b1000;
        active.uncertain_count = 1;
        cases.push((active, C3_R2_REASON_ACTIVE_PRESENT));
        let mut global = c3_r2_observation();
        global.global_invalidation = 1;
        cases.push((global, C3_R2_REASON_GLOBAL_INVALIDATION));
        let mut overlap = c3_r2_observation();
        overlap.overlap_conflict_mask = 1;
        cases.push((overlap, C3_R2_REASON_OVERLAP_CONFLICT));
        let mut consecutive = c3_r2_observation();
        consecutive.prior_step_reused = 1;
        cases.push((consecutive, C3_R2_REASON_CONSECUTIVE_REUSE));
        for (observation, reason) in cases {
            let directive = evaluate_reuse_plan(&observation);
            assert_eq!(directive.decision_code, C3_R2_DECISION_FULL_COMPUTE);
            assert_eq!(directive.reason_code, reason);
        }
    }

    #[test]
    fn c3_r2_invalid_contract_and_panic_boundary_escalate() {
        let mut invalid = c3_r2_observation();
        invalid.abi_version = 99;
        let directive = evaluate_reuse_plan(&invalid);
        assert_eq!(
            directive.decision_code,
            C3_R2_DECISION_ESCALATE_FULL_COMPUTE
        );
        assert_eq!(directive.reason_code, C3_R2_REASON_ABI_MISMATCH);
        let fail_open = ReusePlanDirective::fail_open(C3_R2_REASON_RUST_PANIC, 5, 4, [9; 32]);
        assert_eq!(
            fail_open.decision_code,
            C3_R2_DECISION_ESCALATE_FULL_COMPUTE
        );
        assert_eq!(fail_open.fallback_required, 1);
    }

    fn c3_r3_observation() -> CorrectionPlanObservation {
        CorrectionPlanObservation {
            abi_version: C3_R3_CORRECTION_PLAN_ABI_VERSION,
            struct_size: CorrectionPlanObservation::contract_size(),
            run_digest: [1; 32],
            workflow_revision_digest: [2; 32],
            settings_digest: [3; 32],
            model_revision_digest: [4; 32],
            segment_logical_digest: [5; 32],
            target_execution_step: 5,
            first_source_execution_step: 3,
            second_source_execution_step: 4,
            total_steps: 20,
            cache_available: 1,
            predictor_available: 1,
            predictor_provenance_valid: 1,
            corrected_similarity_admitted: 1,
            correction_metadata_valid: 1,
            calibrated_target: 1,
            full_compute_seed_count: 2,
            reseed_required: 0,
            stable_mask: 0b0011,
            stable_count: 2,
            active_mask: 0,
            active_count: 0,
            uncertain_mask: 0b1100,
            uncertain_count: 2,
            global_invalidation: 0,
            overlap_conflict_mask: 0,
            prediction_valid: 1,
            source_valid: 1,
            finite: 1,
            fallback_supported: 1,
            fatal_flags: 0,
            unsupported_flags: 0,
        }
    }

    #[test]
    fn c3_r3_correction_plan_is_deterministic_and_tensor_free() {
        let observation = c3_r3_observation();
        let first = evaluate_correction_plan(&observation);
        let second = evaluate_correction_plan(&observation);
        assert_eq!(first, second);
        assert_eq!(
            first.decision_code,
            C3_R3_DECISION_REUSE_CORRECTED_TRANSFORM
        );
        assert_eq!(first.reason_code, C3_R3_REASON_NONE);
        assert_eq!(first.fallback_required, 0);
        assert!(CorrectionPlanObservation::contract_size() < 512);
        assert!(CorrectionPlanDirective::contract_size() < 128);
    }

    #[test]
    fn c3_r3_invalid_predictor_and_live_vetoes_fail_open() {
        let mut cases = Vec::new();
        let mut missing = c3_r3_observation();
        missing.predictor_available = 0;
        cases.push((missing, C3_R3_REASON_PREDICTOR_MISSING));
        let mut invalid = c3_r3_observation();
        invalid.correction_metadata_valid = 0;
        cases.push((invalid, C3_R3_REASON_METADATA_INVALID));
        let mut reseed = c3_r3_observation();
        reseed.full_compute_seed_count = 1;
        reseed.reseed_required = 1;
        cases.push((reseed, C3_R3_REASON_RESEED_REQUIRED));
        let mut active = c3_r3_observation();
        active.stable_mask = 0b0011;
        active.stable_count = 2;
        active.active_mask = 0b0100;
        active.active_count = 1;
        active.uncertain_mask = 0b1000;
        active.uncertain_count = 1;
        cases.push((active, C3_R3_REASON_ACTIVE_PRESENT));
        let mut global = c3_r3_observation();
        global.global_invalidation = 1;
        cases.push((global, C3_R3_REASON_GLOBAL_INVALIDATION));
        let mut overlap = c3_r3_observation();
        overlap.overlap_conflict_mask = 1;
        cases.push((overlap, C3_R3_REASON_OVERLAP_CONFLICT));
        for (observation, reason) in cases {
            let directive = evaluate_correction_plan(&observation);
            assert_eq!(directive.decision_code, C3_R3_DECISION_FULL_COMPUTE);
            assert_eq!(directive.reason_code, reason);
            assert_eq!(directive.fallback_required, 1);
        }
    }

    #[test]
    fn c3_r3_invalid_contract_and_panic_boundary_escalate() {
        let mut invalid = c3_r3_observation();
        invalid.abi_version = 99;
        let directive = evaluate_correction_plan(&invalid);
        assert_eq!(
            directive.decision_code,
            C3_R3_DECISION_ESCALATE_FULL_COMPUTE
        );
        assert_eq!(directive.reason_code, C3_R3_REASON_ABI_MISMATCH);
        let fail_open =
            CorrectionPlanDirective::fail_open(C3_R3_REASON_RUST_PANIC, 5, 3, 4, [9; 32]);
        assert_eq!(
            fail_open.decision_code,
            C3_R3_DECISION_ESCALATE_FULL_COMPUTE
        );
        assert_eq!(fail_open.fallback_required, 1);
    }

    fn semantic(profile: &str, topology: Topology) -> SemanticResult {
        let profile = InputProfile::named(profile, 101).expect("profile");
        let sequence = generate_sequence(&profile).expect("sequence");
        run_pipeline(&profile, topology, &sequence)
            .expect("pipeline")
            .semantic
    }

    #[test]
    fn mono_eye_is_deterministic() {
        let first = semantic("low", Topology::Mono1x1);
        let second = semantic("low", Topology::Mono1x1);
        assert_eq!(first, second);
        assert_eq!(first.eyes.len(), 1);
        assert_eq!(
            semantic_hash(&first).expect("hash"),
            semantic_hash(&second).expect("hash")
        );
    }

    #[test]
    fn uniform_topologies_have_expected_eye_counts() {
        assert_eq!(semantic("low", Topology::Uniform2x2).eyes.len(), 5);
        assert_eq!(semantic("low", Topology::Uniform4x4).eyes.len(), 17);
    }

    #[test]
    fn overlap_coordinates_and_write_scopes_are_bounded() {
        let result = semantic("low", Topology::Overlap2x2);
        for eye in result.eyes.iter().filter(|eye| eye.write_scope.is_some()) {
            let scope = eye.write_scope.as_ref().expect("scope");
            assert!(eye.receptive_field.contains(scope));
            assert_eq!(
                eye.local_to_global,
                [eye.receptive_field.x, eye.receptive_field.y]
            );
        }
    }

    #[test]
    fn motion_focused_topology_detects_change() {
        let result = semantic("medium", Topology::MotionFocused);
        let focus = result
            .observations
            .iter()
            .find(|item| item.eye_id == "motion-focus-00")
            .expect("focus observation");
        assert!(focus.changed_pixels > 0);
        assert!(focus.motion_bbox.is_some());
    }

    #[test]
    fn fusion_preserves_provenance() {
        let result = semantic("low", Topology::Uniform2x2);
        for region in &result.shared_visual_state.regions {
            assert!(!region.sources.is_empty());
            for source in &region.sources {
                assert!(result.shared_visual_state.observation_ids.contains(source));
            }
        }
    }

    #[test]
    fn overlap_conflict_remains_uncertain() {
        let result = semantic("low", Topology::Overlap2x2);
        assert!(result
            .shared_visual_state
            .regions
            .iter()
            .any(|region| region.state == "uncertain"));
        assert!(result
            .compute_plan
            .units
            .iter()
            .any(|unit| unit.action == "reconcile"));
    }

    #[test]
    fn invalid_input_is_rejected() {
        assert!(InputProfile::new("invalid", 16, 16, 1, 101, vec![]).is_err());
        let profile = InputProfile::named("low", 101).expect("profile");
        assert!(validate_sequence(&profile, &[0_u8; 3]).is_err());
    }

    #[test]
    fn unsupported_metrics_are_null_with_reasons() {
        let result = semantic("low", Topology::Mono1x1);
        for metric in &result.compute_plan.claims {
            assert!(metric.value.is_none());
            assert!(matches!(
                metric.status.as_str(),
                "unsupported" | "uncollected"
            ));
            assert!(!metric.reason.is_empty());
            assert!(!metric.method.is_empty());
        }
    }

    #[test]
    fn r2_batch_is_coarse_deterministic_and_complete() {
        let profile = InputProfile::named("low", 101).expect("profile");
        let sequence = generate_sequence(&profile).expect("sequence");
        let report = benchmark_r2_batch(&profile, &sequence, 5, 20).expect("r2 batch");
        assert_eq!(report.run_kind, R2_RUN_KIND);
        assert_eq!(report.samples.len(), 60);
        assert_eq!(report.semantic_results.len(), 3);
        assert_eq!(report.copied_bytes, 0);
        for candidate in ["T0", "T1", "T2"] {
            let hashes = report
                .samples
                .iter()
                .filter(|sample| sample.candidate_id == candidate)
                .map(|sample| sample.semantic_hash.as_str())
                .collect::<std::collections::BTreeSet<_>>();
            assert_eq!(hashes.len(), 1);
            assert_eq!(
                hashes.into_iter().next().expect("hash"),
                semantic_hash(&report.semantic_results[candidate]).expect("semantic hash")
            );
        }
    }

    #[test]
    fn r3_candidate_summary_preserves_existing_semantics() {
        let profile = InputProfile::named("high", 101).expect("profile");
        let sequence = generate_sequence(&profile).expect("sequence");
        for candidate in ["T0", "T1", "T2"] {
            let first = run_r3_candidate(&profile, candidate, &sequence).expect("first");
            let second = run_r3_candidate(&profile, candidate, &sequence).expect("second");
            assert_eq!(first.semantic_hash, second.semantic_hash);
            assert_eq!(first.input_sha256, second.input_sha256);
            assert_eq!(first.bytes_copied, 0);
            assert!(first.eye_count > 0);
            assert_eq!(
                first.compute_unit_count,
                first.generate_unit_count
                    + first.reuse_cache_unit_count
                    + first.reconcile_unit_count
            );
        }
    }
}
