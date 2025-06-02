import tkinter as tk
from tkinter import ttk, messagebox
import os
import json
import threading
import time
from datetime import datetime, timedelta
from PIL import Image # For image conversion
import logging
import traceback
import queue # For thread-safe logging

# Import server-specific configuration
from server_config import (
    NETWORK_BASE_PATH, NETWORK_CONVERTED_PATH, CLIENT_CONFIG_FILE,
    load_server_config, save_server_config,
    DEFAULT_SERVER_CONVERSION_TYPE, DEFAULT_SERVER_CONVERSION_VALUE
)

# --- Custom Logging Handler for GUI ---
class TextHandler(logging.Handler):
    """A custom logging handler that sends logs to a Tkinter Text widget."""
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.queue = queue.Queue() # Use a queue for thread-safe updates
        self.master = text_widget.winfo_toplevel() # Get the root window
        self.master.after(100, self.check_queue) # Start checking the queue

    def emit(self, record):
        msg = self.format(record)
        self.queue.put(msg)

    def check_queue(self):
        while not self.queue.empty():
            msg = self.queue.get()
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, msg + '\n')
            self.text_widget.configure(state='disabled')
            # Auto-scroll to the bottom
            self.text_widget.see(tk.END)
        self.master.after(100, self.check_queue) # Schedule next check

# Configure logging for the server
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
# Base logging configuration (will be overridden by TextHandler for GUI)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename=os.path.join(log_dir, 'snaplog_server.log'),
    filemode='a'
)
logger = logging.getLogger(__name__)

