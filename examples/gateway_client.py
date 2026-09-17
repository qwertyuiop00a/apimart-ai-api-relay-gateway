#!/usr/bin/env python3
"""Gateway client: idempotent submits, classed retries, widening polling, per-task cost logging.

    python examples/gateway_client.py --dry-run --task image
    python examples/gateway_client.py --task text --prompt "Explain idempotency keys"
    python examples/gateway_client.py --task image --model gpt-image-2.5-ext --variant flare --resolution 1K

Set APIMART_API_KEY for live runs; --dry-run prints the plan without touching the network.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("APIMART_BASE_URL", "https://api.apimart.ai/v1").rstrip("/")
RETRYABLE = {429, 500, 502, 503, 504}
TERMINAL = {400, 401, 402}
BACKOFF = [2, 8, 30]
POLL_PLAN = [1, 2, 3, 5, 8, 10, 10, 10, 10, 10]


def plan(task: str) -> dict:
    if task == "image":
        return {"path": "/images/generations",
                "body": {"model": "gpt-image-2.5-ext", "version": "flare", "prompt": "<prompt>",
                         "size": "1:1", "resolution": "1K", "n": 1}}
    return {"path": "/chat/completions",
            "body": {"model": "gpt-5.5", "messages": [{"role": "user", "content": "<prompt>"}]}}


def classify(status: int | None, exc: Exception | None) -> str:
    if exc is not None:
        return "retryable"          # socket timeout / connection reset
    if status in RETRYABLE:
        return "retryable"
    if status in TERMINAL:
        return "terminal"
    return "other"


def submit(payload: dict, idempotency_key: str, timeout: int = 60) -> dict:
    request = urllib.request.Request(
        BASE + payload["path"], data=json.dumps(payload["body"]).encode(), method="POST",
        headers={"Authorization": f"Bearer {os.environ['APIMART_API_KEY']}",
                 "Content-Type": "application/json",
                 "X-APIMart-Response-Version": "2026-07-27",
                 "Idempotency-Key": idempotency_key})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def poll(task_id: str, timeout: int = 60) -> dict:
    request = urllib.request.Request(
        f"{BASE}/tasks/{task_id}",
        headers={"Authorization": f"Bearer {os.environ['APIMART_API_KEY']}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def run(payload: dict) -> dict | None:
    """Submit with retries, then poll. Returns the completed task or None."""
    key = str(uuid.uuid4())          # one key per logical operation, reused on every retry
    for attempt in range(len(BACKOFF) + 1):
        started = time.time()
        try:
            result = submit(payload, key)
            task_id = (result.get("data") or {}).get("id") if isinstance(result.get("data"), dict) else None
            if not task_id:
                return result
            break
        except urllib.error.HTTPError as exc:
            kind = classify(exc.code, None)
            print(f"[retry] attempt={attempt + 1} http={exc.code} class={kind}")
            if kind != "retryable" or attempt == len(BACKOFF):
                raise
        except Exception as exc:                      # noqa: BLE001 - network layer
            print(f"[retry] attempt={attempt + 1} error={type(exc).__name__} class=retryable")
            if attempt == len(BACKOFF):
                raise
        time.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)] + random.uniform(0, 0.5))

    for delay in POLL_PLAN:
        task = poll(task_id).get("data", {})
        print(f"[poll ] status={task.get('status')} progress={task.get('progress')}")
        if task.get("status") in ("completed", "failed"):
            return task
        time.sleep(delay)
    print("[poll ] timeout; keep the task id for later reconciliation:", task_id)
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Gateway client with idempotent submits and classed retries")
    ap.add_argument("--task", choices=["image", "text"], default="image")
    ap.add_argument("--prompt", default="A ceramic espresso cup on a stone pedestal, soft window light")
    ap.add_argument("--model")
    ap.add_argument("--variant", default="flare")
    ap.add_argument("--resolution", default="1K")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    payload = plan(args.task)
    if args.model:
        payload["body"]["model"] = args.model
    if args.task == "image":
        payload["body"]["variant"] = args.variant
        payload["body"]["resolution"] = args.resolution
        payload["body"]["prompt"] = args.prompt
    else:
        payload["body"]["messages"][0]["content"] = args.prompt

    print("[plan ] POST", BASE + payload["path"])
    print("[plan ] body", json.dumps(payload["body"], ensure_ascii=False))
    print("[plan ] retry backoff", BACKOFF, "| poll plan", POLL_PLAN)
    if args.dry_run:
        print("[plan ] dry run: no network calls made")
        return
    if not os.environ.get("APIMART_API_KEY"):
        sys.exit("set APIMART_API_KEY for a live run, or use --dry-run")

    task = run(payload)
    if task:
        print("[cost ] task_id=%s status=%s cost=%s credits=%s"
              % (task.get("id"), task.get("status"), task.get("cost"), task.get("credits_cost")))


if __name__ == "__main__":
    main()
