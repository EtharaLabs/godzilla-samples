#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export CGO_ENABLED=0 GOFLAGS=-mod=vendor GOTOOLCHAIN=local
go build -trimpath -ldflags="-s -w" -o ./executable ./cmd/declscope
