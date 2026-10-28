-- =============================================================================
-- OsterbackaPhoto Shop – migrering 0002: skärpning efter granskning av etapp 2
--
-- Körs i Supabase SQL-editor efter 0001_init.sql. Inga hemligheter.
--
--   1. stripe_payment_id är unik (när den finns).
--   2. Leveransmejl kan inte markeras som skickat/skickas innan ordern är betald.
--   3. En bilds lagringsnycklar (preview_key, original_r2_key) kan aldrig ändras
--      efter att bilden skapats – oavsett roll.
--   4. shop_admin får bara uppdatera de kolumner kontrollvyn behöver.
--   5. Den som kör migreringen (postgres i SQL-editorn) får rätt att byta till
--      rollen shop_admin, så att kontrollskriptet kan testa rollen på riktigt.
-- =============================================================================

begin;

-- 1. Samma PaymentIntent kan inte hamna på två ordrar.
create unique index shop_order_stripe_payment_id_unique
  on public.shop_order (stripe_payment_id)
  where stripe_payment_id is not null;

-- 2. Leverans (sending/sent/failed) kräver att ordern är betald.
alter table public.shop_order
  add constraint shop_order_delivery_requires_payment
  check (delivery_status = 'not_sent' or paid_at is not null);

-- 3. Lagringsnycklarna är oföränderliga.
create function public.prevent_image_storage_key_change()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.preview_key is distinct from old.preview_key
     or new.original_r2_key is distinct from old.original_r2_key then
    raise exception 'En bilds lagringsnycklar kan inte ändras (bild %)', old.id
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

create trigger image_storage_key_immutable
  before update of preview_key, original_r2_key on public.image
  for each row execute function public.prevent_image_storage_key_change();

-- 4. Kolumnspecifika uppdateringsrättigheter för shop_admin.
revoke update on public.team, public.match, public.image from shop_admin;

grant update (name)
  on public.team to shop_admin;
grant update (slug, date, home_team_id, away_team_id, series, status, hidden_at, hidden_reason)
  on public.match to shop_admin;
grant update (width, height, status, hidden_at, hidden_reason)
  on public.image to shop_admin;
-- Oförändrat: insert/select på team, match, image; select/insert/update/delete på image_tag.
-- Fortfarande ingen delete på bilder och ingen åtkomst till price, ordrar eller Stripe-händelser.

-- 5. Tillåt att byta till shop_admin för test (ärver inga rättigheter automatiskt).
do $$
begin
  begin
    execute format('grant shop_admin to %I with inherit false, set true', current_user);
  exception when syntax_error then
    execute format('grant shop_admin to %I', current_user);   -- äldre Postgres-versioner
  end;
end;
$$;

commit;
