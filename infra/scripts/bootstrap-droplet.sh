#!/usr/bin/env bash
# Bootstrap a fresh Ubuntu 24.04 droplet for Atlas.
#
# Idempotent — safe to re-run. Installs Docker, creates the atlas user
# and data directories, clones (or updates) the repo, and drops a
# .env stub the operator fills in before first deploy.
#
#   sudo ./bootstrap-droplet.sh

set -euo pipefail

REPO="${ATLAS_REPO:-git@github.com:Bison1330/atlas.git}"
TARGET="${ATLAS_TARGET:-/opt/atlas}"
DATA_ROOT="/var/atlas"

if [[ $EUID -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

echo "==> Updating apt"
apt-get update -y
apt-get install -y --no-install-recommends \
  ca-certificates curl git ufw fail2ban unattended-upgrades

echo "==> Installing Docker (if missing)"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

echo "==> Creating data directories"
mkdir -p "${DATA_ROOT}"/{postgres-data,redis-data,caddy-data,caddy-config}
chown -R root:root "${DATA_ROOT}"
chmod 750 "${DATA_ROOT}"

echo "==> Firewall"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "==> Cloning ${REPO} into ${TARGET}"
if [[ ! -d "${TARGET}/.git" ]]; then
  git clone "${REPO}" "${TARGET}"
else
  git -C "${TARGET}" pull --ff-only
fi

if [[ ! -f "${TARGET}/.env" ]]; then
  cp "${TARGET}/.env.example" "${TARGET}/.env"
  echo "==> .env stub created — fill in secrets before deploy.sh"
fi

echo "==> Done. Next: edit ${TARGET}/.env and run infra/scripts/deploy.sh"
