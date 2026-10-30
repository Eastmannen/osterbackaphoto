# Shoppens databas (Supabase)

## Migreringar

Körs i ordning i Supabase **SQL Editor**, först i testprojektet `osterbackaphoto-shop-test`.
I produktion körs de först efter uttryckligt godkännande.

| Fil | Innehåll |
| --- | --- |
| `migrations/0001_init.sql` | Tabeller, regler, Row Level Security och rollen `shop_admin` (utan inloggning) |
| `migrations/0002_hardening.sql` | Unikt `stripe_payment_id`, leverans kräver betalning, oföränderliga lagringsnycklar, kolumnspecifika rättigheter för `shop_admin` |
| `migrations/0003_signed_and_taken_at.sql` | Signerad version (`signed_r2_key`, krävs och är oföränderlig) och tagningstid (`taken_at`) för galleriets ordning |

En körd migrering ändras aldrig. Rättelser görs i en ny numrerad fil.

## Kontroll

Efter varje migrering körs motsvarande fil i `tests/`. Den senaste (`tests/0003_verify.sql`) kontrollerar hela schemat,
inklusive prov som körs som rollen `shop_admin`.
Skriptet ändrar ingenting permanent och visar en rad per kontroll (OK/FEL) samt en sammanfattning.

## Hemligheter

Inga lösenord eller nycklar finns i dessa filer. Rollen `shop_admin` får inloggning och
lösenord först i etapp 3, direkt i Supabase – lösenordet sparas aldrig i repot.
