#![doc = "Metadata-only, generation-batched region-sparse cache planning ABI V2."]

use sha2::{Digest, Sha256};
use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet};

pub const CACHE_PLAN_ABI_V2_VERSION: u32 = 2;
pub const CACHE_PLAN_V2_CONTRACT_VERSION: u32 = 1;
pub const CACHE_PLAN_V2_FULL_COMPUTE: u32 = 0;
pub const CACHE_PLAN_V2_READY: u32 = 1;
pub const CACHE_PLAN_V2_OVERFLOW_FULL_COMPUTE: u32 = 1;
pub const CACHE_PLAN_V2_MIN_REDUCTION_PPM: u64 = 30_000;
pub const CACHE_PLAN_V2_MAX_RECORDS: usize = 4_096;
pub const CACHE_PLAN_V2_MAX_INVENTORY: usize = 200;
pub const CACHE_PLAN_V2_MAX_BATCH_BYTES: u64 = 4 * 1_024 * 1_024;

pub const CACHE_PLAN_V2_REASON_NONE: u32 = 0;
pub const CACHE_PLAN_V2_REASON_ABI_MISMATCH: u32 = 1;
pub const CACHE_PLAN_V2_REASON_STRUCT_SIZE_MISMATCH: u32 = 2;
pub const CACHE_PLAN_V2_REASON_IDENTITY_INVALID: u32 = 3;
pub const CACHE_PLAN_V2_REASON_PROFILE_INVALID: u32 = 4;
pub const CACHE_PLAN_V2_REASON_BATCH_OVERFLOW: u32 = 5;
pub const CACHE_PLAN_V2_REASON_BATCH_MALFORMED: u32 = 6;
pub const CACHE_PLAN_V2_REASON_RECORD_MALFORMED: u32 = 7;
pub const CACHE_PLAN_V2_REASON_INVENTORY_MALFORMED: u32 = 8;
pub const CACHE_PLAN_V2_REASON_PRE_GATE_BELOW_THREE_PERCENT: u32 = 9;
pub const CACHE_PLAN_V2_REASON_RUST_PANIC: u32 = 10;

pub const CACHE_REJECT_NOT_STABLE: u32 = 1;
pub const CACHE_REJECT_SAFETY_EVIDENCE_MISSING: u32 = 2;
pub const CACHE_REJECT_ACTUAL_UNSAFE: u32 = 3;
pub const CACHE_REJECT_FALSE_SAFE: u32 = 4;
pub const CACHE_REJECT_LINEAGE_MISMATCH: u32 = 5;
pub const CACHE_REJECT_AGE_MISMATCH: u32 = 6;
pub const CACHE_REJECT_NONFINITE: u32 = 7;
pub const CACHE_REJECT_NOT_ELIGIBLE: u32 = 8;
pub const CACHE_REJECT_PROFILE_CACHE_BUDGET: u32 = 9;
pub const CACHE_REJECT_PROFILE_TRANSFER_BUDGET: u32 = 10;
pub const CACHE_REJECT_PROFILE_SELECTED_LIMIT: u32 = 11;
pub const CACHE_REJECT_PROFILE_STAGING_BUDGET: u32 = 12;

pub const CACHE_STATE_STABLE: u32 = 1;
pub const CACHE_STATE_ACTIVE: u32 = 2;
pub const CACHE_STATE_UNCERTAIN: u32 = 3;
pub const CACHE_SAFETY_SAFE: u32 = 1;
pub const CACHE_SAFETY_UNSAFE: u32 = 2;
pub const CACHE_SOURCE_ACTUAL_FULL_ATTENTION_CORE_OUTPUT: u32 = 1;
pub const CACHE_DTYPE_BFLOAT16: u32 = 1;
pub const CACHE_DEVICE_CPU_PINNED: u32 = 1;
pub const CACHE_PRECISION_BFLOAT16: u32 = 1;
pub const CACHE_QUANTIZATION_NONE: u32 = 1;
pub const CACHE_OFFLOAD_PINNED_HOST: u32 = 1;
pub const CACHE_RESOLUTION_STANDARD_864X480: u32 = 1;
pub const HARDWARE_PROFILE_BALANCED_12GB: u32 = 1;
pub const HARDWARE_PROFILE_QUALITY_24GB_PLUS: u32 = 2;

pub const RECEIPT_STATUS_MEASURED: u32 = 1;
pub const RECEIPT_STATUS_STRUCTURAL_ZERO: u32 = 2;
pub const RECEIPT_STATUS_UNKNOWN: u32 = 3;
pub const RECEIPT_STATUS_NOT_EXECUTED: u32 = 4;

#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct GenerationCachePlanRequest {
    pub abi_version: u32,
    pub struct_size: u32,
    pub contract_version: u32,
    pub overflow_policy: u32,
    pub generation_id: u64,
    pub current_step: u32,
    pub maximum_batch_records: u32,
    pub maximum_batch_bytes: u64,
    pub total_full_q_rows: u64,
    pub unsupported_flags: u32,
}

impl GenerationCachePlanRequest {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct GenerationIdentityV2 {
    pub run_digest: [u8; 32],
    pub workflow_digest: [u8; 32],
    pub model_digest: [u8; 32],
    pub model_revision_digest: [u8; 32],
    pub settings_digest: [u8; 32],
    pub source_plan_digest: [u8; 32],
    pub layout_digest: [u8; 32],
    pub input_identity_digest: [u8; 32],
    pub generation_id: u64,
    pub scheduler_id: u32,
    pub total_steps: u32,
    pub width: u32,
    pub height: u32,
    pub frame_count: u32,
    pub fps_numerator: u32,
    pub fps_denominator: u32,
}

impl GenerationIdentityV2 {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }

    fn valid(&self, request: &GenerationCachePlanRequest) -> bool {
        let digests = [
            self.run_digest,
            self.workflow_digest,
            self.model_digest,
            self.model_revision_digest,
            self.settings_digest,
            self.source_plan_digest,
            self.layout_digest,
            self.input_identity_digest,
        ];
        digests.into_iter().all(|digest| digest != [0; 32])
            && self.generation_id == request.generation_id
            && self.scheduler_id != 0
            && self.total_steps != 0
            && request.current_step < self.total_steps
            && self.width != 0
            && self.height != 0
            && self.frame_count != 0
            && self.fps_numerator != 0
            && self.fps_denominator != 0
    }
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HardwareProfileV2 {
    pub abi_version: u32,
    pub struct_size: u32,
    pub profile_id: u32,
    pub precision: u32,
    pub quantization: u32,
    pub offload_policy: u32,
    pub resolution_class: u32,
    pub cache_age: u32,
    pub vram_budget_bytes: u64,
    pub host_cache_budget_bytes: u64,
    pub gpu_staging_budget_bytes: u64,
    pub minimum_reserve_bytes: u64,
    pub maximum_transfer_bytes: u64,
    pub maximum_candidates: u32,
    pub maximum_selected_regions: u32,
    pub maximum_batch_bytes: u64,
    pub maximum_work_units: u32,
    pub resolution_width: u32,
    pub resolution_height: u32,
    pub frame_budget: u32,
}

impl HardwareProfileV2 {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }

