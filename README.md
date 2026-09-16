# AI API Relay and Gateway Field Notes — image2.5 Routing in Practice

Engineering notes for putting an **AI API relay** in front of image workloads: which request headers matter, how to retry an asynchronous image2.5 task safely, how to poll without hammering the gateway, and how a flat per-image route changes capacity planning.

**Attributed entry points:** [Open GPT Image 2.5 on APIMart](https://go.apimart.ai/k-59cd25) · [Current pricing](https://go.apimart.ai/k-80ac8c) · [Get an API key](https://go.apimart.ai/k-a926cd)

## Contents

- [Model routes and IDs](#model-routes-and-ids)
- [Observed pricing](#observed-pricing)
- [What the output looks like](#what-the-output-looks-like)
- [Quickstart](#quickstart)
- [Request and response reference](#request-and-response-reference)
- [Request headers worth standardising](#request-headers-worth-standardising)
- [Retry policy that survived testing](#retry-policy-that-survived-testing)
- [FAQ](#faq)
- [Attributed links](#attributed-links-how-this-repository-is-measured)
- [Repository map](#repository-map)

## What a relay changes in an image pipeline

A relay (also called a gateway or 中转 in Chinese-language docs) terminates your request and re-issues it upstream. That
adds one hop and removes a pile of integration work. In practice four things change:

1. **Idempotency becomes your problem.** The relayed image2.5 route accepts `Idempotency-Key`; generate it once per
   logical operation and reuse it on retry, otherwise a network timeout can buy you two images.
2. **Completion is a state machine, not a response body.** `pending → processing → completed` with a `progress` field.
   Poll with backoff, and treat `failed` as terminal for that task ID.
3. **Cost is measured, not estimated.** `cost` and `credits_cost` come back on the task, which lets a pipeline reconcile
   spend per tenant instead of guessing from token counts.
4. **Version strings replace models.** `gpt-image-2.5-ext` plus `version` keeps one client path for two behaviours,
   which makes A/B routing a config change.

## Model routes and IDs

| Route | `model` value | Selector | Billing style | Best for |
| --- | --- | --- | --- | --- |
| Official (token) | `gpt-image-2.5-flare` | n/a | token usage, `quality` low → max | everyday generation, batch drafts |
| Official (token) | `gpt-image-2.5-sunburst` | n/a | token usage, `quality` low → max | editing precision, production assets |
| Relayed (per image) | `gpt-image-2.5-ext` | `version: "flare"` | per delivered image (`n` ≤ 4) | high-volume generation at a flat price |
| Relayed (per image) | `gpt-image-2.5-ext` | `version: "sunburst"` | per delivered image (`n` ≤ 4) | edits and reference-driven work at a flat price |

Both relayed variants accept `resolution` `1K` / `2K` / `4K`, ten aspect ratios plus `auto`, and up to 16 reference images in `image_urls`. The official route adds exact pixel dimensions and the `low / medium / high / xhigh / max` quality ladder.

- Family: **GPT Image 2.5** — the OpenAI image generation and editing series served through APIMart
- Model IDs: `gpt-image-2.5-flare`, `gpt-image-2.5-sunburst` (official route); `gpt-image-2.5-ext` with `version: flare|sunburst` (per-image relay route)
- Base URL: `https://api.apimart.ai/v1` — OpenAI-compatible `POST /v1/images/generations`
- Async tasks: submit, then poll `GET /v1/tasks/{task_id}` until `status: completed`
- Output tiers: `1K`, `2K`, `4K`; up to 16 reference images for image-to-image; `n` ≤ 4
- Observed 1K price on the relayed route: **$0.0085 per delivered image** (checked 2026-09-16)

## Observed pricing

| version | 1K | 2K | 4K | billing unit |
| --- | --- | --- | --- | --- |
| `flare` | $0.0085 | $0.014 | $0.021 | per delivered image |
| `sunburst` | $0.0085 | $0.014 | check live pricing | per delivered image |

Per-image billing on the relayed route is charged for delivered images, and the task response reports the exact amount in `cost` / `credits_cost`, so the table above can be re-verified after a single paid call. The official `gpt-image-2.5-flare` / `gpt-image-2.5-sunburst` route is token-billed with a `low → medium → high → xhigh → max` quality ladder, which is why this repository keeps both the flat per-image expectation and the token-billed option side by side. Snapshot date: 2026-09-16.

## What the output looks like

Every render below came from a single `POST /v1/images/generations` call on the relayed route, at the aspect ratio shown.
| Output | Recipe | Use case | Version | Ratio | Prompt |
| --- | --- | --- | --- | --- | --- |
| <img src="assets/02-rainy-tokyo-alley.jpg" width="220" alt="Cinematic night street generated with GPT Image 2.5"> | Cinematic night street | Cinematic still | `flare` | 16:9 | `Rain-slicked Tokyo alley at night, neon sign reflections on wet asphalt, a lone cyclist with an umbrella, cinematic 35mm film still, shallow depth of field` |
| <img src="assets/07-isometric-smart-home.jpg" width="220" alt="Isometric 3D cutaway generated with GPT Image 2.5"> | Isometric 3D cutaway | 3D illustration | `sunburst` | 1:1 | `Isometric cutaway of a compact smart home control room, tiny mid century furniture, pastel palette, clay render finish, clean soft shadows, 3D illustration` |
| <img src="assets/12-paper-cut-mountain-lake.jpg" width="220" alt="Layered paper-cut illustration generated with GPT Image 2.5"> | Layered paper-cut illustration | Editorial illustration | `sunburst` | 4:3 | `Layered paper cut illustration of a mountain lake sunrise, five depth layers, soft pastel palette, subtle drop shadows, art print composition` |
| <img src="assets/11-floating-ruin-keyart.jpg" width="220" alt="Game key art generated with GPT Image 2.5"> | Game key art | Game concept art | `sunburst` | 16:9 | `Fantasy game key art, an armored knight standing on a floating stone ruin above a sea of clouds, dramatic backlight, painterly detail, wide cinematic composition` |

Every recipe ships with the exact JSON body in [`examples/`](examples).

## Quickstart

The relayed route is asynchronous: submit, then poll the task ID.

```bash
# text to image on the per-image route
IDEMPOTENCY_KEY="$(uuidgen)"
curl --request POST \
  --url https://api.apimart.ai/v1/images/generations \
  --header "Authorization: Bearer $APIMART_API_KEY" \
  --header 'Content-Type: application/json' \
  --header 'X-APIMart-Response-Version: 2026-07-27' \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --data '{
    "model": "gpt-image-2.5-ext",
    "version": "flare",
    "prompt": "A cozy reading nook beside a window on a rainy day, warm table lamp, cinematic lighting",
    "size": "1:1",
    "resolution": "1K",
    "n": 1
  }'
```

```python
import os, time, uuid, requests

BASE = "https://api.apimart.ai/v1"
HEADERS = {
    "Authorization": f"Bearer {os.environ['APIMART_API_KEY']}",
    "Content-Type": "application/json",
    "X-APIMart-Response-Version": "2026-07-27",
    "Idempotency-Key": str(uuid.uuid4()),   # reuse on retry, not on a new image
}

def generate(prompt: str, version: str = "flare", resolution: str = "1K", size: str = "1:1") -> str:
    r = requests.post(f"{BASE}/images/generations", headers=HEADERS, timeout=60, json={
        "model": "gpt-image-2.5-ext", "version": version, "prompt": prompt,
        "size": size, "resolution": resolution, "n": 1,
    })
    r.raise_for_status()
    task_id = r.json()["data"]["id"]
    while True:
        t = requests.get(f"{BASE}/tasks/{task_id}", headers=HEADERS, timeout=60).json()["data"]
        if t["status"] in ("completed", "failed"):
            return t
        time.sleep(5)
```

```javascript
const headers = {
  Authorization: `Bearer ${process.env.APIMART_API_KEY}`,
  "Content-Type": "application/json",
  "X-APIMart-Response-Version": "2026-07-27",
  "Idempotency-Key": crypto.randomUUID(),
};
const res = await fetch("https://api.apimart.ai/v1/images/generations", {
  method: "POST",
  headers,
  body: JSON.stringify({
    model: "gpt-image-2.5-ext", version: "flare", prompt: "A sky garden at dawn, architectural photography",
    size: "16:9", resolution: "1K", n: 1,
  }),
});
const { data } = await res.json();          // data.id === task id
// poll GET https://api.apimart.ai/v1/tasks/${data.id} until data.status === "completed"
```

Official (token-billed) route, for comparison — same path, no `version`, quality ladder instead:

```bash
curl --request POST --url https://api.apimart.ai/v1/images/generations \
  --header "Authorization: Bearer $APIMART_API_KEY" --header 'Content-Type: application/json' \
  --data '{"model":"gpt-image-2.5-sunburst","prompt":"Preserve the product label, replace the background with soft off-white, add a natural cast shadow","size":"1:1","resolution":"1k","quality":"high","n":1}'
```

Full field reference: [official route docs](https://docs.apimart.ai/en/api-reference/images/gpt-image-2.5/generation) and [ext route docs](https://docs.apimart.ai/en/api-reference/images/gpt-image-2.5-ext/generation). Get a key at [apimart.ai/keys](https://go.apimart.ai/k-a926cd).

## Request and response reference (ext route)

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `model` | string | required | `gpt-image-2.5-ext` |
| `version` | string | `flare` | `flare` or `sunburst` |
| `prompt` | string | required | must not be empty after trimming |
| `resolution` | string | `1K` | `1K`, `2K`, `4K` |
| `size` | string | `auto` | `auto` or 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 5:4, 4:5, 21:9 |
| `n` | integer | `1` | 1–4 per request on the relayed route |
| `image_urls` | string[] | — | up to 16 references, URL or data URL, no extra charge |

Submission returns `202` with `data.id` (the task ID) and `data.poll_url`; `GET /v1/tasks/{task_id}` then reports
`status` (`pending` → `processing` → `completed` / `failed`), `progress`, `cost`, `credits_cost` and, when finished,
`result.images[].url` with an `expires_at` timestamp. Download outputs before that timestamp — the URLs are temporary.

## Request headers worth standardising

| Header | Why it is there | Failure if missing |
| --- | --- | --- |
| `Authorization: Bearer <key>` | key scoping per environment | 401 on every call |
| `Content-Type: application/json` | both text-to-image and edits are JSON bodies | 400 or truncated body |
| `Idempotency-Key` | collapses retries into one logical generation | duplicate billing |
| `X-APIMart-Response-Version: 2026-07-27` | pins the response envelope | parser drift after an API revision |

## Retry policy that survived testing

```text
attempt 1  immediate
attempt 2  +2s   (only on 429 / 5xx / socket timeout, reusing Idempotency-Key)
attempt 3  +8s
attempt 4  +30s  then surface the task_id to the caller instead of failing blind

never retry on: 400 invalid_request_error, 401 authentication_error, 402 payment_required
poll cadence:    first 30s every 3s, then every 10s, hard stop at the documented task TTL
```



## FAQ

**What is the difference between an AI API relay and an AI API gateway?**

They are used interchangeably. Relay emphasises forwarding traffic to an upstream provider; gateway emphasises the single ingress point with one key, one base URL and shared policy. A useful gateway also normalises responses, reports cost and hides provider-specific quirks.

**Is retrying an image2.5 request safe?**

Only with an idempotency key. Reusing the same `Idempotency-Key` plus the identical body lets the gateway collapse the retry into the original task instead of creating a second billable image.

**How should polling be scheduled?**

Follow the returned `poll_url` and back off: roughly every 3 seconds for the first half minute, then every 10 seconds. Budget for completion times in the tens of seconds, and stop polling when `status` is `completed` or `failed`.

**Why use a flat per-image route for image workloads?**

Because cost per asset becomes a constant. Token-billed image routes depend on output size, which makes per-tenant budgeting a measurement problem rather than a multiplication.

## Related searches

- `image2.5 api`
- `image 2.5 api`
- `image2.5 api gateway`
- `image2-5 api`
- `gpt-image-2.5 api`
- `image2.5 api pricing`
- `ai api relay`
- `ai api gateway`
- `ai api aggregator`
- `apimart image2.5`
- `image2.5 api documentation`
- `openai compatible image api`
- `apimart`
- `openai compatible`
- `api aggregator`
- `image2 5`

## Attributed links (how this repository is measured)

Every outbound link in this repository points at APIMart through a short link, so visits coming from this page are attributed instead of arriving as anonymous traffic.

| Purpose | Attributed link | Target |
| --- | --- | --- |
| Open GPT Image 2.5 on APIMart | <https://go.apimart.ai/k-59cd25> | `apimart.ai/model/gpt-image-2-5` |
| Current APIMart pricing | <https://go.apimart.ai/k-80ac8c> | `apimart.ai/pricing` |
| Get an API key on APIMart | <https://go.apimart.ai/k-a926cd> | `apimart.ai/keys` |

- [ ] Attribution target: the three `go.apimart.ai` short links above, all minted through the promo link API (302 with `utm_source=kol_sponsor&utm_medium=sponsor&sclid=...`). The endpoint docs on `docs.apimart.ai` are referenced as plain links: the link service only accepts the `apimart.ai` main domain, so no attributed short link exists for them.
- [ ] Re-check the price on the pricing page before a production run: promotional routing can change.

## Disclosure

APIMart is the service described in this repository; this page is published to document it, not to claim official status. The `ext` route is a third-party relay endpoint billed per delivered image, while the `gpt-image-2.5-flare` / `gpt-image-2.5-sunburst` models are the token-billed route. Model names, prices and limits belong to their respective owners, and everything here is observation-dated (2026-09-16). Verify with a single paid request before scaling volume.


## Repository map

```text
apimart-ai-api-relay-gateway/
  PROMPTS.md           every recipe with its output
  README.md            overview, pricing, quickstart and FAQ
  examples/
    curl.sh            submit + poll with curl
    python_generate.py end-to-end Python client
    javascript.mjs     Node 18+ equivalent
  tools/check_links.py attribution + prompt-data validator
  .github/workflows/validate.yml  CI for the validator
  assets/              example renders (JPEG, resized for the README)
  LICENSE              MIT
```

## License

MIT — see [LICENSE](LICENSE). Model names and vendor documentation remain the property of their owners.
