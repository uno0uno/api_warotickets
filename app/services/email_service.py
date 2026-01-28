import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal
import boto3
from botocore.exceptions import ClientError
from app.config import settings

logger = logging.getLogger(__name__)


def get_ses_client():
    """Get AWS SES client"""
    return boto3.client(
        'ses',
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key
    )


async def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None
) -> bool:
    """Send email via AWS SES"""
    try:
        client = get_ses_client()

        message = {
            'Subject': {'Data': subject, 'Charset': 'UTF-8'},
            'Body': {
                'Html': {'Data': html_body, 'Charset': 'UTF-8'}
            }
        }

        if text_body:
            message['Body']['Text'] = {'Data': text_body, 'Charset': 'UTF-8'}

        response = client.send_email(
            Source=f"WaRo Tickets <{settings.aws_ses_from_email}>",
            Destination={'ToAddresses': [to_email]},
            Message=message
        )

        logger.info(f"Email sent to {to_email}: {response['MessageId']}")
        return True

    except ClientError as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        return False


async def send_transfer_notification(
    recipient_email: str,
    sender_name: str,
    event_name: str,
    event_date: Optional[datetime],
    area_name: str,
    unit_display_name: str,
    transfer_token: str,
    message: Optional[str] = None,
    expires_at: Optional[datetime] = None
) -> bool:
    """Send transfer notification email to recipient (plain text, same style as purchase confirmation)"""
    try:
        accept_url = f"{settings.frontend_url}/transfers/accept?token={transfer_token}"

        event_date_str = event_date.strftime('%d de %B de %Y a las %H:%M') if event_date else 'Por confirmar'
        expires_str = expires_at.strftime('%d/%m/%Y a las %H:%M') if expires_at else '48 horas'

        text_body = f"""Hola!

{sender_name} quiere transferirte un boleto en WaRo Tickets.

DETALLE DEL BOLETO
--------------------
Evento: {event_name}
Fecha: {event_date_str}
Zona: {area_name}
Ubicacion: {unit_display_name}
{f"Mensaje: {message}" if message else ""}

ACEPTAR TRANSFERENCIA
--------------------
Para aceptar este boleto, haz clic aqui:
{accept_url}

IMPORTANTE
--------------------
- Esta transferencia expira el {expires_str}
- Si no deseas aceptar, simplemente ignora este correo
- Al aceptar, se generara un nuevo codigo QR a tu nombre

----
{settings.email_signature}
"""

        client = get_ses_client()

        response = client.send_email(
            Source=f"{settings.aws_ses_from_name} <{settings.aws_ses_from_email}>",
            Destination={'ToAddresses': [recipient_email]},
            Message={
                'Subject': {'Data': f"Te transfirieron un boleto para {event_name}", 'Charset': 'UTF-8'},
                'Body': {
                    'Text': {'Data': text_body, 'Charset': 'UTF-8'}
                }
            }
        )

        logger.info(f"Transfer notification sent to {recipient_email}: {response['MessageId']}")
        return True

    except ClientError as e:
        logger.error(f"Failed to send transfer notification to {recipient_email}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error sending transfer notification: {e}")
        return False


