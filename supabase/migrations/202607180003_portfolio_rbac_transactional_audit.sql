-- PUBBA Power portfolio-scoped operator access and transactional auditing.
-- Additive only. Apply manually after 202607180002_operator_identity_rbac.sql.

create table if not exists public.operator_portfolio_access (
    id uuid primary key default gen_random_uuid(),
    operator_id uuid not null references public.operators(id) on update restrict on delete restrict,
    portfolio_id uuid not null references public.portfolios(id) on update restrict on delete restrict,
    role_override text,
    active boolean not null default true,
    created_at timestamptz not null default now(),
    created_by uuid not null references public.operators(id) on update restrict on delete restrict,
    updated_at timestamptz not null default now(),
    constraint operator_portfolio_access_role_check
        check (role_override is null or role_override in ('viewer', 'operator', 'approver')),
    constraint operator_portfolio_access_unique unique (operator_id, portfolio_id)
);

create index if not exists operator_portfolio_access_portfolio_idx
    on public.operator_portfolio_access (portfolio_id, active, operator_id);
create index if not exists operator_portfolio_access_operator_idx
    on public.operator_portfolio_access (operator_id, active, portfolio_id);
alter table public.operator_portfolio_access enable row level security;

create or replace function public.pubba_effective_portfolio_role(
    p_operator_id uuid, p_portfolio_id uuid
) returns text language sql stable security definer set search_path = public as $$
    select case
        when o.status <> 'active' then null
        when o.role = 'admin' then 'admin'
        when a.active then coalesce(a.role_override, o.role)
        else null
    end
    from public.operators o
    left join public.operator_portfolio_access a
      on a.operator_id = o.id and a.portfolio_id = p_portfolio_id
    where o.id = p_operator_id;
$$;

create or replace function public.pubba_require_portfolio_role(
    p_operator_id uuid, p_portfolio_id uuid, p_allowed_roles text[]
) returns text language plpgsql stable security definer set search_path = public as $$
declare v_role text;
begin
    v_role := public.pubba_effective_portfolio_role(p_operator_id, p_portfolio_id);
    if v_role is null or not (v_role = any(p_allowed_roles)) then
        raise exception 'portfolio access denied' using errcode = '42501';
    end if;
    return v_role;
end;
$$;

create or replace function public.pubba_sanitize_audit_metadata(p_metadata jsonb)
returns jsonb language sql immutable as $$
    select coalesce(p_metadata, '{}'::jsonb)
      - array['token','authorization','credential','secret','client_secret','access_token','id_token'];
$$;

create or replace function public.pubba_audited_recommendation_action(
    p_operator_id uuid,
    p_recommendation_id uuid,
    p_action text,
    p_payload jsonb default '{}'::jsonb
) returns jsonb language plpgsql security definer set search_path = public as $$
declare
    v_rec public.recommendation_history%rowtype;
    v_role text;
    v_action_name text;
    v_approval public.recommendation_approvals%rowtype;
