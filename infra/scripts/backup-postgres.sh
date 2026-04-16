#!/usr/bin/env bash
# Dump the Atlas Postgres database and upload the compressed archive to S3.
#
# Designed to be run from cron, e.g. daily at 03:17:
#   17 3 * * * /opt/atlas/infra/scripts/backup-postgres.sh >> /var/log/atlas-backup.log 2>&1
#
# Requires .env with POSTGRES_* and S3_* variables, and awscli on PATH.

set -euo pipefail

cd "$(dirname "$0")/../.."
export $(grep -v '^\s*#' .env | grep -v '^\s*$' | xargs -d '\n')

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

OUT="${TMP}/atlas-${STAMP}.sql.gz"

echo "==> Dumping ${POSTGRES_DB} -> ${OUT}"
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --no-owner --no-acl \
  | gzip -9 > "${OUT}"

SIZE=$(du -h "${OUT}" | cut -f1)
echo "==> Dump size: ${SIZE}"

S3_URI="s3://${S3_BUCKET}/backups/postgres/atlas-${STAMP}.sql.gz"
echo "==> Uploading to ${S3_URI}"

AWS_ACCESS_KEY_ID="${S3_ACCESS_KEY}" \
AWS_SECRET_ACCESS_KEY="${S3_SECRET_KEY}" \
AWS_REGION="${S3_REGION}" \
aws s3 cp "${OUT}" "${S3_URI}" \
  ${S3_ENDPOINT_URL:+--endpoint-url "${S3_ENDPOINT_URL}"}

echo "==> Backup complete."
