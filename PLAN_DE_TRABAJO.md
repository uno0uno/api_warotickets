# Plan de Trabajo - API WaRo Tickets

## Resumen del Proyecto
Sistema de ticketera para venta de boleteria de eventos, utilizando el mismo framework (FastAPI + asyncpg) y base de datos compartida con multi-tenancy.

---

## Estructura de Base de Datos Existente

La base de datos ya cuenta con las siguientes tablas para el sistema de tickets:

### Jerarquia Principal
```
clusters (Eventos)
    |-- profile_id (tenant/organizador)
    |-- cluster_name, description
    |-- start_date, end_date
    |-- cluster_type
    |-- slug_cluster
    |-- legal_info_id
    |-- is_active, shadowban
    |
    +-- cluster_images (Imagenes del evento)
    |       |-- image_id, type_image
    |
    +-- areas (Zonas/Localidades)
            |-- area_name, description
            |-- capacity, price, currency
            |-- nomenclature_letter
            |-- unit_capacity, service
            |
            +-- units (Boletos/Asientos individuales)
                    |-- area_id
                    |-- status (available, reserved, sold)
                    |-- nomenclature_letter_area
                    |-- nomenclature_number_area
                    |-- nomenclature_number_unit
```

### Sistema de Reservaciones
```
reservations (Reservas de usuarios)
    |-- user_id
    |-- reservation_date
    |-- start_date, end_date
    |-- status (active, cancelled, completed)
    |-- extra_attributes (jsonb)
    |
    +-- reservation_units (Boletos reservados)
    |       |-- unit_id
    |       |-- status (reserved, confirmed, used, transferred)
    |       |-- original_user_id
    |       |-- transfer_date
    |       |-- applied_sale_stage_id
    |       |-- applied_promotion_id
    |       |
    |       +-- reservation_unit_qr_images (QR de entrada)
    |               |-- image_id, type_image
    |
    +-- payments (Pagos)
            |-- amount, currency
            |-- payment_method, status
            |-- payment_gateway_transaction_id
            |-- customer_email, customer_data
            |-- billing_data
```

### Sistema de Precios Dinamicos
```
sale_stages (Etapas de venta)
    |-- stage_name (Early Bird, Preventa, General, etc.)
    |-- price_adjustment_type (percentage, fixed)
    |-- price_adjustment_value
    |-- quantity_available
    |-- start_time, end_time
    |-- target_area_id (opcional)
    |-- target_product_variant_id (opcional)
    |-- priority_order

promotions (Codigos de descuento)
    |-- promotion_name, promotion_code
    |-- discount_type, discount_value
    |-- applies_to (cluster, area, product)
    |-- target_cluster_id, target_area_id
    |-- min_quantity, max_discount_amount
    |-- start_date, end_date
```

### Tablas Auxiliares
```
unit_transfer_log (Historial de transferencias)
    |-- reservation_unit_id
    |-- from_user_id, to_user_id
    |-- transfer_date, transfer_reason

legal_info (Info legal del organizador)
    |-- nit, legal_name
    |-- puleb_code (registro PULEP)
    |-- address, city, country

images (Almacenamiento de imagenes)
    |-- url, type, etc.
```

---

## Arquitectura del Proyecto

### Stack Tecnologico
- **Framework:** FastAPI 0.119+
- **Base de datos:** PostgreSQL (compartida con warolabs)
- **Driver:** asyncpg (asincrono)
- **Validacion:** Pydantic v2
- **Autenticacion:** Session tokens + Magic Links
- **Storage:** Cloudflare R2 (S3-compatible)
- **Email:** AWS SES
- **Notificaciones:** Discord Webhooks

