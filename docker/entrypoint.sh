#!/bin/sh
set -eu

python docker/migrate.py
exec "$@"
