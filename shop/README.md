# Shop MVP

Shoppen byggs i grenen `feature/shop-mvp` och påverkar inte den publicerade sajten.

## Så är produktionen skyddad

- Produktionen bygger som förut med `hugo` (sektionen `[build]` i `netlify.toml`).
- Bara Deploy Preview och branch deploy av `feature/shop-mvp` kör `shop/build.sh`.
- `shop/build.sh`
  - vägrar köra i produktion och i okända kontexter,
  - tar bara med shoppen när `SHOP_ENABLED=true` **och** grenen är `feature/shop-mvp`,
  - tar bort `/cms` ur testbygget (Decap skriver alltid till `main`),
  - markerar testbygget `noindex`.
- `hugo.shop.toml` läses bara när shoppen är påslagen.

Befintliga mallar, CSS, poster, `static/cms/` (Decap) och uppladdningsskript ändras inte.

## Regressionstest före varje merge

```
bash shop/verify-build.sh            # jämför mot origin/main
```

Kräver git, python3 och Hugo 0.147.0. Testet bevisar att:

1. `hugo` på grenen ger byte för byte samma sajt som `main` (produktionen efter merge),
2. `shop/build.sh` vägrar produktion och saknad kontext,
3. testbygget med shoppen av = produktionen, utom att `/cms` är borttagen och noindex tillagd,
4. med shoppen på tillkommer/ändras bara `/shop` och `sitemap.xml`.

## Krav i kommande etapper

- Varje Netlify Function ska själv kontrollera `SHOP_ENABLED` vid varje anrop och svara "inte tillgänglig" om den inte är exakt `true`.
- `shop/verify-build.sh` ska då utökas med test att shop-API och Checkout är otillgängliga när shoppen är avstängd.
- `SHOP_ENABLED` sätts uttryckligen till `false` i Production och `true` i testkontexterna. Saknad variabel behandlas alltid som `false`.
