import logging
from typing import Optional
from datetime import datetime
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
    """Send transfer notification email to recipient"""
    accept_url = f"{settings.frontend_url}/transfers/accept?token={transfer_token}"

    event_date_str = event_date.strftime("%d de %B, %Y") if event_date else "Por confirmar"
    expires_str = expires_at.strftime("%d/%m/%Y a las %H:%M") if expires_at else "48 horas"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
            .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
            .ticket-info {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #667eea; }}
            .btn {{ display: inline-block; background: #667eea; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
            .message {{ background: #fff3cd; padding: 15px; border-radius: 8px; margin: 15px 0; }}
            .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 30px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🎫 Te han transferido un boleto</h1>
            </div>
            <div class="content">
                <p>Hola,</p>
                <p><strong>{sender_name}</strong> quiere transferirte un boleto para:</p>

                <div class="ticket-info">
                    <h3 style="margin-top: 0;">📍 {event_name}</h3>
                    <p><strong>Fecha:</strong> {event_date_str}</p>
                    <p><strong>Zona:</strong> {area_name}</p>
                    <p><strong>Ubicación:</strong> {unit_display_name}</p>
                </div>

                {"<div class='message'><strong>Mensaje del remitente:</strong><br>" + message + "</div>" if message else ""}

                <p style="text-align: center;">
                    <a href="{accept_url}" class="btn">Aceptar Transferencia</a>
                </p>

                <p style="color: #dc3545;"><strong>⏰ Esta transferencia expira el {expires_str}</strong></p>

                <p>Si no deseas aceptar este boleto, simplemente ignora este correo.</p>

                <div class="footer">
                    <p>Este correo fue enviado por WaRo Tickets</p>
                    <p>Si tienes problemas con el botón, copia y pega este enlace: {accept_url}</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    text_body = f"""
    Te han transferido un boleto

    {sender_name} quiere transferirte un boleto para:

    Evento: {event_name}
    Fecha: {event_date_str}
    Zona: {area_name}
    Ubicación: {unit_display_name}

    {"Mensaje: " + message if message else ""}

    Para aceptar la transferencia, visita:
    {accept_url}

    Esta transferencia expira el {expires_str}
    """

    return await send_email(
        to_email=recipient_email,
        subject=f"🎫 {sender_name} te transfirió un boleto para {event_name}",
        html_body=html_body,
        text_body=text_body
    )


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
    recipient_name: str,
    event_name: str,
    unit_display_name: str
) -> bool:
    """Notify sender that transfer was accepted"""
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: #17a2b8; color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
            .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>✅ Transferencia Aceptada</h1>
            </div>
            <div class="content">
                <p>Hola {sender_name},</p>
                <p><strong>{recipient_name}</strong> ha aceptado la transferencia del boleto:</p>
                <ul>
                    <li><strong>Evento:</strong> {event_name}</li>
                    <li><strong>Ubicación:</strong> {unit_display_name}</li>
                </ul>
                <p>El boleto ahora pertenece a {recipient_name}.</p>
            </div>
        </div>
    </body>
    </html>
    """

    return await send_email(
        to_email=sender_email,
        subject=f"✅ Transferencia aceptada - {event_name}",
        html_body=html_body
    )
