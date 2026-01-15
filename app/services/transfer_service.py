import logging
import secrets
from typing import Optional, List
from datetime import datetime, timedelta
from app.database import get_db_connection
from app.models.transfer import (
    Transfer, TransferSummary, TransferLogEntry, PendingTransfer,
    TransferInitiateRequest, TransferResult, TransferStatus
)
from app.utils.qr_generator import generate_ticket_qr, generate_data_url
from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

# Transfer expires after 48 hours
TRANSFER_EXPIRY_HOURS = 48


async def initiate_transfer(
    user_id: str,
    data: TransferInitiateRequest
) -> Transfer:
    """Initiate a ticket transfer to another user"""
    async with get_db_connection() as conn:
        # Get ticket and verify ownership
        ticket = await conn.fetchrow("""
            SELECT ru.id, ru.status, ru.reservation_id,
                   r.user_id, c.cluster_name, c.start_date,
                   a.area_name, u.nomenclature_letter_area, u.nomenclature_number_unit,
                   p.name as owner_name, p.email as owner_email
            FROM reservation_units ru
            JOIN reservations r ON ru.reservation_id = r.id
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            JOIN profile p ON r.user_id = p.id
            WHERE ru.id = $1
        """, data.reservation_unit_id)

        if not ticket:
            raise ValidationError("Ticket not found")

        if str(ticket['user_id']) != user_id:
            raise ValidationError("You don't own this ticket")

        if ticket['status'] != 'confirmed':
            raise ValidationError(f"Cannot transfer ticket with status: {ticket['status']}")

        # Check for existing pending transfer
        existing = await conn.fetchrow("""
            SELECT id FROM unit_transfer_log
            WHERE reservation_unit_id = $1 AND transfer_reason LIKE 'PENDING|%'
        """, data.reservation_unit_id)

        if existing:
            raise ValidationError("This ticket already has a pending transfer")

        # Check if recipient exists
        recipient = await conn.fetchrow(
            "SELECT id, name FROM profile WHERE email = $1",
            data.recipient_email.lower()
        )

        # Generate transfer token
        transfer_token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(hours=TRANSFER_EXPIRY_HOURS)

        # Create transfer record
        # Note: We need to create the ticket_transfers table if it doesn't exist
        # For now, we'll use a simplified approach with unit_transfer_log
        transfer_row = await conn.fetchrow("""
            INSERT INTO unit_transfer_log (
                reservation_unit_id, from_user_id, to_user_id,
                transfer_date, transfer_reason
            ) VALUES ($1, $2, $3, NOW(), $4)
            RETURNING *
        """,
            data.reservation_unit_id,
            user_id,
            recipient['id'] if recipient else None,
            f"PENDING|{transfer_token}|{data.recipient_email}|{expires_at.isoformat()}|{data.message or ''}"
        )

        # Update ticket status
        await conn.execute("""
            UPDATE reservation_units
            SET status = 'transferred', transfer_date = NOW(), updated_at = NOW()
            WHERE id = $1
        """, data.reservation_unit_id)

        display_name = f"{ticket['nomenclature_letter_area'] or ''}-{ticket['nomenclature_number_unit'] or data.reservation_unit_id}".strip('-')

        logger.info(f"Transfer initiated: Ticket {data.reservation_unit_id} from {user_id} to {data.recipient_email}")

        return Transfer(
            id=transfer_row['id'],
            reservation_unit_id=data.reservation_unit_id,
            from_user_id=user_id,
            to_user_id=str(recipient['id']) if recipient else None,
            to_email=data.recipient_email,
            transfer_token=transfer_token,
            status=TransferStatus.PENDING,
            message=data.message,
            initiated_at=datetime.now(),
            expires_at=expires_at,
            from_user_name=ticket['owner_name'],
            from_user_email=ticket['owner_email'],
            to_user_name=recipient['name'] if recipient else None,
            event_name=ticket['cluster_name'],
            event_date=ticket['start_date'],
            area_name=ticket['area_name'],
            unit_display_name=display_name
        )


