#!/usr/bin/env bash
# Pull latest code and restart the app.
# Run as root (or with sudo) on the server: bash /home/quayside/app/deploy/update.sh

set -euo pipefail

echo "==> Pulling latest code"
sudo -u quayside git -C /home/quayside/app pull --ff-only

echo "==> Installing any new dependencies"
sudo -u quayside /home/quayside/app/venv/bin/pip install -q -e "/home/quayside/app"

echo "==> Restarting gunicorn"
systemctl restart quayside

echo "==> Done. Status:"
systemctl status quayside --no-pager
