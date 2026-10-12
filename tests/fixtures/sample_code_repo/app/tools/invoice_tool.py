"""Entry point used by the invoicing CLI/worker."""

from app.providers.postmark_client import PostmarkClient
from app.services.delivery_service import InvoiceDeliveryService
from app.services.invoice_service import InvoiceService


def send_invoice(invoice_id: str) -> None:
    service = InvoiceService(InvoiceDeliveryService(PostmarkClient()))
    service.send(invoice_id)
