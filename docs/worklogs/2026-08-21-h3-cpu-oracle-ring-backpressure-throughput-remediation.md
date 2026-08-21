# H3 CPU Oracle Ring Backpressure Throughput Remediation

## Authorization and base

Issue #127 and Draft PR #128 track the one-time constitutional exception for
`H3_CPU_ORACLE_RING_BACKPRESSURE_THROUGHPUT_REMEDIATION`. The branch starts
from exact Draft PR #126 head
`d1863ec359fb09f42f27f21adc50096e364e6563`; local HEAD, upstream HEAD, remote
PR head, and a clean worktree matched before the branch was created. Existing
PRs were not changed.

The scope was model-free CPU-oracle throughput, RAM-bounded ring capacity,
actual trace replay, a full synthetic production-shape replay, and bounded
CUDA pinned-D2H stress. H3 model load, Generation, Formal CONTROL, SELECTIVE,
partial-Q, Attention omission, executor integration, Rust CachePlan admission,
and product wiring remained prohibited.

## Actual trace facts and measurement limit

The immutable PR #126 trace proves that sequences 1 through 30 were fully
consumed. Sequence 31 completed D2H and entered CPU work, sequence 32 occupied
the second slot, and arriving sequence 33 found no free slot. The actual slot
payload is `(3367, 7168)` BF16, exactly 48,269,312 bytes. The observed minimum
simultaneous demand is therefore three payloads: the two occupied records plus
the rejected arrival.

The source trace does not contain host enqueue, CPU service start/end, or slot
release timestamps. Exact enqueue intervals and actual min/median/p95/max
service or occupancy times cannot be reconstructed and are recorded as
`UNAVAILABLE_IN_SOURCE_TRACE`, not estimated. The 31 completed CUDA transfers
totaled 56.97158420085907 ms, but no per-sample distribution survived. The
only broader producer observation is a 66.20238609996159-second client progress
interval. Treating 30 candidates over that interval yields a conservative
sustained producer upper bound of 0.4531558719756992 records/s; it is not
claimed as exact block timing.

## CPU worker comparison

All workers used the same deterministic BF16 source/current tensors, exact
correction and metric implementation, production payload shape, source-copy
cost, and one Torch intra-op thread. Each configuration processed 18 measured
records.

| Workers | records/s | service min / median / p95 / max (s) | peak RSS (B) | normalized CPU | digest count |
|---:|---:|---|---:|---:|---:|
| 1 | 5.991146 | 0.153067 / 0.165835 / 0.203765 / 0.203765 | 793,362,432 | 8.234% | 1 |
| 2 | 7.242389 | 0.256963 / 0.269106 / 0.302088 / 0.302088 | 883,507,200 | 16.503% | 1 |
| 3 | 9.515405 | 0.281680 / 0.314611 / 0.348009 / 0.348009 | 974,127,104 | 24.229% | 1 |

Every configuration produced metric digest
`349dc9dfd7d41737d8cc42a1a411290fdd9b763aa327fac50a06450b78f053dc`.
One worker is the selected minimum: its sustained rate is 13.22 times the
observed producer bound and exceeds the required 1.10 margin. Two and three
workers improve aggregate throughput but increase per-record latency, RAM,
CPU use, and completion reordering. The selected single worker preserves
logical completion and finalizer order without a keyed reorder buffer.

## Ring and backpressure remediation

The fixed two-slot assumption is replaced by a trace-derived requirement:

```text
measured maximum in flight = 3
safety slots = 1
required ring slots = 4
```

Admission uses current available RAM rather than a GPU-name table:

```text
available_ring_bytes = available_system_ram
                     - 1.5 GiB host reserve
                     - 1,448,079,360-byte non-ring source cache
max_slots = floor(available_ring_bytes / 48,269,312)
```