class SnapLogServer: 
    def __init__(self, master):
        self.master = master
        master.title("SnapLog Server Dashboard")
        master.geometry("1000x750") # Increased size for log display

        self.client_configs = {} # Stores all client configurations
        self.server_config = load_server_config() # Load server's own config (includes aliases)
        self.conversion_thread = None
        self.stop_conversion_event = threading.Event()
        self.last_daily_conversion_check = None # To prevent multiple daily conversions within the same minute
        self.last_periodic_conversion_time = None # To track last periodic conversion time

        self._create_widgets()
        # Set up GUI logging handler AFTER widgets are created
        self.log_handler = TextHandler(self.log_text_widget)
        self.log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(self.log_handler)
        logger.info("SnapLog Server GUI started.")

        self._load_all_client_configs() # This will now load aliases too
        self._populate_client_list()
        self._start_conversion_scheduler()

        # Periodically refresh client list and configs
        self.master.after(60000, self._refresh_data) # Refresh every minute

        # Handle window close event
        self.master.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _create_widgets(self):
        # Main PanedWindow for resizable sections
        self.paned_window = ttk.PanedWindow(self.master, orient=tk.HORIZONTAL)
        self.paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- Moved conversion_status_label creation here to ensure it exists early ---
        self.conversion_status_label = ttk.Label(self.master, text="Conversion Status: Initializing...", font=('Arial', 10))
        self.conversion_status_label.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=5)
        # --- End of moved section ---

        # Left Frame: Client List and Alias
        self.left_frame = ttk.Frame(self.paned_window)
        self.paned_window.add(self.left_frame, weight=1)

        self.client_list_frame = ttk.LabelFrame(self.left_frame, text="Connected Clients")
        self.client_list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.client_listbox = tk.Listbox(self.client_list_frame, height=15)
        self.client_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.client_listbox.bind("<<ListboxSelect>>", self._on_client_select)

        self.refresh_button = ttk.Button(self.client_list_frame, text="Refresh Clients", command=self._refresh_data)
        self.refresh_button.pack(pady=5)

        # Alias section
        self.alias_frame = ttk.LabelFrame(self.left_frame, text="Manage Alias for Selected Client")
        self.alias_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(self.alias_frame, text="Alias:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.alias_var = tk.StringVar()
        self.alias_entry = ttk.Entry(self.alias_frame, textvariable=self.alias_var)
        self.alias_entry.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=2)
        self.save_alias_button = ttk.Button(self.alias_frame, text="Save Alias", command=self._save_alias)
        self.save_alias_button.grid(row=1, column=0, columnspan=2, pady=5)
        self.alias_frame.grid_columnconfigure(1, weight=1)


        # Right Frame: Configuration Details & Apply to All & Server Settings
        self.right_frame = ttk.Frame(self.paned_window)
        self.paned_window.add(self.right_frame, weight=2)

        # Client Specific Configuration
        self.config_frame = ttk.LabelFrame(self.right_frame, text="Selected Client Configuration")
        self.config_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Selected Client Label
        self.selected_client_label = ttk.Label(self.config_frame, text="Selected Client: None", font=('Arial', 12, 'bold'))
        self.selected_client_label.grid(row=0, column=0, columnspan=2, pady=10)

        # Screenshot Interval
        ttk.Label(self.config_frame, text="Screenshot Interval (seconds):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.screenshot_interval_var = tk.StringVar()
        self.screenshot_interval_entry = ttk.Entry(self.config_frame, textvariable=self.screenshot_interval_var)
        self.screenshot_interval_entry.grid(row=1, column=1, sticky=tk.EW, padx=5, pady=2)

        # Upload Type
        ttk.Label(self.config_frame, text="Upload Type:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.upload_type_var = tk.StringVar(value="daily")
        self.upload_type_daily_radio = ttk.Radiobutton(self.config_frame, text="Daily (HH:MM)", variable=self.upload_type_var, value="daily", command=self._toggle_upload_value_entry)
        self.upload_type_periodic_radio = ttk.Radiobutton(self.config_frame, text="Periodic (seconds)", variable=self.upload_type_var, value="periodic", command=self._toggle_upload_value_entry)
        self.upload_type_daily_radio.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        self.upload_type_periodic_radio.grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)

        # Upload Value
        ttk.Label(self.config_frame, text="Upload Value:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=2)
        self.upload_value_var = tk.StringVar()
        self.upload_value_entry = ttk.Entry(self.config_frame, textvariable=self.upload_value_var)
        self.upload_value_entry.grid(row=4, column=1, sticky=tk.EW, padx=5, pady=2)

        # Save Client Settings Button
        self.save_client_button = ttk.Button(self.config_frame, text="Save Client Settings", command=self._save_client_config)
        self.save_client_button.grid(row=5, column=0, columnspan=2, pady=10)

        self.config_frame.grid_columnconfigure(1, weight=1)

        # Apply to All Clients Section
        self.apply_all_frame = ttk.LabelFrame(self.right_frame, text="Apply Settings to ALL Clients")
        self.apply_all_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(self.apply_all_frame, text="Screenshot Interval (seconds):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.apply_all_screenshot_interval_var = tk.StringVar()
        ttk.Entry(self.apply_all_frame, textvariable=self.apply_all_screenshot_interval_var).grid(row=0, column=1, sticky=tk.EW, padx=5, pady=2)

        ttk.Label(self.apply_all_frame, text="Upload Type:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.apply_all_upload_type_var = tk.StringVar(value="daily")
        ttk.Radiobutton(self.apply_all_frame, text="Daily (HH:MM)", variable=self.apply_all_upload_type_var, value="daily", command=self._toggle_apply_all_upload_value_entry).grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Radiobutton(self.apply_all_frame, text="Periodic (seconds)", variable=self.apply_all_upload_type_var, value="periodic", command=self._toggle_apply_all_upload_value_entry).grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)

        ttk.Label(self.apply_all_frame, text="Upload Value:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.apply_all_upload_value_var = tk.StringVar()
        self.apply_all_upload_value_entry = ttk.Entry(self.apply_all_frame, textvariable=self.apply_all_upload_value_var)
        self.apply_all_upload_value_entry.grid(row=3, column=1, sticky=tk.EW, padx=5, pady=2)

        ttk.Button(self.apply_all_frame, text="Apply to ALL Clients", command=self._apply_to_all_clients).grid(row=4, column=0, columnspan=2, pady=10)
        self.apply_all_frame.grid_columnconfigure(1, weight=1)
        self._toggle_apply_all_upload_value_entry() # Initial state

        # Server Conversion Settings
        self.server_settings_frame = ttk.LabelFrame(self.right_frame, text="Server Conversion Settings")
        self.server_settings_frame.pack(fill=tk.X, padx=5, pady=5)

        # Conversion Type (Daily/Periodic)
        ttk.Label(self.server_settings_frame, text="Conversion Type:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.server_conversion_type_var = tk.StringVar(value=self.server_config["conversion_type"])
        self.server_conversion_daily_radio = ttk.Radiobutton(self.server_settings_frame, text="Daily (HH:MM)", variable=self.server_conversion_type_var, value="daily", command=self._toggle_server_conversion_value_entry)
        self.server_conversion_periodic_radio = ttk.Radiobutton(self.server_settings_frame, text="Periodic (seconds)", variable=self.server_conversion_type_var, value="periodic", command=self._toggle_server_conversion_value_entry)
        self.server_conversion_daily_radio.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        self.server_conversion_periodic_radio.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)

        # Conversion Value
        ttk.Label(self.server_settings_frame, text="Conversion Value:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.server_conversion_value_var = tk.StringVar(value=self.server_config["conversion_value"])
        self.server_conversion_value_entry = ttk.Entry(self.server_settings_frame, textvariable=self.server_conversion_value_var)
        self.server_conversion_value_entry.grid(row=2, column=1, sticky=tk.EW, padx=5, pady=2)

        self.save_server_button = ttk.Button(self.server_settings_frame, text="Save Server Settings", command=self._save_server_config)
        self.save_server_button.grid(row=3, column=0, columnspan=2, pady=10) # Adjusted row for new fields
        self.server_settings_frame.grid_columnconfigure(1, weight=1)

        # New: Manual Conversion Button
        self.manual_conversion_button = ttk.Button(self.server_settings_frame, text="Run Conversion Now", command=self._manual_run_conversion)
        self.manual_conversion_button.grid(row=4, column=0, columnspan=2, pady=5) # Placed below save button

        # Initial state of server conversion value entry
        self._toggle_server_conversion_value_entry()


        # Log Display Area
        self.log_frame = ttk.LabelFrame(self.master, text="Server Log")
        self.log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.log_text_widget = tk.Text(self.log_frame, wrap=tk.WORD, state='disabled', height=10) # Set height for initial view
        self.log_text_widget.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.log_scrollbar = ttk.Scrollbar(self.log_text_widget, command=self.log_text_widget.yview)
        self.log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text_widget['yscrollcommand'] = self.log_scrollbar.set

        # Initial state of client upload value entry
        self._toggle_upload_value_entry()

    def _toggle_upload_value_entry(self):
        """Enables/disables and updates placeholder for individual client upload_value_entry."""
        if self.upload_type_var.get() == "daily":
            self.upload_value_entry.config(state=tk.NORMAL)
        else: # periodic
            self.upload_value_entry.config(state=tk.NORMAL)

    def _toggle_apply_all_upload_value_entry(self):
        """Enables/disables and updates placeholder for 'Apply to All' upload_value_entry."""
        if self.apply_all_upload_type_var.get() == "daily":
            self.apply_all_upload_value_entry.config(state=tk.NORMAL)
        else: # periodic
            self.apply_all_upload_value_entry.config(state=tk.NORMAL)

    def _toggle_server_conversion_value_entry(self):
        """Enables/disables and updates placeholder for server conversion_value_entry."""
        if self.server_conversion_type_var.get() == "daily":
            self.server_conversion_value_entry.config(state=tk.NORMAL)
        else: # periodic
            self.server_conversion_value_entry.config(state=tk.NORMAL)

    def _load_all_client_configs(self):
        """Loads all client configurations from the central JSON file and server aliases."""
        try:
            os.makedirs(NETWORK_BASE_PATH, exist_ok=True) # Ensure base path exists
            if os.path.exists(CLIENT_CONFIG_FILE):
                with open(CLIENT_CONFIG_FILE, 'r') as f:
                    self.client_configs = json.load(f)
                logger.info(f"Loaded all client configs from {CLIENT_CONFIG_FILE}")
            else:
                self.client_configs = {}
                logger.warning(f"Client config file not found at {CLIENT_CONFIG_FILE}. Starting with empty configs.")
        except json.JSONDecodeError:
            messagebox.showerror("Error", f"Error decoding JSON from {CLIENT_CONFIG_FILE}. File might be corrupted.")
            self.client_configs = {}
            logger.error(f"JSONDecodeError loading client configs from {CLIENT_CONFIG_FILE}", exc_info=True)
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred loading client configs: {e}")
            self.client_configs = {}
            logger.error(f"Error loading client configs: {e}", exc_info=True)
        
        # Load aliases from server_config (which is already loaded in __init__)
        self.client_aliases = self.server_config.get("client_aliases", {})
        logger.info(f"Loaded client aliases: {self.client_aliases}")


    def _save_all_client_configs(self):
        """Saves all client configurations to the central JSON file."""
        try:
            os.makedirs(NETWORK_BASE_PATH, exist_ok=True) # Ensure base path exists
            with open(CLIENT_CONFIG_FILE, 'w') as f:
                json.dump(self.client_configs, f, indent=4)
            logger.info(f"Saved all client configs to {CLIENT_CONFIG_FILE}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save client configurations: {e}")
            logger.error(f"Error saving client configs: {e}", exc_info=True)

    def _populate_client_list(self):
        """Populates the client listbox with available device IDs and their aliases."""
        self.client_listbox.delete(0, tk.END)
        # Scan for existing client directories in NETWORK_BASE_PATH
        found_clients = []
        try:
            if os.path.exists(NETWORK_BASE_PATH):
                for item in os.listdir(NETWORK_BASE_PATH):
                    full_path = os.path.join(NETWORK_BASE_PATH, item)
                    # Exclude special folders like 'logs', 'converted', and the config file itself
                    if os.path.isdir(full_path) and item not in ["logs", "converted", os.path.basename(CLIENT_CONFIG_FILE).split('.')[0]]:
                        found_clients.append(item)
            else:
                logger.warning(f"Network base path not found: {NETWORK_BASE_PATH}")
        except FileNotFoundError:
            logger.warning(f"Network base path not found: {NETWORK_BASE_PATH}")
        except PermissionError:
            logger.error(f"Permission denied accessing network path: {NETWORK_BASE_PATH}")
            messagebox.showerror("Permission Error", f"Permission denied accessing network path: {NETWORK_BASE_PATH}. Please check folder permissions.")
        except Exception as e:
            logger.error(f"Error scanning network path for clients: {e}", exc_info=True)

        # Combine found clients with those in the config file
        all_device_ids = sorted(list(set(found_clients) | set(self.client_configs.keys())))

        if not all_device_ids:
            self.client_listbox.insert(tk.END, "No clients found yet.")
            self.client_listbox.config(state=tk.DISABLED)
        else:
            self.client_listbox.config(state=tk.NORMAL)
            for device_id in all_device_ids:
                alias = self.client_aliases.get(device_id, None)
                display_name = f"{alias} ({device_id})" if alias else device_id
                self.client_listbox.insert(tk.END, display_name)
        
        # Select the first client if available
        if all_device_ids:
            self.client_listbox.selection_set(0)
            self._on_client_select() # Manually trigger selection update

    def _on_client_select(self, event=None):
        """Loads the selected client's configuration and alias into the input fields."""
        selected_indices = self.client_listbox.curselection()
        if not selected_indices:
            self.selected_client_label.config(text="Selected Client: None")
            self._clear_config_fields()
            self.alias_var.set("") # Clear alias field
            return

        selected_display_name = self.client_listbox.get(selected_indices[0])
        # Extract the actual device_id from the display name (e.g., "Alias (device_id)")
        if "(" in selected_display_name and selected_display_name.endswith(")"):
            selected_client_id = selected_display_name[selected_display_name.rfind('(') + 1:-1]
        else:
            selected_client_id = selected_display_name

        self.selected_client_label.config(text=f"Selected Client: {selected_display_name}")

        config = self.client_configs.get(selected_client_id, {})
        
        # Populate fields, using defaults if not present in config
        self.screenshot_interval_var.set(config.get("screenshot_interval", 300))
        self.upload_type_var.set(config.get("upload_type", "daily"))
        self.upload_value_var.set(config.get("upload_value", "09:03"))
        
        self._toggle_upload_value_entry() # Adjust entry state based on type

        # Populate alias field
        self.alias_var.set(self.client_aliases.get(selected_client_id, ""))

    def _clear_config_fields(self):
        """Clears all client configuration input fields."""
        self.screenshot_interval_var.set("")
        self.upload_type_var.set("daily")
        self.upload_value_var.set("")
        self._toggle_upload_value_entry()

    def _save_client_config(self):
        """Saves the current client configuration from the input fields."""
        selected_indices = self.client_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Warning", "Please select a client first.")
            return

        selected_display_name = self.client_listbox.get(selected_indices[0])
        if "(" in selected_display_name and selected_display_name.endswith(")"):
            selected_client_id = selected_display_name[selected_display_name.rfind('(') + 1:-1]
        else:
            selected_client_id = selected_display_name

        try:
            screenshot_interval = int(self.screenshot_interval_var.get())
            if screenshot_interval <= 0:
                raise ValueError("Screenshot interval must be a positive integer.")

            upload_type = self.upload_type_var.get()
            upload_value = self.upload_value_var.get()

            if upload_type == "daily":
                # Validate HH:MM format
                datetime.strptime(upload_value, "%H:%M")
            elif upload_type == "periodic":
                # Validate as integer seconds
                upload_value = int(upload_value)
                if upload_value <= 0:
                    raise ValueError("Periodic upload value (seconds) must be a positive integer.")
            else:
                raise ValueError("Invalid upload type selected.")

            self.client_configs[selected_client_id] = {
                "screenshot_interval": screenshot_interval,
                "upload_type": upload_type,
                "upload_value": upload_value
            }
            self._save_all_client_configs()
            messagebox.showinfo("Success", f"Configuration saved for {selected_display_name}.")
            logger.info(f"Configuration saved for {selected_display_name}: {self.client_configs[selected_client_id]}")

        except ValueError as ve:
            messagebox.showerror("Validation Error", str(ve))
            logger.error(f"Validation error saving client config for {selected_display_name}: {ve}")
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")
            logger.error(f"Unexpected error saving client config for {selected_display_name}: {e}", exc_info=True)

    def _save_alias(self):
        """Saves the alias for the currently selected client."""
        selected_indices = self.client_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Warning", "Please select a client first to save an alias.")
            return

        selected_display_name = self.client_listbox.get(selected_indices[0])
        if "(" in selected_display_name and selected_display_name.endswith(")"):
            selected_client_id = selected_display_name[selected_display_name.rfind('(') + 1:-1]
        else:
            selected_client_id = selected_display_name
        
        new_alias = self.alias_var.get().strip()
        
        if new_alias:
            self.client_aliases[selected_client_id] = new_alias
            logger.info(f"Alias for {selected_client_id} set to: '{new_alias}'")
        else:
            if selected_client_id in self.client_aliases:
                del self.client_aliases[selected_client_id]
                logger.info(f"Alias for {selected_client_id} removed.")
            else:
                messagebox.showinfo("Info", "No alias entered and no existing alias to remove.")
                return

        self.server_config["client_aliases"] = self.client_aliases
        save_server_config(self.server_config)
        
        messagebox.showinfo("Success", f"Alias updated for {selected_display_name}.")
        self._populate_client_list() # Refresh list to show new alias
        # Re-select the client to ensure its fields are updated correctly
        for i, item in enumerate(self.client_listbox.get(0, tk.END)):
            if selected_client_id in item: # Check if device_id is part of the item string
                self.client_listbox.selection_set(i)
                self.client_listbox.activate(i)
                self._on_client_select()
                break

    def _apply_to_all_clients(self):
        """Applies the settings from the 'Apply to ALL Clients' section to all clients."""
        if not messagebox.askyesno("Confirm Apply to All", "Are you sure you want to apply these settings to ALL connected clients? This action cannot be undone for client configurations."):
            return

        try:
            screenshot_interval = int(self.apply_all_screenshot_interval_var.get())
            if screenshot_interval <= 0:
                raise ValueError("Screenshot interval must be a positive integer.")

            upload_type = self.apply_all_upload_type_var.get()
            upload_value = self.apply_all_upload_value_var.get()

            if upload_type == "daily":
                datetime.strptime(upload_value, "%H:%M")
            elif upload_type == "periodic":
                upload_value = int(upload_value)
                if upload_value <= 0:
                    raise ValueError("Periodic upload value (seconds) must be a positive integer.")
            else:
                raise ValueError("Invalid upload type selected.")

            updated_count = 0
            # Iterate through all clients currently known (from scanning folders or existing configs)
            # Ensure we update existing entries and potentially add new ones if they've appeared
            all_device_ids = sorted(list(set(self.client_configs.keys()) | set(self._get_found_client_dirs())))

            if not all_device_ids:
                messagebox.showwarning("No Clients", "No clients found to apply settings to.")
                return

            for device_id in all_device_ids:
                self.client_configs[device_id] = {
                    "screenshot_interval": screenshot_interval,
                    "upload_type": upload_type,
                    "upload_value": upload_value
                }
                updated_count += 1
            
            self._save_all_client_configs()
            messagebox.showinfo("Success", f"Settings applied to {updated_count} clients successfully.")
            logger.info(f"Settings applied to {updated_count} clients: Interval={screenshot_interval}, Type={upload_type}, Value={upload_value}")
            self._populate_client_list() # Refresh GUI
            self._on_client_select() # Re-select current client to show updated values

        except ValueError as ve:
            messagebox.showerror("Validation Error", str(ve))
            logger.error(f"Validation error applying settings to all clients: {ve}")
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")
            logger.error(f"Unexpected error applying settings to all clients: {e}", exc_info=True)

    def _get_found_client_dirs(self):
        """Helper to get list of actual client directories on network path."""
        found_clients = []
        try:
            if os.path.exists(NETWORK_BASE_PATH):
                for item in os.listdir(NETWORK_BASE_PATH):
                    full_path = os.path.join(NETWORK_BASE_PATH, item)
                    if os.path.isdir(full_path) and item not in ["logs", "converted", os.path.basename(CLIENT_CONFIG_FILE).split('.')[0]]:
                        found_clients.append(item)
        except Exception as e:
            logger.error(f"Error getting found client directories: {e}", exc_info=True)
        return found_clients

    def _save_server_config(self):
        """Saves the server's conversion type and value settings."""
        try:
            conversion_type = self.server_conversion_type_var.get()
            conversion_value = self.server_conversion_value_var.get()

            if conversion_type == "daily":
                # Validate HH:MM format
                datetime.strptime(conversion_value, "%H:%M")
            elif conversion_type == "periodic":
                # Validate as integer seconds
                conversion_value = int(conversion_value)
                if conversion_value <= 0:
                    raise ValueError("Periodic conversion value (seconds) must be a positive integer.")
            else:
                raise ValueError("Invalid conversion type selected.")

            self.server_config["conversion_type"] = conversion_type
            self.server_config["conversion_value"] = conversion_value
            save_server_config(self.server_config)
            messagebox.showinfo("Success", "Server conversion settings saved.")
            logger.info(f"Server conversion settings updated to: Type={conversion_type}, Value={conversion_value}")
            self._start_conversion_scheduler() # Restart scheduler with new settings
        except ValueError as ve:
            messagebox.showerror("Validation Error", str(ve))
            logger.error(f"Validation error saving server config: {ve}")
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")
            logger.error(f"Unexpected error saving server config: {e}", exc_info=True)

    def _refresh_data(self):
        """Refreshes client list and reloads configurations."""
        logger.info("Refreshing client data...")
        self._load_all_client_configs()
        self._populate_client_list()
        self.master.after(60000, self._refresh_data) # Schedule next refresh

    def _start_conversion_scheduler(self):
        """Starts or restarts the background thread for scheduled conversions."""
        if self.conversion_thread and self.conversion_thread.is_alive():
            self.stop_conversion_event.set() # Signal existing thread to stop
            self.conversion_thread.join(timeout=2) # Wait for it to finish
            self.stop_conversion_event.clear() # Clear event for new thread
            logger.info("Stopped existing conversion scheduler.")

        self.conversion_thread = threading.Thread(target=self._conversion_scheduler_loop, daemon=True)
        self.conversion_thread.start()
        
        status_text = f"Conversion Status: Scheduled for {self.server_config['conversion_type']} ({self.server_config['conversion_value']})"
        self.conversion_status_label.config(text=status_text)
        logger.info(f"Started conversion scheduler: {status_text}.")

    def _conversion_scheduler_loop(self):
        """Background loop to trigger conversion based on scheduled type (daily or periodic)."""
        while not self.stop_conversion_event.is_set():
            # Reload server config to pick up changes dynamically
            self.server_config = load_server_config()
            conversion_type = self.server_config["conversion_type"]
            conversion_value = self.server_config["conversion_value"]
            
            now = datetime.now()
            should_run_conversion = False

            if conversion_type == "daily":
                target_time_str = str(conversion_value) # Ensure it's a string like "HH:MM"
                current_time_str = now.strftime("%H:%M")
                
                if current_time_str == target_time_str and current_time_str != self.last_daily_conversion_check:
                    should_run_conversion = True
                    self.last_daily_conversion_check = current_time_str # Mark as checked for this minute
                elif current_time_str != self.last_daily_conversion_check:
                    # Reset last_daily_conversion_check if the minute changes, so it can trigger again next day
                    self.last_daily_conversion_check = None 
                
                # Reset periodic tracker if switching to daily
                self.last_periodic_conversion_time = None

            elif conversion_type == "periodic":
                try:
                    interval_seconds = int(conversion_value)
                    if self.last_periodic_conversion_time is None:
                        # First run, or after service restart, run immediately
                        should_run_conversion = True
                        self.last_periodic_conversion_time = now
                    elif (now - self.last_periodic_conversion_time).total_seconds() >= interval_seconds:
                        should_run_conversion = True
                        self.last_periodic_conversion_time = now
                except ValueError:
                    logger.error(f"Invalid periodic conversion value: {conversion_value}. Expected seconds (integer).")
                    # Log error but continue loop, perhaps with a default delay
                    time.sleep(60)
                    continue # Skip current check, wait for next loop iteration
                
                # Reset daily tracker if switching to periodic
                self.last_daily_conversion_check = None

            else:
                logger.warning(f"Unknown conversion type: {conversion_type}. Skipping conversion check.")

            if should_run_conversion:
                logger.info("\n" + "="*50)
                logger.info(f"[*] Server conversion triggered ({conversion_type} schedule).")
                self.conversion_status_label.config(text="Conversion Status: Running...")
                self.master.update_idletasks() # Update GUI immediately
                self._run_conversions()
                self.conversion_status_label.config(text=f"Conversion Status: Last run at {datetime.now().strftime('%H:%M:%S')}")
            
            time.sleep(1) # Check every second

    def _manual_run_conversion(self):
        """Triggers a manual conversion process in a separate thread."""
        if messagebox.askyesno("Confirm Manual Conversion", "Are you sure you want to run conversion now?"):
            logger.info("[*] Manual conversion triggered by user.")
            self.conversion_status_label.config(text="Conversion Status: Manual run initiated...")
            self.master.update_idletasks() # Update GUI immediately

            # Run conversion in a separate thread to keep GUI responsive
            manual_thread = threading.Thread(target=self._run_conversions_threaded, daemon=True)
            manual_thread.start()

    def _run_conversions_threaded(self):
        """Wrapper to run conversions and update status after completion."""
        try:
            self._run_conversions()
        finally:
            self.master.after(0, lambda: self.conversion_status_label.config(text=f"Conversion Status: Manual run completed at {datetime.now().strftime('%H:%M:%S')}"))
            logger.info("[*] Manual conversion process finished.")


    def _run_conversions(self):
        """Performs the actual conversion of .binn files to .png for all clients."""
        logger.info("Starting batch conversion process...")
        total_converted = 0
        try:
            if not os.path.exists(NETWORK_BASE_PATH):
                logger.error(f"NETWORK_BASE_PATH '{NETWORK_BASE_PATH}' does not exist. Cannot perform conversions.")
                messagebox.showerror("Error", f"Network base path not found: {NETWORK_BASE_PATH}")
                return

            # Iterate through all client directories
            for device_id_dir in self._get_found_client_dirs(): # Use helper to get valid client dirs
                client_base_path = os.path.join(NETWORK_BASE_PATH, device_id_dir)
                raw_path = os.path.join(client_base_path)
                converted_path = os.path.join(NETWORK_CONVERTED_PATH, device_id_dir)

                if not os.path.isdir(raw_path):
                    logger.warning(f"Raw directory not found for {device_id_dir}: {raw_path}. Skipping.")
                    continue

                try:
                    os.makedirs(converted_path, exist_ok=True) # Ensure converted folder exists
                except Exception as e:
                    logger.error(f"Failed to create converted directory for {device_id_dir}: {e}. Skipping conversion for this client.")
                    continue

                files_to_convert = [f for f in os.listdir(raw_path) if f.endswith(".binn")]
                if not files_to_convert:
                    logger.info(f"No .binn files found for conversion in {raw_path} for client {device_id_dir}.")
                    continue

                logger.info(f"Converting {len(files_to_convert)} files for client: {device_id_dir}")
                for file_name in files_to_convert:
                    binn_path = os.path.join(raw_path, file_name)
                    json_path = binn_path.replace(".binn", ".json")
                    
                    img_width, img_height = None, None
                    try:
                        if os.path.exists(json_path):
                            with open(json_path, 'r') as f:
                                metadata = json.load(f)
                            img_width = metadata.get("width")
                            img_height = metadata.get("height")
                            if not (isinstance(img_width, int) and isinstance(img_height, int) and img_width > 0 and img_height > 0):
                                logger.warning(f"Invalid dimensions in metadata for {file_name}. Using default 1920x1080.")
                                img_width, img_height = 1920, 1080 # Fallback
                        else:
                            logger.warning(f"No metadata .json file found for {file_name}. Using default 1920x1080.")
                            img_width, img_height = 1920, 1080 # Fallback
                    except (json.JSONDecodeError, FileNotFoundError, KeyError) as e:
                        logger.error(f"Error reading metadata for {file_name}: {e}. Using default 1920x1080.")
                        img_width, img_height = 1920, 1080 # Fallback

                    try:
                        # Extract timestamp and create PNG filename
                        timestamp = file_name.replace("screen_", "").replace(".binn", "")
                        png_name = f"{device_id_dir}_{timestamp}.png"
                        png_path = os.path.join(converted_path, png_name)

                        # Read .binn raw data
                        with open(binn_path, "rb") as f:
                            raw_data = f.read()
                        
                        # Create a PIL Image from raw RGB data using extracted/default dimensions
                        img = Image.frombytes("RGB", (img_width, img_height), raw_data)
                        img.save(png_path)

                        os.remove(binn_path) # Remove original .binn file after successful conversion
                        if os.path.exists(json_path): # Also remove the metadata file
                            os.remove(json_path)
                            
                        total_converted += 1
                        logger.info(f"[✓] Converted {file_name} to {png_name} for {device_id_dir}")

                    except Exception as e:
                        logger.error(f"[!] Failed to convert {file_name} for {device_id_dir}: {str(e)}")
                        traceback.print_exc()
                        continue
        except Exception as e:
            logger.critical(f"[!!!] Fatal error during batch conversion: {str(e)}")
            traceback.print_exc()
        finally:
            logger.info(f"Batch conversion finished. Total converted: {total_converted} files.")

    def _on_closing(self):
        """Handles the window closing event, stopping background threads."""
        if messagebox.askokcancel("Quit", "Do you want to quit the SnapLog Server? This will stop conversions."):
            logger.info("Shutting down SnapLog Server...")
            self.stop_conversion_event.set() # Signal conversion thread to stop
            if self.conversion_thread and self.conversion_thread.is_alive():
                self.conversion_thread.join(timeout=5) # Give it time to finish
            logger.info("SnapLog Server stopped.")
            self.master.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = SnapLogServer(root)
    root.mainloop()
