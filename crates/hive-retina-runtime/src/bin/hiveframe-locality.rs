use hive_retina_runtime::locality::{
    analyze_gray, analyze_rgb, bytes_sha256, ActivationRule, LocalityConfig, TranslationConfig,
};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::io::{self, Read};
use std::path::PathBuf;
use std::time::Instant;

fn parse_args() -> Result<BTreeMap<String, String>, String> {
    let mut values = BTreeMap::new();
    let mut arguments = env::args().skip(1);
    while let Some(argument) = arguments.next() {
        if !argument.starts_with("--") {
            return Err(format!("Unexpected positional argument: {argument}"));
        }
        let value = arguments
            .next()
            .ok_or_else(|| format!("Missing value for {argument}"))?;
        values.insert(argument.trim_start_matches("--").to_string(), value);
    }
    Ok(values)
}

fn required<'a>(arguments: &'a BTreeMap<String, String>, key: &str) -> Result<&'a str, String> {
    arguments
        .get(key)
        .map(String::as_str)
        .ok_or_else(|| format!("Missing required --{key}."))
}

fn usize_value(arguments: &BTreeMap<String, String>, key: &str) -> Result<usize, String> {
    required(arguments, key)?
        .parse::<usize>()
        .map_err(|error| format!("Invalid --{key}: {error}"))
}

fn array_u8(value: &Value, pointer: &str) -> Result<Vec<u8>, String> {
    value
        .pointer(pointer)
        .and_then(Value::as_array)
        .ok_or_else(|| format!("Missing config array {pointer}."))?
        .iter()
        .map(|item| {
            item.as_u64()
                .and_then(|number| u8::try_from(number).ok())
                .ok_or_else(|| format!("Invalid u8 value in {pointer}."))
        })
        .collect()
}

fn array_usize(value: &Value, pointer: &str) -> Result<Vec<usize>, String> {
    value
        .pointer(pointer)
        .and_then(Value::as_array)
        .ok_or_else(|| format!("Missing config array {pointer}."))?
        .iter()
        .map(|item| {
            item.as_u64()
                .and_then(|number| usize::try_from(number).ok())
                .ok_or_else(|| format!("Invalid usize value in {pointer}."))
        })
        .collect()
}

fn integer(value: &Value, pointer: &str) -> Result<i64, String> {
    value
        .pointer(pointer)
        .and_then(Value::as_i64)
        .ok_or_else(|| format!("Missing integer config value {pointer}."))
}

fn positive_usize(value: &Value, pointer: &str) -> Result<usize, String> {
    usize::try_from(integer(value, pointer)?)
        .map_err(|_| format!("Config value {pointer} must be non-negative."))
}

fn parse_config(value: &Value) -> Result<LocalityConfig, String> {
    let activation_rules = value
        .pointer("/surface/activation_rules")
        .and_then(Value::as_array)
        .ok_or_else(|| "Missing activation rules.".to_string())?
        .iter()
        .map(|rule| {
            Ok(ActivationRule {
                id: rule
                    .get("id")
                    .and_then(Value::as_str)
                    .ok_or_else(|| "Activation rule id is missing.".to_string())?
                    .to_string(),
                minimum_changed_numerator: rule
                    .get("minimum_changed_numerator")
                    .and_then(Value::as_u64)
                    .and_then(|number| usize::try_from(number).ok())
                    .ok_or_else(|| "Activation numerator is invalid.".to_string())?,
                minimum_changed_denominator: match rule.get("minimum_changed_denominator") {
                    Some(Value::Null) | None => None,
                    Some(item) => Some(
                        item.as_u64()
                            .and_then(|number| usize::try_from(number).ok())
                            .ok_or_else(|| "Activation denominator is invalid.".to_string())?,
                    ),
                },
            })
        })
        .collect::<Result<Vec<_>, String>>()?;

    Ok(LocalityConfig {
        gray_thresholds: array_u8(value, "/surface/gray8_thresholds")?,
        rgb_thresholds: array_u8(value, "/surface/rgb24_thresholds")?,
        tile_sizes: array_usize(value, "/surface/tile_sizes")?,
        activation_rules,
        halos: array_usize(value, "/surface/halo_tiles")?,
        translation: TranslationConfig {
            downsample_width: positive_usize(value, "/translation/downsample_width")?,
            downsample_height: positive_usize(value, "/translation/downsample_height")?,
            search_min: i32::try_from(integer(value, "/translation/search_min")?)
                .map_err(|_| "translation search_min is outside i32.".to_string())?,
            search_max: i32::try_from(integer(value, "/translation/search_max")?)
                .map_err(|_| "translation search_max is outside i32.".to_string())?,
            full_resolution_scale: positive_usize(value, "/translation/full_resolution_scale")?,
            minimum_mad_margin_for_high_confidence: value
                .pointer("/translation/minimum_mad_margin_for_high_confidence")
                .and_then(Value::as_f64)
                .ok_or_else(|| "Missing translation confidence margin.".to_string())?,
        },
    })
}

