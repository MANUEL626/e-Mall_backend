alter table public.organization_article_order_lines
    add column if not exists total_price numeric(14, 2) not null default 0,
    add column if not exists unit_price numeric(14, 4) not null default 0;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'organization_article_order_lines_total_price_check'
    ) then
        alter table public.organization_article_order_lines
            add constraint organization_article_order_lines_total_price_check
            check (total_price >= 0);
    end if;

    if not exists (
        select 1
        from pg_constraint
        where conname = 'organization_article_order_lines_unit_price_check'
    ) then
        alter table public.organization_article_order_lines
            add constraint organization_article_order_lines_unit_price_check
            check (unit_price >= 0);
    end if;
end $$;

create or replace function public.organization_article_order_lines_compute_unit_price()
returns trigger
language plpgsql
as $$
begin
    if new.quantity_ordered is null or new.quantity_ordered <= 0 then
        raise exception 'quantity_ordered must be greater than 0';
    end if;

    new.total_price := round(coalesce(new.total_price, 0), 2);
    new.unit_price := round(new.total_price / new.quantity_ordered, 4);
    return new;
end;
$$;

drop trigger if exists organization_article_order_lines_compute_unit_price
    on public.organization_article_order_lines;

create trigger organization_article_order_lines_compute_unit_price
before insert or update of total_price, quantity_ordered
on public.organization_article_order_lines
for each row
execute function public.organization_article_order_lines_compute_unit_price();

