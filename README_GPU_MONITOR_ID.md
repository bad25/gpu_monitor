# GPU Monitor

Quick start untuk monitor multi-runtime di [gpu_monitor.py](./gpu_monitor.py).

Dokumentasi utama:

- README utama: [README.md](./README.md)
- Referensi lengkap: [gpu_monitor.md](./gpu_monitor.md)

## Runtime yang Didukung

- `ollama`
- `vllm`
- `sglang`
- `localai`
- `docker-model-runner`
- `generic`

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

Container generic:

```bash
python3 gpu_monitor.py serve \
  --runtime generic \
  --container my-runtime-container \
  --output-mode all
```

Snapshot satu kali:

```bash
python3 gpu_monitor.py snapshot \
  --runtime vllm \
  --container auto \
  --output-mode json
```

## Catatan

- `ollama` memakai `docker exec <container> ollama ps`
- `vllm` dan `sglang` memakai `/v1/models`, `/health`, dan `/metrics`
- `localai` dan `docker-model-runner` memakai `/v1/models`
- `generic` hanya monitor GPU, statistik container, dan log OOM

Kalau auto-detect API runtime gagal, override manual:

```bash
python3 gpu_monitor.py serve --runtime vllm --container my-vllm --runtime-port 8000
python3 gpu_monitor.py serve --runtime sglang --container my-sglang --api-base-url http://127.0.0.1:30000
```

## Output

- CSV: `gpu_monitor_log.csv`
- JSON: `gpu_monitor_snapshot.json`
- Prometheus: `gpu_monitor.prom`

Endpoint HTTP monitor:

- `/metrics`
- `/health`
- `/ready`
- `/snapshot`
