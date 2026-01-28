from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from typing import Optional, Literal
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.services import upload_service
from app.services import event_images_service
from app.models.event_image import EventImageCreate

router = APIRouter()

# Max file size: 5MB
MAX_FILE_SIZE = 5 * 1024 * 1024

# Allowed content types
ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"]


class UploadResponse(BaseModel):
    """Respuesta de upload"""
    success: bool
    image_id: Optional[int] = None
    url: Optional[str] = None
    message: Optional[str] = None


class PresignedUrlRequest(BaseModel):
    """Request para URL presignada"""
    filename: str
    content_type: str
    folder: str = "images"


class PresignedUrlResponse(BaseModel):
    """Respuesta con URL presignada"""
    upload_url: str
    final_url: str
    key: str
    expires_in: int


class ConfirmEventImageRequest(BaseModel):
    """Request para confirmar upload de imagen de evento"""
    event_id: int = Field(..., description="ID del evento (cluster)")
    image_type: Literal["banner", "flyer", "cover", "gallery"] = Field(..., description="Tipo de imagen")
    image_url: str = Field(..., description="URL final de la imagen en R2")
    alt_text: Optional[str] = Field(None, description="Texto alternativo")
    width: Optional[int] = Field(None, description="Ancho en pixels")
    height: Optional[int] = Field(None, description="Alto en pixels")
    file_size: Optional[int] = Field(None, description="Tamaño en bytes")


@router.post("/image", response_model=UploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Upload an image file.

    Accepts JPEG, PNG, WebP, and GIF. Max size: 5MB.
    Returns the image ID and URL for use in other endpoints.
    """
    # Validate content type
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de archivo no permitido. Permitidos: {', '.join(ALLOWED_TYPES)}"
        )

    # Read file content
    content = await file.read()

    # Validate size
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Archivo muy grande. Maximo: {MAX_FILE_SIZE // (1024*1024)}MB"
        )

    # Upload
    result = await upload_service.upload_image(
        file_content=content,
        filename=file.filename or "image.jpg",
        content_type=file.content_type
    )

    if not result:
        raise HTTPException(status_code=500, detail="Error al subir imagen")

    return UploadResponse(
        success=True,
        image_id=result['image_id'],
        url=result['url']
    )


@router.post("/presigned-url", response_model=PresignedUrlResponse)
async def get_presigned_url(
    data: PresignedUrlRequest,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get a presigned URL for direct upload to storage.

    Use this for larger files or when you want to upload directly
    from the client without going through the API server.
    """
    if data.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de archivo no permitido"
        )

    result = await upload_service.get_presigned_upload_url(
        filename=data.filename,
        content_type=data.content_type,
        folder=data.folder
    )

    if not result:
        raise HTTPException(status_code=500, detail="Error generando URL")

    return PresignedUrlResponse(**result)


@router.post("/event-image")
async def upload_event_image(
    file: UploadFile = File(...),
    event_id: int = None,
    image_type: str = None,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Upload an image for an event (banner, flyer, cover, gallery).

    Uploads to R2 and saves to event_images table in one step.
    For banner/flyer/cover: replaces existing image of same type.
    """
    # Validate required params
    if not event_id or not image_type:
        raise HTTPException(
            status_code=400,
            detail="event_id y image_type son requeridos"
        )

    if image_type not in ["banner", "flyer", "cover", "gallery"]:
        raise HTTPException(
            status_code=400,
            detail="image_type debe ser: banner, flyer, cover, o gallery"
        )

    # Validate content type
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de archivo no permitido. Permitidos: {', '.join(ALLOWED_TYPES)}"
        )

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Validate size
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Archivo muy grande. Maximo: {MAX_FILE_SIZE // (1024*1024)}MB"
        )

    # Upload to R2
    folder = f"events/{event_id}/{image_type}"
    r2_result = await upload_service.upload_to_r2(
        file_content=content,
        filename=file.filename or "image.jpg",
        content_type=file.content_type,
        folder=folder
    )

    if not r2_result:
        raise HTTPException(status_code=500, detail="Error al subir imagen a R2")

    # Save to event_images table
    image_data = EventImageCreate(
        image_type=image_type,
        image_url=r2_result['url'],
        alt_text=file.filename,
        file_size=file_size
    )

    db_result = await event_images_service.create_event_image(
        cluster_id=event_id,
        image_data=image_data,
        profile_id=user.user_id
    )

    if not db_result:
        raise HTTPException(
            status_code=404,
            detail="Evento no encontrado o no autorizado"
        )

    return {
        "success": True,
        "image_id": db_result['id'],
        "url": r2_result['url'],
        "image_type": image_type,
        "event_id": event_id
    }


@router.delete("/{image_id}", status_code=204)
async def delete_image(
    image_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Delete an uploaded image.

    Note: Only delete images you own/created.
    """
    deleted = await upload_service.delete_image(image_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")
