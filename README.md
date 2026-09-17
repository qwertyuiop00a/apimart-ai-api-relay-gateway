# AI API Gateway and LLM Gateway — Field Notes

**AI API gateway** and **LLM gateway** notes from running image, video and text workloads behind one base URL: request
headers that decide whether a retry is safe, a retry policy that survived testing, a timeout and failover decision tree,
and a comparison table for choosing between self-hosted, managed and relayed gateways.

**Attributed entry points:** [Browse the model catalog](https://go.apimart.ai/k-79ec90) · [Current pricing](https://go.apimart.ai/k-44c6fc) · [Get an API key](https://go.apimart.ai/k-3e0659)

## What a gateway changes (and what it does not)

A gateway (also called a relay or a proxy) terminates your request and re-issues it upstream. That adds one hop and
removes a pile of integration work. Four things change in practice:

1. **Idempotency becomes your problem.** Reusing an idempotency key collapses a retry into the original task; skipping it
   means a timeout plus a retry is two billable generations.
2. **Completion is a state machine, not a response body.** Long jobs return a task id: `pending → processing →
   completed | failed`, with `progress` and, when finished, `cost` and result URLs that expire.
3. **Cost is measured per task, not estimated per request.** The task payload carries `cost` and `credits_cost`, which is
   the only reconciliation that matches an invoice.
4. **Model strings replace SDKs.** Swapping one string (and sometimes a `version` selector) moves a request to another
   vendor without a new integration.

What it does *not* change: model quality comes from upstream, and each provider still leaks its own parameter subset,
safety layer and error envelope.

## Headers worth standardising

| Header | Why it is there | Failure mode without it |
| --- | --- | --- |
| `Authorization: Bearer <key>` | per-environment key scoping | `401` on every call |
| `Content-Type: application/json` | text-to-image, video and edits are all JSON bodies | `400` or a truncated body |
| `Idempotency-Key` | collapses retries into one logical generation | duplicate billing |
| `X-APIMart-Response-Version: 2026-07-27` | pins the response envelope so parsers do not drift | silent parser breakage after an API revision |

## Retry policy that survived testing

```text
attempt 1  immediate
attempt 2  +2s    only on 429 / 5xx / socket timeout, reusing the same Idempotency-Key
attempt 3  +8s
attempt 4  +30s   then surface the task id to the caller instead of failing blind

never retry   400 invalid_request_error, 401 authentication_error, 402 payment_required
poll cadence  first 30s every 3s, then every 10s, hard stop at the documented task TTL
```

The rule that saves the most money: **retry the submit, not the poll.** A retried submit without an idempotency key is a
second charge; a repeated poll is free.

## Timeout and failover decision tree

```text
request fails
├─ error class?
│  ├─ 400 / 401 / 402  -> do not retry: fix the request, the key or the balance
│  ├─ 429             -> wait for the reset signal, then retry with the same idempotency key
│  ├─ 5xx             -> retry twice with backoff; if still failing, fail over
│  └─ socket timeout  -> poll the task id first; the job may already be running
├─ same modality available elsewhere?
│  ├─ yes -> fail over with the same modality only (image route -> another image route)
│  └─ no  -> queue and surface the task id; do not silently drop the job
└─ record: model, version, attempt, task id, cost, latency
```

Cross-modality failover is where pipelines quietly break: an edit prompt written for one model rarely survives a
different vendor's model.

## Gateway comparison

| Dimension | Self-hosted gateway | Managed gateway | Relayed per-unit route |
| --- | --- | --- | --- |
| Keys | you hold provider keys | one gateway key, provider keys upstream | one key, provider managed |
| Envelope | you normalise it | mostly normalised, versioned | normalised, async task model |
| Billing unit | provider units | provider units + gateway fee | flat per image / per second / per token |
| Retry control | full (you own the loop) | policy config | header-driven (`Idempotency-Key`) |
| Timeout control | full | partial | request + poll TTL |
| Observability | you build it | dashboard + logs | per-task `cost`, `progress`, status |
| Failure surface | your bugs | their quirks | one extra hop, provider quirks can leak |
| Best fit | platform teams with SLO ownership | teams that want policy without ops | teams that want several modalities on one budget line |

## Reference implementation

```bash
python examples/gateway_client.py --dry-run --task image      # prints the plan, no network calls
python examples/gateway_client.py --task text --prompt "Explain idempotency keys"
./examples/curl.sh                                            # chat + image submit + poll
node examples/javascript_client.mjs                           # same contract in Node 18+
```

The client implements the interesting parts: a reused idempotency key per logical operation, backoff classification
(`429`/`5xx` retryable, `400`/`401`/`402` terminal), polling with widening intervals, and a per-task cost log line.

What to log for every call (this is the minimum for a post-incident reconstruction):

```text
timestamp, task_id, model, version, attempt, status, latency_ms, cost, error_class
```

## FAQ

**What is the difference between an AI API gateway, a relay and a proxy?**
They describe the same hop. *Proxy* usually means a thin forwarding layer, *relay* emphasises forwarding to an upstream
provider, and *gateway* emphasises a single ingress with one key, one base URL and shared policy (keys, quota, retry,
observability). The useful question is not the name but which of those four controls the layer actually gives you.

**Is retrying a generation request safe?**
Only with an idempotency key. Reuse the identical body and key, and the gateway collapses the retry into the original
task instead of creating a second billable artefact.

**Does a gateway add latency?**
It adds one hop. Whether that matters depends on what you gain: a shared retry policy, one credential to rotate, a single
cost ledger. Measure p50 and p95 on your own prompt set rather than trusting a benchmark.

**When is a flat per-unit route better than a token-billed route?**
When your workload is uniform and large: per-image and per-second routes make cost a multiplication, while token billing
rewards small, cache-heavy requests. Compare on cost per *accepted* artefact.

## Related searches

- `ai api gateway`
- `llm gateway`
- `ai api relay`
- `api gateway open source`
- `llm gateway vs proxy`
- `openai compatible api`
- `ai api aggregator`

## Attributed links (how this repository is measured)

| Purpose | Attributed link | Target |
| --- | --- | --- |
| Browse the model catalog | <https://go.apimart.ai/k-79ec90> | `apimart.ai` |
| Current pricing page | <https://go.apimart.ai/k-44c6fc> | `apimart.ai/pricing` |
| Get an API key | <https://go.apimart.ai/k-3e0659> | `apimart.ai/keys` |

Outbound APIMart links are minted through the promo link API (`go.apimart.ai`); hand-made tracking parameters are
rejected by `tools/check_links.py` in CI.

## Disclosure

These are field notes from operating workloads behind a gateway; the repository documents the patterns and does not claim
official status for any vendor. Product names, model names and documentation belong to their respective owners, and
relayed routes are third-party relay endpoints rather than first-party vendor endpoints.

## Repository map

```text
README.md                        gateway field notes, retry policy, comparison, FAQ
examples/gateway_client.py       retry + idempotency + polling + cost logging
examples/curl.sh                 chat, image submit, task poll
examples/javascript_client.mjs   the same contract in Node 18+
tools/check_links.py             attribution guard (CI)
.github/workflows/validate.yml   CI
```

## License

MIT — see [LICENSE](LICENSE).
