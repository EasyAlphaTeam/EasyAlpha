#!/usr/bin/env bash

set -euo pipefail

# Keep initialization in this service so Compose needs only three containers.
bash scripts/prestart.sh

# Preserve the image CMD and forward signals to the API process.
exec "$@"
