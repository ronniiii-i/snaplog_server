import os
import json
import sys

# ====================================================================
# Server-specific paths and settings
# ====================================================================

# This MUST match the NETWORK_BASE_PATH set in the client's src/config.py
NETWORK_BASE_PATH = "E:/Binn/" # Example: Adjust this to your actual shared network path
NETWORK_CONVERTED_PATH = "E:/Binn2/" # Example: Adjust this to your actual shared network 

# Path to the central configuration file for all clients
CLIENT_CONFIG_FILE = os.path.join(NETWORK_BASE_PATH, "client_configs.json")

# Get the directory where the executable is located
if getattr(sys, 'frozen', False): # True if running as a PyInstaller bundle
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

# Path to the server's own configuration file (for conversion time, type, and aliases)
SERVER_LOCAL_CONFIG_FILE = os.path.join(application_path, 'server_config.json')

# SERVER_LOCAL_CONFIG_FILE = "server_config.json"

# Default server conversion settings
DEFAULT_SERVER_CONVERSION_TYPE = "daily" # "daily" or "periodic"
DEFAULT_SERVER_CONVERSION_VALUE = "17:00" # HH:MM for daily, seconds for periodic (e.g., 3600 for 1 hour)

def load_server_config():
    """Loads server-specific configuration (e.g., conversion time, type, client aliases)."""
    config = {
        "conversion_type": DEFAULT_SERVER_CONVERSION_TYPE,
        "conversion_value": DEFAULT_SERVER_CONVERSION_VALUE,
        "client_aliases": {}
    }
    try:
        if os.path.exists(SERVER_LOCAL_CONFIG_FILE):
            with open(SERVER_LOCAL_CONFIG_FILE, 'r') as f:
                loaded_config = json.load(f)
                # Load new fields, providing defaults for backward compatibility
                config["conversion_type"] = loaded_config.get("conversion_type", DEFAULT_SERVER_CONVERSION_TYPE)
                config["conversion_value"] = loaded_config.get("conversion_value", DEFAULT_SERVER_CONVERSION_VALUE)
                config["client_aliases"] = loaded_config.get("client_aliases", {})
                print(f"[SERVER_CONFIG] Loaded server configuration: {config}")
        else:
            print("[SERVER_CONFIG] Server config file not found. Using defaults.")
    except json.JSONDecodeError:
        print("[SERVER_CONFIG] Error decoding JSON from server_config.json. Using defaults.")
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