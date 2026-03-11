# GPU Monitor

Quick start untuk [gpu_monitor.py](/home/srwd/gpu_monitor.py).

Dokumentasi lengkap ada di [gpu_monitor.md](/home/srwd/gpu_monitor.md).

## Fungsi

Script ini memonitor:

- GPU host via `nvidia-smi`
- container Ollama via `docker stats`
- model aktif via `ollama ps`
- OOM signal via `docker logs`

Fitur utama:

- multi-container Ollama auto-discovery
- support multi-GPU
- output `csv`, `json`, `prometheus`
- HTTP endpoints `/metrics`, `/health`, `/ready`, `/snapshot`
- mode `serve` dan `snapshot`

## Requirement

- Python 3
- `docker`
- `nvidia-smi`

## Quick Start

Jalankan monitor terus-menerus:

```bash
python3 /home/srwd/gpu_monitor.py serve \
  --output-mode all \
  --metrics-http \
  --interval 2 \
  --container auto
```

Ambil satu snapshot lalu keluar:

```bash
python3 /home/srwd/gpu_monitor.py snapshot \
  --output-mode json \
  --container auto
```

Lihat help:

```bash
python3 /home/srwd/gpu_monitor.py --help
python3 /home/srwd/gpu_monitor.py serve --help
python3 /home/srwd/gpu_monitor.py snapshot --help
```

## Output

- CSV log: default `ollama_gpu_per_model_log.csv`
- JSON snapshot: default `ollama_gpu_per_model_snapshot.json`
- Prometheus text: default `ollama_gpu_per_model.prom`

Catatan CPU container:

- nilai CPU berasal dari `docker stats`
- nilai bisa lebih dari `100%` pada host multi-core
- contoh `329.36%` berarti kira-kira memakai `3.29` core CPU

Output mode:

- `csv`
- `json`
- `prometheus`
- kombinasi seperti `csv,json`
- `all`

## HTTP Endpoints

Jika `--metrics-http` aktif, default endpoint:

- `http://127.0.0.1:9464/metrics`
- `http://127.0.0.1:9464/health`
- `http://127.0.0.1:9464/ready`
- `http://127.0.0.1:9464/snapshot`

## Opsi Penting

- `--container auto`
  Auto-discover semua container Ollama aktif.
- `--output-mode all`
  Tulis CSV, JSON, dan Prometheus sekaligus.
- `--metrics-http`
  Enable embedded HTTP exporter.
- `--interval 2`
  Collect setiap 2 detik.

## Contoh Umum

Target satu container tertentu:

```bash
python3 /home/srwd/gpu_monitor.py serve \
  --container ollama-chat \
  --output-mode csv,prometheus
```

HTTP exporter saja:

```bash
python3 /home/srwd/gpu_monitor.py serve \
  --output-mode prometheus \
  --metrics-http
```

## Prometheus Scrape Config

Contoh `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: gpu_monitor
    scrape_interval: 5s
    static_configs:
      - targets:
          - 127.0.0.1:9464
```

Jika monitor jalan di host lain, ganti target ke `host:port` yang sesuai.

## systemd Service

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

Langkah umum:

```bash
sudo cp /path/to/gpu-monitor.service /etc/systemd/system/gpu-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable --now gpu-monitor.service
sudo systemctl status gpu-monitor.service
```

## Referensi

- Ringkasan lengkap: [gpu_monitor.md](/home/srwd/gpu_monitor.md)
- Script: [gpu_monitor.py](/home/srwd/gpu_monitor.py)
