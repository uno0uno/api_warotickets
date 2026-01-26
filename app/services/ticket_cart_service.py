import logging
from typing import Optional, List
from decimal import Decimal
from datetime import datetime, timezone
from app.database import get_db_connection
from app.models.ticket_cart import (
    TicketCartItemCreate, TicketCartCreate, TicketCartItemUpdate,
    TicketCartResponse, TicketCartItemResponse, CartSummary, CheckoutResponse,
    ConvertedPromotion
)
from app.services import reservations_service, payments_service
from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

MAX_TICKETS_PER_CART = 20


async def get_tenant_id(conn, cluster_id: int) -> str:
    """Get tenant_id from cluster"""
    row = await conn.fetchrow(
        "SELECT tenant_id FROM clusters WHERE id = $1",
        cluster_id
    )
    if not row:
        raise ValidationError("Evento no encontrado")
    return str(row['tenant_id'])


async def get_or_create_cart(
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    cluster_id: Optional[int] = None
) -> Optional[dict]:
    """Get existing active cart or create new one"""
    if not session_id and not user_id:
        return None

    async with get_db_connection() as conn:
        # Try to find existing active cart
        query = """
            SELECT tc.*, c.cluster_name, c.slug_cluster
            FROM ticket_carts tc
            JOIN clusters c ON tc.cluster_id = c.id
            WHERE tc.status = 'active'
        """
        params = []
        param_idx = 1

        if user_id:
            query += f" AND tc.user_id = ${param_idx}"
            params.append(user_id)
            param_idx += 1
        elif session_id:
            query += f" AND tc.session_id = ${param_idx}"
            params.append(session_id)
            param_idx += 1

        if cluster_id:
            query += f" AND tc.cluster_id = ${param_idx}"
            params.append(cluster_id)

        query += " ORDER BY tc.updated_at DESC LIMIT 1"

        cart = await conn.fetchrow(query, *params)

        if cart:
            return dict(cart)

        # Create new cart if cluster_id provided
        if cluster_id:
            tenant_id = await get_tenant_id(conn, cluster_id)

            row = await conn.fetchrow("""
                INSERT INTO ticket_carts (tenant_id, session_id, user_id, cluster_id, status)
                VALUES ($1, $2, $3, $4, 'active')
                RETURNING *
            """, tenant_id, session_id, user_id, cluster_id)

            cart_dict = dict(row)

            # Get cluster info
            cluster = await conn.fetchrow(
                "SELECT cluster_name, slug_cluster FROM clusters WHERE id = $1",
                cluster_id
            )
            cart_dict['cluster_name'] = cluster['cluster_name']
            cart_dict['slug_cluster'] = cluster['slug_cluster']

            return cart_dict

        return None


async def get_active_stage_for_area(conn, area_id: int) -> Optional[dict]:
    """Get active sale stage with quantity for an area"""
    stage = await conn.fetchrow("""
        SELECT ss.id, ss.stage_name, ss.price_adjustment_type, ss.price_adjustment_value,
               ssa.quantity as bundle_size,
               (ss.quantity_available - ss.quantity_sold) as quantity_remaining
        FROM sale_stages ss
        JOIN sale_stage_areas ssa ON ss.id = ssa.sale_stage_id
        WHERE ssa.area_id = $1
          AND ss.is_active = true
          AND ss.start_time <= NOW()
          AND (ss.end_time IS NULL OR ss.end_time > NOW())
          AND (ss.quantity_available - ss.quantity_sold) > 0
        ORDER BY ss.priority_order ASC
        LIMIT 1
    """, area_id)

    return dict(stage) if stage else None