fn execute() -> Result<(), String> {
    let process_started = Instant::now();
    let arguments = parse_args()?;
    let input_argument = required(&arguments, "input")?;
    let input = PathBuf::from(input_argument);
    let output = PathBuf::from(required(&arguments, "output")?);
    let config_path = PathBuf::from(required(&arguments, "config")?);
    if output.exists() {
        return Err("Output collision: refusing to overwrite an existing artifact.".to_string());
    }
    let clip_id = required(&arguments, "clip-id")?;
    let pixel_format = required(&arguments, "format")?;
    let width = usize_value(&arguments, "width")?;
    let height = usize_value(&arguments, "height")?;
    let frames = usize_value(&arguments, "frames")?;
    let warmups = usize_value(&arguments, "warmups")?;
    let repeats = usize_value(&arguments, "repeats")?;
    if repeats == 0 {
        return Err("--repeats must be at least one.".to_string());
    }

    let input_started = Instant::now();
    let bytes = if input_argument == "-" {
        let mut bytes = Vec::new();
        io::stdin()
            .read_to_end(&mut bytes)
            .map_err(|error| format!("Unable to read stdin: {error}"))?;
        bytes
    } else {
        fs::read(&input).map_err(|error| format!("Unable to read input: {error}"))?
    };
    let input_read_seconds = input_started.elapsed().as_secs_f64();
    let input_sha256 = bytes_sha256(&bytes);
    let expected_sha256 = required(&arguments, "expected-input-sha256")?;
    if input_sha256 != expected_sha256 {
        return Err(format!(
            "Input SHA-256 mismatch: expected {expected_sha256}, got {input_sha256}."
        ));
    }
    let config_bytes =
        fs::read(&config_path).map_err(|error| format!("Unable to read config: {error}"))?;
    let config_json: Value = serde_json::from_slice(&config_bytes)
        .map_err(|error| format!("Unable to parse config: {error}"))?;
    let config = parse_config(&config_json)?;

    let mut last_summary = Value::Null;
    for _ in 0..warmups {
        last_summary = match pixel_format {
            "gray8" => serde_json::to_value(analyze_gray(&bytes, width, height, frames, &config)?)
                .map_err(|error| error.to_string())?,
            "rgb24" => serde_json::to_value(analyze_rgb(&bytes, width, height, frames, &config)?)
                .map_err(|error| error.to_string())?,
            _ => return Err("--format must be gray8 or rgb24.".to_string()),
        };
    }
    let mut measured_seconds = Vec::with_capacity(repeats);
    for _ in 0..repeats {
        let started = Instant::now();
        last_summary = match pixel_format {
            "gray8" => serde_json::to_value(analyze_gray(&bytes, width, height, frames, &config)?)
                .map_err(|error| error.to_string())?,
            "rgb24" => serde_json::to_value(analyze_rgb(&bytes, width, height, frames, &config)?)
                .map_err(|error| error.to_string())?,
            _ => return Err("--format must be gray8 or rgb24.".to_string()),
        };
        measured_seconds.push(started.elapsed().as_secs_f64());
    }
    let output_value = json!({
        "schema_version": "0.1.0",
        "run_kind": "m1_b0_rust_locality_probe",
        "clip_id": clip_id,
        "pixel_format": pixel_format,
        "input": {
            "logical_ref": format!("m1-b0-raw:{clip_id}:{pixel_format}"),
            "sha256": input_sha256,
            "bytes": bytes.len(),
            "width": width,
            "height": height,
            "frames": frames
        },
        "execution": {
            "warmups": warmups,
            "measured_repeats": repeats,
            "input_read_seconds": input_read_seconds,
            "analysis_seconds": measured_seconds,
            "process_internal_wall_seconds": process_started.elapsed().as_secs_f64(),
            "scope": "rust_process_after_cli_entry_excluding_process_spawn"
        },
        "summary": last_summary
    });
    let serialized = serde_json::to_vec_pretty(&output_value)
        .map_err(|error| format!("Unable to serialize output: {error}"))?;
    if let Some(parent) = output.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("Unable to create output parent: {error}"))?;
    }
    fs::write(&output, serialized).map_err(|error| format!("Unable to write output: {error}"))?;
    Ok(())
}

fn main() {
    if let Err(error) = execute() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}
