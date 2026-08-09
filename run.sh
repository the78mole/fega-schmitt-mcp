#!/usr/bin/env bash
set -a
source "$(dirname "$0")/.env"
set +a
exec uv --directory "$(dirname "$0")" run --python 3.13 fega-schmitt-mcp
