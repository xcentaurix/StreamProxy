# -*- coding: utf-8 -*-

from __future__ import absolute_import
from Tools.Directories import resolveFilename, SCOPE_PLUGINS
from Components.Language import language
import gettext
import os

# try:
# from Crypto.Cipher import AES
# CRYPTO_AVAILABLE = True
# except ImportError:
# CRYPTO_AVAILABLE = False

print("[StreamProxy] Plugin init")

__license__ = "GPL-v2"
__version__ = "1.2_20260626"


PluginLanguageDomain = "streamproxy"
PluginLanguagePath = "Extensions/StreamProxy/locale"


def localeInit():
    lang = language.getLanguage()[:2]  # es. "it", "en"
    os.environ["LANGUAGE"] = lang
    gettext.bindtextdomain(
        PluginLanguageDomain,
        resolveFilename(
            SCOPE_PLUGINS,
            PluginLanguagePath))


def _(txt):
    return gettext.dgettext(PluginLanguageDomain, txt) if txt else ""


localeInit()
language.addCallback(localeInit)
