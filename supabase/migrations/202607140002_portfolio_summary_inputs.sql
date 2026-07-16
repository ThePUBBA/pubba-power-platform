-- Auditable inputs required by the Phase 2 portfolio summary.

alter table public.dispatch_events
    add column if not exists purchased_energy_mwh numeric,
    add column if not exists sold_energy_mwh numeric,
    add column if not exists average_buy_price_per_mwh numeric,
    add column if not exists average_sell_price_per_mwh numeric,
    add column if not exists updated_at timestamptz;

-- Existing simulation-derived records store discharged energy as energy_mwh.
-- Recover purchased energy from the linked simulation efficiency where safe.
update public.dispatch_events d
set sold_energy_mwh = coalesce(d.sold_energy_mwh, d.energy_mwh),
    purchased_energy_mwh = coalesce(
        d.purchased_energy_mwh,
        case
            when s.round_trip_efficiency > 0
                then d.energy_mwh / s.round_trip_efficiency
            else null
        end
    ),
    updated_at = coalesce(d.updated_at, d.created_at, now())
from public.simulation_results s
where d.simulation_id = s.id
  and (
      d.sold_energy_mwh is null
      or d.purchased_energy_mwh is null
      or d.updated_at is null
  );

update public.dispatch_events
set sold_energy_mwh = coalesce(sold_energy_mwh, energy_mwh, 0),
    purchased_energy_mwh = coalesce(purchased_energy_mwh, 0),
    updated_at = coalesce(updated_at, created_at, now());

update public.dispatch_events
set average_buy_price_per_mwh = coalesce(
        average_buy_price_per_mwh,
        case when purchased_energy_mwh > 0
            then charging_cost / purchased_energy_mwh else null end
    ),
    average_sell_price_per_mwh = coalesce(
        average_sell_price_per_mwh,
        case when sold_energy_mwh > 0
            then discharge_revenue / sold_energy_mwh else null end
    );

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'dispatch_events_purchased_energy_nonnegative_check'
          and conrelid = 'public.dispatch_events'::regclass
    ) then
        alter table public.dispatch_events add constraint
            dispatch_events_purchased_energy_nonnegative_check
            check (purchased_energy_mwh >= 0);
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'dispatch_events_sold_energy_nonnegative_check'
          and conrelid = 'public.dispatch_events'::regclass
    ) then
        alter table public.dispatch_events add constraint
            dispatch_events_sold_energy_nonnegative_check
            check (sold_energy_mwh >= 0);
    end if;
end
$$;

alter table public.dispatch_events
    alter column purchased_energy_mwh set default 0,
    alter column purchased_energy_mwh set not null,
    alter column sold_energy_mwh set default 0,
    alter column sold_energy_mwh set not null,
    alter column updated_at set default now(),
    alter column updated_at set not null;

create index if not exists dispatch_events_portfolio_status_timestamp_idx
    on public.dispatch_events (portfolio_id, status, dispatch_timestamp, id);

drop trigger if exists dispatch_events_set_updated_at on public.dispatch_events;
create trigger dispatch_events_set_updated_at
before update on public.dispatch_events
for each row execute function public.set_updated_at();
