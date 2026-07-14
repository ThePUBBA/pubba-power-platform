-- Only1 Power authoritative Supabase ledger.
-- Preserves the live schema's text asset_id foreign keys and existing data.
-- Safe to rerun: tables, columns, constraints, and indexes are guarded.

create extension if not exists pgcrypto;

create table if not exists public.assets (
    id uuid primary key default gen_random_uuid(),
    asset_id text not null,
    asset_name text not null,
    technology text,
    power_mw numeric,
    energy_mwh numeric,
    duration_hours numeric,
    location text,
    lease_cost_monthly numeric default 0,
    status text default 'Available',
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table if not exists public.simulation_results (
    id uuid primary key default gen_random_uuid(),
    external_simulation_id text not null,
    request_hash text,
    asset_id text,
    location text not null,
    market text not null,
    simulation_date date not null,
    power_mw numeric not null,
    duration_hours numeric not null,
    round_trip_efficiency numeric not null,
    cycles numeric not null,
    storage_fee_per_mwh numeric default 0,
    variable_om_per_mwh numeric default 0,
    charging_cost numeric,
    discharge_revenue numeric,
    gross_arbitrage_margin numeric,
    estimated_net_margin numeric,
    charging_window_start timestamptz,
    charging_window_end timestamptz,
    discharging_window_start timestamptz,
    discharging_window_end timestamptz,
    created_at timestamptz default now()
);

create table if not exists public.dispatch_events (
    id uuid primary key default gen_random_uuid(),
    dispatch_id text not null,
    simulation_id uuid,
    asset_id text,
    market text,
    location text,
    action text default 'discharge',
    dispatch_timestamp timestamptz not null,
    charge_start timestamptz,
    charge_end timestamptz,
    discharge_start timestamptz,
    discharge_end timestamptz,
    power_mw numeric,
    energy_mwh numeric,
    charging_cost numeric default 0,
    discharge_revenue numeric default 0,
    storage_cost numeric default 0,
    net_profit numeric default 0,
    status text default 'simulated',
    created_at timestamptz default now()
);

alter table public.assets add column if not exists id uuid default gen_random_uuid();
alter table public.assets add column if not exists asset_id text;
alter table public.assets add column if not exists asset_name text;
alter table public.assets add column if not exists technology text;
alter table public.assets add column if not exists power_mw numeric;
alter table public.assets add column if not exists energy_mwh numeric;
alter table public.assets add column if not exists duration_hours numeric;
alter table public.assets add column if not exists location text;
alter table public.assets add column if not exists lease_cost_monthly numeric default 0;
alter table public.assets add column if not exists status text default 'Available';
alter table public.assets add column if not exists created_at timestamptz default now();
alter table public.assets add column if not exists updated_at timestamptz default now();

alter table public.simulation_results add column if not exists id uuid default gen_random_uuid();
alter table public.simulation_results add column if not exists external_simulation_id text;
alter table public.simulation_results add column if not exists request_hash text;
alter table public.simulation_results add column if not exists asset_id text;
alter table public.simulation_results add column if not exists location text;
alter table public.simulation_results add column if not exists market text;
alter table public.simulation_results add column if not exists simulation_date date;
alter table public.simulation_results add column if not exists power_mw numeric;
alter table public.simulation_results add column if not exists duration_hours numeric;
alter table public.simulation_results add column if not exists round_trip_efficiency numeric;
alter table public.simulation_results add column if not exists cycles numeric;
alter table public.simulation_results add column if not exists storage_fee_per_mwh numeric default 0;
alter table public.simulation_results add column if not exists variable_om_per_mwh numeric default 0;
alter table public.simulation_results add column if not exists charging_cost numeric;
alter table public.simulation_results add column if not exists discharge_revenue numeric;
alter table public.simulation_results add column if not exists gross_arbitrage_margin numeric;
alter table public.simulation_results add column if not exists estimated_net_margin numeric;
alter table public.simulation_results add column if not exists charging_window_start timestamptz;
alter table public.simulation_results add column if not exists charging_window_end timestamptz;
alter table public.simulation_results add column if not exists discharging_window_start timestamptz;
alter table public.simulation_results add column if not exists discharging_window_end timestamptz;
alter table public.simulation_results add column if not exists created_at timestamptz default now();

alter table public.dispatch_events add column if not exists id uuid default gen_random_uuid();
alter table public.dispatch_events add column if not exists dispatch_id text;
alter table public.dispatch_events add column if not exists simulation_id uuid;
alter table public.dispatch_events add column if not exists asset_id text;
alter table public.dispatch_events add column if not exists market text;
alter table public.dispatch_events add column if not exists location text;
alter table public.dispatch_events add column if not exists action text default 'discharge';
alter table public.dispatch_events add column if not exists dispatch_timestamp timestamptz;
alter table public.dispatch_events add column if not exists charge_start timestamptz;
alter table public.dispatch_events add column if not exists charge_end timestamptz;
alter table public.dispatch_events add column if not exists discharge_start timestamptz;
alter table public.dispatch_events add column if not exists discharge_end timestamptz;
alter table public.dispatch_events add column if not exists power_mw numeric;
alter table public.dispatch_events add column if not exists energy_mwh numeric;
alter table public.dispatch_events add column if not exists charging_cost numeric default 0;
alter table public.dispatch_events add column if not exists discharge_revenue numeric default 0;
alter table public.dispatch_events add column if not exists storage_cost numeric default 0;
alter table public.dispatch_events add column if not exists net_profit numeric default 0;
alter table public.dispatch_events add column if not exists status text default 'simulated';
alter table public.dispatch_events add column if not exists created_at timestamptz default now();

-- The live schema used integer cycles. Numeric preserves existing values while
-- retaining the API's existing support for fractional equivalent cycles.
alter table public.simulation_results
    alter column cycles type numeric using cycles::numeric;

-- Backfill only newly required operational identifiers/timestamps. No rows are
-- deleted and no existing asset or simulation relationships are rewritten.
update public.simulation_results
set external_simulation_id = 'legacy:' || id::text
where external_simulation_id is null;

update public.dispatch_events
set dispatch_timestamp = coalesce(charge_start, created_at, now())
where dispatch_timestamp is null;

alter table public.assets alter column id set not null;
alter table public.assets alter column asset_id set not null;
alter table public.assets alter column asset_name set not null;
alter table public.simulation_results alter column id set not null;
alter table public.simulation_results alter column external_simulation_id set not null;
alter table public.simulation_results alter column location set not null;
alter table public.simulation_results alter column market set not null;
alter table public.simulation_results alter column simulation_date set not null;
alter table public.simulation_results alter column power_mw set not null;
alter table public.simulation_results alter column duration_hours set not null;
alter table public.simulation_results alter column round_trip_efficiency set not null;
alter table public.simulation_results alter column cycles set not null;
alter table public.dispatch_events alter column id set not null;
alter table public.dispatch_events alter column dispatch_id set not null;
alter table public.dispatch_events alter column dispatch_timestamp set not null;

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
        where conname = 'simulation_results_external_simulation_id_key'
          and conrelid = 'public.simulation_results'::regclass
    ) then
        alter table public.simulation_results
            add constraint simulation_results_external_simulation_id_key
            unique (external_simulation_id);
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
            foreign key (asset_id) references public.assets(asset_id)
            on update cascade on delete restrict;
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'dispatch_events_asset_id_fkey'
          and conrelid = 'public.dispatch_events'::regclass
    ) then
        alter table public.dispatch_events
            add constraint dispatch_events_asset_id_fkey
            foreign key (asset_id) references public.assets(asset_id)
            on update cascade on delete restrict;
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
                'storage_fee_per_mwh', 'variable_om_per_mwh', 'charging_cost',
                'discharge_revenue', 'gross_arbitrage_margin',
                'estimated_net_margin'
            ))
            or (table_name = 'dispatch_events' and column_name in (
                'power_mw', 'energy_mwh', 'charging_cost', 'discharge_revenue',
                'storage_cost', 'net_profit'
            ))
          )
          and data_type <> 'numeric'
        )
        or (
          column_name in ('created_at', 'updated_at', 'dispatch_timestamp',
                          'charge_start', 'charge_end', 'discharge_start',
                          'discharge_end', 'charging_window_start',
                          'charging_window_end', 'discharging_window_start',
                          'discharging_window_end')
          and data_type <> 'timestamp with time zone'
        )
        or (
          ((column_name = 'id' and table_name in (
              'assets', 'simulation_results', 'dispatch_events'
          )) or (table_name = 'dispatch_events' and column_name = 'simulation_id'))
          and data_type <> 'uuid'
        )
        or (
          column_name = 'asset_id'
          and table_name in ('assets', 'simulation_results', 'dispatch_events')
          and data_type <> 'text'
        )
        or (
          table_name = 'simulation_results' and column_name = 'simulation_date'
          and data_type <> 'date'
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
