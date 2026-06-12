import os
import sys
import yaml
import json
import logging
from pathlib import Path

try:
    from google.cloud import secretmanager
    import google.auth
    from google.auth import impersonated_credentials
except ImportError:
    secretmanager = None
    google = None

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def write_to_env(destination, secret_value):
    github_env = os.environ.get('GITHUB_ENV')
    if github_env:
        with open(github_env, 'a') as f:
            # Use dynamic delimiter for multiline support to prevent collisions
            import uuid
            delimiter = f"EOF-{uuid.uuid4()}"
            f.write(f"{destination}<<{delimiter}\n{secret_value}\n{delimiter}\n")
        logger.info(f"Successfully set workflow output variable '{destination}'.")
    else:
        logger.warning(f"GITHUB_ENV not found. Would set '{destination}'.")

def write_to_file(destination, secret_value):
    dest_path = Path(destination)
    # Create directories if they do not exist
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, 'w') as f:
        f.write(secret_value)
    logger.info(f"Successfully wrote secret to file '{destination}'.")

def get_gh_secret(source, github_secrets):
    logger.info(f"Fetching GitHub secret: {source}")
    secret_value = github_secrets.get(source) or os.environ.get(source)
    if not secret_value:
        logger.error(f"GitHub secret '{source}' is not available.")
        logger.error("Please ensure you have passed it via 'secrets-json' input or as an environment variable.")
        return None
    return secret_value

def get_gh_variable(source, github_vars):
    logger.info(f"Fetching GitHub variable: {source}")
    secret_value = github_vars.get(source) or os.environ.get(source)
    if not secret_value:
        logger.error(f"GitHub variable '{source}' is not available.")
        logger.error("Please ensure you have passed it via 'vars-json' input or as an environment variable.")
        return None
    return secret_value

