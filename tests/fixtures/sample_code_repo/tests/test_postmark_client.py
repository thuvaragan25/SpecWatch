from app.providers.postmark_client import PostmarkClient


def test_send_email_prints_invoice_id(capsys):
    client = PostmarkClient()
    client.send_email("INV-2")
    captured = capsys.readouterr()
    assert "INV-2" in captured.out
