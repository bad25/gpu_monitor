# GPU Monitor

Multi-runtime GPU and container monitor for local AI inference stacks.

The monitor collects:

- host GPU metrics from `nvidia-smi`
- container CPU, memory, I/O, and PID metrics from `docker stats`
- model/runtime introspection per adapter
- GPU OOM signals from `docker logs`
- Prometheus, JSON, CSV, and optional embedded HTTP exporter output

## Supported Runtimes

Current runtime adapters:

- `ollama`
- `vllm`
- `sglang`
- `localai`
- `docker-model-runner`
- `generic`

Support level:

- `ollama`: full container discovery plus `ollama ps` model parsing
- `vllm`: container discovery plus OpenAI-compatible `/v1/models`, `/health`, and `/metrics`
- `sglang`: container discovery plus OpenAI-compatible `/v1/models`, `/health`, and `/metrics`
- `localai`: container discovery plus OpenAI-compatible `/v1/models`
- `docker-model-runner`: container discovery plus OpenAI-compatible `/v1/models`
- `generic`: GPU/container/OOM monitoring without model introspection

## Requirements

- Python 3
- `docker`
- `nvidia-smi`

## CLI

Show help:

```bash
python3 gpu_monitor.py --help
python3 gpu_monitor.py serve --help
python3 gpu_monitor.py snapshot --help
```

Common flags:

- `--runtime`: runtime adapter to use
- `--container`: specific container name, or `auto`
- `--image-match`: override discovery image filter
- `--api-base-url`: force runtime API base URL
- `--runtime-port`: force runtime API host port
- `--output-mode`: `csv`, `json`, `prometheus`, or `all`
- `--metrics-http`: expose `/metrics`, `/health`, `/ready`, `/snapshot`

## Quick Start

Ollama:

```bash
python3 gpu_monitor.py serve \
  --runtime ollama \
  --container auto \
  --output-mode all \
  --metrics-http \
  --interval 2
```

vLLM:

```bash
python3 gpu_monitor.py serve \
  --runtime vllm \
  --container auto \
  --output-mode all \
  --metrics-http \
  --interval 2
```

SGLang:

```bash
python3 gpu_monitor.py serve \
  --runtime sglang \
  --container auto \
  --output-mode all \
  --metrics-http \
  --interval 2
```

LocalAI:

```bash
python3 gpu_monitor.py serve \
  --runtime localai \
  --container auto \
  --output-mode all
```

Docker Model Runner:

```bash
python3 gpu_monitor.py serve \
  --runtime docker-model-runner \
  --container auto \
  --output-mode all
```

Generic container:

```bash
python3 gpu_monitor.py serve \
  --runtime generic \
  --container my-runtime-container \
  --output-mode all
```

One-shot snapshot:

```bash
python3 gpu_monitor.py snapshot \
  --runtime vllm \
  --container auto \
  --output-mode json
```

## Runtime-Specific Notes

### Ollama

- discovery defaults to containers whose image matches `ollama/ollama`
- model list comes from `docker exec <container> ollama ps`

### vLLM

- discovery defaults to image names containing `vllm`
- model list uses `GET /v1/models`
- runtime health uses `GET /health`
- runtime metrics uses `GET /metrics`
- if port auto-detection fails, set `--runtime-port 8000` or `--api-base-url http://127.0.0.1:8000`

### SGLang

- discovery defaults to image names containing `sglang`
- model list uses `GET /v1/models`
- runtime health uses `GET /health`
- runtime metrics uses `GET /metrics`
- if port auto-detection fails, set `--runtime-port 30000` or `--api-base-url http://127.0.0.1:30000`

### LocalAI

- discovery defaults to image names containing `localai`
- model list uses `GET /v1/models`

### Docker Model Runner

- discovery defaults to image names containing `model-runner`
- model list uses `GET /v1/models`

### Generic

- use this when the runtime has no supported adapter yet
- the monitor still reports GPU, container resource usage, and OOM events

## Outputs

Default generated files:

- `gpu_monitor_log.csv`
- `gpu_monitor_snapshot.json`
- `gpu_monitor.prom`

Extra runtime-aware fields now include:

- `runtime` in JSON payloads
- `container_runtime` in CSV
- `gpu_monitor_runtime_health_up` in Prometheus
- `gpu_monitor_runtime_metrics_up` in Prometheus
- `gpu_monitor_runtime_metrics_samples` in Prometheus

## Embedded HTTP Endpoints

When `--metrics-http` is enabled, the monitor exposes:

- `http://127.0.0.1:9464/metrics`
- `http://127.0.0.1:9464/health`
- `http://127.0.0.1:9464/ready`
- `http://127.0.0.1:9464/snapshot`

These are the monitor's own endpoints, separate from runtime endpoints such as `vLLM` or `SGLang` `/health` and `/metrics`.

## Prometheus Example

```yaml
scrape_configs:
  - job_name: gpu_monitor
    scrape_interval: 5s
    static_configs:
      - targets:
          - 127.0.0.1:9464
```

## Files

- [`gpu_monitor.py`](./gpu_monitor.py): main monitor
- [`CHANGELOG.md`](./CHANGELOG.md): official release history
- [`gpu_monitor.md`](./gpu_monitor.md): detailed reference
- [`README_GPU_MONITOR_EN.md`](./README_GPU_MONITOR_EN.md): English quick start
- [`README_GPU_MONITOR_ID.md`](./README_GPU_MONITOR_ID.md): Indonesian quick start
- [`gpu_monitor_v1.sh`](./gpu_monitor_v1.sh): older shell version
- [`gpu_monitor_v2.sh`](./gpu_monitor_v2.sh): newer shell version
