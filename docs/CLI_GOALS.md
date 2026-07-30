# CLI Goals

The CLI is a stable control-plane contract. Commands below are targets; the scaffold does not yet claim backend execution.

## Baseline generation

```bash
hiveframe baseline run --suite canonical-v0 --backend wan21
```

Required behavior:

- refuse unadmitted model/checkpoint records;
- resolve a pinned configuration;
- run deterministic seeds;
- emit one receipt per sample and a suite summary;
- include VAE and failed-run time.

## Compile scene intent

```bash
hiveframe director compile scene.yaml --out scene.contract.json
```

Required behavior:

- validate relationships and references;
- compile numeric geometry, constraints, ownership, and write permissions;
- emit a schema-versioned deterministic contract.

## Simulate patch planning

```bash
hiveframe patch simulate --contract scene.contract.json --grid 4x4
```

Required behavior:

- display patches, object intersections, dependencies, and affected closure;
- estimate work and boundary bytes without model execution;
- reject grids below the configured minimum work size.

## Audit boundaries

```bash
hiveframe boundary audit output.latent --report reports/boundary.json
```

Required behavior:

- measure seams by edge, frame, and timestep;
- distinguish geometric, semantic, style, and temporal disagreement;
- recommend accept, neighbor retry, or central escalation.

## Generate with sparse runtime

```bash
hiveframe generate \
  --backend wan21 \
  --contract scene.contract.json \
  --enable-temporal-cache \
  --enable-boundary-bus \
  --receipt reports/run_001.json
```

Required behavior:

- log cache decisions, transferred bytes, reconciliation rounds, and promotions;
- enforce write permissions;
- fail explicitly when safe execution is unavailable.

## Compare with baseline

```bash
hiveframe benchmark compare \
  reports/baseline.json \
  reports/run_001.json
```

Required behavior:

- reject incompatible configurations;
- report speed, resources, sparse behavior, and quality separately;
- identify missing metrics and false-success conditions;
- produce machine-readable JSON plus a human-readable summary.
