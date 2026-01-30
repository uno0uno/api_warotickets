"""
Discord Error Notification Service for WaRo Tickets
Sends error notifications to Discord webhook for real-time monitoring
"""
import httpx
import traceback
from datetime import datetime
from typing import Optional, Dict, Any
import logging
from app.config import settings

logger = logging.getLogger(__name__)


class DiscordErrorNotifier:
    """Send error notifications to Discord webhook"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send_error(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        request_info: Optional[Dict[str, Any]] = None
    ):
        """Send error notification to Discord"""
        try:
            error_type = type(error).__name__
            error_message = str(error)
            error_traceback = ''.join(traceback.format_exception(type(error), error, error.__traceback__))

            if len(error_traceback) > 1900:
                error_traceback = error_traceback[:1900] + "\n... (truncado)"

            embed = {
                "title": f"Error: {error_type}",
                "description": error_message[:2000] if error_message else "Sin mensaje",
                "color": 15158332,  # Red
                "timestamp": datetime.utcnow().isoformat(),
                "fields": []
            }

            if request_info:
                request_details = []
                if request_info.get('method'):
                    request_details.append(f"**Metodo:** {request_info['method']}")
                if request_info.get('url'):
                    request_details.append(f"**URL:** {request_info['url']}")
                if request_info.get('client_host'):
                    request_details.append(f"**Cliente:** {request_info['client_host']}")

                if request_details:
                    embed["fields"].append({
                        "name": "Request",
                        "value": "\n".join(request_details),
                        "inline": False
                    })

            if context:
                context_details = [f"**{k}:** {v}" for k, v in context.items()]
                if context_details:
                    embed["fields"].append({
                        "name": "Contexto",
                        "value": "\n".join(context_details)[:1024],
                        "inline": False
                    })

            embed["fields"].append({
                "name": "Traceback",
                "value": f"```python\n{error_traceback[:900]}\n```",
                "inline": False
            })

            embed["fields"].append({
                "name": "Entorno",
                "value": f"**Env:** {settings.environment}",
                "inline": True
            })

            payload = {
                "embeds": [embed],
                "username": "WaRo Tickets Error Monitor"
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.webhook_url, json=payload)
                if response.status_code == 204:
                    logger.info(f"Error notification sent: {error_type}")

        except Exception as e:
            logger.error(f"Failed to send error to Discord: {e}")

    async def send_warning(
        self,
        title: str,
        message: str,
        context: Optional[Dict[str, Any]] = None
    ):
        """Send warning notification to Discord"""
        try:
            embed = {
                "title": f"Advertencia: {title}",
                "description": message[:2000],
                "color": 16776960,  # Yellow
                "timestamp": datetime.utcnow().isoformat()
            }

            if context:
                embed["fields"] = [
                    {"name": k, "value": str(v)[:1024], "inline": True}
                    for k, v in context.items()
                ]

            payload = {
                "embeds": [embed],
                "username": "WaRo Tickets Warning"
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(self.webhook_url, json=payload)

        except Exception as e:
            logger.error(f"Failed to send warning to Discord: {e}")


# Global error notifier instance
error_notifier = None
if settings.discord_error_webhook_url:
    error_notifier = DiscordErrorNotifier(settings.discord_error_webhook_url)
