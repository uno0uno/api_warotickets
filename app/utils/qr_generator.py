import qrcode
from qrcode.image.pil import PilImage
from io import BytesIO
import base64
import hashlib
import hmac
from typing import Optional
from datetime import datetime
from app.config import settings

# Secret for QR code signatures
QR_SECRET = settings.jwt_secret


def generate_ticket_qr_data(
    reservation_unit_id: int,
    unit_id: int,
    user_id: str,
    event_slug: str
) -> str:
    """
    Generate the data string to encode in QR.
    Includes a signature to prevent tampering.
    """
    # Create payload
    timestamp = int(datetime.now().timestamp())
    payload = f"{reservation_unit_id}|{unit_id}|{user_id}|{event_slug}|{timestamp}"

    # Create signature
    signature = hmac.new(
        QR_SECRET.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()[:16]

    # Final QR data
    qr_data = f"WT:{payload}|{signature}"

    return qr_data


def verify_qr_signature(qr_data: str) -> Optional[dict]:
    """
    Verify QR code signature and extract data.
    Returns None if invalid.
    """
    if not qr_data.startswith("WT:"):
        return None

    try:
        data = qr_data[3:]  # Remove "WT:" prefix
        parts = data.rsplit("|", 1)

        if len(parts) != 2:
            return None

        payload, provided_signature = parts

        # Verify signature
        expected_signature = hmac.new(
            QR_SECRET.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()[:16]

        if not hmac.compare_digest(expected_signature, provided_signature):
            return None

        # Parse payload
        payload_parts = payload.split("|")
        if len(payload_parts) != 5:
            return None

        return {
            "reservation_unit_id": int(payload_parts[0]),
            "unit_id": int(payload_parts[1]),
            "user_id": payload_parts[2],
            "event_slug": payload_parts[3],
            "timestamp": int(payload_parts[4]),
            "is_valid": True
        }

    except Exception:
        return None


def generate_qr_image(data: str, size: int = 10, border: int = 2) -> bytes:
    """
    Generate QR code image as PNG bytes.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    # Convert to bytes
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return buffer.getvalue()


def generate_qr_base64(data: str, size: int = 10) -> str:
    """
    Generate QR code as base64 encoded PNG string.
    Useful for embedding in HTML/JSON.
    """
    img_bytes = generate_qr_image(data, size)
    return base64.b64encode(img_bytes).decode('utf-8')


def generate_ticket_qr(
    reservation_unit_id: int,
    unit_id: int,
    user_id: str,
    event_slug: str,
    as_base64: bool = True
) -> str:
    """
    Generate complete ticket QR code.

    Args:
        reservation_unit_id: ID of the reservation_unit
        unit_id: ID of the unit/ticket
        user_id: ID of the ticket owner
        event_slug: Slug of the event
        as_base64: If True, returns base64 string; if False, returns raw bytes

    Returns:
        Base64 encoded PNG image or raw bytes
    """
    qr_data = generate_ticket_qr_data(
        reservation_unit_id, unit_id, user_id, event_slug
    )

    if as_base64:
        return generate_qr_base64(qr_data)
    else:
        return generate_qr_image(qr_data)


def generate_data_url(base64_data: str) -> str:
    """
    Convert base64 to data URL for direct embedding in HTML.
    """
    return f"data:image/png;base64,{base64_data}"
