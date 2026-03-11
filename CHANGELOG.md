# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project uses Semantic Versioning.

## [Unreleased]

No unreleased changes yet.

## [1.0.5] - 2026-03-12

### Fixed

- Fixed `--version` flag silently breaking due to serve-prepend fallback in `parse_args`.
- Fixed `run_cmd_result` not catching `OSError`/`FileNotFoundError` — now returns a failed `CmdResult` instead of crashing on missing executables.
- Fixed redundant `sys.stdout.isatty()` check at `clear_screen` call site; guard is now canonical inside `clear_screen()` only.
- Fixed `ensure_ascii=True` in HTTP server `/health`, `/snapshot`, `/ready` endpoints — non-ASCII model names now serialize correctly.
- Added per-tick `try/except` in the `serve` loop so transient errors log to stderr and the monitor continues instead of crashing.
- Updated stale file header comment to reflect current multi-runtime usage and correct filename.

## [1.0.4] - 2026-03-11

### Changed

- Added the official `CHANGELOG.md` file to the repository.
- Linked the changelog from `README.md`.
- Aligned the documented release history with the published tags and releases.

## [1.0.3] - 2026-03-11

### Changed

- Follow-up patch release for changelog and release-history cleanup.
- Published release metadata for the changelog update line.

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
