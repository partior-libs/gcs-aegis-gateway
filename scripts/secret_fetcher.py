import os
import sys
import yaml
import json
import logging
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Locks to prevent race conditions during concurrent file writes
env_file_lock = threading.Lock()
file_write_lock = threading.Lock()

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
        with env_file_lock:
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
    with file_write_lock:
        # Create directories if they do not exist
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, 'w') as f:
            f.write(secret_value)
        # Set strict permissions (0600) for security and compatibility with strict clients like PostgreSQL
        os.chmod(dest_path, 0o600)
    logger.info(f"Successfully wrote secret to file '{destination}' with 0600 permissions.")

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

def get_gcp_secret(secret_name, source, auth_config=None, version=None):
    logger.info(f"Fetching GCP secret: {secret_name}")
    if not secretmanager:
        logger.error("google-cloud-secret-manager or google-auth is not installed. Please add it to your requirements.")
        return None
        
    if not source:
        logger.error(f"GCP secret '{secret_name}' missing 'source' attribute in central config.")
        return None
        
    # Default to latest version if no version is specified
    if "/versions/" not in source:
        target_version = version if version else "latest"
        source = f"{source}/versions/{target_version}"
        
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

def get_aws_secret(secret_name, source, auth_config=None, version=None):
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

        kwargs = {'SecretId': source}
        if version:
             kwargs['VersionStage'] = version

        response = client.get_secret_value(**kwargs)
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
    matches = []
    
    for item in central_items:
        # Match if name and type match, and environment matches (including both being None)
        if item.get('name') == name and item.get('type') == provider_type and item.get('env') == env:
            matches.append(item.get('config', {}))
            
    if not matches:
        return None
    elif len(matches) > 1:
        # Throw an exception if we have multiple identical matches so it's not a race condition
        raise ValueError(f"Ambiguous configuration: Found {len(matches)} entries in central config matching name='{name}', env='{env}', type='{provider_type}'. Please remove duplicates.")
        
    return matches[0]

def main():
    logger.info("Starting AegisGateway Secret Fetcher......")
    
    # Read inputs
    org = os.environ.get('INPUT_ORG')
    repo = os.environ.get('INPUT_REPO')
    config_file = os.environ.get('INPUT_CONFIG_FILE')
    central_config_file = os.environ.get('INPUT_CENTRAL_CONFIG_FILE')
    auth_profiles_file = os.environ.get('INPUT_AUTH_PROFILES_FILE', 'config/auth_profiles.yaml')
    action_path = os.environ.get('ACTION_PATH', '.')
    provider_filter = os.environ.get('INPUT_PROVIDER', 'all')
    env_filter = os.environ.get('INPUT_ENV')
    
    central_files_to_load = []
    if central_config_file:
        central_files_to_load.append(central_config_file)
    elif env_filter:
        central_files_to_load.append(f"config/central_configs/{env_filter}.yaml")
    else:
        configs_dir = os.path.join(action_path, "config", "central_configs")
        if os.path.exists(configs_dir):
            for f in os.listdir(configs_dir):
                if f.endswith(".yaml"):
                    central_files_to_load.append(f"config/central_configs/{f}")
        if not central_files_to_load:
            logger.warning("No central configuration files found.")
            
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
            config_file = os.path.join(action_path, "config", org, f"{repo}.yaml")
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

    central_config = {'aegis-gateway': []}
    for c_file in central_files_to_load:
        c_path = os.path.join(action_path, c_file) if not os.path.isabs(c_file) else c_file
        try:
            with open(c_path, 'r') as f:
                c_data = yaml.safe_load(f) or {}
                if 'aegis-gateway' in c_data:
                    central_config['aegis-gateway'].extend(c_data['aegis-gateway'])
        except FileNotFoundError:
            logger.error(f"Central config file not found at '{c_path}'.")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Failed to read central config file '{c_path}': {e}")
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

    # Use ThreadPoolExecutor to fetch secrets concurrently
    futures = []
    has_errors = False
    
    with ThreadPoolExecutor(max_workers=10) as executor:
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
                
            futures.append(
                executor.submit(
                    process_secret, 
                    provider, 
                    secret_name, 
                    target_env, 
                    secret_config, 
                    github_secrets, 
                    github_vars, 
                    central_config, 
                    auth_profiles
                )
            )

    for future in as_completed(futures):
        try:
            future.result() # Raises exception if the task failed
        except Exception as e:
            logger.error(f"A secret fetching task failed: {e}")
            has_errors = True

    if has_errors:
        logger.error("One or more secret fetching tasks failed. Aborting.")
        sys.exit(1)

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
    version = mapped_config.get('version')
    # Allow application config to specify json-key, fallback to central config
    json_key_to_extract = secret_config.get('json-key') or mapped_config.get('json-key')
    
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
        secret_value = get_gcp_secret(secret_name, source, auth_config, version)
    elif provider in ['aws', 'aws-secret-manager']:
        secret_value = get_aws_secret(secret_name, source, auth_config, version)
    else:
        logger.error(f"Provider type '{provider}' is not supported by this script currently.")
        return
        
    if not secret_value:
        logger.error(f"Failed to retrieve value for '{secret_name}'. Aborting.")
        raise Exception(f"Failed to retrieve value for '{secret_name}'.")

    # If a JSON property is requested, extract it now
    if json_key_to_extract:
        try:
            parsed_json = json.loads(secret_value)
            if json_key_to_extract in parsed_json:
                secret_value = str(parsed_json[json_key_to_extract])
            else:
                logger.error(f"Key '{json_key_to_extract}' not found in the JSON secret '{secret_name}'.")
                raise Exception(f"Missing JSON key '{json_key_to_extract}' in secret '{secret_name}'.")
        except json.JSONDecodeError:
            logger.error(f"Secret '{secret_name}' is not valid JSON, but 'json-key' extraction was requested.")
            raise Exception(f"Invalid JSON for key extraction in secret '{secret_name}'.")
        
    # 2. Mask the secret in GitHub Actions logs
    # for line in secret_value.splitlines():
    #     if len(line.strip()) > 3:  # Prevent masking empty lines or short common characters
    #         print(f"::add-mask::{line}")
        
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
            raise Exception(f"Unsupported output type '{output_type}'.")

if __name__ == "__main__":
    main()