### Estructura de Carpetas
```
api_warotickets/
|-- app/
|   |-- main.py                 # Punto de entrada FastAPI
|   |-- config.py               # Configuracion Pydantic Settings
|   |-- database.py             # Pool de conexiones asyncpg
|   |-- core/
|   |   |-- __init__.py
|   |   |-- middleware.py       # Tenant detection, session validation
|   |   |-- security.py         # Session tokens
|   |   |-- tenant.py           # Logica de tenants
|   |   |-- dependencies.py     # Dependencias FastAPI
|   |   |-- exceptions.py       # Excepciones personalizadas
|   |   |-- error_handlers.py   # Manejadores de errores
|   |-- models/
|   |   |-- __init__.py
|   |   |-- auth.py             # User, Session
|   |   |-- event.py            # Cluster/Evento
|   |   |-- area.py             # Areas/Localidades
|   |   |-- unit.py             # Units/Boletos
|   |   |-- reservation.py      # Reservaciones
|   |   |-- payment.py          # Pagos
|   |   |-- promotion.py        # Promociones
|   |   |-- sale_stage.py       # Etapas de venta
|   |-- routers/
|   |   |-- __init__.py
|   |   |-- auth.py             # Autenticacion
|   |   |-- events.py           # CRUD Eventos (clusters)
|   |   |-- areas.py            # CRUD Areas
|   |   |-- units.py            # CRUD Units/Boletos
|   |   |-- reservations.py     # Proceso de reserva
|   |   |-- payments.py         # Procesamiento de pagos
|   |   |-- promotions.py       # Gestion de promociones
|   |   |-- sale_stages.py      # Etapas de venta
|   |   |-- public.py           # Endpoints publicos (listado eventos)
|   |   |-- qr.py               # Generacion/validacion QR
|   |   |-- transfers.py        # Transferencia de boletos
|   |-- services/
|   |   |-- __init__.py
|   |   |-- auth_service.py
|   |   |-- events_service.py
|   |   |-- areas_service.py
|   |   |-- units_service.py
|   |   |-- reservations_service.py
|   |   |-- payments_service.py
|   |   |-- promotions_service.py
|   |   |-- sale_stages_service.py
|   |   |-- qr_service.py
|   |   |-- pricing_service.py  # Calculo de precios dinamicos
|   |   |-- transfer_service.py
|   |   |-- aws_s3_service.py
|   |   |-- aws_ses_service.py
|   |   |-- discord_service.py
|   |-- templates/
|   |   |-- ticket_email.py     # Template email de boletos
|   |   |-- confirmation_email.py
|   |-- utils/
|       |-- __init__.py
|       |-- qr_generator.py     # Generacion de QR codes
|       |-- encryption.py
|-- tests/
|-- docs/
|-- requirements.txt
|-- Dockerfile
|-- docker-compose.yml
|-- .env.example
|-- pytest.ini
```

---

## Plan de Implementacion por Fases

### FASE 1: Configuracion Base
**Objetivo:** Tener el proyecto corriendo con autenticacion y tenant detection

- [ ] Copiar y adaptar archivos de configuracion base
  - [ ] `config.py` - Variables de entorno
  - [ ] `database.py` - Pool de conexiones
  - [ ] `main.py` - App FastAPI con middleware
- [ ] Implementar core/
  - [ ] `middleware.py` - Tenant y session detection
  - [ ] `security.py` - Manejo de session tokens
  - [ ] `tenant.py` - Contexto de tenant
  - [ ] `dependencies.py` - get_current_user, get_tenant
  - [ ] `exceptions.py` - Excepciones personalizadas
  - [ ] `error_handlers.py` - Handlers globales
- [ ] Implementar autenticacion
  - [ ] `models/auth.py`
  - [ ] `routers/auth.py`
  - [ ] `services/auth_service.py`
- [ ] Configurar requirements.txt y Docker
- [ ] Probar que el servidor inicia correctamente

### FASE 2: Gestion de Eventos (Clusters)
**Objetivo:** CRUD completo de eventos para organizadores

- [ ] Modelos
  - [ ] `models/event.py` - Cluster, ClusterCreate, ClusterUpdate
  - [ ] `models/area.py` - Area, AreaCreate, AreaUpdate
  - [ ] `models/unit.py` - Unit, UnitCreate, UnitBulkCreate
- [ ] Servicios
  - [ ] `services/events_service.py` - CRUD eventos
  - [ ] `services/areas_service.py` - CRUD areas con calculo de capacidad
  - [ ] `services/units_service.py` - Generacion masiva de boletos
- [ ] Routers
  - [ ] `routers/events.py` - Endpoints de eventos
  - [ ] `routers/areas.py` - Endpoints de areas
  - [ ] `routers/units.py` - Endpoints de boletos
- [ ] Subida de imagenes para eventos
  - [ ] `services/aws_s3_service.py`

### FASE 3: Sistema de Precios Dinamicos
**Objetivo:** Implementar etapas de venta y promociones

- [ ] Modelos
  - [ ] `models/sale_stage.py`
  - [ ] `models/promotion.py`
- [ ] Servicios
  - [ ] `services/sale_stages_service.py`
  - [ ] `services/promotions_service.py`
  - [ ] `services/pricing_service.py` - Motor de calculo de precios
- [ ] Routers
  - [ ] `routers/sale_stages.py`
  - [ ] `routers/promotions.py`
- [ ] Logica de negocio:
  - [ ] Activacion automatica por fecha/cantidad
  - [ ] Validacion de codigos promocionales
  - [ ] Calculo de precio final con descuentos

### FASE 4: Portal Publico de Eventos
**Objetivo:** Endpoints publicos para listar y ver eventos

- [ ] Router `routers/public.py`:
  - [ ] GET /events - Listar eventos activos
  - [ ] GET /events/{slug} - Detalle de evento
  - [ ] GET /events/{slug}/areas - Areas disponibles con precios
  - [ ] GET /events/{slug}/areas/{area_id}/availability - Disponibilidad
- [ ] Servicios publicos sin requerir autenticacion
- [ ] Cache de consultas frecuentes (opcional)

### FASE 5: Sistema de Reservaciones
**Objetivo:** Flujo completo de compra de boletos

- [ ] Modelos
  - [ ] `models/reservation.py`
  - [ ] `models/payment.py`
