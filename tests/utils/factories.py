"""
Factories para generar datos de prueba.
"""
from datetime import datetime, timedelta
from typing import Optional
import secrets


class UserFactory:
    """Factory para crear usuarios de prueba."""

    _counter = 0

    @classmethod
    def create(
        cls,
        id: Optional[str] = None,
        email: Optional[str] = None,
        name: Optional[str] = None
    ) -> dict:
        cls._counter += 1
        return {
            "id": id or f"user-{cls._counter}",
            "email": email or f"user{cls._counter}@test.com",
            "name": name or f"Test User {cls._counter}",
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }


class EventFactory:
    """Factory para crear eventos de prueba."""

    _counter = 0

    @classmethod
    def create(
        cls,
        id: Optional[int] = None,
        profile_id: str = "test-user-123",
        cluster_name: Optional[str] = None,
        start_date: Optional[datetime] = None,
        **kwargs
    ) -> dict:
        cls._counter += 1
        name = cluster_name or f"Evento Test {cls._counter}"
        slug = name.lower().replace(" ", "-")

        return {
            "id": id or cls._counter,
            "profile_id": profile_id,
            "cluster_name": name,
            "slug_cluster": slug,
            "description": kwargs.get("description", "Descripción del evento"),
            "start_date": start_date or (datetime.now() + timedelta(days=30)),
            "end_date": kwargs.get("end_date", datetime.now() + timedelta(days=30, hours=6)),
            "cluster_type": kwargs.get("cluster_type", "concert"),
            "is_active": kwargs.get("is_active", True),
            "shadowban": kwargs.get("shadowban", False),
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
            "total_capacity": kwargs.get("total_capacity", 1000),
            "tickets_sold": kwargs.get("tickets_sold", 0),
            "tickets_available": kwargs.get("tickets_available", 1000)
        }


class AreaFactory:
    """Factory para crear áreas de prueba."""

    _counter = 0

    @classmethod
    def create(
        cls,
        id: Optional[int] = None,
        cluster_id: int = 1,
        area_name: Optional[str] = None,
        **kwargs
    ) -> dict:
        cls._counter += 1

        return {
            "id": id or cls._counter,
            "cluster_id": cluster_id,
            "area_name": area_name or f"Área {cls._counter}",
            "description": kwargs.get("description", "Descripción del área"),
            "capacity": kwargs.get("capacity", 100),
            "base_price": kwargs.get("base_price", 100000.0),
            "is_active": kwargs.get("is_active", True),
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }


class UnitFactory:
    """Factory para crear units de prueba."""

    _counter = 0

    @classmethod
    def create(
        cls,
        id: Optional[int] = None,
        area_id: int = 1,
        status: str = "available",
        **kwargs
    ) -> dict:
        cls._counter += 1

        return {
            "id": id or cls._counter,
            "area_id": area_id,
            "nomenclature_letter_area": kwargs.get("nomenclature_letter_area", "A"),
            "nomenclature_number_unit": kwargs.get("nomenclature_number_unit", cls._counter),
            "status": status,
            "price": kwargs.get("price"),
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }

    @classmethod
    def create_batch(cls, count: int, area_id: int = 1, **kwargs) -> list:
        """Crea múltiples units."""
        return [cls.create(area_id=area_id, **kwargs) for _ in range(count)]


class ReservationFactory:
    """Factory para crear reservaciones de prueba."""

    _counter = 0

    @classmethod
    def create(
        cls,
        id: Optional[int] = None,
        user_id: str = "test-user-123",
        cluster_id: int = 1,
        status: str = "pending",
        **kwargs
    ) -> dict:
        cls._counter += 1

        return {
            "id": id or cls._counter,
            "user_id": user_id,
            "cluster_id": cluster_id,
            "status": status,
            "total_price": kwargs.get("total_price", 200000.0),
            "promotion_code": kwargs.get("promotion_code"),
            "promotion_discount": kwargs.get("promotion_discount", 0),
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
            "start_date": kwargs.get("start_date", datetime.now()),
            "end_date": kwargs.get("end_date", datetime.now() + timedelta(hours=2))
        }


