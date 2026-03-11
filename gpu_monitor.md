# GPU Monitor Reference

Referensi lengkap untuk monitor multi-runtime di [gpu_monitor.py](./gpu_monitor.py).

Dokumen terkait:

- Main README: [README.md](./README.md)
- English quick start: [README_GPU_MONITOR_EN.md](./README_GPU_MONITOR_EN.md)
- Indonesian quick start: [README_GPU_MONITOR_ID.md](./README_GPU_MONITOR_ID.md)

## Ringkasan

`gpu_monitor.py` adalah monitor observability untuk host GPU yang menjalankan runtime AI berbasis container. Saat ini monitor mendukung:

- `ollama`
- `vllm`
- `sglang`
- `localai`
- `docker-model-runner`
- `generic`

Data yang dikumpulkan:

- metrik GPU host dari `nvidia-smi`
- statistik container dari `docker stats`
- daftar model aktif atau tersedia dari adapter runtime
- sinyal OOM GPU dari `docker logs`
- output `csv`, `json`, `prometheus`
- embedded HTTP endpoint `/metrics`, `/health`, `/ready`, `/snapshot`

## Runtime Adapter

### Ollama

- discovery default berdasarkan image yang mengandung `ollama`
- model introspection memakai `docker exec <container> ollama ps`

### vLLM

- discovery default berdasarkan image yang mengandung `vllm`
- model introspection memakai `GET /v1/models`
- runtime probe memakai `GET /health`
- runtime metrics probe memakai `GET /metrics`

### SGLang

- discovery default berdasarkan image yang mengandung `sglang`
- model introspection memakai `GET /v1/models`
- runtime probe memakai `GET /health`
- runtime metrics probe memakai `GET /metrics`

### LocalAI

- discovery default berdasarkan image yang mengandung `localai`
- model introspection memakai `GET /v1/models`

### Docker Model Runner

- discovery default berdasarkan image yang mengandung `model-runner`
- model introspection memakai `GET /v1/models`

### Generic

- dipakai untuk runtime lain yang belum punya adapter
- hanya monitor GPU host, statistik container, dan OOM log

## CLI Options

Flag utama untuk `serve` dan `snapshot`:

- `--runtime`
  Pilihan: `ollama`, `vllm`, `sglang`, `localai`, `docker-model-runner`, `generic`
- `--container`
  Nama container spesifik, atau `auto`
- `--image-match`
  Override substring image untuk discovery container
- `--api-base-url`
  Override base URL API runtime
- `--runtime-port`
  Override host port API runtime
- `--log-file`
  Path output CSV
- `--json-file`
  Path output JSON
- `--prom-file`
  Path output Prometheus text
- `--output-mode`
  `csv`, `json`, `prometheus`, kombinasi, atau `all`
- `--interval`
  Interval collection
- `--metrics-http`
  Aktifkan HTTP exporter milik monitor

## Environment Variable Fallback

- `MONITOR_RUNTIME`
- `CONTAINER_NAME`
- `OLLAMA_CONTAINER`
- `IMAGE_MATCH`
- `API_BASE_URL`
- `RUNTIME_PORT`
- `LOG_FILE`
- `JSON_FILE`
- `PROM_FILE`
- `OUTPUT_MODE`
- `INTERVAL_S`
- `ANSI`
- `METRICS_HTTP`
- `METRICS_HTTP_HOST`
- `METRICS_HTTP_PORT`

## Output Schema

### CSV

CSV kini menyertakan field runtime-aware, termasuk:

- `container_runtime`
- `container_status`
- `container_error`

Jika schema CSV berubah, file lama akan di-rotate ke `.bak.<timestamp>`.

### JSON

Payload JSON kini menyertakan:

- `runtime`
- `requested_container`
- `discovery_message`
- `gpus`
- `containers`

Per container:

- `name`
- `runtime`
- `api_base_url`
- `status`
- `error`
- `runtime_health_ok`
- `runtime_metrics_ok`
- `runtime_metrics_samples`
- `stats`
- `models`

### Prometheus

Metric utama:

- `gpu_monitor_gpu_util_percent`
- `gpu_monitor_gpu_mem_util_percent`
- `gpu_monitor_gpu_mem_used_mib`
- `gpu_monitor_gpu_mem_total_mib`
- `gpu_monitor_gpu_power_watts`
- `gpu_monitor_gpu_temp_celsius`
- `gpu_monitor_gpu_sm_clock_mhz`
- `gpu_monitor_container_status`
- `gpu_monitor_container_cpu_percent`
- `gpu_monitor_container_mem_percent`
- `gpu_monitor_container_pids`
- `gpu_monitor_container_models_loaded`
- `gpu_monitor_container_oom_detected`
- `gpu_monitor_runtime_health_up`
- `gpu_monitor_runtime_metrics_up`
- `gpu_monitor_runtime_metrics_samples`
- `gpu_monitor_container_error_state`
- `gpu_monitor_model_loaded`

## Embedded HTTP Endpoints

Endpoint milik monitor:

- `/metrics`
- `/health`
- `/ready`
- `/snapshot`

Catatan:

- ini berbeda dari endpoint runtime seperti `vllm` atau `sglang`
- untuk `vllm` dan `sglang`, monitor juga mencoba probe ke `/health` dan `/metrics` milik runtime

## Contoh

Ollama:

```bash
python3 gpu_monitor.py serve --runtime ollama --container auto --output-mode all --metrics-http
```

vLLM:

```bash
python3 gpu_monitor.py serve --runtime vllm --container auto --output-mode all --metrics-http
```

SGLang dengan port override:

```bash
python3 gpu_monitor.py serve --runtime sglang --container auto --runtime-port 30000 --output-mode all
```

Generic runtime:

```bash
python3 gpu_monitor.py serve --runtime generic --container my-runtime-container --output-mode prometheus
```

## Error Classification

Beberapa error operasional yang dapat muncul:

- `docker_socket_permission_denied`
- `docker_daemon_unreachable`
- `container_not_found`
- `container_not_running`
- `api_endpoint_unresolved`
- `api_request_failed`
- `api_http_error`
- `api_invalid_json`
- `ollama_ps_failed`
- `ollama_ps_timed_out`
- `docker_logs_timed_out`
- `docker_stats_no_data`