    pub fn balanced_12gb() -> Self {
        Self {
            abi_version: CACHE_PLAN_ABI_V2_VERSION,
            struct_size: Self::contract_size(),
            profile_id: HARDWARE_PROFILE_BALANCED_12GB,
            precision: CACHE_PRECISION_BFLOAT16,
            quantization: CACHE_QUANTIZATION_NONE,
            offload_policy: CACHE_OFFLOAD_PINNED_HOST,
            resolution_class: CACHE_RESOLUTION_STANDARD_864X480,
            cache_age: 1,
            vram_budget_bytes: 12 * 1_024 * 1_024 * 1_024,
            host_cache_budget_bytes: 2 * 1_024 * 1_024 * 1_024,
            gpu_staging_budget_bytes: 256 * 1_024 * 1_024,
            minimum_reserve_bytes: 2 * 1_024 * 1_024 * 1_024,
            maximum_transfer_bytes: 40 * 1_024 * 1_024 * 1_024,
            maximum_candidates: CACHE_PLAN_V2_MAX_RECORDS as u32,
            maximum_selected_regions: 44,
            maximum_batch_bytes: 2 * 1_024 * 1_024,
            maximum_work_units: CACHE_PLAN_V2_MAX_RECORDS as u32,
            resolution_width: 864,
            resolution_height: 480,
            frame_budget: 124,
        }
    }

    pub fn quality_24gb_plus() -> Self {
        Self {
            profile_id: HARDWARE_PROFILE_QUALITY_24GB_PLUS,
            vram_budget_bytes: 24 * 1_024 * 1_024 * 1_024,
            host_cache_budget_bytes: 4 * 1_024 * 1_024 * 1_024,
            gpu_staging_budget_bytes: 512 * 1_024 * 1_024,
            minimum_reserve_bytes: 4 * 1_024 * 1_024 * 1_024,
            maximum_selected_regions: 88,
            maximum_batch_bytes: CACHE_PLAN_V2_MAX_BATCH_BYTES,
            ..Self::balanced_12gb()
        }
    }

    fn valid(&self) -> bool {
        self.abi_version == CACHE_PLAN_ABI_V2_VERSION
            && self.struct_size == Self::contract_size()
            && (self.profile_id == HARDWARE_PROFILE_BALANCED_12GB
                || self.profile_id == HARDWARE_PROFILE_QUALITY_24GB_PLUS)
            && self.precision == CACHE_PRECISION_BFLOAT16
            && self.quantization == CACHE_QUANTIZATION_NONE
            && self.offload_policy == CACHE_OFFLOAD_PINNED_HOST
            && self.resolution_class == CACHE_RESOLUTION_STANDARD_864X480
            && self.cache_age == 1
            && self.vram_budget_bytes > self.minimum_reserve_bytes
            && self.host_cache_budget_bytes != 0
            && self.gpu_staging_budget_bytes != 0
            && self.maximum_transfer_bytes != 0
            && self.maximum_candidates != 0
            && self.maximum_candidates as usize <= CACHE_PLAN_V2_MAX_RECORDS
            && self.maximum_selected_regions != 0
            && self.maximum_selected_regions <= self.maximum_candidates
            && self.maximum_batch_bytes != 0
            && self.maximum_batch_bytes <= CACHE_PLAN_V2_MAX_BATCH_BYTES
            && self.maximum_work_units >= self.maximum_candidates
            && self.resolution_width != 0
            && self.resolution_height != 0
            && self.frame_budget != 0
    }
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct GenerationEvidenceBatchHeader {
    pub abi_version: u32,
    pub struct_size: u32,
    pub generation_id: u64,
    pub record_count: u32,
    pub maximum_records: u32,
    pub batch_bytes: u64,
    pub overflowed: u32,
    pub truncated: u32,
    pub tensor_bytes: u64,
    pub unsupported_flags: u32,
}

impl GenerationEvidenceBatchHeader {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CacheCandidateV2 {
    pub target_step: u32,
    pub source_step: u32,
    pub block_index: u32,
    pub region: u32,
    pub packed_row_start: u32,
    pub packed_row_count: u32,
    pub state: u32,
    pub actual_safety_state: u32,
    pub safety_evidence_present: u32,
    pub uncertainty_ppm: u32,
    pub motion_ppm: u32,
    pub cosine_ppm: i32,
    pub corrected_nl2_ppm: u32,
    pub false_safe_count: u32,
    pub nonfinite_count: u32,
    pub cache_age: u32,
    pub source_kind: u32,
    pub shape_rows: u32,
    pub shape_width: u32,
    pub dtype: u32,
    pub device_class: u32,
    pub precision: u32,
    pub quantization: u32,
    pub admission_eligible: u32,
    pub rejection_reason: u32,
    pub planned_q_rows: u64,
    pub full_q_rows: u64,
    pub payload_bytes: u64,
    pub effect_numerator: u64,
    pub effect_denominator: u64,
    pub planned_d2h_bytes: u64,
    pub planned_h2d_bytes: u64,
    pub shape_digest: [u8; 32],
    pub packed_row_digest: [u8; 32],
    pub lineage_digest: [u8; 32],
}

impl CacheCandidateV2 {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }

