
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

# Import server-specific configuration
from server_config import (
    NETWORK_BASE_PATH, CLIENT_CONFIG_FILE,
    load_server_config, save_server_config,
    DEFAULT_SERVER_CONVERSION_TIME
)

# Configure logging for the server
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
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
        master.geometry("800x600")

        self.client_configs = {} # Stores all client configurations
        self.server_config = load_server_config() # Load server's own config
        self.conversion_thread = None
        self.stop_conversion_event = threading.Event()
        self.last_conversion_check = None # To prevent multiple conversions in the same minute

        self._create_widgets()
        self._load_all_client_configs()
        self._populate_client_list()
        self._start_conversion_scheduler()

        # Periodically refresh client list and configs
        self.master.after(60000, self._refresh_data) # Refresh every minute

    def _create_widgets(self):
        # Main PanedWindow for resizable sections
        self.paned_window = ttk.PanedWindow(self.master, orient=tk.HORIZONTAL)
        self.paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Left Frame: Client List
        self.client_list_frame = ttk.LabelFrame(self.paned_window, text="Connected Clients")
        self.paned_window.add(self.client_list_frame, weight=1)

        self.client_listbox = tk.Listbox(self.client_list_frame, height=15)
        self.client_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.client_listbox.bind("<<ListboxSelect>>", self._on_client_select)

        self.refresh_button = ttk.Button(self.client_list_frame, text="Refresh Clients", command=self._refresh_data)
        self.refresh_button.pack(pady=5)

        # Right Frame: Configuration Details
        self.config_frame = ttk.LabelFrame(self.paned_window, text="Client Configuration")
        self.paned_window.add(self.config_frame, weight=2)

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

        # Server Conversion Settings (below client settings)
        ttk.Separator(self.config_frame, orient='horizontal').grid(row=6, column=0, columnspan=2, sticky='ew', pady=10)
        ttk.Label(self.config_frame, text="Server Conversion Settings", font=('Arial', 12, 'bold')).grid(row=7, column=0, columnspan=2, pady=5)

        ttk.Label(self.config_frame, text="Conversion Time (HH:MM):").grid(row=8, column=0, sticky=tk.W, padx=5, pady=2)
        self.server_conversion_time_var = tk.StringVar(value=self.server_config["conversion_time"])
        self.server_conversion_time_entry = ttk.Entry(self.config_frame, textvariable=self.server_conversion_time_var)
        self.server_conversion_time_entry.grid(row=8, column=1, sticky=tk.EW, padx=5, pady=2)

        self.save_server_button = ttk.Button(self.config_frame, text="Save Server Settings", command=self._save_server_config)
        self.save_server_button.grid(row=9, column=0, columnspan=2, pady=10)

        # Conversion Status
        self.conversion_status_label = ttk.Label(self.master, text="Conversion Status: Idle", font=('Arial', 10))
        self.conversion_status_label.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=5)

        # Configure column weights for resizing
        self.config_frame.grid_columnconfigure(1, weight=1)

        # Initial state of upload value entry
        self._toggle_upload_value_entry()

    def _toggle_upload_value_entry(self):
        """Enables/disables and updates placeholder for upload_value_entry based on upload_type."""
        if self.upload_type_var.get() == "daily":
            self.upload_value_entry.config(state=tk.NORMAL)
            self.upload_value_entry.delete(0, tk.END)
            # self.upload_value_entry.insert(0, "HH:MM") # Optional placeholder
        else: # periodic
            self.upload_value_entry.config(state=tk.NORMAL)
            self.upload_value_entry.delete(0, tk.END)
            # self.upload_value_entry.insert(0, "Seconds") # Optional placeholder

    def _load_all_client_configs(self):
        """Loads all client configurations from the central JSON file."""
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
        """Populates the client listbox with available device IDs."""
        self.client_listbox.delete(0, tk.END)
        # Scan for existing client directories in NETWORK_BASE_PATH
        found_clients = []
        try:
            if os.path.exists(NETWORK_BASE_PATH):
                for item in os.listdir(NETWORK_BASE_PATH):
                    full_path = os.path.join(NETWORK_BASE_PATH, item)
                    if os.path.isdir(full_path) and item not in ["logs", "converted", os.path.basename(CLIENT_CONFIG_FILE).split('.')[0]]: # Exclude special folders
                        found_clients.append(item)
            else:
                logger.warning(f"Network base path not found: {NETWORK_BASE_PATH}")
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
                self.client_listbox.insert(tk.END, device_id)
        
        # Select the first client if available
        if all_device_ids:
            self.client_listbox.selection_set(0)
            self._on_client_select() # Manually trigger selection update

    def _on_client_select(self, event=None):
        """Loads the selected client's configuration into the input fields."""
        selected_indices = self.client_listbox.curselection()
        if not selected_indices:
            self.selected_client_label.config(text="Selected Client: None")
            self._clear_config_fields()
            return

        selected_client_id = self.client_listbox.get(selected_indices[0])
        self.selected_client_label.config(text=f"Selected Client: {selected_client_id}")

        config = self.client_configs.get(selected_client_id, {})
        
        # Populate fields, using defaults if not present in config
        self.screenshot_interval_var.set(config.get("screenshot_interval", 300))
        self.upload_type_var.set(config.get("upload_type", "daily"))
        self.upload_value_var.set(config.get("upload_value", "09:03"))
        
        self._toggle_upload_value_entry() # Adjust entry state based on type

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

        selected_client_id = self.client_listbox.get(selected_indices[0])

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
            messagebox.showinfo("Success", f"Configuration saved for {selected_client_id}.")
            logger.info(f"Configuration saved for {selected_client_id}: {self.client_configs[selected_client_id]}")

        except ValueError as ve:
            messagebox.showerror("Validation Error", str(ve))
            logger.error(f"Validation error saving client config for {selected_client_id}: {ve}")
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")
            logger.error(f"Unexpected error saving client config for {selected_client_id}: {e}", exc_info=True)

    def _save_server_config(self):
        """Saves the server's conversion time setting."""
        try:
            conversion_time = self.server_conversion_time_var.get()
            # Validate HH:MM format
            datetime.strptime(conversion_time, "%H:%M")

            self.server_config["conversion_time"] = conversion_time
            save_server_config(self.server_config)
            messagebox.showinfo("Success", "Server conversion time saved.")
            logger.info(f"Server conversion time updated to: {conversion_time}")
            self._start_conversion_scheduler() # Restart scheduler with new time
        except ValueError:
            messagebox.showerror("Validation Error", "Conversion time must be in HH:MM format (e.g., 02:00).")
            logger.error(f"Validation error saving server config: Invalid time format '{conversion_time}'")
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
        logger.info(f"Started conversion scheduler for {self.server_config['conversion_time']}.")
        self.conversion_status_label.config(text=f"Conversion Status: Scheduled for {self.server_config['conversion_time']}")

    def _conversion_scheduler_loop(self):
        """Background loop to trigger conversion at the scheduled time."""
        while not self.stop_conversion_event.is_set():
            now = datetime.now()
            target_time_str = self.server_config["conversion_time"]
            current_time_str = now.strftime("%H:%M")

            if current_time_str == target_time_str and current_time_str != self.last_conversion_check:
                logger.info(f"[*] Conversion time {target_time_str} reached. Starting conversion...")
                self.conversion_status_label.config(text="Conversion Status: Running...")
                self.master.update_idletasks() # Update GUI immediately
                self._run_conversions()
                self.last_conversion_check = current_time_str # Mark as checked for this minute
                self.conversion_status_label.config(text=f"Conversion Status: Last run at {datetime.now().strftime('%H:%M:%S')}")
            elif current_time_str != self.last_conversion_check:
                # Reset last_conversion_check if the minute changes, so it can trigger again next day
                self.last_conversion_check = None

            time.sleep(1) # Check every second

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
            for device_id_dir in os.listdir(NETWORK_BASE_PATH):
                client_base_path = os.path.join(NETWORK_BASE_PATH, device_id_dir)
                raw_path = os.path.join(client_base_path, "raw")
                converted_path = os.path.join(client_base_path, "converted")

                if not os.path.isdir(raw_path):
                    continue # Skip if not a client directory or no raw folder

                os.makedirs(converted_path, exist_ok=True) # Ensure converted folder exists

                files_to_convert = [f for f in os.listdir(raw_path) if f.endswith(".binn")]
                if not files_to_convert:
                    logger.info(f"No .binn files found for conversion in {raw_path}")
                    continue

                logger.info(f"Converting {len(files_to_convert)} files for client: {device_id_dir}")
                for file_name in files_to_convert:
                    binn_path = os.path.join(raw_path, file_name)
                    
                    try:
                        # Extract timestamp and create PNG filename
                        timestamp = file_name.replace("screen_", "").replace(".binn", "")
                        png_name = f"{device_id_dir}_{timestamp}.png"
                        png_path = os.path.join(converted_path, png_name)

                        # Read .binn raw data
                        with open(binn_path, "rb") as f:
                            raw_data = f.read()
                        
                        # Use mss.tools.to_png to convert.
                        # We need monitor dimensions. Since we don't have the client's monitor info here,
                        # we'll assume a common resolution or try to infer.
                        # A better approach would be for the client to store metadata with the .binn file.
                        # For now, let's use a common default or try to get it from the raw data if possible.
                        # mss.tools.to_png expects (width, height) tuple.
                        # If the raw data is just pixel data, we need the dimensions.
                        # The original client code used `sct.monitors[1]`.
                        # Let's assume a standard 1920x1080 for now, or you might need to
                        # store dimensions in the filename or a companion file.
                        # For a robust solution, client should send resolution with each screenshot.
                        
                        # For demonstration, let's assume 1920x1080.
                        # In a real scenario, you'd need the actual resolution.
                        # You could modify the client to embed resolution in the binn file or filename.
                        
                        # Example: If your binn file format was structured to include width/height
                        # For now, let's use a placeholder.
                        # The mss.tools.to_png function expects the raw pixel data and (width, height).
                        # The original client code writes `screenshot.rgb`.
                        # If `screenshot.rgb` is always 1920*1080*3 bytes, then the dimensions are fixed.
                        # Otherwise, you need to store them.
                        
                        # Let's assume a fixed resolution for now, or you'll need to update client to send metadata.
                        # For example, if all clients are 1920x1080:
                        img_width = 1920
                        img_height = 1080

                        # Check if raw_data size matches expected for assumed dimensions
                        # RGB data: width * height * 3 bytes
                        if len(raw_data) != img_width * img_height * 3:
                            logger.warning(f"Raw data size mismatch for {file_name}. Expected {img_width * img_height * 3} bytes, got {len(raw_data)}. Attempting conversion with assumed dimensions.")
                            # You might need more robust error handling or metadata here.
                            # For simplicity, if the size doesn't match, this conversion might fail or produce garbage.
                            # A better approach: client saves metadata (width, height) alongside .binn or in filename.
                            # For now, we'll proceed with assumed dimensions.

                        # Create a PIL Image from raw RGB data
                        img = Image.frombytes("RGB", (img_width, img_height), raw_data)
                        img.save(png_path)

                        os.remove(binn_path) # Remove original .binn file after successful conversion
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


if __name__ == "__main__":
    root = tk.Tk()
    app = SnapLogServer(root)
    root.mainloop()