async def accept_transfer(
    user_id: str,
    user_email: str,
    transfer_token: str
) -> TransferResult:
    """Accept a pending transfer"""
    async with get_db_connection() as conn:
        # Find transfer by token
        transfer = await conn.fetchrow("""
            SELECT utl.*, ru.reservation_id, ru.unit_id, r.user_id as current_owner,
                   c.slug_cluster
            FROM unit_transfer_log utl
            JOIN reservation_units ru ON utl.reservation_unit_id = ru.id
            JOIN reservations r ON ru.reservation_id = r.id
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            WHERE utl.transfer_reason LIKE $1
        """, f"PENDING|{transfer_token}|%")

        if not transfer:
            return TransferResult(
                success=False,
                message="Transfer not found or invalid token"
            )

        # Parse transfer reason to get details
        reason_parts = transfer['transfer_reason'].split('|')
        if len(reason_parts) < 4:
            return TransferResult(
                success=False,
                message="Invalid transfer data"
            )

        _, token, recipient_email, expires_at_str = reason_parts[:4]

        # Verify recipient
        if recipient_email.lower() != user_email.lower():
            return TransferResult(
                success=False,
                message="This transfer was sent to a different email"
            )

        # Check expiration
        expires_at = datetime.fromisoformat(expires_at_str)
        if datetime.now() > expires_at:
            # Mark as expired
            await conn.execute("""
                UPDATE unit_transfer_log
                SET transfer_reason = REPLACE(transfer_reason, 'PENDING|', 'EXPIRED|')
                WHERE id = $1
            """, transfer['id'])

            await conn.execute("""
                UPDATE reservation_units
                SET status = 'confirmed', updated_at = NOW()
                WHERE id = $1
            """, transfer['reservation_unit_id'])

            return TransferResult(
                success=False,
                message="This transfer has expired"
            )

        # Complete the transfer
        # Update transfer log
        await conn.execute("""
            UPDATE unit_transfer_log
            SET to_user_id = $2,
                transfer_reason = REPLACE(transfer_reason, 'PENDING|', 'ACCEPTED|')
            WHERE id = $1
        """, transfer['id'], user_id)

        # Update reservation_unit with new owner
        await conn.execute("""
            UPDATE reservation_units
            SET status = 'confirmed',
                original_user_id = $2,
                transfer_date = NOW(),
                updated_at = NOW()
            WHERE id = $1
        """, transfer['reservation_unit_id'], user_id)

        # Create new reservation for the recipient if needed
        # Or update the existing reservation's user_id
        # For simplicity, we'll just update the original_user_id in reservation_units

        # Generate new QR code for the new owner
        new_qr = generate_ticket_qr(
            reservation_unit_id=transfer['reservation_unit_id'],
            unit_id=transfer['unit_id'],
            user_id=user_id,
            event_slug=transfer['slug_cluster']
        )

        logger.info(f"Transfer accepted: Ticket {transfer['reservation_unit_id']} now owned by {user_id}")

        return TransferResult(
            success=True,
            message="Transfer accepted successfully! Your new ticket is ready.",
            transfer_id=transfer['id'],
            new_qr_code=generate_data_url(new_qr)
        )


async def cancel_transfer(
    user_id: str,
    reservation_unit_id: int
) -> bool:
    """Cancel a pending transfer"""
    async with get_db_connection() as conn:
        # Find pending transfer
        transfer = await conn.fetchrow("""
            SELECT utl.id, utl.from_user_id
            FROM unit_transfer_log utl
            WHERE utl.reservation_unit_id = $1
              AND utl.transfer_reason LIKE 'PENDING|%'
        """, reservation_unit_id)

        if not transfer:
            return False

        if str(transfer['from_user_id']) != user_id:
            raise ValidationError("You can only cancel your own transfers")

        # Update transfer log
        await conn.execute("""
            UPDATE unit_transfer_log
            SET transfer_reason = REPLACE(transfer_reason, 'PENDING|', 'CANCELLED|')
            WHERE id = $1
        """, transfer['id'])

        # Restore ticket status
        await conn.execute("""
            UPDATE reservation_units
            SET status = 'confirmed', updated_at = NOW()
            WHERE id = $1
        """, reservation_unit_id)

        logger.info(f"Transfer cancelled: Ticket {reservation_unit_id}")
        return True


