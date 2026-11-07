#!/bin/sh
# Playback measurement on LibreELEC (Raspberry Pi 4), one line per interval:
# decoded frames/s (v4l2_dqbuf on the HEVC decoder), display flips/s
# (drm_vblank_event_delivered), media clock speed, stream info from Kodi,
# temperature, throttling and the curve state.
#
#   KODI_RPC=http://kodi:password@127.0.0.1:8080/jsonrpc perf.sh [seconds] > perf.log
#
# Stop it with SIGTERM (kill), which restores the trace settings.
T=/sys/kernel/tracing
INTERVAL=${1:-10}
RPC=${KODI_RPC:-http://127.0.0.1:8080/jsonrpc}
DECODER=/dev/video19

rpc() {
  curl -s -m 3 -H 'Content-Type: application/json' -d "$1" "$RPC"
}

echo 0 > $T/tracing_on
echo > $T/trace
echo 4096 > $T/buffer_size_kb
# the trace reports the device minor, which is not the number in the node name
MINOR=$(ls -l $DECODER | awk '{print $6}')
echo "minor == $MINOR" > $T/events/v4l2/v4l2_dqbuf/filter
echo 1 > $T/events/v4l2/v4l2_dqbuf/enable
echo 1 > $T/events/drm/drm_vblank_event_delivered/enable
trap 'echo 0 > $T/tracing_on; echo 0 > $T/events/v4l2/v4l2_dqbuf/enable; echo 0 > $T/events/drm/drm_vblank_event_delivered/enable; echo 0 > $T/events/v4l2/v4l2_dqbuf/filter; echo > $T/trace; exit 0' INT TERM

prev_ms=""
while true; do
  echo > $T/trace
  echo 1 > $T/tracing_on
  sleep "$INTERVAL"
  echo 0 > $T/tracing_on
  dec=$(grep -c 'type = VIDEO_CAPTURE' $T/trace)
  vbl=$(grep -c drm_vblank_event_delivered $T/trace)

  p=$(rpc '{"jsonrpc":"2.0","id":1,"method":"Player.GetProperties","params":{"playerid":1,"properties":["time"]}}')
  h=$(echo "$p" | sed -n 's/.*"hours":\([0-9]*\).*/\1/p')
  m=$(echo "$p" | sed -n 's/.*"minutes":\([0-9]*\).*/\1/p')
  s=$(echo "$p" | sed -n 's/.*"seconds":\([0-9]*\).*/\1/p')
  ms=$(echo "$p" | sed -n 's/.*"milliseconds":\([0-9]*\).*/\1/p')
  rate="-"
  if [ -n "$h" ]; then
    now=$(( ((h * 60 + m) * 60 + s) * 1000 + ms ))
    [ -n "$prev_ms" ] && rate=$(awk -v a="$now" -v b="$prev_ms" -v i="$INTERVAL" 'BEGIN { printf "%.2f", (a - b) / 1000 / i }')
    prev_ms=$now
  else
    prev_ms=""
  fi

  l=$(rpc '{"jsonrpc":"2.0","id":2,"method":"XBMC.GetInfoLabels","params":{"labels":["Player.Process(videofps)","Player.Process(videowidth)","Player.Process(videoheight)","Player.Filename"]}}')
  fps=$(echo "$l" | sed -n 's/.*"Player.Process(videofps)":"\([^"]*\)".*/\1/p')
  w=$(echo "$l" | sed -n 's/.*"Player.Process(videowidth)":"\([^"]*\)".*/\1/p')
  hh=$(echo "$l" | sed -n 's/.*"Player.Process(videoheight)":"\([^"]*\)".*/\1/p')
  file=$(echo "$l" | sed -n 's/.*"Player.Filename":"\([^"]*\)".*/\1/p')

  printf '%s dec=%s/s flips=%s/s media=%sx fps=%s %sx%s curve=%s %s %s load=%s %s\n' \
    "$(date +%T)" \
    "$(awk -v n="$dec" -v i="$INTERVAL" 'BEGIN { printf "%.2f", n / i }')" \
    "$(awk -v n="$vbl" -v i="$INTERVAL" 'BEGIN { printf "%.2f", n / i }')" \
    "$rate" "$fps" "$w" "$hh" "$(cat /sys/module/vc4/parameters/hvs5_pq_gamma)" \
    "$(vcgencmd measure_temp | cut -d= -f2)" "$(vcgencmd get_throttled)" \
    "$(cut -d' ' -f1 /proc/loadavg)" "$file"
done
