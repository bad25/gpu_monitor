#!/usr/bin/env python3
#"""
#SAWIT.tech Local AI DevOps Lab Monitor (Python)
#- One CSV row per model per interval (Grafana/Postgres-ready)
#- Live terminal dashboard (optional ANSI)
#- Sources:
#   * GPU: nvidia-smi (host)
#   * Container: docker stats (ollama container)
#   * Models: docker exec <container> ollama ps (robust column parsing)
#   * OOM: docker logs tail since last tick; detect "CUDA out of memory" / "out of memory"
#
#Usage:
#  chmod +x monitor_ollama_gpu_per_model.py
#  ./monitor_ollama_gpu_per_model.py
#
#Env overrides:
#  LOG_FILE=ollama_gpu_per_model_log.csv
#  INTERVAL_S=1
#  OLLAMA_CONTAINER=ollama
#  ANSI=1 (force) / ANSI=0 (disable)
#
#Stop:
#  Ctrl+C
#"""
from __future__ import annotations

import argparse
import os
import sys
import time
import csv
import json
import re
import shutil
import subprocess
import concurrent.futures
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple


# -------------------------
# Helpers
# -------------------------
def which_or_die(cmd: str) -> None:
    if shutil.which(cmd) is None:
        raise SystemExit(f"ERROR: missing required command: {cmd}")


@dataclass
class CmdResult:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return (not self.timed_out) and self.returncode == 0

    @property
    def combined_output(self) -> str:
        return (self.stdout or self.stderr).strip()


def run_cmd_result(args: List[str], timeout: float = 10.0, merge_stderr: bool = False) -> CmdResult:
    try:
        stderr_target = subprocess.STDOUT if merge_stderr else subprocess.PIPE
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=stderr_target, text=True, timeout=timeout)
        return CmdResult(
            stdout=(p.stdout or "").strip(),
            stderr="" if merge_stderr else (p.stderr or "").strip(),
            returncode=p.returncode,
            timed_out=False,
        )
    except subprocess.TimeoutExpired:
        return CmdResult(returncode=124, timed_out=True)


def run_cmd(args: List[str], timeout: float = 10.0, merge_stderr: bool = False) -> str:
    result = run_cmd_result(args, timeout=timeout, merge_stderr=merge_stderr)
    if not result.ok:
        return ""
    return result.stdout


def now_local_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def iso_utc(ts: float) -> str:
    # docker logs --since accepts RFC3339 or Unix timestamp; RFC3339 is safer
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def try_int(x: str, default: int = 0) -> int:
    try:
        return int(float(x))
    except Exception:
        return default


