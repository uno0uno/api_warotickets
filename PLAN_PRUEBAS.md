# Plan de Pruebas Unitarias - WaRo Tickets API

## 📋 Resumen

Este documento describe el plan de pruebas unitarias para el backend de WaRo Tickets API.

---

## 🏗️ Estructura de Tests

```
tests/
├── __init__.py
├── conftest.py                 # Fixtures globales (DB, cliente, auth)
├── test_health.py              # Tests básicos de salud
├── unit/                       # Tests unitarios
│   ├── __init__.py
│   ├── test_auth.py
│   ├── test_events.py
│   ├── test_areas.py
│   ├── test_units.py
│   ├── test_sale_stages.py
│   ├── test_promotions.py
│   ├── test_reservations.py
│   ├── test_payments.py
│   ├── test_qr.py
│   ├── test_transfers.py
│   ├── test_dashboard.py
│   └── test_uploads.py
├── integration/                # Tests de integración
│   ├── __init__.py
│   ├── test_reservation_flow.py
│   ├── test_payment_flow.py
│   └── test_transfer_flow.py
└── utils/                      # Utilidades de testing
    ├── __init__.py
    ├── factories.py            # Factories para crear datos
    └── mocks.py                # Mocks para servicios externos
```

---

## 🔧 Configuración

### Dependencias (ya en requirements.txt)
- pytest==8.3.4
- pytest-asyncio==0.24.0
- pytest-cov==6.0.0
- httpx==0.27.0 (para TestClient async)

