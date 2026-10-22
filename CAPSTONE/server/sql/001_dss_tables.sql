-- Makisushi DSS: decision log, purchasing-list ticks and manual waste log.
-- NEW tables only (no column is added to any existing table). Idempotent. Apply once per database:
--   npm run db:migrate
-- The warehouse load (supabase_final/03_transform.sql) truncates the tables it owns and does not touch these.
-- The dw schema is not exposed through the Supabase API; keep it that way (these tables have no row-level security).

create table if not exists dw.fact_recommendation (
    rec_id            bigint generated always as identity primary key,
    rec_key           text not null,                      -- type:ingredient_code:decision_date, e.g. spoilage:SAL:2026-09-09
    created_at        timestamptz not null default now(),
    type              text not null check (type in ('stockout', 'spoilage', 'excess', 'weekly_order')),
    title             text not null,
    ingredient_id     int references dw.dim_ingredient,
    recommended_qty   numeric,                            -- base units of the ingredient
    peso_impact       numeric,
    status            text not null check (status in ('open', 'applied', 'modified', 'dismissed')),
    decided_by        text,
    decided_at        timestamptz,
    reason            text,
    outcome_text      text,                               -- filled after the next ETL cycle
    outcome_waste_kg  numeric,
    data_as_of        date,                               -- last warehouse day the recommendation was based on
    opt_run_id        bigint
);
create index if not exists ix_fact_recommendation_key on dw.fact_recommendation (rec_key, rec_id desc);

create table if not exists dw.plan_line_status (
    opt_run_id     bigint not null,
    ingredient_id  int not null references dw.dim_ingredient,
    ordered        boolean not null default false,
    ordered_by     text,
    ordered_at     timestamptz not null default now(),
    primary key (opt_run_id, ingredient_id)
);

create table if not exists dw.manual_waste_log (
    log_id         bigint generated always as identity primary key,
    logged_at      timestamptz not null default now(),
    waste_date     date not null,
    ingredient_id  int not null references dw.dim_ingredient,
    qty_base       numeric not null check (qty_base > 0),  -- base units (g, pc, serving)
    reason         text not null check (reason in ('expiry', 'over_ordering', 'prep', 'damaged', 'other')),
    note           text,
    logged_by      text
);
