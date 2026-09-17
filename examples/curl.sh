#!/usr/bin/env bash
# Gateway request shapes: text, image submit, task poll — with the headers that make retries safe.
set -euo pipefail
: "${APIMART_API_KEY:?export APIMART_API_KEY first}"
BASE="${APIMART_BASE_URL:-https://api.apimart.ai/v1}"
AUTH=(-H "Authorization: Bearer $APIMART_API_KEY")
COMMON=(-H 'Content-Type: application/json' -H 'X-APIMart-Response-Version: 2026-07-27')

echo "== text =="
curl -sS "$BASE/chat/completions" "${AUTH[@]}" "${COMMON[@]}" \
  -d '{"model":"gpt-5.5","messages":[{"role":"user","content":"List three retry rules."}]}' | head -c 300; echo

echo "== image submit (idempotent) =="
TASK=$(curl -sS "$BASE/images/generations" "${AUTH[@]}" "${COMMON[@]}" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"model":"gpt-image-2.5-ext","version":"flare","prompt":"A ceramic espresso cup on a stone pedestal","size":"1:1","resolution":"1K","n":1}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["id"])')
echo "task: $TASK"

echo "== poll (free; retrying a submit is not) =="
for _ in $(seq 1 20); do
  RESPONSE=$(curl -sS "$BASE/tasks/$TASK" "${AUTH[@]}")
  STATUS=$(printf '%s' "$RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["status"])')
  echo "status: $STATUS"
  [ "$STATUS" = "completed" ] && break
  [ "$STATUS" = "failed" ] && { printf '%s\n' "$RESPONSE"; exit 1; }
  sleep 5
done
printf '%s' "$RESPONSE" | python3 -c 'import json,sys; d=json.load(sys.stdin)["data"]; print("cost:", d.get("cost"), "urls:", d.get("result",{}).get("images",[{}])[0].get("url"))'