def try_float(x: str, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def format_container_cpu(cpu_pct: str) -> str:
    if not cpu_pct:
        return "-"
    cpu_value = try_float(cpu_pct, 0.0)
    return f"{cpu_pct} % (~{cpu_value / 100.0:.2f} cores)"


# -------------------------
# ANSI / dashboard
# -------------------------
class ANSI:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        if not enabled:
            self.RED = self.GREEN = self.YELLOW = self.CYAN = self.MAGENTA = self.GRAY = self.RESET = self.BOLD = ""
            return
        self.RED = "\033[38;5;196m"
        self.GREEN = "\033[38;5;46m"
        self.YELLOW = "\033[38;5;226m"
        self.CYAN = "\033[38;5;51m"
        self.MAGENTA = "\033[38;5;201m"
        self.GRAY = "\033[38;5;240m"
        self.RESET = "\033[0m"
        self.BOLD = "\033[1m"

    def pct_color(self, pct: int) -> str:
        if pct >= 90:
            return self.RED
        if pct >= 75:
            return self.YELLOW
        return self.GREEN

    def temp_color(self, t: int) -> str:
        if t >= 85:
            return self.RED
        if t >= 78:
            return self.YELLOW
        return self.GREEN

    def progress_bar(self, pct: int, width: int = 24) -> str:
        pct = max(0, min(100, pct))
        filled = (pct * width) // 100
        empty = width - filled
        return "[" + ("█" * filled) + ("░" * empty) + f"] {pct:3d}%"


# -------------------------
# Data models
# -------------------------
@dataclass
class GpuSnap:
    gpu_id: str = ""
    gpu_name: str = ""
    gpu_uuid: str = ""
    nv_ts: str = ""
    util_pct: str = ""
    mem_util_pct: str = ""
    mem_used_mib: str = ""
    mem_total_mib: str = ""
    power_w: str = ""
    temp_c: str = ""
    sm_clock_mhz: str = ""


@dataclass
class ContainerSnap:
    cpu_pct: str = ""
    mem_used: str = ""
    mem_limit: str = ""
    mem_pct: str = ""
    net_in: str = ""
    net_out: str = ""
    blk_in: str = ""
    blk_out: str = ""
    pids: str = ""


@dataclass
class ModelRow:
    name: str
    ctx: str
    size: str
    processor_raw: str
    ctx_pct: str
    device_mix: str
    until: str
    model_id: str


@dataclass
class ContainerReport:
    name: str
    stats: ContainerSnap
    models: List[ModelRow]
    oom_detected: bool
    oom_line: str
    status: str
    stats_error: str = ""
    ps_error: str = ""
    oom_error: str = ""
    error: str = ""


@dataclass
class SharedSnapshotState:
    lock: threading.Lock
    prometheus_text: str = ""
    health_payload: Dict[str, Any] | None = None
    json_payload: Dict[str, Any] | None = None
    ready_payload: Dict[str, Any] | None = None


@dataclass
class AppConfig:
    command: str
    log_file: str
    json_file: str
    prom_file: str
    output_modes: List[str]
    metrics_http_enabled: bool
    metrics_http_host: str
    metrics_http_port: int
    interval_s: float
    requested_container: str
    ansi_enabled: bool


# -------------------------
# Collectors
# -------------------------
def classify_docker_error(stderr: str, container: Optional[str] = None) -> str:
    message = (stderr or "").strip()
    lower = message.lower()
    if not message:
        return "unknown error"
    if "permission denied" in lower and "docker api" in lower:
        return "docker socket permission denied"
    if "cannot connect to the docker daemon" in lower:
        return "docker daemon unreachable"
    if "no such container" in lower:
        if container:
            return f"container not found: {container}"
        return "container not found"
    if "is not running" in lower:
        if container:
            return f"container not running: {container}"
        return "container not running"
    return message


def get_gpus() -> List[GpuSnap]:
    out = run_cmd([
        "nvidia-smi",
        "--query-gpu=index,name,uuid,timestamp,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,temperature.gpu,clocks.sm",
        "--format=csv,noheader,nounits"
    ], timeout=5.0)
    snaps: List[GpuSnap] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")] if line else [""] * 11
        parts = (parts + [""] * 11)[:11]
        snaps.append(GpuSnap(
            gpu_id=parts[0],
            gpu_name=parts[1],
            gpu_uuid=parts[2],
            nv_ts=parts[3],
            util_pct=parts[4],
            mem_util_pct=parts[5],
            mem_used_mib=parts[6],
            mem_total_mib=parts[7],
            power_w=parts[8],
            temp_c=parts[9],
            sm_clock_mhz=parts[10],
        ))
    if snaps:
        return snaps
    return [GpuSnap()]


def get_container_stats(container: str) -> Tuple[ContainerSnap, str]:
    result = run_cmd_result([
        "docker", "stats", "--no-stream",
        "--format", "{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}},{{.BlockIO}},{{.PIDs}}",
        container
    ], timeout=5.0)
    if not result.ok:
        return ContainerSnap(), classify_docker_error(result.stderr, container)
    out = result.stdout
    if not out:
        return ContainerSnap(), "docker stats returned no data"

    parts = [p.strip() for p in out.split(",")]
    parts = (parts + [""] * 6)[:6]
    c_cpu, c_memusage, c_memp, c_netio, c_blkio, c_pids = parts

    # cleanup perc
    c_cpu = c_cpu.replace("%", "").strip()
    c_memp = c_memp.replace("%", "").strip()

    mem_used, mem_limit = "", ""
    if " / " in c_memusage:
        mem_used, mem_limit = [x.strip() for x in c_memusage.split(" / ", 1)]
    net_in, net_out = "", ""
    if " / " in c_netio:
        net_in, net_out = [x.strip() for x in c_netio.split(" / ", 1)]
    blk_in, blk_out = "", ""
    if " / " in c_blkio:
        blk_in, blk_out = [x.strip() for x in c_blkio.split(" / ", 1)]

    return ContainerSnap(
        cpu_pct=c_cpu,
        mem_used=mem_used,
        mem_limit=mem_limit,
        mem_pct=c_memp,
        net_in=net_in,
        net_out=net_out,
        blk_in=blk_in,
        blk_out=blk_out,
        pids=c_pids.strip(),
    ), ""


def list_running_ollama_containers() -> Tuple[List[str], str]:
    result = run_cmd_result([
        "docker", "ps",
        "--filter", "ancestor=ollama/ollama",
        "--format", "{{.Names}}",
    ], timeout=5.0)
    if not result.ok:
        return [], classify_docker_error(result.stderr)
    return [ln.strip() for ln in result.stdout.splitlines() if ln.strip()], ""


def container_exists(container: str) -> bool:
    if not container:
        return False
    out = run_cmd([
        "docker", "ps",
        "--filter", f"name=^{container}$",
        "--format", "{{.Names}}",
    ], timeout=5.0)
    return any(ln.strip() == container for ln in out.splitlines())


def parse_ollama_ps(ps_text: str) -> List[ModelRow]:
    """
    Robust parsing by column positions derived from header line indices,
    similar to the bash script approach.
    """
    lines = [ln.rstrip("\n") for ln in ps_text.splitlines() if ln.strip() != ""]
    if len(lines) <= 1:
        return []

    header = lines[0]
    # Find column starts
    id_pos = header.find("ID")
    size_pos = header.find("SIZE")
    proc_pos = header.find("PROCESSOR")
    ctx_pos = header.find("CONTEXT")
    until_pos = header.find("UNTIL")

    if min(id_pos, size_pos, proc_pos, ctx_pos, until_pos) < 0:
        # Fallback: whitespace split (less reliable)
        rows: List[ModelRow] = []
        for ln in lines[1:]:
            cols = ln.split()
            if len(cols) < 6:
                continue
            # name may include ":" but not spaces; safe
            name = cols[0]
            model_id = cols[1]
            size = cols[2]
            # processor may be multiple tokens until CONTEXT numeric; heuristic:
            # find first token that is all digits (context)
            ctx_idx = None
            for i in range(3, len(cols)):
                if cols[i].isdigit():
                    ctx_idx = i
                    break
            if ctx_idx is None:
                continue
            processor_raw = " ".join(cols[3:ctx_idx])
            ctx = cols[ctx_idx]
            until = " ".join(cols[ctx_idx+1:]) if ctx_idx+1 < len(cols) else ""
            # ctx_pct = first token of processor_raw
            pparts = processor_raw.split()
            ctx_pct = pparts[0] if pparts else ""
            device_mix = " ".join(pparts[1:]) if len(pparts) > 1 else ""
            rows.append(ModelRow(name, ctx, size, processor_raw, ctx_pct, device_mix, until, model_id))
        return rows

    rows = []
    for ln in lines[1:]:
        name = ln[:id_pos].strip()
        model_id = ln[id_pos:size_pos].strip()
        size = ln[size_pos:proc_pos].strip()
        proc = ln[proc_pos:ctx_pos].strip()
        ctx = ln[ctx_pos:until_pos].strip()
        until = ln[until_pos:].strip()

        pparts = proc.split()
        ctx_pct = pparts[0] if pparts else ""
        device_mix = " ".join(pparts[1:]) if len(pparts) > 1 else ""

        rows.append(ModelRow(
            name=name,
            ctx=ctx,
            size=size,
            processor_raw=proc,
            ctx_pct=ctx_pct,
            device_mix=device_mix,
            until=until,
            model_id=model_id,
        ))
    return rows


def get_ollama_ps(container: str) -> str:
    return run_cmd(["docker", "exec", container, "ollama", "ps"], timeout=8.0)


def get_ollama_ps_result(container: str) -> Tuple[str, str]:
    result = run_cmd_result(["docker", "exec", container, "ollama", "ps"], timeout=8.0)
    if result.timed_out:
        return "", f"ollama ps timed out in {container}"
    if not result.ok:
        err = classify_docker_error(result.stderr, container)
        if err == "unknown error":
            err = f"ollama ps failed in {container}: {(result.stderr or result.stdout or 'unknown error').strip()}"
        return "", err
    return result.stdout, ""


def resolve_ollama_containers(preferred: str) -> Tuple[List[str], Optional[str]]:
    """
    Returns (container_names, resolution_message).
    If a specific running container is requested, use only that one.
    Otherwise discover all running Ollama containers.
    """
    if preferred and preferred not in ("ollama", "auto", "*") and container_exists(preferred):
        return [preferred], None

    candidates, discovery_error = list_running_ollama_containers()
    if not candidates:
        if discovery_error:
            return [preferred], discovery_error
        if preferred and preferred not in ("ollama", "auto", "*"):
            return [preferred], f"Requested OLLAMA container '{preferred}' is not running; monitoring will likely show errors."
        return [preferred], f"No running Ollama containers found for requested target '{preferred}'."

    if preferred and preferred not in ("ollama", "auto", "*") and not container_exists(preferred):
        return candidates, f"Requested OLLAMA container '{preferred}' is not running; discovered {len(candidates)} running Ollama container(s) instead."

    return candidates, f"Auto-discovered {len(candidates)} running Ollama container(s)."


# Precise GPU/CUDA OOM patterns — requires explicit CUDA/GPU context to avoid
# false positives from Java heap, Python MemoryError, or other non-GPU OOM logs.
OOM_PAT = re.compile(
    r"("
    r"CUDA\s+out\s+of\s+memory"                          # PyTorch classic
    r"|torch\.cuda\.OutOfMemoryError"                    # PyTorch >= 1.12
    r"|RuntimeError:.*(?:CUDA|GPU).*(?:memory|alloc)"   # RuntimeError with GPU context
    r"|cublas.*alloc\s+(?:failed|error)"                 # cuBLAS allocation failure
    r"|cufft.*alloc\s+(?:failed|error)"                  # cuFFT allocation failure
    r"|failed\s+to\s+allocate.*(?:GPU|CUDA|device)"      # generic GPU alloc failure
    r"|OOM\s+when\s+allocating"                          # TensorFlow / JAX style
    r"|out\s+of\s+memory\s+(?:on\s+device|on\s+GPU)"    # explicit device context
    r"|llama_model_load.*out\s+of\s+memory"              # llama.cpp / ollama specific
    r")",
    re.IGNORECASE,
)

def detect_oom_from_logs(container: str, since_utc_iso: str, max_lines: int = 4000) -> Tuple[bool, str]:
    """
    Returns (oom_detected, last_matching_line).
    """
    # docker logs writes to stderr by default; merge_stderr=True captures it
    out = run_cmd(["docker", "logs", "--since", since_utc_iso, container], timeout=10.0, merge_stderr=True)
    if not out:
        return False, ""

    # limit scan cost
    lines = out.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]

    last = ""
    found = False
    for ln in lines:
        if OOM_PAT.search(ln):
            found = True
            last = ln
    return found, last.strip()


