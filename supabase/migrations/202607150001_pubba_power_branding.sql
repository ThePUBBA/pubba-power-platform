-- Update the user-facing portfolio name while preserving the stable portfolio code.
update public.portfolios
set name = 'PUBBA Power',
    updated_at = now()
where code = 'ONLY1'
  and name is distinct from 'PUBBA Power';
