#!/usr/bin/env bash
# Runs lint + every test suite with coverage, and keeps going after a failure
# so you always see the coverage tables. Prints a pass/fail summary at the end.
#
#   bash run-tests.sh              full output, including test warnings and logged errors
#   bash run-tests.sh no:warnings  same checks and tables, without the warning/stderr noise
#                                  (also accepts: quiet, -q, --quiet)
cd "$(dirname "$0")" || exit 1
status=0

pytest_flags="-rfE --cov-report=term-missing"
vitest_flags="run --coverage"
case "${1:-}" in
  no:warnings|quiet|-q|--quiet)
    # -p no:warnings drops pytest's warnings summary; --silent drops the console
    # output (React Router notices, logged errors) the frontend tests print.
    pytest_flags="-q -p no:warnings $pytest_flags"
    vitest_flags="$vitest_flags --silent"
    ;;
  "") ;;
  *) echo "Unknown option: $1 (use: no:warnings)" >&2; exit 2 ;;
esac

echo "=================== BACKEND: lint ==================="
(cd backend && source .venv/bin/activate && ruff check app tests) || status=1

echo
echo "=============== BACKEND: tests + coverage ==============="
# -rfE lists every failed/errored test by name at the end of the run.
(cd backend && source .venv/bin/activate && python -m pytest $pytest_flags) || status=1

echo
echo "============== FRONTEND: tests + coverage ==============="
(cd frontend && npx vitest $vitest_flags) || status=1

echo
if [ "$status" -eq 0 ]; then
  echo "ALL GREEN"
else
  echo "SOMETHING FAILED -- scroll up: failed tests are listed under 'short test summary info' (backend) or marked FAIL (frontend)."
fi
exit "$status"
