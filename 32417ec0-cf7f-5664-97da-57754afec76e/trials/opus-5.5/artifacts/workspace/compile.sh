#!/bin/sh
# Builds the declscope reimplementation into ./executable.
set -e
cd "$(dirname "$0")"
export CGO_ENABLED=0
export GOFLAGS=-mod=mod
go build -trimpath -o executable ./cmd/declscope
