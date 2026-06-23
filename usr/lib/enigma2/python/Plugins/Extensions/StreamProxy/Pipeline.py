# Pipeline.py - Handles flow between AppCore and ServiceMonitor

from .StreamProxyLog import StreamProxyLogger, enhanced_log
import os
import time

logger = StreamProxyLogger.getInstance()


class Pipeline:
    """Handles data flow between AppCore and ServiceMonitor"""

    def __init__(self):
        self.output_path = (
            "/usr/lib/enigma2/python/Plugins/Extensions/"
            "StreamProxy/stream.m3u"
        )
        enhanced_log("Pipeline initialized", "INFO", "PIPELINE")

    def process_and_write(self, content, content_type, source_url=None):
        """Process content and write it to file if valid"""
        try:
            enhanced_log(
                "Pipeline processing: size=%d bytes, type=%s" % (
                    len(content),
                    content_type
                ),
                "INFO",
                "PIPELINE"
            )

            if content_type == "application/vnd.apple.mpegurl":

                # Validate M3U8 content
                if self._validate_m3u8_content(content):

                    # Ensure directory exists
                    os.makedirs(
                        os.path.dirname(self.output_path),
                        exist_ok=True
                    )

                    # Write M3U8 file
                    with open(self.output_path, 'w', encoding='utf-8') as f:
                        f.write(content)

                    enhanced_log(
                        "✅ M3U file written: %s" % self.output_path,
                        "INFO",
                        "PIPELINE"
                    )

                    # Notify ServiceMonitor with small delay to avoid race
                    # condition
                    from twisted.internet import reactor
                    reactor.callLater(0.1, self._notify_service_monitor)

                    return True

                enhanced_log(
                    "❌ Invalid M3U8 content",
                    "ERROR",
                    "PIPELINE"
                )
                return False

            enhanced_log(
                "⚠️ Unsupported content type: %s" % content_type,
                "WARNING",
                "PIPELINE"
            )
            return False

        except Exception as e:
            enhanced_log(
                "💥 Pipeline error: %s" % str(e),
                "ERROR",
                "PIPELINE"
            )
            return False

    def _validate_m3u8_content(self, content):
        """Validate that M3U8 contains valid video segments"""
        try:
            if not content or not content.strip():
                enhanced_log("Empty M3U8 content", "ERROR", "PIPELINE")
                return False

            if not content.startswith('#EXTM3U'):
                enhanced_log(
                    "Invalid M3U8 format",
                    "ERROR",
                    "PIPELINE"
                )
                return False

            lines = content.strip().split('\n')
            video_segments = 0

            non_video_extensions = [
                '.txt', '.ico', '.eot', '.svg', '.woff', '.woff2',
                '.js', '.css', '.xml', '.html', '.png', '.jpg',
                '.jpeg', '.gif', '.csv', '.md', '.json', '.pdf'
            ]

            for line in lines:
                line = line.strip()

                if line and not line.startswith('#'):

                    line_lower = line.lower()

                    is_non_video = any(
                        ext in line_lower for ext in non_video_extensions
                    )

                    if (
                        not is_non_video and
                        ('.ts' in line_lower or
                         'segment' in line_lower or
                         '.m4s' in line_lower)
                    ):
                        video_segments += 1

                        enhanced_log(
                            "Video segment found: %s..." % line[:100],
                            "DEBUG",
                            "PIPELINE"
                        )
                    else:
                        enhanced_log(
                            "Non-video segment ignored: %s..." % line[:100],
                            "WARNING",
                            "PIPELINE"
                        )

            enhanced_log(
                "Found %d valid video segments" % video_segments,
                "INFO",
                "PIPELINE"
            )

            return video_segments > 0

        except Exception as e:
            enhanced_log(
                "M3U8 validation error: %s" % str(e),
                "ERROR",
                "PIPELINE"
            )
            return False

    def _notify_service_monitor(self):
        """Notify ServiceMonitor that M3U8 file is ready"""
        try:
            from . import AppCore

            result = AppCore.service_monitor_callback(
                '/service/notify_m3u',
                path=self.output_path
            )

            enhanced_log(
                "Notification sent to ServiceMonitor: %s" % self.output_path,
                "INFO",
                "PIPELINE"
            )

            return result

        except Exception as e:
            enhanced_log(
                "ServiceMonitor notification error: %s" % str(e),
                "ERROR",
                "PIPELINE"
            )
            return False


# Global pipeline instance
pipeline_instance = Pipeline()


def process_content(content, content_type, source_url=None):
    """Utility function to process content through pipeline"""
    return pipeline_instance.process_and_write(
        content,
        content_type,
        source_url
    )
