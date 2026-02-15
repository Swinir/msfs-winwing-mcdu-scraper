"""
GUI application for MSFS A330 WinWing MCDU Scraper
Provides window selection, log viewing, and control interface
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import logging
import asyncio
import threading
import sys
from pathlib import Path
from typing import Optional
import queue

# Add src to path (handle both normal and PyInstaller frozen execution)
if getattr(sys, 'frozen', False):
    # Running as PyInstaller bundle: modules are in the same temp directory
    sys.path.insert(0, sys._MEIPASS)
else:
    sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from window_capture import WindowCapture, WINDOWS_AVAILABLE
from screen_capture import ScreenCapture
from mcdu_parser import MCDUParser
from mobiflight_client import MobiFlightClient
from region_selector import RegionSelectorDialog


class QueueHandler(logging.Handler):
    """Custom logging handler that puts log messages into a queue"""
    
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
    
    def emit(self, record):
        self.log_queue.put(self.format(record))


class MCDUScraperGUI:
    """GUI for MSFS MCDU Scraper with window selection and log viewing"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("MSFS WinWing MCDU Scraper")
        self.root.geometry("900x700")
        
        # State
        self.running = False
        self.capture = None
        self.clients = {}
        self.scraper_thread = None
        self.loop = None
        
        # Logging queue
        self.log_queue = queue.Queue()
        
        # Setup logging
        self.setup_logging()
        
        # Create UI
        self.create_widgets()
        
        # Start log updater
        self.update_logs()
        
        # Load config
        try:
            self.config = Config()
            self.log("Configuration loaded successfully")
        except Exception as e:
            self.log(f"Warning: Could not load config: {e}", level="WARNING")
            self.config = None
    
    def setup_logging(self):
        """Setup logging to capture to GUI"""
        # Create queue handler
        queue_handler = QueueHandler(self.log_queue)
        queue_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        )
        
        # Add to root logger
        root_logger = logging.getLogger()
        root_logger.addHandler(queue_handler)
        root_logger.setLevel(logging.INFO)
    
    def create_widgets(self):
        """Create GUI widgets"""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(4, weight=1)
        
        # Title
        title_label = ttk.Label(
            main_frame, 
            text="MSFS WinWing MCDU Scraper", 
            font=('Arial', 16, 'bold')
        )
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 10))
        
        # Capture Mode Selection
        mode_frame = ttk.LabelFrame(main_frame, text="Capture Mode", padding="10")
        mode_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        self.capture_mode = tk.StringVar(value="window")
        ttk.Radiobutton(
            mode_frame, 
            text="Window Capture (works when minimized)", 
            variable=self.capture_mode, 
            value="window",
            command=self.on_mode_change
        ).grid(row=0, column=0, sticky=tk.W, padx=5)
        
        ttk.Radiobutton(
            mode_frame, 
            text="Screen Region (from config.yaml)", 
            variable=self.capture_mode, 
            value="region",
            command=self.on_mode_change
        ).grid(row=0, column=1, sticky=tk.W, padx=5)
        
        # Window Selection (for window mode)
        self.window_frame = ttk.LabelFrame(main_frame, text="Window Selection", padding="10")
        self.window_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(self.window_frame, text="Select MCDU Window:").grid(row=0, column=0, sticky=tk.W)
        
        self.window_combo = ttk.Combobox(self.window_frame, width=60, state='readonly')
        self.window_combo.grid(row=0, column=1, padx=5, sticky=(tk.W, tk.E))
        
        ttk.Button(
            self.window_frame, 
            text="Refresh Windows", 
            command=self.refresh_windows
        ).grid(row=0, column=2, padx=5)

        self.show_all_windows_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self.window_frame,
            text="Show all windows",
            variable=self.show_all_windows_var,
            command=self.refresh_windows
        ).grid(row=0, column=3, padx=10)
        
        # Screen area selection button (NEW)
        self.select_area_button = ttk.Button(
            self.window_frame,
            text="Select Screen Area",
            command=self.select_screen_area,
            state='normal'
        )
        self.select_area_button.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
        
        # Crop region info label (NEW)
        self.crop_info_label = ttk.Label(self.window_frame, text="No crop region set", font=('Arial', 8))
        self.crop_info_label.grid(row=1, column=2, padx=5, sticky=tk.W)
        
        self.window_frame.columnconfigure(1, weight=1)
        
        # Store crop region (NEW)
        self.crop_region = None
        
        # Status and Control
        control_frame = ttk.LabelFrame(main_frame, text="Control", padding="10")
        control_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        self.status_label = ttk.Label(control_frame, text="Status: Stopped", font=('Arial', 10, 'bold'))
        self.status_label.grid(row=0, column=0, sticky=tk.W, padx=5)
        
        self.start_button = ttk.Button(
            control_frame, 
            text="Start Scraper", 
            command=self.start_scraper,
            width=15
        )
        self.start_button.grid(row=0, column=1, padx=5)
        
        self.stop_button = ttk.Button(
            control_frame, 
            text="Stop Scraper", 
            command=self.stop_scraper,
            state='disabled',
            width=15
        )
        self.stop_button.grid(row=0, column=2, padx=5)
        
        # Logs
        log_frame = ttk.LabelFrame(main_frame, text="Logs", padding="10")
        log_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=20, width=100)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Clear logs button
        ttk.Button(log_frame, text="Clear Logs", command=self.clear_logs).grid(row=1, column=0, pady=5)
        
        # Refresh windows on startup
        if WINDOWS_AVAILABLE:
            self.refresh_windows()
        else:
            self.log("Window capture not available (Windows only or pywin32 not installed)", level="WARNING")
            self.capture_mode.set("region")
            self.window_combo.config(state='disabled')
    
    def on_mode_change(self):
        """Handle capture mode change"""
        if self.capture_mode.get() == "window":
            self.window_combo.config(state='readonly')
        else:
            self.window_combo.config(state='disabled')
    
    def refresh_windows(self):
        """Refresh list of available windows"""
        if not WINDOWS_AVAILABLE:
            self.log("Window capture not available on this platform", level="WARNING")
            return
        
        try:
            windows = WindowCapture.list_windows()
            
            if self.show_all_windows_var.get():
                filtered_windows = windows
            else:
                # Filter for likely MCDU windows
                msfs_keywords = ['microsoft flight simulator', 'msfs', 'flight simulator', 'mcdu', 'airbus']
                filtered_windows = [
                    (hwnd, title) for hwnd, title in windows
                    if any(keyword in title.lower() for keyword in msfs_keywords) or len(title) < 50
                ]
            
                if not filtered_windows:
                    filtered_windows = windows[:20]  # Show first 20 if no matches
            
            self.window_list = filtered_windows
            window_titles = [f"{title} (HWND: {hwnd})" for hwnd, title in filtered_windows]
            
            self.window_combo['values'] = window_titles
            if window_titles:
                self.window_combo.current(0)
            
            self.log(f"Found {len(windows)} windows, showing {len(filtered_windows)}")
        except Exception as e:
            self.log(f"Error refreshing windows: {e}", level="ERROR")
    
    def select_screen_area(self):
        """Open dialog to visually select screen area from window"""
        if not WINDOWS_AVAILABLE:
            messagebox.showerror("Error", "Window capture not available on this platform")
            return
        
        # Get selected window
        selection = self.window_combo.current()
        if selection < 0:
            messagebox.showerror("Error", "Please select a window first")
            return
        
        try:
            hwnd, title = self.window_list[selection]
            self.log(f"Capturing preview from: {title}")
            
            # Capture window for preview
            temp_capture = WindowCapture(window_handle=hwnd)
            preview_image = temp_capture.capture()
            temp_capture.close()
            
            # Open region selector dialog
            dialog = RegionSelectorDialog(self.root, preview_image, self.crop_region)
            result = dialog.show()
            
            if result:
                self.crop_region = result
                x, y, w, h = result
                self.crop_info_label.config(
                    text=f"Crop: X={x}, Y={y}, W={w}, H={h}",
                    foreground='green'
                )
                self.log(f"Screen area selected: X={x}, Y={y}, Width={w}, Height={h}")
            else:
                self.log("Screen area selection cancelled")
                
        except Exception as e:
            self.log(f"Error selecting screen area: {e}", level="ERROR")
            messagebox.showerror("Error", f"Failed to capture window: {e}")
    
    def start_scraper(self):
        """Start the MCDU scraper"""
        if self.running:
            return
        
        try:
            # Validate configuration
            if not self.config:
                messagebox.showerror("Error", "Configuration not loaded. Please check config.yaml")
                return
            
            # Get capture mode
            mode = self.capture_mode.get()
            
            if mode == "window":
                if not WINDOWS_AVAILABLE:
                    messagebox.showerror("Error", "Window capture not available. Please install pywin32.")
                    return
                
                # Get selected window
                selection = self.window_combo.current()
                if selection < 0:
                    messagebox.showerror("Error", "Please select a window to capture")
                    return
                
                hwnd, title = self.window_list[selection]
                self.log(f"Starting scraper with window: {title}")
                
                # Create window capture with optional crop region
                self.capture = WindowCapture(window_handle=hwnd, crop_region=self.crop_region)
                
                if self.crop_region:
                    x, y, w, h = self.crop_region
                    self.log(f"Using crop region: X={x}, Y={y}, Width={w}, Height={h}")
            else:
                # Use screen region from config
                if not self.config.get_captain_enabled():
                    messagebox.showerror("Error", "Captain MCDU not enabled in config.yaml")
                    return
                
                region = self.config.get_captain_region()
                self.log(f"Starting scraper with screen region: {region}")
                self.capture = ScreenCapture(region)
            
            # Update UI
            self.running = True
            self.start_button.config(state='disabled')
            self.stop_button.config(state='normal')
            self.status_label.config(text="Status: Running", foreground='green')
            
            # Start scraper in background thread
            self.scraper_thread = threading.Thread(target=self.run_scraper, daemon=True)
            self.scraper_thread.start()
            
        except Exception as e:
            self.log(f"Error starting scraper: {e}", level="ERROR")
            messagebox.showerror("Error", f"Failed to start scraper: {e}")
            self.running = False
    
    def stop_scraper(self):
        """Stop the MCDU scraper"""
        if not self.running:
            return
        
        self.log("Stopping scraper...")
        self.running = False
        
        # Update UI
        self.start_button.config(state='normal')
        self.stop_button.config(state='disabled')
        self.status_label.config(text="Status: Stopped", foreground='red')
    
    def run_scraper(self):
        """Run the scraper loop in background thread"""
        try:
            # Create new event loop for this thread
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            # Run async scraper
            self.loop.run_until_complete(self.async_scraper())
        except Exception as e:
            self.log(f"Scraper error: {e}", level="ERROR")
        finally:
            if self.loop:
                self.loop.close()
    
    async def async_scraper(self):
        """Async scraper main loop"""
        try:
            # Initialize MobiFlight client
            client = MobiFlightClient(
                websocket_uri=self.config.get_captain_url(),
                font=self.config.get_font(),
                max_retries=self.config.get_max_retries()
            )
            
            # Start client connection
            asyncio.create_task(client.run())
            
            # Wait for connection
            await client.connected.wait()
            self.log("Connected to WinWing CDU")
            
            # Main capture loop
            fps = self.config.get_capture_fps()
            frame_delay = 1.0 / fps
            
            while self.running:
                frame_start = asyncio.get_event_loop().time()
                
                try:
                    # Capture screen/window
                    img = self.capture.capture()
                    
                    # Parse MCDU grid
                    parser = MCDUParser(
                        img,
                        columns=Config.CDU_COLUMNS,
                        rows=Config.CDU_ROWS
                    )
                    display_data = parser.parse_grid()
                    
                    # Send to WinWing
                    await client.send_display_data(display_data)
                    
                except Exception as e:
                    self.log(f"Frame error: {e}", level="ERROR")
                
                # Maintain target FPS
                frame_elapsed = asyncio.get_event_loop().time() - frame_start
                sleep_time = max(0, frame_delay - frame_elapsed)
                await asyncio.sleep(sleep_time)
            
            # Cleanup
            await client.close()
            self.log("Scraper stopped")
            
        except Exception as e:
            self.log(f"Async scraper error: {e}", level="ERROR")
    
    def log(self, message: str, level: str = "INFO"):
        """Add log message"""
        timestamp = logging.Formatter().formatTime(logging.LogRecord(
            name="GUI", level=0, pathname="", lineno=0,
            msg="", args=(), exc_info=None
        ))
        log_msg = f"{timestamp} - {level} - {message}"
        self.log_queue.put(log_msg)
    
    def update_logs(self):
        """Update log display from queue"""
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log_text.insert(tk.END, message + '\n')
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
        
        # Schedule next update
        self.root.after(100, self.update_logs)
    
    def clear_logs(self):
        """Clear log display"""
        self.log_text.delete(1.0, tk.END)


def main():
    """Main entry point for GUI"""
    root = tk.Tk()
    app = MCDUScraperGUI(root)
    
    # Handle window close
    def on_closing():
        if app.running:
            if messagebox.askokcancel("Quit", "Scraper is running. Do you want to quit?"):
                app.stop_scraper()
                root.destroy()
        else:
            root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
