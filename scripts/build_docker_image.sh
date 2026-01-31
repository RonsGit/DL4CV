#!/usr/bin/env zsh
# Build and optionally push the Docker image for LaTeX builds

set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE_NAME="eecs498-latex-builder"
REGISTRY="ghcr.io/deep-learning-for-computer-vision/eecs498---summary/latex-builder"

echo "[Docker] Building image: $IMAGE_NAME"
docker build -t "$IMAGE_NAME:latest" -f Dockerfile .

echo "[Docker] Testing image..."
docker run --rm "$IMAGE_NAME:latest" make4ht --version

if [[ "${1:-}" == "--push" ]]; then
  echo "[Docker] Tagging for registry: $REGISTRY"
  docker tag "$IMAGE_NAME:latest" "$REGISTRY:latest"
  
  echo "[Docker] Pushing to registry..."
  docker push "$REGISTRY:latest"
  
  echo "[Docker] Successfully pushed to $REGISTRY:latest"
else
  echo "[Docker] Build complete. Local image: $IMAGE_NAME:latest"
  echo "[Docker] To push to registry, run: $0 --push"
fi

echo "[Docker] Image size:"
docker images "$IMAGE_NAME:latest" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

