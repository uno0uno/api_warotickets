-- ============================================================================
-- Migration 011: Promoter Event Configs
-- Purpose: Per-event commission configuration for promoters
-- ============================================================================

CREATE TABLE promoter_event_configs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    promoter_code_id uuid NOT NULL,
    cluster_id integer NOT NULL,
    tenant_id uuid NOT NULL,

    commission_percentage numeric NOT NULL,

    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),

    CONSTRAINT pec_promoter_code_fkey
        FOREIGN KEY (promoter_code_id) REFERENCES promoter_codes(id) ON DELETE CASCADE,
    CONSTRAINT pec_cluster_fkey
        FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE CASCADE,
    CONSTRAINT pec_tenant_fkey
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT unique_promoter_event UNIQUE(promoter_code_id, cluster_id)
);

CREATE INDEX idx_pec_promoter_code ON promoter_event_configs(promoter_code_id);
CREATE INDEX idx_pec_cluster ON promoter_event_configs(cluster_id);
CREATE INDEX idx_pec_tenant ON promoter_event_configs(tenant_id);
