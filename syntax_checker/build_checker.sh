#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TRANSLATOR_ROOT="${REPO_ROOT}/P4LTL-Translator"
OUT_DIR="${SCRIPT_DIR}/bin"
OUT_BIN="${OUT_DIR}/p4ltl_formula_checker"

mkdir -p "${OUT_DIR}"

g++ \
  -std=gnu++11 \
  -Wall \
  -Wextra \
  -Wno-deprecated \
  -I"${TRANSLATOR_ROOT}" \
  -I"${TRANSLATOR_ROOT}/build" \
  "${SCRIPT_DIR}/p4ltl_formula_checker.cpp" \
  "${TRANSLATOR_ROOT}/frontends/parsers/p4ltl/p4ltlast.cpp" \
  "${TRANSLATOR_ROOT}/build/frontends/parsers/p4ltl/p4ltlparser.cpp" \
  "${TRANSLATOR_ROOT}/build/frontends/parsers/p4ltl/p4ltllexer.cc" \
  -o "${OUT_BIN}" \
  -lfl

echo "Built ${OUT_BIN}"
