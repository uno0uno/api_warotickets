from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from enum import Enum


class ImageType(str, Enum):
    """Tipos de imagen de evento"""
    BANNER = "banner"
    FLYER = "flyer"
    COVER = "cover"
    GALLERY = "gallery"


class EventImageBase(BaseModel):
    """Campos base de una imagen de evento"""
    image_type: Literal["banner", "flyer", "cover", "gallery"] = Field(
        ..., description="Tipo de imagen: banner, flyer, cover, gallery"
    )
    image_url: str = Field(..., description="URL de la imagen en storage")
    alt_text: Optional[str] = Field(None, max_length=255, description="Texto alternativo")
    width: Optional[int] = Field(None, gt=0, description="Ancho en pixels")
    height: Optional[int] = Field(None, gt=0, description="Alto en pixels")
    file_size: Optional[int] = Field(None, gt=0, description="Tamaño del archivo en bytes")


class EventImageCreate(EventImageBase):
    """Schema para crear una imagen de evento"""
    pass


class EventImageUpdate(BaseModel):
    """Schema para actualizar una imagen de evento"""
    image_url: Optional[str] = None
    alt_text: Optional[str] = Field(None, max_length=255)
    width: Optional[int] = Field(None, gt=0)
    height: Optional[int] = Field(None, gt=0)
    file_size: Optional[int] = Field(None, gt=0)


class EventImage(EventImageBase):
    """Schema completo de imagen de evento"""
    id: int
    cluster_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EventImageSummary(BaseModel):
    """Schema resumido para respuestas"""
    id: int
    image_type: str
    image_url: str
    alt_text: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None

    class Config:
        from_attributes = True
