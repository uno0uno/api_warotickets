import json
import logging
from typing import Optional, List
from datetime import datetime, timedelta
from decimal import Decimal
from app.database import get_db_connection
from app.models.reservation import (
    Reservation, ReservationCreate, ReservationUpdate,
    ReservationSummary, ReservationUnit, CreateReservationResponse,
    ReservationTimeout, MyTicket
)
from app.services import units_service, pricing_service
from app.core.exceptions import ValidationError, ReservationError

logger = logging.getLogger(__name__)

# Reservation expires after 15 minutes without payment
RESERVATION_TIMEOUT_MINUTES = 15


async def get_reservations(
    user_id: str,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[ReservationSummary]:
    """Get reservations for a user"""
    async with get_db_connection(use_transaction=False) as conn:
        query = """
            SELECT r.id, r.user_id, r.start_date, r.status,
                   r.reservation_date,
                   c.cluster_name,
                   (SELECT COUNT(*) FROM reservation_units ru WHERE ru.reservation_id = r.id) as total_units,
                   COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.reservation_id = r.id AND p.status = 'approved'), 0) as total,
                   'COP' as currency
            FROM reservations r
            LEFT JOIN reservation_units ru ON ru.reservation_id = r.id
            LEFT JOIN units u ON ru.unit_id = u.id
            LEFT JOIN areas a ON u.area_id = a.id
            LEFT JOIN clusters c ON a.cluster_id = c.id
            WHERE r.user_id = $1
        """
        params = [user_id]
        param_idx = 2

        if status:
            query += f" AND r.status = ${param_idx}"
            params.append(status)
            param_idx += 1

        query += f" GROUP BY r.id, c.cluster_name ORDER BY r.reservation_date DESC LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        params.extend([limit, offset])

        rows = await conn.fetch(query, *params)
        return [ReservationSummary(**dict(row)) for row in rows]


async def get_reservation_by_id(reservation_id: str, user_id: str) -> Optional[Reservation]:
    """Get reservation by ID with all details"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow("""
            SELECT r.*
            FROM reservations r
            WHERE r.id = $1 AND r.user_id = $2
        """, reservation_id, user_id)

        if not row:
            return None

        reservation_dict = dict(row)
        # Convert UUIDs to strings
        for uuid_field in ['id', 'user_id']:
            if reservation_dict.get(uuid_field) is not None:
                reservation_dict[uuid_field] = str(reservation_dict[uuid_field])
        # Parse extra_attributes JSON string to dict
        if reservation_dict.get('extra_attributes') and isinstance(reservation_dict['extra_attributes'], str):
            reservation_dict['extra_attributes'] = json.loads(reservation_dict['extra_attributes'])

        # Get cluster info
        cluster_info = await conn.fetchrow("""
            SELECT DISTINCT c.id, c.cluster_name, c.slug_cluster
            FROM reservation_units ru
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            WHERE ru.reservation_id = $1
            LIMIT 1
        """, reservation_id)

        if cluster_info:
            reservation_dict['cluster_id'] = cluster_info['id']
            reservation_dict['cluster_name'] = cluster_info['cluster_name']
            reservation_dict['cluster_slug'] = cluster_info['slug_cluster']

        # Get units
        units = await conn.fetch("""
            SELECT ru.*, u.nomenclature_letter_area, u.nomenclature_number_unit,
                   a.area_name, a.id as area_id, a.price as base_price
            FROM reservation_units ru
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            WHERE ru.reservation_id = $1
        """, reservation_id)

        reservation_dict['units'] = []
        subtotal = Decimal("0")

        for unit in units:
            unit_dict = dict(unit)
            # Convert UUIDs to strings
            for uuid_field in ['reservation_id', 'original_user_id', 'applied_promotion_id', 'applied_area_sale_stage_id']:
                if unit_dict.get(uuid_field) is not None:
                    unit_dict[uuid_field] = str(unit_dict[uuid_field])
            unit_dict['unit_display_name'] = f"{unit['nomenclature_letter_area'] or ''}-{unit['nomenclature_number_unit'] or unit['id']}".strip('-')
            unit_dict['final_price'] = unit['base_price']  # TODO: Apply discounts
            subtotal += Decimal(str(unit['base_price']))
            reservation_dict['units'].append(ReservationUnit(**unit_dict))

        reservation_dict['total_units'] = len(units)
        reservation_dict['subtotal'] = subtotal
        reservation_dict['discount'] = Decimal("0")
        reservation_dict['service_fee'] = Decimal("0")
        reservation_dict['total'] = subtotal

        return Reservation(**reservation_dict)


async def get_or_create_user(conn, email: str) -> str:
    """Get existing user by email or create a new profile"""
    email = email.lower().strip()

    # Check if user exists
    existing = await conn.fetchrow(
        "SELECT id FROM profile WHERE email = $1",
        email
    )

    if existing:
        return str(existing['id'])

    # Create new profile with generic defaults
    new_user = await conn.fetchrow("""
        INSERT INTO profile (
            email, name, phone_number, nationality_id,
            created_at, updated_at
        ) VALUES ($1, $2, $3, $4, NOW(), NOW())
        RETURNING id
    """,
        email,
        email.split('@')[0],  # Use email prefix as name
        '0000000000',         # Generic phone
        1                     # Default nationality (Colombia)
    )

    logger.info(f"Created new profile for {email}: {new_user['id']}")
    return str(new_user['id'])


async def create_reservation(user_id: Optional[str], data: ReservationCreate) -> CreateReservationResponse:
    """Create a new reservation (public endpoint)"""
    async with get_db_connection() as conn:
        # Get or create user from email (ignores user_id parameter)
        user_id = await get_or_create_user(conn, data.email)

        # Verify units are available and belong to same event
        units_info = await conn.fetch("""
            SELECT u.id, u.status, u.area_id, a.cluster_id, a.price, c.start_date, c.end_date
            FROM units u
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            WHERE u.id = ANY($1)
        """, data.unit_ids)

        if len(units_info) != len(data.unit_ids):
            raise ValidationError("Some units not found")

        # Check all units are available
        unavailable = [u for u in units_info if u['status'] != 'available']
        if unavailable:
            raise ReservationError(
                f"{len(unavailable)} units are not available",
                {"unavailable_unit_ids": [u['id'] for u in unavailable]}
            )

        # Check all units belong to same event
        cluster_ids = set(u['cluster_id'] for u in units_info)
        if len(cluster_ids) > 1:
            raise ValidationError("All units must belong to the same event")

        cluster_id = list(cluster_ids)[0]
        if cluster_id != data.cluster_id:
            raise ValidationError("Units do not belong to the specified event")

        # Get event dates
        event_start = units_info[0]['start_date']
        event_end = units_info[0]['end_date']

        # Calculate pricing
        total = Decimal("0")
        for unit in units_info:
            price_info = await pricing_service.calculate_price(
                unit['area_id'],
                quantity=1,
                promotion_code=data.promotion_code
            )
            total += price_info.final_price

        # Create reservation
        reservation_row = await conn.fetchrow("""
            INSERT INTO reservations (
                user_id, reservation_date, start_date, end_date,
                status, extra_attributes, updated_at
            ) VALUES (
                $1, NOW(), $2, $3, 'pending', $4, NOW()
            )
            RETURNING *
        """, user_id, event_start, event_end, json.dumps(data.model_dump()))

        reservation_id = str(reservation_row['id'])

        # Get active sale stage for discount tracking
        sale_stage = await pricing_service.get_active_sale_stage(units_info[0]['area_id'])
        sale_stage_id = sale_stage['id'] if sale_stage else None

        # Get promotion ID if code provided
        promotion_id = None
        if data.promotion_code:
            promo = await conn.fetchrow(
                "SELECT id FROM area_promotions WHERE promotion_code = $1",
                data.promotion_code.upper().strip()
            )
            promotion_id = str(promo['id']) if promo else None

        # Create reservation units and reserve the units
        for unit in units_info:
            await conn.execute("""
                INSERT INTO reservation_units (
                    reservation_id, unit_id, status, original_user_id,
                    applied_area_sale_stage_id, applied_promotion_id, updated_at
                ) VALUES ($1, $2, 'reserved', $3, $4, $5, NOW())
            """, reservation_id, unit['id'], user_id, sale_stage_id, promotion_id)

            # Update unit status
            await conn.execute("""
                UPDATE units SET status = 'reserved', updated_at = NOW()
                WHERE id = $1
            """, unit['id'])

        logger.info(f"Created reservation {reservation_id} for user {user_id} with {len(data.unit_ids)} units")

    # Get full reservation (outside transaction so it can see committed data)
    reservation = await get_reservation_by_id(reservation_id, user_id)

    # Calculate expiration
    expires_at = datetime.now() + timedelta(minutes=RESERVATION_TIMEOUT_MINUTES)

    return CreateReservationResponse(
        reservation=reservation,
        expires_at=expires_at,
        payment_url=None  # Will be set when payment is initiated
    )


async def cancel_reservation(reservation_id: str, user_id: str) -> bool:
    """Cancel a reservation and release units"""
    async with get_db_connection() as conn:
        # Verify ownership and status
        reservation = await conn.fetchrow("""
            SELECT id, status FROM reservations
            WHERE id = $1 AND user_id = $2
        """, reservation_id, user_id)

        if not reservation:
            return False

        if reservation['status'] not in ['pending', 'active']:
            raise ValidationError(f"Cannot cancel reservation with status: {reservation['status']}")

        # Get unit IDs
        units = await conn.fetch("""
            SELECT unit_id FROM reservation_units
            WHERE reservation_id = $1
        """, reservation_id)

        unit_ids = [u['unit_id'] for u in units]

        # Release units
        await conn.execute("""
            UPDATE units SET status = 'available', updated_at = NOW()
            WHERE id = ANY($1) AND status = 'reserved'
        """, unit_ids)

        # Update reservation status
        await conn.execute("""
            UPDATE reservations SET status = 'cancelled', updated_at = NOW()
            WHERE id = $1
        """, reservation_id)

        # Update reservation units
        await conn.execute("""
            UPDATE reservation_units SET status = 'cancelled', updated_at = NOW()
            WHERE reservation_id = $1
        """, reservation_id)

        logger.info(f"Cancelled reservation {reservation_id}")
        return True


async def confirm_reservation(reservation_id: str) -> bool:
    """
    Confirm reservation after payment (called by payment service).

    This function also recovers expired reservations when payment was successful.
    If a reservation expired while the user was completing payment, we still
    confirm it since the payment went through.
    """
    async with get_db_connection() as conn:
        # Update reservation status - also recover expired reservations
        # (payment was successful, so we should honor the reservation)
        result = await conn.execute("""
            UPDATE reservations SET status = 'active', updated_at = NOW()
            WHERE id = $1 AND status IN ('pending', 'expired')
        """, reservation_id)

        # Update reservation units - handle both 'reserved' and 'incomplete' states
        await conn.execute("""
            UPDATE reservation_units SET status = 'confirmed', updated_at = NOW()
            WHERE reservation_id = $1 AND status IN ('reserved', 'incomplete')
        """, reservation_id)

        # Mark units as sold
        await conn.execute("""
            UPDATE units u SET status = 'sold', updated_at = NOW()
            FROM reservation_units ru
            WHERE ru.unit_id = u.id AND ru.reservation_id = $1
        """, reservation_id)

        logger.info(f"Confirmed reservation {reservation_id}")
        return True


async def expire_pending_reservations() -> int:
    """Expire pending reservations that have timed out (scheduled job)"""
    async with get_db_connection() as conn:
        cutoff_time = datetime.now() - timedelta(minutes=RESERVATION_TIMEOUT_MINUTES)

        # Find expired reservations
        expired = await conn.fetch("""
            SELECT id FROM reservations
            WHERE status = 'pending' AND reservation_date < $1
        """, cutoff_time)

        count = 0
        for reservation in expired:
            reservation_id = str(reservation['id'])

            # Get unit IDs
            units = await conn.fetch("""
                SELECT unit_id FROM reservation_units
                WHERE reservation_id = $1
            """, reservation_id)

            unit_ids = [u['unit_id'] for u in units]

            # Release units
            await conn.execute("""
                UPDATE units SET status = 'available', updated_at = NOW()
                WHERE id = ANY($1) AND status = 'reserved'
            """, unit_ids)

            # Update reservation
            await conn.execute("""
                UPDATE reservations SET status = 'expired', updated_at = NOW()
                WHERE id = $1
            """, reservation_id)

            # Update reservation units
            await conn.execute("""
                UPDATE reservation_units SET status = 'cancelled', updated_at = NOW()
                WHERE reservation_id = $1
            """, reservation_id)

            count += 1

        if count > 0:
            logger.info(f"Expired {count} pending reservations")

        return count


async def get_my_tickets(user_id: str) -> List[MyTicket]:
    """Get all confirmed tickets for a user"""
    async with get_db_connection(use_transaction=False) as conn:
        rows = await conn.fetch("""
            SELECT
                ru.id as reservation_unit_id,
                ru.reservation_id,
                ru.unit_id,
                ru.status,
                u.nomenclature_letter_area,
                u.nomenclature_number_unit,
                a.area_name,
                c.cluster_name as event_name,
                c.slug_cluster as event_slug,
                c.start_date as event_date
            FROM reservation_units ru
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            JOIN reservations r ON ru.reservation_id = r.id
            WHERE r.user_id = $1 AND ru.status IN ('confirmed', 'used')
            ORDER BY c.start_date ASC
        """, user_id)

        tickets = []
        for row in rows:
            ticket_dict = dict(row)
            ticket_dict['unit_display_name'] = f"{row['nomenclature_letter_area'] or ''}-{row['nomenclature_number_unit'] or row['unit_id']}".strip('-')
            ticket_dict['can_transfer'] = row['status'] == 'confirmed'
            ticket_dict['qr_code_url'] = None  # Will be generated on demand
            tickets.append(MyTicket(**ticket_dict))

        return tickets


async def get_reservation_timeout(reservation_id: str, user_id: str) -> Optional[ReservationTimeout]:
    """Get timeout info for a pending reservation"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow("""
            SELECT id, reservation_date, status
            FROM reservations
            WHERE id = $1 AND user_id = $2
        """, reservation_id, user_id)

        if not row or row['status'] != 'pending':
            return None

        created_at = row['reservation_date']
        expires_at = created_at + timedelta(minutes=RESERVATION_TIMEOUT_MINUTES)
        now = datetime.now(created_at.tzinfo)
        seconds_remaining = max(0, int((expires_at - now).total_seconds()))

        return ReservationTimeout(
            reservation_id=reservation_id,
            created_at=created_at,
            expires_at=expires_at,
            seconds_remaining=seconds_remaining,
            is_expired=seconds_remaining == 0
        )
