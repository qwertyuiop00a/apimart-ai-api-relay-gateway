// Gateway client in Node 18+: idempotent submit, classed retries, widening poll, cost log.
const BASE = process.env.APIMART_BASE_URL ?? "https://api.apimart.ai/v1";
const KEY = process.env.APIMART_API_KEY;
const RETRYABLE = new Set([429, 500, 502, 503, 504]);
const BACKOFF = [2000, 8000, 30000];
const POLL_PLAN = [1000, 2000, 3000, 5000, 8000, 10000, 10000];
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function submit(body, idempotencyKey) {
  const res = await fetch(`${BASE}/images/generations`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${KEY}`,
      "Content-Type": "application/json",
      "X-APIMart-Response-Version": "2026-07-27",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = new Error(`http ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export async function generate(prompt, { version = "flare", resolution = "1K", size = "1:1" } = {}) {
  const key = crypto.randomUUID();          // one key per logical operation
  let created;
  for (let attempt = 0; attempt <= BACKOFF.length; attempt++) {
    try {
      created = await submit({ model: "gpt-image-2.5-ext", version, prompt, size, resolution, n: 1 }, key);
      break;
    } catch (err) {
      const retryable = err.status ? RETRYABLE.has(err.status) : true;   // network error => retry
      if (!retryable || attempt === BACKOFF.length) throw err;
      console.warn(`[retry] attempt=${attempt + 1} status=${err.status ?? "network"}`);
      await sleep(BACKOFF[Math.min(attempt, BACKOFF.length - 1)]);
    }
  }
  const taskId = created.data.id;
  for (const delay of POLL_PLAN) {
    const task = (await (await fetch(`${BASE}/tasks/${taskId}`, { headers: { Authorization: `Bearer ${KEY}` } })).json()).data;
    console.log(`[poll ] status=${task.status} progress=${task.progress}`);
    if (task.status === "completed" || task.status === "failed") {
      console.log(`[cost ] task_id=${task.id} cost=${task.cost}`);
      return task;
    }
    await sleep(delay);
  }
  console.warn(`[poll ] timeout; keep ${taskId} for reconciliation`);
}

if (process.argv[1]?.endsWith("javascript_client.mjs")) {
  await generate(process.argv[2] ?? "A sky garden at dawn, architectural photography");
}