def calculate_item_prices(
    base_price: Decimal,
    quantity: int,
    stage: Optional[dict]
) -> dict:
    """Calculate prices for a cart item based on stage and quantity"""
    bundle_size = 1
    unit_price = base_price
    bundle_price = None
    stage_id = None
    stage_name = None
    stage_status = "none"

    if stage:
        bundle_size = stage.get('bundle_size') or 1
        stage_id = str(stage['id'])
        stage_name = stage['stage_name']
        stage_status = "active"

        adj_type = stage['price_adjustment_type']
        adj_value = Decimal(str(stage['price_adjustment_value']))

        if adj_type == 'percentage':
            # Percentage discount applies to base price
            unit_price = base_price * (1 + adj_value / 100)
        elif adj_type == 'fixed':
            # Fixed discount applies to bundle total, then divide
            bundle_total = base_price * bundle_size
            discounted_total = bundle_total + adj_value
            unit_price = discounted_total / bundle_size
        elif adj_type == 'fixed_price':
            # Fixed price is total bundle price
            unit_price = adj_value / bundle_size

        unit_price = max(Decimal('0'), unit_price)

        if bundle_size > 1:
            bundle_price = unit_price * bundle_size

    tickets_count = quantity * bundle_size
    original_price = base_price
    subtotal = unit_price * tickets_count

    return {
        'unit_price': unit_price,
        'bundle_price': bundle_price,
        'original_price': original_price,
        'subtotal': subtotal,
        'tickets_count': tickets_count,
        'bundle_size': bundle_size,
        'stage_id': stage_id,
        'stage_name': stage_name,
        'stage_status': stage_status
    }


async def validate_promotion(conn, promotion_id: str, cluster_id: int) -> dict:
    """Validate if a promotion is still active and available"""
    promo = await conn.fetchrow("""
        SELECT p.*, c.cluster_name
        FROM promotions p
        JOIN clusters c ON p.cluster_id = c.id
        WHERE p.id = $1 AND p.cluster_id = $2
    """, promotion_id, cluster_id)

    if not promo:
        return {"is_valid": False, "reason": "Promoción no encontrada", "promo": None}

    if not promo['is_active']:
        return {"is_valid": False, "reason": "Promoción desactivada", "promo": promo}

    now = datetime.now(timezone.utc)

    if promo['start_time']:
        start = promo['start_time']
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if now < start:
            return {"is_valid": False, "reason": "Promoción aún no vigente", "promo": promo}

    if promo['end_time']:
        end = promo['end_time']
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if now > end:
            return {"is_valid": False, "reason": "Promoción finalizada", "promo": promo}

    if promo['quantity_available']:
        remaining = promo['quantity_available'] - promo['uses_count']
        if remaining <= 0:
            return {"is_valid": False, "reason": "Promoción agotada", "promo": promo}

    return {"is_valid": True, "reason": None, "promo": promo}


async def convert_expired_promo_to_individual(conn, cart_id: str, promotion_id: str, promo_name: str, reason: str) -> ConvertedPromotion:
    """Convert items from an expired promotion to individual items"""
    # Get items from this promotion
    promo_items = await conn.fetch("""
        SELECT area_id, quantity FROM ticket_cart_items
        WHERE cart_id = $1 AND promotion_id = $2
    """, cart_id, promotion_id)

    items_count = len(promo_items)

    # Delete promotion items
    await conn.execute("""
        DELETE FROM ticket_cart_items
        WHERE cart_id = $1 AND promotion_id = $2
    """, cart_id, promotion_id)

    # Re-add as individual items (without promotion_id)
    for item in promo_items:
        # Check if individual item already exists for this area
        existing = await conn.fetchval("""
            SELECT quantity FROM ticket_cart_items
            WHERE cart_id = $1 AND area_id = $2 AND promotion_id IS NULL
        """, cart_id, item['area_id'])

        if existing:
            # Add quantity to existing
            await conn.execute("""
                UPDATE ticket_cart_items
                SET quantity = quantity + $3, updated_at = NOW()
                WHERE cart_id = $1 AND area_id = $2 AND promotion_id IS NULL
            """, cart_id, item['area_id'], item['quantity'])
        else:
            # Create new individual item
            await conn.execute("""
                INSERT INTO ticket_cart_items (cart_id, area_id, quantity, promotion_id)
                VALUES ($1, $2, $3, NULL)
            """, cart_id, item['area_id'], item['quantity'])

    return ConvertedPromotion(
        promotion_name=promo_name,
        reason=reason,
        items_converted=items_count
    )


