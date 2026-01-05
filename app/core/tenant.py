from fastapi import Request, HTTPException
from app.database import get_db_connection
from app.core.security import detect_tenant_from_headers
from app.config import settings
import json
from pathlib import Path

async def detect_and_validate_tenant(request: Request) -> str:
    """
    Detect and validate tenant from request headers.
    Returns the validated site name.
    """

    headers = detect_tenant_from_headers(request)
    potential_sites = []

    if settings.is_development:
        try:
            mapping_path = Path("dev-site-mapping.json")
            if mapping_path.exists():
                dev_site_mapping = json.loads(mapping_path.read_text())

                if headers['forwarded_host'] and headers['forwarded_host'] in dev_site_mapping:
                    potential_sites = [dev_site_mapping[headers['forwarded_host']]]
                else:
                    backend_port = headers['host'].split(':')[1] if ':' in headers['host'] else '8001'
                    backend_host = f"localhost:{backend_port}"

                    if backend_host in dev_site_mapping:
                        potential_sites = [dev_site_mapping[backend_host]]
        except:
            pass

    if not potential_sites:
        potential_sites = [
            headers['forwarded_host'],
            headers['original_host'],
            headers['origin'].replace('https://', '').replace('http://', '') if headers['origin'] else None,
            headers['referer'].replace('https://', '').replace('http://', '').split('/')[0] if headers['referer'] else None,
            headers['host']
        ]

    potential_sites = [site for site in potential_sites if site]

    async with get_db_connection() as conn:
        for site in potential_sites:
            result = await conn.fetchrow(
                "SELECT site FROM tenant_sites WHERE site = $1 AND is_active = true",
                site
            )
            if result:
                return site

    raise HTTPException(
        status_code=404,
        detail=f"No tenant found for sites: {', '.join(potential_sites)}"
    )


async def get_tenant_by_site(site: str) -> dict:
    """Get tenant information by site"""
    async with get_db_connection(use_transaction=False) as conn:
        result = await conn.fetchrow("""
            SELECT
                ts.tenant_id,
                ts.site,
                ts.brand_name,
                ts.is_active,
                t.name as tenant_name,
                t.slug as tenant_slug,
                t.email as tenant_email
            FROM tenant_sites ts
            JOIN tenants t ON ts.tenant_id = t.id
            WHERE ts.site = $1 AND ts.is_active = true
            LIMIT 1
        """, site)

        if not result:
            return None

        return dict(result)


async def validate_tenant_access(tenant_id: str, user_id: str) -> bool:
    """Validate if user has access to tenant"""
    async with get_db_connection(use_transaction=False) as conn:
        result = await conn.fetchrow("""
            SELECT id FROM tenant_members
            WHERE tenant_id = $1 AND user_id = $2 AND is_active = true
            LIMIT 1
        """, tenant_id, user_id)

        return result is not None
