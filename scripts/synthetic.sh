#!/usr/bin/env bash
# Synthetic runner tests. Writes one JSON object to $OUT.
# T1 CPU, T2 cache round trip, T4 disk, T5 network egress.
set -uo pipefail

OUT="${OUT:-synthetic.json}"
PAYLOAD_MB="${CACHE_PAYLOAD_MB:-1024}"

now() { date +%s.%N; }
elapsed() { python3 -c "print(round($2-$1,3))"; }

json_add() { printf '  "%s": %s,\n' "$1" "$2" >> "$OUT.parts"; }

: > "$OUT.parts"

# --- tool install, also a proxy for apt throughput
t0=$(now)
sudo apt-get update -qq >/dev/null 2>&1
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq sysbench fio >/dev/null 2>&1
t1=$(now)
json_add apt_install_s "$(elapsed "$t0" "$t1")"

# --- T1 CPU, single thread then all threads
s1=$(sysbench cpu --cpu-max-prime=20000 --threads=1 --time=20 run 2>/dev/null \
     | awk '/events per second/{print $4}')
sn=$(sysbench cpu --cpu-max-prime=20000 --threads="$(nproc)" --time=20 run 2>/dev/null \
     | awk '/events per second/{print $4}')
json_add cpu_events_per_s_1t "${s1:-null}"
json_add cpu_events_per_s_nt "${sn:-null}"
json_add nproc "$(nproc)"

# --- T4 disk, on the workspace volume
fio --name=randrw --directory="$RUNNER_TEMP" --size=512M --bs=4k \
    --rw=randrw --rwmixread=70 --ioengine=libaio --direct=1 --iodepth=32 \
    --runtime=20 --time_based --group_reporting --output-format=json \
    > "$RUNNER_TEMP/fio.json" 2>/dev/null
if [ -s "$RUNNER_TEMP/fio.json" ]; then
  json_add disk_read_iops  "$(python3 -c "import json;d=json.load(open('$RUNNER_TEMP/fio.json'));print(round(d['jobs'][0]['read']['iops']))")"
  json_add disk_write_iops "$(python3 -c "import json;d=json.load(open('$RUNNER_TEMP/fio.json'));print(round(d['jobs'][0]['write']['iops']))")"
  json_add disk_read_mbps  "$(python3 -c "import json;d=json.load(open('$RUNNER_TEMP/fio.json'));print(round(d['jobs'][0]['read']['bw']/1024,1))")"
else
  json_add disk_read_iops null; json_add disk_write_iops null; json_add disk_read_mbps null
fi
rm -f "$RUNNER_TEMP/fio.json"

# --- T5 network egress from a public CDN object
t0=$(now)
curl -sSL -o /dev/null "https://speed.cloudflare.com/__down?bytes=524288000" || true
t1=$(now)
d=$(elapsed "$t0" "$t1")
json_add net_download_s "$d"
json_add net_download_mbps "$(python3 -c "print(round(500/$d,1)) if $d>0 else print('null')")"

# --- T2 cache payload build. The save and restore are timed by the workflow steps.
mkdir -p "$HOME/.bench-cache/payload"
t0=$(now)
dd if=/dev/urandom of="$HOME/.bench-cache/payload/blob" bs=1M count="$PAYLOAD_MB" status=none
t1=$(now)
json_add payload_write_s "$(elapsed "$t0" "$t1")"
json_add payload_mb "$PAYLOAD_MB"

{
  echo "{"
  cat "$OUT.parts"
  printf '  "schema": 1\n'
  echo "}"
} > "$OUT"
rm -f "$OUT.parts"
cat "$OUT"
