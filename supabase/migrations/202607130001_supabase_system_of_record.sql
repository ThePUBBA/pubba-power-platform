-- Only1 Power authoritative Supabase ledger.
-- Safe to rerun: tables, columns, constraints, and indexes are guarded.

create extension if not exists pgcrypto;

create table if not exists public.assets (
    id uuid primary key default gen_random_uuid(),
    asset_id text not null,
    asset_name text not null,
    technology text,
    power_mw numeric(18, 6) not null default 0,
    energy_mwh numeric(18, 6) not null default 0,
    duration_hours numeric(18, 6) not null default 0,
    location text,
    lease_cost_monthly numeric(18, 2) not null default 0,
    status text not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.simulation_results (
    id uuid primary key default gen_random_uuid(),
    idempotency_key text not null,
    request_hash text not null,
    asset_id uuid,
    location text not null,
    market text not null,
    simulation_date date,
    power_mw numeric(18, 6) not null,
    duration_hours numeric(18, 6) not null,
    round_trip_efficiency numeric(18, 8) not null,
    cycles numeric(18, 6) not null,
    charging_cost numeric(18, 2) not null,
    discharge_revenue numeric(18, 2) not null,
    storage_cost numeric(18, 2) not null,
    net_profit numeric(18, 2) not null,
    result_json jsonb not null,
    created_at timestamptz not null default now()
);

create table if not exists public.dispatch_events (
    id uuid primary key default gen_random_uuid(),
    dispatch_id text not null,
    asset_id uuid not null,
    simulation_id uuid not null,
    dispatch_timestamp timestamptz not null,
    charge_start timestamptz not null,
    charge_end timestamptz not null,
    discharge_start timestamptz not null,
    discharge_end timestamptz not null,
    market text not null,
    location text not null,
    status text not null default 'completed',
    energy_mwh numeric(18, 6) not null,
    charging_cost numeric(18, 2) not null,
    discharge_revenue numeric(18, 2) not null,
    storage_cost numeric(18, 2) not null,
    net_profit numeric(18, 2) not null,
    created_at timestamptz not null default now()
);

alter table public.assets add column if not exists id uuid default gen_random_uuid();
alter table public.assets add column if not exists asset_id text;
alter table public.assets add column if not exists asset_name text;
alter table public.assets add column if not exists technology text;
alter table public.assets add column if not exists power_mw numeric(18, 6) default 0;
alter table public.assets add column if not exists energy_mwh numeric(18, 6) default 0;
alter table public.assets add column if not exists duration_hours numeric(18, 6) default 0;
alter table public.assets add column if not exists location text;
alter table public.assets add column if not exists lease_cost_monthly numeric(18, 2) default 0;
alter table public.assets add column if not exists status text default 'active';
alter table public.assets add column if not exists created_at timestamptz default now();
alter table public.assets add column if not exists updated_at timestamptz default now();

alter table public.simulation_results add column if not exists id uuid default gen_random_uuid();
alter table public.simulation_results add column if not exists idempotency_key text;
alter table public.simulation_results add column if not exists request_hash text;
alter table public.simulation_results add column if not exists asset_id uuid;
alter table public.simulation_results add column if not exists location text;
alter table public.simulation_results add column if not exists market text;
alter table public.simulation_results add column if not exists simulation_date date;
alter table public.simulation_results add column if not exists power_mw numeric(18, 6);
alter table public.simulation_results add column if not exists duration_hours numeric(18, 6);
alter table public.simulation_results add column if not exists round_trip_efficiency numeric(18, 8);
alter table public.simulation_results add column if not exists cycles numeric(18, 6);
alter table public.simulation_results add column if not exists charging_cost numeric(18, 2);
alter table public.simulation_results add column if not exists discharge_revenue numeric(18, 2);
alter table public.simulation_results add column if not exists storage_cost numeric(18, 2);
alter table public.simulation_results add column if not exists net_profit numeric(18, 2);
alter table public.simulation_results add column if not exists result_json jsonb;
alter table public.simulation_results add column if not exists created_at timestamptz default now();

alter table public.dispatch_events add column if not exists id uuid default gen_random_uuid();
alter table public.dispatch_events add column if not exists dispatch_id text;
alter table public.dispatch_events add column if not exists asset_id uuid;
alter table public.dispatch_events add column if not exists simulation_id uuid;
alter table public.dispatch_events add column if not exists dispatch_timestamp timestamptz;
alter table public.dispatch_events add column if not exists charge_start timestamptz;
alter table public.dispatch_events add column if not exists charge_end timestamptz;
alter table public.dispatch_events add column if not exists discharge_start timestamptz;
alter table public.dispatch_events add column if not exists discharge_end timestamptz;
alter table public.dispatch_events add column if not exists market text;
alter table public.dispatch_events add column if not exists location text;
alter table public.dispatch_events add column if not exists status text default 'completed';
alter table public.dispatch_events add column if not exists energy_mwh numeric(18, 6);
alter table public.dispatch_events add column if not exists charging_cost numeric(18, 2);
alter table public.dispatch_events add column if not exists discharge_revenue numeric(18, 2);
alter table public.dispatch_events add column if not exists storage_cost numeric(18, 2);
alter table public.dispatch_events add column if not exists net_profit numeric(18, 2);
alter table public.dispatch_events add column if not exists created_at timestamptz default now();

-- These checks intentionally fail on incompatible historical rows so operators
-- can repair data instead of silently deploying a weaker ledger schema.
alter table public.assets alter column id set not null;
alter table public.assets alter column asset_id set not null;
alter table public.assets alter column asset_name set not null;
alter table public.assets alter column power_mw set not null;
alter table public.assets alter column energy_mwh set not null;
alter table public.assets alter column duration_hours set not null;
alter table public.assets alter column lease_cost_monthly set not null;
alter table public.assets alter column status set not null;
alter table public.assets alter column created_at set not null;
alter table public.assets alter column updated_at set not null;

alter table public.simulation_results alter column id set not null;
alter table public.simulation_results alter column idempotency_key set not null;
alter table public.simulation_results alter column request_hash set not null;
alter table public.simulation_results alter column location set not null;
alter table public.simulation_results alter column market set not null;
alter table public.simulation_results alter column power_mw set not null;
alter table public.simulation_results alter column duration_hours set not null;
alter table public.simulation_results alter column round_trip_efficiency set not null;
alter table public.simulation_results alter column cycles set not null;
alter table public.simulation_results alter column charging_cost set not null;
alter table public.simulation_results alter column discharge_revenue set not null;
alter table public.simulation_results alter column storage_cost set not null;
alter table public.simulation_results alter column net_profit set not null;
alter table public.simulation_results alter column result_json set not null;
alter table public.simulation_results alter column created_at set not null;

alter table public.dispatch_events alter column id set not null;
alter table public.dispatch_events alter column dispatch_id set not null;
alter table public.dispatch_events alter column asset_id set not null;
alter table public.dispatch_events alter column simulation_id set not null;
alter table public.dispatch_events alter column dispatch_timestamp set not null;
alter table public.dispatch_events alter column charge_start set not null;
alter table public.dispatch_events alter column charge_end set not null;
alter table public.dispatch_events alter column discharge_start set not null;
alter table public.dispatch_events alter column discharge_end set not null;
alter table public.dispatch_events alter column market set not null;
alter table public.dispatch_events alter column location set not null;
alter table public.dispatch_events alter column status set not null;
alter table public.dispatch_events alter column energy_mwh set not null;
alter table public.dispatch_events alter column charging_cost set not null;
alter table public.dispatch_events alter column discharge_revenue set not null;
alter table public.dispatch_events alter column storage_cost set not null;
alter table public.dispatch_events alter column net_profit set not null;
alter table public.dispatch_events alter column created_at set not null;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where contype = 'p' and conrelid = 'public.assets'::regclass
    ) then
        alter table public.assets add constraint assets_pkey primary key (id);
    end if;
    if not exists (
        select 1 from pg_constraint
        where contype = 'p' and conrelid = 'public.simulation_results'::regclass
    ) then
        alter table public.simulation_results
            add constraint simulation_results_pkey primary key (id);
    end if;
    if not exists (
        select 1 from pg_constraint
        where contype = 'p' and conrelid = 'public.dispatch_events'::regclass
    ) then
        alter table public.dispatch_events
            add constraint dispatch_events_pkey primary key (id);
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'assets_asset_id_key' and conrelid = 'public.assets'::regclass
    ) then
        alter table public.assets add constraint assets_asset_id_key unique (asset_id);
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'simulation_results_idempotency_key_key'
          and conrelid = 'public.simulation_results'::regclass
    ) then
        alter table public.simulation_results
            add constraint simulation_results_idempotency_key_key unique (idempotency_key);
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'dispatch_events_dispatch_id_key'
          and conrelid = 'public.dispatch_events'::regclass
    ) then
        alter table public.dispatch_events
            add constraint dispatch_events_dispatch_id_key unique (dispatch_id);
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'simulation_results_asset_id_fkey'
          and conrelid = 'public.simulation_results'::regclass
    ) then
        alter table public.simulation_results
            add constraint simulation_results_asset_id_fkey
            foreign key (asset_id) references public.assets(id) on delete restrict;
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'dispatch_events_asset_id_fkey'
          and conrelid = 'public.dispatch_events'::regclass
    ) then
        alter table public.dispatch_events
            add constraint dispatch_events_asset_id_fkey
            foreign key (asset_id) references public.assets(id) on delete restrict;
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'dispatch_events_simulation_id_fkey'
          and conrelid = 'public.dispatch_events'::regclass
    ) then
        alter table public.dispatch_events
            add constraint dispatch_events_simulation_id_fkey
            foreign key (simulation_id) references public.simulation_results(id)
            on delete restrict;
    end if;
