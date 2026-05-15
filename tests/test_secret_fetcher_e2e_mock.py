import pytest
import os
import sys
import json
import yaml
from unittest.mock import patch, mock_open, MagicMock

sys.path.append("scripts")
import secret_fetcher

def test_main_e2e_mocked():
    central_yaml = """
aegis-gateway:
  - name: dummy_dev_secret_1
    env: devnet02
    type: gh-secret
    config:
      source: DUMMY_SECRET_VALUE_1
"""
    app_yaml = """
aegis-link:
  - name: dummy_dev_secret_1
    type: gh-secret
    env: devnet02
    outputs:
      - type: value
        destination: MY_WF_SECRET_KEY_1
"""

    mocked_env = {
        'INPUT_CONFIG_FILE': 'dummy_app.yml',
        'INPUT_CENTRAL_CONFIG_FILE': 'dummy_central.yml',
        'SECRETS_JSON': json.dumps({'DUMMY_SECRET_VALUE_1': 'real_secret_123'})
    }

    def mock_file_open(filename, mode='r'):
        if filename == 'dummy_app.yml':
            return mock_open(read_data=app_yaml).return_value
        elif filename == 'dummy_central.yml':
            return mock_open(read_data=central_yaml).return_value
        raise FileNotFoundError(filename)

    with patch.dict(os.environ, mocked_env, clear=True):
        with patch('builtins.open', side_effect=mock_file_open):
            with patch('secret_fetcher.write_to_env') as mock_write_to_env:
                with patch('sys.stdout') as mock_stdout:
                    secret_fetcher.main()
                    
                    mock_write_to_env.assert_called_once_with('MY_WF_SECRET_KEY_1', 'real_secret_123')
