from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.services import upload_service

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
