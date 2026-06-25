import pytest
from unittest.mock import mock_open, patch
import sys
sys.path.append("scripts")
from config_validator import validate_config

# Helper to run the validation with a mocked yaml content
def run_validation(yaml_content, is_central=False):
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=yaml_content)):
            return validate_config("dummy.yml", is_central=is_central)

def test_valid_app_config():
    yaml_content = """
aegis-link:
  - name: my_secret
    env: dev
    type: gh-secret
    outputs:
      - type: value
        destination: MY_SECRET
  - name: my_secret
    env: prod
    type: gh-secret
    outputs:
      - type: value
        destination: MY_SECRET_PROD
"""
    assert run_validation(yaml_content, is_central=False) is True

def test_valid_central_config():
    yaml_content = """
aegis-gateway:
  - name: my_secret
    env: dev
    type: gcp-secret-manager
    config:
      source: projects/123/secrets/my-secret/versions/1
"""
    assert run_validation(yaml_content, is_central=True) is True

def test_duplicate_name_and_env(caplog):
    yaml_content = """
aegis-link:
  - name: my_secret
    env: dev
    outputs: [{type: value, destination: A}]
  - name: my_secret
    env: dev
    outputs: [{type: value, destination: B}]
"""
    assert run_validation(yaml_content, is_central=False) is False
    assert "Duplicate identifier found" in caplog.text

def test_missing_name(caplog):
    yaml_content = """
aegis-link:
  - env: dev
    outputs: [{type: value, destination: A}]
"""
    assert run_validation(yaml_content, is_central=False) is False
    assert "is missing name" in caplog.text

def test_uppercase_name(caplog):
    yaml_content = """
aegis-link:
  - name: MY_SECRET
    env: dev
    outputs: [{type: value, destination: A}]
"""
    assert run_validation(yaml_content, is_central=False) is False
    assert "must be lowercase" in caplog.text

def test_app_config_missing_outputs(caplog):
    yaml_content = """
aegis-link:
  - name: my_secret
    env: dev
"""
    assert run_validation(yaml_content, is_central=False) is False
    assert "is missing outputs" in caplog.text

def test_app_config_empty_outputs(caplog):
    yaml_content = """
aegis-link:
  - name: my_secret
    env: dev
    outputs: []
"""
    assert run_validation(yaml_content, is_central=False) is False
    assert "is missing outputs" in caplog.text

def test_central_config_missing_config_block(caplog):
    yaml_content = """
aegis-gateway:
  - name: my_secret
    env: dev
    type: gcp-secret-manager
"""
    assert run_validation(yaml_content, is_central=True) is False
    assert "is missing config.source" in caplog.text

def test_central_config_missing_source(caplog):
    yaml_content = """
aegis-gateway:
  - name: my_secret
    env: dev
    type: gcp-secret-manager
    config:
      other_key: some_value
"""
    assert run_validation(yaml_content, is_central=True) is False
    assert "is missing config.source" in caplog.text

