# Models module for WaRo Tickets API
from app.models.event import (
    Event, EventCreate, EventUpdate, EventSummary,
    EventImage, EventImageCreate, EventPublic, EventWithAreas,
    LegalInfo, LegalInfoCreate, EventType, EventStatus
)
from app.models.area import (
    Area, AreaCreate, AreaUpdate, AreaSummary,
    AreaAvailability, AreaBulkCreate, AreaWithUnits, AreaStatus
)
from app.models.unit import (
    Unit, UnitCreate, UnitUpdate, UnitSummary,
    UnitBulkCreate, UnitBulkUpdate, UnitBulkResponse,
    UnitWithArea, UnitsMapView, UnitStatus, UnitSelection
)
from app.models.sale_stage import (
    SaleStage, SaleStageCreate, SaleStageUpdate, SaleStageSummary,
    ActiveSaleStage, PriceAdjustmentType
)
from app.models.area_promotion import (
    AreaPromotion, AreaPromotionCreate, AreaPromotionUpdate, AreaPromotionSummary,
    DiscountType
)
# Aliases for backwards compatibility
Promotion = AreaPromotion
PromotionCreate = AreaPromotionCreate
PromotionUpdate = AreaPromotionUpdate
PromotionSummary = AreaPromotionSummary
from app.models.reservation import (
    Reservation, ReservationCreate, ReservationUpdate, ReservationSummary,
    ReservationUnit, CreateReservationResponse, ReservationTimeout,
    MyTicket, ReservationStatus, ReservationUnitStatus
)
from app.models.payment import (
    Payment, PaymentCreate, PaymentSummary,
    PaymentIntentResponse, PaymentConfirmation,
    WompiWebhookEvent, PaymentStatus, PaymentMethodType
)
from app.models.qr import (
    QRCodeResponse, QRValidationRequest, QRValidationResponse,
    ValidationResult, TicketCheckIn, CheckInStats
)
from app.models.transfer import (
    Transfer, TransferSummary, TransferLogEntry, PendingTransfer,
    TransferInitiateRequest, TransferAcceptRequest, TransferResult,
    TransferStatus
)
from app.models.dashboard import (
    EventSalesSummary, AreaSalesBreakdown, SalesTimeSeries, SalesTimePoint,
    RevenueReport, PaymentMethodBreakdown, CheckInAnalytics, DashboardOverview,
    DateRange, CustomerInsights, ExportRequest, ExportResponse
)
