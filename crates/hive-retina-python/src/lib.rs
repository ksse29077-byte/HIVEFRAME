#![doc = "Bounded Python 3.12 shared-buffer adapter for the model-free R3 probe."]

use hive_retina_runtime::{InputProfile, PixelBox, R3CandidateSummary};
use pyo3::buffer::PyBuffer;
use pyo3::exceptions::{PyRuntimeError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyModule};
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

#[pymodule]
fn _hive_retina_boundary(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(run_candidate, module)?)?;
    module.add_function(wrap_pyfunction!(empty_boundary_probe, module)?)?;
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    module.add("pyo3_version", "0.29.0")?;
    module.add("python_abi", "abi3-py312")?;
    Ok(())
}
