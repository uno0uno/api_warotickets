-- Migration: Create event_images table for storing event banner and flyer images
-- Date: 2026-01-28

-- Create event_images table
CREATE TABLE IF NOT EXISTS event_images (
    id SERIAL PRIMARY KEY,
    cluster_id INTEGER NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    image_type VARCHAR(20) NOT NULL,
    image_url TEXT NOT NULL,
    alt_text VARCHAR(255),
    width INTEGER,
    height INTEGER,
    file_size INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Constraint para tipos válidos: banner, flyer, cover, gallery
ALTER TABLE event_images ADD CONSTRAINT chk_event_image_type
    CHECK (image_type IN ('banner', 'flyer', 'cover', 'gallery'));

-- Solo una imagen por tipo por evento (excepto gallery que puede tener múltiples)
CREATE UNIQUE INDEX IF NOT EXISTS idx_event_images_unique_type
    ON event_images(cluster_id, image_type)
    WHERE image_type != 'gallery';

-- Índices para búsquedas rápidas
CREATE INDEX IF NOT EXISTS idx_event_images_cluster ON event_images(cluster_id);
CREATE INDEX IF NOT EXISTS idx_event_images_type ON event_images(image_type);

-- Trigger para actualizar updated_at automáticamente
CREATE OR REPLACE FUNCTION update_event_images_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_event_images_updated_at ON event_images;
CREATE TRIGGER trigger_event_images_updated_at
    BEFORE UPDATE ON event_images
    FOR EACH ROW
    EXECUTE FUNCTION update_event_images_updated_at();