### pytest.ini
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_functions = test_*
addopts = -v --tb=short
```

---

## 📊 Cobertura por Módulo

| Módulo | Archivo Test | Casos | Prioridad |
|--------|--------------|-------|-----------|
| Health | test_health.py | 2 | Alta |
| Auth | test_auth.py | 8 | Alta |
| Events | test_events.py | 10 | Alta |
| Areas | test_areas.py | 8 | Alta |
| Units | test_units.py | 8 | Media |
| Sale Stages | test_sale_stages.py | 6 | Media |
| Promotions | test_promotions.py | 8 | Media |
| Reservations | test_reservations.py | 12 | Alta |
| Payments | test_payments.py | 8 | Alta |
| QR | test_qr.py | 8 | Alta |
| Transfers | test_transfers.py | 10 | Media |
| Dashboard | test_dashboard.py | 8 | Baja |
| Uploads | test_uploads.py | 4 | Baja |

**Total: ~100 casos de prueba**

---

## 🧪 Detalle de Casos de Prueba

### 1. Health (test_health.py)
- [ ] `test_root_endpoint` - GET / retorna info del servicio
- [ ] `test_health_endpoint` - GET /health retorna status healthy

### 2. Auth (test_auth.py)
- [ ] `test_send_magic_link_new_user` - Crea usuario y envía código
- [ ] `test_send_magic_link_existing_user` - Usuario existente recibe código
- [ ] `test_send_magic_link_invalid_email` - Email inválido retorna 422
- [ ] `test_verify_code_success` - Código válido crea sesión
- [ ] `test_verify_code_invalid` - Código inválido retorna 400
- [ ] `test_verify_code_expired` - Código expirado retorna 400
- [ ] `test_get_current_user` - Usuario autenticado obtiene su info
- [ ] `test_get_current_user_unauthorized` - Sin sesión retorna 401

### 3. Events (test_events.py)
- [ ] `test_list_events` - Lista eventos del organizador
- [ ] `test_list_events_filter_active` - Filtra por is_active
- [ ] `test_get_event_by_id` - Obtiene evento por ID
- [ ] `test_get_event_not_found` - Evento no existe retorna 404
- [ ] `test_get_event_not_owner` - No es dueño retorna 404
- [ ] `test_create_event` - Crea evento exitosamente
- [ ] `test_create_event_generates_slug` - Auto-genera slug
- [ ] `test_update_event` - Actualiza evento
- [ ] `test_delete_event` - Soft delete evento
- [ ] `test_get_event_by_slug_public` - Acceso público por slug

### 4. Areas (test_areas.py)
- [ ] `test_list_areas_by_event` - Lista áreas de un evento
- [ ] `test_get_area_by_id` - Obtiene área por ID
- [ ] `test_create_area` - Crea área con capacidad
- [ ] `test_create_area_auto_units` - Crea área y genera units
- [ ] `test_update_area` - Actualiza precio/descripción
- [ ] `test_delete_area` - Elimina área
- [ ] `test_get_area_availability` - Obtiene disponibilidad
- [ ] `test_area_not_found` - Área no existe retorna 404

### 5. Units (test_units.py)
- [ ] `test_list_units_by_area` - Lista units de un área
- [ ] `test_list_units_filter_status` - Filtra por status
- [ ] `test_create_units_bulk` - Crea múltiples units
- [ ] `test_create_units_nomenclature` - Genera nomenclatura correcta
- [ ] `test_update_units_bulk` - Actualiza múltiples units
- [ ] `test_get_unit_by_id` - Obtiene unit por ID
- [ ] `test_reserve_unit` - Reserva unit cambia status
- [ ] `test_release_unit` - Libera unit reservado

### 6. Sale Stages (test_sale_stages.py)
- [ ] `test_list_sale_stages` - Lista etapas de venta
- [ ] `test_get_active_stage` - Obtiene etapa activa
- [ ] `test_create_sale_stage` - Crea etapa con descuento
- [ ] `test_update_sale_stage` - Actualiza etapa
- [ ] `test_delete_sale_stage` - Elimina etapa
- [ ] `test_stage_price_calculation` - Calcula precio con etapa

### 7. Promotions (test_promotions.py)
- [ ] `test_list_promotions` - Lista promociones
- [ ] `test_create_promotion_percentage` - Crea descuento porcentual
- [ ] `test_create_promotion_fixed` - Crea descuento fijo
- [ ] `test_validate_promotion_valid` - Código válido aplica
- [ ] `test_validate_promotion_expired` - Código expirado falla
- [ ] `test_validate_promotion_max_uses` - Límite de usos alcanzado
- [ ] `test_update_promotion` - Actualiza promoción
- [ ] `test_delete_promotion` - Elimina promoción

### 8. Reservations (test_reservations.py)
- [ ] `test_create_reservation` - Crea reserva exitosa
- [ ] `test_create_reservation_units_reserved` - Units cambian a reserved
- [ ] `test_create_reservation_with_promotion` - Aplica código promocional
- [ ] `test_create_reservation_unavailable_units` - Units no disponibles falla
- [ ] `test_get_reservation` - Obtiene reserva por ID
- [ ] `test_confirm_reservation` - Confirma reserva
- [ ] `test_confirm_reservation_units_confirmed` - Units cambian a confirmed
- [ ] `test_cancel_reservation` - Cancela reserva
- [ ] `test_cancel_reservation_releases_units` - Libera units
- [ ] `test_get_my_tickets` - Lista tickets del usuario
- [ ] `test_reservation_timeout` - Reserva expira después de 15 min
- [ ] `test_reservation_price_calculation` - Precio total correcto

### 9. Payments (test_payments.py)
- [ ] `test_create_payment_intent` - Crea intención de pago
- [ ] `test_get_payment_status` - Obtiene estado del pago
- [ ] `test_payment_intent_invalid_reservation` - Reserva inválida falla
- [ ] `test_wompi_webhook_approved` - Webhook aprobado confirma
- [ ] `test_wompi_webhook_declined` - Webhook rechazado cancela
- [ ] `test_wompi_webhook_invalid_signature` - Firma inválida rechaza
- [ ] `test_payment_already_paid` - Reserva ya pagada falla
- [ ] `test_payment_expired_reservation` - Reserva expirada falla

### 10. QR (test_qr.py)
- [ ] `test_generate_qr_code` - Genera QR para ticket
- [ ] `test_generate_qr_image` - Genera imagen PNG
- [ ] `test_qr_contains_signature` - QR incluye firma HMAC
- [ ] `test_validate_qr_valid` - QR válido permite entrada
- [ ] `test_validate_qr_invalid_signature` - Firma alterada rechaza
- [ ] `test_validate_qr_already_used` - Ticket usado rechaza
- [ ] `test_validate_qr_wrong_event` - Evento incorrecto rechaza
- [ ] `test_reset_ticket_status` - Reset de ticket usado

### 11. Transfers (test_transfers.py)
- [ ] `test_initiate_transfer` - Inicia transferencia
- [ ] `test_initiate_transfer_generates_token` - Genera token único
- [ ] `test_initiate_transfer_not_owner` - No es dueño falla
- [ ] `test_initiate_transfer_already_pending` - Ya tiene transfer falla
- [ ] `test_accept_transfer` - Acepta transferencia
- [ ] `test_accept_transfer_new_qr` - Genera nuevo QR
- [ ] `test_accept_transfer_expired` - Transfer expirado falla
- [ ] `test_cancel_transfer` - Cancela transferencia
- [ ] `test_get_outgoing_transfers` - Lista transfers enviados
- [ ] `test_get_incoming_transfers` - Lista transfers recibidos

### 12. Dashboard (test_dashboard.py)
- [ ] `test_get_overview` - Obtiene resumen general
- [ ] `test_get_event_summary` - Resumen de evento
- [ ] `test_get_area_breakdown` - Desglose por área
- [ ] `test_get_sales_chart` - Serie temporal de ventas
- [ ] `test_get_revenue_report` - Reporte de ingresos
- [ ] `test_get_checkin_analytics` - Analíticas de check-in
- [ ] `test_get_attendees_list` - Lista de asistentes
- [ ] `test_dashboard_not_owner` - No es dueño retorna 404

### 13. Uploads (test_uploads.py)
- [ ] `test_upload_image` - Sube imagen exitosamente
- [ ] `test_upload_invalid_type` - Tipo inválido falla
- [ ] `test_upload_too_large` - Archivo muy grande falla
- [ ] `test_delete_image` - Elimina imagen

---

## 🔄 Flujos de Integración

### test_reservation_flow.py
1. Crear evento → Crear área → Crear units
2. Usuario hace reserva
3. Usuario paga con Wompi
4. Webhook confirma pago
5. Usuario obtiene QR
6. Staff valida QR en entrada

### test_payment_flow.py
1. Crear reserva pendiente
2. Crear payment intent
3. Simular webhook Wompi
4. Verificar confirmación
5. Verificar email enviado

### test_transfer_flow.py
1. Usuario A tiene ticket confirmado
2. Usuario A inicia transfer a Usuario B
3. Usuario B acepta transfer
4. Usuario B tiene nuevo QR
5. QR antiguo de Usuario A es inválido

---

## ▶️ Comandos de Ejecución

```bash
# Ejecutar todos los tests
pytest

