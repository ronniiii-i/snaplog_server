# server_config.py
import os
import json

# ====================================================================
# Server-specific paths and settings
# ====================================================================

# This MUST match the NETWORK_BASE_PATH set in the client's src/config.py
NETWORK_BASE_PATH = "C:/snaplog_data/" # Example: Adjust this to your actual shared network path

# Path to the central configuration file for all clients
CLIENT_CONFIG_FILE = os.path.join(NETWORK_BASE_PATH, "client_configs.json")

# Path to the server's own configuration file (for conversion time)
SERVER_LOCAL_CONFIG_FILE = "server_config.json"

# Default server conversion time
DEFAULT_SERVER_CONVERSION_TIME = "02:00" # HH:MM

def load_server_config():
    """Loads server-specific configuration (e.g., conversion time)."""
    config = {"conversion_time": DEFAULT_SERVER_CONVERSION_TIME}
    try:
        if os.path.exists(SERVER_LOCAL_CONFIG_FILE):
            with open(SERVER_LOCAL_CONFIG_FILE, 'r') as f:
                loaded_config = json.load(f)
                config["conversion_time"] = loaded_config.get("conversion_time", DEFAULT_SERVER_CONVERSION_TIME)
                print(f"[SERVER_CONFIG] Loaded server configuration: {config}")
        else:
            print(f"[SERVER_CONFIG] Server config file not found. Using defaults.")
    except json.JSONDecodeError:
        print(f"[SERVER_CONFIG] Error decoding JSON from server_config.json. Using defaults.")
    except Exception as e:
        print(f"[SERVER_CONFIG] An error occurred loading server config: {e}. Using defaults.")
    return config

def save_server_config(config):
    """Saves server-specific configuration."""
    try:
        with open(SERVER_LOCAL_CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        print(f"[SERVER_CONFIG] Saved server configuration: {config}")
    except Exception as e:
        print(f"[SERVER_CONFIG] Error saving server config: {e}")