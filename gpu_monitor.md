# GPU Monitor Reference

Referensi lengkap untuk [gpu_monitor.py](/home/srwd/gpu_monitor.py).

Untuk quick start, lihat:

- Bahasa Indonesia: [README_GPU_MONITOR_ID.md](/home/srwd/README_GPU_MONITOR_ID.md)
- English: [README_GPU_MONITOR_EN.md](/home/srwd/README_GPU_MONITOR_EN.md)

## Ringkasan

`gpu_monitor.py` adalah monitor observability untuk host GPU yang menjalankan beberapa container Ollama. Script ini mengumpulkan:

- metrik GPU dari `nvidia-smi`
- metrik container dari `docker stats`
- model aktif dari `docker exec <container> ollama ps`
- sinyal OOM dari `docker logs`

Script mendukung:

- auto-discovery multi-container Ollama
- support multi-GPU
- output `csv`, `json`, dan `prometheus`
- HTTP endpoint `/metrics`, `/health`, `/ready`, `/snapshot`
- mode daemon `serve` dan mode one-shot `snapshot`

## Requirement

- Python 3
- `docker`
- `nvidia-smi`
- container Ollama aktif, atau nama container spesifik bila ingin menargetkan satu instance

## Mode Command

Root command:

```bash
python3 /home/srwd/gpu_monitor.py --help
```

Subcommand:

- `serve`: jalan terus dan collect tiap interval
- `snapshot`: collect sekali lalu exit

Contoh:

```bash
python3 /home/srwd/gpu_monitor.py serve
python3 /home/srwd/gpu_monitor.py snapshot
```

Tanpa subcommand, script otomatis dianggap `serve`.

## CLI Options

Option yang tersedia untuk `serve` dan `snapshot`:

- `--log-file`
  Path output CSV.
- `--json-file`
  Path output JSON snapshot.
- `--prom-file`
  Path output Prometheus text.
- `--output-mode`
  Nilai: `csv`, `json`, `prometheus`, kombinasi seperti `csv,json`, atau `all`.
- `--interval`
  Interval collect dalam detik.
- `--container`
  Nama container spesifik, atau `auto`, `ollama`, `*` untuk auto-discovery.
- `--ansi`
  Nilai: `auto`, `on`, `off`.
- `--metrics-http` / `--no-metrics-http`
  Enable atau disable embedded HTTP server.
- `--metrics-http-host`
  Host bind untuk HTTP server.
- `--metrics-http-port`
  Port bind untuk HTTP server.

Lihat help detail:

```bash
python3 /home/srwd/gpu_monitor.py serve --help
python3 /home/srwd/gpu_monitor.py snapshot --help
```

## Environment Variable Fallback

Kalau flag tidak diberikan, script akan fallback ke env berikut:

- `LOG_FILE`
- `JSON_FILE`
- `PROM_FILE`
- `OUTPUT_MODE`
- `INTERVAL_S`
- `OLLAMA_CONTAINER`
- `ANSI`
- `METRICS_HTTP`
- `METRICS_HTTP_HOST`
- `METRICS_HTTP_PORT`

## Perilaku Discovery Container

Default target adalah `ollama`, tetapi script tidak hardcode ke nama container itu.

Perilakunya:

- kalau `--container` menunjuk ke container yang valid dan running, script pakai itu
- kalau `--container` adalah `ollama`, `auto`, atau `*`, script auto-discover semua container berbasis image `ollama/ollama`
- kalau container spesifik yang diminta tidak running, script fallback ke hasil discovery dan menampilkan pesan discovery di dashboard

## Output Modes

### CSV

Mode `csv` melakukan append ke file log.

Isi row mencakup:

- waktu host
- identitas GPU: `gpu_id`, `gpu_name`, `gpu_uuid`
- metrik GPU
- nama/status/error container
- data model aktif
- stats container
- flag OOM

Catatan:

- jika header CSV lama tidak cocok dengan schema terbaru, file lama akan di-rotate otomatis menjadi file `.bak.<timestamp>`

### JSON

Mode `json` menulis snapshot penuh terbaru ke satu file JSON.

Strukturnya mencakup:

- metadata waktu dan discovery
- array `gpus`
- array `containers`
- stats, error, OOM, dan model per container

### Prometheus

Mode `prometheus` menulis file text format Prometheus.

Catatan CPU container:

- nilai CPU container mengikuti `docker stats`
- angka dapat lebih dari `100%` pada host multi-core
- contoh `329.36%` berarti container sedang memakai sekitar `3.29` core CPU

Metric utama yang tersedia:

