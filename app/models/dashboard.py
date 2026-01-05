from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from enum import Enum


class DateRange(str, Enum):
    """Rangos de fecha predefinidos"""
    TODAY = "today"
    YESTERDAY = "yesterday"
    LAST_7_DAYS = "last_7_days"
    LAST_30_DAYS = "last_30_days"
    THIS_MONTH = "this_month"
    LAST_MONTH = "last_month"
    ALL_TIME = "all_time"


class EventSalesSummary(BaseModel):
    """Resumen de ventas de un evento"""
    event_id: int
    event_name: str
    event_date: Optional[datetime] = None
    event_status: str

    # Capacidad
    total_capacity: int
    available_units: int
    sold_units: int
    reserved_units: int

    # Financiero
    total_revenue: float
    pending_revenue: float  # Reservas sin pagar

    # Porcentajes
    occupancy_percentage: float
    sales_velocity: Optional[float] = None  # Ventas por día

    class Config:
        from_attributes = True


class AreaSalesBreakdown(BaseModel):
    """Desglose de ventas por área"""
    area_id: int
    area_name: str
    base_price: float
    current_price: float  # Con etapa de venta aplicada

    total_units: int
    sold_units: int
    available_units: int
    reserved_units: int

    revenue: float
    occupancy_percentage: float

    class Config:
        from_attributes = True


class SalesTimePoint(BaseModel):
    """Punto de datos de ventas en el tiempo"""
    date: date
    tickets_sold: int
    revenue: float
    reservations_created: int
    reservations_expired: int


class SalesTimeSeries(BaseModel):
    """Serie temporal de ventas"""
    event_id: int
    event_name: str
    date_range: str
    data_points: List[SalesTimePoint]

    # Totales del periodo
    total_tickets: int
    total_revenue: float


class PaymentMethodBreakdown(BaseModel):
    """Desglose por método de pago"""
    method: str
    transaction_count: int
    total_amount: float
    percentage: float


class RevenueReport(BaseModel):
    """Reporte de ingresos"""
    event_id: int
    event_name: str
    period: str

    # Totales
    gross_revenue: float
    refunds: float
    net_revenue: float

    # Desglose
    by_payment_method: List[PaymentMethodBreakdown]
    by_area: List[AreaSalesBreakdown]

    # Promedios
    average_ticket_price: float
    average_transaction_value: float


class CheckInAnalytics(BaseModel):
    """Analíticas de check-in"""
    event_id: int
    event_name: str
    event_date: Optional[datetime] = None

    total_tickets: int
    checked_in: int
    pending: int
    transferred: int
    cancelled: int

    check_in_percentage: float

    # Timing
    first_check_in: Optional[datetime] = None
    last_check_in: Optional[datetime] = None
    peak_hour: Optional[str] = None

    # Por área
    by_area: List[dict]  # [{area_name, checked_in, pending, percentage}]


class DashboardOverview(BaseModel):
    """Vista general del dashboard"""
    profile_id: str

    # Eventos
    total_events: int
    active_events: int
    upcoming_events: int
    past_events: int

    # Tickets totales
    total_tickets_sold: int
    total_revenue: float

    # Eventos recientes
    recent_events: List[EventSalesSummary]

    # Actividad reciente
    recent_sales_count: int  # Últimas 24 horas
    recent_revenue: float


class SalesByHour(BaseModel):
    """Ventas por hora del día"""
    hour: int  # 0-23
    tickets_sold: int
    revenue: float


class CustomerInsights(BaseModel):
    """Insights de clientes"""
    event_id: int

    unique_customers: int
    repeat_customers: int
    new_customers: int

    average_tickets_per_customer: float
    top_customers: List[dict]  # [{name, email, tickets_count, total_spent}]


class ExportRequest(BaseModel):
    """Request para exportar datos"""
    event_id: int
    report_type: str = Field(..., description="sales, checkins, revenue, attendees")
    format: str = Field(default="csv", description="csv, xlsx, pdf")
    date_from: Optional[date] = None
    date_to: Optional[date] = None


class ExportResponse(BaseModel):
    """Respuesta de exportación"""
    download_url: str
    expires_at: datetime
    file_name: str
    file_size: int