def detect_oom_from_logs_result(container: str, since_utc_iso: str, max_lines: int = 4000) -> Tuple[bool, str, str]:
    result = run_cmd_result(["docker", "logs", "--since", since_utc_iso, container], timeout=10.0, merge_stderr=True)
    if result.timed_out:
        return False, "", f"docker logs timed out for {container}"
    if not result.ok:
        return False, "", classify_docker_error(result.stdout or result.stderr, container)
    out = result.stdout
    if not out:
        return False, "", ""

    lines = out.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]

    last = ""
    found = False
    for ln in lines:
        if OOM_PAT.search(ln):
            found = True
            last = ln
    return found, last.strip(), ""


# -------------------------
# Async snapshot collectors
# -------------------------
def collect_container(container: str, since_iso: str) -> ContainerReport:
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        f_cont = pool.submit(get_container_stats, container)
        f_ps = pool.submit(get_ollama_ps_result, container)
        f_oom = pool.submit(detect_oom_from_logs_result, container, since_iso)

        cont, stats_error = f_cont.result()
        ps_text, ps_error = f_ps.result()
        oom, oom_line, oom_error = f_oom.result()
        models = parse_ollama_ps(ps_text)

    status = "ok"
    errors = [err for err in [stats_error, ps_error, oom_error] if err]
    error = " | ".join(errors)
    if stats_error or ps_error:
        status = "error"
    elif not models:
        status = "idle"

    return ContainerReport(
        name=container,
        stats=cont,
        models=models,
        oom_detected=oom,
        oom_line=oom_line,
        status=status,
        stats_error=stats_error,
        ps_error=ps_error,
        oom_error=oom_error,
        error=error,
    )


def collect_all(
    containers: List[str], since_by_container: Dict[str, str]
) -> Tuple[List[GpuSnap], List[ContainerReport]]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(containers) + 1)) as pool:
        f_gpu = pool.submit(get_gpus)
        futures = [
            pool.submit(collect_container, container, since_by_container.get(container, iso_utc(time.time() - 2.0)))
            for container in containers
        ]
        gpus = f_gpu.result()
        reports = [f.result() for f in futures]
    return gpus, reports


# -------------------------
# CSV
# -------------------------
CSV_HEADER = [
    # baseline
    "host_ts","gpu_id","gpu_name","gpu_uuid","nv_ts",
    "gpu_util_pct","gpu_mem_util_pct","gpu_mem_used_MiB","gpu_mem_total_MiB","gpu_power_W","gpu_temp_C","gpu_sm_clock_MHz",
    # container + model
    "container_name","container_status","container_error",
    "model_name","model_id","model_size","model_processor_raw","model_context_pct","model_device_mix","model_context_tokens","model_until",
    # container
    "container_cpu_pct","container_mem_used","container_mem_limit","container_mem_pct","container_net_in","container_net_out","container_blk_in","container_blk_out","container_pids",
    # oom
    "oom_detected","oom_last_line"
]

