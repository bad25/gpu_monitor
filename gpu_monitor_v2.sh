#!/usr/bin/env bash
set -euo pipefail

# ============================================================
#  LOCAL AI DEVOPS LAB MONITOR (Hacker Aesthetic + DevOps)
#  - One CSV row per model per interval (Grafana/Postgres-ready)
#  - Live terminal dashboard with colors + progress bars
#  - Sources:
#     * GPU: nvidia-smi (host)
#     * Container: docker stats (ollama container)
#     * Models: docker exec ollama ollama ps (robust column parsing)
#
#  Usage:
#    chmod +x monitor_ollama_gpu_per_model.sh
#    ./monitor_ollama_gpu_per_model.sh
#
#  Env overrides:
#    LOG_FILE=ollama_gpu_per_model_log.csv
#    INTERVAL_S=1
#    OLLAMA_CONTAINER=ollama
#
#  Stop:
#    Ctrl+C
# ============================================================

LOG_FILE="${LOG_FILE:-ollama_gpu_per_model_log.csv}"
INTERVAL_S="${INTERVAL_S:-1}"
OLLAMA_CONTAINER="${OLLAMA_CONTAINER:-ollama}"

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: missing: $1" >&2; exit 1; }; }
need_cmd nvidia-smi
need_cmd docker
need_cmd awk
need_cmd sed
need_cmd head
need_cmd date
need_cmd printf
need_cmd tput

