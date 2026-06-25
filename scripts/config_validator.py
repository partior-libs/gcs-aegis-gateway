import os
import sys
import yaml
import logging

# ANSI color codes for logging
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

class ColorFormatter(logging.Formatter):
    def format(self, record):
        if record.levelno == logging.ERROR:
            record.levelname = f"{RED}{record.levelname}{RESET}"
            record.msg = f"{RED}{record.msg}{RESET}"
        elif record.levelno == logging.WARNING:
            record.levelname = f"{YELLOW}{record.levelname}{RESET}"
            record.msg = f"{YELLOW}{record.msg}{RESET}"
        return super().format(record)

# Set up logging
handler = logging.StreamHandler()
handler.setFormatter(ColorFormatter("%(levelname)s: %(message)s"))
logger = logging.getLogger(__name__)
logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False # Prevent double logging if basicConfig is called elsewhere

def validate_config(file_path, is_central=False):
    if not os.path.exists(file_path):
        logger.error(f"Config file not found: {file_path}")
        return False
        
    try:
        with open(file_path, "r") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to read/parse {file_path}: {e}")
        return False
        
    expected_key = "aegis-gateway" if is_central else "aegis-link"
        
    if not config or expected_key not in config:
        logger.warning(f"No {expected_key} found in {file_path}.")
        return True
        
    items = config.get(expected_key, [])
    if not isinstance(items, list):
        logger.error(f"[{file_path}] {expected_key} should be a list.")
        return False

    seen = set()
    is_valid = True
    
    for idx, item in enumerate(items):
        name = item.get("name")
        env = item.get("env")
        
        if not name:
            logger.error(f"[{file_path}] Item at index {idx} is missing name.")
            is_valid = False
            continue
            
        if not name.islower():
            logger.error(f"[{file_path}] Secret name {name} must be lowercase.")
            is_valid = False
            
        identifier = (name, env)
        if identifier in seen:
            logger.error(f"[{file_path}] Duplicate identifier found for name={name} and env={env}.")
            is_valid = False
        else:
            seen.add(identifier)
            
        # Check specific required fields based on config type
        if is_central:
            if "config" not in item or "source" not in item["config"]:
                logger.error(f"[{file_path}] Item {name} env {env} is missing config.source.")
                is_valid = False
        else:
            if "outputs" not in item or not item["outputs"]:
                logger.error(f"[{file_path}] Item {name} env {env} is missing outputs.")
                is_valid = False
                
    return is_valid

def main():
    logger.info("Starting config validation...")
    
    org = os.environ.get("INPUT_ORG")
    repo = os.environ.get("INPUT_REPO")
    config_file = os.environ.get("INPUT_CONFIG_FILE")
    central_config_file = os.environ.get("INPUT_CENTRAL_CONFIG_FILE")
    auth_profiles_file = os.environ.get("INPUT_AUTH_PROFILES_FILE", "config/auth_profiles.yaml")
    action_path = os.environ.get("ACTION_PATH", ".")
    env_filter = os.environ.get("INPUT_ENV")
    
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
            logger.error("Either config-file input or both org and repo inputs are required.")
            sys.exit(0)
    else:
        config_file = os.path.join(action_path, config_file) if not os.path.isabs(config_file) else config_file
            
    auth_profiles_file = os.path.join(action_path, auth_profiles_file) if not os.path.isabs(auth_profiles_file) else auth_profiles_file

    logger.info(f"Validating app config: {config_file}")
    logger.info(f"Validating auth profiles: {auth_profiles_file}")
    
    valid_app = validate_config(config_file, is_central=False)
    
    valid_central = True
    for c_file in central_files_to_load:
        c_path = os.path.join(action_path, c_file) if not os.path.isabs(c_file) else c_file
        logger.info(f"Validating central config: {c_path}")
        if not validate_config(c_path, is_central=True):
            valid_central = False
    
    # Simple validation for auth profiles: just check if it's readable and a dictionary
    valid_auth = True
    if os.path.exists(auth_profiles_file):
        try:
            with open(auth_profiles_file, "r") as f:
                auth_data = yaml.safe_load(f)
                if auth_data and not isinstance(auth_data, dict):
                    logger.error(f"[{auth_profiles_file}] Auth profiles file should be a dictionary.")
                    valid_auth = False
        except Exception as e:
            logger.error(f"Failed to read/parse {auth_profiles_file}: {e}")
            valid_auth = False
    
    if not valid_app or not valid_central or not valid_auth:
        logger.error("Configuration validation failed. Please fix the errors above.")
        sys.exit(0)
        
    logger.info("Configuration validation passed successfully!")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(0)

