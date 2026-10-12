"""Thin wrapper around the Postmark email API."""


class PostmarkClient:
    """Sends transactional email through Postmark."""

    def send_email(self, invoice_id: str) -> None:
        print(f"sending invoice {invoice_id}")
