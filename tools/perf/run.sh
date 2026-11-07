#!/bin/sh
# Plays each file of a list from 30 % of its length for a minute, through
# Kodi's JSON-RPC, while perf.sh measures. Do not use Kodi meanwhile: a
# refresh rate switch with a settings window open can deadlock Kodi.
#
#   KODI_RPC=http://kodi:password@127.0.0.1:8080/jsonrpc run.sh files.txt
#
# files.txt: one path or URL per line, as Kodi sees it (smb://..., /storage/...).
RPC=${KODI_RPC:-http://127.0.0.1:8080/jsonrpc}

rpc() {
  curl -s -m 5 -H 'Content-Type: application/json' -d "$1" "$RPC" > /dev/null
}

while IFS= read -r f; do
  [ -z "$f" ] && continue
  echo "$(date +%T) START $f"
  rpc "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"Player.Open\",\"params\":{\"item\":{\"file\":\"$f\"}}}"
  sleep 12
  rpc '{"jsonrpc":"2.0","id":2,"method":"Player.Seek","params":{"playerid":1,"value":{"percentage":30}}}'
  sleep 55
  echo "$(date +%T) STOP"
  rpc '{"jsonrpc":"2.0","id":3,"method":"Player.Stop","params":{"playerid":1}}'
  sleep 6
done < "$1"
echo "$(date +%T) DONE"
