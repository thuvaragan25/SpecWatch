from app.providers.postmark_client import PostmarkClient
from app.services.delivery_service import InvoiceDeliveryService


def test_deliver_forwards_to_client(capsys):
    client = PostmarkClient()
    delivery = InvoiceDeliveryService(client)
    delivery.deliver("INV-3")
    captured = capsys.readouterr()
    assert "INV-3" in captured.out