async def add_item(
    cart_id: str,
    area_id: int,
    quantity: int = 1,
    replace: bool = False
) -> TicketCartResponse:
    """Add item to cart or update if exists - Only stores selection, prices calculated on read

    Args:
        cart_id: Cart UUID
        area_id: Area ID to add
        quantity: Quantity to add (bundles/tickets)
        replace: If True, replace existing quantity. If False, add to existing.
    """
    async with get_db_connection() as conn:
        # Verify cart exists
        cart = await conn.fetchrow(
            "SELECT * FROM ticket_carts WHERE id = $1 AND status = 'active'",
            cart_id
        )
        if not cart:
            raise ValidationError("Carrito no encontrado")

        # Get area info
        area = await conn.fetchrow("""
            SELECT a.id, a.area_name, a.price, a.cluster_id,
                   (SELECT COUNT(*) FROM units u WHERE u.area_id = a.id AND u.status = 'available') as available
            FROM areas a
            WHERE a.id = $1
        """, area_id)

        if not area:
            raise ValidationError("Area no encontrada")

        if area['cluster_id'] != cart['cluster_id']:
            raise ValidationError("El area no pertenece al evento del carrito")

        # Get current active stage to calculate tickets for validation
        stage = await get_active_stage_for_area(conn, area_id)
        bundle_size = stage.get('bundle_size', 1) if stage else 1

        # Check existing item quantity (only for normal items, not promotions)
        existing_item = await conn.fetchrow("""
            SELECT quantity FROM ticket_cart_items
            WHERE cart_id = $1 AND area_id = $2 AND promotion_id IS NULL
        """, cart_id, area_id)

        # Calculate final quantity (add or replace)
        if replace or not existing_item:
            final_quantity = quantity
        else:
            final_quantity = existing_item['quantity'] + quantity

        # Cap at max 10 bundles per area
        final_quantity = min(final_quantity, 10)

        # Calculate tickets for validation
        tickets_count = final_quantity * bundle_size

        # Check total tickets in cart won't exceed limit
        current_tickets_result = await conn.fetch("""
            SELECT tci.area_id, tci.quantity, tci.promotion_id
            FROM ticket_cart_items tci
            WHERE tci.cart_id = $1 AND NOT (tci.area_id = $2 AND tci.promotion_id IS NULL)
        """, cart_id, area_id)

        total_other_tickets = 0
        for item in current_tickets_result:
            if item['promotion_id']:
                # Promotion items: quantity IS the ticket count (no bundle)
                total_other_tickets += item['quantity']
            else:
                # Individual items: multiply by current stage's bundle_size
                item_stage = await get_active_stage_for_area(conn, item['area_id'])
                item_bundle = item_stage.get('bundle_size', 1) if item_stage else 1
                total_other_tickets += item['quantity'] * item_bundle

        if total_other_tickets + tickets_count > MAX_TICKETS_PER_CART:
            raise ValidationError(f"Maximo {MAX_TICKETS_PER_CART} boletas por carrito")

        # Check availability
        if tickets_count > area['available']:
            raise ValidationError(f"Solo hay {area['available']} boletas disponibles")

        # Upsert: only store area_id, quantity (NO PRICES)
        if existing_item:
            await conn.execute("""
                UPDATE ticket_cart_items SET
                    quantity = $3,
                    updated_at = NOW()
                WHERE cart_id = $1 AND area_id = $2 AND promotion_id IS NULL
            """, cart_id, area_id, final_quantity)
        else:
            await conn.execute("""
                INSERT INTO ticket_cart_items (cart_id, area_id, quantity, promotion_id)
                VALUES ($1, $2, $3, NULL)
            """, cart_id, area_id, final_quantity)

        # Update cart timestamp
        await conn.execute(
            "UPDATE ticket_carts SET updated_at = NOW() WHERE id = $1",
            cart_id
        )

    return await get_cart(cart_id)


async def update_item(cart_id: str, area_id: int, quantity: int) -> TicketCartResponse:
    """Update item quantity in cart (replaces existing quantity)"""
    if quantity <= 0:
        return await remove_item(cart_id, area_id)

    return await add_item(cart_id, area_id, quantity, replace=True)


