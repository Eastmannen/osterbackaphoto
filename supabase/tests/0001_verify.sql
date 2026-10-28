-- =============================================================================
-- OsterbackaPhoto Shop – kontroll av migrering 0001
--
-- Körs i Supabase SQL-editor EFTER 0001_init.sql. Ändrar ingenting permanent:
-- all testdata skapas i ett block som rullas tillbaka. Resultatet visas som en
-- tabell med en rad per kontroll (OK/FEL) och en sammanfattning sist.
-- =============================================================================

create temp table if not exists _kontroll (nr int, kontroll text, resultat text);
truncate _kontroll;

do $$
declare
  tabeller text[] := array['team','match','image','image_tag','price','shop_order','order_image','stripe_event'];
  r text[] := '{}';
  n int;
  t_home uuid; t_away uuid; t_other uuid; t_x uuid;
  m1 uuid; m2 uuid; i1 uuid; o1 uuid;
begin
  ---------------------------------------------------------------------------
  -- A. Struktur och åtkomst (läser bara systemtabeller)
  ---------------------------------------------------------------------------
  select count(*) into n from pg_tables where schemaname = 'public' and tablename = any (tabeller);
  r := r || case when n = 8 then 'OK|Alla 8 tabeller finns' else format('FEL|Alla 8 tabeller finns (hittade %s)', n) end;

  select count(*) into n from pg_class c join pg_namespace s on s.oid = c.relnamespace
   where s.nspname = 'public' and c.relname = any (tabeller) and c.relrowsecurity;
  r := r || case when n = 8 then 'OK|Row Level Security är på för alla tabeller' else format('FEL|Row Level Security är på för alla tabeller (%s av 8)', n) end;

  select count(*) into n from unnest(tabeller) t
   where has_table_privilege('anon', 'public.' || t, 'SELECT,INSERT,UPDATE,DELETE');
  r := r || case when n = 0 then 'OK|Webbläsaren (anon) har ingen åtkomst till tabellerna' else format('FEL|anon har åtkomst till %s tabeller', n) end;

  select count(*) into n from unnest(tabeller) t
   where has_table_privilege('authenticated', 'public.' || t, 'SELECT,INSERT,UPDATE,DELETE');
  r := r || case when n = 0 then 'OK|Inloggade användare (authenticated) har ingen åtkomst' else format('FEL|authenticated har åtkomst till %s tabeller', n) end;

  select count(*) into n from unnest(tabeller) t
   where has_table_privilege('service_role', 'public.' || t, 'SELECT')
     and has_table_privilege('service_role', 'public.' || t, 'INSERT')
     and has_table_privilege('service_role', 'public.' || t, 'UPDATE');
  r := r || case when n = 8 then 'OK|Shoppens serverkod (service_role) når alla tabeller' else format('FEL|service_role når bara %s av 8 tabeller', n) end;

  r := r || case when exists (select 1 from pg_roles where rolname = 'shop_admin' and not rolcanlogin and not rolbypassrls)
                 then 'OK|Rollen shop_admin finns, utan inloggning (aktiveras i etapp 3)'
                 else 'FEL|Rollen shop_admin saknas eller kan redan logga in' end;

  select count(*) into n from unnest(array['team','match','image','image_tag']) t
   where has_table_privilege('shop_admin', 'public.' || t, 'SELECT');
  r := r || case when n = 4 then 'OK|shop_admin kan hantera lag, matcher, bilder och taggar' else format('FEL|shop_admin når bara %s av 4 tabeller', n) end;

  select count(*) into n from unnest(array['price','shop_order','order_image','stripe_event']) t
   where has_table_privilege('shop_admin', 'public.' || t, 'SELECT,INSERT,UPDATE,DELETE');
  r := r || case when n = 0 then 'OK|shop_admin når inte ordrar, kunders e-post eller priser' else format('FEL|shop_admin når %s skyddade tabeller', n) end;

  select count(*) into n from pg_policies where schemaname = 'public' and 'shop_admin' = any (roles);
  r := r || case when n = 4 then 'OK|4 åtkomstregler (policies) för shop_admin' else format('FEL|%s åtkomstregler för shop_admin (väntat 4)', n) end;

  select count(*) into n from pg_trigger where not tgisinternal
     and tgname in ('image_tag_team_check', 'match_team_change_check', 'image_match_change_block');
  r := r || case when n = 3 then 'OK|3 skyddsregler (triggers) finns' else format('FEL|%s skyddsregler finns (väntat 3)', n) end;

  ---------------------------------------------------------------------------
  -- B. Regler med testdata – allt rullas tillbaka
  ---------------------------------------------------------------------------
  begin
    insert into public.team (name, slug) values ('Kontroll Hemma', 'kontroll-hemma-0001') returning id into t_home;
    insert into public.team (name, slug) values ('Kontroll Borta', 'kontroll-borta-0001') returning id into t_away;
    insert into public.team (name, slug) values ('Kontroll Annat', 'kontroll-annat-0001') returning id into t_other;
    insert into public.match (slug, date, home_team_id, away_team_id)
      values ('kontroll-match-0001', current_date, t_home, t_away) returning id into m1;
    insert into public.match (slug, date, home_team_id, away_team_id)
      values ('kontroll-match-0001-b', current_date, t_home, t_other) returning id into m2;
    insert into public.image (match_id, filename, preview_key, original_r2_key)
      values (m1, 'IMG_0001.jpg', 'kontroll/0001-preview.jpg', 'kontroll/0001-original.jpg') returning id into i1;

    -- Taggar
    begin
      insert into public.image_tag values (i1, t_home, 17);
      r := r || text 'OK|Tagg "hemma 17" godtas';
    exception when others then r := r || ('FEL|Tagg "hemma 17" godtas: ' || sqlerrm); end;

    begin
      insert into public.image_tag values (i1, t_away, 17);
      r := r || text 'OK|Samma nummer i bortalaget ("borta 17") godtas och hålls isär';
    exception when others then r := r || ('FEL|"borta 17" godtas: ' || sqlerrm); end;

    begin
      insert into public.image_tag values (i1, t_other, 8);
      r := r || text 'FEL|Tagg på lag som inte spelar matchen stoppas';
    exception when check_violation then r := r || text 'OK|Tagg på lag som inte spelar matchen stoppas'; end;

    begin
      insert into public.image_tag values (i1, t_home, 17);
      r := r || text 'FEL|Dubbel tagg stoppas';
    exception when unique_violation then r := r || text 'OK|Dubbel tagg stoppas'; end;

    begin
      update public.match set away_team_id = t_other where id = m1;
      r := r || text 'FEL|Matchens lag kan inte bytas när taggar finns';
    exception when check_violation then r := r || text 'OK|Matchens lag kan inte bytas när taggar finns'; end;

    begin
      update public.image set match_id = m2 where id = i1;
      r := r || text 'FEL|En bild kan inte flyttas till en annan match';
    exception when check_violation then r := r || text 'OK|En bild kan inte flyttas till en annan match'; end;

    begin
      insert into public.match (slug, date, home_team_id, away_team_id)
        values ('kontroll-samma-lag', current_date, t_home, t_home);
      r := r || text 'FEL|En match kan inte ha samma lag som hemma och borta';
    exception when check_violation then r := r || text 'OK|En match kan inte ha samma lag som hemma och borta'; end;

    -- Döljning
    begin
      update public.image set status = 'hidden' where id = i1;
      r := r || text 'FEL|Dold bild kräver tidpunkt och skäl';
    exception when check_violation then r := r || text 'OK|Dold bild kräver tidpunkt och skäl'; end;

    begin
      update public.image set status = 'hidden', hidden_at = now(), hidden_reason = 'Kontroll' where id = i1;
      r := r || text 'OK|Bild kan döljas med tidpunkt och skäl';
    exception when others then r := r || ('FEL|Bild kan döljas med tidpunkt och skäl: ' || sqlerrm); end;

    -- Pris
    begin
      insert into public.price (amount, active) values (3900, true);
      insert into public.price (amount, active) values (4900, true);
      r := r || text 'FEL|Högst ett aktivt pris åt gången';
    exception when unique_violation then r := r || text 'OK|Högst ett aktivt pris åt gången'; end;

    -- Ordrar
    insert into public.shop_order (amount, currency, stripe_session_id, access_token_hash, consent_at)
      values (3900, 'sek', 'cs_test_kontroll_0001', 'hash-kontroll-0001', now()) returning id into o1;

    begin
      insert into public.shop_order (amount, currency, stripe_session_id, access_token_hash, consent_at)
        values (3900, 'sek', 'cs_test_kontroll_0001', 'hash-kontroll-0002', now());
      r := r || text 'FEL|Samma Stripe-betalning kan inte registreras två gånger';
    exception when unique_violation then r := r || text 'OK|Samma Stripe-betalning kan inte registreras två gånger'; end;

    begin
      update public.shop_order set status = 'paid' where id = o1;
      r := r || text 'FEL|Betald order kräver betalningstidpunkt';
    exception when check_violation then r := r || text 'OK|Betald order kräver betalningstidpunkt'; end;

    begin
      insert into public.order_image values (o1, i1, 3900);
      delete from public.image where id = i1;
      r := r || text 'FEL|En köpt bild kan inte raderas';
    exception when foreign_key_violation then r := r || text 'OK|En köpt bild kan inte raderas'; end;

    begin
      insert into public.stripe_event (id, type) values ('evt_kontroll_0001', 'checkout.session.completed');
      insert into public.stripe_event (id, type) values ('evt_kontroll_0001', 'checkout.session.completed');
      r := r || text 'FEL|Samma Stripe-händelse kan bara registreras en gång';
    exception when unique_violation then r := r || text 'OK|Samma Stripe-händelse kan bara registreras en gång'; end;

    raise exception 'kontroll_klar_rulla_tillbaka';
  exception when others then
    if sqlerrm <> 'kontroll_klar_rulla_tillbaka' then
      r := r || ('FEL|Testdata kunde inte skapas: ' || sqlerrm);
    end if;
  end;

  -- Bekräfta att ingen testdata finns kvar.
  select count(*) into n from public.team where slug like 'kontroll-%-0001';
  r := r || case when n = 0 then 'OK|All testdata är borttagen' else 'FEL|Testdata finns kvar' end;

  insert into _kontroll (nr, kontroll, resultat)
  select ord::int, split_part(x, '|', 2), split_part(x, '|', 1)
  from unnest(r) with ordinality as u(x, ord);
end;
$$;

select nr, resultat, kontroll from _kontroll
union all
select 999,
       case when count(*) filter (where resultat = 'FEL') = 0 then 'OK' else 'FEL' end,
       format('SAMMANFATTNING: %s av %s kontroller godkända',
              count(*) filter (where resultat = 'OK'), count(*))
from _kontroll
order by nr;
