import logging
import uuid
from typing import Optional
from datetime import datetime
import boto3
from botocore.exceptions import ClientError
from app.config import settings
from app.database import get_db_connection

logger = logging.getLogger(__name__)


def get_r2_client():
    """Get Cloudflare R2 client (S3-compatible)"""
    return boto3.client(
        's3',
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name='auto'
    )


async def upload_image(
    file_content: bytes,
    filename: str,
    content_type: str,
    folder: str = "images"
) -> Optional[dict]:
    """
    Upload image to Cloudflare R2.

    Returns dict with url and image_id, or None if failed.
    """
    try:
        client = get_r2_client()

        # Generate unique filename
        ext = filename.split('.')[-1] if '.' in filename else 'jpg'
        unique_name = f"{folder}/{uuid.uuid4()}.{ext}"

        # Upload to R2
        client.put_object(
            Bucket=settings.r2_bucket,
            Key=unique_name,
            Body=file_content,
            ContentType=content_type
        )

        # Generate public URL
        # R2 URLs are typically: https://{account}.r2.cloudflarestorage.com/{bucket}/{key}
        # Or with custom domain: https://assets.warotickets.com/{key}
        public_url = f"{settings.r2_endpoint}/{settings.r2_bucket}/{unique_name}"

        # Store in database
        async with get_db_connection() as conn:
            row = await conn.fetchrow("""
                INSERT INTO images (url, alt_text, created_at)
                VALUES ($1, $2, NOW())
                RETURNING id, url
            """, public_url, filename)

            logger.info(f"Uploaded image: {unique_name}")

            return {
                "image_id": row['id'],
                "url": row['url'],
                "key": unique_name
            }

    except ClientError as e:
        logger.error(f"R2 upload error: {e}")
        return None
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return None


async def upload_to_r2(
    file_content: bytes,
    filename: str,
    content_type: str,
    folder: str = "images"
) -> Optional[dict]:
    """
    Upload file to R2 only (no database save).

    Returns dict with url and key, or None if failed.
    """
    try:
        client = get_r2_client()

        # Generate unique filename
        ext = filename.split('.')[-1] if '.' in filename else 'jpg'
        unique_key = f"{folder}/{uuid.uuid4()}.{ext}"

        # Upload to R2
        client.put_object(
            Bucket=settings.r2_bucket,
            Key=unique_key,
            Body=file_content,
            ContentType=content_type
        )

        # Generate public URL (using r2.dev public URL)
        public_url = f"{settings.r2_public_url}/{unique_key}"

        logger.info(f"Uploaded to R2: {unique_key}")

        return {
            "url": public_url,
            "key": unique_key
        }

    except ClientError as e:
        logger.error(f"R2 upload error: {e}")
        return None
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return None


async def delete_image(image_id: int) -> bool:
    """
    Delete image from R2 and database.
    """
    try:
        async with get_db_connection() as conn:
            # Get image info
            image = await conn.fetchrow(
                "SELECT url FROM images WHERE id = $1",
                image_id
            )

            if not image:
                return False

            # Extract key from URL
            url = image['url']
            # Parse key from URL (after bucket name)
            key = url.split(f"{settings.r2_bucket}/")[-1] if settings.r2_bucket in url else None

            # Delete from R2
            if key:
                try:
                    client = get_r2_client()
                    client.delete_object(Bucket=settings.r2_bucket, Key=key)
                except Exception as e:
                    logger.warning(f"Failed to delete from R2: {e}")

            # Delete from database
            await conn.execute("DELETE FROM images WHERE id = $1", image_id)

            logger.info(f"Deleted image: {image_id}")
            return True

    except Exception as e:
        logger.error(f"Delete image error: {e}")
        return False


async def get_presigned_upload_url(
    filename: str,
    content_type: str,
    folder: str = "images",
    expires_in: int = 3600
) -> Optional[dict]:
    """
    Get presigned URL for direct upload from client.

    Client can upload directly to R2 without going through our server.
    """
    try:
        client = get_r2_client()

        # Generate unique filename
        ext = filename.split('.')[-1] if '.' in filename else 'jpg'
        unique_key = f"{folder}/{uuid.uuid4()}.{ext}"

        # Generate presigned URL
        presigned_url = client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': settings.r2_bucket,
                'Key': unique_key,
                'ContentType': content_type
            },
            ExpiresIn=expires_in
        )

        # Final URL where the file will be accessible (public r2.dev URL)
        final_url = f"{settings.r2_public_url}/{unique_key}"

        return {
            "upload_url": presigned_url,
            "final_url": final_url,
            "key": unique_key,
            "expires_in": expires_in
        }

    except Exception as e:
        logger.error(f"Presigned URL error: {e}")
        return None
