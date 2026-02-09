"""
Service for managing team member invitations
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from app.database import get_db_connection
from app.services.email_service import get_ses_client
from app.templates.invitation_template import get_invitation_email_body, get_invitation_subject
from app.config import settings

logger = logging.getLogger(__name__)


async def send_invitation(
    tenant_id: str,
    email: str,
    name: str,
    role: str,
    invited_by_user_id: str,
    phone: Optional[str] = None
) -> dict:
    """
    Send invitation to join a tenant as a team member

    Args:
        tenant_id: ID of the tenant
        email: Email of the person to invite
        name: Name of the person to invite
        role: Role to assign (admin, promotor, member)
        invited_by_user_id: User ID of the person sending the invitation
        phone: Optional phone number

    Returns:
        dict with invitation details

    Raises:
        ValueError: If user already exists or invitation already sent
    """
    async with get_db_connection() as conn:
        # Check if user already exists in this tenant
        existing_member = await conn.fetchrow("""
            SELECT tm.id, p.email
            FROM tenant_members tm
            JOIN profile p ON p.id = tm.user_id
            WHERE tm.tenant_id = $1 AND p.email = $2
        """, tenant_id, email)

        if existing_member:
            raise ValueError(f"El usuario {email} ya es miembro de esta organizacion")

        # Check if there's a pending invitation
        existing_invitation = await conn.fetchrow("""
            SELECT id, status, expires_at
            FROM tenant_invitations
            WHERE tenant_id = $1 AND email = $2 AND status = 'pending'
        """, tenant_id, email)

        if existing_invitation:
            # Check if it's expired
            if existing_invitation['expires_at'] > datetime.now(timezone.utc):
                raise ValueError(f"Ya existe una invitacion pendiente para {email}")
            # If expired, we'll create a new one (old one stays as expired)

        # Generate unique token
        token = secrets.token_urlsafe(32)

        # Set expiration (7 days)
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        # Get tenant name and inviter name
        tenant_info = await conn.fetchrow("""
            SELECT t.name as tenant_name, p.name, p.user_name, p.email
            FROM tenants t, profile p
            WHERE t.id = $1 AND p.id = $2
        """, tenant_id, invited_by_user_id)

        tenant_name = tenant_info['tenant_name'] if tenant_info else 'WaRo Tickets'
        invited_by_name = tenant_info['name'] or tenant_info['user_name'] or tenant_info['email'].split('@')[0] if tenant_info else 'El equipo'

        # Create invitation record
        invitation = await conn.fetchrow("""
            INSERT INTO tenant_invitations (
                id, tenant_id, email, token, expires_at, role, invited_by, status
            )
            VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, 'pending')
            RETURNING id, tenant_id, email, role, invited_by, status, expires_at
        """, tenant_id, email, token, expires_at, role, invited_by_user_id)

        # Generate accept URL
        accept_url = f"{settings.frontend_url}/invitations/accept?token={token}"

        # Send email
        try:
            email_body = get_invitation_email_body(
                invitee_name=name,
                invitee_email=email,
                tenant_name=tenant_name,
                role=role,
                invited_by_name=invited_by_name,
                accept_url=accept_url
            )

            subject = get_invitation_subject(tenant_name)

            client = get_ses_client()
            response = client.send_email(
                Source=f"{settings.aws_ses_from_name} <{settings.aws_ses_from_email}>",
                Destination={'ToAddresses': [email]},
                Message={
                    'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                    'Body': {
                        'Text': {'Data': email_body, 'Charset': 'UTF-8'}
                    }
                }
            )

            logger.info(f"Invitation email sent to {email}: {response['MessageId']}")

        except Exception as e:
            logger.error(f"Failed to send invitation email to {email}: {e}")
            # Don't fail the invitation creation if email fails
            # The invitation is still valid and can be resent

        return {
            'id': str(invitation['id']),
            'email': invitation['email'],
            'role': invitation['role'],
            'status': invitation['status'],
            'expires_at': invitation['expires_at'].isoformat(),
            'accept_url': accept_url
        }


async def get_pending_invitations(tenant_id: str) -> list:
    """
    Get all pending invitations for a tenant

    Args:
        tenant_id: ID of the tenant

    Returns:
        List of pending invitations
    """
    async with get_db_connection(use_transaction=False) as conn:
        rows = await conn.fetch("""
            SELECT
                ti.id,
                ti.email,
                ti.role,
                ti.status,
                ti.expires_at,
                ti.invited_by,
                p.name as invited_by_name,
                p.email as invited_by_email
            FROM tenant_invitations ti
            LEFT JOIN profile p ON p.id = ti.invited_by
            WHERE ti.tenant_id = $1 AND ti.status = 'pending'
            ORDER BY ti.expires_at DESC
        """, tenant_id)

        return [dict(row) for row in rows]


async def cancel_invitation(invitation_id: str, tenant_id: str) -> bool:
    """
    Cancel a pending invitation

    Args:
        invitation_id: ID of the invitation
        tenant_id: ID of the tenant (for authorization)

    Returns:
        True if cancelled, False if not found
    """
    async with get_db_connection() as conn:
        result = await conn.execute("""
            UPDATE tenant_invitations
            SET status = 'cancelled'
            WHERE id = $1 AND tenant_id = $2 AND status = 'pending'
        """, invitation_id, tenant_id)

        # Check if any row was updated
        return result.split()[-1] == '1'


async def resend_invitation(invitation_id: str, tenant_id: str) -> dict:
    """
    Resend an invitation email

    Args:
        invitation_id: ID of the invitation
        tenant_id: ID of the tenant (for authorization)

    Returns:
        Invitation details

    Raises:
        ValueError: If invitation not found or already accepted
    """
    async with get_db_connection() as conn:
        invitation = await conn.fetchrow("""
            SELECT ti.*, t.name as tenant_name, p.name as invited_by_name
            FROM tenant_invitations ti
            JOIN tenants t ON t.id = ti.tenant_id
            LEFT JOIN profile p ON p.id = ti.invited_by
            WHERE ti.id = $1 AND ti.tenant_id = $2
        """, invitation_id, tenant_id)

        if not invitation:
            raise ValueError("Invitacion no encontrada")

        if invitation['status'] != 'pending':
            raise ValueError(f"No se puede reenviar: invitacion {invitation['status']}")

        if invitation['expires_at'] < datetime.now(timezone.utc):
            raise ValueError("La invitacion ha expirado. Crea una nueva invitacion.")

        # Generate accept URL
        accept_url = f"{settings.frontend_url}/invitations/accept?token={invitation['token']}"

        # Resend email
        email_body = get_invitation_email_body(
            invitee_name=invitation['email'].split('@')[0],  # Fallback to email prefix
            invitee_email=invitation['email'],
            tenant_name=invitation['tenant_name'],
            role=invitation['role'],
            invited_by_name=invitation['invited_by_name'] or 'El equipo',
            accept_url=accept_url
        )

        subject = get_invitation_subject(invitation['tenant_name'])

        client = get_ses_client()
        response = client.send_email(
            Source=f"{settings.aws_ses_from_name} <{settings.aws_ses_from_email}>",
            Destination={'ToAddresses': [invitation['email']]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Text': {'Data': email_body, 'Charset': 'UTF-8'}
                }
            }
        )

        logger.info(f"Invitation resent to {invitation['email']}: {response['MessageId']}")

        return {
            'id': str(invitation['id']),
            'email': invitation['email'],
            'role': invitation['role'],
            'status': invitation['status']
        }


async def accept_invitation(token: str) -> dict:
    """
    Accept a team invitation via token.

    Flow:
    1. Find invitation by token
    2. Validate it's pending and not expired
    3. Find or create profile by email
    4. Create tenant_member record
    5. Mark invitation as accepted

    Args:
        token: Invitation token from the URL

    Returns:
        dict with user info and tenant info

    Raises:
        ValueError: If token invalid, expired, or already accepted
    """
    async with get_db_connection() as conn:
        # 1. Find invitation by token
        invitation = await conn.fetchrow("""
            SELECT ti.*, t.name as tenant_name
            FROM tenant_invitations ti
            JOIN tenants t ON t.id = ti.tenant_id
            WHERE ti.token = $1
        """, token)

        if not invitation:
            raise ValueError("Invitación inválida o no encontrada")

        # 2. Validate status
        if invitation['status'] != 'pending':
            raise ValueError("Esta invitación ya fue utilizada o cancelada")

        # 3. Check expiration
        if invitation['expires_at'] < datetime.now(timezone.utc):
            raise ValueError("La invitación ha expirado. Solicita una nueva al administrador.")

        email = invitation['email']
        tenant_id = invitation['tenant_id']
        role = invitation['role'] or 'admin'

        # 4. Find or create profile
        profile = await conn.fetchrow("""
            SELECT id, name, email FROM profile WHERE email = $1
        """, email)

        if not profile:
            # Create new profile
            profile = await conn.fetchrow("""
                INSERT INTO profile (id, email, user_name, created_at)
                VALUES (gen_random_uuid(), $1, $2, now())
                RETURNING id, name, email
            """, email, email.split('@')[0])

        user_id = profile['id']

        # 5. Check if already a member
        existing_member = await conn.fetchrow("""
            SELECT id FROM tenant_members
            WHERE user_id = $1 AND tenant_id = $2
        """, user_id, tenant_id)

        if not existing_member:
            # Create tenant_member
            await conn.execute("""
                INSERT INTO tenant_members (id, tenant_id, user_id, role)
                VALUES (gen_random_uuid(), $1, $2, $3)
            """, tenant_id, user_id, role)

        # 6. Mark invitation as accepted
        await conn.execute("""
            UPDATE tenant_invitations
            SET status = 'accepted', accepted_at = now(), user_id = $1
            WHERE id = $2
        """, user_id, invitation['id'])

        logger.info(f"Invitation accepted: {email} joined tenant {invitation['tenant_name']} as {role}")

        return {
            'success': True,
            'user': {
                'id': str(user_id),
                'name': profile['name'] or email.split('@')[0],
                'email': email
            },
            'tenant': {
                'id': str(tenant_id),
                'name': invitation['tenant_name']
            },
            'role': role
        }
