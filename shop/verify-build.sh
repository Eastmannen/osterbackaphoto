#!/usr/bin/env bash
# Regressionstest: bevisar att shoppen inte påverkar den befintliga sajten.
#
# Körs före varje föreslagen merge:   bash shop/verify-build.sh [referens]
# Referens = det som produktionen bygger i dag (standard: origin/main).
# Kräver: git, python3 och hugo i PATH (samma version som Netlify, 0.147.0).
#
# Testar arbetskopians filer (spårade + nya, aldrig ignorerade som .env)
# i tillfälliga kopior. Repots egen public/ rörs inte. Körs aldrig i Netlify.
set -euo pipefail

REF="${1:-origin/main}"
ROOT="$(git rev-parse --show-toplevel)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAIL=0
pass(){ echo "  OK   $1"; }
fail(){ echo "  FEL  $1"; FAIL=1; }

echo "Hugo: $(hugo version | cut -d' ' -f2)  (Netlify använder v0.147.0)"
echo "Referens: $REF ($(git -C "$ROOT" rev-parse --short "$REF"))"

# Referens = produktionens bygge av REF.
mkdir -p "$TMP/ref-src"
git -C "$ROOT" archive "$REF" | tar -x -C "$TMP/ref-src"
(cd "$TMP/ref-src" && hugo --quiet -d "$TMP/ref") >/dev/null

# Kopia av arbetskopian (utan ignorerade filer som .env och public/).
copy_tree(){ mkdir -p "$1"; (cd "$ROOT" && git ls-files -co --exclude-standard -z | xargs -0 tar -cf -) | tar -xf - -C "$1"; }

# Jämför två byggen: skriver avvikande sökvägar (A=tillkommen, D=borttagen, M=ändrad).
compare(){ python3 - "$1" "$2" << 'PY'
import hashlib, os, sys
def tree(d):
    out = {}
    for r, _, fs in os.walk(d):
        for f in fs:
            p = os.path.join(r, f)
            out[os.path.relpath(p, d)] = hashlib.sha256(open(p, 'rb').read()).hexdigest()
    return out
a, b = tree(sys.argv[1]), tree(sys.argv[2])
for p in sorted(set(a) | set(b)):
    if p not in a: print("A", p)
    elif p not in b: print("D", p)
    elif a[p] != b[p]: print("M", p)
PY
}

# Kör shop/build.sh i en ny kopia med givna miljövariabler. Utdata i $TMP/out-NAMN.
run_build(){ local name="$1"; shift; local src="$TMP/src-$name"; copy_tree "$src"
  if (cd "$src" && env -i PATH="$PATH" HOME="$HOME" "$@" sh shop/build.sh) >"$TMP/log-$name" 2>&1; then
    mv "$src/public" "$TMP/out-$name"; return 0; else return 1; fi; }

# Tillåtna skillnader i testbyggen: /cms borttagen, _headers tillagd.
only_test_diffs(){ grep -vE '^(D cms/|A _headers$)' || true; }

echo
echo "1. Produktionen efter en merge (\"hugo\" på grenen) = dagens produktion"
src="$TMP/src-prod"; copy_tree "$src"; (cd "$src" && hugo --quiet -d "$TMP/out-prod") >/dev/null
d="$(compare "$TMP/ref" "$TMP/out-prod")"
[ -z "$d" ] && pass "byte för byte identisk" || { fail "skillnader:"; echo "$d" | sed 's/^/       /'; }

echo "2. build.sh vägrar produktion och okänd kontext"
run_build prodctx CONTEXT=production HEAD=feature/shop-mvp SHOP_ENABLED=true && fail "körde med CONTEXT=production" || pass "CONTEXT=production avvisas"
run_build noctx HEAD=feature/shop-mvp SHOP_ENABLED=true && fail "körde utan CONTEXT" || pass "saknad CONTEXT avvisas"

echo "3. Testbygge med shoppen avstängd = produktion, utan /cms och med noindex"
for case_ in "unset:" "false:SHOP_ENABLED=false" "upper:SHOP_ENABLED=TRUE" "otherbranch:SHOP_ENABLED=true"; do
  name="${case_%%:*}"; var="${case_#*:}"; head="feature/shop-mvp"; [ "$name" = otherbranch ] && head="annan-gren"
  if run_build "off-$name" CONTEXT=deploy-preview HEAD="$head" $var; then
    d="$(compare "$TMP/ref" "$TMP/out-off-$name")"
    rest="$(echo "$d" | only_test_diffs)"
    if [ -n "$rest" ]; then fail "$name: oväntade skillnader:"; echo "$rest" | sed 's/^/       /'
    elif ! echo "$d" | grep -q '^D cms/'; then fail "$name: /cms finns kvar"
    elif ! grep -q 'X-Robots-Tag: noindex' "$TMP/out-off-$name/_headers"; then fail "$name: noindex saknas"
    else pass "$name: bara /cms borttagen och noindex tillagd"; fi
  else fail "$name: bygget misslyckades"; cat "$TMP/log-off-$name"; fi
done

echo "4. Testbygge med shoppen påslagen: bara /shop och sitemap.xml får tillkomma/ändras"
if run_build on CONTEXT=branch-deploy HEAD=feature/shop-mvp SHOP_ENABLED=true; then
  grep -q 'bygger MED shoppen' "$TMP/log-on" && pass "shoppen aktiverad" || fail "shoppen aktiverades inte"
  rest="$(compare "$TMP/ref" "$TMP/out-on" | only_test_diffs | grep -vE '^(A shop/|M sitemap\.xml$)' || true)"
  [ -z "$rest" ] && pass "inga skillnader utanför /shop och sitemap.xml" || { fail "oväntade skillnader:"; echo "$rest" | sed 's/^/       /'; }
  [ ! -e "$TMP/out-on/cms" ] && pass "/cms borttagen" || fail "/cms finns kvar"
else fail "bygget misslyckades"; cat "$TMP/log-on"; fi

echo
[ "$FAIL" = 0 ] && { echo "RESULTAT: ALLA TESTER GODKÄNDA"; exit 0; } || { echo "RESULTAT: TESTER MISSLYCKADES"; exit 1; }
