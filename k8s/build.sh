#!/usr/bin/env bash
# Build and deploy the Bursar demo to k3s.
#
#   ./k8s/build.sh              # build + import images, apply manifests
#   ./k8s/build.sh --manifests  # apply manifests only (images already imported)
#
# Prereqs:
#   - LLM key secret created once (see k8s/kustomization.yaml header)
#   - DNS: bursar.rigorix.eu -> this host (Cloudflare A record, proxied)

set -euo pipefail
cd "$(dirname "$0")/.."

MANIFESTS_ONLY="${1:-}"

if [ "$MANIFESTS_ONLY" != "--manifests" ]; then
  echo "==> Building backend image..."
  docker build -f backend/Dockerfile -t bursar-backend:latest backend/

  echo "==> Building frontend image (API on same origin via /api)..."
  docker build -f frontend/Dockerfile \
    --build-arg VITE_CONSOLE_API_URL=/api \
    --build-arg VITE_OWNER_TOKEN=demo-owner-token \
    --build-arg VITE_DEMO_OWNER_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 \
    --build-arg VITE_RIGORIX_HMAC_KEY=bursar-demo-operator-held-evidence-key-4c1f9a \
    -t bursar-frontend:latest frontend/

  echo "==> Importing into k3s containerd..."
  docker save bursar-backend:latest  | sudo k3s ctr images import -
  docker save bursar-frontend:latest | sudo k3s ctr images import -
fi

echo "==> Applying manifests..."
sudo kubectl apply -k k8s/

echo "==> Waiting for rollouts..."
sudo kubectl rollout status deployment/bursar-authority -n bursar --timeout=180s
sudo kubectl rollout status deployment/bursar-console   -n bursar --timeout=180s
sudo kubectl rollout status deployment/bursar-frontend  -n bursar --timeout=120s

echo ""
echo "=== Pods ==="
sudo kubectl get pods -n bursar
echo ""
echo "=== Certificate ==="
sudo kubectl get certificate -n bursar
echo ""
echo "Local check (TLS may take a minute on first issue):"
echo "  curl -sI https://bursar.rigorix.eu/ | head -1"