async def get_outgoing_transfers(user_id: str) -> List[TransferSummary]:
    """Get transfers initiated by user"""
    async with get_db_connection(use_transaction=False) as conn:
        rows = await conn.fetch("""
            SELECT utl.id, utl.reservation_unit_id, utl.transfer_date as initiated_at,
                   utl.transfer_reason, c.cluster_name as event_name,
                   u.nomenclature_letter_area, u.nomenclature_number_unit
            FROM unit_transfer_log utl
            JOIN reservation_units ru ON utl.reservation_unit_id = ru.id
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            WHERE utl.from_user_id = $1
            ORDER BY utl.transfer_date DESC
        """, user_id)

        transfers = []
        for row in rows:
            reason = row['transfer_reason'] or ''
            parts = reason.split('|')

            status = parts[0] if parts else 'unknown'
            to_email = parts[2] if len(parts) > 2 else ''

            display_name = f"{row['nomenclature_letter_area'] or ''}-{row['nomenclature_number_unit'] or row['reservation_unit_id']}".strip('-')

            transfers.append(TransferSummary(
                id=row['id'],
                reservation_unit_id=row['reservation_unit_id'],
                to_email=to_email,
                status=status.lower(),
                initiated_at=row['initiated_at'],
                event_name=row['event_name'],
                unit_display_name=display_name
            ))

        return transfers


async def get_incoming_transfers(user_email: str) -> List[PendingTransfer]:
    """Get pending transfers for user"""
    async with get_db_connection(use_transaction=False) as conn:
        rows = await conn.fetch("""
            SELECT utl.id, utl.reservation_unit_id, utl.from_user_id,
                   utl.transfer_date as initiated_at, utl.transfer_reason,
                   c.cluster_name as event_name, c.start_date as event_date,
                   a.area_name, u.nomenclature_letter_area, u.nomenclature_number_unit,
                   p.name as from_user_name, p.email as from_user_email
            FROM unit_transfer_log utl
            JOIN reservation_units ru ON utl.reservation_unit_id = ru.id
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            JOIN profile p ON utl.from_user_id = p.id
            WHERE utl.transfer_reason LIKE $1
            ORDER BY utl.transfer_date DESC
        """, f"PENDING|%|{user_email.lower()}|%")

        transfers = []
        for row in rows:
            reason = row['transfer_reason'] or ''
            parts = reason.split('|')

            if len(parts) < 5:
                continue

            transfer_token = parts[1]
            expires_at = datetime.fromisoformat(parts[3])
            message = parts[4] if len(parts) > 4 else None

            # Skip expired
            if datetime.now() > expires_at:
                continue

            display_name = f"{row['nomenclature_letter_area'] or ''}-{row['nomenclature_number_unit'] or row['reservation_unit_id']}".strip('-')

            transfers.append(PendingTransfer(
                id=row['id'],
                transfer_token=transfer_token,
                from_user_name=row['from_user_name'],
                from_user_email=row['from_user_email'],
                event_name=row['event_name'],
                event_date=row['event_date'],
                area_name=row['area_name'],
                unit_display_name=display_name,
                message=message,
                initiated_at=row['initiated_at'],
                expires_at=expires_at
            ))

        return transfers


async def get_transfer_history(reservation_unit_id: int) -> List[TransferLogEntry]:
    """Get transfer history for a ticket"""
    async with get_db_connection(use_transaction=False) as conn:
        rows = await conn.fetch("""
            SELECT utl.*,
                   pf.name as from_user_name,
                   pt.name as to_user_name
            FROM unit_transfer_log utl
            LEFT JOIN profile pf ON utl.from_user_id = pf.id
            LEFT JOIN profile pt ON utl.to_user_id = pt.id
            WHERE utl.reservation_unit_id = $1
              AND utl.transfer_reason LIKE 'ACCEPTED|%'
            ORDER BY utl.transfer_date ASC
        """, reservation_unit_id)

        entries = []
        for row in rows:
            data = dict(row)
            # Convert UUIDs to strings
            if data.get('from_user_id'):
                data['from_user_id'] = str(data['from_user_id'])
            if data.get('to_user_id'):
                data['to_user_id'] = str(data['to_user_id'])
            entries.append(TransferLogEntry(**data))
        return entries
