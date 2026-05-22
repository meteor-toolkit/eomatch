#!/bin/sh
set -e
# Substitute only ${INGEST_API_KEY} — leave nginx variables ($request_method etc.) untouched.
envsubst '${INGEST_API_KEY}' \
    < /etc/nginx/nginx.conf.template \
    > /etc/nginx/nginx.conf
exec nginx -g 'daemon off;'
