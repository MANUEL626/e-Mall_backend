-- V1 currency policy: keep currency columns for future multi-currency support,
-- but force every business write to XOF/FCFA for now.

UPDATE public.organizations
SET default_currencies = jsonb_build_object('purchase', 'xof', 'sale', 'xof');

ALTER TABLE public.organization_articles
    ALTER COLUMN sale_currency SET DEFAULT 'xof';
UPDATE public.organization_articles
SET sale_currency = 'xof'
WHERE sale_currency IS DISTINCT FROM 'xof';

ALTER TABLE public.organization_article_orders
    ALTER COLUMN currency SET DEFAULT 'xof';
UPDATE public.organization_article_orders
SET currency = 'xof'
WHERE currency IS DISTINCT FROM 'xof';

ALTER TABLE public.organization_customer_sale_orders
    ALTER COLUMN currency SET DEFAULT 'xof';
UPDATE public.organization_customer_sale_orders
SET currency = 'xof'
WHERE currency IS DISTINCT FROM 'xof';

ALTER TABLE public.organization_customer_sale_order_lines
    ALTER COLUMN currency_snapshot SET DEFAULT 'xof';
UPDATE public.organization_customer_sale_order_lines
SET currency_snapshot = 'xof'
WHERE currency_snapshot IS DISTINCT FROM 'xof';

ALTER TABLE public.customer_sale_receipts
    ALTER COLUMN currency SET DEFAULT 'xof';
UPDATE public.customer_sale_receipts
SET currency = 'xof'
WHERE currency IS DISTINCT FROM 'xof';

ALTER TABLE public.organization_repair_requests
    ALTER COLUMN currency SET DEFAULT 'xof';
UPDATE public.organization_repair_requests
SET currency = 'xof'
WHERE currency IS DISTINCT FROM 'xof';

ALTER TABLE public.organization_repair_request_parts
    ALTER COLUMN currency SET DEFAULT 'xof';
UPDATE public.organization_repair_request_parts
SET currency = 'xof'
WHERE currency IS DISTINCT FROM 'xof';

ALTER TABLE public.organization_repair_invoices
    ALTER COLUMN currency SET DEFAULT 'xof';
UPDATE public.organization_repair_invoices
SET currency = 'xof'
WHERE currency IS DISTINCT FROM 'xof';

ALTER TABLE public.organization_rental_reservations
    ALTER COLUMN currency SET DEFAULT 'xof';
UPDATE public.organization_rental_reservations
SET currency = 'xof'
WHERE currency IS DISTINCT FROM 'xof';

ALTER TABLE public.organization_rental_orders
    ALTER COLUMN currency SET DEFAULT 'xof';
UPDATE public.organization_rental_orders
SET currency = 'xof'
WHERE currency IS DISTINCT FROM 'xof';

ALTER TABLE public.organization_rental_order_lines
    ALTER COLUMN currency SET DEFAULT 'xof';
UPDATE public.organization_rental_order_lines
SET currency = 'xof'
WHERE currency IS DISTINCT FROM 'xof';

ALTER TABLE public.organization_rental_invoices
    ALTER COLUMN currency SET DEFAULT 'xof';
UPDATE public.organization_rental_invoices
SET currency = 'xof'
WHERE currency IS DISTINCT FROM 'xof';

ALTER TABLE public.organization_rental_proformas
    ALTER COLUMN currency SET DEFAULT 'xof';
UPDATE public.organization_rental_proformas
SET currency = 'xof'
WHERE currency IS DISTINCT FROM 'xof';

ALTER TABLE public.organization_rental_proforma_lines
    ALTER COLUMN currency SET DEFAULT 'xof';
UPDATE public.organization_rental_proforma_lines
SET currency = 'xof'
WHERE currency IS DISTINCT FROM 'xof';

ALTER TABLE public.organization_rental_proforma_payments
    ALTER COLUMN currency SET DEFAULT 'xof';
UPDATE public.organization_rental_proforma_payments
SET currency = 'xof'
WHERE currency IS DISTINCT FROM 'xof';

ALTER TABLE public.organization_subscription_plans
    ALTER COLUMN price_currency SET DEFAULT 'xof';
UPDATE public.organization_subscription_plans
SET price_currency = 'xof'
WHERE price_currency IS DISTINCT FROM 'xof';

CREATE OR REPLACE FUNCTION public.force_business_currency_xof_v1()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_TABLE_NAME = 'organizations' THEN
        NEW.default_currencies := jsonb_build_object('purchase', 'xof', 'sale', 'xof');
    ELSIF TG_TABLE_NAME = 'organization_articles' THEN
        NEW.sale_currency := 'xof';
    ELSIF TG_TABLE_NAME IN (
        'organization_article_orders',
        'organization_customer_sale_orders',
        'customer_sale_receipts',
        'organization_repair_requests',
        'organization_repair_request_parts',
        'organization_repair_invoices',
        'organization_rental_reservations',
        'organization_rental_orders',
        'organization_rental_order_lines',
        'organization_rental_invoices',
        'organization_rental_proformas',
        'organization_rental_proforma_lines',
        'organization_rental_proforma_payments'
    ) THEN
        NEW.currency := 'xof';
    ELSIF TG_TABLE_NAME = 'organization_customer_sale_order_lines' THEN
        NEW.currency_snapshot := 'xof';
    ELSIF TG_TABLE_NAME = 'organization_subscription_plans' THEN
        NEW.price_currency := 'xof';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_force_organizations_xof_v1 ON public.organizations;
