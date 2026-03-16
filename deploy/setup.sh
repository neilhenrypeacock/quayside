#!/usr/bin/env bash
# First-time server setup for Quayside on a fresh Debian/Ubuntu Hetzner VPS.
# Run as root: bash setup.sh
#
# Before running, edit the two variables below.

HOSTNAME="quaysidedata.duckdns.org"   # your DuckDNS subdomain (or real domain later)
GIT_REPO="https://github.com/neilhenrypeacock/quayside.git"  # your repo URL

set -euo pipefail

echo "==> Installing system packages"
apt-get update -qq
apt-get install -y -qq \
    git python3 python3-venv python3-pip \
    nginx certbot python3-certbot-nginx \
    curl

echo "==> Creating quayside user"
useradd --system --create-home --shell /bin/bash quayside || echo "(user already exists)"

echo "==> Cloning repo"
sudo -u quayside git clone "$GIT_REPO" /home/quayside/app

echo "==> Creating virtualenv and installing deps"
sudo -u quayside python3 -m venv /home/quayside/app/venv
sudo -u quayside /home/quayside/app/venv/bin/pip install -q -e "/home/quayside/app[dev]"

echo "==> Creating data/uploads/output directories"
sudo -u quayside mkdir -p /home/quayside/app/data/uploads
sudo -u quayside mkdir -p /home/quayside/app/output

echo "==> Creating log directory"
mkdir -p /var/log/quayside
chown quayside:quayside /var/log/quayside

echo "==> Creating .env file (edit this with real values)"
if [ ! -f /home/quayside/app/.env ]; then
    cat > /home/quayside/app/.env <<EOF
QUAYSIDE_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
# QUAYSIDE_SMTP_USER=you@gmail.com
# QUAYSIDE_SMTP_PASS=your-app-password
# QUAYSIDE_RECIPIENTS=buyer1@example.com
EOF
    chown quayside:quayside /home/quayside/app/.env
    chmod 600 /home/quayside/app/.env
fi

echo "==> Installing systemd service"
cp /home/quayside/app/deploy/quayside.service /etc/systemd/system/quayside.service
systemctl daemon-reload
systemctl enable quayside
systemctl start quayside

echo "==> Configuring nginx"
sed "s/YOUR_HOSTNAME/$HOSTNAME/g" \
    /home/quayside/app/deploy/quayside-nginx.conf \
    > /etc/nginx/sites-available/quayside
ln -sf /etc/nginx/sites-available/quayside /etc/nginx/sites-enabled/quayside
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "==> Getting HTTPS certificate"
certbot --nginx -d "$HOSTNAME" --non-interactive --agree-tos -m "admin@$HOSTNAME" || \
    echo "WARNING: Certbot failed — make sure DNS is pointing at this server's IP first"

echo ""
echo "Done! Check status with:"
echo "  systemctl status quayside"
echo "  journalctl -u quayside -f"