async def remove_item(cart_id: str, area_id: int) -> TicketCartResponse:
    """Remove normal item from cart (not promotion items)"""
    async with get_db_connection() as conn:
        await conn.execute("""
            DELETE FROM ticket_cart_items
            WHERE cart_id = $1 AND area_id = $2 AND promotion_id IS NULL
        """, cart_id, area_id)

        await conn.execute(
            "UPDATE ticket_carts SET updated_at = NOW() WHERE id = $1",
            cart_id
        )

    return await get_cart(cart_id)


async def add_promotion_package(
    cart_id: str,
    promotion_id: str,
    quantity: int = 1
) -> TicketCartResponse:
    """Add promotional package(s) to cart - Only stores selection, prices calculated on read

    Args:
        cart_id: Cart UUID
        promotion_id: Promotion UUID
        quantity: Number of packages to add (default 1)
    """
    if quantity < 1:
        quantity = 1
    if quantity > 5:
        raise ValidationError("Maximo 5 paquetes promocionales")

    async with get_db_connection() as conn:
        # Verify cart
        cart = await conn.fetchrow(
            "SELECT * FROM ticket_carts WHERE id = $1 AND status = 'active'",
            cart_id
        )
        if not cart:
            raise ValidationError("Carrito no encontrado")

        # Validate promotion
        promo_validation = await validate_promotion(conn, promotion_id, cart['cluster_id'])
        if not promo_validation['is_valid']:
            raise ValidationError(promo_validation['reason'])

        promo = promo_validation['promo']

        # Check quantity available
        if promo['quantity_available']:
            remaining = promo['quantity_available'] - promo['uses_count']
            if remaining < quantity:
                raise ValidationError(f"Solo hay {remaining} paquetes disponibles de esta promocion")

        # Get promotion items
        promo_items = await conn.fetch("""
            SELECT pi.area_id, pi.quantity, a.area_name, a.price,
                   (SELECT COUNT(*) FROM units u WHERE u.area_id = a.id AND u.status = 'available') as available
            FROM promotion_items pi
            JOIN areas a ON pi.area_id = a.id
            WHERE pi.promotion_id = $1
        """, promotion_id)

        if not promo_items:
            raise ValidationError("Esta promocion no tiene items configurados")

        # Calculate total tickets and validate availability
        promo_tickets = 0
        for item in promo_items:
            item_qty = item['quantity'] * quantity
            promo_tickets += item_qty

            if item_qty > item['available']:
                raise ValidationError(f"No hay suficientes boletas disponibles en {item['area_name']}")

        # Check total tickets in cart
        current_tickets_result = await conn.fetch("""
            SELECT tci.area_id, tci.quantity, tci.promotion_id
            FROM ticket_cart_items tci
            WHERE tci.cart_id = $1 AND (tci.promotion_id IS NULL OR tci.promotion_id != $2)
        """, cart_id, promotion_id)

        total_other_tickets = 0
        for item in current_tickets_result:
            if item['promotion_id']:
                # Promotion items: quantity IS the ticket count (no bundle)
                total_other_tickets += item['quantity']
            else:
                # Individual items: multiply by current stage's bundle_size
                item_stage = await get_active_stage_for_area(conn, item['area_id'])
                item_bundle = item_stage.get('bundle_size', 1) if item_stage else 1
                total_other_tickets += item['quantity'] * item_bundle

        if total_other_tickets + promo_tickets > MAX_TICKETS_PER_CART:
            raise ValidationError(f"Este pedido excede el maximo de {MAX_TICKETS_PER_CART} boletas")

        # Remove existing items from THIS promotion only (if re-adding)
        await conn.execute(
            "DELETE FROM ticket_cart_items WHERE cart_id = $1 AND promotion_id = $2",
            cart_id, promotion_id
        )

        # Add promotion items - Only store area_id, quantity, promotion_id (NO PRICES)
        for item in promo_items:
            item_qty = item['quantity'] * quantity
            await conn.execute("""
                INSERT INTO ticket_cart_items (cart_id, area_id, quantity, promotion_id)
                VALUES ($1, $2, $3, $4)
            """, cart_id, item['area_id'], item_qty, promotion_id)

        # Update cart timestamp
        await conn.execute(
            "UPDATE ticket_carts SET updated_at = NOW() WHERE id = $1",
            cart_id
        )

    return await get_cart(cart_id)


