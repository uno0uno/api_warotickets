from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.core.logging import setup_logging
from app.core.exceptions import api_exception_handler, general_exception_handler, APIError
from app.core.middleware import tenant_detection_middleware, session_validation_middleware, request_logging_middleware

# Initialize logging
setup_logging()

app = FastAPI(
    title="WaRo Tickets API",
    description="API para sistema de ticketera y venta de boleteria",
    version="1.0.0",
    debug=settings.debug,
    docs_url="/docs",
    redirect_slashes=True
)

# Configure cookie authentication for Swagger UI
from fastapi.openapi.utils import get_openapi

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="WaRo Tickets API",
        version="1.0.0",
        description="API para sistema de ticketera y venta de boleteria para eventos",
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "cookieAuth": {
            "type": "apiKey",
            "in": "cookie",
            "name": "session-token"
        }
    }

    # Public endpoints (no auth required)
    public_endpoints = [
        "/auth/sign-in-magic-link",
        "/auth/verify-code",
        "/auth/verify",
        "/health",
        "/",
    ]

    # Public prefixes
    public_prefixes = ["/public", "/webhooks", "/cart"]

    for path in openapi_schema["paths"]:
        if path in public_endpoints:
            continue
        if any(path.startswith(prefix) for prefix in public_prefixes):
            continue

        for method in openapi_schema["paths"][path]:
            if method in ["get", "post", "put", "delete", "patch"]:
                openapi_schema["paths"][path][method]["security"] = [{"cookieAuth": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# Exception handlers
app.add_exception_handler(APIError, api_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom middleware (order matters - first added runs last)
# Execution order: tenant_detection → session_validation → logging
app.middleware("http")(request_logging_middleware)   # runs last
app.middleware("http")(session_validation_middleware) # runs second
app.middleware("http")(tenant_detection_middleware)   # runs first

# Import and include routers
from app.routers import (
    events, areas, units, public,
    sale_stages, promotions, reservations, payments,
    qr, transfers, auth, tenants, ticket_cart, uploads,
    promoters, invitations
)
from app.routers.admin import promoters as admin_promoters, commissions as admin_commissions

# Authentication (public endpoints)
app.include_router(auth.router, prefix="/auth", tags=["auth"])

# Event management (requires auth)
app.include_router(events.router, prefix="/events", tags=["events"])
app.include_router(areas.router, prefix="/areas", tags=["areas"])
app.include_router(units.router, prefix="/units", tags=["units"])

# Pricing (requires auth for management, some public endpoints)
app.include_router(sale_stages.router, prefix="/sale-stages", tags=["sale-stages"])
app.include_router(promotions.router, prefix="/promotions", tags=["promotions"])

# Reservations and Payments (requires auth)
app.include_router(reservations.router, prefix="/reservations", tags=["reservations"])
app.include_router(payments.router, prefix="/payments", tags=["payments"])

# Public endpoints (no auth required)
app.include_router(public.router, prefix="/public", tags=["public"])

# QR codes (requires auth)
app.include_router(qr.router, prefix="/qr", tags=["qr"])

# Ticket transfers (requires auth)
app.include_router(transfers.router, prefix="/transfers", tags=["transfers"])


# Tenants management (requires auth)
app.include_router(tenants.router, prefix="/tenants", tags=["tenants"])

# Shopping cart (public - no auth required)
app.include_router(ticket_cart.router, prefix="/cart", tags=["cart"])

# Uploads (requires auth)
app.include_router(uploads.router, prefix="/uploads", tags=["uploads"])

# Promoter system (requires auth)
app.include_router(promoters.router, prefix="/promoters", tags=["promoters"])
app.include_router(admin_promoters.router, tags=["admin-promoters"])
app.include_router(admin_commissions.router, tags=["admin-commissions"])

# Invitations (requires auth)
app.include_router(invitations.router, tags=["invitations"])

@app.get("/")
async def root():
    return {
        "service": "WaRo Tickets API",
        "version": "1.0.0",
        "database": settings.db_name,
        "environment": settings.environment
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "database": settings.db_name,
        "host": settings.db_host
    }

# Background tasks
import asyncio
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - startup and shutdown"""
    # Startup: Start background cleanup task
    from app.tasks.cleanup import run_cleanup_loop
    cleanup_task = asyncio.create_task(run_cleanup_loop())

    yield

    # Shutdown: Cancel background task
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

# Note: To use lifespan, update FastAPI initialization:
# app = FastAPI(..., lifespan=lifespan)

# Auto-start server if run directly
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
