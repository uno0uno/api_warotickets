import json
import logging
import uuid
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
            SELECT u.id, u.status, u.area_id, a.cluster_id, a.price, a.service as area_service, c.start_date, c.end_date
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

        # Calculate pricing and store per-unit info
        total = Decimal("0")
        pricing_by_unit = {}
        sale_stages_by_area = {}
        for unit in units_info:
            price_info = await pricing_service.calculate_area_price(
                unit['area_id'],
                quantity=1
            )
            total += price_info['final_price']
            pricing_by_unit[unit['id']] = price_info
            # Cache sale stage per area
            area_id = unit['area_id']
            if area_id not in sale_stages_by_area:
                sale_stages_by_area[area_id] = await pricing_service.get_active_sale_stage(area_id)

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

        # Track reservation creation
        await _track_reservation_status(
            conn, reservation_id, None, 'pending',
            changed_by=user_id, reason='Reservation created'
        )

        # Get promotion ID and data if code or ID provided
        promotion_id = data.promotion_id
        promo_data = None
        
        if promotion_id:
            promo_data = await conn.fetchrow(
                "SELECT promotion_name, promotion_code, pricing_type, pricing_value FROM promotions WHERE id = $1",
                uuid.UUID(promotion_id)
            )
        elif data.promotion_code:
            promo = await conn.fetchrow(
                "SELECT id, promotion_name, promotion_code, pricing_type, pricing_value FROM promotions WHERE promotion_code = $1",
                data.promotion_code.upper().strip()
            )
            if promo:
                promotion_id = str(promo['id'])
                promo_data = promo

        # Create reservation units and reserve the units
        for unit in units_info:
            price_info = pricing_by_unit[unit['id']]
            active_stage = sale_stages_by_area.get(unit['area_id'])
            unit_sale_stage_id = active_stage['id'] if active_stage else None

            # Build pricing snapshot
            # a.service stores the per-unit service fee in COP (monetary amount)
            snapshot = {
                "base_price": float(price_info['base_price']),
                "unit_price": float(price_info['unit_price']),
                "service_fee": float(unit['area_service'] or 0),
                "bundle_size": price_info['bundle_size'],
            }

            # Check if unit is part of the promotion (if one is applied)
            is_promo_unit = False
            if promotion_id and promo_data:
                # Check if this specific unit ID was marked for promotion
                if data.promo_unit_ids and unit['id'] in data.promo_unit_ids:
                    is_promo_unit = True

            if active_stage and not is_promo_unit:
                snapshot["discount_type"] = "sale_stage"
                snapshot["discount_name"] = active_stage['stage_name']
                snapshot["adjustment_type"] = active_stage['price_adjustment_type']
                snapshot["adjustment_value"] = float(active_stage['price_adjustment_value'])
            elif is_promo_unit and promo_data:
                snapshot["discount_type"] = "promotion"
                snapshot["discount_name"] = promo_data['promotion_name']
                snapshot["promotion_code"] = promo_data['promotion_code']
                snapshot["adjustment_type"] = promo_data['pricing_type']
                snapshot["adjustment_value"] = float(promo_data['pricing_value'])

            unit_price_paid = float(price_info['unit_price'])

            ru_row = await conn.fetchrow("""
                INSERT INTO reservation_units (
                    reservation_id, unit_id, status, original_user_id,
                    applied_area_sale_stage_id, applied_promotion_id,
                    unit_price_paid, pricing_snapshot, updated_at
                ) VALUES ($1, $2, 'reserved', $3, $4, $5, $6, $7, NOW())
                RETURNING id
            """, reservation_id, unit['id'], user_id, unit_sale_stage_id, promotion_id,
                 unit_price_paid, json.dumps(snapshot))

            # Track unit reservation
            await _track_reservation_unit_status(
                conn, ru_row['id'], reservation_id, None, 'reserved',
                changed_by=user_id, reason='Unit reserved'
            )

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

        old_status = reservation['status']

        # Get reservation units with their IDs and status
        units = await conn.fetch("""
            SELECT id, unit_id, status FROM reservation_units
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

        # Track reservation status change
        await _track_reservation_status(
            conn, reservation_id, old_status, 'cancelled',
            changed_by=user_id, reason='Cancelled by user'
        )

        # Update reservation units and track each
        for unit in units:
            await conn.execute("""
                UPDATE reservation_units SET status = 'cancelled', updated_at = NOW()
                WHERE id = $1
            """, unit['id'])

            await _track_reservation_unit_status(
                conn, unit['id'], reservation_id, unit['status'], 'cancelled',
                changed_by=user_id, reason='Reservation cancelled'
            )

        logger.info(f"Cancelled reservation {reservation_id}")
        return True


async def confirm_reservation(reservation_id: str) -> bool:
    """
    Confirm reservation after payment (called by payment service).

    This function also recovers expired reservations when payment was successful.
    If a reservation expired while the user was completing payment, we still
    confirm it since the payment went through.

    Also generates QR code data for each ticket.
    """
    async with get_db_connection() as conn:
        # Get current status before update
        reservation = await conn.fetchrow("""
            SELECT status, user_id FROM reservations WHERE id = $1
        """, reservation_id)

        if not reservation:
            logger.warning(f"Reservation {reservation_id} not found for confirmation")
            return False

        old_reservation_status = reservation['status']
        user_id = str(reservation['user_id'])

        # Get reservation units with current status
        units = await conn.fetch("""
            SELECT id, status FROM reservation_units
            WHERE reservation_id = $1 AND status IN ('reserved', 'incomplete')
        """, reservation_id)

        # Update reservation status - also recover expired reservations
        # (payment was successful, so we should honor the reservation)
        await conn.execute("""
            UPDATE reservations SET status = 'active', updated_at = NOW()
            WHERE id = $1 AND status IN ('pending', 'expired')
        """, reservation_id)

        # Track reservation status change
        await _track_reservation_status(
            conn, reservation_id, old_reservation_status, 'active',
            reason='Payment confirmed'
        )

        # Update reservation units and track each
        for unit in units:
            await conn.execute("""
                UPDATE reservation_units SET status = 'confirmed', updated_at = NOW()
                WHERE id = $1
            """, unit['id'])

            await _track_reservation_unit_status(
                conn, unit['id'], reservation_id, unit['status'], 'confirmed',
                reason='Payment confirmed'
            )

        # Mark units as sold
        await conn.execute("""
            UPDATE units u SET status = 'sold', updated_at = NOW()
            FROM reservation_units ru
            WHERE ru.unit_id = u.id AND ru.reservation_id = $1
        """, reservation_id)

        # Generate QR data for each ticket
        await _generate_qr_data_for_reservation(conn, reservation_id)

        logger.info(f"Confirmed reservation {reservation_id}")
        return True


async def _generate_qr_data_for_reservation(conn, reservation_id: str) -> None:
    """
    Generate QR code data for each reservation unit (ticket).

    The QR data includes all information needed to validate the ticket at entry.
    """
    # Get reservation info with user_id
    reservation = await conn.fetchrow("""
        SELECT r.id, r.user_id
        FROM reservations r
        WHERE r.id = $1
    """, reservation_id)

    if not reservation:
        logger.warning(f"Reservation {reservation_id} not found for QR generation")
        return

    user_id = str(reservation['user_id'])

    # Get all units with event and area info
    units = await conn.fetch("""
        SELECT
            ru.id as reservation_unit_id,
            ru.unit_id,
            u.nomenclature_letter_area,
            u.nomenclature_number_unit,
            a.id as area_id,
            a.area_name,
            c.id as cluster_id,
            c.cluster_name,
            c.start_date as event_date
        FROM reservation_units ru
        JOIN units u ON ru.unit_id = u.id
        JOIN areas a ON u.area_id = a.id
        JOIN clusters c ON a.cluster_id = c.id
        WHERE ru.reservation_id = $1
    """, reservation_id)

    generated_at = datetime.now().isoformat()

    for unit in units:
        # Generate unique QR code token
        qr_code = str(uuid.uuid4())

        # Build QR data JSON
        qr_data = {
            "code": qr_code,
            "reservation_id": reservation_id,
            "reservation_unit_id": unit['reservation_unit_id'],
            "user_id": user_id,
            "event": {
                "id": unit['cluster_id'],
                "name": unit['cluster_name'],
                "date": unit['event_date'].isoformat() if unit['event_date'] else None
            },
            "area": {
                "id": unit['area_id'],
                "name": unit['area_name']
            },
            "unit": {
                "id": unit['unit_id'],
                "display_name": f"{unit['nomenclature_letter_area'] or ''}-{unit['nomenclature_number_unit'] or unit['unit_id']}".strip('-')
            },
            "generated_at": generated_at
        }

        # Update reservation unit with QR data
        await conn.execute("""
            UPDATE reservation_units
            SET qr_code = $1, qr_data = $2, updated_at = NOW()
            WHERE id = $3
        """, qr_code, json.dumps(qr_data), unit['reservation_unit_id'])

    logger.info(f"Generated QR data for {len(units)} tickets in reservation {reservation_id}")


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

            # Get reservation units with status
            units = await conn.fetch("""
                SELECT id, unit_id, status FROM reservation_units
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

            # Track reservation expiration
            await _track_reservation_status(
                conn, reservation_id, 'pending', 'expired',
                reason='Reservation timeout - no payment received'
            )

            # Update reservation units and track each
            for unit in units:
                await conn.execute("""
                    UPDATE reservation_units SET status = 'cancelled', updated_at = NOW()
                    WHERE id = $1
                """, unit['id'])

                await _track_reservation_unit_status(
                    conn, unit['id'], reservation_id, unit['status'], 'cancelled',
                    reason='Reservation expired'
                )

            count += 1

        if count > 0:
            logger.info(f"Expired {count} pending reservations")

        return count


async def get_my_tickets(user_id: str) -> List[MyTicket]:
    """Get all confirmed tickets for a user (including transferred tickets)"""
    async with get_db_connection(use_transaction=False) as conn:
        rows = await conn.fetch("""
            SELECT
                ru.id as reservation_unit_id,
                ru.reservation_id,
                ru.unit_id,
                ru.status,
                ru.qr_code,
                ru.qr_data,
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
            WHERE (r.user_id = $1 OR ru.original_user_id = $1)
              AND ru.status IN ('confirmed', 'used')
            ORDER BY c.start_date ASC
        """, user_id)

        tickets = []
        for row in rows:
            ticket_dict = dict(row)
            ticket_dict['unit_display_name'] = f"{row['nomenclature_letter_area'] or ''}-{row['nomenclature_number_unit'] or row['unit_id']}".strip('-')
            ticket_dict['can_transfer'] = row['status'] == 'confirmed'
            ticket_dict['qr_code_url'] = None  # Will be generated on demand
            # Parse qr_data if it's a string
            if ticket_dict.get('qr_data') and isinstance(ticket_dict['qr_data'], str):
                ticket_dict['qr_data'] = json.loads(ticket_dict['qr_data'])
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


# ============================================================================
# STATUS HISTORY TRACKING
# ============================================================================

async def _track_reservation_status(
    conn,
    reservation_id: str,
    old_status: Optional[str],
    new_status: str,
    changed_by: Optional[str] = None,
    reason: Optional[str] = None,
    metadata: Optional[dict] = None
) -> None:
    """Track reservation status change in history table"""
    await conn.execute("""
        INSERT INTO reservation_status_history
        (reservation_id, old_status, new_status, changed_by, reason, metadata)
        VALUES ($1, $2, $3, $4, $5, $6)
    """, reservation_id, old_status, new_status, changed_by, reason,
        json.dumps(metadata) if metadata else None)

    logger.debug(f"Tracked reservation {reservation_id}: {old_status} -> {new_status}")


async def _track_reservation_unit_status(
    conn,
    reservation_unit_id: int,
    reservation_id: str,
    old_status: Optional[str],
    new_status: str,
    changed_by: Optional[str] = None,
    reason: Optional[str] = None,
    metadata: Optional[dict] = None
) -> None:
    """Track reservation unit status change in history table"""
    await conn.execute("""
        INSERT INTO reservation_unit_status_history
        (reservation_unit_id, reservation_id, old_status, new_status, changed_by, reason, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
    """, reservation_unit_id, reservation_id, old_status, new_status, changed_by, reason,
        json.dumps(metadata) if metadata else None)

    logger.debug(f"Tracked unit {reservation_unit_id}: {old_status} -> {new_status}")


async def get_my_invoices(user_id: str) -> list:
    """Get all payment invoices for a buyer, with ticket breakdown per area."""
    async with get_db_connection(use_transaction=False) as conn:
        # Get all payments for the user
        payments = await conn.fetch("""
            SELECT DISTINCT
                p.id as payment_id,
                p.reference,
                p.amount,
                p.currency,
                p.status as payment_status,
                p.payment_method_type,
                p.payment_date,
                p.finalized_at,
                p.gateway_name,
                c.cluster_name as event_name,
                c.slug_cluster as event_slug,
                c.start_date as event_date,
                r.id as reservation_id
            FROM payments p
            JOIN reservations r ON p.reservation_id = r.id
            JOIN reservation_units ru ON r.id = ru.reservation_id
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            WHERE r.user_id = $1
            ORDER BY p.payment_date DESC
        """, uuid.UUID(user_id))

        invoices = []
        for pay in payments:
            # Get ticket breakdown by area for this reservation
            ticket_details = await conn.fetch("""
                SELECT
                    a.area_name,
                    a.price as base_price,
                    a.service as area_service_fee,
                    COUNT(ru.id) as quantity,
                    ru.unit_price_paid,
                    ru.pricing_snapshot
                FROM reservation_units ru
                JOIN units u ON ru.unit_id = u.id
                JOIN areas a ON u.area_id = a.id
                WHERE ru.reservation_id = $1
                GROUP BY a.area_name, a.price, a.service, ru.unit_price_paid, ru.pricing_snapshot
            """, pay['reservation_id'])

            tickets = []
            ticket_count = 0
            for td in ticket_details:
                qty = td['quantity']
                ticket_count += qty

                snapshot = td['pricing_snapshot'] or {}
                if isinstance(snapshot, str):
                    snapshot = json.loads(snapshot)

                base_price = float(td['base_price'] or 0)

                # Use snapshot price if available, fallback to base price
                if td['unit_price_paid'] is not None:
                    unit_price = float(td['unit_price_paid'])
                else:
                    unit_price = base_price

                # Service fee from snapshot, fallback to percentage-based calculation
                if snapshot.get('service_fee') is not None:
                    service_fee = float(snapshot['service_fee'])
                else:
                    service_fee = float(td['area_service_fee'] or 0)

                # Discount info
                discount_type = snapshot.get('discount_type')
                discount_name = snapshot.get('discount_name')
                has_discount = discount_type is not None

                # Build pricing label
                if discount_name:
                    pricing_label = f"{td['area_name']} ({discount_name})"
                else:
                    pricing_label = td['area_name']

                # Build discount detail string
                discount_detail = None
                if has_discount:
                    adj_type = snapshot.get('adjustment_type')
                    adj_value = snapshot.get('adjustment_value')
                    if discount_type == 'promotion' and snapshot.get('promotion_code'):
                        discount_detail = f"Promo: {snapshot['promotion_code']}"
                    elif adj_type == 'percentage' and adj_value is not None:
                        discount_detail = f"{adj_value:+g}%"
                    elif adj_type in ('fixed', 'fixed_discount') and adj_value is not None:
                        discount_detail = f"${adj_value:+,.0f}"
                    elif adj_type in ('fixed_price',) and adj_value is not None:
                        discount_detail = f"Precio fijo: ${adj_value:,.0f}"

                tickets.append({
                    "area_name": td['area_name'],
                    "unit_price": unit_price,
                    "base_price": base_price,
                    "service_fee": service_fee,
                    "quantity": qty,
                    "subtotal": unit_price * qty,
                    "service_total": service_fee * qty,
                    "pricing_label": pricing_label,
                    "has_discount": has_discount,
                    "discount_type": discount_type,
                    "discount_name": discount_name,
                    "discount_detail": discount_detail,
                })

            invoices.append({
                "payment_id": pay['payment_id'],
                "reference": pay['reference'] or '',
                "amount": float(pay['amount'] or 0),
                "currency": pay['currency'] or 'COP',
                "payment_status": pay['payment_status'] or 'pending',
                "payment_method_type": pay['payment_method_type'],
                "payment_date": pay['payment_date'].isoformat() if pay['payment_date'] else None,
                "finalized_at": pay['finalized_at'].isoformat() if pay['finalized_at'] else None,
                "gateway_name": pay['gateway_name'],
                "event_name": pay['event_name'] or '',
                "event_slug": pay['event_slug'] or '',
                "event_date": pay['event_date'].isoformat() if pay['event_date'] else None,
                "reservation_id": str(pay['reservation_id']),
                "ticket_count": ticket_count,
                "tickets": tickets
            })

        return invoices


async def get_my_invoice_detail(user_id: str, payment_id: int) -> dict | None:
    """Get full detail of a single payment invoice for a buyer."""
    async with get_db_connection(use_transaction=False) as conn:
        pay = await conn.fetchrow("""
            SELECT DISTINCT
                p.id as payment_id,
                p.reference,
                p.amount,
                p.currency,
                p.status as payment_status,
                p.payment_method_type,
                p.payment_method_data,
                p.payment_date,
                p.finalized_at,
                p.gateway_name,
                p.customer_email,
                p.status_message,
                p.environment,
                p.payment_gateway_transaction_id,
                c.cluster_name as event_name,
                c.slug_cluster as event_slug,
                c.start_date as event_date,
                r.id as reservation_id,
                r.reservation_date
            FROM payments p
            JOIN reservations r ON p.reservation_id = r.id
            JOIN reservation_units ru ON r.id = ru.reservation_id
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            WHERE p.id = $1 AND r.user_id = $2
            LIMIT 1
        """, payment_id, uuid.UUID(user_id))

        if not pay:
            return None

        # Get ticket breakdown by area
        ticket_details = await conn.fetch("""
            SELECT
                a.area_name,
                a.price as base_price,
                a.service as area_service_fee,
                COUNT(ru.id) as quantity,
                ru.unit_price_paid,
                ru.pricing_snapshot
            FROM reservation_units ru
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            WHERE ru.reservation_id = $1
            GROUP BY a.area_name, a.price, a.service, ru.unit_price_paid, ru.pricing_snapshot
        """, pay['reservation_id'])

        tickets = []
        ticket_count = 0
        for td in ticket_details:
            qty = td['quantity']
            ticket_count += qty

            snapshot = td['pricing_snapshot'] or {}
            if isinstance(snapshot, str):
                snapshot = json.loads(snapshot)

            base_price = float(td['base_price'] or 0)

            if td['unit_price_paid'] is not None:
                unit_price = float(td['unit_price_paid'])
            else:
                unit_price = base_price

            if snapshot.get('service_fee') is not None:
                service_fee = float(snapshot['service_fee'])
            else:
                service_fee = float(td['area_service_fee'] or 0)

            discount_type = snapshot.get('discount_type')
            discount_name = snapshot.get('discount_name')
            has_discount = discount_type is not None

            if discount_name:
                pricing_label = f"{td['area_name']} ({discount_name})"
            else:
                pricing_label = td['area_name']

            discount_detail = None
            if has_discount:
                adj_type = snapshot.get('adjustment_type')
                adj_value = snapshot.get('adjustment_value')
                if discount_type == 'promotion' and snapshot.get('promotion_code'):
                    discount_detail = f"Promo: {snapshot['promotion_code']}"
                elif adj_type == 'percentage' and adj_value is not None:
                    discount_detail = f"{adj_value:+g}%"
                elif adj_type in ('fixed', 'fixed_discount') and adj_value is not None:
                    discount_detail = f"${adj_value:+,.0f}"
                elif adj_type in ('fixed_price',) and adj_value is not None:
                    discount_detail = f"Precio fijo: ${adj_value:,.0f}"

            tickets.append({
                "area_name": td['area_name'],
                "unit_price": unit_price,
                "base_price": base_price,
                "service_fee": service_fee,
                "quantity": qty,
                "subtotal": unit_price * qty,
                "service_total": service_fee * qty,
                "pricing_label": pricing_label,
                "has_discount": has_discount,
                "discount_type": discount_type,
                "discount_name": discount_name,
                "discount_detail": discount_detail,
            })

        # Get individual units
        units = await conn.fetch("""
            SELECT
                ru.id as reservation_unit_id,
                ru.status,
                ru.qr_code,
                ru.unit_price_paid,
                ru.pricing_snapshot,
                u.nomenclature_letter_area,
                u.nomenclature_number_area,
                u.nomenclature_number_unit,
                a.area_name,
                a.price as base_price,
                a.service as area_service_fee
            FROM reservation_units ru
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            WHERE ru.reservation_id = $1
            ORDER BY a.area_name, u.nomenclature_number_unit
        """, pay['reservation_id'])

        unit_list = []
        for u in units:
            letter = u['nomenclature_letter_area'] or ''
            num_area = u['nomenclature_number_area'] or ''
            num_unit = u['nomenclature_number_unit'] or ''
            display = f"{letter}{'-' + str(num_area) if num_area else ''}-{num_unit}" if letter else str(num_unit)

            snapshot = u['pricing_snapshot'] or {}
            if isinstance(snapshot, str):
                snapshot = json.loads(snapshot)

            base_price = float(u['base_price'] or 0)

            if u['unit_price_paid'] is not None:
                unit_price = float(u['unit_price_paid'])
            else:
                unit_price = base_price

            if snapshot.get('service_fee') is not None:
                service_fee = float(snapshot['service_fee'])
            else:
                service_fee = float(u['area_service_fee'] or 0)

            discount_type = snapshot.get('discount_type')
            discount_name = snapshot.get('discount_name')
            has_discount = discount_type is not None

            if discount_name:
                pricing_label = f"{u['area_name']} ({discount_name})"
            else:
                pricing_label = u['area_name']

            unit_list.append({
                "reservation_unit_id": u['reservation_unit_id'],
                "area_name": u['area_name'],
                "display_name": display,
                "status": u['status'],
                "qr_code": u['qr_code'],
                "unit_price": unit_price,
                "base_price": base_price,
                "service_fee": service_fee,
                "pricing_label": pricing_label,
                "has_discount": has_discount,
                "discount_type": discount_type,
                "discount_name": discount_name,
            })

        # Parse payment method data
        method_data = pay['payment_method_data'] or {}
        extra = method_data.get('extra', {}) if isinstance(method_data, dict) else {}

        return {
            "payment_id": pay['payment_id'],
            "reference": pay['reference'] or '',
            "amount": float(pay['amount'] or 0),
            "currency": pay['currency'] or 'COP',
            "payment_status": pay['payment_status'] or 'pending',
            "payment_method_type": pay['payment_method_type'],
            "payment_date": pay['payment_date'].isoformat() if pay['payment_date'] else None,
            "finalized_at": pay['finalized_at'].isoformat() if pay['finalized_at'] else None,
            "gateway_name": pay['gateway_name'],
            "customer_email": pay['customer_email'],
            "status_message": pay['status_message'],
            "transaction_id": pay['payment_gateway_transaction_id'],
            "card_brand": extra.get('brand'),
            "card_last_four": extra.get('last_four'),
            "card_name": extra.get('name'),
            "installments": method_data.get('installments') if isinstance(method_data, dict) else None,
            "event_name": pay['event_name'] or '',
            "event_slug": pay['event_slug'] or '',
            "event_date": pay['event_date'].isoformat() if pay['event_date'] else None,
            "reservation_id": str(pay['reservation_id']),
            "reservation_date": pay['reservation_date'].isoformat() if pay['reservation_date'] else None,
            "ticket_count": ticket_count,
            "tickets": tickets,
            "units": unit_list
        }
