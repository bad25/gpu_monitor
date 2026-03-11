#!/usr/bin/env bash
# DEPRECATED: Shell version v1, Ollama-only.
# Use gpu_monitor.py instead — supports all runtimes (ollama, vllm, sglang, localai, docker-model-runner, generic).
set -euo pipefail

LOG_FILE="${LOG_FILE:-gpu_monitor_log.csv}"
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

trim() { sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//'; }

# CSV header (long format: one row per model)
# Notes:
# - host_ts: host wall clock
# - nv_ts: timestamp from nvidia-smi
# - model_*: per model row from `ollama ps`
# - container_*: docker stats for ollama container
echo "host_ts,nv_ts,gpu_util_pct,gpu_mem_util_pct,gpu_mem_used_MiB,gpu_mem_total_MiB,gpu_power_W,gpu_temp_C,gpu_sm_clock_MHz,model_name,model_id,model_size,model_processor_raw,model_context_pct,model_device_mix,model_context_tokens,model_until,container_cpu_pct,container_mem_used,container_mem_limit,container_mem_pct,container_net_in,container_net_out,container_blk_in,container_blk_out,container_pids" > "$LOG_FILE"

echo "Logging to: $LOG_FILE"
echo "Interval: ${INTERVAL_S}s | Container: ${OLLAMA_CONTAINER}"
echo "Press Ctrl+C to stop."
echo

while true; do
  HOST_TS="$(date +"%Y-%m-%d %H:%M:%S")"

  # --- GPU snapshot ---
  # output order:
  # nv_ts, gpu_util, gpu_mem_util, mem_used, mem_total, power, temp, sm_clock
  GPU_LINE="$(nvidia-smi \
    --query-gpu=timestamp,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,temperature.gpu,clocks.sm \
    --format=csv,noheader,nounits 2>/dev/null | head -n1 || true)"

  if [ -z "${GPU_LINE:-}" ]; then
    # keep columns stable if nvidia-smi fails
    GPU_LINE=",,,,,,,,"  # 8 columns (nv_ts + 7 metrics)
  fi

  # Split GPU_LINE into vars (commas may have spaces; trim later)
  IFS=',' read -r NV_TS GPU_UTIL GPU_MEM_UTIL GPU_MEM_USED GPU_MEM_TOTAL GPU_POWER GPU_TEMP GPU_SM_CLOCK <<< "$GPU_LINE"
  NV_TS="$(printf "%s" "${NV_TS:-}" | trim)"
  GPU_UTIL="$(printf "%s" "${GPU_UTIL:-}" | trim)"
  GPU_MEM_UTIL="$(printf "%s" "${GPU_MEM_UTIL:-}" | trim)"
  GPU_MEM_USED="$(printf "%s" "${GPU_MEM_USED:-}" | trim)"
  GPU_MEM_TOTAL="$(printf "%s" "${GPU_MEM_TOTAL:-}" | trim)"
  GPU_POWER="$(printf "%s" "${GPU_POWER:-}" | trim)"
  GPU_TEMP="$(printf "%s" "${GPU_TEMP:-}" | trim)"
  GPU_SM_CLOCK="$(printf "%s" "${GPU_SM_CLOCK:-}" | trim)"

  # --- Docker stats for container ---
  # format:
  # CPU%, MemUsage, Mem%, NetIO, BlockIO, PIDs
  DSTATS="$(docker stats --no-stream \
    --format '{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}},{{.BlockIO}},{{.PIDs}}' \
    "$OLLAMA_CONTAINER" 2>/dev/null || true)"

  if [ -n "$DSTATS" ]; then
    IFS=',' read -r C_CPU C_MEMUSAGE C_MEMPERC C_NETIO C_BLKIO C_PIDS <<< "$DSTATS"

    C_CPU="${C_CPU/\%/}"
    C_MEMPERC="${C_MEMPERC/\%/}"

    C_MEM_USED="$(printf "%s" "$C_MEMUSAGE" | awk -F' / ' '{print $1}' | trim)"
    C_MEM_LIMIT="$(printf "%s" "$C_MEMUSAGE" | awk -F' / ' '{print $2}' | trim)"

    C_NET_IN="$(printf "%s" "$C_NETIO" | awk -F' / ' '{print $1}' | trim)"
    C_NET_OUT="$(printf "%s" "$C_NETIO" | awk -F' / ' '{print $2}' | trim)"

    C_BLK_IN="$(printf "%s" "$C_BLKIO" | awk -F' / ' '{print $1}' | trim)"
    C_BLK_OUT="$(printf "%s" "$C_BLKIO" | awk -F' / ' '{print $2}' | trim)"

    C_PIDS="$(printf "%s" "${C_PIDS:-}" | trim)"
    C_CPU="$(printf "%s" "${C_CPU:-}" | trim)"
    C_MEMPERC="$(printf "%s" "${C_MEMPERC:-}" | trim)"
  else
    C_CPU=""; C_MEM_USED=""; C_MEM_LIMIT=""; C_MEMPERC=""; C_NET_IN=""; C_NET_OUT=""; C_BLK_IN=""; C_BLK_OUT=""; C_PIDS=""
  fi

  # --- Ollama ps ---
  # We parse by header column positions (robust despite spaces in PROCESSOR/UNTIL).
  PS_OUTPUT="$(docker exec "$OLLAMA_CONTAINER" ollama ps 2>/dev/null || true)"

  # Render terminal dashboard header
  clear
  echo "================ SAWITH.TECH AI LOCAL MONITOR ================="
  echo "Time          : $HOST_TS"
  echo
  echo "GPU"
  echo "  Util        : ${GPU_UTIL:-} %"
  echo "  VRAM        : ${GPU_MEM_USED:-} / ${GPU_MEM_TOTAL:-} MiB"
  echo "  Power       : ${GPU_POWER:-} W"
  echo "  Temp        : ${GPU_TEMP:-} °C"
  echo "  SM Clock    : ${GPU_SM_CLOCK:-} MHz"
  echo
  echo "CONTAINER ($OLLAMA_CONTAINER)"
  echo "  CPU         : ${C_CPU:-} %"
  echo "  RAM         : ${C_MEM_USED:-} / ${C_MEM_LIMIT:-} (${C_MEMPERC:-} %)"
  echo "  Net I/O     : ${C_NET_IN:-} / ${C_NET_OUT:-}"
  echo "  Block I/O   : ${C_BLK_IN:-} / ${C_BLK_OUT:-}"
  echo "  PIDs        : ${C_PIDS:-}"
  echo
  echo "OLLAMA MODELS (one row per model)"
  printf "%-32s  %-6s  %-8s  %-18s  %-10s  %-8s  %-22s\n" "NAME" "CTX" "SIZE" "PROCESSOR" "CTX_PCT" "DEVICE" "UNTIL"
  echo "--------------------------------------------------------------------------------------------------------------"

  # If empty or only header -> write one NONE row
  if [ -z "${PS_OUTPUT:-}" ] || [ "$(printf "%s\n" "$PS_OUTPUT" | awk 'END{print NR}')" -le 1 ]; then
    # Terminal row
    printf "%-32s  %-6s  %-8s  %-18s  %-10s  %-8s  %-22s\n" "NONE" "0" "-" "-" "0%/100%" "-" "-"

    # CSV row
    echo "$HOST_TS,$NV_TS,$GPU_UTIL,$GPU_MEM_UTIL,$GPU_MEM_USED,$GPU_MEM_TOTAL,$GPU_POWER,$GPU_TEMP,$GPU_SM_CLOCK,NONE,,,,0%/100%,,0,,,$C_CPU,$C_MEM_USED,$C_MEM_LIMIT,$C_MEMPERC,$C_NET_IN,$C_NET_OUT,$C_BLK_IN,$C_BLK_OUT,$C_PIDS" >> "$LOG_FILE"

    sleep "$INTERVAL_S"
    continue
  fi

  # Parse header positions once, then each data row -> emit CSV row per model
  # Columns in `ollama ps`:
  # NAME | ID | SIZE | PROCESSOR | CONTEXT | UNTIL
  #
  # PROCESSOR examples:
  #   "28%/72% CPU/GPU"
  #   "7%/93% CPU/GPU"
  #
  # We derive:
  #   model_context_pct = first token of PROCESSOR (e.g. 28%/72%)
  #   model_device_mix  = remaining tokens joined (e.g. CPU/GPU)
  #
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

      # derive context pct + device mix
      split(proc,a," ");
      ctx_pct=a[1];
      device_mix="";
      for(i=2;i<=length(a);i++){
        if(a[i]!=""){
          device_mix = (device_mix=="" ? a[i] : device_mix " " a[i]);
        }
      }

      # terminal print via stderr? (we print from bash later) -> instead we print a TSV line to stdout for bash to render
      print name "\t" ctx "\t" size "\t" proc "\t" ctx_pct "\t" device_mix "\t" until;

      # CSV emit (one row per model)
      line = host_ts "," nv_ts "," gpu_util "," gpu_mem_util "," gpu_mem_used "," gpu_mem_total "," gpu_power "," gpu_temp "," gpu_sm \
             "," csvq(name) "," csvq(id) "," csvq(size) "," csvq(proc) "," csvq(ctx_pct) "," csvq(device_mix) "," csvq(ctx) "," csvq(until) \
             "," c_cpu "," csvq(c_mem_used) "," csvq(c_mem_limit) "," c_mem_pct "," csvq(c_net_in) "," csvq(c_net_out) "," csvq(c_blk_in) "," csvq(c_blk_out) "," c_pids;

      print line >> log_file;
    }
  ' | while IFS=$'\t' read -r T_NAME T_CTX T_SIZE T_PROC T_CTXPCT T_DEV T_UNTIL; do
        # terminal row per model
        printf "%-32s  %-6s  %-8s  %-18s  %-10s  %-8s  %-22s\n" \
          "${T_NAME:0:32}" "${T_CTX:0:6}" "${T_SIZE:0:8}" "${T_PROC:0:18}" "${T_CTXPCT:0:10}" "${T_DEV:0:8}" "${T_UNTIL:0:22}"
     done

  sleep "$INTERVAL_S"
done
