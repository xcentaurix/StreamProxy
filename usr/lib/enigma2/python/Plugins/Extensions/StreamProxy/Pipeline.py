# Pipeline.py - Gestisce il flusso tra AppCore e ServiceMonitor
from .StreamProxyLog import StreamProxyLogger, enhanced_log
import os
import time

logger = StreamProxyLogger.getInstance()

class Pipeline:
    """Gestisce il flusso di dati tra AppCore e ServiceMonitor"""
    
    def __init__(self):
        self.output_path = "/usr/lib/enigma2/python/Plugins/Extensions/StreamProxy/stream.m3u"
        enhanced_log("Pipeline inizializzata", "INFO", "PIPELINE")
    
    def process_and_write(self, content, content_type, source_url=None):
        """Processa il contenuto e lo scrive su file se valido"""
        try:
            enhanced_log(f"Pipeline processing: size={len(content)} bytes, type={content_type}", "INFO", "PIPELINE")
            
            if content_type == "application/vnd.apple.mpegurl":
                # Verifica che il contenuto sia un M3U8 valido con segmenti video
                if self._validate_m3u8_content(content):
                    # Assicurati che la directory esista
                    import os
                    os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
                    
                    # Scrivi il file M3U8
                    with open(self.output_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    enhanced_log(f"✅ File M3U scritto: {self.output_path}", "INFO", "PIPELINE")
                    
                    # Notifica ServiceMonitor con delay per evitare race condition
                    from twisted.internet import reactor
                    reactor.callLater(0.1, self._notify_service_monitor)
                    return True
                else:
                    enhanced_log("❌ Contenuto M3U8 non valido", "ERROR", "PIPELINE")
                    return False
            else:
                enhanced_log(f"⚠️ Tipo contenuto non supportato: {content_type}", "WARNING", "PIPELINE")
                return False
                
        except Exception as e:
            enhanced_log(f"💥 Errore pipeline: {str(e)}", "ERROR", "PIPELINE")
            return False
    
    def _validate_m3u8_content(self, content):
        """Valida che il contenuto M3U8 contenga segmenti video validi"""
        try:
            if not content or not content.strip():
                enhanced_log("Contenuto M3U8 vuoto", "ERROR", "PIPELINE")
                return False
            
            if not content.startswith('#EXTM3U'):
                enhanced_log("Contenuto non è un M3U8 valido", "ERROR", "PIPELINE")
                return False
            
            # Conta i segmenti video validi
            lines = content.strip().split('\n')
            video_segments = 0
            non_video_extensions = ['.txt', '.ico', '.eot', '.svg', '.woff', '.woff2', '.js', '.css', '.xml', '.html', '.png', '.jpg', '.jpeg', '.gif', '.csv', '.md', '.json', '.pdf']
            
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#'):
                    # Verifica se è un segmento video valido
                    line_lower = line.lower()
                    is_non_video = any(ext in line_lower for ext in non_video_extensions)
                    
                    if not is_non_video and ('.ts' in line_lower or 'segment' in line_lower or '.m4s' in line_lower):
                        video_segments += 1
                        enhanced_log(f"Segmento video valido trovato: {line[:100]}...", "DEBUG", "PIPELINE")
                    else:
                        enhanced_log(f"Segmento non-video scartato: {line[:100]}...", "WARNING", "PIPELINE")
            
            enhanced_log(f"Trovati {video_segments} segmenti video validi", "INFO", "PIPELINE")
            return video_segments > 0
            
        except Exception as e:
            enhanced_log(f"Errore nella validazione M3U8: {str(e)}", "ERROR", "PIPELINE")
            return False
    
    def _notify_service_monitor(self):
        """Notifica ServiceMonitor che il file M3U8 è pronto"""
        try:
            # Importa qui per evitare dipendenze circolari
            from . import AppCore
            
            # Usa il callback di AppCore per notificare ServiceMonitor
            result = AppCore.service_monitor_callback('/service/notify_m3u', path=self.output_path)
            enhanced_log(f"Notifica inviata a ServiceMonitor per il file: {self.output_path}", "INFO", "PIPELINE")
            return result
            
        except Exception as e:
            enhanced_log(f"Errore nella notifica a ServiceMonitor: {str(e)}", "ERROR", "PIPELINE")
            return False

# Istanza globale della pipeline
pipeline_instance = Pipeline()

def process_content(content, content_type, source_url=None):
    """Funzione di utilità per processare contenuti tramite la pipeline"""
    return pipeline_instance.process_and_write(content, content_type, source_url)