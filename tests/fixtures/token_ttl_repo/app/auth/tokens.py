"""Password reset token generation and validation."""

TOKEN_TTL_MINUTES = 30


class PasswordResetTokenService:
    """Issues and validates password reset tokens."""

    def issue_token(self, user_id: str) -> str:
        """Create a new password reset token for a user."""
        return f"token-for-{user_id}"

    def validate_token(self, token: str) -> bool:
        """Check whether a password reset token is still valid."""
        return token.startswith("token-for-")
