#!/usr/bin/env bash
# Runs lint + every test suite with coverage, and keeps going after a failure
# so you always see the coverage tables. Prints a pass/fail summary at the end.
#
#   ./run-tests.sh
cd "$(dirname "$0")" || exit 1
status=0

echo "=================== BACKEND: lint ==================="
(cd backend && source .venv/bin/activate && ruff check app tests) || status=1

echo
echo "=============== BACKEND: tests + coverage ==============="
# -rfE lists every failed/errored test by name at the end of the run.
(cd backend && source .venv/bin/activate && python -m pytest -rfE --cov-report=term-missing) || status=1

echo
echo "============== FRONTEND: tests + coverage ==============="
(cd frontend && npx vitest run --coverage) || status=1

echo
if [ "$status" -eq 0 ]; then
  echo "ALL GREEN"
else
  echo "SOMETHING FAILED -- scroll up: failed tests are listed under 'short test summary info' (backend) or marked FAIL (frontend)."
fi
exit "$status"
