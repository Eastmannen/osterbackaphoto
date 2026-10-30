-- =============================================================================
-- OsterbackaPhoto Shop – migrering 0001: grundschema
--
-- Körs i Supabase SQL-editor: först i testprojektet, i produktion först efter
-- uttryckligt godkännande. Filen innehåller inga hemligheter och inga lösenord.
-- Ändra aldrig en körd migrering – rättelser görs i en ny fil (0002_…).
--
-- Innehåll:
--   typer        publish_status, order_status, delivery_status
--   tabeller     team, match, image, image_tag, price,
--                shop_order, order_image, stripe_event
--   regler       constraints + triggers (t.ex. tagg måste tillhöra matchens lag)
--   åtkomst      RLS på alla tabeller; anon/authenticated har ingen åtkomst;
--                service_role (Netlify Functions) har tabellrättigheter;
--                rollen shop_admin (lokal uppladdare/kontrollvy) får bara
--                matcher, bilder, lag och taggar – aldrig ordrar eller e-post.
-- =============================================================================

begin;

-- -----------------------------------------------------------------------------
-- Typer
-- -----------------------------------------------------------------------------
create type public.publish_status  as enum ('draft', 'published', 'hidden', 'archived');
create type public.order_status    as enum ('pending', 'paid', 'expired', 'refunded');
create type public.delivery_status as enum ('not_sent', 'sending', 'sent', 'failed');

