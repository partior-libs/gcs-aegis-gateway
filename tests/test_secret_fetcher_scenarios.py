import pytest
import os
import sys
import json
from unittest.mock import patch, mock_open, MagicMock
from io import StringIO

sys.path.append("scripts")
from secret_fetcher import process_secret, main

def test_fetch_gh_secret():
    central_config = {
        'aegis-gateway': [
            {
                'name': 'my_gh_secret',
                'env': 'dev',
                'type': 'gh-secret',
                'config': {
                    'source': 'SECRET_IN_GITHUB'
                }
            }
        ]
    }
    secret_config = {
        'name': 'my_gh_secret',
        'env': 'dev',
        'type': 'gh-secret',
        'outputs': [
            {'type': 'value', 'destination': 'MY_WF_SECRET'}
        ]
    }
    github_secrets = {'SECRET_IN_GITHUB': 'super_secret_value'}
    github_vars = {}

    with patch('secret_fetcher.write_to_env') as mock_write_to_env:
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            process_secret('gh-secret', 'my_gh_secret', 'dev', secret_config, github_secrets, github_vars, central_config)

            mock_write_to_env.assert_called_once_with('MY_WF_SECRET', 'super_secret_value')
            assert '::add-mask::super_secret_value' in mock_stdout.getvalue()

def test_fetch_gh_variable_file_output():
    central_config = {
        'aegis-gateway': [
            {
                'name': 'my_gh_var',
                'env': 'prod',
                'type': 'gh-variable',
                'config': {
                    'source': 'VAR_IN_GITHUB'
                }
            }
        ]
    }
    secret_config = {
        'name': 'my_gh_var',
        'env': 'prod',
        'type': 'gh-variable',
        'outputs': [
            {'type': 'file', 'destination': './tmp/my_var.txt'}
        ]
    }
    github_secrets = {}
    github_vars = {'VAR_IN_GITHUB': 'var_value'}

    with patch('secret_fetcher.write_to_file') as mock_write_to_file:
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            process_secret('gh-variable', 'my_gh_var', 'prod', secret_config, github_secrets, github_vars, central_config)

            mock_write_to_file.assert_called_once_with('./tmp/my_var.txt', 'var_value')
            assert '::add-mask::var_value' in mock_stdout.getvalue()

@patch('secret_fetcher.secretmanager')
def test_fetch_gcp_secret(mock_secretmanager):
    # Setup mock GCP secret manager
    mock_client_instance = MagicMock()
    mock_secretmanager.SecretManagerServiceClient.return_value = mock_client_instance
    
    mock_response = MagicMock()
    mock_response.payload.data.decode.return_value = "gcp_super_secret"
    mock_client_instance.access_secret_version.return_value = mock_response

    central_config = {
        'aegis-gateway': [
            {
                'name': 'my_gcp_secret',
                'env': 'dev',
                'type': 'gcp-secret-manager',
                'config': {
                    'source': 'projects/123/secrets/my-secret/versions/1'
                }
            }
        ]
    }
    secret_config = {
        'name': 'my_gcp_secret',
        'env': 'dev',
        'type': 'gcp-secret-manager',
        'outputs': [
            {'type': 'value', 'destination': 'MY_GCP_SECRET'},
            {'type': 'file', 'destination': './tmp/gcp_secret.txt'}
        ]
    }

    with patch('secret_fetcher.write_to_env') as mock_write_to_env:
        with patch('secret_fetcher.write_to_file') as mock_write_to_file:
            with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
                process_secret('gcp-secret-manager', 'my_gcp_secret', 'dev', secret_config, {}, {}, central_config)

                mock_write_to_env.assert_called_once_with('MY_GCP_SECRET', 'gcp_super_secret')
                mock_write_to_file.assert_called_once_with('./tmp/gcp_secret.txt', 'gcp_super_secret')
                assert '::add-mask::gcp_super_secret' in mock_stdout.getvalue()
                
                # Verify that GCP secret manager was called correctly
                mock_client_instance.access_secret_version.assert_called_once_with(
                    request={"name": "projects/123/secrets/my-secret/versions/1"}
                )
