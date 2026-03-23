"""
Router de leads — endpoints publicos para captura de solicitudes.
No requiere autenticacion.
"""
import logging
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, field_validator
from app.database import get_db_connection
from app.services.email_service import send_email
from app.templates.lead_confirmation_template import (
    get_lead_confirmation_template,
    get_lead_confirmation_subject,
)

logger = logging.getLogger(__name__)

router = APIRouter()

CAMPAIGN_SLUG = "solicitud-organizador-contacto"


class ContactoLeadRequest(BaseModel):
    email: str
    phone: str
    name: Optional[str] = None

    @field_validator("email")
    @classmethod
    def email_must_be_valid(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Email invalido")
        return v

    @field_validator("phone")
    @classmethod
    def phone_must_be_valid(cls, v: str) -> str:
        v = v.strip()
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) < 7:
            raise ValueError("Numero de telefono invalido")
        return v


async def _send_confirmation_email(
    email: str,
    name: Optional[str],
    lead_id: str,
    campaign_id: str,
) -> None:
    """Tarea en background: enviar correo y registrar en email_sends."""
    html = get_lead_confirmation_template(name or "", email)
    subject = get_lead_confirmation_subject()

    try:
        from app.services.email_service import get_ses_client
        import asyncio

        client = get_ses_client()
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.send_email(
                Source="WaRo Tickets <tickets@warotickets.com>",
                Destination={"ToAddresses": [email]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
                },
            ),
        )
        message_id = response.get("MessageId", "")
        status = "sent"
        logger.info(f"[leads] Confirmation email sent to {email}: {message_id}")
    except Exception as exc:
        message_id = ""
        status = "failed"
        logger.error(f"[leads] Failed to send confirmation email to {email}: {exc}")

    # Registrar en email_sends independientemente del resultado
    try:
        async with get_db_connection() as conn:
            await conn.execute(
                """
                INSERT INTO email_sends (campaign_id, lead_id, email, status, message_id)
                VALUES ($1, $2, $3, $4, $5)
                """,
                campaign_id,
                lead_id,
                email,
                status,
                message_id,
            )
    except Exception as exc:
        logger.error(f"[leads] Failed to record email_sends for {email}: {exc}")


@router.post("/contacto", status_code=201)
async def submit_contacto(
    payload: ContactoLeadRequest,
    background_tasks: BackgroundTasks,
    request: Request,
):
    """
    Endpoint publico para capturar solicitudes de acceso como organizador.
    No requiere autenticacion.

    Flujo:
    1. Obtener o crear profile con el email
    2. Insertar lead vinculado al profile
    3. Vincular lead a la campaña solicitud-organizador-contacto
    4. Registrar interaccion form_submit
    5. Enviar correo de confirmacion (background)
    """
    email = payload.email
    phone = payload.phone
    name = payload.name.strip() if payload.name else None

    try:
        async with get_db_connection() as conn:

            # 1. Obtener o crear profile
            profile = await conn.fetchrow(
                "SELECT id FROM profile WHERE email = $1", email
            )
            if profile:
                profile_id = str(profile["id"])
            else:
                new_profile = await conn.fetchrow(
                    """
                    INSERT INTO profile (email, name, phone_number, created_at, updated_at)
                    VALUES ($1, $2, $3, NOW(), NOW())
                    ON CONFLICT (email) DO NOTHING
                    RETURNING id
                    """,
                    email,
                    name or email.split("@")[0],
                    phone,
                )
                if new_profile:
                    profile_id = str(new_profile["id"])
                else:
                    # Race condition: otro request creó el profile justo antes
                    existing = await conn.fetchrow(
                        "SELECT id FROM profile WHERE email = $1", email
                    )
                    profile_id = str(existing["id"])

            # 2. Insertar lead
            lead = await conn.fetchrow(
                """
                INSERT INTO leads
                    (profile_id, email, phone, source, campaign, status,
                     utm_source, utm_medium, utm_campaign)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
                """,
                profile_id,
                email,
                phone,
                "contacto-form",
                CAMPAIGN_SLUG,
                "active",
                "contacto",
                "formulario",
                CAMPAIGN_SLUG,
            )
            lead_id = str(lead["id"])

            # 3. Obtener id de la campaña y vincular lead
            campaign = await conn.fetchrow(
                "SELECT id FROM campaign WHERE slug = $1 AND is_deleted = false LIMIT 1",
                CAMPAIGN_SLUG,
            )
            campaign_id: Optional[str] = None
            if campaign:
                campaign_id = str(campaign["id"])
                await conn.execute(
                    """
                    INSERT INTO campaign_leads (campaign_id, lead_id)
                    VALUES ($1, $2)
                    ON CONFLICT (campaign_id, lead_id) DO NOTHING
                    """,
                    campaign_id,
                    lead_id,
                )

            # 4. Registrar interaccion
            ip = request.client.host if request.client else None
            user_agent = request.headers.get("user-agent")
            await conn.execute(
                """
                INSERT INTO lead_interactions
                    (lead_id, interaction_type, source, campaign, ip_address, user_agent,
                     campaign_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                lead_id,
                "form_submit",
                "contacto-form",
                CAMPAIGN_SLUG,
                ip,
                user_agent,
                campaign_id,
            )

        # 5. Enviar correo en background (no bloquea la respuesta)
        if campaign_id:
            background_tasks.add_task(
                _send_confirmation_email, email, name, lead_id, campaign_id
            )

        return {"success": True}

    except Exception as exc:
        logger.error(f"[leads] Error processing contacto request for {email}: {exc}")
        raise HTTPException(status_code=500, detail="Error al procesar la solicitud")
