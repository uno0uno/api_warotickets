import logging
from typing import Optional, List
from app.database import get_db_connection
from app.models.event_image import (
    EventImageCreate,
    EventImageUpdate,
    EventImageSummary
)

logger = logging.getLogger(__name__)


async def create_event_image(
    cluster_id: int,
    image_data: EventImageCreate,
    profile_id: str
) -> Optional[dict]:
    """
    Create an event image record.
    For banner, flyer, cover: replaces existing image of same type.
    For gallery: allows multiple images.
    """
    try:
        async with get_db_connection() as conn:
            # Verify event belongs to profile
            event = await conn.fetchrow(
                "SELECT id FROM clusters WHERE id = $1 AND profile_id = $2",
                cluster_id, profile_id
            )
            if not event:
                logger.warning(f"Event {cluster_id} not found for profile {profile_id}")
                return None

            # For non-gallery types, delete existing image of same type first
            if image_data.image_type != 'gallery':
                await conn.execute("""
                    DELETE FROM event_images
                    WHERE cluster_id = $1 AND image_type = $2
                """, cluster_id, image_data.image_type)

            # Insert new image
            row = await conn.fetchrow("""
                INSERT INTO event_images (
                    cluster_id, image_type, image_url, alt_text,
                    width, height, file_size, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
                RETURNING id, cluster_id, image_type, image_url, alt_text,
                          width, height, file_size, created_at, updated_at
            """,
                cluster_id,
                image_data.image_type,
                image_data.image_url,
                image_data.alt_text,
                image_data.width,
                image_data.height,
                image_data.file_size
            )

            logger.info(f"Created {image_data.image_type} image for event {cluster_id}")

            return dict(row)

    except Exception as e:
        logger.error(f"Error creating event image: {e}")
        return None


async def get_event_images(
    cluster_id: int,
    image_type: Optional[str] = None
) -> List[dict]:
    """
    Get all images for an event, optionally filtered by type.
    """
    try:
        async with get_db_connection() as conn:
            if image_type:
                rows = await conn.fetch("""
                    SELECT id, cluster_id, image_type, image_url, alt_text,
                           width, height, file_size, created_at, updated_at
                    FROM event_images
                    WHERE cluster_id = $1 AND image_type = $2
                    ORDER BY created_at DESC
                """, cluster_id, image_type)
            else:
                rows = await conn.fetch("""
                    SELECT id, cluster_id, image_type, image_url, alt_text,
                           width, height, file_size, created_at, updated_at
                    FROM event_images
                    WHERE cluster_id = $1
                    ORDER BY image_type, created_at DESC
                """, cluster_id)

            return [dict(row) for row in rows]

    except Exception as e:
        logger.error(f"Error getting event images: {e}")
        return []


async def get_event_image_by_type(
    cluster_id: int,
    image_type: str
) -> Optional[dict]:
    """
    Get a specific image by type (for banner, flyer, cover).
    """
    try:
        async with get_db_connection() as conn:
            row = await conn.fetchrow("""
                SELECT id, cluster_id, image_type, image_url, alt_text,
                       width, height, file_size, created_at, updated_at
                FROM event_images
                WHERE cluster_id = $1 AND image_type = $2
                LIMIT 1
            """, cluster_id, image_type)

            return dict(row) if row else None

    except Exception as e:
        logger.error(f"Error getting event image by type: {e}")
        return None


async def update_event_image(
    image_id: int,
    cluster_id: int,
    image_data: EventImageUpdate,
    profile_id: str
) -> Optional[dict]:
    """
    Update an event image record.
    """
    try:
        async with get_db_connection() as conn:
            # Verify ownership
            existing = await conn.fetchrow("""
                SELECT ei.id FROM event_images ei
                JOIN clusters c ON c.id = ei.cluster_id
                WHERE ei.id = $1 AND ei.cluster_id = $2 AND c.profile_id = $3
            """, image_id, cluster_id, profile_id)

            if not existing:
                logger.warning(f"Image {image_id} not found or not owned")
                return None

            # Build update query dynamically
            updates = []
            values = []
            param_count = 1

            if image_data.image_url is not None:
                updates.append(f"image_url = ${param_count}")
                values.append(image_data.image_url)
                param_count += 1

            if image_data.alt_text is not None:
                updates.append(f"alt_text = ${param_count}")
                values.append(image_data.alt_text)
                param_count += 1

            if image_data.width is not None:
                updates.append(f"width = ${param_count}")
                values.append(image_data.width)
                param_count += 1

            if image_data.height is not None:
                updates.append(f"height = ${param_count}")
                values.append(image_data.height)
                param_count += 1

            if image_data.file_size is not None:
                updates.append(f"file_size = ${param_count}")
                values.append(image_data.file_size)
                param_count += 1

            if not updates:
                # Nothing to update
                return await get_event_image_by_id(image_id)

            updates.append("updated_at = NOW()")
            values.append(image_id)

            query = f"""
                UPDATE event_images
                SET {', '.join(updates)}
                WHERE id = ${param_count}
                RETURNING id, cluster_id, image_type, image_url, alt_text,
                          width, height, file_size, created_at, updated_at
            """

            row = await conn.fetchrow(query, *values)

            logger.info(f"Updated image {image_id}")
            return dict(row) if row else None

    except Exception as e:
        logger.error(f"Error updating event image: {e}")
        return None


async def delete_event_image(
    image_id: int,
    cluster_id: int,
    profile_id: str
) -> bool:
    """
    Delete an event image record.
    """
    try:
        async with get_db_connection() as conn:
            # Verify ownership and delete
            result = await conn.execute("""
                DELETE FROM event_images
                WHERE id = $1
                  AND cluster_id = $2
                  AND cluster_id IN (
                      SELECT id FROM clusters WHERE profile_id = $3
                  )
            """, image_id, cluster_id, profile_id)

            deleted = result.split()[-1]  # Gets the count from "DELETE X"
            if int(deleted) > 0:
                logger.info(f"Deleted image {image_id}")
                return True

            logger.warning(f"Image {image_id} not found or not owned")
            return False

    except Exception as e:
        logger.error(f"Error deleting event image: {e}")
        return False


async def get_event_image_by_id(image_id: int) -> Optional[dict]:
    """
    Get an event image by its ID.
    """
    try:
        async with get_db_connection() as conn:
            row = await conn.fetchrow("""
                SELECT id, cluster_id, image_type, image_url, alt_text,
                       width, height, file_size, created_at, updated_at
                FROM event_images
                WHERE id = $1
            """, image_id)

            return dict(row) if row else None

    except Exception as e:
        logger.error(f"Error getting event image by id: {e}")
        return None


async def get_event_images_urls(cluster_id: int) -> dict:
    """
    Get all image URLs for an event as a flat dictionary.
    Useful for including in event responses.
    """
    try:
        async with get_db_connection() as conn:
            rows = await conn.fetch("""
                SELECT image_type, image_url
                FROM event_images
                WHERE cluster_id = $1 AND image_type IN ('banner', 'flyer', 'cover')
            """, cluster_id)

            result = {
                'banner_image_url': None,
                'flyer_image_url': None,
                'cover_image_url': None
            }

            for row in rows:
                key = f"{row['image_type']}_image_url"
                result[key] = row['image_url']

            return result

    except Exception as e:
        logger.error(f"Error getting event images urls: {e}")
        return {
            'banner_image_url': None,
            'flyer_image_url': None,
            'cover_image_url': None
        }