async def get_cart(cart_id: str) -> TicketCartResponse:
    """Get full cart with items - Prices calculated in real-time"""
    async with get_db_connection() as conn:
        cart = await conn.fetchrow("""
            SELECT tc.*, c.cluster_name, c.slug_cluster
            FROM ticket_carts tc
            JOIN clusters c ON tc.cluster_id = c.id
            WHERE tc.id = $1
        """, cart_id)

        if not cart:
            raise ValidationError("Carrito no encontrado")

        # Get items (only stored fields: area_id, quantity, promotion_id) + service fee
        items_rows = await conn.fetch("""
            SELECT tci.id, tci.area_id, tci.quantity, tci.promotion_id,
                   a.area_name, a.price as base_price,
                   COALESCE(a.service, 0) as service_fee
            FROM ticket_cart_items tci
            JOIN areas a ON tci.area_id = a.id
            WHERE tci.cart_id = $1
            ORDER BY tci.promotion_id NULLS LAST, a.area_name
        """, cart_id)

        items = []
        subtotal = Decimal('0')
        total_tickets = 0
        original_total = Decimal('0')
        total_service_fee = Decimal('0')
        converted_promotions = []

        # Group items by promotion_id to detect expired promotions
        promo_items_map = {}
        individual_items = []

        for row in items_rows:
            if row['promotion_id']:
                promo_id = str(row['promotion_id'])
                if promo_id not in promo_items_map:
                    promo_items_map[promo_id] = []
                promo_items_map[promo_id].append(row)
            else:
                individual_items.append(row)

        # Process promotion items - validate each promotion
        for promo_id, promo_items in promo_items_map.items():
            promo_validation = await validate_promotion(conn, promo_id, cart['cluster_id'])

            if not promo_validation['is_valid']:
                # Promotion expired - convert to individual items
                promo = promo_validation['promo']
                promo_name = promo['promotion_name'] if promo else "Promoción"
                converted = await convert_expired_promo_to_individual(
                    conn, cart_id, promo_id, promo_name, promo_validation['reason']
                )
                converted_promotions.append(converted)
                # The items are now individual - they'll be picked up below
            else:
                # Promotion still valid - calculate prices
                promo = promo_validation['promo']

                # Get promotion pricing config (how many tickets per area in ONE combo)
                promo_items_config = await conn.fetch("""
                    SELECT pi.area_id, pi.quantity
                    FROM promotion_items pi
                    WHERE pi.promotion_id = $1
                """, promo_id)

                # Build map of area_id -> tickets per package
                area_qty_per_package = {pi['area_id']: pi['quantity'] for pi in promo_items_config}

                # Calculate how many packages based on total tickets
                total_promo_tickets = sum(item['quantity'] for item in promo_items)
                tickets_per_package_total = sum(pi['quantity'] for pi in promo_items_config)
                package_count = total_promo_tickets // tickets_per_package_total if tickets_per_package_total > 0 else 1

                # Promo total price
                promo_total = Decimal(str(promo['pricing_value'])) * package_count
                price_per_ticket = promo_total / total_promo_tickets if total_promo_tickets > 0 else Decimal('0')

                for row in promo_items:
                    base_price = Decimal(str(row['base_price']))
                    item_tickets = row['quantity']
                    item_subtotal = price_per_ticket * item_tickets
                    item_original = base_price * item_tickets
                    qty_per_pkg = area_qty_per_package.get(row['area_id'], 1)

                    # Service fee per ticket (from area.service)
                    service_fee_per_ticket = Decimal(str(row.get('service_fee', 0) or 0))
                    item_service_fee = service_fee_per_ticket * item_tickets

                    item = TicketCartItemResponse(
                        id=str(row['id']),
                        area_id=row['area_id'],
                        area_name=row['area_name'],
                        quantity=package_count,  # Number of combos
                        tickets_count=item_tickets,
                        unit_price=price_per_ticket,
                        bundle_price=None,
                        original_price=base_price,
                        subtotal=item_subtotal,
                        bundle_size=1,
                        service_fee_per_ticket=service_fee_per_ticket,
                        service_fee_total=item_service_fee,
                        stage_name=None,
                        stage_id=None,
                        stage_status="none",
                        promotion_id=promo_id,
                        promotion_name=promo['promotion_name'],
                        tickets_per_package=qty_per_pkg  # Tickets of this area per combo
                    )
                    items.append(item)
                    subtotal += item_subtotal
                    total_tickets += item_tickets
                    original_total += item_original
                    total_service_fee += item_service_fee

        # Re-fetch individual items (may have new ones from converted promotions)
        if converted_promotions:
            individual_items = await conn.fetch("""
                SELECT tci.id, tci.area_id, tci.quantity, tci.promotion_id,
                       a.area_name, a.price as base_price,
                       COALESCE(a.service, 0) as service_fee
                FROM ticket_cart_items tci
                JOIN areas a ON tci.area_id = a.id
                WHERE tci.cart_id = $1 AND tci.promotion_id IS NULL
                ORDER BY a.area_name
            """, cart_id)

        # Process individual items - calculate prices based on current stage
        for row in individual_items:
            base_price = Decimal(str(row['base_price']))
            quantity = row['quantity']

            # Get current active stage for this area
            stage = await get_active_stage_for_area(conn, row['area_id'])

            # Calculate prices based on current state
            prices = calculate_item_prices(base_price, quantity, stage)

            # Service fee per ticket (from area.service)
            service_fee_per_ticket = Decimal(str(row.get('service_fee', 0) or 0))
            item_service_fee = service_fee_per_ticket * prices['tickets_count']

            item = TicketCartItemResponse(
                id=str(row['id']),
                area_id=row['area_id'],
                area_name=row['area_name'],
                quantity=quantity,
                tickets_count=prices['tickets_count'],
                unit_price=prices['unit_price'],
                bundle_price=prices['bundle_price'],
                original_price=prices['original_price'],
                subtotal=prices['subtotal'],
                bundle_size=prices['bundle_size'],
                service_fee_per_ticket=service_fee_per_ticket,
                service_fee_total=item_service_fee,
                stage_name=prices['stage_name'],
                stage_id=prices['stage_id'],
                stage_status=prices['stage_status'],
                promotion_id=None,
                promotion_name=None
            )
            items.append(item)
            subtotal += prices['subtotal']
            total_tickets += prices['tickets_count']
            original_total += prices['original_price'] * prices['tickets_count']
            total_service_fee += item_service_fee

        discount = original_total - subtotal
        # Total includes subtotal (product prices) + service fees
        total = subtotal + total_service_fee

        return TicketCartResponse(
            id=str(cart['id']),
            cluster_id=cart['cluster_id'],
            cluster_name=cart['cluster_name'],
            cluster_slug=cart['slug_cluster'],
            status=cart['status'],
            items=items,
            subtotal=subtotal,
            discount=max(Decimal('0'), discount),
            service_fee=total_service_fee,
            total=max(Decimal('0'), total),
            tickets_count=total_tickets,
            expires_at=cart['expires_at'],
            created_at=cart['created_at'],
            updated_at=cart['updated_at'],
            converted_promotions=converted_promotions
        )


