"""Outbound email delivery."""


class EmailSender:
    """Sends transactional email notifications."""

    def send(self, recipient: str, subject: str, body: str) -> None:
        """Send an email to a recipient."""
        print(f"emailing {recipient}: {subject}")