def ensure_csv_header(path: str) -> None:
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            existing_header = next(reader, [])
        if existing_header == CSV_HEADER:
            return
        backup_path = f"{path}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        os.replace(path, backup_path)
        print(f"Existing CSV header mismatch; rotated old log to: {backup_path}")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)


def append_rows(path: str, rows: List[List[str]]) -> None:
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(rows)


def parse_output_modes(raw_value: str) -> List[str]:
    allowed = {"csv", "json", "prometheus"}
    modes: List[str] = []
    for part in raw_value.split(","):
        mode = part.strip().lower()
        if not mode:
            continue
        if mode == "all":
            return ["csv", "json", "prometheus"]
        if mode in allowed and mode not in modes:
            modes.append(mode)
    return modes or ["csv"]


def env_truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def parse_args(argv: Optional[List[str]] = None) -> AppConfig:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--log-file",
        default=os.environ.get("LOG_FILE", "ollama_gpu_per_model_log.csv"),
        help="CSV output path. Env fallback: LOG_FILE.",
    )
    shared.add_argument(
        "--json-file",
        default=os.environ.get("JSON_FILE", "ollama_gpu_per_model_snapshot.json"),
        help="JSON snapshot output path. Env fallback: JSON_FILE.",
    )
    shared.add_argument(
        "--prom-file",
        default=os.environ.get("PROM_FILE", "ollama_gpu_per_model.prom"),
        help="Prometheus text output path. Env fallback: PROM_FILE.",
    )
    shared.add_argument(
        "--output-mode",
        default=os.environ.get("OUTPUT_MODE", "csv"),
        help="Comma-separated outputs: csv,json,prometheus or all. Env fallback: OUTPUT_MODE.",
    )
    shared.add_argument(
        "--interval",
        type=float,
        default=float(os.environ.get("INTERVAL_S", "1")),
        help="Collection interval in seconds. Env fallback: INTERVAL_S.",
    )
    shared.add_argument(
        "--container",
        default=os.environ.get("OLLAMA_CONTAINER", "ollama").strip(),
        help="Specific Ollama container name, or auto/ollama/* for discovery. Env fallback: OLLAMA_CONTAINER.",
    )
    shared.add_argument(
        "--ansi",
        choices=["auto", "on", "off"],
        default=os.environ.get("ANSI", "auto").strip().lower() if os.environ.get("ANSI") else "auto",
        help="Terminal color mode. Env fallback: ANSI.",
    )
    shared.add_argument(
        "--metrics-http",
        action=argparse.BooleanOptionalAction,
        default=env_truthy("METRICS_HTTP"),
        help="Enable embedded HTTP endpoints /metrics, /health, /ready, /snapshot. Env fallback: METRICS_HTTP.",
    )
    shared.add_argument(
        "--metrics-http-host",
        default=os.environ.get("METRICS_HTTP_HOST", "127.0.0.1").strip(),
        help="HTTP listen host for embedded metrics server. Env fallback: METRICS_HTTP_HOST.",
    )
    shared.add_argument(
        "--metrics-http-port",
        type=int,
        default=int(os.environ.get("METRICS_HTTP_PORT", "9464")),
        help="HTTP listen port for embedded metrics server. Env fallback: METRICS_HTTP_PORT.",
    )

    parser = argparse.ArgumentParser(
        description="Monitor GPU, Ollama containers, loaded models, and OOM signals.",
    )
    subparsers = parser.add_subparsers(dest="command")
    serve_parser = subparsers.add_parser(
        "serve",
        parents=[shared],
        help="Run the continuous monitor loop.",
    )
    serve_parser.set_defaults(command="serve")
    snapshot_parser = subparsers.add_parser(
        "snapshot",
        parents=[shared],
        help="Collect one snapshot, write configured outputs, print once, then exit.",
    )
    snapshot_parser.set_defaults(command="snapshot")

    args_list = list(argv) if argv is not None else sys.argv[1:]
    if args_list in (["-h"], ["--help"]):
        parser.print_help()
        raise SystemExit(0)
    if not args_list or args_list[0].startswith("-"):
        args_list = ["serve", *args_list]

    args = parser.parse_args(args_list)
    if args.interval <= 0:
        raise SystemExit("ERROR: --interval must be greater than 0")
    if not (1 <= args.metrics_http_port <= 65535):
        raise SystemExit("ERROR: --metrics-http-port must be between 1 and 65535")

    if args.ansi == "auto":
        ansi_enabled = sys.stdout.isatty()
    else:
        ansi_enabled = args.ansi == "on"

    return AppConfig(
        command=args.command,
        log_file=args.log_file,
        json_file=args.json_file,
        prom_file=args.prom_file,
        output_modes=parse_output_modes(args.output_mode),
        metrics_http_enabled=args.metrics_http,
        metrics_http_host=args.metrics_http_host,
        metrics_http_port=args.metrics_http_port,
        interval_s=args.interval,
        requested_container=args.container,
        ansi_enabled=ansi_enabled,
    )


def build_json_payload(
    host_ts: str,
    requested_container: str,
    resolution_msg: Optional[str],
    gpus: List[GpuSnap],
    reports: List[ContainerReport],
) -> Dict[str, Any]:
    return {
        "host_ts": host_ts,
        "requested_container": requested_container,
        "discovery_message": resolution_msg,
        "gpus": [
            {
                "gpu_id": gpu.gpu_id,
                "gpu_name": gpu.gpu_name,
                "gpu_uuid": gpu.gpu_uuid,
                "nv_ts": gpu.nv_ts,
                "util_pct": gpu.util_pct,
                "mem_util_pct": gpu.mem_util_pct,
                "mem_used_mib": gpu.mem_used_mib,
                "mem_total_mib": gpu.mem_total_mib,
                "power_w": gpu.power_w,
                "temp_c": gpu.temp_c,
                "sm_clock_mhz": gpu.sm_clock_mhz,
            }
            for gpu in gpus
        ],
        "containers": [
            {
                "name": report.name,
                "status": report.status,
                "error": report.error,
                "stats_error": report.stats_error,
                "ps_error": report.ps_error,
                "oom_error": report.oom_error,
                "oom_detected": report.oom_detected,
                "oom_line": report.oom_line,
                "stats": {
                    "cpu_pct": report.stats.cpu_pct,
                    "mem_used": report.stats.mem_used,
                    "mem_limit": report.stats.mem_limit,
                    "mem_pct": report.stats.mem_pct,
                    "net_in": report.stats.net_in,
                    "net_out": report.stats.net_out,
                    "blk_in": report.stats.blk_in,
                    "blk_out": report.stats.blk_out,
                    "pids": report.stats.pids,
                },
                "models": [
                    {
                        "name": model.name,
                        "model_id": model.model_id,
                        "size": model.size,
                        "processor_raw": model.processor_raw,
                        "ctx_pct": model.ctx_pct,
                        "device_mix": model.device_mix,
                        "ctx": model.ctx,
                        "until": model.until,
                    }
                    for model in report.models
                ],
            }
            for report in reports
        ],
    }


