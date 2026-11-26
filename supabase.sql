-- RKB Collection Manager · servidor (Supabase)
-- Se pega entero en Supabase → SQL Editor → Run. Se puede correr más de una vez.
--
-- Qué arma:
--   app_config   una sola fila: última versión, versión mínima obligatoria, días de gracia, links de descarga
--   perfiles     un perfil por usuario (email, nombre que se muestra, si es administrador)
--   anuncios     la cartelera. Cualquiera la lee (sólo lo publicado); cada usuario maneja los suyos;
--                sólo un administrador publica o rechaza.
--   flyers       carpeta pública de imágenes; cada usuario sube sólo a su subcarpeta.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- configuración / versión
create table if not exists public.app_config (
  id            int primary key default 1 check (id = 1),
  ultima        text not null default '0.8',     -- versión más nueva publicada
  minima        text,                            -- versión mínima obligatoria (null = no obliga)
  minima_desde  date default current_date,       -- desde cuándo rige la mínima
  gracia_dias   int  not null default 7,         -- días de aviso antes de bloquear
  link_mac      text,                            -- dónde se baja la versión de Mac
  link_win      text,                            -- dónde se baja la versión de Windows
  mensaje       text                             -- qué trae la versión nueva
);
insert into public.app_config (id) values (1) on conflict (id) do nothing;
alter table public.app_config enable row level security;
drop policy if exists "config: lectura pública" on public.app_config;
create policy "config: lectura pública" on public.app_config for select using (true);
-- (se edita desde el panel de Supabase: Table Editor → app_config)

-- ---------------------------------------------------------------- perfiles
create table if not exists public.perfiles (
  id      uuid primary key references auth.users (id) on delete cascade,
  email   text,
  nombre  text,
  admin   boolean not null default false,
  creado  timestamptz not null default now()
);
alter table public.perfiles enable row level security;

create or replace function public.es_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((select admin from public.perfiles where id = auth.uid()), false);
$$;

-- al registrarse alguien, se crea su perfil
create or replace function public.nuevo_usuario() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.perfiles (id, email) values (new.id, new.email) on conflict (id) do nothing;
  return new;
end $$;
drop trigger if exists al_registrarse on auth.users;
create trigger al_registrarse after insert on auth.users for each row execute function public.nuevo_usuario();

-- nadie se puede hacer administrador solo, ni cambiarse el email
create or replace function public.cuidar_perfil() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  -- desde el panel de Supabase (SQL Editor, Table Editor) no se aplica: ahí manda el dueño
  if coalesce(auth.role(), '') not in ('authenticated', 'anon') then
    return new;
  end if;
  if not public.es_admin() then
    if tg_op = 'INSERT' then
      new.admin := false;
      new.email := (select email from auth.users where id = new.id);
    else
      new.admin := old.admin;
      new.email := old.email;
    end if;
  end if;
  return new;
end $$;
drop trigger if exists cuidar_perfil on public.perfiles;
create trigger cuidar_perfil before insert or update on public.perfiles for each row execute function public.cuidar_perfil();

drop policy if exists "perfil: ver el propio" on public.perfiles;
create policy "perfil: ver el propio" on public.perfiles for select using (id = auth.uid() or public.es_admin());
drop policy if exists "perfil: crear el propio" on public.perfiles;
create policy "perfil: crear el propio" on public.perfiles for insert with check (id = auth.uid());
drop policy if exists "perfil: editar el propio" on public.perfiles;
create policy "perfil: editar el propio" on public.perfiles for update using (id = auth.uid() or public.es_admin())
  with check (id = auth.uid() or public.es_admin());

