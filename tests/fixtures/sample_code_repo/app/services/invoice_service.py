"""Invoice sending service."""

from app.services.delivery_service import InvoiceDeliveryService


class InvoiceService:
    """Coordinates invoice approval and delivery."""

    def __init__(self, delivery: InvoiceDeliveryService) -> None:
        self.delivery = delivery

    def send(self, invoice_id: str) -> None:
        """Send an approved invoice."""
        self.delivery.deliver(invoice_id)
