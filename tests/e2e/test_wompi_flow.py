#!/usr/bin/env python3
"""
E2E Test: Flujo de Pago Real con Wompi

Este script prueba el flujo completo con la pasarela real de Wompi (sandbox):
1. Crear reservación
2. Crear payment intent
3. Abrir checkout de Wompi
4. Verificar estado del pago

Uso:
    python tests/e2e/test_wompi_flow.py

Tarjetas de prueba Wompi:
    - Aprobada: 4242 4242 4242 4242
    - Rechazada: 4111 1111 1111 1111
    - CVV: 123
    - Fecha: Cualquier fecha futura (ej: 12/28)
"""
import httpx
import asyncio
import webbrowser
import sys
from datetime import datetime

# ============================================================
# CONFIGURACION - Modificar segun tu entorno
# ============================================================
BASE_URL = "http://localhost:8001"
# Webhook: servidor-a-servidor (necesita túnel público)
WEBHOOK_URL = "https://empty-cats-burn.loca.lt"
# Redirect: navegador del usuario (puede ser localhost)
# Wompi redirige a: {REDIRECT_URL}?id=TRANSACTION_ID&env=test
REDIRECT_URL = "http://localhost:8001/payments/checkout/result"
SESSION_TOKEN = "bde1489f-9ee4-4de1-9c3f-d31b26f13ce6"

# Datos de prueba
CLUSTER_ID = 23  # Festival de las Madres
UNIT_IDS = [34199, 34200]  # Zona General disponibles (110K COP c/u)
CUSTOMER_EMAIL = "anderson.electronico@gmail.com"
CUSTOMER_NAME = "Anderson Test"
GATEWAY = "wompi"  # wompi, bold, mercadopago


# ============================================================
# COLORES PARA TERMINAL
# ============================================================
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")


def print_step(step: int, text: str):
    print(f"\n{Colors.CYAN}[PASO {step}]{Colors.END} {Colors.BOLD}{text}{Colors.END}")


def print_success(text: str):
    print(f"  {Colors.GREEN}✓{Colors.END} {text}")


def print_error(text: str):
    print(f"  {Colors.RED}✗{Colors.END} {text}")


def print_info(text: str):
    print(f"  {Colors.YELLOW}→{Colors.END} {text}")


def print_data(label: str, value: str):
    print(f"  {Colors.CYAN}{label}:{Colors.END} {value}")


# ============================================================
# FUNCIONES DE PRUEBA
# ============================================================
async def create_reservation(client: httpx.AsyncClient) -> dict:
    """Crear una nueva reservación"""
    headers = {
        "Content-Type": "application/json",
        "Cookie": f"session-token={SESSION_TOKEN}"
    }

    data = {
        "cluster_id": CLUSTER_ID,
        "unit_ids": UNIT_IDS,
        "email": CUSTOMER_EMAIL
    }

    response = await client.post(
        f"{BASE_URL}/reservations",
        json=data,
        headers=headers
    )

    if response.status_code == 201:
        result = response.json()
        return result.get("reservation", result)
    else:
        raise Exception(f"Error {response.status_code}: {response.text}")


async def create_payment_intent(client: httpx.AsyncClient, reservation_id: str) -> dict:
    """Crear payment intent con el gateway especificado"""
    data = {
        "reservation_id": reservation_id,
        "gateway": GATEWAY,
        "customer_email": CUSTOMER_EMAIL,
        "customer_name": CUSTOMER_NAME,
        "return_url": REDIRECT_URL  # Redirect a localhost (navegador)
    }

    response = await client.post(
        f"{BASE_URL}/payments/intent",
        json=data,
        headers={"Content-Type": "application/json"}
    )

    if response.status_code == 201:
        return response.json()
    else:
        raise Exception(f"Error {response.status_code}: {response.text}")


async def check_payment_status(client: httpx.AsyncClient, payment_id: int) -> dict:
    """Verificar estado del pago"""
    response = await client.get(f"{BASE_URL}/payments/{payment_id}/status")

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Error {response.status_code}: {response.text}")


async def check_reservation_status(client: httpx.AsyncClient, reservation_id: str) -> dict:
    """Verificar estado de la reservación"""
    headers = {"Cookie": f"session-token={SESSION_TOKEN}"}
    response = await client.get(
        f"{BASE_URL}/reservations/{reservation_id}",
        headers=headers
    )

    if response.status_code == 200:
        return response.json()
    else:
        return {"status": "unknown", "error": response.text}


