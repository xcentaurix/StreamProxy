"""Extractor package for StreamProxy."""

try:
    from .base import BaseExtractor, ExtractorError
    from .generic import GenericHLSExtractor
except Exception:
    BaseExtractor = None
    GenericHLSExtractor = None

    class ExtractorError(Exception):
        pass
