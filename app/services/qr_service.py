import logging
from typing import Optional
from datetime import datetime
from app.database import get_db_connection
from app.utils.qr_generator import (
    generate_ticket_qr, verify_qr_signature, generate_data_url
)
from app.models.qr import (
    QRCodeResponse, QRValidationRequest, QRValidationResponse,
    ValidationResult, TicketCheckIn, CheckInStats
)
from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


async def generate_qr_for_ticket(
    reservation_unit_id: int,
    user_id: str
) -> QRCodeResponse:
    """Generate QR code for a ticket"""
    async with get_db_connection(use_transaction=False) as conn:
        # Get ticket info
        ticket = await conn.fetchrow("""
            SELECT ru.id, ru.unit_id, ru.status,
                   r.user_id, c.slug_cluster
            FROM reservation_units ru
            JOIN reservations r ON ru.reservation_id = r.id
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            WHERE ru.id = $1
        """, reservation_unit_id)

        if not ticket:
            raise ValidationError("Ticket not found")

        # Verify ownership
        if str(ticket['user_id']) != user_id:
            raise ValidationError("Access denied")

        # Check status
        if ticket['status'] not in ['confirmed', 'used']:
            raise ValidationError(f"Cannot generate QR for ticket with status: {ticket['status']}")

        # Generate QR
        qr_base64 = generate_ticket_qr(
            reservation_unit_id=reservation_unit_id,
            unit_id=ticket['unit_id'],
            user_id=user_id,
            event_slug=ticket['slug_cluster']
        )

        return QRCodeResponse(
            reservation_unit_id=reservation_unit_id,
            qr_code_base64=qr_base64,
            qr_code_data_url=generate_data_url(qr_base64),
            generated_at=datetime.now()
        )


async def validate_qr(
    data: QRValidationRequest,
    validator_user_id: str
) -> QRValidationResponse:
    """
    Validate QR code at event entrance.
    Called by event staff with scanning device.
    """
    # Verify QR signature
    qr_info = verify_qr_signature(data.qr_data)

    if not qr_info:
        return QRValidationResponse(
            is_valid=False,
            result=ValidationResult.INVALID_SIGNATURE,
            message="Codigo QR invalido o alterado"
        )

    async with get_db_connection() as conn:
        # Get ticket info
        ticket = await conn.fetchrow("""
            SELECT ru.id, ru.unit_id, ru.status, ru.original_user_id,
                   r.user_id, r.start_date, r.end_date,
                   u.nomenclature_letter_area, u.nomenclature_number_unit,
                   a.area_name,
                   c.id as cluster_id, c.cluster_name, c.slug_cluster, c.start_date as event_start,
                   p.name as owner_name, p.email as owner_email
            FROM reservation_units ru
            JOIN reservations r ON ru.reservation_id = r.id
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            JOIN profile p ON r.user_id = p.id
            WHERE ru.id = $1
        """, qr_info['reservation_unit_id'])

        if not ticket:
            return QRValidationResponse(
                is_valid=False,
                result=ValidationResult.TICKET_NOT_FOUND,
                message="Boleto no encontrado"
            )

        # Verify event matches
        if ticket['slug_cluster'] != data.event_slug:
            return QRValidationResponse(
                is_valid=False,
                result=ValidationResult.WRONG_EVENT,
                message=f"Este boleto es para otro evento: {ticket['cluster_name']}"
            )

        # Check ticket status
        if ticket['status'] == 'used':
            return QRValidationResponse(
                is_valid=False,
                result=ValidationResult.ALREADY_USED,
                message="Este boleto ya fue utilizado"
            )

        if ticket['status'] == 'transferred':
            return QRValidationResponse(
                is_valid=False,
                result=ValidationResult.TICKET_TRANSFERRED,
                message="Este boleto fue transferido a otro usuario"
            )

        if ticket['status'] == 'cancelled':
            return QRValidationResponse(
                is_valid=False,
                result=ValidationResult.TICKET_CANCELLED,
                message="Este boleto fue cancelado"
            )

        if ticket['status'] != 'confirmed':
            return QRValidationResponse(
                is_valid=False,
                result=ValidationResult.TICKET_NOT_FOUND,
                message=f"Estado de boleto invalido: {ticket['status']}"
            )

        # Check event timing (optional - can allow early entry)
        now = datetime.now(ticket['event_start'].tzinfo) if ticket['event_start'] else datetime.now()

        # Mark ticket as used
        await conn.execute("""
            UPDATE reservation_units
            SET status = 'used', updated_at = NOW()
            WHERE id = $1
        """, qr_info['reservation_unit_id'])

        # Generate display name
        display_name = f"{ticket['nomenclature_letter_area'] or ''}-{ticket['nomenclature_number_unit'] or ticket['unit_id']}".strip('-')

        logger.info(f"Check-in: Ticket {qr_info['reservation_unit_id']} validated by {validator_user_id}")

        return QRValidationResponse(
            is_valid=True,
            result=ValidationResult.VALID,
            message="Boleto valido - Acceso permitido",
            reservation_unit_id=ticket['id'],
            unit_id=ticket['unit_id'],
            unit_display_name=display_name,
            area_name=ticket['area_name'],
            owner_name=ticket['owner_name'],
            owner_email=ticket['owner_email'],
            event_name=ticket['cluster_name'],
            event_date=ticket['event_start']
        )


async def get_check_in_stats(cluster_id: int, profile_id: str) -> Optional[CheckInStats]:
    """Get check-in statistics for an event"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify ownership
        event = await conn.fetchrow("""
            SELECT id, cluster_name FROM clusters
            WHERE id = $1 AND profile_id = $2
        """, cluster_id, profile_id)

        if not event:
            return None

        stats = await conn.fetchrow("""
            SELECT
                COUNT(*) as total_tickets,
                COUNT(*) FILTER (WHERE ru.status = 'used') as checked_in,
                COUNT(*) FILTER (WHERE ru.status = 'confirmed') as pending,
                MAX(ru.updated_at) FILTER (WHERE ru.status = 'used') as last_check_in
            FROM reservation_units ru
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            WHERE a.cluster_id = $1
              AND ru.status IN ('confirmed', 'used')
        """, cluster_id)

        total = stats['total_tickets'] or 0
        checked_in = stats['checked_in'] or 0

        return CheckInStats(
            event_id=cluster_id,
            event_name=event['cluster_name'],
            total_tickets=total,
            checked_in=checked_in,
            pending=stats['pending'] or 0,
            check_in_percentage=round((checked_in / total * 100) if total > 0 else 0, 2),
            last_check_in=stats['last_check_in']
        )


async def reset_ticket_status(
    reservation_unit_id: int,
    profile_id: str
) -> bool:
    """Reset a used ticket back to confirmed (admin function)"""
    async with get_db_connection() as conn:
        # Verify ownership
        ticket = await conn.fetchrow("""
            SELECT ru.id FROM reservation_units ru
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            WHERE ru.id = $1 AND c.profile_id = $2
        """, reservation_unit_id, profile_id)

        if not ticket:
            return False

        result = await conn.execute("""
            UPDATE reservation_units
            SET status = 'confirmed', updated_at = NOW()
            WHERE id = $1 AND status = 'used'
        """, reservation_unit_id)

        reset = result == "UPDATE 1"
        if reset:
            logger.info(f"Reset ticket {reservation_unit_id} status to confirmed")

        return reset
