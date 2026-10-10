#!/usr/bin/env bash
# Serves a built frontend with deploy/nginx.conf in the production nginx image and
# checks the Content-Type of one file per extension found in the build. nginx sends
# X-Content-Type-Options: nosniff on static files, so a script or stylesheet with a
# wrong type is refused by the browser, and module scripts/workers (pdf.js's
# /pdfjs/pdf.worker.min.mjs) need a JavaScript type in any case.
#
# Usage: deploy/tests/test_nginx_static_types.sh [dist-dir]   (default: frontend/dist)
# Needs docker, openssl and the nginx image from docker-compose.prod.yml present
# locally (NGINX_IMAGE, default nginx:1.27-alpine); it does not pull images.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIST="${1:-$ROOT/frontend/dist}"
IMAGE="${NGINX_IMAGE:-nginx:1.27-alpine}"
NAME="nginx-static-types-$$"
[[ -f "$DIST/index.html" ]] || { echo "FAIL: no build at $DIST (run npm run build)" >&2; exit 1; }
docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "SKIP: image $IMAGE not present locally" >&2; exit 0; }

TMP="$(mktemp -d)"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT
mkdir -p "$TMP/certs"
# Native Windows tools (Git Bash) need Windows paths; elsewhere this is a no-op.
host_path() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else echo "$1"; fi; }
MSYS_NO_PATHCONV=1 openssl req -x509 -nodes -newkey rsa:2048 -subj "/CN=localhost" -days 1 \
  -keyout "$(host_path "$TMP/certs/key.pem")" -out "$(host_path "$TMP/certs/cert.pem")" >/dev/null 2>&1
MSYS_NO_PATHCONV=1 docker run -d --name "$NAME" \
  --add-host backend:127.0.0.1 --add-host file-gateway:127.0.0.1 \
  -v "$(host_path "$ROOT/deploy/nginx.conf"):/etc/nginx/nginx.conf:ro" \
  -v "$(host_path "$ROOT/deploy/spa-security-headers.conf"):/etc/nginx/snippets/spa-security-headers.conf:ro" \
  -v "$(host_path "$TMP/certs"):/etc/nginx/certs:ro" \
  -v "$(host_path "$DIST"):/usr/share/nginx/html:ro" \
  "$IMAGE" >/dev/null
for _ in $(seq 1 20); do
  docker exec "$NAME" wget -q -O /dev/null --no-check-certificate https://127.0.0.1/index.html 2>/dev/null && break
  sleep 0.5
done

expected_type() {
  case "$1" in
    js|mjs) echo "text/javascript|application/javascript" ;;
    css) echo "text/css" ;;
    html) echo "text/html" ;;
    json|map) echo "application/json" ;;
    webmanifest) echo "application/manifest\+json" ;;
    svg) echo "image/svg\+xml" ;;
    png) echo "image/png" ;;
    ico) echo "image/(x-icon|vnd.microsoft.icon)" ;;
    woff2) echo "font/woff2" ;;
    woff) echo "font/woff" ;;
    ttf) echo "font/ttf" ;;
    wasm) echo "application/wasm" ;;
    txt) echo "text/plain" ;;
    *) echo "" ;;
  esac
}

failures=0
check() { # url-path ext
  local path="$1" ext="$2" headers type want
  headers="$(docker exec "$NAME" wget -S -q -O /dev/null --no-check-certificate "https://127.0.0.1$path" 2>&1 || true)"
  type="$(printf '%s\n' "$headers" | tr -d '\r' | sed -n 's/^ *[Cc]ontent-[Tt]ype: *//p' | head -1)"
  want="$(expected_type "$ext")"
  if [[ -z "$type" || "$type" == application/octet-stream* ]]; then
    echo "FAIL: $path served as '${type:-<none>}'"; failures=$((failures + 1)); return
  fi
  if [[ -n "$want" ]] && ! [[ "$type" =~ ^($want)(;.*)?$ ]]; then
    echo "FAIL: $path served as '$type', expected $want"; failures=$((failures + 1)); return
  fi
  if ! printf '%s\n' "$headers" | grep -qi '^ *x-content-type-options: *nosniff'; then
    echo "FAIL: $path has no X-Content-Type-Options: nosniff"; failures=$((failures + 1)); return
  fi
  echo "ok   $path -> $type"
}

declare -A seen=()
while IFS= read -r file; do
  rel="${file#"$DIST"}"
  base="${rel##*/}"
  [[ "$base" == *.* ]] || continue
  ext="${base##*.}"; ext="${ext,,}"
  [[ -n "${seen[$ext]:-}" ]] && continue
  seen[$ext]=1
  check "$rel" "$ext"
done < <(find "$DIST" -type f | sort)
# The pdf.js worker is loaded as a module worker from this fixed URL.
if [[ -f "$DIST/pdfjs/pdf.worker.min.mjs" && "$(find "$DIST" -type f -name '*.mjs' | sort | head -1)" != "$DIST/pdfjs/pdf.worker.min.mjs" ]]; then check /pdfjs/pdf.worker.min.mjs mjs; fi

if [[ "$failures" -gt 0 ]]; then echo "FAIL: $failures file type(s) served with a wrong Content-Type" >&2; exit 1; fi
echo "PASS: every file type in $DIST is served with a matching Content-Type and nosniff"
