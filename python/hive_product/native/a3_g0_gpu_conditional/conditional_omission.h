#pragma once

#include <cuda_runtime.h>

#include <cstdint>

struct A3G0NativeRunSummary {
    int graph_launch_count;
    int explicit_hot_path_cpu_sync_count;
    int final_evidence_sync_count;
    int conditional_body_allocation_count;
};

A3G0NativeRunSummary run_a3_g0_conditional_sequence(
    const std::int32_t* input,
    const std::int32_t* flags,
    std::int32_t* outputs,
    std::int32_t* reuse_reference,
    std::int32_t* exact_reference,
    std::int32_t* parity,
    std::int32_t* body_counts,
    std::int32_t* branch_history,
    std::int32_t* launch_index,
    std::int64_t element_count,
    cudaStream_t stream);