    fn structurally_valid(&self, identity: &GenerationIdentityV2) -> bool {
        self.target_step < identity.total_steps
            && self.source_step < identity.total_steps
            && self.target_step == self.source_step.saturating_add(1)
            && self.block_index < 50
            && self.region < 4
            && self.packed_row_count != 0
            && self.state >= CACHE_STATE_STABLE
            && self.state <= CACHE_STATE_UNCERTAIN
            && (self.actual_safety_state == CACHE_SAFETY_SAFE
                || self.actual_safety_state == CACHE_SAFETY_UNSAFE)
            && self.safety_evidence_present <= 1
            && self.uncertainty_ppm <= 1_000_000
            && self.motion_ppm <= 1_000_000
            && (-1_000_000..=1_000_000).contains(&self.cosine_ppm)
            && self.corrected_nl2_ppm <= 10_000_000
            && self.source_kind == CACHE_SOURCE_ACTUAL_FULL_ATTENTION_CORE_OUTPUT
            && self.shape_rows != 0
            && self.shape_width != 0
            && self.dtype == CACHE_DTYPE_BFLOAT16
            && self.device_class == CACHE_DEVICE_CPU_PINNED
            && self.precision == CACHE_PRECISION_BFLOAT16
            && self.quantization == CACHE_QUANTIZATION_NONE
            && self.admission_eligible <= 1
            && self.planned_q_rows != 0
            && self.full_q_rows != 0
            && self.planned_q_rows <= self.full_q_rows
            && self.payload_bytes != 0
            && self.effect_numerator == self.planned_q_rows
            && self.effect_denominator == self.payload_bytes
            && self.planned_d2h_bytes != 0
            && self.planned_h2d_bytes != 0
            && self.shape_digest != [0; 32]
            && self.packed_row_digest != [0; 32]
            && self.lineage_digest != [0; 32]
    }
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CacheInventoryEntryV2 {
    pub block_index: u32,
    pub region: u32,
    pub source_step: u32,
    pub cache_age: u32,
    pub valid: u32,
    pub payload_bytes: u64,
    pub planned_q_rows: u64,
    pub lineage_digest: [u8; 32],
}

impl CacheInventoryEntryV2 {
    pub fn contract_size() -> u32 {
        std::mem::size_of::<Self>() as u32
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GenerationEvidenceBatchV2 {
    pub header: GenerationEvidenceBatchHeader,
    pub records: Vec<CacheCandidateV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelectedCacheKeyV2 {
    pub block_index: u32,
    pub region: u32,
    pub payload_bytes: u64,
    pub planned_q_rows: u64,
    pub planned_d2h_bytes: u64,
    pub planned_h2d_bytes: u64,
    pub effect_numerator: u64,
    pub effect_denominator: u64,
    pub transfer_effect_numerator: u64,
    pub transfer_effect_denominator: u64,
    pub selection_lineage_digest: [u8; 32],
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RejectedCacheKeyV2 {
    pub block_index: u32,
    pub region: u32,
    pub reason_code: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvictionKeyV2 {
    pub block_index: u32,
    pub region: u32,
    pub reason_code: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReceiptMetricU64 {
    pub value: Option<u64>,
    pub status: u32,
}

impl ReceiptMetricU64 {
    pub fn measured(value: u64) -> Self {
        Self {
            value: Some(value),
            status: RECEIPT_STATUS_MEASURED,
        }
    }

    pub fn structural_zero() -> Self {
        Self {
            value: Some(0),
            status: RECEIPT_STATUS_STRUCTURAL_ZERO,
        }
    }

    pub fn unknown() -> Self {
        Self {
            value: None,
            status: RECEIPT_STATUS_UNKNOWN,
        }
    }

    pub fn not_executed() -> Self {
        Self {
            value: None,
            status: RECEIPT_STATUS_NOT_EXECUTED,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CachePlanPerformanceReceiptV2 {
    pub rust_module_load_count: ReceiptMetricU64,
    pub rust_module_load_time_ns: ReceiptMetricU64,
    pub rust_process_spawn_count: ReceiptMetricU64,
    pub calls_per_generation: ReceiptMetricU64,
    pub calls_per_step: ReceiptMetricU64,
    pub calls_per_block: ReceiptMetricU64,
    pub calls_per_region: ReceiptMetricU64,
    pub calls_per_row: ReceiptMetricU64,
    pub evidence_record_count: ReceiptMetricU64,
    pub evidence_batch_bytes: ReceiptMetricU64,
    pub pyo3_conversion_time_ns: ReceiptMetricU64,
    pub rust_plan_time_ns: ReceiptMetricU64,
    pub ffi_total_time_ns: ReceiptMetricU64,
    pub serialization_time_ns: ReceiptMetricU64,
    pub rust_transfer_bytes: ReceiptMetricU64,
    pub gpu_to_cpu_metadata_bytes: ReceiptMetricU64,
    pub gpu_to_cpu_tensor_bytes: ReceiptMetricU64,
    pub cpu_to_gpu_metadata_bytes: ReceiptMetricU64,
    pub cpu_to_gpu_tensor_bytes: ReceiptMetricU64,
    pub cuda_sync_count: ReceiptMetricU64,
    pub selected_payload_bytes: ReceiptMetricU64,
    pub planned_d2h_bytes: ReceiptMetricU64,
    pub planned_h2d_bytes: ReceiptMetricU64,
    pub actual_d2h_bytes: ReceiptMetricU64,
    pub actual_h2d_bytes: ReceiptMetricU64,
    pub d2h_estimate_error_bytes: ReceiptMetricU64,
    pub h2d_estimate_error_bytes: ReceiptMetricU64,
    pub fallback_count: ReceiptMetricU64,
    pub partial_full_recovery_count: ReceiptMetricU64,
    pub rust_overhead_ratio_ppm: ReceiptMetricU64,
}

impl CachePlanPerformanceReceiptV2 {
    fn model_free(batch: &GenerationEvidenceBatchV2, fallback: bool) -> Self {
        Self {
            rust_module_load_count: ReceiptMetricU64::unknown(),
            rust_module_load_time_ns: ReceiptMetricU64::unknown(),
            rust_process_spawn_count: ReceiptMetricU64::structural_zero(),
            calls_per_generation: ReceiptMetricU64::measured(1),
            calls_per_step: ReceiptMetricU64::structural_zero(),
            calls_per_block: ReceiptMetricU64::structural_zero(),
            calls_per_region: ReceiptMetricU64::structural_zero(),
            calls_per_row: ReceiptMetricU64::structural_zero(),
            evidence_record_count: ReceiptMetricU64::measured(batch.records.len() as u64),
            evidence_batch_bytes: ReceiptMetricU64::measured(batch.header.batch_bytes),
            pyo3_conversion_time_ns: ReceiptMetricU64::unknown(),
            rust_plan_time_ns: ReceiptMetricU64::unknown(),
            ffi_total_time_ns: ReceiptMetricU64::unknown(),
            serialization_time_ns: ReceiptMetricU64::structural_zero(),
            rust_transfer_bytes: ReceiptMetricU64::measured(batch.header.batch_bytes),
            gpu_to_cpu_metadata_bytes: ReceiptMetricU64::not_executed(),
            gpu_to_cpu_tensor_bytes: ReceiptMetricU64::not_executed(),
            cpu_to_gpu_metadata_bytes: ReceiptMetricU64::not_executed(),
            cpu_to_gpu_tensor_bytes: ReceiptMetricU64::not_executed(),
            cuda_sync_count: ReceiptMetricU64::not_executed(),
            selected_payload_bytes: ReceiptMetricU64::measured(0),
            planned_d2h_bytes: ReceiptMetricU64::measured(0),
            planned_h2d_bytes: ReceiptMetricU64::measured(0),
            actual_d2h_bytes: ReceiptMetricU64::not_executed(),
            actual_h2d_bytes: ReceiptMetricU64::not_executed(),
            d2h_estimate_error_bytes: ReceiptMetricU64::not_executed(),
            h2d_estimate_error_bytes: ReceiptMetricU64::not_executed(),
            fallback_count: ReceiptMetricU64::measured(u64::from(fallback)),
            partial_full_recovery_count: ReceiptMetricU64::not_executed(),
            rust_overhead_ratio_ppm: ReceiptMetricU64::unknown(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GenerationCachePlanV2 {
    pub abi_version: u32,
    pub decision_code: u32,
    pub reason_code: u32,
    pub fallback_required: bool,
    pub selected: Vec<SelectedCacheKeyV2>,
    pub rejected: Vec<RejectedCacheKeyV2>,
    pub eviction_order: Vec<EvictionKeyV2>,
    pub total_selected_bytes: u64,
    pub total_planned_q_rows: u64,
    pub total_full_q_rows: u64,
    pub planned_reduction_ppm: u64,
    pub total_planned_d2h_bytes: u64,
    pub total_planned_h2d_bytes: u64,
    pub plan_digest: [u8; 32],
    pub lineage_digest: [u8; 32],
    pub receipt: CachePlanPerformanceReceiptV2,
}

#[derive(Clone, Debug)]
struct CandidateGroup {
    block_index: u32,
    region: u32,
    payload_bytes: u64,
    planned_q_rows: u64,
    planned_d2h_bytes: u64,
    planned_h2d_bytes: u64,
    records: Vec<CacheCandidateV2>,
    rejection_reason: Option<u32>,
}

impl CandidateGroup {
    fn selected(&self, identity: &GenerationIdentityV2) -> SelectedCacheKeyV2 {
        let transfer = self
            .planned_d2h_bytes
            .saturating_add(self.planned_h2d_bytes);
        SelectedCacheKeyV2 {
            block_index: self.block_index,
            region: self.region,
            payload_bytes: self.payload_bytes,
            planned_q_rows: self.planned_q_rows,
            planned_d2h_bytes: self.planned_d2h_bytes,
            planned_h2d_bytes: self.planned_h2d_bytes,
            effect_numerator: self.planned_q_rows,
            effect_denominator: self.payload_bytes,
            transfer_effect_numerator: self.planned_q_rows,
            transfer_effect_denominator: transfer,
            selection_lineage_digest: selection_lineage_digest(
                identity,
                self.block_index,
                self.region,
            ),
        }
    }
}

fn digest_parts(parts: &[&[u8]]) -> [u8; 32] {
    let mut hasher = Sha256::new();
    for part in parts {
        hasher.update(part);
    }
    hasher.finalize().into()
}

pub fn cache_lineage_v2_digest(
    identity: &GenerationIdentityV2,
    candidate: &CacheCandidateV2,
) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(b"hiveframe-cache-lineage-v2");
    for digest in [
        identity.run_digest,
        identity.workflow_digest,
        identity.model_digest,
        identity.model_revision_digest,
        identity.settings_digest,
        identity.source_plan_digest,
        identity.layout_digest,
        identity.input_identity_digest,
    ] {
        hasher.update(digest);
    }
    for value in [
        identity.scheduler_id,
        identity.total_steps,
        identity.width,
        identity.height,
        identity.frame_count,
        identity.fps_numerator,
        identity.fps_denominator,
        candidate.block_index,
        candidate.region,
        candidate.source_step,
        candidate.source_kind,
        candidate.shape_rows,
        candidate.shape_width,
        candidate.dtype,
        candidate.device_class,
        candidate.precision,
        candidate.quantization,
    ] {
        hasher.update(value.to_le_bytes());
    }
    hasher.update(candidate.shape_digest);
    hasher.update(candidate.packed_row_digest);
    hasher.finalize().into()
}

fn selection_lineage_digest(
    identity: &GenerationIdentityV2,
    block_index: u32,
    region: u32,
) -> [u8; 32] {
    digest_parts(&[
        b"hiveframe-cache-selection-lineage-v2",
        &identity.run_digest,
        &identity.workflow_digest,
        &identity.model_digest,
        &identity.model_revision_digest,
        &identity.settings_digest,
        &identity.source_plan_digest,
        &identity.layout_digest,
        &identity.input_identity_digest,
        &block_index.to_le_bytes(),
        &region.to_le_bytes(),
    ])
}

fn ratio_cmp(
    left_numerator: u64,
    left_denominator: u64,
    right_numerator: u64,
    right_denominator: u64,
) -> Ordering {
    (left_numerator as u128 * right_denominator as u128)
        .cmp(&(right_numerator as u128 * left_denominator as u128))
}

fn candidate_rejection(
    candidate: &CacheCandidateV2,
    identity: &GenerationIdentityV2,
    profile: &HardwareProfileV2,
) -> Option<u32> {
    if candidate.state != CACHE_STATE_STABLE {
        Some(CACHE_REJECT_NOT_STABLE)
    } else if candidate.safety_evidence_present != 1 {
        Some(CACHE_REJECT_SAFETY_EVIDENCE_MISSING)
    } else if candidate.actual_safety_state != CACHE_SAFETY_SAFE {
        Some(CACHE_REJECT_ACTUAL_UNSAFE)
    } else if candidate.false_safe_count != 0 {
        Some(CACHE_REJECT_FALSE_SAFE)
    } else if candidate.lineage_digest != cache_lineage_v2_digest(identity, candidate) {
        Some(CACHE_REJECT_LINEAGE_MISMATCH)
    } else if candidate.cache_age != profile.cache_age {
        Some(CACHE_REJECT_AGE_MISMATCH)
    } else if candidate.nonfinite_count != 0 {
        Some(CACHE_REJECT_NONFINITE)
    } else if candidate.admission_eligible != 1 || candidate.rejection_reason != 0 {
        Some(CACHE_REJECT_NOT_ELIGIBLE)
    } else {
        None
    }
}

fn fail_open_plan(
    reason_code: u32,
    request: &GenerationCachePlanRequest,
    batch: &GenerationEvidenceBatchV2,
) -> GenerationCachePlanV2 {
    let plan_digest = digest_parts(&[
        b"hiveframe-cache-plan-v2-fail-open",
        &reason_code.to_le_bytes(),
        &request.generation_id.to_le_bytes(),
    ]);
    GenerationCachePlanV2 {
        abi_version: CACHE_PLAN_ABI_V2_VERSION,
        decision_code: CACHE_PLAN_V2_FULL_COMPUTE,
        reason_code,
        fallback_required: true,
        selected: Vec::new(),
        rejected: Vec::new(),
        eviction_order: Vec::new(),
        total_selected_bytes: 0,
        total_planned_q_rows: 0,
        total_full_q_rows: request.total_full_q_rows,
        planned_reduction_ppm: 0,
        total_planned_d2h_bytes: 0,
        total_planned_h2d_bytes: 0,
        plan_digest,
        lineage_digest: [0; 32],
        receipt: CachePlanPerformanceReceiptV2::model_free(batch, true),
    }
}

pub fn fail_open_cache_plan_v2(reason_code: u32) -> GenerationCachePlanV2 {
    let request = GenerationCachePlanRequest {
        abi_version: CACHE_PLAN_ABI_V2_VERSION,
        struct_size: GenerationCachePlanRequest::contract_size(),
        contract_version: CACHE_PLAN_V2_CONTRACT_VERSION,
        overflow_policy: CACHE_PLAN_V2_OVERFLOW_FULL_COMPUTE,
        generation_id: 0,
        current_step: 0,
        maximum_batch_records: CACHE_PLAN_V2_MAX_RECORDS as u32,
        maximum_batch_bytes: CACHE_PLAN_V2_MAX_BATCH_BYTES,
        total_full_q_rows: 0,
        unsupported_flags: 0,
    };
    let batch = GenerationEvidenceBatchV2 {
        header: GenerationEvidenceBatchHeader {
            abi_version: CACHE_PLAN_ABI_V2_VERSION,
            struct_size: GenerationEvidenceBatchHeader::contract_size(),
            generation_id: 0,
            record_count: 0,
            maximum_records: CACHE_PLAN_V2_MAX_RECORDS as u32,
            batch_bytes: u64::from(GenerationEvidenceBatchHeader::contract_size()),
            overflowed: 0,
            truncated: 0,
            tensor_bytes: 0,
            unsupported_flags: 0,
        },
        records: Vec::new(),
    };
    fail_open_plan(reason_code, &request, &batch)
}

pub fn compile_cache_plan_v2(
    request: &GenerationCachePlanRequest,
    identity: &GenerationIdentityV2,
    profile: &HardwareProfileV2,
    batch: &GenerationEvidenceBatchV2,
    inventory: &[CacheInventoryEntryV2],
) -> GenerationCachePlanV2 {
    let structural_reason = if request.abi_version != CACHE_PLAN_ABI_V2_VERSION
        || request.contract_version != CACHE_PLAN_V2_CONTRACT_VERSION
    {
        CACHE_PLAN_V2_REASON_ABI_MISMATCH
    } else if request.struct_size != GenerationCachePlanRequest::contract_size()
        || batch.header.struct_size != GenerationEvidenceBatchHeader::contract_size()
        || profile.struct_size != HardwareProfileV2::contract_size()
    {
        CACHE_PLAN_V2_REASON_STRUCT_SIZE_MISMATCH
    } else if request.overflow_policy != CACHE_PLAN_V2_OVERFLOW_FULL_COMPUTE
        || request.total_full_q_rows == 0
        || request.unsupported_flags != 0
        || !identity.valid(request)
    {
        CACHE_PLAN_V2_REASON_IDENTITY_INVALID
    } else if !profile.valid()
        || profile.resolution_width != identity.width
        || profile.resolution_height != identity.height
        || identity.frame_count > profile.frame_budget
    {
        CACHE_PLAN_V2_REASON_PROFILE_INVALID
    } else if batch.header.abi_version != CACHE_PLAN_ABI_V2_VERSION {
        CACHE_PLAN_V2_REASON_ABI_MISMATCH
    } else if batch.header.generation_id != request.generation_id
        || batch.header.record_count as usize != batch.records.len()
        || batch.header.maximum_records != request.maximum_batch_records
        || batch.header.tensor_bytes != 0
        || batch.header.unsupported_flags != 0
    {
        CACHE_PLAN_V2_REASON_BATCH_MALFORMED
    } else if batch.header.overflowed != 0
        || batch.header.truncated != 0
        || batch.records.len() > CACHE_PLAN_V2_MAX_RECORDS
        || batch.records.len() > request.maximum_batch_records as usize
        || batch.records.len() > profile.maximum_candidates as usize
        || batch.header.batch_bytes > request.maximum_batch_bytes
        || batch.header.batch_bytes > profile.maximum_batch_bytes
        || batch.header.batch_bytes > CACHE_PLAN_V2_MAX_BATCH_BYTES
        || batch.records.len() > profile.maximum_work_units as usize
    {
        CACHE_PLAN_V2_REASON_BATCH_OVERFLOW
    } else if batch.header.batch_bytes
        != u64::from(GenerationEvidenceBatchHeader::contract_size())
            + batch.records.len() as u64 * u64::from(CacheCandidateV2::contract_size())
    {
        CACHE_PLAN_V2_REASON_BATCH_MALFORMED
    } else if batch
        .records
        .iter()
        .any(|candidate| !candidate.structurally_valid(identity))
    {
        CACHE_PLAN_V2_REASON_RECORD_MALFORMED
    } else if inventory.len() > CACHE_PLAN_V2_MAX_INVENTORY
        || inventory.iter().any(|entry| {
            entry.block_index >= 50
                || entry.region >= 4
                || entry.source_step >= identity.total_steps
                || entry.valid > 1
                || entry.payload_bytes == 0
                || entry.lineage_digest == [0; 32]
        })
    {
        CACHE_PLAN_V2_REASON_INVENTORY_MALFORMED
    } else {
        CACHE_PLAN_V2_REASON_NONE
    };
    if structural_reason != CACHE_PLAN_V2_REASON_NONE {
        return fail_open_plan(structural_reason, request, batch);
    }

    let mut groups: BTreeMap<(u32, u32), CandidateGroup> = BTreeMap::new();
    let mut evidence_events: BTreeMap<(u32, u32, u32, u32), CacheCandidateV2> = BTreeMap::new();
    for candidate in &batch.records {
        let event_key = (
            candidate.target_step,
            candidate.source_step,
            candidate.block_index,
            candidate.region,
        );
        if let Some(previous) = evidence_events.get(&event_key) {
            if previous == candidate {
                continue;
            }
            return fail_open_plan(CACHE_PLAN_V2_REASON_RECORD_MALFORMED, request, batch);
        }
        evidence_events.insert(event_key, *candidate);
        let key = (candidate.block_index, candidate.region);
        let rejection = candidate_rejection(candidate, identity, profile);
        let group = groups.entry(key).or_insert_with(|| CandidateGroup {
            block_index: candidate.block_index,
            region: candidate.region,
            payload_bytes: candidate.payload_bytes,
            planned_q_rows: 0,
            planned_d2h_bytes: 0,
            planned_h2d_bytes: 0,
            records: Vec::new(),
            rejection_reason: None,
        });
        if group.payload_bytes != candidate.payload_bytes
            || group.records.iter().any(|record| {
                record.shape_rows != candidate.shape_rows
                    || record.shape_width != candidate.shape_width
                    || record.dtype != candidate.dtype
                    || record.device_class != candidate.device_class
                    || record.precision != candidate.precision
                    || record.quantization != candidate.quantization
            })
        {
            return fail_open_plan(CACHE_PLAN_V2_REASON_RECORD_MALFORMED, request, batch);
        }
        group.planned_q_rows = group
            .planned_q_rows
            .saturating_add(candidate.planned_q_rows);
        group.planned_d2h_bytes = group
            .planned_d2h_bytes
            .saturating_add(candidate.planned_d2h_bytes);
        group.planned_h2d_bytes = group
            .planned_h2d_bytes
            .saturating_add(candidate.planned_h2d_bytes);
        if rejection.is_some() {
            group.rejection_reason = rejection;
        }
        group.records.push(*candidate);
    }

    let mut eligible: Vec<CandidateGroup> = groups
        .values()
        .filter(|group| group.rejection_reason.is_none())
        .cloned()
        .collect();
    eligible.sort_by(|left, right| {
        ratio_cmp(
            right.planned_q_rows,
            right.payload_bytes,
            left.planned_q_rows,
            left.payload_bytes,
        )
        .then_with(|| left.block_index.cmp(&right.block_index))
        .then_with(|| left.region.cmp(&right.region))
    });

    let mut selected = Vec::new();
    let mut rejected: Vec<RejectedCacheKeyV2> = groups
        .values()
        .filter_map(|group| {
            group
                .rejection_reason
                .map(|reason_code| RejectedCacheKeyV2 {
                    block_index: group.block_index,
                    region: group.region,
                    reason_code,
                })
        })
        .collect();
    let mut selected_bytes = 0_u64;
    let mut planned_q_rows = 0_u64;
    let mut planned_d2h = 0_u64;
    let mut planned_h2d = 0_u64;
    for group in eligible {
        let transfer = group
            .planned_d2h_bytes
            .saturating_add(group.planned_h2d_bytes);
        let current_transfer = planned_d2h.saturating_add(planned_h2d);
        let rejection_reason = if group.payload_bytes > profile.gpu_staging_budget_bytes {
            Some(CACHE_REJECT_PROFILE_STAGING_BUDGET)
        } else if selected.len() >= profile.maximum_selected_regions as usize {
            Some(CACHE_REJECT_PROFILE_SELECTED_LIMIT)
        } else if selected_bytes.saturating_add(group.payload_bytes)
            > profile.host_cache_budget_bytes
        {
            Some(CACHE_REJECT_PROFILE_CACHE_BUDGET)
        } else if current_transfer.saturating_add(transfer) > profile.maximum_transfer_bytes {
            Some(CACHE_REJECT_PROFILE_TRANSFER_BUDGET)
        } else {
            None
        };
        if let Some(reason_code) = rejection_reason {
            rejected.push(RejectedCacheKeyV2 {
                block_index: group.block_index,
                region: group.region,
                reason_code,
            });
            continue;
        }
        selected_bytes = selected_bytes.saturating_add(group.payload_bytes);
        planned_q_rows = planned_q_rows.saturating_add(group.planned_q_rows);
        planned_d2h = planned_d2h.saturating_add(group.planned_d2h_bytes);
        planned_h2d = planned_h2d.saturating_add(group.planned_h2d_bytes);
        selected.push(group.selected(identity));
    }
    rejected.sort_by_key(|item| (item.block_index, item.region, item.reason_code));

    let selected_keys: BTreeSet<(u32, u32)> = selected
        .iter()
        .map(|item| (item.block_index, item.region))
        .collect();
    let candidate_lineages: BTreeSet<[u8; 32]> = batch
        .records
        .iter()
        .filter(|item| selected_keys.contains(&(item.block_index, item.region)))
        .map(|item| item.lineage_digest)
        .collect();
    let mut evictions: Vec<(&CacheInventoryEntryV2, u32)> = inventory
        .iter()
        .filter_map(|entry| {
            let selected_key = selected_keys.contains(&(entry.block_index, entry.region));
            let lineage_valid = candidate_lineages.contains(&entry.lineage_digest);
            let reason =
                if entry.valid != 1 || !lineage_valid || entry.cache_age != profile.cache_age {
                    CACHE_REJECT_LINEAGE_MISMATCH
                } else if !selected_key {
                    CACHE_REJECT_PROFILE_CACHE_BUDGET
                } else {
                    return None;
                };
            Some((entry, reason))
        })
        .collect();
    evictions.sort_by(|(left, left_reason), (right, right_reason)| {
        left_reason
            .cmp(right_reason)
            .then_with(|| {
                ratio_cmp(
                    left.planned_q_rows,
                    left.payload_bytes,
                    right.planned_q_rows,
                    right.payload_bytes,
                )
            })
            .then_with(|| right.block_index.cmp(&left.block_index))
            .then_with(|| right.region.cmp(&left.region))
    });
    let eviction_order = evictions
        .into_iter()
        .map(|(entry, reason_code)| EvictionKeyV2 {
            block_index: entry.block_index,
            region: entry.region,
            reason_code,
        })
        .collect::<Vec<_>>();

    let planned_reduction_ppm =
        ((planned_q_rows as u128 * 1_000_000_u128) / request.total_full_q_rows as u128) as u64;
    let gate_passed = planned_reduction_ppm >= CACHE_PLAN_V2_MIN_REDUCTION_PPM;
    let decision_code = if gate_passed {
        CACHE_PLAN_V2_READY
    } else {
        CACHE_PLAN_V2_FULL_COMPUTE
    };
    let reason_code = if gate_passed {
        CACHE_PLAN_V2_REASON_NONE
    } else {
        CACHE_PLAN_V2_REASON_PRE_GATE_BELOW_THREE_PERCENT
    };

    let mut lineage_hasher = Sha256::new();
    lineage_hasher.update(b"hiveframe-cache-plan-lineage-v2");
    for item in &selected {
        lineage_hasher.update(item.selection_lineage_digest);
    }
    let lineage_digest: [u8; 32] = lineage_hasher.finalize().into();
    let mut plan_hasher = Sha256::new();
    plan_hasher.update(b"hiveframe-generation-cache-plan-v2");
    plan_hasher.update(request.generation_id.to_le_bytes());
    plan_hasher.update(profile.profile_id.to_le_bytes());
    plan_hasher.update(batch.header.batch_bytes.to_le_bytes());
    plan_hasher.update(decision_code.to_le_bytes());
    plan_hasher.update(reason_code.to_le_bytes());
    plan_hasher.update(selected_bytes.to_le_bytes());
    plan_hasher.update(planned_q_rows.to_le_bytes());
    plan_hasher.update(request.total_full_q_rows.to_le_bytes());
    plan_hasher.update(planned_d2h.to_le_bytes());
    plan_hasher.update(planned_h2d.to_le_bytes());
    for item in &selected {
        plan_hasher.update(item.block_index.to_le_bytes());
        plan_hasher.update(item.region.to_le_bytes());
        plan_hasher.update(item.payload_bytes.to_le_bytes());
        plan_hasher.update(item.planned_q_rows.to_le_bytes());
        plan_hasher.update(item.selection_lineage_digest);
    }
    for item in &rejected {
        plan_hasher.update(item.block_index.to_le_bytes());
        plan_hasher.update(item.region.to_le_bytes());
        plan_hasher.update(item.reason_code.to_le_bytes());
    }
    for item in &eviction_order {
        plan_hasher.update(item.block_index.to_le_bytes());
        plan_hasher.update(item.region.to_le_bytes());
        plan_hasher.update(item.reason_code.to_le_bytes());
    }
    let plan_digest = plan_hasher.finalize().into();
    let mut receipt = CachePlanPerformanceReceiptV2::model_free(batch, !gate_passed);
    receipt.selected_payload_bytes = ReceiptMetricU64::measured(selected_bytes);
    receipt.planned_d2h_bytes = ReceiptMetricU64::measured(planned_d2h);
    receipt.planned_h2d_bytes = ReceiptMetricU64::measured(planned_h2d);

    GenerationCachePlanV2 {
        abi_version: CACHE_PLAN_ABI_V2_VERSION,
        decision_code,
        reason_code,
        fallback_required: !gate_passed,
        selected,
        rejected,
        eviction_order,
        total_selected_bytes: selected_bytes,
        total_planned_q_rows: planned_q_rows,
        total_full_q_rows: request.total_full_q_rows,
        planned_reduction_ppm,
        total_planned_d2h_bytes: planned_d2h,
        total_planned_h2d_bytes: planned_h2d,
        plan_digest,
        lineage_digest,
        receipt,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn identity() -> GenerationIdentityV2 {
        GenerationIdentityV2 {
            run_digest: [1; 32],
            workflow_digest: [2; 32],
            model_digest: [3; 32],
            model_revision_digest: [4; 32],
            settings_digest: [5; 32],
            source_plan_digest: [6; 32],
            layout_digest: [7; 32],
            input_identity_digest: [8; 32],
            generation_id: 101,
            scheduler_id: 1,
            total_steps: 20,
            width: 864,
            height: 480,
            frame_count: 124,
            fps_numerator: 24,
            fps_denominator: 1,
        }
    }

    fn request(_record_count: usize) -> GenerationCachePlanRequest {
        GenerationCachePlanRequest {
            abi_version: CACHE_PLAN_ABI_V2_VERSION,
            struct_size: GenerationCachePlanRequest::contract_size(),
            contract_version: CACHE_PLAN_V2_CONTRACT_VERSION,
            overflow_policy: CACHE_PLAN_V2_OVERFLOW_FULL_COMPUTE,
            generation_id: 101,
            current_step: 0,
            maximum_batch_records: CACHE_PLAN_V2_MAX_RECORDS as u32,
            maximum_batch_bytes: CACHE_PLAN_V2_MAX_BATCH_BYTES,
            total_full_q_rows: 15_424_000,
            unsupported_flags: 0,
        }
    }

    fn candidate(block: u32, region: u32, events: u64) -> CacheCandidateV2 {
        let rows = [3_367_u32, 3_108, 2_886, 2_664][region as usize];
        let omitted = [2_331_u64, 2_072, 1_850, 1_628][region as usize] * events;
        let payload = u64::from(rows) * 7_168 * 2;
        let mut value = CacheCandidateV2 {
            target_step: 2,
            source_step: 1,
            block_index: block,
            region,
            packed_row_start: region * 3_000,
            packed_row_count: rows,
            state: CACHE_STATE_STABLE,
            actual_safety_state: CACHE_SAFETY_SAFE,
            safety_evidence_present: 1,
            uncertainty_ppm: 10_000,
            motion_ppm: 20_000,
            cosine_ppm: 990_000,
            corrected_nl2_ppm: 100_000,
            false_safe_count: 0,
            nonfinite_count: 0,
            cache_age: 1,
            source_kind: CACHE_SOURCE_ACTUAL_FULL_ATTENTION_CORE_OUTPUT,
            shape_rows: rows,
            shape_width: 7_168,
            dtype: CACHE_DTYPE_BFLOAT16,
            device_class: CACHE_DEVICE_CPU_PINNED,
            precision: CACHE_PRECISION_BFLOAT16,
            quantization: CACHE_QUANTIZATION_NONE,
            admission_eligible: 1,
            rejection_reason: 0,
            planned_q_rows: omitted,
            full_q_rows: 100_000,
            payload_bytes: payload,
            effect_numerator: omitted,
            effect_denominator: payload,
            planned_d2h_bytes: payload,
            planned_h2d_bytes: payload,
            shape_digest: [9; 32],
            packed_row_digest: [10; 32],
            lineage_digest: [0; 32],
        };
        value.lineage_digest = cache_lineage_v2_digest(&identity(), &value);
        value
    }

    fn batch(records: Vec<CacheCandidateV2>) -> GenerationEvidenceBatchV2 {
        GenerationEvidenceBatchV2 {
            header: GenerationEvidenceBatchHeader {
                abi_version: CACHE_PLAN_ABI_V2_VERSION,
                struct_size: GenerationEvidenceBatchHeader::contract_size(),
                generation_id: 101,
                record_count: records.len() as u32,
                maximum_records: CACHE_PLAN_V2_MAX_RECORDS as u32,
                batch_bytes: u64::from(GenerationEvidenceBatchHeader::contract_size())
                    + records.len() as u64 * u64::from(CacheCandidateV2::contract_size()),
                overflowed: 0,
                truncated: 0,
                tensor_bytes: 0,
                unsupported_flags: 0,
            },
            records,
        }
    }

    #[test]
    fn abi_sizes_and_profiles_are_fixed_and_distinct() {
        assert_eq!(CACHE_PLAN_ABI_V2_VERSION, 2);
        assert!(GenerationCachePlanRequest::contract_size() > 0);
        assert!(GenerationEvidenceBatchHeader::contract_size() > 0);
        assert!(CacheCandidateV2::contract_size() > 0);
        assert!(CacheInventoryEntryV2::contract_size() > 0);
        assert!(HardwareProfileV2::balanced_12gb().valid());
        assert!(HardwareProfileV2::quality_24gb_plus().valid());
        assert_eq!(
            HardwareProfileV2::balanced_12gb().host_cache_budget_bytes,
            2 * 1_024 * 1_024 * 1_024
        );
        assert!(
            HardwareProfileV2::quality_24gb_plus().host_cache_budget_bytes
                > HardwareProfileV2::balanced_12gb().host_cache_budget_bytes
        );
    }

    #[test]
    fn v1_or_size_mismatch_fails_open() {
        let records = batch(vec![candidate(0, 0, 7)]);
        let mut bad = request(records.records.len());
        bad.abi_version = 1;
        let first = compile_cache_plan_v2(
            &bad,
            &identity(),
            &HardwareProfileV2::balanced_12gb(),
            &records,
            &[],
        );
        assert_eq!(first.decision_code, CACHE_PLAN_V2_FULL_COMPUTE);
        assert_eq!(first.reason_code, CACHE_PLAN_V2_REASON_ABI_MISMATCH);
        bad.abi_version = CACHE_PLAN_ABI_V2_VERSION;
        bad.struct_size = 0;
        let second = compile_cache_plan_v2(
            &bad,
            &identity(),
            &HardwareProfileV2::balanced_12gb(),
            &records,
            &[],
        );
        assert_eq!(
            second.reason_code,
            CACHE_PLAN_V2_REASON_STRUCT_SIZE_MISMATCH
        );
    }

    #[test]
    fn overflow_truncation_and_tensor_bytes_fail_open() {
        let mut records = batch(vec![candidate(0, 0, 7)]);
        records.header.overflowed = 1;
        let overflow = compile_cache_plan_v2(
            &request(1),
            &identity(),
            &HardwareProfileV2::balanced_12gb(),
            &records,
            &[],
        );
        assert_eq!(overflow.reason_code, CACHE_PLAN_V2_REASON_BATCH_OVERFLOW);
        records.header.overflowed = 0;
        records.header.truncated = 1;
        assert_eq!(
            compile_cache_plan_v2(
                &request(1),
                &identity(),
                &HardwareProfileV2::balanced_12gb(),
                &records,
                &[],
            )
            .reason_code,
            CACHE_PLAN_V2_REASON_BATCH_OVERFLOW
        );
        records.header.truncated = 0;
        records.header.tensor_bytes = 1;
        assert_eq!(
            compile_cache_plan_v2(
                &request(1),
                &identity(),
                &HardwareProfileV2::balanced_12gb(),
                &records,
                &[],
            )
            .reason_code,
            CACHE_PLAN_V2_REASON_BATCH_MALFORMED
        );
    }

    #[test]
    fn deterministic_admission_reaches_frozen_three_percent_without_unsafe_fill() {
        let records = batch((0..29).map(|block| candidate(block, 0, 7)).collect());
        let first = compile_cache_plan_v2(
            &request(records.records.len()),
            &identity(),
            &HardwareProfileV2::balanced_12gb(),
            &records,
            &[],
        );
        let second = compile_cache_plan_v2(
            &request(records.records.len()),
            &identity(),
            &HardwareProfileV2::balanced_12gb(),
            &records,
            &[],
        );
        assert_eq!(first, second);
        assert_eq!(first.decision_code, CACHE_PLAN_V2_READY);
        assert_eq!(first.selected.len(), 29);
        assert_eq!(first.total_selected_bytes, 1_399_810_048);
        assert_eq!(first.total_planned_q_rows, 473_193);
        assert!(first.planned_reduction_ppm >= CACHE_PLAN_V2_MIN_REDUCTION_PPM);
        assert!(
            first.total_selected_bytes
                <= HardwareProfileV2::balanced_12gb().host_cache_budget_bytes
        );
        assert_eq!(
            first.receipt.rust_transfer_bytes.value,
            Some(records.header.batch_bytes)
        );
        assert_eq!(first.receipt.calls_per_block.value, Some(0));
        assert_eq!(first.receipt.calls_per_region.value, Some(0));
    }

    #[test]
    fn unsafe_nonstable_nonfinite_age_and_lineage_are_excluded() {
        let mut values = vec![candidate(0, 0, 7)];
        let mut active = candidate(1, 0, 7);
        active.state = CACHE_STATE_ACTIVE;
        values.push(active);
        let mut unsafe_item = candidate(2, 0, 7);
        unsafe_item.actual_safety_state = CACHE_SAFETY_UNSAFE;
        values.push(unsafe_item);
        let mut false_safe = candidate(3, 0, 7);
        false_safe.false_safe_count = 1;
        values.push(false_safe);
        let mut stale = candidate(4, 0, 7);
        stale.cache_age = 2;
        values.push(stale);
        let mut nonfinite = candidate(5, 0, 7);
        nonfinite.nonfinite_count = 1;
        values.push(nonfinite);
        let mut mismatch = candidate(6, 0, 7);
        mismatch.lineage_digest = [99; 32];
        values.push(mismatch);
        let records = batch(values);
        let plan = compile_cache_plan_v2(
            &request(records.records.len()),
            &identity(),
            &HardwareProfileV2::balanced_12gb(),
            &records,
            &[],
        );
        assert_eq!(plan.selected.len(), 1);
        assert_eq!(plan.rejected.len(), 6);
        assert_eq!(plan.decision_code, CACHE_PLAN_V2_FULL_COMPUTE);
        assert_eq!(
            plan.reason_code,
            CACHE_PLAN_V2_REASON_PRE_GATE_BELOW_THREE_PERCENT
        );
    }

    #[test]
    fn duplicate_evidence_is_aggregated_and_ties_are_stable() {
        let first = candidate(0, 0, 7);
        let mut second = candidate(0, 0, 3);
        second.target_step = 3;
        second.source_step = 2;
        second.lineage_digest = cache_lineage_v2_digest(&identity(), &second);
        let records = batch(vec![candidate(1, 0, 7), first, first, second]);
        let plan = compile_cache_plan_v2(
            &request(records.records.len()),
            &identity(),
            &HardwareProfileV2::balanced_12gb(),
            &records,
            &[],
        );
        assert_eq!(plan.selected.len(), 2);
        assert_eq!(plan.selected[0].block_index, 0);
        assert_eq!(plan.selected[0].planned_q_rows, 23_310);
    }

    #[test]
    fn unknown_enum_and_conflicting_duplicate_fail_open() {
        let mut unknown = candidate(0, 0, 7);
        unknown.state = 99;
        let records = batch(vec![unknown]);
        assert_eq!(
            compile_cache_plan_v2(
                &request(1),
                &identity(),
                &HardwareProfileV2::balanced_12gb(),
                &records,
                &[],
            )
            .reason_code,
            CACHE_PLAN_V2_REASON_RECORD_MALFORMED
        );

        let first = candidate(0, 0, 7);
        let mut conflict = first;
        conflict.planned_q_rows += 1;
        conflict.effect_numerator += 1;
        let records = batch(vec![first, conflict]);
        assert_eq!(
            compile_cache_plan_v2(
                &request(2),
                &identity(),
                &HardwareProfileV2::balanced_12gb(),
                &records,
                &[],
            )
            .reason_code,
            CACHE_PLAN_V2_REASON_RECORD_MALFORMED
        );
    }

    #[test]
    fn cache_and_transfer_budgets_reject_without_overcommit() {
        let records = batch(vec![candidate(0, 0, 7), candidate(1, 0, 7)]);
        let payload = records.records[0].payload_bytes;
        let mut cache_limited = HardwareProfileV2::balanced_12gb();
        cache_limited.host_cache_budget_bytes = payload;
        let cache_plan =
            compile_cache_plan_v2(&request(2), &identity(), &cache_limited, &records, &[]);
        assert_eq!(cache_plan.selected.len(), 1);
        assert_eq!(cache_plan.total_selected_bytes, payload);
        assert!(cache_plan
            .rejected
            .iter()
            .any(|item| item.reason_code == CACHE_REJECT_PROFILE_CACHE_BUDGET));

        let mut transfer_limited = HardwareProfileV2::balanced_12gb();
        transfer_limited.maximum_transfer_bytes = payload * 2;
        let transfer_plan =
            compile_cache_plan_v2(&request(2), &identity(), &transfer_limited, &records, &[]);
        assert_eq!(transfer_plan.selected.len(), 1);
        assert_eq!(
            transfer_plan.total_planned_d2h_bytes + transfer_plan.total_planned_h2d_bytes,
            payload * 2
        );
        assert!(transfer_plan
            .rejected
            .iter()
            .any(|item| item.reason_code == CACHE_REJECT_PROFILE_TRANSFER_BUDGET));
    }

    #[test]
    fn bounded_batch_and_profile_enums_fail_open() {
        let records = batch(vec![candidate(0, 0, 7), candidate(1, 0, 7)]);
        let mut bounded_request = request(2);
        bounded_request.maximum_batch_records = 1;
        let mut bounded_batch = records.clone();
        bounded_batch.header.maximum_records = 1;
        assert_eq!(
            compile_cache_plan_v2(
                &bounded_request,
                &identity(),
                &HardwareProfileV2::balanced_12gb(),
                &bounded_batch,
                &[],
            )
            .reason_code,
            CACHE_PLAN_V2_REASON_BATCH_OVERFLOW
        );

        let mut unknown_profile = HardwareProfileV2::balanced_12gb();
        unknown_profile.profile_id = 99;
        assert_eq!(
            compile_cache_plan_v2(&request(2), &identity(), &unknown_profile, &records, &[],)
                .reason_code,
            CACHE_PLAN_V2_REASON_PROFILE_INVALID
        );
    }

    #[test]
    fn malformed_record_and_inventory_fail_the_generation_open() {
        let mut malformed = candidate(0, 0, 7);
        malformed.payload_bytes = 0;
        let records = batch(vec![malformed]);
        assert_eq!(
            compile_cache_plan_v2(
                &request(1),
                &identity(),
                &HardwareProfileV2::balanced_12gb(),
                &records,
                &[],
            )
            .reason_code,
            CACHE_PLAN_V2_REASON_RECORD_MALFORMED
        );
        let valid = batch(vec![candidate(0, 0, 7)]);
        let bad_inventory = CacheInventoryEntryV2 {
            block_index: 50,
            region: 0,
            source_step: 1,
            cache_age: 1,
            valid: 1,
            payload_bytes: 1,
            planned_q_rows: 1,
            lineage_digest: [1; 32],
        };
        assert_eq!(
            compile_cache_plan_v2(
                &request(1),
                &identity(),
                &HardwareProfileV2::balanced_12gb(),
                &valid,
                &[bad_inventory],
            )
            .reason_code,
            CACHE_PLAN_V2_REASON_INVENTORY_MALFORMED
        );
    }

    #[test]
    fn eviction_is_deterministic_and_prefers_low_effect_entries() {
        let records = batch((0..29).map(|block| candidate(block, 0, 7)).collect());
        let inventory = vec![
            CacheInventoryEntryV2 {
                block_index: 49,
                region: 3,
                source_step: 1,
                cache_age: 1,
                valid: 1,
                payload_bytes: 100,
                planned_q_rows: 1,
                lineage_digest: [77; 32],
            },
            CacheInventoryEntryV2 {
                block_index: 48,
                region: 3,
                source_step: 1,
                cache_age: 1,
                valid: 1,
                payload_bytes: 100,
                planned_q_rows: 2,
                lineage_digest: [78; 32],
            },
        ];
        let plan = compile_cache_plan_v2(
            &request(records.records.len()),
            &identity(),
            &HardwareProfileV2::balanced_12gb(),
            &records,
            &inventory,
        );
        assert_eq!(plan.eviction_order.len(), 2);
        assert_eq!(plan.eviction_order[0].block_index, 49);
        assert_eq!(plan.eviction_order[1].block_index, 48);
    }

    #[test]
    fn balanced_and_quality_profiles_share_the_algorithm() {
        let records = batch((0..29).map(|block| candidate(block, 0, 7)).collect());
        let balanced = compile_cache_plan_v2(
            &request(records.records.len()),
            &identity(),
            &HardwareProfileV2::balanced_12gb(),
            &records,
            &[],
        );
        let quality = compile_cache_plan_v2(
            &request(records.records.len()),
            &identity(),
            &HardwareProfileV2::quality_24gb_plus(),
            &records,
            &[],
        );
        assert_eq!(balanced.selected, quality.selected);
        assert_eq!(balanced.decision_code, CACHE_PLAN_V2_READY);
        assert_eq!(quality.decision_code, CACHE_PLAN_V2_READY);
    }
}
