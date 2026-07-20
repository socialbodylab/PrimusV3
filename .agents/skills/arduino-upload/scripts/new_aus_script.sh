#!/usr/bin/env bash
# =============================================================================
# new_aus_script.sh — Scaffold a new AUS 1.0 conforming upload script.
#
# Two modes:
#
#   1. BEGINNER (interactive, no args):
#        ./new_aus_script.sh
#      Asks a few questions and writes a ready-to-run single-board script.
#
#   2. ADVANCED (flags + presets):
#        ./new_aus_script.sh --name led-feather --preset esp32-feather \
#                            --sketch ./my_sketch --output upload.sh
#        ./new_aus_script.sh --name multi --multi-profile \
#                            --preset esp32-feather --preset esp32-feather-s3-reversetft \
#                            --sketch ./fw --output upload.sh
#
# Generated scripts source the AUS common library by path (AUS_LIB_DIR),
# so they conform to AUS 1.0 by construction. Edit the generated file freely;
# it's your script now.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROFILES_DIR="$SCRIPT_DIR/../assets/board_profiles"

# Colors for prompts (disabled if not a TTY).
if [[ -t 0 && -t 1 ]]; then
  C_BLUE='\033[1;34m'; C_GREEN='\033[1;32m'; C_YELLOW='\033[1;33m'; C_RESET='\033[0m'
else
  C_BLUE=''; C_GREEN=''; C_YELLOW=''; C_RESET=''
fi

note()  { printf "${C_BLUE}[?]${C_RESET} %s " "$*"; }
good()  { printf "${C_GREEN}[✓]${C_RESET} %s\n" "$*"; }
warn_() { printf "${C_YELLOW}[!]${C_RESET} %s\n" "$*" >&2; }
die_()  { printf "${C_YELLOW}[!]${C_RESET} %s\n" "$*" >&2; exit 1; }

usage() {
  cat <<EOF
new_aus_script.sh — scaffold an AUS 1.0 conforming upload script.

BEGINNER (interactive):
  ./new_aus_script.sh

ADVANCED (flags):
  ./new_aus_script.sh --name <name> --preset <preset> [options]

Options:
  --name <name>            Script/profile name (e.g. led-feather).
  --preset <preset>        Board preset (see --list-presets).
                           May be repeated with --multi-profile.
  --multi-profile          Generate a multi-profile script (one --board per preset).
  --fqbn <fqbn>            Override the preset's FQBN.
  --baud <n>               Override the preset's baud.
  --libs "lib1,lib2"       Override the preset's library list (comma-sep).
  --sketch <dir>           Sketch directory (default: ./<name>).
  --output <file>          Output script path (default: ./<name>_upload.sh).
  --lib-dir <dir>          Absolute path to aus_common.sh (default: auto-detect).
  --list-presets           List available board presets and exit.
  -h, --help               Show this help.
EOF
}

# --- Parse args. ---
PRESETS=()
NAME=""
MULTI_PROFILE=false
FQBN_OVERRIDE=""
BAUD_OVERRIDE=""
LIBS_OVERRIDE=""
SKETCH_DIR=""
OUTPUT=""
LIB_DIR=""
LIST_PRESETS=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)         NAME="${2:-}"; shift 2 ;;
    --preset)       PRESETS+=("${2:-}"); shift 2 ;;
    --multi-profile) MULTI_PROFILE=true; shift ;;
    --fqbn)         FQBN_OVERRIDE="${2:-}"; shift 2 ;;
    --baud)         BAUD_OVERRIDE="${2:-}"; shift 2 ;;
    --libs)         LIBS_OVERRIDE="${2:-}"; shift 2 ;;
    --sketch)       SKETCH_DIR="${2:-}"; shift 2 ;;
    --output)       OUTPUT="${2:-}"; shift 2 ;;
    --lib-dir)      LIB_DIR="${2:-}"; shift 2 ;;
    --list-presets) LIST_PRESETS=true; shift ;;
    -h|--help)      usage; exit 0 ;;
    *) die_ "Unknown option: $1 (try --help)" ;;
  esac
done

