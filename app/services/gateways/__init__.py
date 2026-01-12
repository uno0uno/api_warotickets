# Payment Gateways
from app.services.gateways.base import BaseGateway, PaymentIntent, WebhookResult
from app.services.gateways.bold import BoldGateway
from app.services.gateways.wompi import WompiGateway

GATEWAYS = {
    'bold': BoldGateway,
    'wompi': WompiGateway,
}

def get_gateway(name: str) -> BaseGateway:
    """Get gateway instance by name"""
    gateway_class = GATEWAYS.get(name.lower())
    if not gateway_class:
        raise ValueError(f"Unknown gateway: {name}. Available: {list(GATEWAYS.keys())}")
    return gateway_class()