CREATE TRIGGER trg_force_organizations_xof_v1
    BEFORE INSERT OR UPDATE OF default_currencies ON public.organizations
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();

DROP TRIGGER IF EXISTS trg_force_organization_articles_xof_v1 ON public.organization_articles;
CREATE TRIGGER trg_force_organization_articles_xof_v1
    BEFORE INSERT OR UPDATE OF sale_currency ON public.organization_articles
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();

DROP TRIGGER IF EXISTS trg_force_article_orders_xof_v1 ON public.organization_article_orders;
CREATE TRIGGER trg_force_article_orders_xof_v1
    BEFORE INSERT OR UPDATE OF currency ON public.organization_article_orders
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();

DROP TRIGGER IF EXISTS trg_force_customer_sale_orders_xof_v1 ON public.organization_customer_sale_orders;
CREATE TRIGGER trg_force_customer_sale_orders_xof_v1
    BEFORE INSERT OR UPDATE OF currency ON public.organization_customer_sale_orders
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();

DROP TRIGGER IF EXISTS trg_force_customer_sale_order_lines_xof_v1 ON public.organization_customer_sale_order_lines;
CREATE TRIGGER trg_force_customer_sale_order_lines_xof_v1
    BEFORE INSERT OR UPDATE OF currency_snapshot ON public.organization_customer_sale_order_lines
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();

DROP TRIGGER IF EXISTS trg_force_customer_sale_receipts_xof_v1 ON public.customer_sale_receipts;
CREATE TRIGGER trg_force_customer_sale_receipts_xof_v1
    BEFORE INSERT OR UPDATE OF currency ON public.customer_sale_receipts
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();

DROP TRIGGER IF EXISTS trg_force_repair_requests_xof_v1 ON public.organization_repair_requests;
CREATE TRIGGER trg_force_repair_requests_xof_v1
    BEFORE INSERT OR UPDATE OF currency ON public.organization_repair_requests
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();

DROP TRIGGER IF EXISTS trg_force_repair_parts_xof_v1 ON public.organization_repair_request_parts;
CREATE TRIGGER trg_force_repair_parts_xof_v1
    BEFORE INSERT OR UPDATE OF currency ON public.organization_repair_request_parts
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();

DROP TRIGGER IF EXISTS trg_force_repair_invoices_xof_v1 ON public.organization_repair_invoices;
CREATE TRIGGER trg_force_repair_invoices_xof_v1
    BEFORE INSERT OR UPDATE OF currency ON public.organization_repair_invoices
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();

DROP TRIGGER IF EXISTS trg_force_rental_reservations_xof_v1 ON public.organization_rental_reservations;
CREATE TRIGGER trg_force_rental_reservations_xof_v1
    BEFORE INSERT OR UPDATE OF currency ON public.organization_rental_reservations
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();

DROP TRIGGER IF EXISTS trg_force_rental_orders_xof_v1 ON public.organization_rental_orders;
CREATE TRIGGER trg_force_rental_orders_xof_v1
    BEFORE INSERT OR UPDATE OF currency ON public.organization_rental_orders
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();

DROP TRIGGER IF EXISTS trg_force_rental_order_lines_xof_v1 ON public.organization_rental_order_lines;
CREATE TRIGGER trg_force_rental_order_lines_xof_v1
    BEFORE INSERT OR UPDATE OF currency ON public.organization_rental_order_lines
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();

DROP TRIGGER IF EXISTS trg_force_rental_invoices_xof_v1 ON public.organization_rental_invoices;
CREATE TRIGGER trg_force_rental_invoices_xof_v1
    BEFORE INSERT OR UPDATE OF currency ON public.organization_rental_invoices
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();

DROP TRIGGER IF EXISTS trg_force_rental_proformas_xof_v1 ON public.organization_rental_proformas;
CREATE TRIGGER trg_force_rental_proformas_xof_v1
    BEFORE INSERT OR UPDATE OF currency ON public.organization_rental_proformas
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();

DROP TRIGGER IF EXISTS trg_force_rental_proforma_lines_xof_v1 ON public.organization_rental_proforma_lines;
CREATE TRIGGER trg_force_rental_proforma_lines_xof_v1
    BEFORE INSERT OR UPDATE OF currency ON public.organization_rental_proforma_lines
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();

DROP TRIGGER IF EXISTS trg_force_rental_proforma_payments_xof_v1 ON public.organization_rental_proforma_payments;
CREATE TRIGGER trg_force_rental_proforma_payments_xof_v1
    BEFORE INSERT OR UPDATE OF currency ON public.organization_rental_proforma_payments
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();

DROP TRIGGER IF EXISTS trg_force_subscription_plans_xof_v1 ON public.organization_subscription_plans;
CREATE TRIGGER trg_force_subscription_plans_xof_v1
    BEFORE INSERT OR UPDATE OF price_currency ON public.organization_subscription_plans
    FOR EACH ROW EXECUTE FUNCTION public.force_business_currency_xof_v1();
