#![doc = "Model-free Compound I/O routing, fusion, planning, and admission evidence."]

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
}
