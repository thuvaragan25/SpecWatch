"""Base exception hierarchy for SpecWatch."""


class SpecWatchError(Exception):
    """Base class for all SpecWatch errors."""


class ConfigError(SpecWatchError):
    """Raised when configuration cannot be loaded or is invalid."""