trim() { sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//'; }

# ----- colors (256-color) -----
RED="\033[38;5;196m"
GREEN="\033[38;5;46m"
YELLOW="\033[38;5;226m"
CYAN="\033[38;5;51m"
MAGENTA="\033[38;5;201m"
GRAY="\033[38;5;240m"
RESET="\033[0m"
BOLD="\033[1m"

# If not a TTY, disable ANSI colors for clean logs (optional)
if ! [ -t 1 ]; then
  RED=""; GREEN=""; YELLOW=""; CYAN=""; MAGENTA=""; GRAY=""; RESET=""; BOLD=""
fi

progress_bar() {
  # progress_bar <pct> [width]
  local pct="${1:-0}"
  local width="${2:-24}"
  local filled=$(( pct * width / 100 ))
  local empty=$(( width - filled ))

  printf "["
  for ((i=0;i<filled;i++)); do printf "█"; done
  for ((i=0;i<empty;i++)); do printf "░"; done
  printf "] %3d%%" "$pct"
}

pct_color() {
  # pct_color <pct_int> -> prints ANSI color
  local p="${1:-0}"
  if (( p >= 90 )); then printf "%s" "$RED"
  elif (( p >= 75 )); then printf "%s" "$YELLOW"
  else printf "%s" "$GREEN"
  fi
}

temp_color() {
  local t="${1:-0}"
  if (( t >= 85 )); then printf "%s" "$RED"
  elif (( t >= 78 )); then printf "%s" "$YELLOW"
  else printf "%s" "$GREEN"
  fi
}

mem_color_by_ratio() {
  # mem_color_by_ratio used total -> based on %
  local used="${1:-0}"
  local total="${2:-1}"
  local pct=0
  if [[ "$used" =~ ^[0-9]+$ ]] && [[ "$total" =~ ^[0-9]+$ ]] && (( total > 0 )); then
    pct=$(( used * 100 / total ))
  fi
  pct_color "$pct"
}

# ----- CSV header (long/tidy format: one row per model) -----
# model_processor_raw: exactly as in `ollama ps` PROCESSOR column (e.g. "7%/93% CPU/GPU" or "100% GPU")
# model_context_pct: first token of processor_raw (e.g. "7%/93%" or "100%")
# model_device_mix: remaining tokens (e.g. "CPU/GPU" or "GPU")
# model_context_tokens: CONTEXT column (e.g. 4096)
# model_until: UNTIL column (e.g. "4 minutes from now")
echo "host_ts,nv_ts,gpu_util_pct,gpu_mem_util_pct,gpu_mem_used_MiB,gpu_mem_total_MiB,gpu_power_W,gpu_temp_C,gpu_sm_clock_MHz,model_name,model_id,model_size,model_processor_raw,model_context_pct,model_device_mix,model_context_tokens,model_until,container_cpu_pct,container_mem_used,container_mem_limit,container_mem_pct,container_net_in,container_net_out,container_blk_in,container_blk_out,container_pids" > "$LOG_FILE"

echo "Logging to: $LOG_FILE"
echo "Interval: ${INTERVAL_S}s | Container: ${OLLAMA_CONTAINER}"
echo "Press Ctrl+C to stop."
sleep 1

while true; do
  HOST_TS="$(date +"%Y-%m-%d %H:%M:%S")"

  # ---- GPU snapshot ----
  GPU_LINE="$(nvidia-smi \
    --query-gpu=timestamp,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,temperature.gpu,clocks.sm \
    --format=csv,noheader,nounits 2>/dev/null | head -n1 || true)"

  if [ -z "${GPU_LINE:-}" ]; then
    GPU_LINE=",,,,,,,"  # nv_ts + 7 fields
  fi

  IFS=',' read -r NV_TS GPU_UTIL GPU_MEM_UTIL GPU_MEM_USED GPU_MEM_TOTAL GPU_POWER GPU_TEMP GPU_SM_CLOCK <<< "$GPU_LINE"
  NV_TS="$(printf "%s" "${NV_TS:-}" | trim)"
  GPU_UTIL="$(printf "%s" "${GPU_UTIL:-}" | trim)"
  GPU_MEM_UTIL="$(printf "%s" "${GPU_MEM_UTIL:-}" | trim)"
  GPU_MEM_USED="$(printf "%s" "${GPU_MEM_USED:-}" | trim)"
  GPU_MEM_TOTAL="$(printf "%s" "${GPU_MEM_TOTAL:-}" | trim)"
  GPU_POWER="$(printf "%s" "${GPU_POWER:-}" | trim)"
  GPU_TEMP="$(printf "%s" "${GPU_TEMP:-}" | trim)"
  GPU_SM_CLOCK="$(printf "%s" "${GPU_SM_CLOCK:-}" | trim)"

  # numeric for coloring (best-effort)
  GPU_UTIL_INT="${GPU_UTIL%%.*}"; GPU_UTIL_INT="${GPU_UTIL_INT//[^0-9]/}"
  GPU_TEMP_INT="${GPU_TEMP%%.*}"; GPU_TEMP_INT="${GPU_TEMP_INT//[^0-9]/}"
  GPU_MEM_USED_INT="${GPU_MEM_USED%%.*}"; GPU_MEM_USED_INT="${GPU_MEM_USED_INT//[^0-9]/}"
  GPU_MEM_TOTAL_INT="${GPU_MEM_TOTAL%%.*}"; GPU_MEM_TOTAL_INT="${GPU_MEM_TOTAL_INT//[^0-9]/}"

  # ---- docker stats ----
  DSTATS="$(docker stats --no-stream \
    --format '{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}},{{.BlockIO}},{{.PIDs}}' \
    "$OLLAMA_CONTAINER" 2>/dev/null || true)"

  if [ -n "$DSTATS" ]; then
    IFS=',' read -r C_CPU C_MEMUSAGE C_MEMPERC C_NETIO C_BLKIO C_PIDS <<< "$DSTATS"

    C_CPU="${C_CPU/\%/}"; C_CPU="$(printf "%s" "${C_CPU:-}" | trim)"
    C_MEMPERC="${C_MEMPERC/\%/}"; C_MEMPERC="$(printf "%s" "${C_MEMPERC:-}" | trim)"
    C_PIDS="$(printf "%s" "${C_PIDS:-}" | trim)"

    C_MEM_USED="$(printf "%s" "$C_MEMUSAGE" | awk -F' / ' '{print $1}' | trim)"
    C_MEM_LIMIT="$(printf "%s" "$C_MEMUSAGE" | awk -F' / ' '{print $2}' | trim)"

    C_NET_IN="$(printf "%s" "$C_NETIO" | awk -F' / ' '{print $1}' | trim)"
    C_NET_OUT="$(printf "%s" "$C_NETIO" | awk -F' / ' '{print $2}' | trim)"

    C_BLK_IN="$(printf "%s" "$C_BLKIO" | awk -F' / ' '{print $1}' | trim)"
    C_BLK_OUT="$(printf "%s" "$C_BLKIO" | awk -F' / ' '{print $2}' | trim)"
  else
    C_CPU=""; C_MEM_USED=""; C_MEM_LIMIT=""; C_MEMPERC=""; C_NET_IN=""; C_NET_OUT=""; C_BLK_IN=""; C_BLK_OUT=""; C_PIDS=""
  fi

  # ---- ollama ps ----
  PS_OUTPUT="$(docker exec "$OLLAMA_CONTAINER" ollama ps 2>/dev/null || true)"

  # ---- terminal dashboard ----
  clear
  echo -e "${CYAN}${BOLD}"
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║            █  SAWITH.TECH LOCAL AI DEVOPS LAB  █             ║"
  echo "║            GPU / LLM / CONTAINER OBSERVABILITY               ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo -e "${RESET}"

  echo -e "${GRAY}Time${RESET}          : ${BOLD}${HOST_TS}${RESET}"
  echo

  # GPU block
  GPU_UTIL_CLR="$(pct_color "${GPU_UTIL_INT:-0}")"
  GPU_TEMP_CLR="$(temp_color "${GPU_TEMP_INT:-0}")"
  GPU_MEM_CLR="$(mem_color_by_ratio "${GPU_MEM_USED_INT:-0}" "${GPU_MEM_TOTAL_INT:-1}")"

  echo -e "${MAGENTA}${BOLD}GPU${RESET}"
  echo -e "  Util        : ${GPU_UTIL_CLR}${GPU_UTIL:-} %${RESET}"
  echo -e "  VRAM        : ${GPU_MEM_CLR}${GPU_MEM_USED:-} / ${GPU_MEM_TOTAL:-} MiB${RESET}"
  echo -e "  Power       : ${YELLOW}${GPU_POWER:-} W${RESET}"
  echo -e "  Temp        : ${GPU_TEMP_CLR}${GPU_TEMP:-} °C${RESET}"
  echo -e "  SM Clock    : ${CYAN}${GPU_SM_CLOCK:-} MHz${RESET}"
  echo

  # Container block
  echo -e "${MAGENTA}${BOLD}CONTAINER (${OLLAMA_CONTAINER})${RESET}"
  echo -e "  CPU         : ${CYAN}${C_CPU:-} %${RESET}"
  echo -e "  RAM         : ${CYAN}${C_MEM_USED:-} / ${C_MEM_LIMIT:-}${RESET} (${YELLOW}${C_MEMPERC:-} %${RESET})"
  echo -e "  Net I/O     : ${GRAY}${C_NET_IN:-} / ${C_NET_OUT:-}${RESET}"
  echo -e "  Block I/O   : ${GRAY}${C_BLK_IN:-} / ${C_BLK_OUT:-}${RESET}"
  echo -e "  PIDs        : ${GRAY}${C_PIDS:-}${RESET}"
  echo

  echo -e "${MAGENTA}${BOLD}OLLAMA MODELS${RESET} ${GRAY}(one row per model; Grafana/Postgres ready)${RESET}"
  echo -e "${GRAY}──────────────────────────────────────────────────────────────────────────────────────────────${RESET}"
  printf "%-34s %-8s %-8s %-18s %-12s %-10s %-22s\n" "NAME" "CTX" "SIZE" "PROCESSOR" "CTX_PCT" "DEVICE" "UNTIL"
  echo -e "${GRAY}──────────────────────────────────────────────────────────────────────────────────────────────${RESET}"

  # If empty/only header => write ONE row with NONE (still time-series consistent)
  if [ -z "${PS_OUTPUT:-}" ] || [ "$(printf "%s\n" "$PS_OUTPUT" | awk 'END{print NR}')" -le 1 ]; then
    printf "%-34s %-8s %-8s %-18s %-12s %-10s %-22s\n" "NONE" "0" "-" "-" "0%/100%" "-" "-"
    echo "$HOST_TS,$NV_TS,$GPU_UTIL,$GPU_MEM_UTIL,$GPU_MEM_USED,$GPU_MEM_TOTAL,$GPU_POWER,$GPU_TEMP,$GPU_SM_CLOCK,NONE,,,,0%/100%,,0,,$C_CPU,\"$C_MEM_USED\",\"$C_MEM_LIMIT\",$C_MEMPERC,\"$C_NET_IN\",\"$C_NET_OUT\",\"$C_BLK_IN\",\"$C_BLK_OUT\",$C_PIDS" >> "$LOG_FILE"
    sleep "$INTERVAL_S"
    continue
  fi

  # Parse each model row and:
  #  - print to terminal (colored)
  #  - append CSV (one row per model)
  printf "%s\n" "$PS_OUTPUT" | awk -v host_ts="$HOST_TS" \
    -v nv_ts="$NV_TS" -v gpu_util="$GPU_UTIL" -v gpu_mem_util="$GPU_MEM_UTIL" \
    -v gpu_mem_used="$GPU_MEM_USED" -v gpu_mem_total="$GPU_MEM_TOTAL" -v gpu_power="$GPU_POWER" \
    -v gpu_temp="$GPU_TEMP" -v gpu_sm="$GPU_SM_CLOCK" \
    -v c_cpu="$C_CPU" -v c_mem_used="$C_MEM_USED" -v c_mem_limit="$C_MEM_LIMIT" -v c_mem_pct="$C_MEMPERC" \
    -v c_net_in="$C_NET_IN" -v c_net_out="$C_NET_OUT" -v c_blk_in="$C_BLK_IN" -v c_blk_out="$C_BLK_OUT" \
    -v c_pids="$C_PIDS" \
    -v log_file="$LOG_FILE" '
    function trim(s){ gsub(/^[ \t]+|[ \t]+$/,"",s); return s }
    function csvq(s){ gsub(/"/,"\"\"",s); return "\"" s "\"" }

    NR==1{
      id_pos=index($0,"ID");
      size_pos=index($0,"SIZE");
      proc_pos=index($0,"PROCESSOR");
      ctx_pos=index($0,"CONTEXT");
      until_pos=index($0,"UNTIL");
      next
    }

    NR>1 && length($0)>0{
      name=trim(substr($0,1,id_pos-1));
      id=trim(substr($0,id_pos,size_pos-id_pos));
      size=trim(substr($0,size_pos,proc_pos-size_pos));
      proc=trim(substr($0,proc_pos,ctx_pos-proc_pos));
      ctx=trim(substr($0,ctx_pos,until_pos-ctx_pos));
      until=trim(substr($0,until_pos));

      split(proc,a," ");
      ctx_pct=a[1];
      device_mix="";
      for(i=2;i<=length(a);i++){
        if(a[i]!=""){
          device_mix = (device_mix=="" ? a[i] : device_mix " " a[i]);
        }
      }

      # TSV for bash to color/pretty print
      print name "\t" ctx "\t" size "\t" proc "\t" ctx_pct "\t" device_mix "\t" until "\t" id;

      # CSV emit (one row per model)
      line = host_ts "," nv_ts "," gpu_util "," gpu_mem_util "," gpu_mem_used "," gpu_mem_total "," gpu_power "," gpu_temp "," gpu_sm \
             "," csvq(name) "," csvq(id) "," csvq(size) "," csvq(proc) "," csvq(ctx_pct) "," csvq(device_mix) "," csvq(ctx) "," csvq(until) \
             "," c_cpu "," csvq(c_mem_used) "," csvq(c_mem_limit) "," c_mem_pct "," csvq(c_net_in) "," csvq(c_net_out) "," csvq(c_blk_in) "," csvq(c_blk_out) "," c_pids;

      print line >> log_file;
    }
  ' | while IFS=$'\t' read -r T_NAME T_CTX T_SIZE T_PROC T_CTXPCT T_DEV T_UNTIL T_ID; do
        # derive ctx pct integer for bar
        CTX_INT="$(printf "%s" "$T_CTXPCT" | cut -d'%' -f1 | tr -cd '0-9')"
        [ -n "$CTX_INT" ] || CTX_INT=0

        # row coloring by device + ctx
        ROW_CLR="$CYAN"
        if echo "$T_DEV" | grep -qi "CPU"; then ROW_CLR="$MAGENTA"; fi
        if (( CTX_INT >= 90 )); then ROW_CLR="$RED"; fi

        # compact table row (colored)
        printf "${ROW_CLR}%-34s${RESET} %-8s %-8s %-18s %-12s %-10s %-22s\n" \
          "${T_NAME:0:34}" "${T_CTX:0:8}" "${T_SIZE:0:8}" "${T_PROC:0:18}" "${T_CTXPCT:0:12}" "${T_DEV:0:10}" "${T_UNTIL:0:22}"

        # optional: show progress bars per model (comment out if too tall)
        echo -ne "  ${GRAY}ctx${RESET} "
        progress_bar "$CTX_INT" 24
        echo
     done

  echo -e "${GRAY}──────────────────────────────────────────────────────────────────────────────────────────────${RESET}"
  echo -e "${GRAY}CSV append:${RESET} ${BOLD}${LOG_FILE}${RESET}  |  ${GRAY}Next tick in ${INTERVAL_S}s${RESET}"

  sleep "$INTERVAL_S"
done