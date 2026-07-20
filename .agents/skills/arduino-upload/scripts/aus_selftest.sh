#!/usr/bin/env bash
# =============================================================================
# aus_selftest.sh — Validate that a script conforms to AUS 1.0.
#
# Mechanically checks the parts of the spec that can be verified without a
# board or arduino-cli installed:
#   - --version output declares AUS 1.0
#   - --help exits 0 and prints something
#   - --ports-json produces valid JSON matching the §5 schema
#   - Required flags are accepted (not rejected as unknown)
#   - Mutual-exclusion rules are enforced
#   - AUS_SPEC_VERSION is declared internally
#
# What it does NOT check (requires human review):
#   - Correct exit codes for every scenario (only spot-checks a few)
#   - Log format adherence
#   - Portability (no bash 4+ constructs)
#   - Idempotency of install
#
# Usage:
#   ./aus_selftest.sh ./my_upload.sh
#   ./aus_selftest.sh ./my_upload.sh --quiet
#
# Exit codes: 0 = all checks passed, 1 = at least one check failed.
# =============================================================================
set -uo pipefail

# Colors.
if [[ -t 1 ]]; then
  C_GREEN='\033[1;32m'; C_RED='\033[1;31m'; C_YELLOW='\033[1;33m'; C_RESET='\033[0m'
else
  C_GREEN=''; C_RED=''; C_YELLOW=''; C_RESET=''
fi

QUIET=false
if [[ "${2:-}" == "--quiet" || "${1:-}" == "--quiet" ]]; then
  QUIET=true
fi

TARGET="${1:-}"
if [[ -z "$TARGET" || "$TARGET" == "--quiet" ]]; then
  echo "Usage: $0 <path-to-upload-script> [--quiet]"
  exit 1
fi

if [[ ! -x "$TARGET" && ! -f "$TARGET" ]]; then
  echo "Not found or not executable: $TARGET"
  exit 1
fi

# If not executable, try bash explicitly.
run() {
  if [[ -x "$TARGET" ]]; then
    "$TARGET" "$@"
  else
    bash "$TARGET" "$@"
  fi
}

PASS=0
FAIL=0
check_pass() { printf "${C_GREEN}✔${C_RESET} %s\n" "$1"; PASS=$((PASS+1)); }
check_fail() { printf "${C_RED}✘${C_RESET} %s\n" "$1"; FAIL=$((FAIL+1)); }
check_info() { [[ "$QUIET" == true ]] && return 0; printf "${C_YELLOW}→${C_RESET} %s\n" "$1"; }

# Use a tmp dir for any artifacts.
TMPDIR_SELF="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_SELF"' EXIT

echo "AUS 1.0 conformance check: $TARGET"
echo ""

# --- Check 1: --version declares AUS 1.0 ---
check_info "Checking --version output..."
version_out="$(run --version 2>/dev/null || true)"
if echo "$version_out" | grep -qE '\(AUS 1\.0\)'; then
  check_pass "--version declares AUS 1.0 ($version_out)"
else
  check_fail "--version should print '<author-version> (AUS 1.0)'; got: $version_out"
fi

# --- Check 2: --help exits 0 and prints something ---
check_info "Checking --help..."
help_exit=0
help_out="$(run --help 2>&1)" || help_exit=$?
if [[ $help_exit -eq 0 && -n "$help_out" ]]; then
  check_pass "--help exits 0 and prints usage"
else
  check_fail "--help should exit 0 and print usage (got exit $help_exit)"
fi

# --- Check 3: unknown flag is rejected ---
check_info "Checking unknown-flag rejection..."
unknown_exit=0
# shellcheck disable=SC2034 # exit code is what we check
unknown_out="$(run --aus-definitely-not-real 2>&1)" || unknown_exit=$?
if [[ $unknown_exit -ne 0 ]]; then
  check_pass "Unknown flag rejected with non-zero exit"
else
  check_fail "Unknown flag should be rejected (exit was 0)"
fi

# --- Check 4: --auto + --all mutex ---
check_info "Checking --auto + --all mutual exclusion..."
mutex_exit=0
# shellcheck disable=SC2034 # exit code is what we check
mutex_out="$(run --auto --all 2>&1)" || mutex_exit=$?
if [[ $mutex_exit -eq 1 ]]; then
  check_pass "--auto + --all rejected with exit 1"
else
  check_fail "--auto + --all should be rejected with exit 1 (got $mutex_exit)"
fi

# --- Check 5: --ports + --ports-json mutex ---
check_info "Checking --ports + --ports-json mutual exclusion..."
mutex2_exit=0
# shellcheck disable=SC2034 # exit code is what we check
mutex2_out="$(run --ports --ports-json 2>&1)" || mutex2_exit=$?
if [[ $mutex2_exit -eq 1 ]]; then
  check_pass "--ports + --ports-json rejected with exit 1"
else
  check_fail "--ports + --ports-json should be rejected with exit 1 (got $mutex2_exit)"
