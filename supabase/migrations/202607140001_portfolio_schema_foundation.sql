-- Phase 2 portfolio ownership foundation.
-- Expand -> seed/backfill -> constrain. Safe to rerun and safe for live rows.

create extension if not exists pgcrypto;

create table if not exists public.portfolios (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    code text not null,
    default_market text not null,
    reporting_timezone text not null,
    currency_code text not null default 'USD',
    status text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists portfolios_code_key
    on public.portfolios (code);

insert into public.portfolios (
    name, code, default_market, reporting_timezone, currency_code, status
)
values (
    'Only1 Power', 'ONLY1', 'CAISO', 'America/Los_Angeles', 'USD', 'active'
)
on conflict (code) do nothing;

alter table public.assets
    add column if not exists portfolio_id uuid,
    add column if not exists retired_at timestamptz,
    add column if not exists retirement_reason text,
    add column if not exists updated_at timestamptz default now(),
    add column if not exists revision integer default 1;

alter table public.simulation_results
    add column if not exists portfolio_id uuid;

alter table public.dispatch_events
    add column if not exists portfolio_id uuid;

-- Normalize only known legacy values. Unexpected values intentionally fail the
-- later validated constraint instead of being silently reclassified.
update public.assets
set status = case lower(trim(coalesce(status, '')))
    when '' then 'active'
    when 'available' then 'active'
    when 'active' then 'active'
    when 'draft' then 'draft'
    when 'unavailable' then 'unavailable'
    when 'maintenance' then 'maintenance'
    when 'retired' then 'retired'
    else status
end;

update public.assets
set updated_at = coalesce(updated_at, created_at, now()),
    revision = coalesce(revision, 1);

do $$
declare
    default_portfolio_id uuid;
begin
    select id into strict default_portfolio_id
    from public.portfolios
    where code = 'ONLY1';

    update public.assets
    set portfolio_id = default_portfolio_id
    where portfolio_id is null;

    update public.simulation_results
    set portfolio_id = default_portfolio_id
    where portfolio_id is null;

    update public.dispatch_events
    set portfolio_id = default_portfolio_id
    where portfolio_id is null;
end
$$;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'portfolios_status_check'
          and conrelid = 'public.portfolios'::regclass
    ) then
        alter table public.portfolios add constraint portfolios_status_check
            check (status in ('active', 'inactive'));
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'assets_portfolio_id_fkey'
          and conrelid = 'public.assets'::regclass
    ) then
        alter table public.assets add constraint assets_portfolio_id_fkey
            foreign key (portfolio_id) references public.portfolios(id)
            on update restrict on delete restrict;
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'simulation_results_portfolio_id_fkey'
          and conrelid = 'public.simulation_results'::regclass
    ) then
        alter table public.simulation_results
            add constraint simulation_results_portfolio_id_fkey
            foreign key (portfolio_id) references public.portfolios(id)
            on update restrict on delete restrict;
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'dispatch_events_portfolio_id_fkey'
          and conrelid = 'public.dispatch_events'::regclass
    ) then
        alter table public.dispatch_events
            add constraint dispatch_events_portfolio_id_fkey
            foreign key (portfolio_id) references public.portfolios(id)
            on update restrict on delete restrict;
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'assets_status_check'
          and conrelid = 'public.assets'::regclass
    ) then
        alter table public.assets add constraint assets_status_check
            check (status in (
                'draft', 'active', 'unavailable', 'maintenance', 'retired'
            )) not valid;
        alter table public.assets validate constraint assets_status_check;
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'assets_revision_positive_check'
          and conrelid = 'public.assets'::regclass
    ) then
        alter table public.assets add constraint assets_revision_positive_check
            check (revision > 0);
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'assets_retired_at_check'
          and conrelid = 'public.assets'::regclass
    ) then
        alter table public.assets add constraint assets_retired_at_check
            check (status <> 'retired' or retired_at is not null);
    end if;
end
$$;

create index if not exists assets_portfolio_status_idx
    on public.assets (portfolio_id, status);
create index if not exists simulation_results_portfolio_created_idx
    on public.simulation_results (portfolio_id, created_at, id);
create index if not exists dispatch_events_portfolio_timestamp_idx
    on public.dispatch_events (portfolio_id, dispatch_timestamp, id);

alter table public.assets alter column status set default 'active';
alter table public.assets alter column status set not null;
alter table public.assets alter column updated_at set default now();
alter table public.assets alter column updated_at set not null;
alter table public.assets alter column revision set default 1;
alter table public.assets alter column revision set not null;
alter table public.assets alter column portfolio_id set not null;
alter table public.simulation_results alter column portfolio_id set not null;
alter table public.dispatch_events alter column portfolio_id set not null;

alter table public.portfolios enable row level security;

-- public.set_updated_at() is created by the ledger foundation migration.
drop trigger if exists portfolios_set_updated_at on public.portfolios;
create trigger portfolios_set_updated_at
before update on public.portfolios
for each row execute function public.set_updated_at();

