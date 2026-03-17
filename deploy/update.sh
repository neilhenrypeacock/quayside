#!/usr/bin/env bash
# Pull latest code and restart the app.
# Run as root (or with sudo) on the server: bash /home/quayside/app/deploy/update.sh

set -euo pipefail

echo "==> Pulling latest code"
sudo -u quayside git -C /home/quayside/app pull --ff-only

echo "==> Installing any new dependencies"
sudo -u quayside /home/quayside/app/venv/bin/pip install -q -e "/home/quayside/app"

echo "==> Installing pipeline service and timer"
cp /home/quayside/app/deploy/quayside-pipeline.service /etc/systemd/system/quayside-pipeline.service
cp /home/quayside/app/deploy/quayside-pipeline.timer /etc/systemd/system/quayside-pipeline.timer
chmod +x /home/quayside/app/deploy/run_pipeline.sh
mkdir -p /var/log/quayside
chown quayside:quayside /var/log/quayside
systemctl daemon-reload
systemctl enable --now quayside-pipeline.timer

echo "==> Restarting gunicorn"
systemctl restart quayside

echo "==> Done. Status:"
systemctl status quayside --no-pager
systemctl status quayside-pipeline.timer --no-pager
