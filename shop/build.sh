#!/bin/sh
# Byggskript för shoppens TESTMILJÖER (Deploy Preview och Branch deploy).
#
# Produktionen använder INTE detta skript. Den bygger enligt [build] i
# netlify.toml med kommandot "hugo", precis som före shoppen.
#
# - SHOP_ENABLED=true  -> bygger med shoppen (hugo.toml + hugo.shop.toml)
# - allt annat/saknas  -> bygger exakt som produktionen ("hugo")
set -eu

if [ "${SHOP_ENABLED:-false}" = "true" ]; then
  echo "shop/build.sh: SHOP_ENABLED=true – bygger med shoppen"
  exec hugo --config hugo.toml,hugo.shop.toml
else
  echo "shop/build.sh: SHOP_ENABLED saknas eller är inte true – bygger utan shoppen"
  exec hugo
fi
