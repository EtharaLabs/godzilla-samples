#!/bin/sh
set -e
cd "$(dirname "$0")"
cargo build --release --offline
cp target/release/lumen ./executable.new
mv -f ./executable.new ./executable