class ReservationUnitFactory:
    """Factory para crear reservation_units de prueba."""

    _counter = 0

    @classmethod
    def create(
        cls,
        id: Optional[int] = None,
        reservation_id: int = 1,
        unit_id: int = 1,
        status: str = "reserved",
        **kwargs
    ) -> dict:
        cls._counter += 1

        return {
            "id": id or cls._counter,
            "reservation_id": reservation_id,
            "unit_id": unit_id,
            "status": status,
            "price": kwargs.get("price", 100000.0),
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }


class PaymentFactory:
    """Factory para crear pagos de prueba."""

    _counter = 0

    @classmethod
    def create(
        cls,
        id: Optional[int] = None,
        reservation_id: int = 1,
        status: str = "pending",
        **kwargs
    ) -> dict:
        cls._counter += 1

        return {
            "id": id or cls._counter,
            "reservation_id": reservation_id,
            "status": status,
            "amount": kwargs.get("amount", 200000.0),
            "payment_method": kwargs.get("payment_method", "card"),
            "external_reference": kwargs.get("external_reference"),
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }


class SaleStageFactory:
    """Factory para crear etapas de venta de prueba."""

    _counter = 0

    @classmethod
    def create(
        cls,
        id: Optional[int] = None,
        cluster_id: int = 1,
        **kwargs
    ) -> dict:
        cls._counter += 1

        return {
            "id": id or cls._counter,
            "cluster_id": cluster_id,
            "name": kwargs.get("name", f"Etapa {cls._counter}"),
            "adjustment_type": kwargs.get("adjustment_type", "percentage"),
            "adjustment_value": kwargs.get("adjustment_value", -10),
            "start_date": kwargs.get("start_date", datetime.now()),
            "end_date": kwargs.get("end_date", datetime.now() + timedelta(days=30)),
            "priority": kwargs.get("priority", cls._counter),
            "is_active": kwargs.get("is_active", True)
        }


class PromotionFactory:
    """Factory para crear promociones de prueba."""

    _counter = 0

    @classmethod
    def create(
        cls,
        id: Optional[int] = None,
        cluster_id: int = 1,
        code: Optional[str] = None,
        **kwargs
    ) -> dict:
        cls._counter += 1

        return {
            "id": id or cls._counter,
            "cluster_id": cluster_id,
            "code": code or f"PROMO{cls._counter}",
            "discount_type": kwargs.get("discount_type", "percentage"),
            "discount_value": kwargs.get("discount_value", 10),
            "max_uses": kwargs.get("max_uses", 100),
            "current_uses": kwargs.get("current_uses", 0),
            "valid_from": kwargs.get("valid_from", datetime.now()),
            "valid_until": kwargs.get("valid_until", datetime.now() + timedelta(days=30)),
            "applies_to": kwargs.get("applies_to", "all"),
            "is_active": kwargs.get("is_active", True)
        }


class TransferFactory:
    """Factory para crear transferencias de prueba."""

    _counter = 0

    @classmethod
    def create(
        cls,
        id: Optional[int] = None,
        reservation_unit_id: int = 1,
        from_user_id: str = "test-user-123",
        to_email: str = "recipient@test.com",
        **kwargs
    ) -> dict:
        cls._counter += 1
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(hours=48)

        return {
            "id": id or cls._counter,
            "reservation_unit_id": reservation_unit_id,
            "from_user_id": from_user_id,
            "to_user_id": kwargs.get("to_user_id"),
            "to_email": to_email,
            "transfer_token": token,
            "status": kwargs.get("status", "pending"),
            "message": kwargs.get("message"),
            "transfer_reason": f"PENDING|{token}|{to_email}|{expires_at.isoformat()}|",
            "transfer_date": datetime.now(),
            "expires_at": expires_at
        }