# ============================================================
# FLUJO PRINCIPAL
# ============================================================
async def run_test():
    print_header("PRUEBA E2E: FLUJO DE PAGO CON WOMPI")
    print(f"\nServidor: {BASE_URL}")
    print(f"Gateway: {GATEWAY.upper()}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    async with httpx.AsyncClient(timeout=30.0) as client:

        # ========================================
        # PASO 1: Crear Reservación
        # ========================================
        print_step(1, "Crear Reservación")

        try:
            reservation = await create_reservation(client)
            reservation_id = reservation["id"]
            print_success("Reservación creada exitosamente")
            print_data("ID", reservation_id)
            print_data("Status", reservation["status"])
            print_data("Total", f"{reservation.get('total', 'N/A')} {reservation.get('currency', 'COP')}")
            print_data("Unidades", str(len(reservation.get("units", []))))
        except Exception as e:
            print_error(f"Error: {e}")
            return

        # ========================================
        # PASO 2: Crear Payment Intent
        # ========================================
        print_step(2, f"Crear Payment Intent ({GATEWAY.upper()})")

        try:
            intent = await create_payment_intent(client, reservation_id)
            payment_id = intent["payment_id"]
            checkout_url = intent.get("checkout_url")
            print_success("Payment intent creado exitosamente")
            print_data("Payment ID", str(payment_id))
            print_data("Reference", intent.get("reference", "N/A"))
            print_data("Gateway Order", intent.get("gateway_order_id", "N/A"))
            print_data("Monto", f"{intent.get('amount', 'N/A')} {intent.get('currency', 'COP')}")
        except Exception as e:
            print_error(f"Error: {e}")
            return

        # ========================================
        # PASO 3: Mostrar URL de Checkout
        # ========================================
        print_step(3, "Checkout URL")

        if checkout_url:
            print_success("URL de checkout obtenida")
            print(f"\n  {Colors.BOLD}{Colors.GREEN}CHECKOUT URL:{Colors.END}")
            print(f"  {Colors.CYAN}{checkout_url}{Colors.END}")

            print(f"\n  {Colors.YELLOW}TARJETAS DE PRUEBA WOMPI:{Colors.END}")
            print(f"  ┌{'─'*50}┐")
            print(f"  │ {Colors.GREEN}APROBADA:{Colors.END} 4242 4242 4242 4242              │")
            print(f"  │ {Colors.RED}RECHAZADA:{Colors.END} 4111 1111 1111 1111             │")
            print(f"  │ CVV: 123                                        │")
            print(f"  │ Fecha: Cualquier fecha futura (ej: 12/28)       │")
            print(f"  └{'─'*50}┘")

            # Preguntar si abrir en navegador
            print(f"\n  ¿Abrir checkout en el navegador? [S/n]: ", end="")
            try:
                response = input().strip().lower()
                if response != 'n':
                    webbrowser.open(checkout_url)
                    print_info("Navegador abierto. Completa el pago...")
            except:
                pass
        else:
            print_error("No se obtuvo URL de checkout")
            print_info("Esto puede ser normal si Wompi requiere configuración adicional")

        # ========================================
        # PASO 4: Esperar y Verificar
        # ========================================
        print_step(4, "Verificar Estado del Pago")

        print_info("Esperando confirmación del pago...")
        print_info("(Presiona Ctrl+C para salir y verificar manualmente)")

        try:
            for i in range(60):  # Esperar hasta 5 minutos (60 * 5 segundos)
                await asyncio.sleep(5)

                # Verificar estado del pago
                try:
                    payment = await check_payment_status(client, payment_id)
                    status = payment.get("status", "unknown")

                    if status == "approved":
                        print_success(f"¡PAGO APROBADO!")
                        print_data("Transaction ID", payment.get("payment_gateway_transaction_id", "N/A"))

                        # Verificar reservación
                        res = await check_reservation_status(client, reservation_id)
                        print_data("Reservation Status", res.get("status", "unknown"))
                        break

                    elif status in ["declined", "voided", "error"]:
                        print_error(f"Pago {status}")
                        print_data("Mensaje", payment.get("status_message", "N/A"))
                        break

                    else:
                        print(f"\r  Verificando... ({i*5}s) - Status: {status}", end="", flush=True)

                except Exception as e:
                    print(f"\r  Verificando... ({i*5}s) - Error: {e}", end="", flush=True)

        except KeyboardInterrupt:
            print("\n")
            print_info("Verificación interrumpida")

        # ========================================
        # RESUMEN FINAL
        # ========================================
        print_header("RESUMEN")
        print_data("Reservation ID", reservation_id)
        print_data("Payment ID", str(payment_id))
        print_data("Gateway", GATEWAY)

        print(f"\n{Colors.YELLOW}Comandos para verificar manualmente:{Colors.END}")
        print(f"  curl {BASE_URL}/payments/{payment_id}/status")
        print(f"  curl -H 'Cookie: session-token={SESSION_TOKEN}' {BASE_URL}/reservations/{reservation_id}")


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    print(f"""
{Colors.BOLD}{Colors.CYAN}
╔═══════════════════════════════════════════════════════════╗
║           WARO TICKETS - TEST DE PAGO WOMPI               ║
╚═══════════════════════════════════════════════════════════╝
{Colors.END}""")

    try:
        asyncio.run(run_test())
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Test cancelado por el usuario{Colors.END}")
    except Exception as e:
        print(f"\n{Colors.RED}Error fatal: {e}{Colors.END}")
        sys.exit(1)
