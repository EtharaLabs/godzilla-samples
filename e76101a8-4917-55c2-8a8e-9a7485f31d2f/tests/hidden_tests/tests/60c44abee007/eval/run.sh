#!/bin/bash
set -e
cd "$(dirname "$0")"

# Install test dependencies (no-op offline: they are preinstalled in the image)
pip install pytest pytest-timeout pytest-xdist pyyaml -q 2>/dev/null || true

# Run tests with parallel execution
python3 -m pytest "${@:-tests/}" -n auto -v --timeout=300 --tb=short --junitxml=results.xml || true
