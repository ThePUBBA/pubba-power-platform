-- PUBBA Power recommendation history and decision audit foundation.
-- Additive only. Apply manually after review; no existing rows are modified.

create extension if not exists pgcrypto;

create table if not exists public.recommendation_history (
    id uuid primary key default gen_random_uuid(),
    portfolio_id uuid not null,
    asset_id text not null,
    generated_at timestamptz not null,
    captured_at timestamptz not null default now(),
    market_timestamp timestamptz not null,
    market_price numeric not null,
    market_node text not null,
    opportunity_score integer not null,
    recommendation text not null,
    recommendation_direction text not null,
    estimated_charging_cost numeric,
    estimated_discharge_revenue numeric,
    estimated_gross_profit numeric,
    estimated_margin numeric,
    estimated_break_even_price numeric,
    estimated_spread numeric,
    round_trip_efficiency_assumption numeric not null,
    variable_om_assumption numeric not null,
    lease_cost_assumption numeric not null,
    telemetry_available boolean not null,
    operational_readiness text not null,
    telemetry_timestamp timestamptz,
    explanation text not null,
    drivers jsonb not null default '[]'::jsonb,
    risks jsonb not null default '[]'::jsonb,
    missing_operational_inputs jsonb not null default '[]'::jsonb,
    recommendation_engine_version text not null,
    snapshot_hash text not null,
    simulation_id uuid,
    simulation_linked_at timestamptz,
    dispatch_id uuid,
    dispatch_linked_at timestamptz,
    acknowledged_at timestamptz,
    acknowledgement_note text,
    acknowledgement_attribution text,
    updated_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    constraint recommendation_history_portfolio_id_fkey
        foreign key (portfolio_id) references public.portfolios(id)
        on update restrict on delete restrict,
    constraint recommendation_history_asset_id_fkey
        foreign key (asset_id) references public.assets(asset_id)
        on update cascade on delete restrict,
    constraint recommendation_history_simulation_id_fkey
        foreign key (simulation_id) references public.simulation_results(id)
        on update restrict on delete restrict,
    constraint recommendation_history_dispatch_id_fkey
        foreign key (dispatch_id) references public.dispatch_events(id)
        on update restrict on delete restrict,
    constraint recommendation_history_score_check
        check (opportunity_score between 0 and 100),
    constraint recommendation_history_direction_check
        check (recommendation_direction in ('charge', 'discharge', 'hold', 'insufficient_data')),
    constraint recommendation_history_efficiency_check
        check (round_trip_efficiency_assumption > 0 and round_trip_efficiency_assumption <= 1),
    constraint recommendation_history_variable_om_check
        check (variable_om_assumption >= 0),
    constraint recommendation_history_lease_cost_check
        check (lease_cost_assumption >= 0),
    constraint recommendation_history_drivers_array_check
        check (jsonb_typeof(drivers) = 'array'),
    constraint recommendation_history_risks_array_check
        check (jsonb_typeof(risks) = 'array'),
    constraint recommendation_history_missing_inputs_array_check
        check (jsonb_typeof(missing_operational_inputs) = 'array'),
    constraint recommendation_history_simulation_link_check
        check (simulation_id is not null or simulation_linked_at is null),
    constraint recommendation_history_dispatch_link_check
        check (dispatch_id is not null or dispatch_linked_at is null)
);

create index if not exists recommendation_history_portfolio_generated_idx
    on public.recommendation_history (portfolio_id, generated_at desc, id desc);
create index if not exists recommendation_history_asset_generated_idx
    on public.recommendation_history (asset_id, generated_at desc, id desc);
create index if not exists recommendation_history_direction_idx
    on public.recommendation_history (recommendation_direction, generated_at desc);
create index if not exists recommendation_history_score_idx
    on public.recommendation_history (opportunity_score desc, generated_at desc);
create index if not exists recommendation_history_snapshot_idx
    on public.recommendation_history (asset_id, snapshot_hash, captured_at desc);
create index if not exists recommendation_history_simulation_idx
    on public.recommendation_history (simulation_id) where simulation_id is not null;
create index if not exists recommendation_history_dispatch_idx
    on public.recommendation_history (dispatch_id) where dispatch_id is not null;

create or replace function public.enforce_recommendation_snapshot_immutability()
returns trigger
language plpgsql
as $$
begin
    if (
        to_jsonb(new) - array[
            'simulation_id', 'simulation_linked_at', 'dispatch_id',
            'dispatch_linked_at', 'acknowledged_at', 'acknowledgement_note',
            'acknowledgement_attribution', 'updated_at'
        ]::text[]
    ) is distinct from (
        to_jsonb(old) - array[
            'simulation_id', 'simulation_linked_at', 'dispatch_id',
            'dispatch_linked_at', 'acknowledged_at', 'acknowledgement_note',
            'acknowledgement_attribution', 'updated_at'
        ]::text[]
    ) then
        raise exception 'Historical recommendation snapshots are immutable';
    end if;
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists recommendation_history_immutable_snapshot
    on public.recommendation_history;
create trigger recommendation_history_immutable_snapshot
before update on public.recommendation_history
for each row execute function public.enforce_recommendation_snapshot_immutability();

alter table public.recommendation_history enable row level security;

comment on table public.recommendation_history is
    'Immutable advisory recommendation snapshots with explicit operator decision links.';
