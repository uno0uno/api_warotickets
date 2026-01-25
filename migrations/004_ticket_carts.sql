-- =============================================================================
-- Migration: 004_ticket_carts.sql
-- Description: Create ticket cart tables for shopping cart functionality
-- =============================================================================

-- Carrito de tickets
CREATE TABLE IF NOT EXISTS ticket_carts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    session_id VARCHAR(255),           -- Para usuarios no autenticados
    user_id UUID REFERENCES profile(id), -- Para usuarios autenticados
    cluster_id INTEGER REFERENCES clusters(id), -- Un carrito por evento
    status VARCHAR(50) DEFAULT 'active', -- active, abandoned, converted
    promotion_code VARCHAR(100),        -- Codigo promo aplicado (exclusivo con stages)
    expires_at TIMESTAMPTZ,             -- Expiracion del carrito (opcional)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Items del carrito
CREATE TABLE IF NOT EXISTS ticket_cart_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cart_id UUID NOT NULL REFERENCES ticket_carts(id) ON DELETE CASCADE,
    area_id INTEGER NOT NULL REFERENCES areas(id),
    sale_stage_id UUID REFERENCES sale_stages(id), -- Etapa aplicada (si aplica)
    quantity INTEGER NOT NULL DEFAULT 1,           -- Cantidad de bundles/tickets
    tickets_count INTEGER NOT NULL,                -- Total boletas (quantity * bundle_size)
    unit_price NUMERIC(12,2) NOT NULL,             -- Precio por boleta con descuento
    bundle_price NUMERIC(12,2),                    -- Precio del bundle (si aplica)
    original_price NUMERIC(12,2) NOT NULL,         -- Precio original sin descuento
    subtotal NUMERIC(12,2) NOT NULL,               -- Total del item
    bundle_size INTEGER DEFAULT 1,                 -- Tamano del bundle (1, 2, 3...)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(cart_id, area_id) -- Un item por area por carrito
);

-- Indices para mejor performance
CREATE INDEX IF NOT EXISTS idx_ticket_carts_session ON ticket_carts(session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ticket_carts_user ON ticket_carts(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ticket_carts_cluster ON ticket_carts(cluster_id);
CREATE INDEX IF NOT EXISTS idx_ticket_carts_status ON ticket_carts(status);
CREATE INDEX IF NOT EXISTS idx_ticket_cart_items_cart ON ticket_cart_items(cart_id);

-- Comentarios para documentacion
COMMENT ON TABLE ticket_carts IS 'Carritos de compra para boletas de eventos';
COMMENT ON TABLE ticket_cart_items IS 'Items dentro de un carrito de boletas';
COMMENT ON COLUMN ticket_carts.session_id IS 'ID de sesion para usuarios anonimos';
COMMENT ON COLUMN ticket_carts.promotion_code IS 'Codigo promocional aplicado (excluyente con etapas de venta)';
COMMENT ON COLUMN ticket_cart_items.quantity IS 'Cantidad de bundles/tickets seleccionados';
COMMENT ON COLUMN ticket_cart_items.tickets_count IS 'Total de boletas (quantity * bundle_size)';
COMMENT ON COLUMN ticket_cart_items.bundle_size IS 'Tamano del bundle (ej: 2 para 2x1)';
