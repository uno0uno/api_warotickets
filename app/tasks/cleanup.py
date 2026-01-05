import asyncio
import logging
from datetime import datetime, timedelta
from app.database import get_db_connection

logger = logging.getLogger(__name__)

# Reservation timeout in minutes
RESERVATION_TIMEOUT_MINUTES = 15


async def cleanup_expired_reservations():
    """
    Clean up expired reservations.

    - Releases units back to available status
    - Marks reservations as expired
    - Runs every 5 minutes
    """
    logger.info("Starting cleanup of expired reservations...")

    async with get_db_connection() as conn:
        timeout = datetime.now() - timedelta(minutes=RESERVATION_TIMEOUT_MINUTES)

        # Find expired pending reservations
        expired_reservations = await conn.fetch("""
            SELECT r.id, r.user_id, COUNT(ru.id) as unit_count
            FROM reservations r
            JOIN reservation_units ru ON ru.reservation_id = r.id
            WHERE r.status = 'pending'
              AND r.created_at < $1
            GROUP BY r.id
        """, timeout)

        if not expired_reservations:
            logger.info("No expired reservations found")
            return 0

        expired_count = 0

        for reservation in expired_reservations:
            try:
                # Release units
                await conn.execute("""
                    UPDATE reservation_units
                    SET status = 'cancelled', updated_at = NOW()
                    WHERE reservation_id = $1 AND status = 'reserved'
                """, reservation['id'])

                # Mark reservation as expired
                await conn.execute("""
                    UPDATE reservations
                    SET status = 'expired', updated_at = NOW()
                    WHERE id = $1
                """, reservation['id'])

                expired_count += 1
                logger.info(
                    f"Expired reservation {reservation['id']}: "
                    f"released {reservation['unit_count']} units"
                )

            except Exception as e:
                logger.error(f"Error expiring reservation {reservation['id']}: {e}")

        logger.info(f"Cleanup complete: {expired_count} reservations expired")
        return expired_count


async def cleanup_expired_transfers():
    """
    Clean up expired transfers.

    - Marks pending transfers as expired
    - Restores ticket status to confirmed
    - Runs every hour
    """
    logger.info("Starting cleanup of expired transfers...")

    async with get_db_connection() as conn:
        # Find expired pending transfers
        # Transfer reason format: PENDING|token|email|expires_at|message
        expired = await conn.fetch("""
            SELECT utl.id, utl.reservation_unit_id, utl.transfer_reason
            FROM unit_transfer_log utl
            WHERE utl.transfer_reason LIKE 'PENDING|%'
        """)

        expired_count = 0

        for transfer in expired:
            try:
                parts = transfer['transfer_reason'].split('|')
                if len(parts) >= 4:
                    expires_at = datetime.fromisoformat(parts[3])
                    if datetime.now() > expires_at:
                        # Mark as expired
                        await conn.execute("""
                            UPDATE unit_transfer_log
                            SET transfer_reason = REPLACE(transfer_reason, 'PENDING|', 'EXPIRED|')
                            WHERE id = $1
                        """, transfer['id'])

                        # Restore ticket status
                        await conn.execute("""
                            UPDATE reservation_units
                            SET status = 'confirmed', updated_at = NOW()
                            WHERE id = $1 AND status = 'transferred'
                        """, transfer['reservation_unit_id'])

                        expired_count += 1
                        logger.info(f"Expired transfer {transfer['id']}")

            except Exception as e:
                logger.error(f"Error expiring transfer {transfer['id']}: {e}")

        logger.info(f"Transfer cleanup complete: {expired_count} transfers expired")
        return expired_count


async def cleanup_expired_sessions():
    """
    Clean up expired sessions from database.
    Runs daily.
    """
    logger.info("Starting cleanup of expired sessions...")

    async with get_db_connection() as conn:
        result = await conn.execute("""
            DELETE FROM sessions WHERE expires_at < NOW()
        """)

        # Parse result like "DELETE 42"
        count = int(result.split()[1]) if result else 0
        logger.info(f"Session cleanup complete: {count} sessions deleted")
        return count


async def run_cleanup_loop():
    """
    Main cleanup loop that runs continuously.
    """
    logger.info("Starting cleanup background tasks...")

    reservation_interval = 5 * 60  # 5 minutes
    transfer_interval = 60 * 60    # 1 hour
    session_interval = 24 * 60 * 60  # 24 hours

    last_reservation_cleanup = 0
    last_transfer_cleanup = 0
    last_session_cleanup = 0

    while True:
        try:
            current_time = asyncio.get_event_loop().time()

            # Reservation cleanup every 5 minutes
            if current_time - last_reservation_cleanup >= reservation_interval:
                await cleanup_expired_reservations()
                last_reservation_cleanup = current_time

            # Transfer cleanup every hour
            if current_time - last_transfer_cleanup >= transfer_interval:
                await cleanup_expired_transfers()
                last_transfer_cleanup = current_time

            # Session cleanup daily
            if current_time - last_session_cleanup >= session_interval:
                await cleanup_expired_sessions()
                last_session_cleanup = current_time

            # Sleep for 1 minute before next check
            await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"Error in cleanup loop: {e}")
            await asyncio.sleep(60)
