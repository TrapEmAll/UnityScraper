"""
Enhanced UnityScraper GUI with HTTPS Support
Modern Tkinter interface with improved features
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import queue
import logging
from pathlib import Path
from typing import Optional
import sys

# Import the main scraper (assumes main.py is in same directory)
try:
    from main import UnityScraper, Config
except ImportError:
    print("Error: main.py not found. Please ensure main.py is in the same directory.")
    sys.exit(1)


class QueueHandler(logging.Handler):
    """Logging handler that puts log records into a queue"""
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
    
    def emit(self, record):
        self.log_queue.put(self.format(record))


class UnityScraperGUI:
    """Enhanced GUI for UnityScraper"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("UnityScraper - Enhanced Edition")
        self.root.geometry("900x700")
        self.root.resizable(True, True)
        
        # State variables
        self.config = Config()
        self.scraper: Optional[UnityScraper] = None
        self.is_running = False
        self.stop_requested = False
        self.log_queue = queue.Queue()
        
        # Setup GUI
        self.setup_styles()
        self.create_widgets()
        self.setup_logging()
        
        # Start log processor
        self.process_log_queue()
    
    def setup_styles(self):
        """Configure ttk styles"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configure colors
        style.configure('TFrame', background='#f0f0f0')
        style.configure('Title.TLabel', font=('Arial', 16, 'bold'), background='#f0f0f0')
        style.configure('Subtitle.TLabel', font=('Arial', 10), background='#f0f0f0')
        style.configure('Success.TLabel', foreground='green', background='#f0f0f0')
        style.configure('Error.TLabel', foreground='red', background='#f0f0f0')
    
    def create_widgets(self):
        """Create all GUI widgets"""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(7, weight=1)
        
        # Title
        title_label = ttk.Label(main_frame, text="UnityScraper Enhanced", style='Title.TLabel')
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 5))
        
        subtitle_label = ttk.Label(
            main_frame, 
            text="Download Xbox 360 Title Updates & Covers with HTTPS Support",
            style='Subtitle.TLabel'
        )
        subtitle_label.grid(row=1, column=0, columnspan=3, pady=(0, 15))
        
        # TitleIDs input
        ttk.Label(main_frame, text="TitleIDs:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.titleids_entry = ttk.Entry(main_frame, width=50)
        self.titleids_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        self.titleids_entry.insert(0, "555308C5")
        
        ttk.Label(
            main_frame, 
            text="Comma-separated (e.g., 555308C5,00000155)"
        ).grid(row=3, column=1, sticky=tk.W, padx=5)
        
        # Output directory
        ttk.Label(main_frame, text="Output Dir:").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.output_entry = ttk.Entry(main_frame, width=50)
        self.output_entry.grid(row=4, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        self.output_entry.insert(0, str(self.config.output_dir))
        
        browse_btn = ttk.Button(main_frame, text="Browse", command=self.browse_output)
        browse_btn.grid(row=4, column=2, pady=5, padx=5)
        
        # Settings frame
        settings_frame = ttk.LabelFrame(main_frame, text="Settings", padding="10")
        settings_frame.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        settings_frame.columnconfigure(1, weight=1)
        settings_frame.columnconfigure(3, weight=1)
        
        # Workers
        ttk.Label(settings_frame, text="Workers:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.workers_var = tk.IntVar(value=self.config.workers)
        workers_spinbox = ttk.Spinbox(
            settings_frame, 
            from_=1, 
            to=16, 
            textvariable=self.workers_var, 
            width=10
        )
        workers_spinbox.grid(row=0, column=1, sticky=tk.W, padx=5)
        
        # Rate limit
        ttk.Label(settings_frame, text="Rate Limit (s):").grid(row=0, column=2, sticky=tk.W, padx=5)
        self.rate_var = tk.DoubleVar(value=self.config.rate_limit)
        rate_spinbox = ttk.Spinbox(
            settings_frame, 
            from_=0.1, 
            to=5.0, 
            increment=0.1,
            textvariable=self.rate_var, 
            width=10
        )
        rate_spinbox.grid(row=0, column=3, sticky=tk.W, padx=5)
        
        # Timeout
        ttk.Label(settings_frame, text="Timeout (s):").grid(row=1, column=0, sticky=tk.W, padx=5)
        self.timeout_var = tk.IntVar(value=self.config.timeout)
        timeout_spinbox = ttk.Spinbox(
            settings_frame, 
            from_=5, 
            to=120, 
            textvariable=self.timeout_var, 
            width=10
        )
        timeout_spinbox.grid(row=1, column=1, sticky=tk.W, padx=5)
        
        # Max retries
        ttk.Label(settings_frame, text="Max Retries:").grid(row=1, column=2, sticky=tk.W, padx=5)
        self.retries_var = tk.IntVar(value=self.config.max_retries)
        retries_spinbox = ttk.Spinbox(
            settings_frame, 
            from_=1, 
            to=10, 
            textvariable=self.retries_var, 
            width=10
        )
        retries_spinbox.grid(row=1, column=3, sticky=tk.W, padx=5)
        
        # Protocol options
        protocol_frame = ttk.Frame(settings_frame)
        protocol_frame.grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=5)
        
        self.https_var = tk.BooleanVar(value=self.config.use_https)
        https_check = ttk.Checkbutton(
            protocol_frame, 
            text="Use HTTPS (with HTTP fallback)", 
            variable=self.https_var
        )
        https_check.grid(row=0, column=0, sticky=tk.W)
        
        # Connection status
        self.status_label = ttk.Label(settings_frame, text="Not connected", style='Subtitle.TLabel')
        self.status_label.grid(row=3, column=0, columnspan=4, sticky=tk.W, pady=5)
        
        # Control buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=6, column=0, columnspan=3, pady=10)
        
        self.start_btn = ttk.Button(
            button_frame, 
            text="Start Download", 
            command=self.start_download,
            width=15
        )
        self.start_btn.grid(row=0, column=0, padx=5)
        
        self.stop_btn = ttk.Button(
            button_frame, 
            text="Stop", 
            command=self.stop_download,
            state=tk.DISABLED,
            width=15
        )
        self.stop_btn.grid(row=0, column=1, padx=5)
        
        test_btn = ttk.Button(
            button_frame, 
            text="Test Connection", 
            command=self.test_connection,
            width=15
        )
        test_btn.grid(row=0, column=2, padx=5)
        
        config_btn = ttk.Button(
            button_frame, 
            text="Save Config", 
            command=self.save_config,
            width=15
        )
        config_btn.grid(row=0, column=3, padx=5)
        
        load_btn = ttk.Button(
            button_frame, 
            text="Load Config", 
            command=self.load_config,
            width=15
        )
        load_btn.grid(row=0, column=4, padx=5)
        
        # Progress bar
        self.progress = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress.grid(row=7, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        
        # Log output
        log_frame = ttk.LabelFrame(main_frame, text="Log Output", padding="5")
        log_frame.grid(row=8, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(
            log_frame, 
            height=15, 
            wrap=tk.WORD,
            font=('Consolas', 9)
        )
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Clear log button
        clear_btn = ttk.Button(log_frame, text="Clear Log", command=self.clear_log)
        clear_btn.grid(row=1, column=0, pady=5)
    
    def setup_logging(self):
        """Setup logging to GUI"""
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        
        # Remove existing handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # Add queue handler
        queue_handler = QueueHandler(self.log_queue)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', 
                                     datefmt='%H:%M:%S')
        queue_handler.setFormatter(formatter)
        logger.addHandler(queue_handler)
        
        # Also add file handler
        file_handler = logging.FileHandler('unityscraper_gui.log')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    def process_log_queue(self):
        """Process log messages from queue and display in GUI"""
        while True:
            try:
                message = self.log_queue.get_nowait()
                self.log_text.insert(tk.END, message + '\n')
                self.log_text.see(tk.END)
            except queue.Empty:
                break
        
        self.root.after(100, self.process_log_queue)
    
    def browse_output(self):
        """Browse for output directory"""
        directory = filedialog.askdirectory(initialdir=self.output_entry.get())
        if directory:
            self.output_entry.delete(0, tk.END)
            self.output_entry.insert(0, directory)
    
    def update_config_from_gui(self):
        """Update config object from GUI values"""
        self.config.output_dir = Path(self.output_entry.get())
        self.config.workers = self.workers_var.get()
        self.config.rate_limit = self.rate_var.get()
        self.config.timeout = self.timeout_var.get()
        self.config.max_retries = self.retries_var.get()
        self.config.use_https = self.https_var.get()
        
        if not self.config.use_https:
            self.config.base_url = self.config.http_fallback_url
    
    def test_connection(self):
        """Test connection to XboxUnity"""
        self.update_config_from_gui()
        
        def test():
            try:
                self.status_label.config(text="Testing connection...", style='Subtitle.TLabel')
                scraper = UnityScraper(self.config)
                protocol = "HTTPS" if self.config.use_https else "HTTP"
                self.status_label.config(
                    text=f"✓ Connected via {protocol}", 
                    style='Success.TLabel'
                )
                logging.info(f"Connection test successful ({protocol})")
            except Exception as e:
                self.status_label.config(
                    text=f"✗ Connection failed: {str(e)}", 
                    style='Error.TLabel'
                )
                logging.error(f"Connection test failed: {e}")
        
        thread = threading.Thread(target=test, daemon=True)
        thread.start()
    
    def save_config(self):
        """Save configuration to file"""
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="config.json"
        )
        
        if filename:
            self.update_config_from_gui()
            try:
                self.config.save_to_file(filename)
                messagebox.showinfo("Success", f"Configuration saved to {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save config: {e}")
    
    def load_config(self):
        """Load configuration from file"""
        filename = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                self.config = Config(filename)
                
                # Update GUI from loaded config
                self.output_entry.delete(0, tk.END)
                self.output_entry.insert(0, str(self.config.output_dir))
                self.workers_var.set(self.config.workers)
                self.rate_var.set(self.config.rate_limit)
                self.timeout_var.set(self.config.timeout)
                self.retries_var.set(self.config.max_retries)
                self.https_var.set(self.config.use_https)
                
                messagebox.showinfo("Success", f"Configuration loaded from {filename}")
                logging.info(f"Loaded configuration from {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load config: {e}")
    
    def clear_log(self):
        """Clear log output"""
        self.log_text.delete(1.0, tk.END)
    
    def start_download(self):
        """Start download process"""
        titleids_input = self.titleids_entry.get().strip()
        if not titleids_input:
            messagebox.showwarning("Input Required", "Please enter at least one TitleID")
            return
        
        titleids = [tid.strip() for tid in titleids_input.split(',')]
        
        self.update_config_from_gui()
        self.is_running = True
        self.stop_requested = False
        
        # Update UI state
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.progress.start(10)
        
        # Start download in separate thread
        thread = threading.Thread(
            target=self.download_thread, 
            args=(titleids,), 
            daemon=True
        )
        thread.start()
    
    def download_thread(self, titleids):
        """Download thread function"""
        try:
            self.scraper = UnityScraper(self.config)
            
            for titleid in titleids:
                if self.stop_requested:
                    logging.info("Download stopped by user")
                    break
                
                self.scraper.process_titleid(titleid)
            
            if not self.stop_requested:
                logging.info("All downloads completed!")
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success", 
                    "All downloads completed successfully!"
                ))
        
        except Exception as e:
            logging.error(f"Download error: {e}")
            self.root.after(0, lambda: messagebox.showerror(
                "Error", 
                f"Download failed: {str(e)}"
            ))
        
        finally:
            self.root.after(0, self.download_finished)
    
    def stop_download(self):
        """Stop download process"""
        self.stop_requested = True
        logging.warning("Stop requested - finishing current operations...")
    
    def download_finished(self):
        """Cleanup after download finishes"""
        self.is_running = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.progress.stop()


def main():
    root = tk.Tk()
    app = UnityScraperGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()