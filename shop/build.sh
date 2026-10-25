#!/bin/sh
# Byggskript för shoppens TESTMILJÖER (Deploy Preview och branch deploy av
# feature/shop-mvp).
#
# Produktionen använder INTE detta skript. Den bygger enligt [build] i
# netlify.toml med kommandot "hugo", precis som före shoppen.
#
# Skydd:
#  1. Vägrar köra i produktion (CONTEXT=production) och i okända kontexter.
#  2. Shoppen tas bara med om SHOP_ENABLED=true OCH grenen är feature/shop-mvp.
#     Allt annat bygger exakt som produktionen.
#  3. Tar bort /cms ur testbygget. Decap skriver alltid till main och får
#     aldrig kunna användas från en testadress.
#  4. Markerar hela testbygget noindex (syns inte i sökmotorer).
set -eu

SHOP_BRANCH="feature/shop-mvp"
ctx="${CONTEXT:-}"
branch="${HEAD:-${BRANCH:-}}"

echo "shop/build.sh: kontext='${ctx}' gren='${branch}'"

# Skydd 1: aldrig i produktion, bara i kända testkontexter.
case "$ctx" in
  deploy-preview|branch-deploy) ;;
  production)
    echo "FEL: shop/build.sh får aldrig köras i produktion." >&2
    exit 1 ;;
  *)
    echo "FEL: okänd kontext '${ctx}'. Avbryter." >&2
    exit 1 ;;
esac

# Skydd 2: shoppen bara med flaggan på och rätt gren.
if [ "${SHOP_ENABLED:-false}" = "true" ] && [ "$branch" = "$SHOP_BRANCH" ]; then
  echo "shop/build.sh: bygger MED shoppen"
  hugo --config hugo.toml,hugo.shop.toml
else
  echo "shop/build.sh: bygger UTAN shoppen (som produktionen)"
  hugo
fi

# Skydd 3: ingen Decap-admin i testmiljön.
rm -rf public/cms
echo "shop/build.sh: /cms borttagen ur testbygget"

# Skydd 4: noindex för hela testbygget.
printf '/*\n  X-Robots-Tag: noindex, nofollow\n' > public/_headers
echo "shop/build.sh: noindex satt för testbygget"
