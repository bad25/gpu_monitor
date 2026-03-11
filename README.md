# GPU Monitor

GPU and Ollama container monitor with CSV, JSON, Prometheus, and optional HTTP exporter output.

This repository provides:

- host GPU metrics from `nvidia-smi`
- Ollama container metrics from `docker stats`
- active model visibility from `ollama ps`
- OOM signal detection from `docker logs`
- multi-container Ollama auto-discovery
- multi-GPU support
- `serve` and `snapshot` modes

## Files

- [`gpu_monitor.py`](./gpu_monitor.py): main Python monitor
- [`gpu_monitor.md`](./gpu_monitor.md): full reference
- [`README_GPU_MONITOR_EN.md`](./README_GPU_MONITOR_EN.md): English quick start
- [`README_GPU_MONITOR_ID.md`](./README_GPU_MONITOR_ID.md): Indonesian quick start
- [`gpu_monitor_v1.sh`](./gpu_monitor_v1.sh): older shell version
- [`gpu_monitor_v2.sh`](./gpu_monitor_v2.sh): newer shell version

## Requirements

- Python 3
- `docker`
- `nvidia-smi`
- optional: `ollama`

## Quick Start

Run the continuous monitor:

```bash
python3 gpu_monitor.py serve \
  --output-mode all \
  --metrics-http \
  --interval 2 \
  --container auto
```

Collect one snapshot and exit:

```bash
python3 gpu_monitor.py snapshot \
  --output-mode json \
  --container auto
```

Show help:

```bash
python3 gpu_monitor.py --help
python3 gpu_monitor.py serve --help
python3 gpu_monitor.py snapshot --help
```

## Outputs

Default generated files:

- `ollama_gpu_per_model_log.csv`
- `ollama_gpu_per_model_snapshot.json`
- `ollama_gpu_per_model.prom`

Available `--output-mode` values:

- `csv`
- `json`
- `prometheus`
- combined values such as `csv,json`
- `all`

## HTTP Endpoints

When `--metrics-http` is enabled, default endpoints are:

- `http://127.0.0.1:9464/metrics`
- `http://127.0.0.1:9464/health`
- `http://127.0.0.1:9464/ready`
- `http://127.0.0.1:9464/snapshot`

## Prometheus Example

```yaml
scrape_configs:
  - job_name: gpu_monitor
    scrape_interval: 5s
    static_configs:
      - targets:
          - 127.0.0.1:9464
```

## Documentation

- English quick start: [`README_GPU_MONITOR_EN.md`](./README_GPU_MONITOR_EN.md)
- Indonesian quick start: [`README_GPU_MONITOR_ID.md`](./README_GPU_MONITOR_ID.md)
- Full reference: [`gpu_monitor.md`](./gpu_monitor.md)
