#!/usr/bin/env bash
# One-time setup for macOS notarization credentials used by build_sender_app.py.
#
# Interactive (prompts for app-specific password):
#   ./V3_6/scripts/setup_notary_profile.sh
#
# Non-interactive (password in env; do not commit or log the value):
#   APPLE_NOTARY_APP_PASSWORD='xxxx-xxxx-xxxx-xxxx' ./V3_6/scripts/setup_notary_profile.sh

set -euo pipefail

PROFILE_NAME="${PRIMUSV3_NOTARY_PROFILE:-PrimusCentral Notary}"
APPLE_ID="${PRIMUSV3_NOTARY_APPLE_ID:-dev@puckettrand.com}"
TEAM_ID="${PRIMUSV3_NOTARY_TEAM_ID:-SAV2V7GXQ5}"

if xcrun notarytool history --keychain-profile "$PROFILE_NAME" >/dev/null 2>&1; then
  echo "Notary profile already configured: $PROFILE_NAME"
  exit 0
fi

cmd=(
  xcrun notarytool store-credentials "$PROFILE_NAME"
  --apple-id "$APPLE_ID"
  --team-id "$TEAM_ID"
)

if [[ -n "${APPLE_NOTARY_APP_PASSWORD:-}" ]]; then
  cmd+=(--password "$APPLE_NOTARY_APP_PASSWORD")
fi

echo "Creating notary keychain profile: $PROFILE_NAME"
echo "Apple ID: $APPLE_ID"
echo "Team ID: $TEAM_ID"
"${cmd[@]}"

echo "Profile ready. Test with:"
echo "  xcrun notarytool history --keychain-profile \"$PROFILE_NAME\""
