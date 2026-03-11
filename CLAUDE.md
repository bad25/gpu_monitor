# GPU Monitor

Single-file Python observability tool untuk monitoring GPU + container di AI inference runtime.

## Commands

```bash
# Jalankan monitor (Ollama, continuous)
python3 gpu_monitor.py serve --runtime ollama --container auto --output-mode all --metrics-http --interval 2

# One-shot snapshot
python3 gpu_monitor.py snapshot --runtime vllm --container auto --output-mode json

# Help
python3 gpu_monitor.py --help
python3 gpu_monitor.py serve --help
python3 gpu_monitor.py snapshot --help
```

## Arsitektur

Satu file: `gpu_monitor.py`. Tidak ada dependency eksternal — hanya stdlib Python + `nvidia-smi` + `docker` di host.

Bagian utama dalam file:
- `Helpers` — subprocess wrapper, utilitas waktu
- Runtime adapters — satu class per runtime (`OllamaAdapter`, `VllmAdapter`, dst.)
- `CollectionLoop` — main polling loop
- `MetricsHTTPServer` — embedded HTTP exporter

## Runtime yang Didukung

`ollama`, `vllm`, `sglang`, `localai`, `docker-model-runner`, `generic`

Menambah runtime baru: implementasikan interface adapter (lihat adapter yang sudah ada) lalu daftarkan di dispatch map runtime.

## Output Files

File yang digenerate secara default (gitignored):
- `gpu_monitor_log.csv`
- `gpu_monitor_snapshot.json`
- `gpu_monitor.prom`

HTTP endpoint (jika `--metrics-http` aktif): `http://127.0.0.1:9464/{metrics,health,ready,snapshot}`

## Gotchas

- **CSV schema rotation**: jika schema CSV berubah antar run, file lama otomatis di-rename ke `.bak.<timestamp>` — ini bukan error
- **CLI flags vs env var**: setiap CLI flag punya env var fallback (contoh: `MONITOR_RUNTIME`, `CONTAINER_NAME`, `INTERVAL_S`). Lihat `gpu_monitor.md` untuk daftar lengkap.
- **Container discovery**: `--container auto` pakai substring nama image. Jika salah deteksi, override dengan `--image-match`.
- **Port detection**: jika auto-deteksi port API gagal, gunakan `--runtime-port` atau `--api-base-url` secara eksplisit.

## Docs

- `README.md` — referensi utama (English)
- `gpu_monitor.md` — referensi lengkap CLI/schema (Indonesian)
- `CHANGELOG.md` — riwayat rilis
