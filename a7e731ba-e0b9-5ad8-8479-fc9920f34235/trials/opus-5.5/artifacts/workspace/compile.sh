#!/bin/sh
set -e
cd "$(dirname "$0")"
cargo build --release --offline
cp target/release/yamark ./executable
