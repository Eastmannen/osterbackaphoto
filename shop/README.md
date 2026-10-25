# Shop MVP

Shoppen byggs i grenen `feature/shop-mvp` och påverkar inte den publicerade sajten.

- Produktionen bygger som förut med `hugo` (sektionen `[build]` i `netlify.toml`).
- Testmiljöerna (Deploy Preview och Branch deploy) kör `shop/build.sh`.
- `shop/build.sh` tar bara med shoppen när `SHOP_ENABLED=true`. Annars byggs sajten exakt som produktionen.
- `hugo.shop.toml` läses bara när shoppen är påslagen.

Befintliga mallar, CSS, poster, `static/cms/` (Decap) och uppladdningsskript ändras inte.
Logga aldrig in på `/cms` via en testadress – Decap skriver alltid till `main`.
