"""
Promoter Codes Service
Manages generation and validation of promoter tracking codes.
"""

import secrets
import string
import logging
from typing import Optional
from app.database import get_db_connection

logger = logging.getLogger(__name__)


async def get_or_create_promoter_code(
    tenant_member_id: str,
    tenant_id: str,
    commission_percentage: Optional[float] = None
) -> dict:
    """
    Obtiene el código de promotor existente o genera uno nuevo.

    Args:
        tenant_member_id: ID del tenant_member
        tenant_id: ID del tenant
        commission_percentage: Porcentaje de comisión (opcional, default None)

    Returns:
        dict: Registro completo de promoter_code

    Raises:
        Exception: Si no se puede generar un código único
    """
    async with get_db_connection() as conn:
        # Buscar código existente
        existing = await conn.fetchrow("""
            SELECT * FROM promoter_codes
            WHERE tenant_member_id = $1 AND tenant_id = $2
        """, tenant_member_id, tenant_id)

        if existing:
            logger.info(f"Returning existing promoter code: {existing['code']}")
            return dict(existing)

        # Generar código único WRPROM-XXXXX
        max_attempts = 100
        for attempt in range(max_attempts):
            code = f"WRPROM-{generate_random_suffix(5)}"

            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM promoter_codes WHERE code = $1)",
                code
            )

            if not exists:
                break
        else:
            # Si llegamos aquí, no pudimos generar un código único
            raise Exception(
                f"Failed to generate unique promoter code after {max_attempts} attempts"
            )

        # Crear nuevo código
        record = await conn.fetchrow("""
            INSERT INTO promoter_codes (
                tenant_member_id,
                tenant_id,
                code,
                commission_percentage
            )
            VALUES ($1, $2, $3, $4)
            RETURNING *
        """, tenant_member_id, tenant_id, code, commission_percentage)

        logger.info(
            f"Created new promoter code: {code} "
            f"for tenant_member {tenant_member_id}"
        )

        return dict(record)


async def get_promoter_code_by_code(code: str) -> Optional[dict]:
    """
    Busca un código de promotor por su código.

    Args:
        code: El código a buscar (ej: WRPROM-AB123)

    Returns:
        dict | None: Registro de promoter_code o None si no existe
    """
    async with get_db_connection(use_transaction=False) as conn:
        record = await conn.fetchrow("""
            SELECT * FROM promoter_codes
            WHERE code = $1 AND is_active = true
        """, code)

        return dict(record) if record else None


async def update_commission_percentage(
    promoter_code_id: str,
    commission_percentage: float
) -> dict:
    """
    Actualiza el porcentaje de comisión de un código de promotor.

    Args:
        promoter_code_id: ID del promoter_code
        commission_percentage: Nuevo porcentaje

    Returns:
        dict: Registro actualizado
    """
    async with get_db_connection() as conn:
        record = await conn.fetchrow("""
            UPDATE promoter_codes
            SET commission_percentage = $1,
                updated_at = now()
            WHERE id = $2
            RETURNING *
        """, commission_percentage, promoter_code_id)

        if not record:
            raise ValueError(f"Promoter code {promoter_code_id} not found")

        logger.info(
            f"Updated commission percentage for code {record['code']} "
            f"to {commission_percentage}%"
        )

        return dict(record)


async def deactivate_promoter_code(promoter_code_id: str) -> dict:
    """
    Desactiva un código de promotor.

    Args:
        promoter_code_id: ID del promoter_code

    Returns:
        dict: Registro actualizado
    """
    async with get_db_connection() as conn:
        record = await conn.fetchrow("""
            UPDATE promoter_codes
            SET is_active = false,
                updated_at = now()
            WHERE id = $1
            RETURNING *
        """, promoter_code_id)

        if not record:
            raise ValueError(f"Promoter code {promoter_code_id} not found")

        logger.info(f"Deactivated promoter code: {record['code']}")

        return dict(record)


def generate_random_suffix(length: int) -> str:
    """
    Genera un sufijo aleatorio para códigos de promotor.

    Args:
        length: Longitud del sufijo

    Returns:
        str: Sufijo aleatorio (letras mayúsculas y dígitos)
    """
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))