async def send_purchase_confirmation(
    to_email: str,
    buyer_name: str,
    event_name: str,
    event_date: Optional[datetime],
    tickets: list,  # [{area_name, unit_display_name, price}]
    total_amount: float,
    reservation_id: int
) -> bool:
    """Send purchase confirmation email"""
    event_date_str = event_date.strftime("%d de %B, %Y - %H:%M") if event_date else "Por confirmar"
    my_tickets_url = f"{settings.frontend_url}/my-tickets"

    tickets_html = ""
    for ticket in tickets:
        tickets_html += f"""
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #eee;">{ticket['area_name']}</td>
            <td style="padding: 10px; border-bottom: 1px solid #eee;">{ticket['unit_display_name']}</td>
            <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: right;">${ticket['price']:,.0f}</td>
        </tr>
        """

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
            .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
            .event-info {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th {{ background: #f0f0f0; padding: 10px; text-align: left; }}
            .total {{ font-size: 1.2em; font-weight: bold; text-align: right; padding: 15px; background: #e8f5e9; border-radius: 8px; margin-top: 15px; }}
            .btn {{ display: inline-block; background: #28a745; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
            .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 30px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>✅ ¡Compra Confirmada!</h1>
            </div>
            <div class="content">
                <p>Hola {buyer_name},</p>
                <p>Tu compra ha sido procesada exitosamente. Aquí están los detalles:</p>

                <div class="event-info">
                    <h3 style="margin-top: 0;">📍 {event_name}</h3>
                    <p><strong>Fecha:</strong> {event_date_str}</p>
                    <p><strong>Referencia:</strong> #{reservation_id}</p>
                </div>

                <h4>Tus Boletos:</h4>
                <table>
                    <thead>
                        <tr>
                            <th>Zona</th>
                            <th>Ubicación</th>
                            <th style="text-align: right;">Precio</th>
                        </tr>
                    </thead>
                    <tbody>
                        {tickets_html}
                    </tbody>
                </table>

                <div class="total">
                    Total: ${total_amount:,.0f} COP
                </div>

                <p style="text-align: center;">
                    <a href="{my_tickets_url}" class="btn">Ver Mis Boletos</a>
                </p>

                <p><strong>Importante:</strong></p>
                <ul>
                    <li>Guarda este correo como comprobante</li>
                    <li>El día del evento, presenta el código QR de tu boleto</li>
                    <li>Cada boleto tiene un QR único e intransferible</li>
                </ul>

                <div class="footer">
                    <p>Gracias por tu compra - WaRo Tickets</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    return await send_email(
        to_email=to_email,
        subject=f"✅ Compra confirmada - {event_name}",
        html_body=html_body
    )


async def send_transfer_accepted_notification(
    sender_email: str,
    sender_name: str,
    recipient_email: str,
    event_name: str,
    area_name: str,
    unit_display_name: str
) -> bool:
    """Notify sender that their transfer was accepted (plain text)"""
    try:
        text_body = f"""Hola {sender_name}!

Tu transferencia fue aceptada.

DETALLE
--------------------
Evento: {event_name}
Zona: {area_name}
Ubicacion: {unit_display_name}
Destinatario: {recipient_email}

El boleto ya no esta vinculado a tu cuenta.

----
{settings.email_signature}
"""

        client = get_ses_client()

        response = client.send_email(
            Source=f"{settings.aws_ses_from_name} <{settings.aws_ses_from_email}>",
            Destination={'ToAddresses': [sender_email]},
            Message={
                'Subject': {'Data': f"Transferencia aceptada - {event_name}", 'Charset': 'UTF-8'},
                'Body': {
                    'Text': {'Data': text_body, 'Charset': 'UTF-8'}
                }
            }
        )

        logger.info(f"Transfer accepted notification sent to {sender_email}: {response['MessageId']}")
        return True

    except ClientError as e:
        logger.error(f"Failed to send transfer accepted notification to {sender_email}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error sending transfer accepted notification: {e}")
        return False


async def send_transfer_received_notification(
    recipient_email: str,
    sender_name: str,
    event_name: str,
    event_date: Optional[datetime],
    area_name: str,
    unit_display_name: str
) -> bool:
    """Notify recipient that they received a ticket via transfer (plain text)"""
    try:
        event_date_str = event_date.strftime('%d de %B de %Y a las %H:%M') if event_date else 'Por confirmar'
        my_tickets_url = f"{settings.frontend_url}/mis-boletas"

        text_body = f"""Hola!

Has recibido un boleto de {sender_name} en WaRo Tickets.

DETALLE DEL BOLETO
--------------------
Evento: {event_name}
Fecha: {event_date_str}
Zona: {area_name}
Ubicacion: {unit_display_name}

VER TUS BOLETAS
--------------------
Ingresa a tu cuenta para ver tu boleto y codigo QR:
{my_tickets_url}

----
{settings.email_signature}
"""

        client = get_ses_client()

        response = client.send_email(
            Source=f"{settings.aws_ses_from_name} <{settings.aws_ses_from_email}>",
            Destination={'ToAddresses': [recipient_email]},
            Message={
                'Subject': {'Data': f"Recibiste un boleto para {event_name}", 'Charset': 'UTF-8'},
                'Body': {
                    'Text': {'Data': text_body, 'Charset': 'UTF-8'}
                }
            }
        )

        logger.info(f"Transfer received notification sent to {recipient_email}: {response['MessageId']}")
        return True

    except ClientError as e:
        logger.error(f"Failed to send transfer received notification to {recipient_email}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error sending transfer received notification: {e}")
        return False


async def send_simple_purchase_confirmation(
    to_email: str,
    event_name: str,
    event_date: Optional[datetime],
    event_location: Optional[str],
    tickets: List[Dict[str, Any]],
    subtotal: Decimal,
    service_fee: Decimal,
    total: Decimal,
    reference: str,
    payment_method: Optional[str] = None,
    access_url: Optional[str] = None
) -> bool:
    """
    Send simple text-based purchase confirmation email.
    Similar style to WARO COLOMBIA - plain text, no fancy HTML.

    Args:
        to_email: Customer email
        event_name: Name of the event
        event_date: Date of the event
        event_location: Venue/location
        tickets: List of tickets [{area_name, quantity, unit_price, subtotal}]
        subtotal: Subtotal before fees
        service_fee: Service fee amount
        total: Total amount paid
        reference: Payment reference
        payment_method: Payment method used (optional)
    """
    try:
        # Format date
        if event_date:
            event_date_str = event_date.strftime('%d de %B de %Y a las %H:%M')
        else:
            event_date_str = 'Por confirmar'

        # Build tickets list
        tickets_list = ""
        total_tickets = 0
        for ticket in tickets:
            qty = ticket.get('quantity', 1)
            total_tickets += qty
            area = ticket.get('area_name', 'General')
            price = ticket.get('unit_price', 0)
            ticket_subtotal = ticket.get('subtotal', price * qty)
            tickets_list += f"  - {qty}x {area}: ${ticket_subtotal:,.0f} COP\n"

        # Format amounts
        subtotal_str = f"${subtotal:,.0f}" if subtotal else "$0"
        service_fee_str = f"${service_fee:,.0f}" if service_fee else "$0"
        total_str = f"${total:,.0f}" if total else "$0"

        # Build text email
        text_body = f"""Hola!

Tu compra en WaRo Tickets ha sido confirmada.

RESUMEN DE TU COMPRA
--------------------
Referencia: {reference}
Evento: {event_name}
Fecha: {event_date_str}
{f"Lugar: {event_location}" if event_location else ""}

BOLETAS ({total_tickets} en total)
--------------------
{tickets_list}
DETALLE DEL PAGO
--------------------
Subtotal: {subtotal_str} COP
Cargo por servicio: {service_fee_str} COP
TOTAL PAGADO: {total_str} COP
{f"Metodo de pago: {payment_method}" if payment_method else ""}

ACCEDE A TUS BOLETAS
--------------------
{f"Para ver tus boletas y codigos QR, haz clic aqui:\n{access_url}" if access_url else f"Puedes ver tus boletas en: {settings.frontend_url}/mis-boletas"}

IMPORTANTE
--------------------
- Guarda este correo como comprobante de tu compra
- El dia del evento presenta el codigo QR de cada boleta

Gracias por tu compra!

----
{settings.email_signature}
"""

        # Send email (text only to avoid spam filters)
        client = get_ses_client()

        response = client.send_email(
            Source=f"{settings.aws_ses_from_name} <{settings.aws_ses_from_email}>",
            Destination={'ToAddresses': [to_email]},
            Message={
                'Subject': {'Data': f"Compra confirmada - {event_name}", 'Charset': 'UTF-8'},
                'Body': {
                    'Text': {'Data': text_body, 'Charset': 'UTF-8'}
                }
            }
        )

        logger.info(f"Purchase confirmation sent to {to_email}: {response['MessageId']}")
        return True

    except ClientError as e:
        logger.error(f"Failed to send purchase confirmation to {to_email}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error sending purchase confirmation: {e}")
        return False
