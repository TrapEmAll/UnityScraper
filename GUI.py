"""
Enhanced UnityScraper GUI
Modern Tkinter interface with improved features and i18n support
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
import threading
import queue
import logging
from pathlib import Path
from typing import Optional
import sys
from datetime import datetime, timedelta

# Import the main scraper (assumes main.py is in same directory)
try:
    from app_paths import (
        CONFIG_PATH,
        GUI_LOG_PATH,
        TITLEIDS_PATH,
        describe_storage,
        ensure_app_dirs,
        ensure_user_titleids_file,
        resource_path,
    )
    from main import UnityScraper, Config
    from i18n import init_translator, get_translator, t
    from updater import VersionChecker
    from queue_manager import DownloadQueue
except ImportError as e:
    print(f"Error: Missing required module: {e}")
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
        self.root.geometry("1100x800")
        self.root.resizable(True, True)
        ensure_app_dirs()
        ensure_user_titleids_file()
        self.set_window_icon()
        
        # Initialize i18n
        init_translator('en')
        
        # State variables
        self.config = Config(str(CONFIG_PATH) if CONFIG_PATH.exists() else None)
        self.scraper: Optional[UnityScraper] = None
        self.is_running = False
        self.stop_requested = False
        self.log_queue = queue.Queue()
        self.download_queue = DownloadQueue()
        self.download_progress = {}
        
        # Setup GUI
        self.setup_styles()
        self.create_widgets()
        self.setup_logging()
        
        # Start log processor
        self.process_log_queue()

    def set_window_icon(self):
        """Apply the bundled UnityScraper icon to the desktop window."""
        icon_path = resource_path("assets", "UnityScraper.png")
        if not icon_path.exists():
            return

        try:
            self.window_icon = tk.PhotoImage(file=str(icon_path))
            self.root.iconphoto(True, self.window_icon)
        except Exception as e:
            logging.warning(f"Unable to load window icon from {icon_path}: {e}")
    
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
            text="Download Xbox 360 Title Updates & Covers over XboxUnity HTTP endpoints",
            style='Subtitle.TLabel'
        )
        subtitle_label.grid(row=1, column=0, columnspan=3, pady=(0, 15))
        
        # TitleIDs input
        ttk.Label(main_frame, text="TitleIDs:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.titleids_entry = ttk.Entry(main_frame, width=50)
        self.titleids_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        self.titleids_entry.insert(0, self.load_saved_titleids_preview())
        
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
        
        # Bandwidth limit
        ttk.Label(settings_frame, text="Bandwidth (KB/s):").grid(row=2, column=0, sticky=tk.W, padx=5)
        self.bandwidth_var = tk.IntVar(value=self.config.bandwidth_limit)
        bandwidth_spinbox = ttk.Spinbox(
            settings_frame,
            from_=0,
            to=10000,
            textvariable=self.bandwidth_var,
            width=10
        )
        bandwidth_spinbox.grid(row=2, column=1, sticky=tk.W, padx=5)
        
        # Protocol options
        protocol_frame = ttk.Frame(settings_frame)
        protocol_frame.grid(row=3, column=0, columnspan=4, sticky=tk.W, pady=5)
        
        self.https_var = tk.BooleanVar(value=self.config.use_https)
        https_check = ttk.Checkbutton(
            protocol_frame, 
            text="XboxUnity HTTP endpoints (required)",
            variable=self.https_var,
            state=tk.DISABLED
        )
        https_check.grid(row=0, column=0, sticky=tk.W)
        
        self.verify_checksum_var = tk.BooleanVar(value=self.config.verify_checksums)
        checksum_check = ttk.Checkbutton(
            protocol_frame,
            text="Verify checksums",
            variable=self.verify_checksum_var
        )
        checksum_check.grid(row=0, column=1, sticky=tk.W, padx=20)
        
        self.dry_run_var = tk.BooleanVar(value=self.config.dry_run)
        dry_run_check = ttk.Checkbutton(
            protocol_frame,
            text="Dry run (no downloads)",
            variable=self.dry_run_var
        )
        dry_run_check.grid(row=0, column=2, sticky=tk.W, padx=20)
        
        # Connection status
        self.status_label = ttk.Label(settings_frame, text="Not connected", style='Subtitle.TLabel')
        self.status_label.grid(row=4, column=0, columnspan=4, sticky=tk.W, pady=5)
        
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
        
        retry_btn = ttk.Button(
            button_frame,
            text="Retry Failed",
            command=self.retry_failed,
            width=15
        )
        retry_btn.grid(row=0, column=3, padx=5)
        
        config_btn = ttk.Button(
            button_frame, 
            text="Save Config", 
            command=self.save_config,
            width=15
        )
        config_btn.grid(row=1, column=0, padx=5)
        
        load_btn = ttk.Button(
            button_frame, 
            text="Load Config", 
            command=self.load_config,
            width=15
        )
        load_btn.grid(row=1, column=1, padx=5)
        
        export_btn = ttk.Button(
            button_frame,
            text="Export DB",
            command=self.export_database,
            width=15
        )
        export_btn.grid(row=1, column=2, padx=5)
        
        stats_btn = ttk.Button(
            button_frame,
            text="Show Stats",
            command=self.show_statistics,
            width=15
        )
        stats_btn.grid(row=1, column=3, padx=5)
        
        # New feature buttons
        integrity_btn = ttk.Button(
            button_frame,
            text="Verify Files",
            command=self.verify_integrity,
            width=15
        )
        integrity_btn.grid(row=2, column=0, padx=5, pady=5)
        
        check_update_btn = ttk.Button(
            button_frame,
            text="Check Updates",
            command=self.check_for_updates,
            width=15
        )
        check_update_btn.grid(row=2, column=1, padx=5, pady=5)
        
        queue_btn = ttk.Button(
            button_frame,
            text="View Queue",
            command=self.show_download_queue,
            width=15
        )
        queue_btn.grid(row=2, column=2, padx=5, pady=5)

        metadata_btn = ttk.Button(
            button_frame,
            text="Collect Metadata",
            command=self.collect_metadata,
            width=15
        )
        metadata_btn.grid(row=3, column=0, padx=5, pady=5)
        
        language_label = ttk.Label(button_frame, text="Language:")
        language_label.grid(row=2, column=3, sticky=tk.W, padx=5)
        
        self.language_var = tk.StringVar(value="en")
        language_combo = ttk.Combobox(
            button_frame,
            textvariable=self.language_var,
            values=["en", "es", "fr", "de", "ja"],
            width=8,
            state='readonly'
        )
        language_combo.grid(row=2, column=3, sticky=tk.E, padx=5)
        language_combo.bind('<<ComboboxSelected>>', self.on_language_change)
        
        # Filters frame
        filter_frame = ttk.LabelFrame(main_frame, text="Filters", padding="10")
        filter_frame.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        filter_frame.columnconfigure(1, weight=1)
        filter_frame.columnconfigure(3, weight=1)
        
        ttk.Label(filter_frame, text="Filter by Status:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.status_filter_var = tk.StringVar(value="all")
        status_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.status_filter_var,
            values=["all", "pending", "downloaded", "failed"],
            width=15,
            state='readonly'
        )
        status_combo.grid(row=0, column=1, sticky=tk.W, padx=5)
        status_combo.bind('<<ComboboxSelected>>', lambda e: self.apply_filters())
        
        ttk.Label(filter_frame, text="Filter by Date:").grid(row=0, column=2, sticky=tk.W, padx=5)
        self.date_filter_var = tk.StringVar(value="any")
        date_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.date_filter_var,
            values=["any", "last_7_days", "last_30_days", "custom"],
            width=15,
            state='readonly'
        )
        date_combo.grid(row=0, column=3, sticky=tk.W, padx=5)
        date_combo.bind('<<ComboboxSelected>>', lambda e: self.apply_filters())
        
        # Filter results display
        self.filter_results_text = ttk.Label(
            filter_frame,
            text="Results: 0 items",
            style='Subtitle.TLabel'
        )
        self.filter_results_text.grid(row=1, column=0, columnspan=4, sticky=tk.W, padx=5, pady=5)
        
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
        file_handler = logging.FileHandler(GUI_LOG_PATH)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        logger.info("UnityScraper desktop storage initialized")
        for line in describe_storage().splitlines():
            logger.info(line)

    def load_saved_titleids_preview(self):
        """Load a short editable TitleID preview from the user's local config."""
        try:
            titleids_path = ensure_user_titleids_file()
            content = titleids_path.read_text(encoding="utf-8").strip()
            if content:
                titleids = [tid.strip() for tid in content.split(",") if tid.strip()]
                return ",".join(titleids[:10])
        except Exception as e:
            logging.warning(f"Unable to load saved TitleIDs from {TITLEIDS_PATH}: {e}")
        return "555308C5"
    
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
        self.config.use_https = False
        self.config.bandwidth_limit = self.bandwidth_var.get()
        self.config.verify_checksums = self.verify_checksum_var.get()
        self.config.dry_run = self.dry_run_var.get()
        
        self.config.base_url = self.config.http_fallback_url
    
    def test_connection(self):
        """Test connection to XboxUnity"""
        self.update_config_from_gui()
        
        def test():
            try:
                self.status_label.config(text="Testing connection...", style='Subtitle.TLabel')
                scraper = UnityScraper(self.config)
                self.status_label.config(
                    text="Connected via HTTP",
                    style='Success.TLabel'
                )
                logging.info("Connection test successful (HTTP)")
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
            initialdir=str(CONFIG_PATH.parent),
            initialfile=CONFIG_PATH.name
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
    
    def retry_failed(self):
        """Retry all failed downloads"""
        self.update_config_from_gui()
        
        def retry():
            try:
                self.scraper = UnityScraper(self.config)
                self.scraper.retry_failed_downloads()
                logging.info("Failed downloads retry completed!")
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success", 
                    "Failed downloads retry completed!"
                ))
            except Exception as e:
                logging.error(f"Retry error: {e}")
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", 
                    f"Retry failed: {str(e)}"
                ))
        
        thread = threading.Thread(target=retry, daemon=True)
        thread.start()
    
    def export_database(self):
        """Export database to JSON or CSV"""
        export_format = tk.simpledialog.askstring(
            "Export Format",
            "Enter format (json or csv):",
            initialvalue="json"
        )
        
        if not export_format:
            return
        
        if export_format.lower() not in ['json', 'csv']:
            messagebox.showerror("Invalid Format", "Please enter 'json' or 'csv'")
            return

        export_format = export_format.lower()
        default_name = f"unityscraper_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{export_format}"
        output_file = filedialog.asksaveasfilename(
            defaultextension=f".{export_format}",
            filetypes=[
                (f"{export_format.upper()} files", f"*.{export_format}"),
                ("All files", "*.*"),
            ],
            initialfile=default_name,
        )
        if not output_file:
            return
        
        self.update_config_from_gui()
        
        def export():
            try:
                self.scraper = UnityScraper(self.config)
                self.scraper.export_database(export_format, output_file)
                logging.info(f"Database exported to {export_format.upper()}")
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success", 
                    f"Database exported successfully!"
                ))
            except Exception as e:
                logging.error(f"Export error: {e}")
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", 
                    f"Export failed: {str(e)}"
                ))
        
        thread = threading.Thread(target=export, daemon=True)
        thread.start()
    
    def show_statistics(self):
        """Show database statistics in a new window"""
        self.update_config_from_gui()
        
        def get_stats():
            try:
                from database import DatabaseManager
                db = DatabaseManager()
                stats = db.get_statistics()
                
                # Display in messagebox
                stats_text = f"""
Database Statistics:

Total TitleIDs: {stats.get('total_titleids', 0)}
Total Covers: {stats.get('total_covers', 0)}
Total Updates: {stats.get('total_updates', 0)}
Downloads Last Week: {stats.get('downloads_last_week', 0)}

Most Scraped:
"""
                for item in stats.get('most_scraped', [])[:5]:
                    stats_text += f"\n  {item.get('titleid')} - {item.get('name', 'Unknown')} ({item.get('scrape_count', 0)}x)"
                
                self.root.after(0, lambda: messagebox.showinfo(
                    "Database Statistics", 
                    stats_text
                ))
            except Exception as e:
                logging.error(f"Stats error: {e}")
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", 
                    f"Failed to get statistics: {str(e)}"
                ))
        
        thread = threading.Thread(target=get_stats, daemon=True)
        thread.start()
    
    def verify_integrity(self):
        """Verify file integrity"""
        self.update_config_from_gui()
        
        def verify():
            try:
                self.scraper = UnityScraper(self.config)
                results = self.scraper.db.verify_file_integrity()
                
                stats_text = f"""File Integrity Check Results:

Total Files Checked: {results['total']}
Verified: {len(results['verified'])}
Corrupted: {len(results['corrupted'])}
Missing: {len(results['missing'])}
"""
                
                if results['corrupted']:
                    stats_text += "\nCorrupted Files:\n"
                    for item in results['corrupted'][:5]:
                        stats_text += f"  - {item['path']}\n"
                    if len(results['corrupted']) > 5:
                        stats_text += f"  ... and {len(results['corrupted']) - 5} more\n"
                
                if results['missing']:
                    stats_text += "\nMissing Files:\n"
                    for item in results['missing'][:5]:
                        stats_text += f"  - {item.get('id', 'unknown')}\n"
                    if len(results['missing']) > 5:
                        stats_text += f"  ... and {len(results['missing']) - 5} more\n"
                
                logging.info("File integrity verification completed")
                self.root.after(0, lambda: messagebox.showinfo(
                    "File Integrity Check",
                    stats_text
                ))
            except Exception as e:
                logging.error(f"Integrity check error: {e}")
                self.root.after(0, lambda: messagebox.showerror(
                    "Error",
                    f"Integrity check failed: {str(e)}"
                ))
        
        thread = threading.Thread(target=verify, daemon=True)
        thread.start()
    
    def check_for_updates(self):
        """Check for application updates"""
        def check():
            try:
                checker = VersionChecker()
                update_info = checker.check_for_updates()
                
                if update_info and update_info.get('new_version'):
                    message = f"""
New Version Available!

Current: Unknown
Latest: {update_info.get('version', 'Unknown')}

Changes:
{update_info.get('changes', 'No changelog available')}

Download: {update_info.get('download_url', 'GitHub')}
"""
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Update Available",
                        message
                    ))
                else:
                    self.root.after(0, lambda: messagebox.showinfo(
                        "No Updates",
                        "You are running the latest version!"
                    ))
            except Exception as e:
                logging.error(f"Update check error: {e}")
                self.root.after(0, lambda: messagebox.showerror(
                    "Error",
                    f"Failed to check for updates: {str(e)}"
                ))
        
        thread = threading.Thread(target=check, daemon=True)
        thread.start()
    
    def show_download_queue(self):
        """Show download queue status"""
        def show_queue():
            try:
                queue_stats = self.download_queue.get_queue_stats()
                
                stats_text = f"""Download Queue Status:

Total Items: {queue_stats['total']}
Queued: {queue_stats['queued']}
Downloading: {queue_stats['downloading']}
Completed: {queue_stats['completed']}
Failed: {queue_stats['failed']}
"""
                logging.info("Queue status displayed")
                self.root.after(0, lambda: messagebox.showinfo(
                    "Download Queue",
                    stats_text
                ))
            except Exception as e:
                logging.error(f"Queue error: {e}")
                self.root.after(0, lambda: messagebox.showerror(
                    "Error",
                    f"Failed to display queue: {str(e)}"
                ))
        
        thread = threading.Thread(target=show_queue, daemon=True)
        thread.start()
    
    def apply_filters(self):
        """Apply status and date filters to database results"""
        status_filter = self.status_filter_var.get()
        date_filter = self.date_filter_var.get()
        
        try:
            from database import DatabaseManager
            db = DatabaseManager()
            
            all_items = []
            with db.get_connection() as conn:
                cursor = conn.cursor()
                status_clause = "" if status_filter == "all" else " WHERE status = ?"
                params = () if status_filter == "all" else (status_filter,)

                cursor.execute(
                    f'SELECT "cover" as type, titleid, status, download_date as date FROM covers{status_clause}',
                    params,
                )
                all_items.extend(dict(row) for row in cursor.fetchall())

                cursor.execute(
                    f'SELECT "update" as type, titleid, status, download_date as date FROM title_updates{status_clause}',
                    params,
                )
                all_items.extend(dict(row) for row in cursor.fetchall())
            
            # Apply date filter
            filtered_items = all_items
            if date_filter != 'any':
                now = datetime.now()
                if date_filter == 'last_7_days':
                    cutoff = now - timedelta(days=7)
                elif date_filter == 'last_30_days':
                    cutoff = now - timedelta(days=30)
                else:
                    cutoff = now
                
                filtered_items = [
                    item for item in all_items
                    if item.get('date') and datetime.fromisoformat(item['date']) >= cutoff
                ]
            
            result_text = f"Results: {len(filtered_items)} items (Status: {status_filter}, Date: {date_filter})"
            self.filter_results_text.config(text=result_text)
            logging.info(result_text)
        
        except Exception as e:
            logging.error(f"Filter error: {e}")
            self.filter_results_text.config(text=f"Filter error: {str(e)}")
    
    def on_language_change(self, event=None):
        """Handle language change"""
        lang = self.language_var.get()
        try:
            init_translator(lang)
            translator = get_translator()
            translator.set_language(lang)
            logging.info(f"Language changed to: {lang}")
            messagebox.showinfo("Language Changed", f"UI language changed to {lang.upper()}")
        except Exception as e:
            logging.error(f"Language change error: {e}")
            messagebox.showerror("Error", f"Failed to change language: {str(e)}")

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

    def collect_metadata(self):
        """Collect metadata without downloading files."""
        titleids_input = self.titleids_entry.get().strip()
        if not titleids_input:
            messagebox.showwarning("Input Required", "Please enter at least one TitleID")
            return

        titleids = [tid.strip() for tid in titleids_input.split(',') if tid.strip()]
        self.update_config_from_gui()
        self.is_running = True
        self.stop_requested = False
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.progress.start(10)

        thread = threading.Thread(
            target=self.metadata_thread,
            args=(titleids,),
            daemon=True,
        )
        thread.start()

    def metadata_thread(self, titleids):
        """Metadata collection thread function."""
        try:
            self.scraper = UnityScraper(self.config)

            for titleid in titleids:
                if self.stop_requested:
                    logging.info("Metadata collection stopped by user")
                    break
                self.scraper.collect_metadata(titleid)

            if not self.stop_requested:
                logging.info("Metadata collection completed!")
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success",
                    "Metadata collection completed successfully!"
                ))
        except Exception as e:
            logging.error(f"Metadata collection error: {e}")
            self.root.after(0, lambda: messagebox.showerror(
                "Error",
                f"Metadata collection failed: {str(e)}"
            ))
        finally:
            self.root.after(0, self.download_finished)
    
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
