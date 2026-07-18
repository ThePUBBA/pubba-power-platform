-- PUBBA Power battery telemetry foundation.
-- Additive only: creates a child table and indexes without changing existing rows.

create extension if not exists pgcrypto;

create table if not exists public.asset_telemetry (
    id uuid primary key default gen_random_uuid(),
    portfolio_id uuid not null,
    asset_id text not null,
    recorded_at timestamptz not null,
    state_of_charge_pct numeric,
    current_power_mw numeric,
    available_charge_power_mw numeric,
    available_discharge_power_mw numeric,
    available_energy_mwh numeric,
    temperature_c numeric,
    operational_status text,
    availability_status text,
    telemetry_source text not null,
    is_simulated boolean not null default false,
    created_at timestamptz not null default now(),
    constraint asset_telemetry_portfolio_id_fkey
        foreign key (portfolio_id) references public.portfolios(id)
        on update restrict on delete restrict,
    constraint asset_telemetry_asset_id_fkey
        foreign key (asset_id) references public.assets(asset_id)
        on update cascade on delete restrict,
    constraint asset_telemetry_soc_check
        check (state_of_charge_pct is null or state_of_charge_pct between 0 and 100),
    constraint asset_telemetry_charge_power_check
        check (available_charge_power_mw is null or available_charge_power_mw >= 0),
    constraint asset_telemetry_discharge_power_check
        check (available_discharge_power_mw is null or available_discharge_power_mw >= 0),
    constraint asset_telemetry_energy_check
        check (available_energy_mwh is null or available_energy_mwh >= 0),
    constraint asset_telemetry_source_check
        check (length(trim(telemetry_source)) > 0),
    constraint asset_telemetry_unique_asset_timestamp
        unique (asset_id, recorded_at)
);

create index if not exists asset_telemetry_asset_id_idx
    on public.asset_telemetry (asset_id);
create index if not exists asset_telemetry_recorded_at_idx
    on public.asset_telemetry (recorded_at desc);
create index if not exists asset_telemetry_latest_idx
    on public.asset_telemetry (asset_id, recorded_at desc, id desc);
create index if not exists asset_telemetry_portfolio_latest_idx
    on public.asset_telemetry (portfolio_id, asset_id, recorded_at desc, id desc);

create or replace view public.latest_asset_telemetry
with (security_invoker = true) as
select distinct on (portfolio_id, asset_id) *
from public.asset_telemetry
order by portfolio_id, asset_id, recorded_at desc, id desc;

alter table public.asset_telemetry enable row level security;

comment on table public.asset_telemetry is
    'Timestamped battery telemetry. Simulated observations are explicitly labeled.';
