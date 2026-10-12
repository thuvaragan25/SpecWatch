from app.providers.postmark_client import PostmarkClient
from app.services.delivery_service import InvoiceDeliveryService
from app.services.invoice_service import InvoiceService


def test_send_invoice_delivers_via_client(capsys):
    client = PostmarkClient()
    delivery = InvoiceDeliveryService(client)
    service = InvoiceService(delivery)

    service.send("INV-1")

    captured = capsys.readouterr()
    assert "INV-1" in captured.out
