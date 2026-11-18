#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
cargo build --release --offline --locked -p bimcraft-cli --bin bimcraft-cli
cp target/release/bimcraft-cli ./executable
