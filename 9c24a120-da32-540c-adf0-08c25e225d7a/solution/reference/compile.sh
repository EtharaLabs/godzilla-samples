#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
cargo build --release --offline --locked -p pyfun --bin pyfun
cp target/release/pyfun ./executable
