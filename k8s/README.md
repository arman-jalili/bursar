# Deploying Bursar to k3s

Target: `bursar.rigorix.eu` (app) and `explorer.bursar.rigorix.eu` (Blockscout).

## What runs where

| Component | Runs as | Why |
|-----------|---------|-----|
| `bursar-anvil` | k8s Deployment | the demo chain; RPC stays ClusterIP + NodePort `30545` for the composer |
| `bursar-contracts` | k8s Job | one-shot deploy of TestUsdc + PaymentRouter |
| `bursar-authority` | k8s Deployment | decision service, port 8001 |
| `bursar-console` | k8s Deployment | API + agent, port 8000 |
| `bursar-frontend` | k8s Deployment | nginx-served SPA, proxies `/api` to the console |
| **Blockscout** | **docker compose** (`explorer/blockscout/compose.vps.yml`) | see below |

### Why Blockscout is compose, not a k8s manifest

The `ghcr.io/blockscout/blockscout:latest` image boots correctly when run the way its
maintainers ship it: its own compose file with `common-blockscout.env` (~35 vars).
A hand-ported k8s manifest carried only ~20 of them, and each missing var surfaced as a
*different* crash — `evision_nif` `undef`, `Hammer` `CaseClauseError`, `Replica1` missing
`:database`. Those looked like image bugs but were all incomplete configuration, because
`RUNTIME_CONFIG=false` means `runtime.exs` never derives the defaults.

So the explorer runs on the host via compose and k3s only routes traffic to it.

Getting Traefik to reach it takes three things:
1. compose publishes the proxy on the **docker bridge gateway**, not loopback
   (`172.17.0.1:4010` — pods cannot reach `127.0.0.1`)
2. a headless `Service` + hand-written `Endpoints` pointing at that address
3. an `Ingress` for `explorer.bursar.rigorix.eu`

## Deploy

```bash
# 1. images (rebuild after any code change — a pull alone does not update the cluster)
docker build -f frontend/Dockerfile \
  --build-arg VITE_CONSOLE_API_URL=/api \
  --build-arg VITE_EXPLORER_URL=https://explorer.bursar.rigorix.eu \
  -t bursar-frontend:latest frontend/
docker build -f backend/Dockerfile -t bursar-backend:latest backend/
docker save bursar-frontend:latest | sudo k3s ctr images import -
docker save bursar-backend:latest  | sudo k3s ctr images import -

# 2. app stack
sudo kubectl apply -k k8s/

# 3. explorer (host compose) — needs the Anvil NodePort from step 2
cd explorer/blockscout
sudo docker compose -f anvil.yml -f compose.vps.yml -p bursar-explorer up -d
sudo kubectl apply -f ../../k8s/blockscout-proxy.yaml -f ../../k8s/blockscout-ingress.yaml
```

The OpenRouter key is never committed:

```bash
sudo kubectl create secret generic bursar-llm -n bursar \
  --from-literal=LLM_API_KEY=sk-or-v1-... \
  --from-literal=LLM_BASE_URL=https://openrouter.ai/api/v1 \
  --from-literal=LLM_MODEL=... --from-literal=LLM_FALLBACK_MODEL=...
```

## Configuration that is load-bearing

These are not obvious, and each one produced a real outage-shaped bug:

- **`BURSAR_CONSOLE_UPSTREAM=live`** — without it the console composes *stub* adapters
  (`console/interfaces/api.py:build_deps`) and never calls the real authority, so a
  dispatch cannot find the intent it just created.
- **Both deployables must share one SQLite file.** `BURSAR_CONSOLE_DATABASE_URL` and
  `BURSAR_AUTHORITY_DATABASE_URL` must be the *same* path in *both* pods. A split
  (`console` writing `bursar.db`, reading `authority.db`) yields
  `Authority refused the intent read with HTTP 404`.
- **`BURSAR_RIGORIX_BASE_URL`** — must point at a `rigorix-server` (the OSS Rust server
  spoken to by `rigorix-verifier`), *not* the enterprise `rigorix-core`, which requires
  Keycloak JWTs and will answer `HTTP 401`. The adapter has no auth header support by
  design ("local mode needs no auth"). Leaving it empty fails the gate step with
  `Something went wrong on our side.`
- **`max_tokens` on the LLM call** (`console_api/agent.py`) — every free OpenRouter model
  is a reasoning model; with no cap they spend the budget on `reasoning` and return
  `content: null`, which silently degrades parsing to the local regex fallback.

## DNS and TLS

Both hostnames need a Cloudflare A record to the node, proxied. Two traps:

- The ACME HTTP-01 self-check resolves through **CoreDNS**, which caches NXDOMAIN.
  Adding the record in Cloudflare is not enough — restart CoreDNS so the challenge can
  resolve: `sudo kubectl rollout restart deploy coredns -n kube-system`
- This node has **no working IPv6 route**, but Cloudflare publishes AAAA records. If the
  self-check picks an IPv6 address it fails with `network is unreachable`. Prefer an
  IPv4-only check (or disable the AAAA record for the hostname).
