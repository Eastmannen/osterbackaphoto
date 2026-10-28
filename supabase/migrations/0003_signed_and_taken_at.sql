-- =============================================================================
-- OsterbackaPhoto Shop – migrering 0003: signerad version och tagningstid
--
-- Körs i Supabase SQL-editor efter 0002_hardening.sql. Inga hemligheter.
--
-- Beslut 2026-10-28:
--   * Esko exporterar RENA original (utan signatur) från Lightroom.
--   * Uppladdaren lägger själv på signaturen och sparar två privata filer:
--       original_r2_key  = rent original (sparas för ett framtida tillval
--                          "utan signatur", säljs inte i version 1)
--       signed_r2_key    = signerad version – det som levereras i version 1
--   * Galleriet visar alla publicerade bilder i tagningsordning (taken_at).
--     Taggar är en genväg för filtrering, inte ett krav.
-- =============================================================================

begin;

alter table public.image add column taken_at timestamptz;
alter table public.image add column signed_r2_key text;
alter table public.image add constraint image_signed_r2_key_unique unique (signed_r2_key);
alter table public.image alter column signed_r2_key set not null;

comment on column public.image.original_r2_key is 'Rent original utan signatur (privat). Levereras inte i version 1.';
comment on column public.image.signed_r2_key   is 'Signerad version (privat). Det som levereras till kunden i version 1.';
comment on column public.image.taken_at        is 'Tagningstid från bildens metadata. Styr ordningen i galleriet.';

create index image_match_taken_idx on public.image (match_id, taken_at, filename);

-- Även den signerade nyckeln är oföränderlig efter att bilden skapats.
create or replace function public.prevent_image_storage_key_change()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.preview_key is distinct from old.preview_key
     or new.original_r2_key is distinct from old.original_r2_key
     or new.signed_r2_key is distinct from old.signed_r2_key then
    raise exception 'En bilds lagringsnycklar kan inte ändras (bild %)', old.id
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

drop trigger image_storage_key_immutable on public.image;
create trigger image_storage_key_immutable
  before update of preview_key, original_r2_key, signed_r2_key on public.image
  for each row execute function public.prevent_image_storage_key_change();

-- shop_admin: insert på image omfattar redan nya kolumner (tabellrättighet).
-- Ingen update-rätt på signed_r2_key eller taken_at.

commit;
