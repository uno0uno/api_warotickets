"""
Team member invitation email template for WaRo Tickets
Plain text format matching the existing email style
"""
from app.config import settings


def get_invitation_email_body(
    invitee_name: str,
    invitee_email: str,
    tenant_name: str,
    role: str,
    invited_by_name: str,
    accept_url: str
) -> str:
    """
    Generate plain text invitation email body

    Args:
        invitee_name: Name of the person being invited
        invitee_email: Email of the person being invited
        tenant_name: Name of the organization/tenant
        role: Role being assigned (admin, promotor, member)
        invited_by_name: Name of person sending the invitation
        accept_url: URL to accept the invitation

    Returns:
        Plain text email body
    """

    role_labels = {
        'admin': 'Administrador',
        'promotor': 'Promotor',
        'member': 'Miembro'
    }
    role_label = role_labels.get(role, role)

    text_body = f"""Hola {invitee_name}!

{invited_by_name} te ha invitado a unirte al equipo de {tenant_name} en WaRo Tickets.

DETALLES DE LA INVITACION
--------------------
Organizacion: {tenant_name}
Rol asignado: {role_label}
Tu correo: {invitee_email}

ACEPTAR INVITACION
--------------------
Para unirte al equipo, haz clic en el siguiente enlace:
{accept_url}

IMPORTANTE
--------------------
- Esta invitacion expira en 7 dias
- Al aceptar, podras acceder al panel de gestion
- Si no deseas unirte, simplemente ignora este correo

Bienvenido al equipo!

----
{settings.email_signature}
"""

    return text_body


def get_invitation_subject(tenant_name: str) -> str:
    """Generate email subject for invitation"""
    return f"Invitacion al equipo de {tenant_name} - WaRo Tickets"
