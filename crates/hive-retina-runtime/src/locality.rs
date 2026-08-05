//! Deterministic model-free spatial/temporal locality measurement.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::cmp::Ordering;
use std::collections::BTreeMap;
use std::time::Instant;

#[derive(Clone, Debug, Deserialize)]
pub struct ActivationRule {
    pub id: String,
    pub minimum_changed_numerator: usize,
    pub minimum_changed_denominator: Option<usize>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct TranslationConfig {
    pub downsample_width: usize,
    pub downsample_height: usize,
    pub search_min: i32,
    pub search_max: i32,
    pub full_resolution_scale: usize,
    pub minimum_mad_margin_for_high_confidence: f64,
}

#[derive(Clone, Debug, Deserialize)]
pub struct LocalityConfig {
    pub gray_thresholds: Vec<u8>,
    pub rgb_thresholds: Vec<u8>,
    pub tile_sizes: Vec<usize>,
    pub activation_rules: Vec<ActivationRule>,
    pub halos: Vec<usize>,
    pub translation: TranslationConfig,
}

#[derive(Clone, Debug, Serialize)]
pub struct PixelSurface {
    pub source: String,
    pub threshold: u8,
    pub changed_pixels: u64,
    pub total_pixels: u64,
    pub changed_pixel_ratio: f64,
}

#[derive(Clone, Debug, Serialize)]
pub struct TileSurface {
    pub source: String,
    pub threshold: u8,
    pub tile_size: usize,
    pub activation_rule: String,
    pub halo_tiles: usize,
    pub total_tiles: u64,
    pub active_tiles: u64,
    pub partial_edge_tiles: u64,
    pub additional_closure_tiles: u64,
    pub pairs_at_or_above_75_percent: u64,
    pub pairs_at_or_above_90_percent: u64,
    pub full_pressure_pairs: u64,
    pub active_tile_ratio: f64,
    pub frozen_candidate_ratio: f64,
    pub halo_inflation_ratio: Option<f64>,
}

#[derive(Clone, Debug, Serialize)]
pub struct TemporalPersistence {
    pub source: String,
    pub threshold: u8,
    pub tile_size: usize,
    pub activation_rule: String,
    pub halo_tiles: usize,
    pub active_run_count: usize,
    pub frozen_run_count: usize,
    pub active_run_median: Option<usize>,
    pub active_run_p95: Option<usize>,
    pub frozen_run_median: Option<usize>,
    pub frozen_run_p95: Option<usize>,
    pub active_to_frozen_transitions: u64,
    pub frozen_to_active_transitions: u64,
    pub one_frame_only_activity_ratio: f64,
    pub persistent_activity_ratio: f64,
}

#[derive(Clone, Debug, Serialize)]
pub struct TranslationRecord {
    pub pair_index: usize,
    pub dx_low: i32,
    pub dy_low: i32,
    pub dx_full: i32,
    pub dy_full: i32,
    pub score_sum: u64,
    pub score_count: u64,
    pub second_score_sum: u64,
    pub second_score_count: u64,
    pub confidence_status: String,
    pub exposed_border_pixels: u64,
}

#[derive(Clone, Debug, Serialize)]
pub struct TranslationCost {
    pub estimation_seconds: f64,
    pub apply_seconds: f64,
    pub exposed_border_pixels: u64,
    pub exposed_border_ratio: f64,
    pub low_confidence_pairs: usize,
}

#[derive(Clone, Debug, Serialize)]
pub struct GlobalDelta {
    pub raw_median: Option<f64>,
    pub raw_p95: Option<f64>,
    pub translation_compensated_median: Option<f64>,
    pub translation_compensated_p95: Option<f64>,
}

#[derive(Clone, Debug, Serialize)]
pub struct GraySummary {
    pub schema_version: String,
    pub implementation: String,
    pub pixel_format: String,
    pub frames: usize,
    pub frame_pairs: usize,
    pub width: usize,
    pub height: usize,
    pub pixel_surface: Vec<PixelSurface>,
    pub global_delta: GlobalDelta,
    pub tile_surface: Vec<TileSurface>,
    pub temporal_persistence: Vec<TemporalPersistence>,
    pub translations: Vec<TranslationRecord>,
    pub translation_cost: TranslationCost,
    pub summary_digest: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct RgbSummary {
    pub schema_version: String,
    pub implementation: String,
    pub pixel_format: String,
    pub frames: usize,
    pub frame_pairs: usize,
    pub width: usize,
    pub height: usize,
    pub pixel_surface: Vec<PixelSurface>,
    pub summary_digest: String,
}

#[derive(Clone, Debug)]
struct TranslationEstimate {
    dx_low: i32,
    dy_low: i32,
    dx_full: i32,
    dy_full: i32,
    score_sum: u64,
    score_count: u64,
    second_score_sum: u64,
    second_score_count: u64,
    confidence_status: String,
}

#[derive(Clone, Debug, Default)]
struct TileAccumulator {
    total_tiles: u64,
    active_tiles: u64,
    partial_edge_tiles: u64,
    additional_closure_tiles: u64,
    pairs_at_or_above_75_percent: u64,
    pairs_at_or_above_90_percent: u64,
    full_pressure_pairs: u64,
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut digest = Sha256::new();
    digest.update(bytes);
    format!("{:x}", digest.finalize())
}

pub fn bytes_sha256(bytes: &[u8]) -> String {
    sha256_hex(bytes)
}

fn nearest_rank(values: &[usize], quantile: f64) -> Option<usize> {
    if values.is_empty() {
        return None;
    }
    let mut ordered = values.to_vec();
    ordered.sort_unstable();
    let rank = ((quantile * ordered.len() as f64).ceil() as usize).max(1);
    Some(ordered[rank - 1])
}

fn nearest_rank_float(values: &[f64], quantile: f64) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    let mut ordered = values.to_vec();
    ordered.sort_by(|left, right| left.partial_cmp(right).unwrap_or(Ordering::Equal));
    let rank = ((quantile * ordered.len() as f64).ceil() as usize).max(1);
    Some(ordered[rank - 1])
}

fn range_pair(length: usize, delta: i32) -> (usize, usize, usize) {
    if delta >= 0 {
        let offset = delta as usize;
        (0, offset, length - offset)
    } else {
        let offset = (-delta) as usize;
        (offset, 0, length - offset)
    }
}

fn candidate_cmp(left: &(u64, u64, i32, i32), right: &(u64, u64, i32, i32)) -> Ordering {
    let left_scaled = left.0 as u128 * right.1 as u128;
    let right_scaled = right.0 as u128 * left.1 as u128;
    left_scaled.cmp(&right_scaled).then_with(|| {
        (
            left.2.abs() + left.3.abs(),
            left.3.abs(),
            left.2.abs(),
            left.3,
            left.2,
        )
            .cmp(&(
                right.2.abs() + right.3.abs(),
                right.3.abs(),
                right.2.abs(),
                right.3,
                right.2,
            ))
    })
}

fn estimate_translation(
    previous: &[u8],
    current: &[u8],
    width: usize,
    height: usize,
    config: &TranslationConfig,
) -> Result<TranslationEstimate, String> {
    let stride = config.full_resolution_scale;
    if stride == 0 {
        return Err("Translation scale must be positive.".to_string());
    }
    let offset = stride / 2;
    let low_width = (width - offset + stride - 1) / stride;
    let low_height = (height - offset + stride - 1) / stride;
    if (low_width, low_height) != (config.downsample_width, config.downsample_height) {
        return Err(format!(
            "Deterministic downsample shape {low_width}x{low_height} does not match {}x{}.",
            config.downsample_width, config.downsample_height
        ));
    }
    let mut candidates = Vec::new();
    for dy in config.search_min..=config.search_max {
        let (previous_y, current_y, rows) = range_pair(low_height, dy);
        for dx in config.search_min..=config.search_max {
            let (previous_x, current_x, columns) = range_pair(low_width, dx);
            let mut sum = 0_u64;
            for row in 0..rows {
                let py = offset + (previous_y + row) * stride;
                let cy = offset + (current_y + row) * stride;
                for column in 0..columns {
                    let px = offset + (previous_x + column) * stride;
                    let cx = offset + (current_x + column) * stride;
                    sum += previous[py * width + px].abs_diff(current[cy * width + cx]) as u64;
                }
            }
            candidates.push((sum, (rows * columns) as u64, dx, dy));
        }
    }
    candidates.sort_by(candidate_cmp);
    let best = candidates[0];
    let second = candidates[1];
    let margin = second.0 as f64 / second.1 as f64 - best.0 as f64 / best.1 as f64;
    Ok(TranslationEstimate {
        dx_low: best.2,
        dy_low: best.3,
        dx_full: best.2 * stride as i32,
        dy_full: best.3 * stride as i32,
        score_sum: best.0,
        score_count: best.1,
        second_score_sum: second.0,
        second_score_count: second.1,
        confidence_status: if margin >= config.minimum_mad_margin_for_high_confidence {
            "collected".to_string()
        } else {
            "low_confidence".to_string()
        },
    })
}

fn compensated_difference(
    previous: &[u8],
    current: &[u8],
    width: usize,
    height: usize,
    estimate: &TranslationEstimate,
) -> (Vec<u16>, usize) {
    let mut difference = vec![255_u16; width * height];
    let (previous_y, current_y, rows) = range_pair(height, estimate.dy_full);
    let (previous_x, current_x, columns) = range_pair(width, estimate.dx_full);
    for row in 0..rows {
        for column in 0..columns {
            let previous_index = (previous_y + row) * width + previous_x + column;
            let current_index = (current_y + row) * width + current_x + column;
            difference[current_index] =
                previous[previous_index].abs_diff(current[current_index]) as u16;
        }
    }
    (difference, width * height - rows * columns)
}

fn tile_counts(
    changed: &[bool],
    width: usize,
    height: usize,
    tile_size: usize,
) -> (Vec<u64>, Vec<u64>, usize, usize) {
    let rows = height.div_ceil(tile_size);
    let columns = width.div_ceil(tile_size);
    let mut counts = vec![0_u64; rows * columns];
    let mut areas = vec![0_u64; rows * columns];
    for tile_y in 0..rows {
        let y0 = tile_y * tile_size;
        let y1 = (y0 + tile_size).min(height);
        for tile_x in 0..columns {
            let x0 = tile_x * tile_size;
            let x1 = (x0 + tile_size).min(width);
            let tile_index = tile_y * columns + tile_x;
            areas[tile_index] = ((y1 - y0) * (x1 - x0)) as u64;
            let mut count = 0_u64;
            for y in y0..y1 {
                for x in x0..x1 {
                    count += changed[y * width + x] as u64;
                }
            }
            counts[tile_index] = count;
        }
    }
    (counts, areas, rows, columns)
}

fn activate(counts: &[u64], areas: &[u64], rule: &ActivationRule) -> Vec<bool> {
    counts
        .iter()
        .zip(areas)
        .map(|(count, area)| match rule.minimum_changed_denominator {
            None => *count >= rule.minimum_changed_numerator as u64,
            Some(denominator) => {
                *count * denominator as u64 >= *area * rule.minimum_changed_numerator as u64
            }
        })
        .collect()
}

fn dilate(active: &[bool], rows: usize, columns: usize, radius: usize) -> Vec<bool> {
    if radius == 0 {
        return active.to_vec();
    }
    let mut result = vec![false; active.len()];
    for row in 0..rows {
        for column in 0..columns {
            if !active[row * columns + column] {
                continue;
            }
            let y0 = row.saturating_sub(radius);
            let y1 = (row + radius + 1).min(rows);
            let x0 = column.saturating_sub(radius);
            let x1 = (column + radius + 1).min(columns);
            for y in y0..y1 {
                for x in x0..x1 {
                    result[y * columns + x] = true;
                }
            }
        }
    }
    result
}

fn tile_key(source: &str, threshold: u8, tile_size: usize, rule: &str, halo: usize) -> String {
    format!("{source}|{threshold}|{tile_size}|{rule}|{halo}")
}

fn run_lengths(states: &[Vec<bool>], target: bool) -> Vec<usize> {
    if states.is_empty() {
        return Vec::new();
    }
    let tiles = states[0].len();
    let mut runs = Vec::new();
    for tile in 0..tiles {
        let mut current = 0_usize;
        for state in states {
            if state[tile] == target {
                current += 1;
            } else if current > 0 {
                runs.push(current);
                current = 0;
            }
        }
        if current > 0 {
            runs.push(current);
        }
    }
    runs
}

fn temporal_summary(
    source: &str,
    threshold: u8,
    tile_size: usize,
    rule: &str,
    halo: usize,
    states: &[Vec<bool>],
) -> TemporalPersistence {
    let active_runs = run_lengths(states, true);
    let frozen_runs = run_lengths(states, false);
    let active_total: usize = active_runs.iter().sum();
    let persistent_total: usize = active_runs.iter().filter(|value| **value >= 2).sum();
    let mut active_to_frozen = 0_u64;
    let mut frozen_to_active = 0_u64;
    for pair in states.windows(2) {
        for (previous, current) in pair[0].iter().zip(&pair[1]) {
            active_to_frozen += (*previous && !*current) as u64;
            frozen_to_active += (!*previous && *current) as u64;
        }
    }
    TemporalPersistence {
        source: source.to_string(),
        threshold,
        tile_size,
        activation_rule: rule.to_string(),
        halo_tiles: halo,
        active_run_count: active_runs.len(),
        frozen_run_count: frozen_runs.len(),
        active_run_median: nearest_rank(&active_runs, 0.5),
        active_run_p95: nearest_rank(&active_runs, 0.95),
        frozen_run_median: nearest_rank(&frozen_runs, 0.5),
        frozen_run_p95: nearest_rank(&frozen_runs, 0.95),
        active_to_frozen_transitions: active_to_frozen,
        frozen_to_active_transitions: frozen_to_active,
        one_frame_only_activity_ratio: if active_runs.is_empty() {
            0.0
        } else {
            active_runs.iter().filter(|value| **value == 1).count() as f64
                / active_runs.len() as f64
        },
        persistent_activity_ratio: if active_total == 0 {
            0.0
        } else {
            persistent_total as f64 / active_total as f64
        },
    }
}

fn option_token(value: Option<usize>) -> String {
    value.map_or_else(|| "None".to_string(), |item| item.to_string())
}

fn gray_digest(summary: &GraySummary) -> String {
    let mut tokens = vec![
        format!("format={}", summary.pixel_format),
        format!(
            "shape={}x{}x{}",
            summary.frames, summary.height, summary.width
        ),
    ];
    for item in &summary.pixel_surface {
        tokens.push(format!(
            "pixel={},{},{},{}",
            item.source, item.threshold, item.changed_pixels, item.total_pixels
        ));
    }
    for item in &summary.tile_surface {
        tokens.push(format!(
            "tile={},{},{},{},{},{},{},{},{},{},{},{}",
            item.source,
            item.threshold,
            item.tile_size,
            item.activation_rule,
            item.halo_tiles,
            item.total_tiles,
            item.active_tiles,
            item.partial_edge_tiles,
            item.additional_closure_tiles,
            item.pairs_at_or_above_75_percent,
            item.pairs_at_or_above_90_percent,
            item.full_pressure_pairs
        ));
    }
    for item in &summary.temporal_persistence {
        tokens.push(format!(
            "temporal={},{},{},{},{},{},{},{},{},{},{},{},{}",
            item.source,
            item.threshold,
            item.tile_size,
            item.activation_rule,
            item.halo_tiles,
            item.active_run_count,
            item.frozen_run_count,
            option_token(item.active_run_median),
            option_token(item.active_run_p95),
            option_token(item.frozen_run_median),
            option_token(item.frozen_run_p95),
            item.active_to_frozen_transitions,
            item.frozen_to_active_transitions
        ));
    }
    for item in &summary.translations {
        tokens.push(format!(
            "translation={},{},{},{},{},{},{},{},{}",
            item.pair_index,
            item.dx_low,
            item.dy_low,
            item.dx_full,
            item.dy_full,
            item.score_sum,
            item.score_count,
            item.exposed_border_pixels,
            item.confidence_status
        ));
    }
    sha256_hex(tokens.join("\n").as_bytes())
}

fn rgb_digest(summary: &RgbSummary) -> String {
    let mut tokens = vec![
        format!("format={}", summary.pixel_format),
        format!(
            "shape={}x{}x{}",
            summary.frames, summary.height, summary.width
        ),
    ];
    for item in &summary.pixel_surface {
        tokens.push(format!(
            "pixel={},{},{},{}",
            item.source, item.threshold, item.changed_pixels, item.total_pixels
        ));
    }
    sha256_hex(tokens.join("\n").as_bytes())
}

pub fn analyze_gray(
    sequence: &[u8],
    width: usize,
    height: usize,
    frames: usize,
    config: &LocalityConfig,
) -> Result<GraySummary, String> {
    let pixels = width
        .checked_mul(height)
        .ok_or_else(|| "Input dimensions overflow.".to_string())?;
    if frames < 2 || sequence.len() != pixels * frames {
        return Err("gray8 input length does not match the declared shape.".to_string());
    }
    let pairs = frames - 1;
    let total_pixels = (pairs * pixels) as u64;
    let mut pixel_counts: BTreeMap<(String, u8), u64> = BTreeMap::new();
    let mut tile_accumulators: BTreeMap<String, TileAccumulator> = BTreeMap::new();
    let mut temporal_states: BTreeMap<String, Vec<Vec<bool>>> = BTreeMap::new();
    let mut translations = Vec::with_capacity(pairs);
    let mut raw_global_delta = Vec::with_capacity(pairs);
    let mut compensated_global_delta = Vec::with_capacity(pairs);
    let mut translation_estimation_seconds = 0.0;
    let mut compensation_apply_seconds = 0.0;

    for pair_index in 0..pairs {
        let previous = &sequence[pair_index * pixels..(pair_index + 1) * pixels];
        let current = &sequence[(pair_index + 1) * pixels..(pair_index + 2) * pixels];
        let raw: Vec<u16> = previous
            .iter()
            .zip(current)
            .map(|(left, right)| left.abs_diff(*right) as u16)
            .collect();
        raw_global_delta
            .push(raw.iter().map(|value| *value as u64).sum::<u64>() as f64 / pixels as f64);
        let started = Instant::now();
        let estimate = estimate_translation(previous, current, width, height, &config.translation)?;
        translation_estimation_seconds += started.elapsed().as_secs_f64();
        let started = Instant::now();
        let (compensated, exposed) =
            compensated_difference(previous, current, width, height, &estimate);
        compensation_apply_seconds += started.elapsed().as_secs_f64();
        compensated_global_delta.push(
            compensated.iter().map(|value| *value as u64).sum::<u64>() as f64 / pixels as f64,
        );
        translations.push(TranslationRecord {
            pair_index,
            dx_low: estimate.dx_low,
            dy_low: estimate.dy_low,
            dx_full: estimate.dx_full,
            dy_full: estimate.dy_full,
            score_sum: estimate.score_sum,
            score_count: estimate.score_count,
            second_score_sum: estimate.second_score_sum,
            second_score_count: estimate.second_score_count,
            confidence_status: estimate.confidence_status.clone(),
            exposed_border_pixels: exposed as u64,
        });

        for (source, difference) in [("raw", &raw), ("translation_compensated", &compensated)] {
            for threshold in &config.gray_thresholds {
                let changed: Vec<bool> = difference
                    .iter()
                    .map(|value| *value > *threshold as u16)
                    .collect();
                *pixel_counts
                    .entry((source.to_string(), *threshold))
                    .or_default() += changed.iter().filter(|value| **value).count() as u64;
                for tile_size in &config.tile_sizes {
                    let (counts, areas, rows, columns) =
                        tile_counts(&changed, width, height, *tile_size);
                    let partial = areas
                        .iter()
                        .filter(|area| **area != (*tile_size * *tile_size) as u64)
                        .count() as u64;
                    let tile_total = counts.len() as u64;
                    for rule in &config.activation_rules {
                        let base_active = activate(&counts, &areas, rule);
                        let base_count = base_active.iter().filter(|value| **value).count() as u64;
                        for halo in &config.halos {
                            let active = dilate(&base_active, rows, columns, *halo);
                            let active_count = active.iter().filter(|value| **value).count() as u64;
                            let key = tile_key(source, *threshold, *tile_size, &rule.id, *halo);
                            let accumulator = tile_accumulators.entry(key.clone()).or_default();
                            accumulator.total_tiles += tile_total;
                            accumulator.active_tiles += active_count;
                            accumulator.partial_edge_tiles += partial;
                            accumulator.additional_closure_tiles += active_count - base_count;
                            accumulator.pairs_at_or_above_75_percent +=
                                (active_count * 4 >= tile_total * 3) as u64;
                            accumulator.pairs_at_or_above_90_percent +=
                                (active_count * 10 >= tile_total * 9) as u64;
                            accumulator.full_pressure_pairs += (active_count == tile_total) as u64;
                            temporal_states.entry(key).or_default().push(active);
                        }
                    }
                }
            }
        }
    }

    let mut pixel_surface = Vec::new();
    for source in ["raw", "translation_compensated"] {
        for threshold in &config.gray_thresholds {
            let changed = pixel_counts[&(source.to_string(), *threshold)];
            pixel_surface.push(PixelSurface {
                source: source.to_string(),
                threshold: *threshold,
                changed_pixels: changed,
                total_pixels,
                changed_pixel_ratio: changed as f64 / total_pixels as f64,
            });
        }
    }

    let mut tile_surface = Vec::new();
    let mut temporal_persistence = Vec::new();
    for source in ["raw", "translation_compensated"] {
        for threshold in &config.gray_thresholds {
            for tile_size in &config.tile_sizes {
                for rule in &config.activation_rules {
                    for halo in &config.halos {
                        let key = tile_key(source, *threshold, *tile_size, &rule.id, *halo);
                        let accumulator = tile_accumulators
                            .get(&key)
                            .ok_or_else(|| format!("Missing tile accumulator: {key}"))?;
                        let base_active =
                            accumulator.active_tiles - accumulator.additional_closure_tiles;
                        tile_surface.push(TileSurface {
                            source: source.to_string(),
                            threshold: *threshold,
                            tile_size: *tile_size,
                            activation_rule: rule.id.clone(),
                            halo_tiles: *halo,
                            total_tiles: accumulator.total_tiles,
                            active_tiles: accumulator.active_tiles,
                            partial_edge_tiles: accumulator.partial_edge_tiles,
                            additional_closure_tiles: accumulator.additional_closure_tiles,
                            pairs_at_or_above_75_percent: accumulator.pairs_at_or_above_75_percent,
                            pairs_at_or_above_90_percent: accumulator.pairs_at_or_above_90_percent,
                            full_pressure_pairs: accumulator.full_pressure_pairs,
                            active_tile_ratio: accumulator.active_tiles as f64
                                / accumulator.total_tiles as f64,
                            frozen_candidate_ratio: 1.0
                                - accumulator.active_tiles as f64 / accumulator.total_tiles as f64,
                            halo_inflation_ratio: if base_active == 0 {
                                if accumulator.active_tiles == 0 {
                                    Some(1.0)
                                } else {
                                    None
                                }
                            } else {
                                Some(accumulator.active_tiles as f64 / base_active as f64)
                            },
                        });
                        temporal_persistence.push(temporal_summary(
                            source,
                            *threshold,
                            *tile_size,
                            &rule.id,
                            *halo,
                            &temporal_states[&key],
                        ));
                    }
                }
            }
        }
    }
    let exposed_total: u64 = translations
        .iter()
        .map(|item| item.exposed_border_pixels)
        .sum();
    let low_confidence_pairs = translations
        .iter()
        .filter(|item| item.confidence_status != "collected")
        .count();
    let mut summary = GraySummary {
        schema_version: "0.1.0".to_string(),
        implementation: "rust_native_compare".to_string(),
        pixel_format: "gray8".to_string(),
        frames,
        frame_pairs: pairs,
        width,
        height,
        pixel_surface,
        global_delta: GlobalDelta {
            raw_median: nearest_rank_float(&raw_global_delta, 0.5),
            raw_p95: nearest_rank_float(&raw_global_delta, 0.95),
            translation_compensated_median: nearest_rank_float(&compensated_global_delta, 0.5),
            translation_compensated_p95: nearest_rank_float(&compensated_global_delta, 0.95),
        },
        tile_surface,
        temporal_persistence,
        translations,
        translation_cost: TranslationCost {
            estimation_seconds: translation_estimation_seconds,
            apply_seconds: compensation_apply_seconds,
            exposed_border_pixels: exposed_total,
            exposed_border_ratio: exposed_total as f64 / total_pixels as f64,
            low_confidence_pairs,
        },
        summary_digest: String::new(),
    };
    summary.summary_digest = gray_digest(&summary);
    Ok(summary)
}

pub fn analyze_rgb(
    sequence: &[u8],
    width: usize,
    height: usize,
    frames: usize,
    config: &LocalityConfig,
) -> Result<RgbSummary, String> {
    let pixels = width
        .checked_mul(height)
        .ok_or_else(|| "Input dimensions overflow.".to_string())?;
    if frames < 2 || sequence.len() != pixels * frames * 3 {
        return Err("rgb24 input length does not match the declared shape.".to_string());
    }
    let pairs = frames - 1;
    let total_pixels = (pairs * pixels) as u64;
    let mut counts = vec![0_u64; config.rgb_thresholds.len()];
    for pair in 0..pairs {
        let previous = &sequence[pair * pixels * 3..(pair + 1) * pixels * 3];
        let current = &sequence[(pair + 1) * pixels * 3..(pair + 2) * pixels * 3];
        for pixel in 0..pixels {
            let index = pixel * 3;
            let delta = previous[index]
                .abs_diff(current[index])
                .max(previous[index + 1].abs_diff(current[index + 1]))
                .max(previous[index + 2].abs_diff(current[index + 2]));
            for (threshold_index, threshold) in config.rgb_thresholds.iter().enumerate() {
                counts[threshold_index] += (delta > *threshold) as u64;
            }
        }
    }
    let pixel_surface = config
        .rgb_thresholds
        .iter()
        .zip(counts)
        .map(|(threshold, changed)| PixelSurface {
            source: "rgb_raw".to_string(),
            threshold: *threshold,
            changed_pixels: changed,
            total_pixels,
            changed_pixel_ratio: changed as f64 / total_pixels as f64,
        })
        .collect();
    let mut summary = RgbSummary {
        schema_version: "0.1.0".to_string(),
        implementation: "rust_native_compare".to_string(),
        pixel_format: "rgb24".to_string(),
        frames,
        frame_pairs: pairs,
        width,
        height,
        pixel_surface,
        summary_digest: String::new(),
    };
    summary.summary_digest = rgb_digest(&summary);
    Ok(summary)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(width: usize, height: usize) -> LocalityConfig {
        LocalityConfig {
            gray_thresholds: vec![0, 2],
            rgb_thresholds: vec![0, 2],
            tile_sizes: vec![8],
            activation_rules: vec![
                ActivationRule {
                    id: "any".to_string(),
                    minimum_changed_numerator: 1,
                    minimum_changed_denominator: None,
                },
                ActivationRule {
                    id: "10_percent".to_string(),
                    minimum_changed_numerator: 10,
                    minimum_changed_denominator: Some(100),
                },
            ],
            halos: vec![0, 1],
            translation: TranslationConfig {
                downsample_width: width / 8,
                downsample_height: height / 8,
                search_min: -1,
                search_max: 1,
                full_resolution_scale: 8,
                minimum_mad_margin_for_high_confidence: 0.25,
            },
        }
    }

    #[test]
    fn exact_sequence_is_deterministic_and_frozen() {
        let (width, height) = (19, 18);
        let frame: Vec<u8> = (0..width * height).map(|value| value as u8).collect();
        let mut sequence = frame.clone();
        sequence.extend(&frame);
        let one = analyze_gray(&sequence, width, height, 2, &config(width, height)).unwrap();
        let two = analyze_gray(&sequence, width, height, 2, &config(width, height)).unwrap();
        assert_eq!(one.summary_digest, two.summary_digest);
        assert_eq!(one.pixel_surface[0].changed_pixels, 0);
    }

    #[test]
    fn partial_edge_tiles_use_real_area() {
        let (width, height) = (19, 18);
        let changed = vec![true; width * height];
        let (counts, areas, rows, columns) = tile_counts(&changed, width, height, 8);
        assert_eq!((rows, columns), (3, 3));
        assert_eq!(areas.iter().filter(|area| **area != 64).count(), 5);
        assert_eq!(*counts.last().unwrap(), 6);
    }

    #[test]
    fn translation_marks_exposed_border() {
        let (width, height) = (832, 480);
        let previous: Vec<u8> = (0..width * height)
            .map(|index| (((index % width) * 3 + (index / width) * 5) % 251) as u8)
            .collect();
        let mut current = vec![0_u8; width * height];
        for y in 0..height {
            for x in 8..width {
                current[y * width + x] = previous[y * width + x - 8];
            }
        }
        let estimate = estimate_translation(
            &previous,
            &current,
            width,
            height,
            &config(width, height).translation,
        )
        .unwrap();
        assert_eq!((estimate.dx_full, estimate.dy_full), (8, 0));
        let (difference, exposed) =
            compensated_difference(&previous, &current, width, height, &estimate);
        assert_eq!(exposed, 8 * height);
        assert!(difference
            .chunks(width)
            .all(|row| row[..8].iter().all(|value| *value == 255)));
    }

    #[test]
    fn invalid_length_returns_error_without_panic() {
        assert!(analyze_gray(&[0; 10], 19, 18, 2, &config(19, 18)).is_err());
    }
}