def write_json_snapshot(path: str, payload: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, indent=2)
        f.write("\n")


def prom_sanitize_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def parse_metric_number(value: str) -> Optional[float]:
    if not value:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_size_to_bytes(value: str) -> Optional[float]:
    if not value:
        return None
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*([kmgtp]?i?b)", value.strip(), re.IGNORECASE)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2).lower()
    multipliers = {
        "b": 1,
        "kb": 1000 ** 1,
        "mb": 1000 ** 2,
        "gb": 1000 ** 3,
        "tb": 1000 ** 4,
        "pb": 1000 ** 5,
        "kib": 1024 ** 1,
        "mib": 1024 ** 2,
        "gib": 1024 ** 3,
        "tib": 1024 ** 4,
        "pib": 1024 ** 5,
    }
    multiplier = multipliers.get(unit)
    if multiplier is None:
        return None
    return amount * multiplier


def parse_until_to_seconds(value: str) -> Optional[float]:
    if not value:
        return None
    text = value.strip().lower()
    if text in ("now", "just now"):
        return 0.0
    if "from now" in text:
        sign = 1
    elif "ago" in text:
        sign = -1
    else:
        sign = 1

    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(second|minute|hour|day|week|month|year)s?", text)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2)
    factors = {
        "second": 1,
        "minute": 60,
        "hour": 3600,
        "day": 86400,
        "week": 604800,
        "month": 2592000,
        "year": 31536000,
    }
    return sign * amount * factors[unit]


def to_error_type(value: str) -> str:
    text = (value or "").strip().lower()
    if not text:
        return "none"
    normalized = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    if "docker_socket_permission_denied" in normalized:
        return "docker_socket_permission_denied"
    if "docker_daemon_unreachable" in normalized:
        return "docker_daemon_unreachable"
    if "container_not_found" in normalized:
        return "container_not_found"
    if "container_not_running" in normalized:
        return "container_not_running"
    if "ollama_ps_timed_out" in normalized:
        return "ollama_ps_timed_out"
    if "ollama_ps_failed" in normalized:
        return "ollama_ps_failed"
    if "docker_logs_timed_out" in normalized:
        return "docker_logs_timed_out"
    if "docker_stats_returned_no_data" in normalized:
        return "docker_stats_no_data"
    return normalized or "unknown"


