import os
import sys
import pytest
from unittest.mock import mock_open, patch

sys.path.append("scripts")
from config_validator import validate_config

def test_validate_config_file_not_found(caplog):
    result = validate_config("non_existent.yml", is_central=False)
    assert result is False
    assert "Config file not found" in caplog.text

@patch("os.path.exists", return_value=True)
def test_validate_config_invalid_yaml(mock_exists, caplog):
    with patch("builtins.open", mock_open(read_data="[ invalid yaml")):
        result = validate_config("dummy.yml", is_central=False)
        assert result is False
        assert "Failed to read/parse" in caplog.text

@patch("os.path.exists", return_value=True)
def test_validate_config_valid_app_config(mock_exists):
    yaml_content = """
aegis-link:
  - name: valid_secret
    env: dev
    type: gh-secret
    outputs:
      - type: value
        destination: MY_SECRET
"""
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        result = validate_config("app.yml", is_central=False)
        assert result is True

@patch("os.path.exists", return_value=True)
def test_validate_config_invalid_lowercase(mock_exists, caplog):
    yaml_content = """
aegis-link:
  - name: BAD_SECRET_UPPERCASE
    env: dev
    outputs:
      - type: value
        destination: MY_SECRET
"""
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        result = validate_config("app.yml", is_central=False)
        assert result is False
        assert "must be lowercase" in caplog.text