def get_gcp_secret(secret_name, source, auth_config=None):
    logger.info(f"Fetching GCP secret: {secret_name}")
    if not secretmanager:
        logger.error("google-cloud-secret-manager or google-auth is not installed. Please add it to your requirements.")
        return None
        
    if not source:
        logger.error(f"GCP secret '{secret_name}' missing 'source' attribute in central config.")
        return None
        
    # Default to latest version if no version is specified
    if "/versions/" not in source:
        source = f"{source}/versions/latest"
        
    try:
        if auth_config and auth_config.get('type') == 'gcp-impersonate':
            target_sa = auth_config.get('service-account')
            logger.info(f"Impersonating GCP service account: {target_sa}")
            base_credentials, _ = google.auth.default()
            creds = impersonated_credentials.Credentials(
                source_credentials=base_credentials,
                target_principal=target_sa,
                target_scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            client = secretmanager.SecretManagerServiceClient(credentials=creds)
        else:
            client = secretmanager.SecretManagerServiceClient()

        response = client.access_secret_version(request={"name": source})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        logger.error(f"Failed to fetch GCP secret '{source}': {e}")
        return None

def get_aws_secret(secret_name, source, auth_config=None):
    logger.info(f"Fetching AWS secret: {secret_name}")
    if not boto3:
        logger.error("boto3 is not installed. Please add it to your requirements.")
        return None
        
    if not source:
        logger.error(f"AWS secret '{secret_name}' missing 'source' attribute in central config.")
        return None
        
    try:
        if auth_config and auth_config.get('type') == 'aws-assume-role':
            target_role_arn = auth_config.get('role-arn')
            region = auth_config.get('region') or 'ap-southeast-1'
            logger.info(f"Assuming AWS role: {target_role_arn} in {region}")
            
            sts_client = boto3.client('sts')
            assumed_role_obj = sts_client.assume_role(
                RoleArn=target_role_arn,
                RoleSessionName="AegisGatewaySecretFetcher"
            )
            credentials = assumed_role_obj['Credentials']
            client = boto3.client(
                'secretsmanager',
                region_name=region,
                aws_access_key_id=credentials['AccessKeyId'],
                aws_secret_access_key=credentials['SecretAccessKey'],
                aws_session_token=credentials['SessionToken']
            )
        else:
            client = boto3.client('secretsmanager')

        response = client.get_secret_value(SecretId=source)
        if 'SecretString' in response:
            return response['SecretString']
        else:
            return response['SecretBinary'].decode('utf-8')
    except ClientError as e:
        logger.error(f"Failed to fetch AWS secret '{source}': {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to fetch AWS secret '{source}': {e}")
        return None

def find_secret_config(central_config, name, env, provider_type):
    central_items = central_config.get('aegis-gateway', [])
    for item in central_items:
        if item.get('name') == name and item.get('env') == env and item.get('type') == provider_type:
            return item.get('config', {})
    return None

def main():
    logger.info("Starting AegisGateway Secret Fetcher......")
    
    # Read inputs
    org = os.environ.get('INPUT_ORG')
    repo = os.environ.get('INPUT_REPO')
    config_file = os.environ.get('INPUT_CONFIG_FILE')
    central_config_file = os.environ.get('INPUT_CENTRAL_CONFIG_FILE', 'config/central_config.yml')
    auth_profiles_file = os.environ.get('INPUT_AUTH_PROFILES_FILE', 'config/auth_profiles.yml')
    action_path = os.environ.get('ACTION_PATH', '.')
    provider_filter = os.environ.get('INPUT_PROVIDER', 'all')
    env_filter = os.environ.get('INPUT_ENV')
    secrets_json_str = os.environ.get('SECRETS_JSON', '{}')
    vars_json_str = os.environ.get('VARS_JSON', '{}')

    github_repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not org and github_repository:
        org = github_repository.split('/')[0]
    if not repo and github_repository:
        repo = github_repository.split('/')[-1]
    
    # Default config path if org and repo are provided
    if not config_file:
        if org and repo:
            config_file = os.path.join(action_path, "config", org, f"{repo}.yml")
        else:
            logger.error("Either 'config-file' input or both 'org' and 'repo' inputs are required.")
            sys.exit(1)
    else:
        config_file = os.path.join(action_path, config_file) if not os.path.isabs(config_file) else config_file
            
    central_config_file = os.path.join(action_path, central_config_file) if not os.path.isabs(central_config_file) else central_config_file
    auth_profiles_file = os.path.join(action_path, auth_profiles_file) if not os.path.isabs(auth_profiles_file) else auth_profiles_file

    try:
        github_secrets = json.loads(secrets_json_str) if secrets_json_str else {}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse SECRETS_JSON: {e}")
        sys.exit(1)

    try:
        github_vars = json.loads(vars_json_str) if vars_json_str else {}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse VARS_JSON: {e}")
        sys.exit(1)

    logger.info("--- AegisGateway Configuration ---")
    logger.info(f"GitHub Org    : {org or 'N/A'}")
    logger.info(f"GitHub Repo   : {repo or 'N/A'}")
    logger.info(f"Config File   : {config_file}")
    logger.info(f"Provider      : {provider_filter}")
    logger.info(f"Environment   : {env_filter or 'N/A'}")
    logger.info("----------------------------------")

    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Config file not found at '{config_file}'.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to read config file '{config_file}': {e}")
        sys.exit(1)

    try:
        with open(central_config_file, 'r') as f:
            central_config = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Central config file not found at '{central_config_file}'.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to read central config file '{central_config_file}': {e}")
        sys.exit(1)

    auth_profiles = {}
    if os.path.exists(auth_profiles_file):
        try:
            with open(auth_profiles_file, 'r') as f:
                auth_profiles = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to read auth profiles file '{auth_profiles_file}': {e}")
            sys.exit(1)
    else:
        logger.warning(f"Auth profiles file not found at '{auth_profiles_file}'.")

    secret_list = config.get('aegis-link', [])
    
    if not secret_list:
        logger.warning("No 'aegis-link' key found in the configuration.")
        return

    for secret_config in secret_list:
        provider = secret_config.get('type')
        secret_name = secret_config.get('name')
        target_env = secret_config.get('env')

        if not provider or not secret_name:
            logger.warning("Skipping an entry due to missing 'type' or 'name'.")
            continue
            
        if provider_filter != 'all' and provider != provider_filter:
            continue
            
        # Filter by environment if an env input was provided and the secret has a specific env
        if env_filter and target_env and target_env != env_filter:
            logger.info(f"Skipping secret '{secret_name}' as its env '{target_env}' does not match requested env '{env_filter}'.")
            continue
            
        process_secret(provider, secret_name, target_env, secret_config, github_secrets, github_vars, central_config, auth_profiles)

def process_secret(provider, secret_name, target_env, secret_config, github_secrets, github_vars, central_config, auth_profiles):
    logger.info(f"Processing secret name: {secret_name} (Provider: {provider}, Env: {target_env})")
    
    outputs = secret_config.get('outputs', [])
    if not outputs:
        logger.error(f"Skipping secret '{secret_name}': the 'outputs' key is missing, not an array, or is empty.")
        return
        
    # Retrieve the mapped config in central config for this provider, name, and env
    mapped_config = find_secret_config(central_config, secret_name, target_env, provider)
    
    if not mapped_config:
        logger.error(f"Could not find entry in central config for name='{secret_name}', env='{target_env}', type='{provider}'")
        return

    source = mapped_config.get('source')
    if not source:
        logger.error(f"Could not find 'source' in central config for name='{secret_name}', env='{target_env}', type='{provider}'")
        return
        
    auth_profile_name = mapped_config.get('auth-profile')
    auth_config = None
    if auth_profile_name:
        auth_config = auth_profiles.get(auth_profile_name)
        if not auth_config:
            logger.warning(f"Auth profile '{auth_profile_name}' not found. Will attempt using base credentials.")

    # 1. Fetch secret value based on provider
    secret_value = None
        
    if provider == 'gh-secret':
        secret_value = get_gh_secret(source, github_secrets)
    elif provider == 'gh-variable':
        secret_value = get_gh_variable(source, github_vars)
    elif provider in ['gcp', 'gcp-secret-manager']:
        secret_value = get_gcp_secret(secret_name, source, auth_config)
    elif provider in ['aws', 'aws-secret-manager']:
        secret_value = get_aws_secret(secret_name, source, auth_config)
    else:
        logger.error(f"Provider type '{provider}' is not supported by this script currently.")
        return
        
    if not secret_value:
        logger.error(f"Failed to retrieve value for '{secret_name}'. Aborting.")
        sys.exit(1)
        
    # 2. Mask the secret in GitHub Actions logs
    for line in secret_value.splitlines():
        if len(line.strip()) > 3:  # Prevent masking empty lines or short common characters
            print(f"::add-mask::{line}")
        
    # 3. Process outputs
    for output in outputs:
        output_type = output.get('type')
        destination = output.get('destination')
        
        if not output_type or not destination:
            logger.error(f"Skipping an output for '{secret_name}': missing a required 'type' or 'destination' key.")
            continue
        
        logger.info(f"Secret's output_type: {output_type}, destination: {destination}")
        
        if output_type == 'value':
            write_to_env(destination, secret_value)
        elif output_type == 'file':
            write_to_file(destination, secret_value)
        else:
            logger.error(f"Unsupported output type '{output_type}'.")
            sys.exit(1)

if __name__ == "__main__":
    main()
