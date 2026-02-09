-- ============================================================================
-- Migration 010: Promoter Commissions System
-- Purpose: Enable promoter tracking and commission calculation for ticket sales
-- ============================================================================

-- ============================================================================
-- NUEVAS TABLAS - Consistentes con convenciones del sistema
-- ============================================================================
-- NOTA: Usa tenant_member_roles existente para gestión de roles (site_role_name='promotor')

-- Tabla: promoter_codes
CREATE TABLE promoter_codes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_member_id uuid NOT NULL,
    tenant_id uuid NOT NULL,

    code character varying(20) NOT NULL UNIQUE,
    commission_percentage numeric,

    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),

    CONSTRAINT promoter_codes_tenant_member_fkey
        FOREIGN KEY (tenant_member_id) REFERENCES tenant_members(id) ON DELETE CASCADE,
    CONSTRAINT promoter_codes_tenant_fkey
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT unique_promoter_per_tenant UNIQUE(tenant_member_id, tenant_id)
);

CREATE INDEX idx_promoter_codes_code ON promoter_codes(code);
CREATE INDEX idx_promoter_codes_tenant ON promoter_codes(tenant_id);


-- Tabla: commission_configs (opcional)
CREATE TABLE commission_configs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,

    default_commission_percentage numeric DEFAULT 10.0,
    require_manual_approval boolean DEFAULT true,
    min_payout_amount numeric DEFAULT 50000,

    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),

    CONSTRAINT commission_configs_tenant_fkey
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT unique_config_per_tenant UNIQUE(tenant_id)
);


-- Tabla: order_commissions
CREATE TABLE order_commissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    reservation_id uuid NOT NULL,
    payment_id integer,
    promoter_code_id uuid NOT NULL,
    tenant_member_id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    cluster_id integer,

    total_base_price numeric NOT NULL,
    tickets_count integer NOT NULL,
    commission_percentage numeric NOT NULL,
    commission_amount numeric NOT NULL,

    status character varying DEFAULT 'pending'::character varying,

    approved_at timestamp with time zone,
    approved_by uuid,
    paid_at timestamp with time zone,
    payment_reference character varying(255),
    notes text,

    extra_attributes jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),

    CONSTRAINT order_commissions_reservation_fkey
        FOREIGN KEY (reservation_id) REFERENCES reservations(id) ON DELETE CASCADE,
    CONSTRAINT order_commissions_payment_fkey
        FOREIGN KEY (payment_id) REFERENCES payments(id) ON DELETE SET NULL,
    CONSTRAINT order_commissions_promoter_code_fkey
        FOREIGN KEY (promoter_code_id) REFERENCES promoter_codes(id) ON DELETE CASCADE,
    CONSTRAINT order_commissions_tenant_member_fkey
        FOREIGN KEY (tenant_member_id) REFERENCES tenant_members(id) ON DELETE CASCADE,
    CONSTRAINT order_commissions_tenant_fkey
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT order_commissions_approved_by_fkey
        FOREIGN KEY (approved_by) REFERENCES profile(id)
);

CREATE INDEX idx_order_commissions_reservation ON order_commissions(reservation_id);
CREATE INDEX idx_order_commissions_payment ON order_commissions(payment_id);
CREATE INDEX idx_order_commissions_promoter_code ON order_commissions(promoter_code_id);
CREATE INDEX idx_order_commissions_status ON order_commissions(status);


-- Modificaciones a tablas existentes
ALTER TABLE reservations
ADD COLUMN promoter_code_id uuid,
ADD CONSTRAINT reservations_promoter_code_fkey
    FOREIGN KEY (promoter_code_id) REFERENCES promoter_codes(id) ON DELETE SET NULL;

CREATE INDEX idx_reservations_promoter_code ON reservations(promoter_code_id)
    WHERE promoter_code_id IS NOT NULL;


ALTER TABLE ticket_carts
ADD COLUMN promoter_code_id uuid,
ADD CONSTRAINT ticket_carts_promoter_code_fkey
    FOREIGN KEY (promoter_code_id) REFERENCES promoter_codes(id) ON DELETE SET NULL;

CREATE INDEX idx_ticket_carts_promoter_code ON ticket_carts(promoter_code_id)
    WHERE promoter_code_id IS NOT NULL;


-- ============================================================================
-- Verification queries (run after migration):
--
-- SELECT COUNT(*) FROM promoter_codes;
-- SELECT COUNT(*) FROM order_commissions;
-- SELECT COUNT(*) FROM commission_configs;
--
-- Test promoter code generation:
-- INSERT INTO promoter_codes (tenant_member_id, tenant_id, code, commission_percentage)
-- VALUES ('<tenant_member_id>', '<tenant_id>', 'WRPROM-TEST1', 10.0);
-- ============================================================================
