"""SpecWatch configuration loading."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from specwatch.domain.errors import ConfigError

DEFAULT_CONFIG_FILENAME = "specwatch.yml"


class Config(BaseModel):
    """SpecWatch runtime configuration for a single repository."""

    repo_path: Path = Field(default_factory=Path.cwd)
    model: str = "anthropic:claude-sonnet-5"
    min_confidence: float = Field(default=0.80, ge=0.0, le=1.0)
    max_tool_calls: int = Field(default=8, ge=1)
    max_rounds: int = Field(default=4, ge=1)
    ignore_file: str = ".specwatchignore"


def load_config(path: Path | None = None, repo_path: Path | None = None) -> Config:
    """Load configuration from a YAML file, falling back to defaults if absent.

    Args:
        path: Explicit path to a config file. Defaults to
            ``<repo_path>/specwatch.yml``.
        repo_path: Repository root. Defaults to the current working
            directory.
    """
    repo_path = repo_path or Path.cwd()
    config_path = path or (repo_path / DEFAULT_CONFIG_FILENAME)

    if not config_path.exists():
        return Config(repo_path=repo_path)

    try:
        raw = yaml.safe_load(config_path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse {config_path}: {exc}") from exc

    raw = raw or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path} must contain a YAML mapping at the top level")

    raw.setdefault("repo_path", str(repo_path))

    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration in {config_path}: {exc}") from exc
