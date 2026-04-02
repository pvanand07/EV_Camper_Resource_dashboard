#!/usr/bin/env bash
# Push repository secrets to GitHub using the gh CLI.
#
# Usage:
#   ./scripts/push-github-secrets.sh --env-file .env.secrets
#   ./scripts/push-github-secrets.sh --from-environment
#   ./scripts/push-github-secrets.sh --env-file .env.secrets --repo owner/repo
#
# --from-environment reads these vars if set: CORS_ORIGINS OPENROUTER_KEY
# ANALYTICS_ADMIN_KEY VPS_HOST VPS_USER VPS_SSH_KEY GH_PAT
#
# Requires: gh auth login

set -euo pipefail

REPO_ARGS=()
ENV_FILE=""
FROM_ENV=false
DEFAULT_NAMES=(
  CORS_ORIGINS OPENROUTER_KEY ANALYTICS_ADMIN_KEY
  VPS_HOST VPS_USER VPS_SSH_KEY GH_PAT
)

usage() {
  sed -n '1,20p' "$0" | tail -n +2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      ENV_FILE="${2:-}"
      shift 2
      ;;
    --from-environment)
      FROM_ENV=true
      shift
      ;;
    --repo|-R)
      REPO_ARGS=(-R "${2:-}")
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      ;;
  esac
done

if ! gh auth status &>/dev/null; then
  echo "error: gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

if [[ -n "$ENV_FILE" && "$FROM_ENV" == true ]]; then
  echo "error: use either --env-file or --from-environment, not both" >&2
  exit 1
fi

if [[ -z "$ENV_FILE" && "$FROM_ENV" != true ]]; then
  echo "error: specify --env-file PATH or --from-environment" >&2
  exit 1
fi

if [[ -n "$ENV_FILE" ]]; then
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "error: file not found: $ENV_FILE" >&2
    exit 1
  fi
  gh secret set -f "$ENV_FILE" "${REPO_ARGS[@]}"
  echo "Secrets synced from $ENV_FILE"
  exit 0
fi

for name in "${DEFAULT_NAMES[@]}"; do
  val="${!name:-}"
  if [[ -z "${val}" ]]; then
    echo "warning: skipping $name (not set in environment)" >&2
    continue
  fi
  gh secret set "$name" "${REPO_ARGS[@]}" <<<"$val"
  echo "Set $name"
done

echo "Done."