The measured preflight had 46,973,562,880 bytes available and admitted 909
maximum slots. Only the four required slots are allocated: 193,077,248 pinned
bytes. The historical-peak ledger projects 64,450,682,880 bytes total against
66,145,665,024 physical bytes, leaving 1,694,982,144 bytes, including the full
1.5 GiB reserve with 84,369,408 bytes remaining.

Slots now follow only
`FREE -> D2H_IN_FLIGHT -> CPU_READY -> PROCESSING -> FINALIZED -> FREE`.
The producer scans the bounded ring for a real FREE slot rather than failing
because only the next circular index is occupied. It still never waits,
sleeps, reads CUDA scalars, or synchronizes in the hot path. No free slot is a
clear fail-closed error; no record is dropped or replaced by fallback. CUDA
events are retained across normal slot reuse and cleaned only at final
shutdown. Future receipts now record enqueue interval, CPU service, slot
occupancy, and ring high-water summaries.

## Replays

The unchanged actual 30/31/32/33 fixture reproduces sequence 33 rejection with
two slots. Four slots accept all three records, reach high-water three, and
preserve 31/32/33 completion order.

The full replay uses all 30 block-zero-region candidates for 20 steps, the
actual production payload shape and bytes, age-one source progression, and
trace-backed bursts of three. It completed 600 enqueues and 480 eligible
evidence calculations in 83.26922330004163 seconds. The source cache was
exactly 1,448,079,360 bytes. Overflow, dropped, overwritten, duplicate,
missing, stale, and lineage-mismatch counts were all zero; final backlog was
zero and ring high-water was three. The logical result digest is
`4ccfbba64e1409cba098c76643f46b3b89566e807d385045e332b225cf134efe`.

## Bounded CUDA stress

The final RTX 3060 stress used four real page-locked production slots and 12
nonblocking production-size D2H transfers, totaling 579,231,744 bytes. CUDA
timing min/median/p95/max was 1.834752/1.835344/1.898496/1.898496 ms. The
timing-disabled completion Event had zero `elapsed_time` calls; completion was
polled with 54 queries and hot-path forced sync remained zero. BF16 sample bits
matched, CPU metric maximum absolute error was 0, and allocated/reserved CUDA
memory returned from 0/0 to 0/0 bytes.

The first model-free preflight attempt completed the CPU replay and one
four-transfer CUDA batch, then stopped because the validator indexed a 2-D
BF16 view as if it were flat. No H3 or workflow was involved. The validator
was corrected to flatten only its sampled bit view; ring, metrics, thresholds,
and schedule were unchanged. Cumulative bounded stress was therefore 16
transfers and 772,308,992 D2H bytes. The successful receipt records the final
12-transfer Gate run.

The full CONTROL projection remains 28,961,587,200 D2H bytes, below the 32 GiB
limit. Oracle H2D bytes, Rust calls/tensor bytes, H3 load, Generation, CONTROL
submission, SELECTIVE, partial-Q, and Attention omission were all zero.

## Verification and decision

- focused throughput/ring/control tests: 25 passed
- H3-prefixed adjacent tests: 66 passed, 4 existing environment skips
- production payload replay: 600/600 enqueues and 480/480 evidence records
- final bounded CUDA stress: all integrity, timing, sync, and cleanup Gates pass
- final local JSON receipt SHA-256:
  `445172562af8cfe2d2edd5e132041459cd589723b3631a8a28b3435f7a3aa912`
- internal canonical receipt digest:
  `3c57f86f49426c5e45a8efad2c92bb398efa1563688d696e4f765486e4decad0`

Final decision:

```text
H3_CPU_ORACLE_RING_BACKPRESSURE_THROUGHPUT_REMEDIATION_READY_FOR_CONTROL
```

This admits only the remediated CPU-oracle ring for a separately authorized
Formal CONTROL. It does not establish holdout quality, false-safe, planned Q,
output integrity, Attention omission, or product readiness. No CONTROL was
started and the one-time exception ends with this decision.

