-- PUBBA Power operator identity, approvals, and action auditing.
-- Additive only. Apply manually after configuring and testing the selected OIDC provider.

create extension if not exists pgcrypto;

create table if not exists public.operators (
    id uuid primary key default gen_random_uuid(),
    auth_subject text not null unique,
    email text not null,
    display_name text not null,
    role text not null,
    status text not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint operators_role_check check (role in ('viewer', 'operator', 'approver', 'admin')),
    constraint operators_status_check check (status in ('active', 'inactive')),
    constraint operators_email_not_blank check (length(trim(email)) > 0),
    constraint operators_display_name_not_blank check (length(trim(display_name)) > 0)
);

create index if not exists operators_email_idx on public.operators (lower(email));
create index if not exists operators_role_status_idx on public.operators (role, status);

create table if not exists public.recommendation_approvals (
    id uuid primary key default gen_random_uuid(),
    recommendation_id uuid not null unique,
    approved_at timestamptz not null default now(),
    approved_by_operator_id uuid not null,
    approval_status text not null,
    approval_note text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint recommendation_approvals_recommendation_fkey
        foreign key (recommendation_id) references public.recommendation_history(id)
        on update restrict on delete restrict,
    constraint recommendation_approvals_operator_fkey
        foreign key (approved_by_operator_id) references public.operators(id)
        on update restrict on delete restrict,
    constraint recommendation_approvals_status_check check (approval_status in ('approved', 'rejected'))
);

create index if not exists recommendation_approvals_operator_idx
    on public.recommendation_approvals (approved_by_operator_id, approved_at desc);
create index if not exists recommendation_approvals_status_idx
    on public.recommendation_approvals (approval_status, approved_at desc);

create table if not exists public.operator_audit_events (
    id uuid primary key default gen_random_uuid(),
    operator_id uuid not null,
    action text not null,
    entity_type text not null,
    entity_id text not null,
    occurred_at timestamptz not null default now(),
    outcome text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint operator_audit_events_operator_fkey
        foreign key (operator_id) references public.operators(id)
        on update restrict on delete restrict,
    constraint operator_audit_events_outcome_check check (outcome in ('succeeded', 'rejected', 'failed')),
    constraint operator_audit_events_metadata_object_check check (jsonb_typeof(metadata) = 'object')
);

create index if not exists operator_audit_events_entity_idx
    on public.operator_audit_events (entity_type, entity_id, occurred_at asc, id asc);
create index if not exists operator_audit_events_operator_idx
    on public.operator_audit_events (operator_id, occurred_at desc);
create index if not exists operator_audit_events_action_idx
    on public.operator_audit_events (action, occurred_at desc);

create or replace function public.prevent_operator_audit_mutation()
returns trigger
language plpgsql
as $$
begin
    raise exception 'Operator audit and approval records are immutable';
end;
$$;

drop trigger if exists recommendation_approvals_immutable
    on public.recommendation_approvals;
create trigger recommendation_approvals_immutable
before update or delete on public.recommendation_approvals
for each row execute function public.prevent_operator_audit_mutation();

drop trigger if exists operator_audit_events_immutable
    on public.operator_audit_events;
create trigger operator_audit_events_immutable
before update or delete on public.operator_audit_events
for each row execute function public.prevent_operator_audit_mutation();

alter table public.operators enable row level security;
alter table public.recommendation_approvals enable row level security;
alter table public.operator_audit_events enable row level security;

comment on table public.operators is
    'PUBBA operator authorization profiles mapped to cryptographically verified OIDC subjects.';
comment on table public.recommendation_approvals is
    'Explicit recommendation approval or rejection decisions by authorized PUBBA operators.';
comment on table public.operator_audit_events is
    'Append-only sanitized audit events for authenticated operator actions.';
