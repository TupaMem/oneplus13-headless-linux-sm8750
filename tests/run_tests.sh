#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

python3 -m unittest discover -s "$ROOT/tests" -p 'test_*.py' -v
python3 "$ROOT/tests/verify_kernel_patches.py" --self-test

for script in "$ROOT/runtime/setup_micro_glibc.sh" "$ROOT/scripts/import_and_patch_lineageos.sh"; do
    bash -n "$script"
done
sh -n "$ROOT/scripts/enter_headless.sh"

gcc -std=c11 -O1 -g -pthread -Wall -Wextra -Werror \
    -fsanitize=address,undefined -fno-omit-frame-pointer \
    "$ROOT/tests/advanced_suite.c" -lm -o "$TMP_DIR/advanced_suite"
"$TMP_DIR/advanced_suite"
