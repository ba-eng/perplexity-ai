#!/bin/sh
set -e

if [ -f /etc/secrets/token_pool_config.json ]; then
  cp /etc/secrets/token_pool_config.json /tmp/token_pool_config.json
  export PPLX_TOKEN_POOL_CONFIG=/tmp/token_pool_config.json
fi

exec python -m perplexity.server --port "${PORT:-8000}"
