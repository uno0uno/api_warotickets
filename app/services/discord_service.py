"""
Discord webhook notification service for WaRo Tickets
Sends notifications to Discord channels via webhooks
"""
import logging
import httpx
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class DiscordWebhookService:
    """Service for sending notifications to Discord via webhooks"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send_notification(
        self,
        title: str,
        description: str,
        color: int = 3447003,
        fields: Optional[list[Dict[str, Any]]] = None,
        footer: Optional[str] = None
    ) -> bool:
        """Send a notification to Discord webhook"""
        try:
            embed = {
                "title": title,
                "description": description,
                "color": color,
                "timestamp": datetime.utcnow().isoformat()
            }

            if fields:
                embed["fields"] = fields

            if footer:
                embed["footer"] = {"text": footer}

            payload = {"embeds": [embed]}

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.webhook_url, json=payload)

                if response.status_code == 204:
                    return True
                else:
                    logger.error(f"Discord webhook failed: {response.status_code}")
                    return False

        except httpx.TimeoutException:
            logger.error(f"Discord webhook timeout: {title}")
            return False
        except Exception as e:
            logger.error(f"Discord webhook error: {e}")
            return False

    async def notify_new_reservation(
        self,
        event_name: str,
        area_name: str,
        tickets_count: int,
        buyer_email: str,
        buyer_name: Optional[str] = None
    ) -> bool:
        """Notify about new ticket reservation (card/pending)"""
        description = (
            f"**Evento:** {event_name}\n"
            f"**Zona:** {area_name}\n"
            f"**Boletas:** {tickets_count}\n"
            f"**Comprador:** {buyer_name or buyer_email}"
        )

        return await self.send_notification(
            title="Nueva Reserva",
            description=description,
            color=16776960,  # Yellow
            footer=buyer_email
        )

    async def notify_new_purchase(
        self,
        event_name: str,
        area_name: str,
        tickets_count: int,
        total_amount: float,
        buyer_email: str,
        buyer_name: Optional[str] = None,
        payment_method: Optional[str] = None
    ) -> bool:
        """Notify about confirmed purchase"""
        formatted_amount = "${:,.0f}".format(total_amount).replace(",", ".")

        description = (
            f"**Evento:** {event_name}\n"
            f"**Zona:** {area_name}\n"
            f"**Boletas:** {tickets_count}\n"
            f"**Total:** {formatted_amount} COP\n"
            f"**Comprador:** {buyer_name or buyer_email}"
        )

        if payment_method:
            description += f"\n**Metodo:** {payment_method}"

        return await self.send_notification(
            title="Compra Confirmada",
            description=description,
            color=3066993,  # Green
            footer=buyer_email
        )

    async def notify_new_transfer(
        self,
        event_name: str,
        area_name: str,
        unit_name: str,
        from_email: str,
        to_email: str,
        from_name: Optional[str] = None
    ) -> bool:
        """Notify about new ticket transfer"""
        description = (
            f"**Evento:** {event_name}\n"
            f"**Zona:** {area_name}\n"
            f"**Boleta:** {unit_name}\n"
            f"**De:** {from_name or from_email}\n"
            f"**Para:** {to_email}"
        )

        return await self.send_notification(
            title="Nueva Transferencia",
            description=description,
            color=10181046,  # Purple
            footer=f"{from_email} -> {to_email}"
        )

    async def notify_transfer_accepted(
        self,
        event_name: str,
        area_name: str,
        unit_name: str,
        to_email: str,
        to_name: Optional[str] = None
    ) -> bool:
        """Notify when transfer is accepted"""
        description = (
            f"**Evento:** {event_name}\n"
            f"**Zona:** {area_name}\n"
            f"**Boleta:** {unit_name}\n"
            f"**Nuevo dueno:** {to_name or to_email}"
        )

        return await self.send_notification(
            title="Transferencia Aceptada",
            description=description,
            color=3066993,  # Green
            footer=to_email
        )


# Initialize services from settings
from app.config import settings

discord_card_service = None
discord_purchase_service = None
discord_transfer_service = None

if settings.discord_card_webhook_url:
    discord_card_service = DiscordWebhookService(settings.discord_card_webhook_url)

if settings.discord_purchase_webhook_url:
    discord_purchase_service = DiscordWebhookService(settings.discord_purchase_webhook_url)

if settings.discord_transfer_webhook_url:
    discord_transfer_service = DiscordWebhookService(settings.discord_transfer_webhook_url)
