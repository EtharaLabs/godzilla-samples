#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
cargo build --release --offline --locked -p lumen-cli --bin lumen-cli
cp target/release/lumen-cli ./executable
