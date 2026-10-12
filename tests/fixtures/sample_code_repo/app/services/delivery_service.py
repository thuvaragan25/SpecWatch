"""Delivery service that hands invoices off to the email provider."""

from app.providers.postmark_client import PostmarkClient


class InvoiceDeliveryService:
    """Delivers an approved invoice via the configured email client."""

    def __init__(self, client: PostmarkClient) -> None:
        self.client = client

    def deliver(self, invoice_id: str) -> None:
        self.client.send_email(invoice_id)