- GPU:
  - `gpu_monitor_gpu_util_percent`
  - `gpu_monitor_gpu_mem_util_percent`
  - `gpu_monitor_gpu_mem_used_mib`
  - `gpu_monitor_gpu_mem_total_mib`
  - `gpu_monitor_gpu_power_watts`
  - `gpu_monitor_gpu_temp_celsius`
  - `gpu_monitor_gpu_sm_clock_mhz`
- Container:
  - `gpu_monitor_container_status`
  - `gpu_monitor_container_cpu_percent`
  - `gpu_monitor_container_mem_percent`
  - `gpu_monitor_container_pids`
  - `gpu_monitor_container_models_loaded`
  - `gpu_monitor_container_oom_detected`
  - `gpu_monitor_container_error_state`
- Model:
  - `gpu_monitor_model_loaded`
  - `gpu_monitor_model_context_tokens`
  - `gpu_monitor_model_context_percent`
  - `gpu_monitor_model_size_bytes`
  - `gpu_monitor_model_until_seconds`

## HTTP Endpoints

Aktif jika `--metrics-http` dinyalakan.

Default bind:

- host: `127.0.0.1`
- port: `9464`

Endpoint:

- `/metrics`
  Output Prometheus text untuk di-scrape Prometheus.
- `/health`
  Ringkasan JSON status collector dan container.
- `/ready`
  Readiness probe.
  `200` jika minimal satu container berstatus `ok` atau `idle`.
  `503` jika belum ada snapshot yang usable atau semua collector gagal.
- `/snapshot`
  Full JSON snapshot yang sama levelnya dengan output file JSON.

Contoh:

```bash
curl http://127.0.0.1:9464/metrics
curl http://127.0.0.1:9464/health
curl http://127.0.0.1:9464/ready
curl http://127.0.0.1:9464/snapshot
```

## Error Classification

Script membedakan beberapa error operasional, misalnya:

- `docker_socket_permission_denied`
- `docker_daemon_unreachable`
- `container_not_found`
- `container_not_running`
- `ollama_ps_failed`
- `ollama_ps_timed_out`
- `docker_logs_timed_out`
- `docker_stats_no_data`

Error ini:

- ditampilkan di dashboard per container
- ditulis ke field `container_error`
- diekspor ke metric `gpu_monitor_container_error_state`

## Contoh Pemakaian

Daemon dengan semua output:

```bash
python3 /home/srwd/gpu_monitor.py serve \
  --output-mode all \
  --metrics-http \
  --metrics-http-host 127.0.0.1 \
  --metrics-http-port 9464 \
  --interval 2 \
  --container auto
```

One-shot snapshot JSON:

```bash
python3 /home/srwd/gpu_monitor.py snapshot \
  --output-mode json \
  --container auto
```

Target satu container tertentu:

```bash
python3 /home/srwd/gpu_monitor.py serve \
  --container ollama-chat \
  --output-mode csv,prometheus
```

Hanya HTTP exporter tanpa CSV:

```bash
python3 /home/srwd/gpu_monitor.py serve \
  --output-mode prometheus \
  --metrics-http
```

## Contoh Prometheus Scrape Config

Contoh `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: gpu_monitor
    scrape_interval: 5s
    static_configs:
      - targets:
          - 127.0.0.1:9464
```

Catatan:

- endpoint yang di-scrape adalah `/metrics`
- aktifkan monitor dengan `--metrics-http`
- ubah target jika monitor berjalan di host lain

## Contoh systemd Service

Contoh unit file:

```ini
[Unit]
Description=GPU Monitor for Ollama
After=docker.service network.target
Requires=docker.service

[Service]
Type=simple
User=srwd
WorkingDirectory=/home/srwd
ExecStart=/usr/bin/python3 /home/srwd/gpu_monitor.py serve --output-mode all --metrics-http --metrics-http-host 127.0.0.1 --metrics-http-port 9464 --interval 2 --container auto
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Langkah umum deploy:

```bash
sudo cp gpu-monitor.service /etc/systemd/system/gpu-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable --now gpu-monitor.service
sudo systemctl status gpu-monitor.service
```

## Saran Operasional

Saran penggunaan:

- pakai `serve` untuk monitoring terus-menerus
- pakai `snapshot` untuk cron, debug, atau verifikasi cepat
- pakai `--output-mode prometheus --metrics-http` kalau ingin integrasi Prometheus yang paling bersih
- pakai `--container auto` kalau host menjalankan lebih dari satu instance Ollama

## File Terkait

- Script: [gpu_monitor.py](/home/srwd/gpu_monitor.py)
- Dokumentasi ini: [gpu_monitor.md](/home/srwd/gpu_monitor.md)
