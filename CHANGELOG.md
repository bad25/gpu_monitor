# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project uses Semantic Versioning.

## [Unreleased]

No unreleased changes yet.

## [1.0.2] - 2026-03-11

### Changed

- Renamed default generated files to runtime-neutral names:
  - `gpu_monitor_log.csv`
  - `gpu_monitor_snapshot.json`
  - `gpu_monitor.prom`
- Updated Python defaults, `.gitignore`, documentation, and legacy shell scripts to use the new filenames.

## [1.0.1] - 2026-03-11

### Added

- Multi-runtime support in `gpu_monitor.py` for:
  - `ollama`
  - `vllm`
  - `sglang`
  - `localai`
  - `docker-model-runner`
  - `generic`
- Runtime-aware container discovery and model introspection adapters.
- Runtime-specific probes for `vllm` and `sglang`:
  - `GET /health`
  - `GET /metrics`
- Runtime-aware Prometheus metrics:
  - `gpu_monitor_runtime_health_up`
  - `gpu_monitor_runtime_metrics_up`
  - `gpu_monitor_runtime_metrics_samples`

### Changed

- Updated `README.md`, `gpu_monitor.md`, and bilingual quick-start guides for multi-runtime usage.
- Documented runtime adapters for `ollama`, `vllm`, `sglang`, `localai`, `docker-model-runner`, and `generic`.
- Added release-aligned documentation for runtime-specific health and metrics behavior.
- JSON, CSV, dashboard, and Prometheus outputs now include runtime context.

## [1.0.0] - 2026-03-11

### Added

- Initial public release of GPU Monitor.
- Python monitor with GPU, container, model, and OOM visibility.
- CSV, JSON, and Prometheus outputs.
- Embedded HTTP endpoints: `/metrics`, `/health`, `/ready`, and `/snapshot`.

### Changed

- Added initial repository documentation and `.gitignore`.
