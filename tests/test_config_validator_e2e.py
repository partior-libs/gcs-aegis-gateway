import os
import subprocess
import pytest

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'config_validator.py')
TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), 'test_data')

def run_validator(app_config, central_config=None):
    env = os.environ.copy()
    env["INPUT_CONFIG_FILE"] = app_config
    if central_config:
        env["INPUT_CENTRAL_CONFIG_FILE"] = central_config
    
    result = subprocess.run(
        ["python", SCRIPT_PATH],
        env=env,
        capture_output=True,
        text=True
    )
    return result

def test_e2e_valid_configs():
    app_config = os.path.join(TEST_DATA_DIR, "valid_app_config.yml")
    central_config = os.path.join(TEST_DATA_DIR, "valid_central_config.yml")
    
    result = run_validator(app_config, central_config)
    assert result.returncode == 0
    assert "Configuration validation passed successfully!" in result.stderr or "Configuration validation passed successfully!" in result.stdout

def test_e2e_invalid_app_missing_name():
    app_config = os.path.join(TEST_DATA_DIR, "invalid_app_config_missing_name.yml")
    central_config = os.path.join(TEST_DATA_DIR, "valid_central_config.yml")
    
    result = run_validator(app_config, central_config)
    assert result.returncode == 1
    assert "is missing name" in result.stderr or "is missing name" in result.stdout

def test_e2e_invalid_app_duplicate():
    app_config = os.path.join(TEST_DATA_DIR, "invalid_app_config_duplicate.yml")
    central_config = os.path.join(TEST_DATA_DIR, "valid_central_config.yml")
    
    result = run_validator(app_config, central_config)
    assert result.returncode == 1
    assert "Duplicate identifier found" in result.stderr or "Duplicate identifier found" in result.stdout

def test_e2e_invalid_app_uppercase():
    app_config = os.path.join(TEST_DATA_DIR, "invalid_app_config_uppercase.yml")
    central_config = os.path.join(TEST_DATA_DIR, "valid_central_config.yml")
    
    result = run_validator(app_config, central_config)
    assert result.returncode == 1
    assert "must be lowercase" in result.stderr or "must be lowercase" in result.stdout

def test_e2e_invalid_app_missing_outputs():
    app_config = os.path.join(TEST_DATA_DIR, "invalid_app_config_missing_outputs.yml")
    central_config = os.path.join(TEST_DATA_DIR, "valid_central_config.yml")
    
    result = run_validator(app_config, central_config)
    assert result.returncode == 1
    assert "is missing outputs" in result.stderr or "is missing outputs" in result.stdout

def test_e2e_invalid_central_missing_source():
    app_config = os.path.join(TEST_DATA_DIR, "valid_app_config.yml")
    central_config = os.path.join(TEST_DATA_DIR, "invalid_central_config_missing_source.yml")
    
    result = run_validator(app_config, central_config)
    assert result.returncode == 1
    assert "is missing config.source" in result.stderr or "is missing config.source" in result.stdout
