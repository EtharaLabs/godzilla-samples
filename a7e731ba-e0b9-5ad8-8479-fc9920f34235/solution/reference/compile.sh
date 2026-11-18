#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
cargo build --release --offline --locked -p yamark --bin yamark
cp target/release/yamark ./executable
