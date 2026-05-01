#!/usr/bin/env bash
# Pulls the latest version of the scheduler from GitHub and rebuilds the
# container if anything actually changed. Safe to run from cron.
#
# Usage:
#   chmod +x update.sh
#   ./update.sh
#
# Optional cron entry (every 10 min):
#   */10 * * * * cd /opt/syba-scheduler && ./update.sh >> update.log 2>&1

set -euo pipefail
cd "$(dirname "$0")"

before=$(git rev-parse HEAD 2>/dev/null || echo "none")
git fetch --quiet origin
git reset --hard --quiet origin/main
after=$(git rev-parse HEAD)

if [ "$before" != "$after" ]; then
  echo "$(date -Iseconds)  updated $before -> $after"
  # Rebuild only if files that affect the image changed; a bind-mounted HTML
  # change is picked up on next browser load without restart. We rebuild
  # unconditionally here so Dockerfile changes also land.
  docker compose up -d --build >/dev/null
fi
