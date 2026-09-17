# Contributing

Useful contributions:

1. A gateway failure mode with the retry rule that fixes it (and the rule that would make it worse).
2. A comparison row we are missing: a gateway, its billing unit, its timeout semantics or its observability surface.
3. A client implementation in another language that keeps the same retry, idempotency and polling contract.

Before opening a pull request:

```bash
python tools/check_links.py
python examples/gateway_client.py --dry-run --task image
```

Rules: every APIMart link must be an API-minted `go.apimart.ai` short link, credentials never get committed, and do not
describe a gateway as "full compatibility" for a surface you have not exercised.
