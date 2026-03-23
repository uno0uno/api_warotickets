-- Migration 016: Crear campaña para solicitudes de acceso como organizador
-- Ejecutar: psql -h <host> -U <user> -d <db> -f migrations/016_lead_campaign_contacto.sql

INSERT INTO campaign (id, name, slug, status, profile_id, created_at, updated_at)
SELECT
  gen_random_uuid(),
  'Solicitud de acceso como organizador',
  'solicitud-organizador-contacto',
  'active',
  (SELECT id FROM profile ORDER BY created_at ASC LIMIT 1),
  now(),
  now()
WHERE NOT EXISTS (
  SELECT 1 FROM campaign WHERE slug = 'solicitud-organizador-contacto'
);
