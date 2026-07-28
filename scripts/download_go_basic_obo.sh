#!/usr/bin/env bash
# scripts/download_go_basic_obo.sh
set -euo pipefail
mkdir -p data
curl -L -o data/go-basic.obo http://purl.obolibrary.org/obo/go/go-basic.obo
echo "Wrote data/go-basic.obo"