-- -----------------------------------------------------------------------------
-- Lag
-- -----------------------------------------------------------------------------
create table public.team (
  id          uuid primary key default gen_random_uuid(),
  name        text not null check (length(btrim(name)) > 0),
  slug        text not null unique check (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  created_at  timestamptz not null default now()
);
comment on table public.team is 'Lag som förekommer i shopmatcher, t.ex. Ulricehamns IFK.';

-- -----------------------------------------------------------------------------
-- Matcher
-- -----------------------------------------------------------------------------
create table public.match (
  id             uuid primary key default gen_random_uuid(),
  slug           text not null unique check (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  date           date not null,
  home_team_id   uuid not null references public.team (id),
  away_team_id   uuid not null references public.team (id),
  series         text,
  status         public.publish_status not null default 'draft',
  hidden_at      timestamptz,
  hidden_reason  text,
  created_at     timestamptz not null default now(),
  constraint match_teams_differ check (home_team_id <> away_team_id),
  constraint match_hidden_has_reason check (
    status <> 'hidden' or (hidden_at is not null and length(btrim(coalesce(hidden_reason, ''))) > 0)
  )
);
create index match_status_date_idx on public.match (status, date desc);
comment on table public.match is 'Shopmatcher. Endast status published visas och kan köpas.';

-- -----------------------------------------------------------------------------
-- Bilder
-- -----------------------------------------------------------------------------
create table public.image (
  id               uuid primary key default gen_random_uuid(),
  match_id         uuid not null references public.match (id) on delete restrict,
  filename         text not null check (length(btrim(filename)) > 0),
  preview_key      text not null unique,   -- nyckel i preview-bucketen; adressen byggs från R2_PREVIEW_PUBLIC_URL
  original_r2_key  text not null unique,   -- nyckel i den privata original-bucketen; läses endast av serverkod
  width            integer check (width > 0),
  height           integer check (height > 0),
  status           public.publish_status not null default 'draft',
  hidden_at        timestamptz,
  hidden_reason    text,
  created_at       timestamptz not null default now(),
  constraint image_filename_unique_per_match unique (match_id, filename),
  constraint image_hidden_has_reason check (
    status <> 'hidden' or (hidden_at is not null and length(btrim(coalesce(hidden_reason, ''))) > 0)
  )
);
create index image_match_status_idx on public.image (match_id, status);
comment on table public.image is 'Shopbilder. Originalet raderas aldrig automatiskt.';

-- -----------------------------------------------------------------------------
-- Taggar: lag + tröjnummer per bild
-- -----------------------------------------------------------------------------
create table public.image_tag (
  image_id       uuid not null references public.image (id) on delete cascade,
  team_id        uuid not null references public.team (id),
  player_number  smallint not null check (player_number between 0 and 999),
  primary key (image_id, team_id, player_number)
);
create index image_tag_team_number_idx on public.image_tag (team_id, player_number);
comment on table public.image_tag is 'Tröjnummer per lag på en bild. Samma nummer i två lag hålls isär via team_id.';

-- Regel: taggens lag måste vara hemma- eller bortalag i bildens match.
create function public.check_image_tag_team()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if not exists (
    select 1
    from public.image i
    join public.match m on m.id = i.match_id
    where i.id = new.image_id
      and new.team_id in (m.home_team_id, m.away_team_id)
  ) then
    raise exception 'Taggens lag tillhör inte bildens match (bild %, lag %)', new.image_id, new.team_id
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

create trigger image_tag_team_check
  before insert or update on public.image_tag
  for each row execute function public.check_image_tag_team();

-- Regel: en matchs lag får inte bytas om befintliga taggar då skulle peka på fel lag.
create function public.check_match_team_change()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if exists (
    select 1
    from public.image_tag t
    join public.image i on i.id = t.image_id
    where i.match_id = new.id
      and t.team_id not in (new.home_team_id, new.away_team_id)
  ) then
    raise exception 'Matchens lag kan inte bytas: det finns taggar på det tidigare laget (match %)', new.id
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

create trigger match_team_change_check
  before update of home_team_id, away_team_id on public.match
  for each row execute function public.check_match_team_change();

-- Regel: en bild kan inte flyttas till en annan match.
create function public.prevent_image_match_change()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.match_id <> old.match_id then
    raise exception 'En bild kan inte flyttas till en annan match (bild %)', old.id
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

create trigger image_match_change_block
  before update of match_id on public.image
  for each row execute function public.prevent_image_match_change();

-- -----------------------------------------------------------------------------
-- Pris (i öre). Högst ett aktivt pris åt gången.
-- -----------------------------------------------------------------------------
create table public.price (
  id          uuid primary key default gen_random_uuid(),
  amount      integer not null check (amount > 0),   -- t.ex. 3900 = 39,00 kr
  currency    text not null default 'sek' check (currency ~ '^[a-z]{3}$'),
  active      boolean not null default false,
  created_at  timestamptz not null default now()
);
create unique index price_single_active_idx on public.price ((true)) where active;
comment on table public.price is 'Styckepris i minsta valutaenhet (öre). Exakt ett aktivt pris används av kassan.';

-- -----------------------------------------------------------------------------
-- Ordrar
-- -----------------------------------------------------------------------------
create table public.shop_order (                     -- "order" är ett reserverat ord i SQL
  id                      uuid primary key default gen_random_uuid(),
  email                   text,                      -- fylls i från Stripe vid betalning
  amount                  integer not null check (amount >= 0),
  currency                text not null check (currency ~ '^[a-z]{3}$'),
  stripe_session_id       text unique,
  stripe_payment_id       text,
  status                  public.order_status not null default 'pending',
  paid_at                 timestamptz,
  delivery_status         public.delivery_status not null default 'not_sent',
  delivery_email_sent_at  timestamptz,
  access_token_hash       text not null unique,      -- hash av länken i leveransmejlet, aldrig själva token
  consent_at              timestamptz not null,      -- kundens samtycke till direkt leverans/upphörd ångerrätt
  created_at              timestamptz not null default now(),
  constraint shop_order_paid_has_time check (status not in ('paid', 'refunded') or paid_at is not null),
  constraint shop_order_sent_has_time check (delivery_status <> 'sent' or delivery_email_sent_at is not null)
);
create index shop_order_created_idx on public.shop_order (created_at desc);

create table public.order_image (
  order_id    uuid not null references public.shop_order (id) on delete cascade,
  image_id    uuid not null references public.image (id) on delete restrict,
  unit_price  integer not null check (unit_price >= 0),   -- priset vid köptillfället, i öre
  primary key (order_id, image_id)
);
create index order_image_image_idx on public.order_image (image_id);

-- Stripe-händelser som redan hanterats (skydd mot dubbel hantering vid omleverans).
create table public.stripe_event (
  id           text primary key,          -- Stripes event-id, t.ex. evt_…
  type         text not null,
  received_at  timestamptz not null default now()
);

-- -----------------------------------------------------------------------------
-- Åtkomst
-- -----------------------------------------------------------------------------

-- Row Level Security på alla tabeller. Utan policy kan anon/authenticated inget läsa.
alter table public.team         enable row level security;
alter table public.match        enable row level security;
alter table public.image        enable row level security;
alter table public.image_tag    enable row level security;
alter table public.price        enable row level security;
alter table public.shop_order   enable row level security;
alter table public.order_image  enable row level security;
alter table public.stripe_event enable row level security;

-- Webbläsaren (anon) och inloggade (authenticated) får ingen direkt åtkomst.
revoke all on public.team, public.match, public.image, public.image_tag, public.price,
              public.shop_order, public.order_image, public.stripe_event
  from anon, authenticated;

-- Netlify Functions använder service_role (förbigår RLS) och behöver tabellrättigheter,
-- eftersom nya tabeller inte exponeras automatiskt i detta projekt.
grant select, insert, update, delete on
  public.team, public.match, public.image, public.image_tag, public.price,
  public.shop_order, public.order_image, public.stripe_event
  to service_role;

-- Rollen för uppladdaren och den lokala kontrollvyn. Skapas UTAN inloggning och lösenord.
-- Inloggning aktiveras separat i etapp 3 (lösenordet läggs aldrig i repot).
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'shop_admin') then
    create role shop_admin nologin noinherit;
  end if;
end;
$$;

grant usage on schema public to shop_admin;
grant select, insert, update         on public.team, public.match, public.image to shop_admin;
grant select, insert, update, delete on public.image_tag                       to shop_admin;
-- Inga rättigheter till price, shop_order, order_image eller stripe_event.

create policy shop_admin_team      on public.team      for all to shop_admin using (true) with check (true);
create policy shop_admin_match     on public.match     for all to shop_admin using (true) with check (true);
create policy shop_admin_image     on public.image     for all to shop_admin using (true) with check (true);
create policy shop_admin_image_tag on public.image_tag for all to shop_admin using (true) with check (true);

commit;
