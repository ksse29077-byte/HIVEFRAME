# Reports

Generated receipts and benchmark summaries belong here when they are safe and useful to version. Large outputs should use an external artifact store and be referenced by digest.

M0 reports must include baseline configuration, environment fingerprint, per-sample hashes, latency breakdown, GPU and host memory, failure records, and repeatability analysis.

`rust_io_admission/` is a separate model-free orchestration receipt kind. It
cannot satisfy an M0 RunReceipt, backend, quality, or product-speed gate.