begin
    select * into v_rec from public.recommendation_history
     where id = p_recommendation_id for update;
    if not found then raise exception 'recommendation not found' using errcode = 'P0002'; end if;

    v_role := public.pubba_require_portfolio_role(
        p_operator_id, v_rec.portfolio_id,
        case when p_action in ('approve','reject','link_dispatch')
             then array['approver','admin'] else array['operator','approver','admin'] end
    );

    if p_action = 'acknowledge' then
        if v_rec.acknowledged_at is not null then raise exception 'recommendation already acknowledged'; end if;
        update public.recommendation_history set
            acknowledged_at = now(),
            acknowledgement_note = nullif(p_payload->>'note',''),
            acknowledgement_attribution = 'operator:' || p_operator_id::text
        where id = p_recommendation_id returning * into v_rec;
        v_action_name := 'recommendation_acknowledged';
    elsif p_action = 'link_simulation' then
        if not exists (
            select 1 from public.simulation_results s
             where s.id = (p_payload->>'record_id')::uuid
               and s.portfolio_id = v_rec.portfolio_id
               and (s.asset_id is null or s.asset_id = v_rec.asset_id)
        ) then raise exception 'simulation not found in recommendation portfolio' using errcode = 'P0002'; end if;
        update public.recommendation_history set
            simulation_id = (p_payload->>'record_id')::uuid, simulation_linked_at = now()
        where id = p_recommendation_id and simulation_id is null returning * into v_rec;
        if not found then raise exception 'simulation already linked'; end if;
        v_action_name := 'simulation_linked';
    elsif p_action = 'review_simulation' then
        if v_rec.simulation_id is null then raise exception 'simulation not linked'; end if;
        v_action_name := 'simulation_reviewed';
    elsif p_action = 'link_dispatch' then
        if not exists (
            select 1 from public.dispatch_events d
             where d.id = (p_payload->>'record_id')::uuid
               and d.portfolio_id = v_rec.portfolio_id and d.asset_id = v_rec.asset_id
        ) then raise exception 'dispatch not found in recommendation portfolio' using errcode = 'P0002'; end if;
        update public.recommendation_history set
            dispatch_id = (p_payload->>'record_id')::uuid, dispatch_linked_at = now()
        where id = p_recommendation_id and dispatch_id is null returning * into v_rec;
        if not found then raise exception 'dispatch already linked'; end if;
        v_action_name := 'dispatch_linked';
    elsif p_action in ('approve','reject') then
        insert into public.recommendation_approvals (
            recommendation_id, approved_by_operator_id, approval_status, approval_note
        ) values (
            p_recommendation_id, p_operator_id,
            case when p_action = 'approve' then 'approved' else 'rejected' end,
            nullif(p_payload->>'note','')
        ) returning * into v_approval;
        v_action_name := case when p_action = 'approve'
            then 'recommendation_approved' else 'approval_rejected' end;
    else
        raise exception 'unsupported recommendation action';
    end if;

    insert into public.operator_audit_events
        (operator_id, action, entity_type, entity_id, outcome, metadata)
    values (p_operator_id, v_action_name, 'recommendation', p_recommendation_id::text,
            'succeeded', public.pubba_sanitize_audit_metadata(p_payload));

    return jsonb_build_object('recommendation', to_jsonb(v_rec), 'approval', to_jsonb(v_approval));
end;
$$;

create or replace function public.pubba_audited_recommendation_capture(
    p_operator_id uuid, p_snapshot jsonb
) returns jsonb language plpgsql security definer set search_path = public as $$
declare v_rec public.recommendation_history%rowtype;
begin
    perform public.pubba_require_portfolio_role(
        p_operator_id, (p_snapshot->>'portfolio_id')::uuid,
        array['operator','approver','admin']
    );
    insert into public.recommendation_history (
        portfolio_id, asset_id, generated_at, market_timestamp, market_price, market_node,
        opportunity_score, recommendation, recommendation_direction,
        estimated_charging_cost, estimated_discharge_revenue, estimated_gross_profit,
        estimated_margin, estimated_break_even_price, estimated_spread,
        round_trip_efficiency_assumption, variable_om_assumption, lease_cost_assumption,
        telemetry_available, operational_readiness, telemetry_timestamp, explanation,
        drivers, risks, missing_operational_inputs, recommendation_engine_version, snapshot_hash
    ) values (
        (p_snapshot->>'portfolio_id')::uuid, p_snapshot->>'asset_id',
        (p_snapshot->>'generated_at')::timestamptz, (p_snapshot->>'market_timestamp')::timestamptz,
        (p_snapshot->>'market_price')::numeric, p_snapshot->>'market_node',
        (p_snapshot->>'opportunity_score')::integer, p_snapshot->>'recommendation',
        p_snapshot->>'recommendation_direction',
        (p_snapshot->>'estimated_charging_cost')::numeric,
        (p_snapshot->>'estimated_discharge_revenue')::numeric,
        (p_snapshot->>'estimated_gross_profit')::numeric,
        (p_snapshot->>'estimated_margin')::numeric,
        (p_snapshot->>'estimated_break_even_price')::numeric,
        (p_snapshot->>'estimated_spread')::numeric,
        (p_snapshot->>'round_trip_efficiency_assumption')::numeric,
        (p_snapshot->>'variable_om_assumption')::numeric,
        (p_snapshot->>'lease_cost_assumption')::numeric,
        (p_snapshot->>'telemetry_available')::boolean, p_snapshot->>'operational_readiness',
        nullif(p_snapshot->>'telemetry_timestamp','')::timestamptz, p_snapshot->>'explanation',
        coalesce(p_snapshot->'drivers','[]'::jsonb), coalesce(p_snapshot->'risks','[]'::jsonb),
        coalesce(p_snapshot->'missing_operational_inputs','[]'::jsonb),
        p_snapshot->>'recommendation_engine_version', p_snapshot->>'snapshot_hash'
    ) returning * into v_rec;
    insert into public.operator_audit_events
        (operator_id, action, entity_type, entity_id, outcome, metadata)
    values (p_operator_id, 'recommendation_captured', 'recommendation', v_rec.id::text,
            'succeeded', jsonb_build_object('asset_id', v_rec.asset_id,
                                            'portfolio_id', v_rec.portfolio_id));
    return to_jsonb(v_rec);
