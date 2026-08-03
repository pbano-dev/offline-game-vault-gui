#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$ROOT"

forbidden='(/run/user/[0-9]+|/home/[A-Za-z0-9._-]+|/var/home/[A-Za-z0-9._-]+|file:///home/|file:///var/home/|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|password[[:space:]]*=|token[[:space:]]*=)'
if grep -RInE \
    --exclude='SOURCE_MANIFEST_SHA256.txt' \
    --exclude='audit-privacy.sh' \
    --exclude-dir='.git' \
    --exclude-dir='__pycache__' \
    "$forbidden" .
then
    printf 'ERROR: possible private path or credential leak.\n' >&2
    exit 1
fi
printf '%s\n' 'Privacy scan: passed'