async def get_cart_summary(
    session_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> CartSummary:
    """Get simple cart summary for header display - Calculates in real-time"""
    cart = await get_or_create_cart(session_id, user_id)

    if not cart:
        return CartSummary()

    # Get full cart to have accurate calculations
    try:
        full_cart = await get_cart(str(cart['id']))
        return CartSummary(
            cart_id=str(cart['id']),
            items_count=len(full_cart.items),
            tickets_count=full_cart.tickets_count,
            total=full_cart.total
        )
    except Exception:
        return CartSummary(cart_id=str(cart['id']))


async def remove_promotion_from_cart(cart_id: str, promotion_id: str) -> TicketCartResponse:
    """Remove all items of a specific promotion from cart"""
    async with get_db_connection() as conn:
        await conn.execute(
            "DELETE FROM ticket_cart_items WHERE cart_id = $1 AND promotion_id = $2",
            cart_id, promotion_id
        )
        await conn.execute(
            "UPDATE ticket_carts SET updated_at = NOW() WHERE id = $1",
            cart_id
        )
    return await get_cart(cart_id)


async def clear_cart(cart_id: str) -> bool:
    """Clear all items from cart"""
    async with get_db_connection() as conn:
        await conn.execute(
            "DELETE FROM ticket_cart_items WHERE cart_id = $1",
            cart_id
        )
        await conn.execute(
            "UPDATE ticket_carts SET updated_at = NOW() WHERE id = $1",
            cart_id
        )
    return True


async def checkout(
    cart_id: str,
    customer_email: str,
    customer_name: Optional[str] = None,
    customer_phone: Optional[str] = None,
    return_url: Optional[str] = None
) -> CheckoutResponse:
    """Convert cart to reservation and create payment - Uses cart's calculated total"""
    # First, get the full cart with calculated prices (respects promotions and stages)
    full_cart = await get_cart(cart_id)
    cart_total = full_cart.total  # This is the correct total with all discounts

    async with get_db_connection() as conn:
        # Get cart
        cart = await conn.fetchrow("""
            SELECT * FROM ticket_carts WHERE id = $1 AND status = 'active'
        """, cart_id)

        if not cart:
            raise ValidationError("Carrito no encontrado o ya procesado")

        # Get cart items
        items = await conn.fetch("""
            SELECT tci.area_id, tci.quantity, tci.promotion_id
            FROM ticket_cart_items tci
            WHERE tci.cart_id = $1
        """, cart_id)

        if not items:
            raise ValidationError("El carrito esta vacio")

        # Group items by area and calculate total tickets needed per area
        area_tickets: dict[int, int] = {}
        for item in items:
            area_id = item['area_id']
            # For promotion items, quantity IS tickets_count (no bundle)
            if item['promotion_id']:
                tickets_count = item['quantity']
            else:
                # For individual items, calculate based on current stage
                stage = await get_active_stage_for_area(conn, area_id)
                bundle_size = stage.get('bundle_size', 1) if stage else 1
                tickets_count = item['quantity'] * bundle_size

            area_tickets[area_id] = area_tickets.get(area_id, 0) + tickets_count

        # Select units for each area (no duplicates)
        unit_ids = []
        for area_id, tickets_count in area_tickets.items():
            available_units = await conn.fetch("""
                SELECT id FROM units
                WHERE area_id = $1 AND status = 'available'
                ORDER BY nomenclature_number_unit
                LIMIT $2
            """, area_id, tickets_count)

            if len(available_units) < tickets_count:
                raise ValidationError(
                    f"No hay suficientes boletas disponibles para el area seleccionada"
                )

            unit_ids.extend([u['id'] for u in available_units])

        cluster_id = cart['cluster_id']

    # Create reservation using existing service
    from app.models.reservation import ReservationCreate

    reservation_data = ReservationCreate(
        cluster_id=cluster_id,
        unit_ids=unit_ids,
        email=customer_email
    )

    reservation_response = await reservations_service.create_reservation(
        user_id=None,
        data=reservation_data
    )

    # Create payment intent with cart's calculated total (respects discounts)
    from app.models.payment import PaymentCreate

    payment_data = PaymentCreate(
        reservation_id=reservation_response.reservation.id,
        gateway="wompi",
        customer_email=customer_email,
        customer_name=customer_name,
        customer_phone=customer_phone,
        return_url=return_url,
        amount=cart_total  # Pass the cart total with all discounts applied
    )

    payment_response = await payments_service.create_payment_intent(payment_data)

    # Mark cart as converted ONLY after successful reservation and payment creation
    async with get_db_connection() as conn:
        await conn.execute("""
            UPDATE ticket_carts SET status = 'converted', updated_at = NOW()
            WHERE id = $1
        """, cart_id)

    return CheckoutResponse(
        reservation_id=reservation_response.reservation.id,
        payment_id=str(payment_response.payment_id),
        checkout_url=payment_response.checkout_url,
        amount=Decimal(str(payment_response.amount)),
        currency=payment_response.currency,
        expires_at=reservation_response.expires_at
    )