# Ejecutar con cobertura
pytest --cov=app --cov-report=html

# Ejecutar solo unitarios
pytest tests/unit/

# Ejecutar solo un módulo
pytest tests/unit/test_auth.py

# Ejecutar un test específico
pytest tests/unit/test_auth.py::test_send_magic_link_new_user

# Ejecutar con output verbose
pytest -v

# Ejecutar en paralelo (requiere pytest-xdist)
pytest -n auto

# Ver tests más lentos
pytest --durations=10
```

---

## 📈 Métricas de Cobertura Objetivo

| Métrica | Objetivo |
|---------|----------|
| Cobertura total | > 80% |
| Cobertura routers | > 90% |
| Cobertura services | > 85% |
| Cobertura models | > 70% |

---

## 🚀 Plan de Ejecución

### Fase 1: Configuración (30 min)
1. Crear estructura de carpetas
2. Configurar conftest.py con fixtures
3. Crear factories y mocks

### Fase 2: Tests Críticos (2 horas)
1. test_health.py
2. test_auth.py
3. test_reservations.py
4. test_payments.py
5. test_qr.py

### Fase 3: Tests de Gestión (1.5 horas)
1. test_events.py
2. test_areas.py
3. test_units.py

### Fase 4: Tests de Funcionalidades (1.5 horas)
1. test_sale_stages.py
2. test_promotions.py
3. test_transfers.py

### Fase 5: Tests Complementarios (1 hora)
1. test_dashboard.py
2. test_uploads.py
3. Tests de integración

### Fase 6: Revisión y Cobertura (30 min)
1. Ejecutar cobertura completa
2. Identificar gaps
3. Agregar tests faltantes

**Tiempo total estimado: ~7 horas**