- [ ] Servicios
  - [ ] `services/reservations_service.py`
    - [ ] Crear reserva (bloquear unidades)
    - [ ] Confirmar reserva (despues del pago)
    - [ ] Cancelar reserva (liberar unidades)
    - [ ] Timeout de reservas pendientes
  - [ ] `services/payments_service.py`
    - [ ] Integracion con pasarela de pagos
    - [ ] Webhook de confirmacion
- [ ] Routers
  - [ ] `routers/reservations.py`
  - [ ] `routers/payments.py`
- [ ] Transacciones atomicas para evitar overselling

### FASE 6: Generacion de Boletos y QR
**Objetivo:** Generar boletos electronicos con QR

- [ ] Utilidades
  - [ ] `utils/qr_generator.py` - Generar QR codes
- [ ] Servicios
  - [ ] `services/qr_service.py`
    - [ ] Generar QR unico por boleto
    - [ ] Validar QR en entrada
    - [ ] Marcar boleto como usado
- [ ] Router `routers/qr.py`:
  - [ ] POST /qr/validate - Validar entrada
  - [ ] GET /qr/{reservation_unit_id} - Obtener QR
- [ ] Email con boletos
  - [ ] `templates/ticket_email.py`
  - [ ] `services/aws_ses_service.py`

### FASE 7: Transferencia de Boletos
**Objetivo:** Permitir transferir boletos entre usuarios

- [ ] Servicios
  - [ ] `services/transfer_service.py`
    - [ ] Iniciar transferencia
    - [ ] Aceptar transferencia
    - [ ] Registrar en unit_transfer_log
    - [ ] Regenerar QR para nuevo dueno
- [ ] Router `routers/transfers.py`:
  - [ ] POST /transfers/initiate
  - [ ] POST /transfers/accept
  - [ ] GET /transfers/history

### FASE 8: Dashboard y Reportes
**Objetivo:** Metricas para organizadores

- [ ] Router `routers/dashboard.py`:
  - [ ] GET /dashboard/sales - Ventas por evento
  - [ ] GET /dashboard/occupancy - Ocupacion por area
  - [ ] GET /dashboard/revenue - Ingresos
- [ ] Servicios de reportes
- [ ] Exportacion a CSV/Excel (opcional)

---

## Consideraciones de Multi-Tenancy

### Patron de Aislamiento
El sistema usa `profile_id` en la tabla `clusters` como identificador de tenant (organizador del evento).

```sql
-- Todas las consultas deben filtrar por organizador
SELECT * FROM clusters WHERE profile_id = $1;

-- Las areas y units heredan el tenant via cluster
SELECT a.* FROM areas a
JOIN clusters c ON a.cluster_id = c.id
WHERE c.profile_id = $1;
```

### Middleware de Tenant
El middleware detecta el tenant desde:
1. Header `Referer` / `Origin`
2. Mapeo `tenant_sites` en BD
3. Configuracion de desarrollo

### Reglas de Aislamiento
1. Nunca mostrar datos de otros organizadores
2. Validar permisos en cada operacion
3. Usar RLS en BD como capa adicional

---

## Integraciones Requeridas

### Pasarela de Pagos
- **Wompi** (Colombia) - Principal
- **PayU** - Alternativa
- Webhooks para confirmacion asincrona

### Notificaciones
- **AWS SES** - Emails transaccionales
- **Discord** - Alertas internas

### Storage
- **Cloudflare R2** - Imagenes de eventos y QR codes

---

## Variables de Entorno Necesarias

```env
# Database
NUXT_PRIVATE_DB_USER=
NUXT_PRIVATE_DB_HOST=
NUXT_PRIVATE_DB_PASSWORD=
NUXT_PRIVATE_DB_PORT=
NUXT_PRIVATE_DB_NAME=

# Auth
NUXT_PRIVATE_AUTH_SECRET=
NUXT_PRIVATE_JWT_SECRET=

# AWS SES
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=
EMAIL_FROM=

# Cloudflare R2
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_ENDPOINT=
R2_BUCKET=

# Pasarela de pagos
WOMPI_PUBLIC_KEY=
WOMPI_PRIVATE_KEY=
WOMPI_EVENTS_SECRET=
WOMPI_ENVIRONMENT=

# Discord
DISCORD_WEBHOOK_URL=
DISCORD_ERROR_WEBHOOK_URL=

# App
ENVIRONMENT=development
BASE_URL=http://localhost:8001
PORT=8001
DEBUG=true
CORS_ORIGINS=http://localhost:3000,http://localhost:3001
```

---

## Proximos Pasos Inmediatos

1. **Crear archivos base** copiando de api_warocol.com
2. **Adaptar middleware** para el contexto de tickets
3. **Implementar FASE 1** completa
4. **Probar conexion** a BD y autenticacion
5. **Continuar con FASE 2**

---

## Notas Adicionales

- El proyecto comparte la misma BD que warolabs/api_warocol
- Los eventos se identifican como `clusters` en la BD
- El sistema ya soporta precios dinamicos via `sale_stages`
- Los QR deben ser unicos y regenerables en transferencias
- Considerar limite de transferencias por boleto
