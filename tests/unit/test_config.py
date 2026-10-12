from pathlib import Path

import pytest

from specwatch.config import load_config
from specwatch.domain.errors import ConfigError


def test_load_config_defaults_when_file_missing(tmp_path: Path) -> None:
    config = load_config(repo_path=tmp_path)
    assert config.repo_path == tmp_path
    assert config.min_confidence == 0.80
    assert config.max_tool_calls == 8
    assert config.max_rounds == 4


def test_load_config_reads_yaml_overrides(tmp_path: Path) -> None:
    (tmp_path / "specwatch.yml").write_text("min_confidence: 0.9\nmax_tool_calls: 5\n")
    config = load_config(repo_path=tmp_path)
    assert config.min_confidence == 0.9
    assert config.max_tool_calls == 5


def test_load_config_rejects_invalid_yaml(tmp_path: Path) -> None:
    (tmp_path / "specwatch.yml").write_text("min_confidence: [unclosed\n")
    with pytest.raises(ConfigError):
        load_config(repo_path=tmp_path)


def test_load_config_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    (tmp_path / "specwatch.yml").write_text("- just\n- a\n- list\n")
    with pytest.raises(ConfigError):
        load_config(repo_path=tmp_path)


def test_load_config_rejects_out_of_range_confidence(tmp_path: Path) -> None:
    (tmp_path / "specwatch.yml").write_text("min_confidence: 1.5\n")
    with pytest.raises(ConfigError):
        load_config(repo_path=tmp_path)


def test_load_config_empty_file_uses_defaults(tmp_path: Path) -> None:
    (tmp_path / "specwatch.yml").write_text("")
    config = load_config(repo_path=tmp_path)
    assert config.min_confidence == 0.80