def build_prometheus_text(gpus: List[GpuSnap], reports: List[ContainerReport]) -> str:
    lines = [
        "# HELP gpu_monitor_gpu_util_percent GPU utilization percent.",
        "# TYPE gpu_monitor_gpu_util_percent gauge",
        "# HELP gpu_monitor_gpu_mem_util_percent GPU memory utilization percent.",
        "# TYPE gpu_monitor_gpu_mem_util_percent gauge",
        "# HELP gpu_monitor_gpu_mem_used_mib GPU memory used in MiB.",
        "# TYPE gpu_monitor_gpu_mem_used_mib gauge",
        "# HELP gpu_monitor_gpu_mem_total_mib GPU memory total in MiB.",
        "# TYPE gpu_monitor_gpu_mem_total_mib gauge",
        "# HELP gpu_monitor_gpu_power_watts GPU power draw in watts.",
        "# TYPE gpu_monitor_gpu_power_watts gauge",
        "# HELP gpu_monitor_gpu_temp_celsius GPU temperature in Celsius.",
        "# TYPE gpu_monitor_gpu_temp_celsius gauge",
        "# HELP gpu_monitor_gpu_sm_clock_mhz GPU SM clock in MHz.",
        "# TYPE gpu_monitor_gpu_sm_clock_mhz gauge",
    ]
    for gpu in gpus:
        gpu_id = prom_sanitize_label_value(gpu.gpu_id or "unknown")
        gpu_name = prom_sanitize_label_value(gpu.gpu_name or "unknown")
        gpu_uuid = prom_sanitize_label_value(gpu.gpu_uuid or "unknown")
        labels = f'gpu_id="{gpu_id}",gpu_name="{gpu_name}",gpu_uuid="{gpu_uuid}"'
        metrics = {
            "gpu_monitor_gpu_util_percent": parse_metric_number(gpu.util_pct),
            "gpu_monitor_gpu_mem_util_percent": parse_metric_number(gpu.mem_util_pct),
            "gpu_monitor_gpu_mem_used_mib": parse_metric_number(gpu.mem_used_mib),
            "gpu_monitor_gpu_mem_total_mib": parse_metric_number(gpu.mem_total_mib),
            "gpu_monitor_gpu_power_watts": parse_metric_number(gpu.power_w),
            "gpu_monitor_gpu_temp_celsius": parse_metric_number(gpu.temp_c),
            "gpu_monitor_gpu_sm_clock_mhz": parse_metric_number(gpu.sm_clock_mhz),
        }
        for metric_name, metric_value in metrics.items():
            if metric_value is not None:
                lines.append(f'{metric_name}{{{labels}}} {metric_value}')

    lines.extend([
        "# HELP gpu_monitor_container_status Container status encoded as 1=ok, 0=idle, -1=error.",
        "# TYPE gpu_monitor_container_status gauge",
        "# HELP gpu_monitor_container_cpu_percent Container CPU usage percent.",
        "# TYPE gpu_monitor_container_cpu_percent gauge",
        "# HELP gpu_monitor_container_mem_percent Container memory usage percent.",
        "# TYPE gpu_monitor_container_mem_percent gauge",
        "# HELP gpu_monitor_container_pids Container process count.",
        "# TYPE gpu_monitor_container_pids gauge",
        "# HELP gpu_monitor_container_models_loaded Number of loaded models in the container.",
        "# TYPE gpu_monitor_container_models_loaded gauge",
        "# HELP gpu_monitor_container_oom_detected Whether OOM was detected in recent logs.",
        "# TYPE gpu_monitor_container_oom_detected gauge",
        "# HELP gpu_monitor_container_error_state Container error state by source and error type.",
        "# TYPE gpu_monitor_container_error_state gauge",
        "# HELP gpu_monitor_model_loaded Whether a model is currently loaded in the container.",
        "# TYPE gpu_monitor_model_loaded gauge",
        "# HELP gpu_monitor_model_context_tokens Model context tokens.",
        "# TYPE gpu_monitor_model_context_tokens gauge",
        "# HELP gpu_monitor_model_context_percent Model context percent.",
        "# TYPE gpu_monitor_model_context_percent gauge",
        "# HELP gpu_monitor_model_size_bytes Model size in bytes.",
        "# TYPE gpu_monitor_model_size_bytes gauge",
        "# HELP gpu_monitor_model_until_seconds Seconds until the model unload horizon; negative means already in the past.",
        "# TYPE gpu_monitor_model_until_seconds gauge",
    ])
    for report in reports:
        labels = f'container_name="{prom_sanitize_label_value(report.name)}"'
        status_value = 1 if report.status == "ok" else 0 if report.status == "idle" else -1
        lines.append(f"gpu_monitor_container_status{{{labels}}} {status_value}")
        for metric_name, metric_value in {
            "gpu_monitor_container_cpu_percent": parse_metric_number(report.stats.cpu_pct),
            "gpu_monitor_container_mem_percent": parse_metric_number(report.stats.mem_pct),
            "gpu_monitor_container_pids": parse_metric_number(report.stats.pids),
            "gpu_monitor_container_models_loaded": float(len(report.models)),
            "gpu_monitor_container_oom_detected": 1.0 if report.oom_detected else 0.0,
        }.items():
            if metric_value is not None:
                lines.append(f"{metric_name}{{{labels}}} {metric_value}")

        error_sources = {
            "stats": report.stats_error,
            "ps": report.ps_error,
            "oom": report.oom_error,
        }
        for source, error_text in error_sources.items():
            error_type = to_error_type(error_text)
            error_labels = (
                f'container_name="{prom_sanitize_label_value(report.name)}",'
                f'source="{prom_sanitize_label_value(source)}",'
                f'error_type="{prom_sanitize_label_value(error_type)}"'
            )
            lines.append(
                f"gpu_monitor_container_error_state{{{error_labels}}} {0 if error_type == 'none' else 1}"
            )

        for model in report.models:
            model_labels = (
                f'container_name="{prom_sanitize_label_value(report.name)}",'
                f'model_name="{prom_sanitize_label_value(model.name)}",'
                f'model_id="{prom_sanitize_label_value(model.model_id)}",'
                f'device_mix="{prom_sanitize_label_value(model.device_mix)}"'
            )
            lines.append(f"gpu_monitor_model_loaded{{{model_labels}}} 1")

            ctx_tokens = parse_metric_number(model.ctx)
            if ctx_tokens is not None:
                lines.append(f"gpu_monitor_model_context_tokens{{{model_labels}}} {ctx_tokens}")

            ctx_pct = parse_metric_number(model.ctx_pct)
            if ctx_pct is not None:
                lines.append(f"gpu_monitor_model_context_percent{{{model_labels}}} {ctx_pct}")

            size_bytes = parse_size_to_bytes(model.size)
            if size_bytes is not None:
                lines.append(f"gpu_monitor_model_size_bytes{{{model_labels}}} {size_bytes}")

            until_seconds = parse_until_to_seconds(model.until)
            if until_seconds is not None:
                lines.append(f"gpu_monitor_model_until_seconds{{{model_labels}}} {until_seconds}")

    return "\n".join(lines) + "\n"


def write_prometheus_snapshot(path: str, gpus: List[GpuSnap], reports: List[ContainerReport]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_prometheus_text(gpus, reports))


def build_health_payload(
    host_ts: str,
    requested_container: str,
    resolution_msg: Optional[str],
    reports: List[ContainerReport],
) -> Dict[str, Any]:
    error_count = sum(1 for report in reports if report.status == "error")
    ok_count = sum(1 for report in reports if report.status == "ok")
    idle_count = sum(1 for report in reports if report.status == "idle")
    overall_status = "ok" if error_count == 0 else "degraded"
    return {
        "host_ts": host_ts,
        "requested_container": requested_container,
        "discovery_message": resolution_msg,
        "status": overall_status,
        "containers_total": len(reports),
        "containers_ok": ok_count,
        "containers_idle": idle_count,
        "containers_error": error_count,
        "containers": [
            {
                "name": report.name,
                "status": report.status,
                "error": report.error,
            }
            for report in reports
        ],
    }


def build_ready_payload(
    host_ts: str,
    requested_container: str,
    resolution_msg: Optional[str],
    reports: List[ContainerReport],
) -> Tuple[int, Dict[str, Any]]:
    usable_count = sum(1 for report in reports if report.status in ("ok", "idle"))
    error_count = sum(1 for report in reports if report.status == "error")
    ready = usable_count > 0
    status_code = 200 if ready else 503
    payload = {
        "host_ts": host_ts,
        "requested_container": requested_container,
        "discovery_message": resolution_msg,
        "ready": ready,
        "usable_containers": usable_count,
        "error_containers": error_count,
        "containers_total": len(reports),
    }
    return status_code, payload


