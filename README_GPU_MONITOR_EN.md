# GPU Monitor

Quick start for [gpu_monitor.py](./gpu_monitor.py).

Full reference is available in [gpu_monitor.md](./gpu_monitor.md).

## What It Does

This script monitors:

- host GPU metrics via `nvidia-smi`
- Ollama container metrics via `docker stats`
- loaded models via `ollama ps`
- OOM signals via `docker logs`

Main features:

- multi-container Ollama auto-discovery
- multi-GPU support
- `csv`, `json`, and `prometheus` outputs
- HTTP endpoints `/metrics`, `/health`, `/ready`, `/snapshot`
- `serve` and `snapshot` modes

## Requirements

- Python 3
- `docker`
- `nvidia-smi`

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

## Output

- CSV log: default `ollama_gpu_per_model_log.csv`
- JSON snapshot: default `ollama_gpu_per_model_snapshot.json`
- Prometheus text: default `ollama_gpu_per_model.prom`

Container CPU note:

- container CPU comes from `docker stats`
- values can exceed `100%` on multi-core hosts
- example: `329.36%` means the container is using about `3.29` CPU cores

Output modes:

- `csv`
- `json`
- `prometheus`
- combinations such as `csv,json`
- `all`

## HTTP Endpoints

If `--metrics-http` is enabled, the default endpoints are:

- `http://127.0.0.1:9464/metrics`
- `http://127.0.0.1:9464/health`
- `http://127.0.0.1:9464/ready`
- `http://127.0.0.1:9464/snapshot`

## Important Options

- `--container auto`
  Auto-discover all active Ollama containers.
- `--output-mode all`
  Write CSV, JSON, and Prometheus outputs together.
- `--metrics-http`
  Enable the embedded HTTP exporter.
- `--interval 2`
  Collect every 2 seconds.

## Common Examples

Target a specific container:

```bash
python3 gpu_monitor.py serve \
  --container ollama-chat \
  --output-mode csv,prometheus
```

Run only the HTTP exporter path:

```bash
python3 gpu_monitor.py serve \
  --output-mode prometheus \
  --metrics-http
```

## Prometheus Scrape Config

Example `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: gpu_monitor
    scrape_interval: 5s
    static_configs:
      - targets:
          - 127.0.0.1:9464
```

If the monitor runs on another host, replace the target with the correct `host:port`.

## systemd Service

Example unit file:

```ini
[Unit]
Description=GPU Monitor for Ollama
After=docker.service network.target
Requires=docker.service

[Service]
Type=simple
User=srwd
WorkingDirectory=/opt/gpu_monitor
ExecStart=/usr/bin/python3 /opt/gpu_monitor/gpu_monitor.py serve --output-mode all --metrics-http --metrics-http-host 127.0.0.1 --metrics-http-port 9464 --interval 2 --container auto
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Typical steps:

```bash
sudo cp /path/to/gpu-monitor.service /etc/systemd/system/gpu-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable --now gpu-monitor.service
sudo systemctl status gpu-monitor.service
```

## References

- Full reference: [gpu_monitor.md](./gpu_monitor.md)
- Script: [gpu_monitor.py](./gpu_monitor.py)
- Indonesian quick start: [README_GPU_MONITOR_ID.md](./README_GPU_MONITOR_ID.md)
