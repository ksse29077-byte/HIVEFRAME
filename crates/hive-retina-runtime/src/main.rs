use hive_retina_runtime::{
    benchmark_case, benchmark_suite, semantic_hash, InputProfile, Topology, TOPOLOGIES,
};
use std::env;
use std::fs;
use std::path::PathBuf;

fn value_after(args: &[String], name: &str) -> Result<String, String> {
    let index = args
        .iter()
        .position(|item| item == name)
        .ok_or_else(|| format!("Missing required option: {name}"))?;
    args.get(index + 1)
        .cloned()
        .ok_or_else(|| format!("Missing value after {name}"))
}

fn optional_value(args: &[String], name: &str, default: &str) -> Result<String, String> {
    if args.iter().any(|item| item == name) {
        value_after(args, name)
    } else {
        Ok(default.to_string())
    }
}

fn parse_list(value: &str) -> Vec<String> {
    value
        .split(',')
        .map(str::trim)
        .filter(|item| !item.is_empty())
        .map(str::to_string)
        .collect()
}

fn print_help() {
    println!(
        "Model-free HIVEFRAME Rust I/O admission probe.

Usage:
  hive-retina-runtime semantic --profile PROFILE --topology TOPOLOGY [--seed N]
  hive-retina-runtime suite --profiles LIST --topologies LIST \\
    --warmups N --repetitions N --output FILE [--seed N]

Profiles: low, medium, high, extended
Topologies: {}",
        TOPOLOGIES.join(", ")
    );
}

fn semantic_command(args: &[String]) -> Result<(), String> {
    let profile_name = value_after(args, "--profile")?;
    let topology_name = value_after(args, "--topology")?;
    let seed = optional_value(args, "--seed", "101")?
        .parse::<u64>()
        .map_err(|error| format!("Invalid seed: {error}"))?;
    let profile = InputProfile::named(&profile_name, seed)?;
    let topology = Topology::parse(&topology_name)?;
    let case = benchmark_case(&profile, topology, 0, 1)?;
    let output = serde_json::json!({
        "semantic_hash": semantic_hash(&case.semantic_result)?,
        "semantic_result": case.semantic_result,
    });
    println!(
        "{}",
        serde_json::to_string_pretty(&output)
            .map_err(|error| format!("Cannot serialize semantic output: {error}"))?
    );
    Ok(())
}

fn suite_command(args: &[String]) -> Result<(), String> {
    let profile_names = parse_list(&optional_value(args, "--profiles", "low,medium,high")?);
    let topology_names = parse_list(&optional_value(
        args,
        "--topologies",
        &TOPOLOGIES.join(","),
    )?);
    let warmups = optional_value(args, "--warmups", "5")?
        .parse::<usize>()
        .map_err(|error| format!("Invalid warm-up count: {error}"))?;
    let repetitions = optional_value(args, "--repetitions", "30")?
        .parse::<usize>()
        .map_err(|error| format!("Invalid repetition count: {error}"))?;
    let seed = optional_value(args, "--seed", "101")?
        .parse::<u64>()
        .map_err(|error| format!("Invalid seed: {error}"))?;
    let output = PathBuf::from(value_after(args, "--output")?);
    if output.exists() {
        return Err(format!(
            "Output already exists; overwrite is forbidden: {}",
            output.display()
        ));
    }
    if let Some(parent) = output.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("Cannot create output parent: {error}"))?;
    }
    let report = benchmark_suite(&profile_names, &topology_names, seed, warmups, repetitions)?;
    let encoded = serde_json::to_string_pretty(&report)
        .map_err(|error| format!("Cannot serialize benchmark report: {error}"))?;
    fs::write(&output, format!("{encoded}\n"))
        .map_err(|error| format!("Cannot write {}: {error}", output.display()))?;
    println!(
        "{}",
        serde_json::to_string_pretty(&serde_json::json!({
            "status": "succeeded",
            "kind": report.kind,
            "implementation": report.implementation,
            "cases": report.cases.len(),
            "model_loaded": false,
            "cuda_used": false,
            "output": output.file_name().and_then(|name| name.to_str()),
        }))
        .map_err(|error| format!("Cannot serialize status: {error}"))?
    );
    Ok(())
}

fn run() -> Result<(), String> {
    let args = env::args().skip(1).collect::<Vec<_>>();
    let Some(command) = args.first().map(String::as_str) else {
        print_help();
        return Ok(());
    };
    match command {
        "semantic" => semantic_command(&args[1..]),
        "suite" => suite_command(&args[1..]),
        "--help" | "-h" | "help" => {
            print_help();
            Ok(())
        }
        _ => Err(format!("Unknown command: {command}")),
    }
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}