end;
$$;

create or replace function public.pubba_audited_operator_update(
    p_actor_operator_id uuid, p_target_operator_id uuid, p_changes jsonb
) returns jsonb language plpgsql security definer set search_path = public as $$
declare v_actor public.operators%rowtype; v_target public.operators%rowtype;
begin
    select * into v_actor from public.operators where id = p_actor_operator_id and status = 'active';
    if not found or v_actor.role <> 'admin' then raise exception 'admin access denied' using errcode = '42501'; end if;
    update public.operators set
        role = coalesce(p_changes->>'role', role),
        status = coalesce(p_changes->>'status', status), updated_at = now()
    where id = p_target_operator_id returning * into v_target;
    if not found then raise exception 'operator not found' using errcode = 'P0002'; end if;
    insert into public.operator_audit_events
        (operator_id, action, entity_type, entity_id, outcome, metadata)
    values (p_actor_operator_id, 'operator_access_updated', 'operator',
            p_target_operator_id::text, 'succeeded', public.pubba_sanitize_audit_metadata(p_changes));
    return to_jsonb(v_target);
end;
$$;

create or replace function public.pubba_audited_portfolio_access_change(
    p_actor_operator_id uuid, p_target_operator_id uuid, p_portfolio_id uuid,
    p_role_override text, p_active boolean
) returns jsonb language plpgsql security definer set search_path = public as $$
declare v_actor public.operators%rowtype; v_access public.operator_portfolio_access%rowtype;
begin
    select * into v_actor from public.operators where id = p_actor_operator_id and status = 'active';
    if not found or v_actor.role <> 'admin' then raise exception 'admin access denied' using errcode = '42501'; end if;
    insert into public.operator_portfolio_access
        (operator_id, portfolio_id, role_override, active, created_by)
    values (p_target_operator_id, p_portfolio_id, p_role_override, p_active, p_actor_operator_id)
    on conflict (operator_id, portfolio_id) do update set
        role_override = excluded.role_override, active = excluded.active,
        updated_at = now()
    returning * into v_access;
    insert into public.operator_audit_events
        (operator_id, action, entity_type, entity_id, outcome, metadata)
    values (p_actor_operator_id, 'portfolio_access_changed', 'operator_portfolio_access',
            v_access.id::text, 'succeeded',
            jsonb_build_object('target_operator_id', p_target_operator_id,
                               'portfolio_id', p_portfolio_id,
                               'role_override', p_role_override, 'active', p_active));
    return to_jsonb(v_access);
end;
$$;

revoke all on function public.pubba_audited_recommendation_action(uuid,uuid,text,jsonb) from public;
revoke all on function public.pubba_audited_recommendation_capture(uuid,jsonb) from public;
revoke all on function public.pubba_audited_operator_update(uuid,uuid,jsonb) from public;
revoke all on function public.pubba_audited_portfolio_access_change(uuid,uuid,uuid,text,boolean) from public;
revoke all on function public.pubba_effective_portfolio_role(uuid,uuid) from public;
revoke all on function public.pubba_require_portfolio_role(uuid,uuid,text[]) from public;
revoke all on function public.pubba_sanitize_audit_metadata(jsonb) from public;
grant execute on function public.pubba_audited_recommendation_action(uuid,uuid,text,jsonb) to service_role;
grant execute on function public.pubba_audited_recommendation_capture(uuid,jsonb) to service_role;
grant execute on function public.pubba_audited_operator_update(uuid,uuid,jsonb) to service_role;
grant execute on function public.pubba_audited_portfolio_access_change(uuid,uuid,uuid,text,boolean) to service_role;

comment on table public.operator_portfolio_access is
    'Explicit active portfolio assignments for verified PUBBA operators; global admins retain all-portfolio access.';