end
$$;

do $$
declare
    invalid_column text;
begin
    select format('%I.%I', table_name, column_name)
    into invalid_column
    from information_schema.columns
    where table_schema = 'public'
      and (
        (
          (
            (table_name = 'assets' and column_name in (
                'power_mw', 'energy_mwh', 'duration_hours', 'lease_cost_monthly'
            ))
            or (table_name = 'simulation_results' and column_name in (
                'power_mw', 'duration_hours', 'round_trip_efficiency', 'cycles',
                'charging_cost', 'discharge_revenue', 'storage_cost', 'net_profit'
            ))
            or (table_name = 'dispatch_events' and column_name in (
                'energy_mwh', 'charging_cost', 'discharge_revenue', 'storage_cost',
                'net_profit'
            ))
          )
          and data_type <> 'numeric'
        )
        or (
          column_name in ('created_at', 'updated_at', 'dispatch_timestamp',
                          'charge_start', 'charge_end', 'discharge_start',
                          'discharge_end')
          and data_type <> 'timestamp with time zone'
        )
        or (
          column_name in ('id', 'asset_id', 'simulation_id')
          and table_name in ('assets', 'simulation_results', 'dispatch_events')
          and not (table_name = 'assets' and column_name = 'asset_id')
          and data_type <> 'uuid'
        )
        or (
          table_name = 'simulation_results' and column_name = 'simulation_date'
          and data_type <> 'date'
        )
        or (
          table_name = 'simulation_results' and column_name = 'result_json'
          and data_type <> 'jsonb'
        )
      )
    limit 1;
    if invalid_column is not null then
        raise exception 'Required ledger column % has an incompatible PostgreSQL type',
            invalid_column;
    end if;
end
$$;

create index if not exists assets_status_idx on public.assets (status);
create index if not exists assets_location_idx on public.assets (location);
create index if not exists simulation_results_created_at_idx
    on public.simulation_results (created_at, id);
create index if not exists simulation_results_asset_id_idx
    on public.simulation_results (asset_id);
create index if not exists dispatch_events_timestamp_id_idx
    on public.dispatch_events (dispatch_timestamp, id);
create index if not exists dispatch_events_asset_timestamp_idx
    on public.dispatch_events (asset_id, dispatch_timestamp, id);
create index if not exists dispatch_events_market_idx on public.dispatch_events (market);
create index if not exists dispatch_events_location_idx on public.dispatch_events (location);
create index if not exists dispatch_events_status_idx on public.dispatch_events (status);

alter table public.assets enable row level security;
alter table public.simulation_results enable row level security;
alter table public.dispatch_events enable row level security;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists assets_set_updated_at on public.assets;
create trigger assets_set_updated_at
before update on public.assets
for each row execute function public.set_updated_at();
