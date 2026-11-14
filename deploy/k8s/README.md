# Bursar on k3s

`bursar.yaml` is the core demo stack as Kubernetes objects: Anvil, the contract deploy Job, the
authority service, the console (agent + gate), the governed execution host (Rigorix), and the
frontend. It is written for a **single-node k3s** cluster, which is what the demo needs: the SQLite
file, the audit tree and the precondition authority are ReadWriteOnce volumes shared by pods on
that node.

> The explorer (`explorer/blockscout/`) is not in this manifest. It is a separate, heavier stack
> (Postgres + indexer + Next.js). Run it with its compose file on the host, or add it as its own
> kustomization if the VPS can afford it.

## Why Rigorix is a Deployment and not a Job or a host process

`rigorix-server` executes the governed `payments.broadcast` command itself, so the execution host
must contain both the server binary and the Bursar package that provides the broadcaster. That is
exactly what `backend/Dockerfile.rigorix` builds. In compose it is the optional
`container-rigorix` profile; in k3s it is the `rigorix` Deployment and Service.

`RIGORIX_SANDBOX=container` is a **declaration** of the isolation boundary, not a runtime
dependency: in a pod, the pod is that boundary. The server does not need a Docker socket, a VM, or
host access.

## 1. Build and make the images available

The cluster needs three images: `bursar-backend:dev`, `bursar-frontend:dev`, `bursar-rigorix:dev`.
Build them on the VPS (native amd64 is simplest):

```bash
# backend (scripts + compiled contracts are inside the image)
docker build -t bursar-backend:dev backend

# rigorix execution host — do NOT run `docker build ../..`: the parent checkout holds
# rigorix-oss/target (tens of GB). The script assembles a clean context.
RIGORIX_OSS=/path/to/rigorix-oss ./scripts/build-rigorix-image.sh

# frontend: the API and explorer URLs are baked at build time
PUBLIC_CONSOLE_URL=https://api.bursar.example.com \
PUBLIC_EXPLORER_URL=https://explorer.bursar.example.com \
  docker compose build frontend
```

On a single k3s node, import them instead of running a registry:

```bash
docker save bursar-backend:dev    | sudo k3s ctr images import -
docker save bursar-frontend:dev   | sudo k3s ctr images import -
docker save bursar-rigorix:dev    | sudo k3s ctr images import -
```

(Or push them to a registry and replace the `image:` values in `bursar.yaml`.)

## 2. Create the configuration

```bash
# The demo values, as in compose. BURSAR_RPC_URL=http://anvil:8545 is already in .env.demo,
# and BURSAR_CONSOLE_AUTHORITY_URL=http://authority:8001 resolves to the Service of the same name.
kubectl -n bursar create configmap bursar-env --from-env-file=.env.demo \
  --dry-run=client -o yaml | kubectl apply -f -

# The agent's key (never in .env.demo)
kubectl -n bursar create secret generic bursar-llm \
  --from-literal=BURSAR_LLM_API_KEY="$BURSAR_LLM_API_KEY"
```

The console's CORS origin is set in `bursar.yaml` (`BURSAR_CORS_ORIGINS`); change it to the host
the page is served from. The Ingress at the bottom uses `bursar.example.com` and
`api.bursar.example.com` — replace them.

## 3. Apply

```bash
kubectl apply -f deploy/k8s/bursar.yaml
kubectl -n bursar get pods -w
```

Ordering is handled by the objects themselves:

- `contracts` Job waits for Anvil, deploys the contracts and writes `/shared/chain.env`.
- authority and console have an initContainer that waits for that file.
- the console and rigorix initContainers seed the precondition check and the initial
  `authority.json` onto the shared volume; the console then owns `authority.json` (the payee
  freeze/reactivate switch).
- both APIs run Alembic at boot, so no separate migrate Job is needed.

## What is different from compose

| Compose | k3s |
|---|---|
| `BURSAR_RIGORIX_BASE_URL=http://host.docker.internal:3001` (host-run) or `http://rigorix:3001` (profile) | Always `http://rigorix:3001` — Service DNS. `host.docker.internal` does not exist in a pod. |
| audit tree bind-mounted from the host repo | `bursar-audit` PVC, mounted at `/workspace/.rigorix` (Rigorix) and `/rigorix-audit` (console) |
| precondition check under `/tmp/bursar-preconditions` on the host | the check is a ConfigMap; it and `authority.json` are seeded onto the `bursar-preconditions` PVC |
| `.rigorix-runtime` named volume/bind | `bursar-audit` PVC + the `preconditions.toml` ConfigMap item |
| Anvil chain is ephemeral (recreated by the contracts one-shot) | same: the Anvil pod uses an emptyDir. If it restarts, delete the `contracts` Job and re-create it (the chain will be empty). |

## Checks

```bash
kubectl -n bursar logs job/contracts          # addresses written
kubectl -n bursar logs deploy/console --tail=20
kubectl -n bursar exec deploy/console -- curl -sS http://127.0.0.1:8000/readyz
kubectl -n bursar exec deploy/console -- curl -sS http://rigorix:3001/health
```

A payment from the page then follows the same path as in compose: console → authority → sign →
persist → `payments.broadcast` inside the rigorix pod → the Anvil service.
