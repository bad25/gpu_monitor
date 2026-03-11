# GPU Monitor

Quick start for the multi-runtime monitor in [gpu_monitor.py](./gpu_monitor.py).

Main documentation:

- Main README: [README.md](./README.md)
- Full reference: [gpu_monitor.md](./gpu_monitor.md)

## Supported Runtimes

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

## Notes

- `ollama` uses `docker exec <container> ollama ps`
- `vllm` and `sglang` use `/v1/models`, `/health`, and `/metrics`
- `localai` and `docker-model-runner` use `/v1/models`
- `generic` only monitors GPU, container stats, and OOM logs

If runtime API auto-detection fails, override it manually:

```bash
python3 gpu_monitor.py serve --runtime vllm --container my-vllm --runtime-port 8000
python3 gpu_monitor.py serve --runtime sglang --container my-sglang --api-base-url http://127.0.0.1:30000
```

## Outputs

- CSV: `ollama_gpu_per_model_log.csv`
- JSON: `ollama_gpu_per_model_snapshot.json`
- Prometheus: `ollama_gpu_per_model.prom`

Monitor HTTP endpoints:

- `/metrics`
- `/health`
- `/ready`
- `/snapshot`
