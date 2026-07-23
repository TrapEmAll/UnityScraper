"""
Internationalization (i18n) module for UnityScraper GUI
Supports multiple languages with easy extensibility
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Supported languages
SUPPORTED_LANGUAGES = ['en', 'es', 'fr', 'de', 'ja']

# Translation strings
TRANSLATIONS = {
    'en': {
        'title': 'UnityScraper - Enhanced Edition',
        'titleids': 'TitleIDs:',
        'titleids_hint': 'Comma-separated (e.g., 555308C5,00000155)',
        'output_dir': 'Output Dir:',
        'browse': 'Browse',
        'settings': 'Settings',
        'workers': 'Workers:',
        'rate_limit': 'Rate Limit (s):',
        'timeout': 'Timeout (s):',
        'max_retries': 'Max Retries:',
        'bandwidth': 'Bandwidth (KB/s):',
        'use_https': 'XboxUnity HTTP endpoints (required)',
        'verify_checksums': 'Verify checksums',
        'dry_run': 'Dry run (no downloads)',
        'not_connected': 'Not connected',
        'start_download': 'Start Download',
        'stop': 'Stop',
        'test_connection': 'Test Connection',
        'retry_failed': 'Retry Failed',
        'save_config': 'Save Config',
        'load_config': 'Load Config',
        'export_db': 'Export DB',
        'show_stats': 'Show Stats',
        'clear_log': 'Clear Log',
        'log_output': 'Log Output',
        'status_testing': 'Testing connection...',
        'status_connected_https': 'Connected via HTTP',
        'status_connected_http': '✓ Connected via HTTP',
        'status_failed': '✗ Connection failed: {}',
        'error_no_titleids': 'Please enter at least one TitleID',
        'success_config_saved': 'Configuration saved',
        'error_config_save': 'Failed to save config: {}',
        'success_config_loaded': 'Configuration loaded',
        'error_config_load': 'Failed to load config: {}',
        'success_retry_completed': 'Failed downloads retry completed!',
        'error_retry_failed': 'Retry failed: {}',
        'success_export': 'Database exported successfully!',
        'error_export': 'Export failed: {}',
        'stats_title': 'Database Statistics',
        'stats_titleids': 'Total TitleIDs: {}',
        'stats_covers': 'Total Covers: {}',
        'stats_updates': 'Total Updates: {}',
        'stats_last_week': 'Downloads Last Week: {}',
        'stats_most_scraped': 'Most Scraped:',
        'verify_integrity': 'Verify file integrity',
        'download_speed': 'Speed: {} MB/s',
        'filter_status': 'Filter by Status:',
        'filter_date': 'Filter by Date:',
        'all': 'All',
        'pending': 'Pending',
        'downloaded': 'Downloaded',
        'failed': 'Failed',
    },
    'es': {
        'title': 'UnityScraper - Edición Mejorada',
        'titleids': 'IDs de Título:',
        'titleids_hint': 'Separados por comas (ej., 555308C5,00000155)',
        'output_dir': 'Directorio de Salida:',
        'browse': 'Examinar',
        'settings': 'Configuración',
        'workers': 'Trabajadores:',
        'rate_limit': 'Límite de Velocidad (s):',
        'timeout': 'Tiempo de Espera (s):',
        'max_retries': 'Reintentos Máximos:',
        'bandwidth': 'Ancho de Banda (KB/s):',
        'use_https': 'XboxUnity HTTP endpoints (required)',
        'verify_checksums': 'Verificar sumas de comprobación',
        'dry_run': 'Ejecución de prueba (sin descargas)',
        'not_connected': 'No conectado',
        'start_download': 'Iniciar Descarga',
        'stop': 'Detener',
        'test_connection': 'Probar Conexión',
        'retry_failed': 'Reintentar Fallos',
        'save_config': 'Guardar Configuración',
        'load_config': 'Cargar Configuración',
        'export_db': 'Exportar BD',
        'show_stats': 'Mostrar Estadísticas',
        'clear_log': 'Limpiar Registro',
        'log_output': 'Salida de Registro',
        'status_testing': 'Probando conexión...',
        'status_connected_https': 'Connected via HTTP',
        'status_connected_http': '✓ Conectado vía HTTP',
        'status_failed': '✗ Conexión fallida: {}',
        'error_no_titleids': 'Ingrese al menos un ID de Título',
        'success_config_saved': 'Configuración guardada',
        'error_config_save': 'Error al guardar configuración: {}',
        'success_config_loaded': 'Configuración cargada',
        'error_config_load': 'Error al cargar configuración: {}',
        'success_retry_completed': '¡Reintentos de descargas fallidas completados!',
        'error_retry_failed': 'Reintento fallido: {}',
        'success_export': '¡Base de datos exportada correctamente!',
        'error_export': 'Error en exportación: {}',
        'stats_title': 'Estadísticas de la Base de Datos',
        'verify_integrity': 'Verificar integridad de archivos',
        'download_speed': 'Velocidad: {} MB/s',
        'filter_status': 'Filtrar por Estado:',
        'filter_date': 'Filtrar por Fecha:',
    },
    'fr': {
        'title': 'UnityScraper - Édition Améliorée',
        'titleids': 'IDs de Titre:',
        'titleids_hint': 'Séparés par des virgules (ex., 555308C5,00000155)',
        'output_dir': 'Répertoire de Sortie:',
        'browse': 'Parcourir',
        'settings': 'Paramètres',
        'workers': 'Travailleurs:',
        'rate_limit': 'Limite de Débit (s):',
        'timeout': 'Délai d\'Attente (s):',
        'max_retries': 'Tentatives Maximales:',
        'bandwidth': 'Largeur de Bande (KB/s):',
        'use_https': 'XboxUnity HTTP endpoints (required)',
        'verify_checksums': 'Vérifier les sommes de contrôle',
        'dry_run': 'Essai (sans téléchargements)',
        'not_connected': 'Non connecté',
        'start_download': 'Démarrer le Téléchargement',
        'stop': 'Arrêter',
        'test_connection': 'Tester la Connexion',
        'retry_failed': 'Réessayer les Échecs',
        'save_config': 'Enregistrer la Configuration',
        'load_config': 'Charger la Configuration',
        'export_db': 'Exporter BD',
        'show_stats': 'Afficher les Statistiques',
        'clear_log': 'Effacer le Journal',
        'log_output': 'Sortie du Journal',
        'status_testing': 'Test de connexion...',
        'status_connected_https': 'Connected via HTTP',
        'status_connected_http': '✓ Connecté via HTTP',
        'status_failed': '✗ Connexion échouée: {}',
        'error_no_titleids': 'Veuillez entrer au moins un ID de Titre',
        'verify_integrity': 'Vérifier l\'intégrité des fichiers',
        'download_speed': 'Vitesse: {} MB/s',
        'filter_status': 'Filtrer par État:',
        'filter_date': 'Filtrer par Date:',
    },
    'de': {
        'title': 'UnityScraper - Verbesserte Edition',
        'titleids': 'Titel-IDs:',
        'titleids_hint': 'Kommagetrennt (z.B. 555308C5,00000155)',
        'output_dir': 'Ausgabeverzeichnis:',
        'browse': 'Durchsuchen',
        'settings': 'Einstellungen',
        'workers': 'Worker:',
        'rate_limit': 'Geschwindigkeitsbegrenzung (s):',
        'timeout': 'Zeitüberschreitung (s):',
        'max_retries': 'Maximale Versuche:',
        'bandwidth': 'Bandbreite (KB/s):',
        'use_https': 'XboxUnity HTTP endpoints (required)',
        'verify_checksums': 'Checksummen überprüfen',
        'dry_run': 'Testlauf (keine Downloads)',
        'not_connected': 'Nicht verbunden',
        'start_download': 'Download starten',
        'stop': 'Stopp',
        'test_connection': 'Verbindung testen',
        'retry_failed': 'Fehler erneut versuchen',
        'save_config': 'Konfiguration speichern',
        'load_config': 'Konfiguration laden',
        'export_db': 'DB exportieren',
        'show_stats': 'Statistiken anzeigen',
        'clear_log': 'Protokoll löschen',
        'log_output': 'Protokollausgabe',
        'verify_integrity': 'Dateiintegrität überprüfen',
        'download_speed': 'Geschwindigkeit: {} MB/s',
        'filter_status': 'Nach Status filtern:',
        'filter_date': 'Nach Datum filtern:',
    },
    'ja': {
        'title': 'UnityScraper - 拡張版',
        'titleids': 'タイトルID:',
        'titleids_hint': 'カンマ区切り (例: 555308C5,00000155)',
        'output_dir': '出力ディレクトリ:',
        'browse': '参照',
        'settings': '設定',
        'workers': 'ワーカー:',
        'rate_limit': 'レート制限 (s):',
        'timeout': 'タイムアウト (s):',
        'max_retries': '最大再試行:',
        'bandwidth': '帯域幅 (KB/s):',
        'use_https': 'XboxUnity HTTP endpoints (required)',
        'verify_checksums': 'チェックサムを確認',
        'dry_run': 'ドライラン (ダウンロードなし)',
        'not_connected': '未接続',
        'start_download': 'ダウンロード開始',
        'stop': '停止',
        'test_connection': '接続テスト',
        'retry_failed': '失敗を再試行',
        'save_config': '設定を保存',
        'load_config': '設定を読み込む',
        'export_db': 'DB をエクスポート',
        'show_stats': '統計を表示',
        'clear_log': 'ログをクリア',
        'log_output': 'ログ出力',
        'verify_integrity': 'ファイルの整合性を確認',
        'download_speed': '速度: {} MB/s',
        'filter_status': 'ステータスでフィルタ:',
        'filter_date': '日付でフィルタ:',
    }
}


class Translator:
    """Language translator for GUI"""
    
    def __init__(self, language: str = 'en'):
        if language not in SUPPORTED_LANGUAGES:
            logger.warning(f"Language '{language}' not supported, using English")
            language = 'en'
        self.language = language
        self.strings = TRANSLATIONS.get(language, TRANSLATIONS['en'])
    
    def get(self, key: str, *args) -> str:
        """Get translated string with optional formatting"""
        text = self.strings.get(key, key)
        if args:
            return text.format(*args)
        return text
    
    def set_language(self, language: str):
        """Change language"""
        if language not in SUPPORTED_LANGUAGES:
            logger.warning(f"Language '{language}' not supported")
            return False
        self.language = language
        self.strings = TRANSLATIONS.get(language, TRANSLATIONS['en'])
        return True
    
    @staticmethod
    def get_supported_languages() -> list:
        """Get list of supported languages"""
        return SUPPORTED_LANGUAGES


# Global translator instance
_translator: Optional[Translator] = None


def init_translator(language: str = 'en') -> Translator:
    """Initialize global translator"""
    global _translator
    _translator = Translator(language)
    return _translator


def get_translator() -> Translator:
    """Get global translator instance"""
    global _translator
    if _translator is None:
        _translator = Translator('en')
    return _translator


def t(key: str, *args) -> str:
    """Shorthand for get_translator().get()"""
    return get_translator().get(key, *args)
