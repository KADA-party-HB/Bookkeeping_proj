#!/bin/sh
set -eu

if [ "${RUN_DB_MIGRATIONS:-1}" = "1" ]; then
    python docker/migrate.py
fi

exec "$@"