def start_http_server(host: str, port: int, state: SharedSnapshotState) -> ThreadingHTTPServer:
    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/metrics":
                with state.lock:
                    payload = state.prometheus_text or ""
                body = payload.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/health":
                with state.lock:
                    payload = state.health_payload or {"status": "starting"}
                body = (json.dumps(payload, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/snapshot":
                with state.lock:
                    payload = state.json_payload or {"status": "starting"}
                body = (json.dumps(payload, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/ready":
                with state.lock:
                    payload = state.ready_payload or {"ready": False, "status": "starting"}
                status_code = int(payload.get("status_code", 503))
                body_payload = {k: v for k, v in payload.items() if k != "status_code"}
                body = (json.dumps(body_payload, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"not found\n")

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), MetricsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# -------------------------
# Main loop
# -------------------------
def clear_screen() -> None:
    # avoid external clear; use ANSI if possible
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def main() -> int:
    config = parse_args()
    run_forever = config.command == "serve"
    log_file = config.log_file
    json_file = config.json_file
    prom_file = config.prom_file
    output_modes = config.output_modes
    metrics_http_enabled = config.metrics_http_enabled
    metrics_http_host = config.metrics_http_host
    metrics_http_port = config.metrics_http_port
    interval_s = config.interval_s
    requested_container = config.requested_container
    A = ANSI(config.ansi_enabled)
    shared_state = SharedSnapshotState(lock=threading.Lock())
    http_server: Optional[ThreadingHTTPServer] = None

    # dependencies
    which_or_die("docker")
    which_or_die("nvidia-smi")

    containers, resolution_msg = resolve_ollama_containers(requested_container)
    if "csv" in output_modes:
        ensure_csv_header(log_file)

    print(f"Output modes: {', '.join(output_modes)}")
    if "csv" in output_modes:
        print(f"CSV file: {log_file}")
    if "json" in output_modes:
        print(f"JSON file: {json_file}")
    try:
        if "prometheus" in output_modes:
            print(f"Prometheus file: {prom_file}")
        if metrics_http_enabled:
            http_server = start_http_server(metrics_http_host, metrics_http_port, shared_state)
            print(f"Metrics HTTP: http://{metrics_http_host}:{metrics_http_port}/metrics")
            print(f"Health HTTP : http://{metrics_http_host}:{metrics_http_port}/health")
            print(f"Ready HTTP  : http://{metrics_http_host}:{metrics_http_port}/ready")
            print(f"Snapshot HTTP: http://{metrics_http_host}:{metrics_http_port}/snapshot")
        print(f"Interval: {interval_s}s | Target: {requested_container}")
        print(f"Command: {config.command}")
        if resolution_msg:
            print(resolution_msg)
        if run_forever:
            print("Press Ctrl+C to stop.")
            time.sleep(0.8)

        last_log_check_ts: Dict[str, float] = {
            container: time.time() - max(2.0, interval_s)
            for container in containers
        }

        while True:
            host_ts = now_local_str()
            tick_started_ts = time.time()
            containers, resolution_msg = resolve_ollama_containers(requested_container)
            for container in containers:
                last_log_check_ts.setdefault(container, tick_started_ts - max(2.0, interval_s))

            since_by_container = {
                container: iso_utc(last_log_check_ts.get(container, tick_started_ts - max(2.0, interval_s)))
                for container in containers
            }
            gpus, reports = collect_all(containers, since_by_container)
            for container in containers:
                # Advance the next log cursor to the start of this tick so logs emitted
                # while collectors are still running are re-scanned instead of skipped.
                last_log_check_ts[container] = tick_started_ts

            # terminal dashboard
            if sys.stdout.isatty():
                clear_screen()
            print(f"{A.CYAN}{A.BOLD}╔══════════════════════════════════════════════════════════════╗{A.RESET}")
            print(f"{A.CYAN}{A.BOLD}║            █  SAWIT.tech LOCAL AI DEVOPS LAB  █              ║{A.RESET}")
            print(f"{A.CYAN}{A.BOLD}║        GPU / LLM / CONTAINER OBSERVABILITY (PY)              ║{A.RESET}")
            print(f"{A.CYAN}{A.BOLD}╚══════════════════════════════════════════════════════════════╝{A.RESET}")
            print(f"{A.GRAY}Time{A.RESET}          : {A.BOLD}{host_ts}{A.RESET}")
            if resolution_msg:
                print(f"{A.GRAY}Discovery{A.RESET}     : {resolution_msg}")
            oom_reports = [r for r in reports if r.oom_detected]
            if oom_reports:
                for report in oom_reports[:3]:
                    print(f"{A.RED}{A.BOLD}OOM DETECTED{A.RESET} : {report.name} | {A.RED}{strip_ansi(report.oom_line)[:180]}{A.RESET}")
            else:
                print(f"{A.GRAY}OOM DETECTED{A.RESET}  : no")
            print()

            # GPU block
            print(f"{A.MAGENTA}{A.BOLD}GPUS{A.RESET}")
            for gpu in gpus:
                util_i = try_int(gpu.util_pct, 0)
                temp_i = try_int(gpu.temp_c, 0)
                mem_used_i = try_int(gpu.mem_used_mib, 0)
                mem_total_i = max(1, try_int(gpu.mem_total_mib, 1))
                mem_pct = int(mem_used_i * 100 / mem_total_i)
                gpu_label = gpu.gpu_id or "?"
                gpu_name = gpu.gpu_name or "-"
                print(f"  GPU {gpu_label} ({gpu_name})")
                print(f"    Util      : {A.pct_color(util_i)}{gpu.util_pct or '-'} %{A.RESET}")
                print(f"    VRAM      : {A.pct_color(mem_pct)}{gpu.mem_used_mib or '-'} / {gpu.mem_total_mib or '-'} MiB{A.RESET}")
                print(f"    Power     : {A.YELLOW}{gpu.power_w or '-'} W{A.RESET}")
                print(f"    Temp      : {A.temp_color(temp_i)}{gpu.temp_c or '-'} °C{A.RESET}")
                print(f"    SM Clock  : {A.CYAN}{gpu.sm_clock_mhz or '-'} MHz{A.RESET}")
            print()

            csv_rows: List[List[str]] = []
            print(f"{A.MAGENTA}{A.BOLD}OLLAMA CONTAINERS{A.RESET} {A.GRAY}(one row per model per container; Grafana/Postgres ready){A.RESET}")
            for report in reports:
                cont = report.stats
                status_color = A.GREEN if report.status == "ok" else A.YELLOW if report.status == "idle" else A.RED
                print(f"{A.GRAY}{'─'*94}{A.RESET}")
                print(f"{A.MAGENTA}{A.BOLD}CONTAINER ({report.name}){A.RESET}  status={status_color}{report.status}{A.RESET}")
                if report.stats_error:
                    print(f"  Stats Error : {A.RED}{report.stats_error}{A.RESET}")
                if report.ps_error:
                    print(f"  PS Error    : {A.RED}{report.ps_error}{A.RESET}")
                if report.oom_error:
                    print(f"  OOM Error   : {A.RED}{report.oom_error}{A.RESET}")
                print(f"  CPU         : {A.CYAN}{format_container_cpu(cont.cpu_pct)}{A.RESET}")
                print(f"  RAM         : {A.CYAN}{cont.mem_used or '-'} / {cont.mem_limit or '-'}{A.RESET} ({A.YELLOW}{cont.mem_pct or '-'} %{A.RESET})")
                print(f"  Net I/O     : {A.GRAY}{cont.net_in or '-'} / {cont.net_out or '-'}{A.RESET}")
                print(f"  Block I/O   : {A.GRAY}{cont.blk_in or '-'} / {cont.blk_out or '-'}{A.RESET}")
                print(f"  PIDs        : {A.GRAY}{cont.pids or '-'}{A.RESET}")
                if report.oom_detected:
                    print(f"  OOM         : {A.RED}{strip_ansi(report.oom_line)[:180]}{A.RESET}")
                else:
                    print(f"  OOM         : no")
                print(f"{'NAME':34} {'CTX':8} {'SIZE':8} {'PROCESSOR':18} {'CTX_PCT':12} {'DEVICE':10} {'UNTIL':22}")
                if not report.models:
                    model_label = "ERROR" if report.status == "error" else "NONE"
                    ctx_label = "0"
                    size_label = "-"
                    proc_label = "-"
                    pct_label = "0%/100%"
                    device_label = "-"
                    until_label = report.status
                    print(f"{model_label[:34]:34} {ctx_label:8} {size_label:8} {proc_label:18} {pct_label:12} {device_label:10} {until_label[:22]:22}")
                    for gpu in gpus:
                        csv_rows.append([
                            host_ts, gpu.gpu_id, gpu.gpu_name, gpu.gpu_uuid, gpu.nv_ts,
                            gpu.util_pct, gpu.mem_util_pct, gpu.mem_used_mib, gpu.mem_total_mib, gpu.power_w, gpu.temp_c, gpu.sm_clock_mhz,
                            report.name, report.status, report.error,
                            model_label, "", "", "", "0%/100%", "", "0", report.status,
                            cont.cpu_pct, cont.mem_used, cont.mem_limit, cont.mem_pct, cont.net_in, cont.net_out, cont.blk_in, cont.blk_out, cont.pids,
                            "1" if report.oom_detected else "0", report.oom_line[:500],
                        ])
                    continue

                for m in report.models:
                    ctx_int = try_int(m.ctx_pct.replace("%","").split("/")[0], 0) if m.ctx_pct else 0
                    row_color = A.CYAN
                    if "CPU" in (m.device_mix or ""):
                        row_color = A.MAGENTA
                    if ctx_int >= 90:
                        row_color = A.RED
                    print(f"{row_color}{m.name[:34]:34}{A.RESET} {m.ctx[:8]:8} {m.size[:8]:8} {m.processor_raw[:18]:18} {m.ctx_pct[:12]:12} {m.device_mix[:10]:10} {m.until[:22]:22}")
                    if sys.stdout.isatty():
                        print(f"  {A.GRAY}ctx{A.RESET} {A.progress_bar(ctx_int, 24)}")
                    for gpu in gpus:
                        csv_rows.append([
                            host_ts, gpu.gpu_id, gpu.gpu_name, gpu.gpu_uuid, gpu.nv_ts,
                            gpu.util_pct, gpu.mem_util_pct, gpu.mem_used_mib, gpu.mem_total_mib, gpu.power_w, gpu.temp_c, gpu.sm_clock_mhz,
                            report.name, report.status, report.error,
                            m.name, m.model_id, m.size, m.processor_raw, m.ctx_pct, m.device_mix, m.ctx, m.until,
                            cont.cpu_pct, cont.mem_used, cont.mem_limit, cont.mem_pct, cont.net_in, cont.net_out, cont.blk_in, cont.blk_out, cont.pids,
                            "1" if report.oom_detected else "0", report.oom_line[:500],
                        ])

            print(f"{A.GRAY}{'─'*94}{A.RESET}")
            print(f"{A.GRAY}Next tick in {interval_s}s{A.RESET}")

            json_payload = build_json_payload(host_ts, requested_container, resolution_msg, gpus, reports)
            prom_text = build_prometheus_text(gpus, reports)
            health_payload = build_health_payload(host_ts, requested_container, resolution_msg, reports)
            ready_status_code, ready_payload = build_ready_payload(host_ts, requested_container, resolution_msg, reports)
            ready_payload["status_code"] = ready_status_code
            with shared_state.lock:
                shared_state.prometheus_text = prom_text
                shared_state.health_payload = health_payload
                shared_state.json_payload = json_payload
                shared_state.ready_payload = ready_payload
            if "csv" in output_modes:
                append_rows(log_file, csv_rows)
            if "json" in output_modes:
                write_json_snapshot(json_file, json_payload)
            if "prometheus" in output_modes:
                with open(prom_file, "w", encoding="utf-8") as f:
                    f.write(prom_text)
            if not run_forever:
                return 0
            time.sleep(interval_s)
    finally:
        shutdown_http_server(http_server)

    return 0


def shutdown_http_server(server: Optional[ThreadingHTTPServer]) -> None:
    if server is None:
        return
    server.shutdown()
    server.server_close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        raise SystemExit(0)
