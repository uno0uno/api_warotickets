from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional
from datetime import datetime
from app.models.event import EventSummary, EventPublic
from app.models.area import AreaSummary
from app.services import events_service, areas_service, promotions_service, sale_stages_service
from app.services import event_images_service
from app.core.dependencies import get_tenant_id

router = APIRouter()


@router.get("/events", response_model=List[EventSummary])
async def list_public_events(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    start_date_from: Optional[datetime] = Query(None, description="Filter events starting from this date"),
    start_date_to: Optional[datetime] = Query(None, description="Filter events starting before this date"),
    city: Optional[str] = Query(None, description="Filter by city (from extra_attributes)"),
    tenant_id: Optional[str] = Depends(get_tenant_id)
):
    """
    List all public active events.
    No authentication required.
    If tenant_id is provided, filters by tenant. Otherwise returns all public events.
    """
    events = await events_service.get_public_events(
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
        event_type=event_type,
        start_date_from=start_date_from,
        start_date_to=start_date_to,
        city=city
    )
    return events


@router.get("/events/{slug}", response_model=EventPublic)
async def get_public_event(
    slug: str,
    tenant_id: Optional[str] = Depends(get_tenant_id)
):
    """
    Get public event details by slug.
    No authentication required.
    """
    event = await events_service.get_event_by_slug(slug, tenant_id=tenant_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Get images from new event_images table
    new_images = await event_images_service.get_event_images_urls(event.id)

    # Fall back to old cluster_images table if not found in new table
    cover_url = new_images.get('cover_image_url') or next(
        (img.image_url for img in event.images if img.type_image == 'cover'),
        None
    )
    banner_url = new_images.get('banner_image_url') or next(
        (img.image_url for img in event.images if img.type_image == 'banner'),
        None
    )
    flyer_url = new_images.get('flyer_image_url')

    return EventPublic(
        id=event.id,
        cluster_name=event.cluster_name,
        slug_cluster=event.slug_cluster,
        description=event.description,
        start_date=event.start_date,
        end_date=event.end_date,
        cluster_type=event.cluster_type,
        cover_image_url=cover_url,
        banner_image_url=banner_url,
        flyer_image_url=flyer_url,
        extra_attributes=event.extra_attributes
    )


@router.get("/events/{slug}/areas", response_model=List[AreaSummary])
async def get_public_event_areas(
    slug: str,
    tenant_id: Optional[str] = Depends(get_tenant_id)
):
    """
    Get available areas for a public event.
    Includes current prices with active sale stages.
    No authentication required.
    """
    event = await events_service.get_event_by_slug(slug, tenant_id=tenant_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    areas = await areas_service.get_public_areas(event.id)
    return areas


@router.get("/events/{slug}/summary")
async def get_public_event_summary(
    slug: str,
    tenant_id: Optional[str] = Depends(get_tenant_id)
):
    """
    Get summary info for a public event.
    Includes total capacity, availability, and price range.
    """
    event = await events_service.get_event_by_slug(slug, tenant_id=tenant_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    areas = await areas_service.get_public_areas(event.id)

    total_capacity = sum(a.capacity for a in areas)
    total_available = sum(a.units_available or 0 for a in areas)
    prices = [a.current_price or a.price for a in areas if a.price]

    return {
        "event_id": event.id,
        "event_name": event.cluster_name,
        "slug": event.slug_cluster,
        "start_date": event.start_date,
        "end_date": event.end_date,
        "total_capacity": total_capacity,
        "tickets_available": total_available,
        "tickets_sold": total_capacity - total_available,
        "min_price": min(prices) if prices else None,
        "max_price": max(prices) if prices else None,
        "areas_count": len(areas),
        "is_sold_out": total_available == 0
    }


@router.get("/events/{slug}/promotions")
async def get_public_event_promotions(
    slug: str,
    tenant_id: Optional[str] = Depends(get_tenant_id)
):
    """
    Get active promotions for a public event.
    Shows available promotional packages/combos.
    No authentication required.
    """
    event = await events_service.get_event_by_slug(slug, tenant_id=tenant_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    promotions = await promotions_service.get_public_promotions(event.id)
    return promotions


@router.get("/events/{slug}/sale-stages")
async def get_public_event_sale_stages(
    slug: str,
    tenant_id: Optional[str] = Depends(get_tenant_id)
):
    """
    Get active sale stages for a public event.
    Shows current pricing tiers and discounts.
    No authentication required.
    """
    event = await events_service.get_event_by_slug(slug, tenant_id=tenant_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    stages = await sale_stages_service.get_public_sale_stages(event.id)
    return stages
