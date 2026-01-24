"""
REST API Server for UnityScraper
Expose scraper functionality via HTTP endpoints
"""

import logging
import json
import threading
from typing import Optional, Dict, Any, TYPE_CHECKING
from flask import Flask, request, jsonify
from flask_cors import CORS
from pathlib import Path

if TYPE_CHECKING:
    from main import UnityScraper

logger = logging.getLogger(__name__)


class UnityScraperAPI:
    """REST API wrapper for UnityScraper"""
    
    def __init__(self, scraper: Optional['UnityScraper'] = None, port: int = 8000, host: str = "127.0.0.1"):
        self.app = Flask(__name__)
        CORS(self.app)  # Enable CORS
        
        self.scraper: Optional['UnityScraper'] = scraper
        self.port = port
        self.host = host
        self.running = False
        
        self._register_routes()
    
    def _register_routes(self):
        """Register all API routes"""
        
        @self.app.route('/api/health', methods=['GET'])
        def health():
            """Health check endpoint"""
            return jsonify({
                'status': 'healthy',
                'version': '1.1.0',
                'scraper_loaded': self.scraper is not None
            })
        
        @self.app.route('/api/titleids', methods=['GET'])
        def get_titleids():
            """Get all TitleIDs in database"""
            try:
                if not self.scraper:
                    return jsonify({'error': 'Scraper not initialized'}), 400
                titleids = self.scraper.db.search_titleids('')
                return jsonify({'titleids': titleids})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/titleid/<titleid>', methods=['GET'])
        def get_titleid_info(titleid):
            """Get info for specific TitleID"""
            try:
                if not self.scraper:
                    return jsonify({'error': 'Scraper not initialized'}), 400
                info = self.scraper.db.get_titleid_info(titleid)
                if info:
                    return jsonify(info)
                return jsonify({'error': 'TitleID not found'}), 404
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/search', methods=['GET'])
        def search():
            """Search TitleIDs"""
            query = request.args.get('q', '')
            try:
                if not self.scraper:
                    return jsonify({'error': 'Scraper not initialized'}), 400
                results = self.scraper.db.search_titleids(query)
                return jsonify({'results': results, 'count': len(results)})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/metadata/<titleid>', methods=['POST'])
        def collect_metadata(titleid):
            """Collect metadata for TitleID"""
            try:
                if not self.scraper:
                    return jsonify({'error': 'Scraper not initialized'}), 400
                success = self.scraper.collect_metadata(titleid)
                return jsonify({
                    'success': success,
                    'titleid': titleid,
                    'message': 'Metadata collected' if success else 'Failed to collect metadata'
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/download/<titleid>', methods=['POST'])
        def download_titleid(titleid):
            """Download content for TitleID"""
            try:
                if not self.scraper:
                    return jsonify({'error': 'Scraper not initialized'}), 400
                success = self.scraper.process_titleid(titleid)
                return jsonify({
                    'success': success,
                    'titleid': titleid,
                    'message': 'Download completed' if success else 'Download failed'
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/statistics', methods=['GET'])
        def get_stats():
            """Get database statistics"""
            try:
                if not self.scraper:
                    return jsonify({'error': 'Scraper not initialized'}), 400
                stats = self.scraper.db.get_statistics()
                return jsonify(stats)
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/failed-items', methods=['GET'])
        def get_failed_items():
            """Get all failed downloads"""
            titleid = request.args.get('titleid')
            try:
                if not self.scraper:
                    return jsonify({'error': 'Scraper not initialized'}), 400
                items = self.scraper.db.get_failed_items(titleid)
                return jsonify({'failed_items': items, 'count': len(items)})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/retry-failed', methods=['POST'])
        def retry_failed():
            """Retry failed downloads"""
            titleid = request.args.get('titleid')
            try:
                if not self.scraper:
                    return jsonify({'error': 'Scraper not initialized'}), 400
                self.scraper.retry_failed_downloads(titleid)
                return jsonify({
                    'success': True,
                    'message': 'Retry process started'
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/verify-integrity', methods=['GET'])
        def verify_integrity():
            """Verify file integrity"""
            titleid = request.args.get('titleid')
            try:
                if not self.scraper:
                    return jsonify({'error': 'Scraper not initialized'}), 400
                results = self.scraper.db.verify_file_integrity(titleid)
                return jsonify(results)
            except Exception as e:
                return jsonify({'error': str(e)}), 500
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/export', methods=['GET'])
        def export():
            """Export database"""
            format = request.args.get('format', 'json')
            try:
                if not self.scraper:
                    return jsonify({'error': 'Scraper not initialized'}), 400
                filename = f"export_{format}.{format}"
                self.scraper.export_database(format, filename)
                return jsonify({
                    'success': True,
                    'filename': filename,
                    'message': f'Database exported as {format.upper()}'
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/config', methods=['GET'])
        def get_config():
            """Get current configuration"""
            try:
                if not self.scraper:
                    return jsonify({'error': 'Scraper not initialized'}), 400
                config = {
                    'workers': self.scraper.config.workers,
                    'rate_limit': self.scraper.config.rate_limit,
                    'timeout': self.scraper.config.timeout,
                    'bandwidth_limit': self.scraper.config.bandwidth_limit,
                    'use_https': self.scraper.config.use_https,
                    'verify_checksums': self.scraper.config.verify_checksums,
                }
                return jsonify(config)
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/config', methods=['POST'])
        def update_config():
            """Update configuration"""
            try:
                if not self.scraper:
                    return jsonify({'error': 'Scraper not initialized'}), 400
                data = request.get_json()
                for key, value in data.items():
                    if hasattr(self.scraper.config, key):
                        setattr(self.scraper.config, key, value)
                return jsonify({
                    'success': True,
                    'message': 'Configuration updated'
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
    
    def run(self, debug: bool = False):
        """Start API server"""
        self.running = True
        logger.info(f"Starting API server on {self.host}:{self.port}")
        self.app.run(host=self.host, port=self.port, debug=debug, use_reloader=False)
    
    def run_in_thread(self, debug: bool = False):
        """Run API server in background thread"""
        thread = threading.Thread(target=self.run, args=(debug,), daemon=True)
        thread.start()
        logger.info(f"API server started in background thread")
        return thread
    
    @staticmethod
    def example_client():
        """Example client code"""
        import requests
        
        BASE_URL = "http://127.0.0.1:8000/api"
        
        # Health check
        response = requests.get(f"{BASE_URL}/health")
        print("Health:", response.json())
        
        # Get statistics
        response = requests.get(f"{BASE_URL}/statistics")
        print("Statistics:", response.json())
        
        # Collect metadata
        response = requests.post(f"{BASE_URL}/metadata/555308C5")
        print("Metadata collection:", response.json())
        
        # Get TitleID info
        response = requests.get(f"{BASE_URL}/titleid/555308C5")
        print("TitleID info:", response.json())
        
        # Search
        response = requests.get(f"{BASE_URL}/search?q=test")
        print("Search results:", response.json())


# Example usage
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    # Start API server (requires scraper instance)
    # from main import UnityScraper, Config
    # 
    # config = Config()
    # scraper = UnityScraper(config)
    # api = UnityScraperAPI(scraper, port=8000)
    # api.run(debug=True)
    
    print("API server module loaded. Import and use UnityScraperAPI class.")
    print("\nExample:")
    print("  from api import UnityScraperAPI")
    print("  from main import UnityScraper, Config")
    print("  scraper = UnityScraper(Config())")
    print("  api = UnityScraperAPI(scraper)")
    print("  api.run_in_thread()")