-- ---------------------------------------------------------------- anuncios
create table if not exists public.anuncios (
  id            uuid primary key default gen_random_uuid(),
  autor         uuid not null default auth.uid() references public.perfiles (id) on delete cascade,
  autor_nombre  text,
  tipo          text not null default 'Evento',
  titulo        text not null check (char_length(titulo) between 1 and 80),
  fecha         date not null,
  hora          text,
  lugar         text,
  ciudad        text,
  pais          text,                 -- código ISO de 2 letras (AR, US, NZ…)
  region        text,                 -- provincia / estado
  alcance       text not null default 'region' check (alcance in ('region', 'pais', 'mundo')),
  texto         text check (char_length(texto) <= 600),
  link          text,
  imagen        text,
  estado        text not null default 'pendiente' check (estado in ('pendiente', 'publicado', 'rechazado')),
  motivo        text,                 -- por qué se rechazó
  destacado     boolean not null default false,
  pagado        boolean not null default false,   -- para cuando se cobre con Mercado Pago
  creado        timestamptz not null default now(),
  actualizado   timestamptz
);
-- (si la tabla ya existía de una versión anterior)
alter table public.anuncios add column if not exists pais text;
alter table public.anuncios add column if not exists region text;
alter table public.anuncios add column if not exists alcance text not null default 'region';
create index if not exists anuncios_cartelera on public.anuncios (estado, fecha);
create index if not exists anuncios_lugar on public.anuncios (pais, alcance);
alter table public.anuncios enable row level security;

-- lo que manda un usuario común siempre queda "pendiente" (aunque toque la app o la API)
create or replace function public.cuidar_anuncio() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  new.actualizado := now();
  if coalesce(auth.role(), '') not in ('authenticated', 'anon') or public.es_admin() then
    return new;
  end if;
  if tg_op = 'INSERT' then
    new.autor := auth.uid();
    if (select count(*) from public.anuncios where autor = auth.uid() and estado = 'pendiente') >= 10 then
      raise exception 'Tenés demasiados anuncios en revisión. Esperá a que se aprueben.';
    end if;
    new.destacado := false;
    new.pagado := false;
  else
    new.autor := old.autor;
    new.destacado := old.destacado;
    new.pagado := old.pagado;
    new.creado := old.creado;
  end if;
  new.estado := 'pendiente';
  new.motivo := null;
  return new;
end $$;
drop trigger if exists cuidar_anuncio on public.anuncios;
create trigger cuidar_anuncio before insert or update on public.anuncios for each row execute function public.cuidar_anuncio();

drop policy if exists "anuncios: leer" on public.anuncios;
create policy "anuncios: leer" on public.anuncios for select
  using (estado = 'publicado' or autor = auth.uid() or public.es_admin());
drop policy if exists "anuncios: crear" on public.anuncios;
create policy "anuncios: crear" on public.anuncios for insert to authenticated with check (autor = auth.uid());
drop policy if exists "anuncios: editar" on public.anuncios;
create policy "anuncios: editar" on public.anuncios for update to authenticated
  using (autor = auth.uid() or public.es_admin()) with check (autor = auth.uid() or public.es_admin());
drop policy if exists "anuncios: borrar" on public.anuncios;
create policy "anuncios: borrar" on public.anuncios for delete to authenticated
  using (autor = auth.uid() or public.es_admin());

-- ---------------------------------------------------------------- imágenes (flyers)
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('flyers', 'flyers', true, 3145728, array['image/jpeg'])
on conflict (id) do update set public = true, file_size_limit = 3145728, allowed_mime_types = array['image/jpeg'];

drop policy if exists "flyers: subir a la carpeta propia" on storage.objects;
create policy "flyers: subir a la carpeta propia" on storage.objects for insert to authenticated
  with check (bucket_id = 'flyers' and (storage.foldername(name))[1] = auth.uid()::text);
drop policy if exists "flyers: borrar los propios" on storage.objects;
create policy "flyers: borrar los propios" on storage.objects for delete to authenticated
  using (bucket_id = 'flyers' and ((storage.foldername(name))[1] = auth.uid()::text or public.es_admin()));

-- ---------------------------------------------------------------- hacerte administrador
-- Después de entrar una vez desde la app con tu email, corré (con tu email):
--   update public.perfiles set admin = true where email = 'tu@email.com';
