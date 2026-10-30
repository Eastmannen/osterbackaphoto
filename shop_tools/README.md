# Shop-verktyg (körs på Eskos Mac)

## Uppladdaren – `shop_upload.py`

Tar en mapp med **rena** JPEG-original från Lightroom och laddar upp en match till shoppen som **utkast**.

För varje bild:

1. Läser nyckelord `home:NN` / `away:NN` (stora/små bokstäver spelar ingen roll), tagningstid och kontrollerar GPS.
2. Skapar en **signerad version** i full upplösning (signaturen nere till höger, GPS borttagen).
3. Skapar en **förhandsbild**: högst 1200 px, stor diagonal vattenstämpel, ingen metadata.
4. Laddar upp rent original + signerad version (privat bucket) och förhandsbild (publik bucket).
5. Registrerar match, bild och taggar i databasen som `draft`.

Bilder utan taggar är helt okej – de visas ändå i galleriet. Original med GPS-position hoppas över.
Avbryts uppladdningen kan den köras igen; redan uppladdade bilder hoppas över.

### Exportera från Lightroom

JPG, verklig storlek, kvalitet 90 %, sRGB, **Alla metadata**, filnamn Original, **ingen vattenstämpel**.
Tröjnummer som nyckelord: `home:17`, `away:8`.

### Engångsinstallation

```
cd "<sökväg till repot>/shop_tools"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fyll sedan i .env
```

Lägg signaturen som `assets/signatur.png` (PNG med genomskinlig bakgrund). Utan den används en tillfällig textsignatur.

### Användning

```
source .venv/bin/activate

# Provkörning – laddar inte upp något, skapar bilder i <mappen>/provkorning/ att titta på
python3 shop_upload.py ~/Desktop/shop-test --hemmalag "Ulricehamns IFK" --bortalag "P18 IK" --provkor

# Uppladdning till TESTMILJÖN (standard)
python3 shop_upload.py ~/Desktop/shop-test --hemmalag "Ulricehamns IFK" --bortalag "P18 IK" --serie "Elitettan"

# Produktion – först efter lansering, kräver bekräftelse
python3 shop_upload.py ~/Desktop/match --hemmalag "…" --bortalag "…" --miljo produktion
```

Matchdatum tas från första bildens tagningstid (ange annars `--datum ÅÅÅÅ-MM-DD`).

### Säkerhet

- Nycklar finns bara i `shop_tools/.env`, som aldrig checkas in. Alla variabelnamn börjar med `SHOP_`
  och kan inte förväxlas med den befintliga sajtens `.env`.
- Uppladdaren ansluter som databasrollen `shop_admin`, som inte kommer åt ordrar eller kunders e-post
  och inte kan radera bilder eller ändra en bilds lagringsnycklar.
- Standard är alltid testmiljön.