fi

# --- Check 6: --ports-json produces valid JSON (if python3 + arduino-cli mockable) ---
# This requires arduino-cli to be on PATH. If it's not, skip with a note.
check_info "Checking --ports-json output (requires arduino-cli)..."
if ! command -v arduino-cli &>/dev/null; then
  check_info "(skipped: arduino-cli not installed)"
elif ! command -v python3 &>/dev/null; then
  check_info "(skipped: python3 not installed)"
else
  json_exit=0
  json_out="$(run --ports-json 2>/dev/null)" || json_exit=$?
  if [[ $json_exit -ne 0 ]]; then
    check_fail "--ports-json exited $json_exit (expected 0)"
  elif [[ -z "$json_out" ]]; then
    check_fail "--ports-json produced no output"
  else
    # Validate JSON and schema. Write the validator to a temp file to avoid
    # shell-escaping issues with the Python source.
    validator="$TMPDIR_SELF/validate.py"
    cat > "$validator" <<'PYEOF'
import json, sys
try:
    data = json.loads(sys.stdin.read())
except Exception as e:
    print("INVALID_JSON: " + str(e))
    sys.exit(0)
required_top = ["spec_version", "script_version", "target_fqbn", "ports", "candidates", "others"]
missing = [k for k in required_top if k not in data]
if missing:
    print("MISSING_TOP_KEYS: " + str(missing))
    sys.exit(0)
if data["spec_version"] != "1.0":
    print("BAD_SPEC_VERSION: " + str(data["spec_version"]))
    sys.exit(0)
for p in data["ports"]:
    for k in ["address", "label", "protocol", "candidate"]:
        if k not in p:
            print("PORT_MISSING_KEY: " + k)
            sys.exit(0)
print("VALID")
PYEOF
    validation="$(printf '%s' "$json_out" | python3 "$validator" 2>&1 || echo "PYTHON_ERROR")"
    if [[ "$validation" == "VALID" ]]; then
      check_pass "--ports-json emits valid AUS 1.0 schema"
    else
      check_fail "--ports-json schema invalid: $validation"
    fi
  fi
fi

# --- Check 7: AUS_SPEC_VERSION or AUS conformance referenced in source ---
# A generated script that sources aus_common.sh is conforming by construction;
# accept either a direct AUS_SPEC_VERSION declaration, an "(AUS x.y)" version
# string, or sourcing of aus_common.sh.
check_info "Checking AUS conformance in source..."
if grep -qE 'AUS_SPEC_VERSION=|AUS 1\.0|aus_common\.sh' "$TARGET" 2>/dev/null; then
  check_pass "Source declares or sources AUS 1.0"
else
  check_fail "Source should reference AUS_SPEC_VERSION, '(AUS 1.0)', or source aus_common.sh"
fi

# --- Check 8: --board with unknown profile exits 5 ---
check_info "Checking unknown profile exit code..."
unknown_board_exit=0
# shellcheck disable=SC2034 # exit code is what we check
unknown_board_out="$(run --board __aus_nonexistent_profile --compile 2>&1)" || unknown_board_exit=$?
if [[ $unknown_board_exit -eq 5 ]]; then
  check_pass "Unknown profile exits 5"
elif [[ $unknown_board_exit -eq 1 ]]; then
  check_info "(unknown profile exits 1 — acceptable if script uses generic failure, spec prefers 5)"
else
  check_fail "Unknown profile should exit 5 (or 1); got $unknown_board_exit"
fi

# --- Check 9: portability — no bash 4+ constructs ---
check_info "Checking bash 4+ constructs (portability)..."
portability_issues=""
if grep -nE 'declare -A|\bmapfile\b|\breadarray\b' "$TARGET" 2>/dev/null | grep -v '^\s*#'; then
  portability_issues+="bash-4-constructs "
fi
# ${var,,} lowercase — tricky to grep without false positives; look for the pattern
# in a non-comment context.
if grep -nE '\$\{[a-zA-Z_][a-zA-Z_0-9]*,,\}|\$\{[a-zA-Z_][a-zA-Z_0-9]*\^\^\}' "$TARGET" 2>/dev/null | grep -v '^\s*#'; then
  portability_issues+="case-folding "
fi
if [[ -z "$portability_issues" ]]; then
  check_pass "No bash 4+ constructs detected"
else
  check_fail "Bash 4+ constructs found: $portability_issues"
fi

# --- Check 10: shebang is portable ---
check_info "Checking shebang..."
shebang="$(head -1 "$TARGET")"
if [[ "$shebang" == "#!/usr/bin/env bash" ]]; then
  check_pass "Shebang is #!/usr/bin/env bash"
else
  check_fail "Shebang should be '#!/usr/bin/env bash'; got: $shebang"
fi

echo ""
echo "Results: ${C_GREEN}$PASS passed${C_RESET}, ${C_RED}$FAIL failed${C_RESET}"
if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
