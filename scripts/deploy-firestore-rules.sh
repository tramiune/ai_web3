#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT_ID="${FIREBASE_PROJECT_ID:-wallpaper-6cbbe}"
RULES_FILE="${1:-firestore.rules}"

if [[ ! -f "$RULES_FILE" ]]; then
  echo "Missing $RULES_FILE" >&2
  exit 1
fi

TOKEN="$(gcloud auth print-access-token)"
CONTENT="$(python3 -c 'import json,sys; print(json.dumps(open(sys.argv[1], encoding="utf-8").read()))' "$RULES_FILE")"

CREATE_RESP="$(curl -sS -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"source\":{\"files\":[{\"name\":\"firestore.rules\",\"content\":$CONTENT}]}}" \
  "https://firebaserules.googleapis.com/v1/projects/$PROJECT_ID/rulesets")"

RULESET_NAME="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("name",""))' <<<"$CREATE_RESP")"
if [[ -z "$RULESET_NAME" ]]; then
  echo "Create ruleset failed: $CREATE_RESP" >&2
  exit 1
fi

PATCH_RESP="$(curl -sS -X PATCH \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"release\":{\"name\":\"projects/$PROJECT_ID/releases/cloud.firestore\",\"rulesetName\":\"$RULESET_NAME\"}}" \
  "https://firebaserules.googleapis.com/v1/projects/$PROJECT_ID/releases/cloud.firestore")"

echo "Deployed $RULESET_NAME"
echo "$PATCH_RESP" | python3 -m json.tool 2>/dev/null || echo "$PATCH_RESP"