# --- List presets and exit. ---
if [[ "$LIST_PRESETS" == true ]]; then
  echo "Available board presets:"
  for f in "$PROFILES_DIR"/*.txt; do
    [[ "$(basename "$f")" == "_template.txt" ]] && continue
    local_name="$(basename "$f" .txt)"
    desc="$(grep -E '^DESC=' "$f" | head -1 | cut -d= -f2-)"
    fqbn="$(grep -E '^FQBN=' "$f" | head -1 | cut -d= -f2-)"
    printf "  %-32s %s\n" "$local_name" "${desc:-$fqbn}"
  done
  exit 0
fi

# --- Resolve path to aus_common.sh for the generated script to source. ---
if [[ -z "$LIB_DIR" ]]; then
  # Default: the aus_common.sh sitting next to this scaffolder.
  LIB_DIR="$SCRIPT_DIR"
fi
if [[ ! -f "$LIB_DIR/aus_common.sh" ]]; then
  die_ "Could not find aus_common.sh in: $LIB_DIR
Set --lib-dir to the directory containing aus_common.sh."
fi

# =============================================================================
# Interactive mode (no args at all).
# =============================================================================
if [[ $# -eq 0 && -z "$NAME" && ${#PRESETS[@]} -eq 0 ]]; then
  # Only enter interactive if literally nothing was passed.
  if [[ -t 0 ]]; then
    echo "AUS scaffolder — let's create an upload script."
    echo ""

    # List presets.
    available=()
    while IFS= read -r f; do
      [[ "$(basename "$f")" == "_template.txt" ]] && continue
      available+=("$(basename "$f" .txt)")
    done < <(ls "$PROFILES_DIR"/*.txt 2>/dev/null)

    echo "Available board presets:"
    for i in "${!available[@]}"; do
      printf "  %d) %s\n" "$((i+1))" "${available[$i]}"
    done
    echo "  (or type a custom FQBN)"
    echo ""

    note "Choose a preset (number) or type an FQBN:"
    read -r selection
    if [[ "$selection" =~ ^[0-9]+$ ]] && (( selection >= 1 && selection <= ${#available[@]} )); then
      PRESETS=("${available[$((selection-1))]}")
    else
      # Treat as a custom FQBN.
      FQBN_OVERRIDE="$selection"
      PRESETS=("esp32-feather")  # placeholder, FQBN override will take over
    fi

    note "Script/profile name [myboard]:"
    read -r NAME
    NAME="${NAME:-myboard}"

    note "Sketch directory [./${NAME}]:"
    read -r SKETCH_DIR
    SKETCH_DIR="${SKETCH_DIR:-./$NAME}"

    note "Required libraries, comma-separated (blank for none):"
    read -r libs_input
    if [[ -n "$libs_input" ]]; then
      LIBS_OVERRIDE="$libs_input"
    fi

    note "Output filename [${NAME}_upload.sh]:"
    read -r OUTPUT
    OUTPUT="${OUTPUT:-${NAME}_upload.sh}"
  else
    # Non-interactive with no args — print usage.
    usage
    exit 1
  fi
fi

# Sanity: must have a name.
[[ -n "$NAME" ]] || die_ "--name is required (or run interactively with no args)."

# Default sketch dir / output if still unset.
[[ -n "$SKETCH_DIR" ]] || SKETCH_DIR="./$NAME"
[[ -n "$OUTPUT" ]] || OUTPUT="./${NAME}_upload.sh"

# =============================================================================
# Load preset(s) and build the profile-registration block.
# =============================================================================
# Each loaded profile becomes one aus_register_board call. In single-profile
# mode the first (only) one is the default; in multi-profile mode the first is
# also the default (override with --default in the generated file if needed).

declare -a PROFILE_BLOCKS=()  # indexed array (bash 3.2 safe; -A would be associative)

_load_preset() {
  local preset_name="$1"
  local preset_file="$PROFILES_DIR/${preset_name}.txt"
  if [[ ! -f "$preset_file" ]]; then
    echo "Unknown preset: $preset_name" >&2
    echo "Available presets:" >&2
    find "$PROFILES_DIR" -maxdepth 1 -name '*.txt' ! -name '_template.txt' -exec basename {} .txt \; 2>/dev/null | sort | sed 's/^/  /' >&2
    exit 1
  fi

  # In multi-profile mode, name each profile after its preset so users can
  # select with --board <preset-name>. In single-profile mode, use "default"
  # (matching the preset file's NAME field, which simplifies the generated script).
  local effective_name
  if [[ "$MULTI_PROFILE" == true ]]; then
    # Use the part after any "esp32-" or "arduino-" prefix for a clean name,
    # but keep it unique. Simplest: use the full preset name with hyphens → ok.
    effective_name="$preset_name"
  else
    effective_name="default"
  fi

  # Parse the preset file.
  local p_name="" p_fqbn="" p_baud="" p_libs="" p_desc="" p_vids="" p_keywords=""
  # shellcheck disable=SC2034 # p_name parsed for completeness; effective_name is what's used
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    local key="${line%%=*}"
    local val="${line#*=}"
    case "$key" in
      NAME)     p_name="$val" ;;
      FQBN)     p_fqbn="$val" ;;
      BAUD)     p_baud="$val" ;;
      LIBS)     p_libs="$val" ;;
      DESC)     p_desc="$val" ;;
      VIDS)     p_vids="$val" ;;
      KEYWORDS) p_keywords="$val" ;;
    esac
  done < "$preset_file"

  # Apply overrides.
  [[ -n "$FQBN_OVERRIDE" ]] && p_fqbn="$FQBN_OVERRIDE"
  [[ -n "$BAUD_OVERRIDE" ]] && p_baud="$BAUD_OVERRIDE"
  [[ -n "$LIBS_OVERRIDE" ]] && p_libs="$LIBS_OVERRIDE"

  # Libraries are comma-separated in presets and in aus_register_board --libs
  # (so names with spaces like "Adafruit NeoPixel" survive intact). Pass through.
  local libs_csv="$p_libs"

  # Build the aus_register_board call. Collect flag/value pairs, then render
  # each as a "  --flag 'value' \\" line. Single quotes are safe here because
  # FQBNs, library names, baud rates, and descriptions never contain them.
  local pairs=()
  pairs+=("--fqbn" "$p_fqbn")
  pairs+=("--baud" "$p_baud")
  if [[ -n "$libs_csv" ]]; then
    pairs+=("--libs" "$libs_csv")
  fi
  if [[ -n "$p_desc" ]]; then
    pairs+=("--desc" "$p_desc")
  fi
  if [[ -n "$p_vids" ]]; then
    pairs+=("--vids" "$p_vids")
  fi
  if [[ -n "$p_keywords" ]]; then
    pairs+=("--keywords" "$p_keywords")
  fi

  local block="aus_register_board ${effective_name} \\"
  local idx=0
  while (( idx < ${#pairs[@]} )); do
    local flag="${pairs[$idx]}"
    local val="${pairs[$((idx+1))]}"
    block+=$'\n  '"${flag} '${val}' \\"
    idx=$((idx+2))
  done
  # Strip the trailing " \\" (space, backslash) so the last line has no continuation.
  block="${block% \\}"
  PROFILE_BLOCKS+=("$block")
}

if [[ ${#PRESETS[@]} -eq 0 ]]; then
  # No preset given; synthesize one from overrides (FQBN required).
  if [[ -z "$FQBN_OVERRIDE" ]]; then
    die_ "Either --preset or --fqbn is required."
  fi
  PRESETS=("__inline__")
  # Create a throwaway preset file inline.
  _load_preset_inline() {
    local p_fqbn="$FQBN_OVERRIDE"
    local p_baud="${BAUD_OVERRIDE:-115200}"
    # Libraries from --libs are comma-separated; pass through unchanged.
    local libs_csv="${LIBS_OVERRIDE:-}"
    local pairs=()
    pairs+=("--fqbn" "$p_fqbn")
    pairs+=("--baud" "$p_baud")
    if [[ -n "$libs_csv" ]]; then
      pairs+=("--libs" "$libs_csv")
    fi
    pairs+=("--desc" "Custom board: ${p_fqbn}")
    local block="aus_register_board default \\"
    local idx=0
    while (( idx < ${#pairs[@]} )); do
      local flag="${pairs[$idx]}"
      local val="${pairs[$((idx+1))]}"
      block+=$'\n  '"${flag} '${val}' \\"
      idx=$((idx+2))
    done
    block="${block% \\}"
    PROFILE_BLOCKS+=("$block")
  }
  _load_preset_inline
else
  for preset in "${PRESETS[@]}"; do
    _load_preset "$preset"
  done
fi

# Mark the first profile as default in multi-profile mode.
if [[ "$MULTI_PROFILE" == true || ${#PROFILE_BLOCKS[@]} -eq 1 ]]; then
  # Append --default to the first block.
  PROFILE_BLOCKS[0]="${PROFILE_BLOCKS[0]} --default"
fi

# =============================================================================
# Generate the script from the minimal template.
# =============================================================================

# Assemble the profile-registration block.
profile_section=""
for i in "${!PROFILE_BLOCKS[@]}"; do
  [[ $i -gt 0 ]] && profile_section+=$'\n\n'
  profile_section+="${PROFILE_BLOCKS[$i]}"
done

# Resolve the sketch dir to something sensible in the generated script.
# If absolute, use as-is; if relative, prepend $SCRIPT_DIR.
sketch_line=""
if [[ "$SKETCH_DIR" == /* ]]; then
  sketch_line="SKETCH_DIR=\"$SKETCH_DIR\""
else
  # Relative — anchor to the generated script's own directory.
  sketch_line="SKETCH_DIR=\"\$SCRIPT_DIR/${SKETCH_DIR#./}\""
fi

# Compute the relative path from the output dir to LIB_DIR, so the generated
# script is portable if both move together. Fall back to absolute.
output_abs="$(cd "$(dirname "$OUTPUT")" 2>/dev/null && pwd)/$(basename "$OUTPUT")" || output_abs="$OUTPUT"
lib_abs="$(cd "$LIB_DIR" && pwd)"
rel_lib=""
if [[ "$lib_abs" == "$(cd "$(dirname "$output_abs")" 2>/dev/null && pwd)"/* ]]; then
  # LIB_DIR is under the output's parent — make it relative.
  rel_lib="$(python3 -c "import os.path,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))" "$lib_abs" "$(dirname "$output_abs")" 2>/dev/null || echo "")"
fi
lib_line=""
if [[ -n "$rel_lib" && "$rel_lib" != "." ]]; then
  lib_line="AUS_LIB_DIR=\"\$SCRIPT_DIR/$rel_lib\""
else
  lib_line="AUS_LIB_DIR=\"$lib_abs\""
fi

# Write the generated script.
mkdir -p "$(dirname "$OUTPUT")"
out_basename="$(basename "$OUTPUT")"
cat > "$OUTPUT" <<EOF
#!/usr/bin/env bash
# =============================================================================
# ${out_basename} — AUS 1.0 conforming upload script.
#
# Generated by new_aus_script.sh.
# Profile: ${NAME}
# Sketch:  ${SKETCH_DIR}
#
# Edit freely — this is your script. See references/aus-spec.md for the
# contract this script satisfies and references/common-library.md for the
# full library API.
# =============================================================================
set -euo pipefail

# shellcheck disable=SC2034
AUS_SCRIPT_VERSION="1.0.0"

SCRIPT_DIR="\$(cd "\$(dirname "\$0")" && pwd)"
${lib_line}
# shellcheck disable=SC1090
source "\$AUS_LIB_DIR/aus_common.sh"

${sketch_line}

# --- Board profile(s) ---
${profile_section}

aus_parse_args "\$@"
aus_run "\$SKETCH_DIR"
EOF

chmod +x "$OUTPUT"

good "Wrote $(basename "$OUTPUT")"
echo ""
echo "  Profile:  ${NAME}"
echo "  Sketch:   ${SKETCH_DIR}"
echo "  Library:  ${lib_abs}"
echo ""
echo "Next steps:"
echo "  ./${OUTPUT} --help           # see all flags"
echo "  ./${OUTPUT} --compile        # verify-only (no board needed)"
echo "  ./${OUTPUT} --install        # install cores + libraries"
echo "  ./${OUTPUT} --ports          # list connected boards"
echo "  ./${OUTPUT} --auto           # flash the detected board"
if [[ ${#PROFILE_BLOCKS[@]} -gt 1 ]]; then
  echo ""
  echo "  Multiple profiles registered. Use --board <name> to select."
fi
