**StreamProxy**

## Github status
[![Lint Status](https://github.com/OwnerPlugins/StreamProxy/actions/workflows/pylint.yml/badge.svg)](https://github.com/OwnerPlugins/StreamProxy/actions/workflows/pylint.yml)
[![Ruff Status](https://github.com/OwnerPlugins/StreamProxy/actions/workflows/ruff.yml/badge.svg)](https://github.com/OwnerPlugins/StreamProxy/actions/workflows/ruff.yml)


# ⭐️ StreamProxy

**StreamProxy** turns an **Enigma2** receiver into an intelligent proxy server capable of handling **HLS (m3u8)** streams from various sources such as DaddyLive, Vavoo, Freeshot, Sport99, and others, making them fully playable on Enigma2 devices.

The plugin intercepts IPTV channel playback requests, resolves the actual stream URLs, handles tokens and encryption keys, performs AES decryption when required, and serves the content through a local proxy in an Enigma2-compatible format.

---

## 🚀 Features

- Automatic IPTV playback interception
- HLS (`.m3u8`) stream support
- Dynamic URL and token handling
- AES-128 decryption
- fMP4 → TS conversion when required
- Intelligent caching system
- Multiple streaming provider support
- Built-in Enigma2 configuration interface
- Advanced logging system
- Configurable local HTTP proxy

---

## 🔄 How It Works

When a user starts an IPTV channel:

1. **ServiceMonitor** intercepts the playback request.
2. The URL is checked against supported providers.
3. If supported, the original URL is replaced with a local proxy URL:

```text
http://127.0.0.1:7860/proxy/m3u?url=<original_URL>
```

4. The Enigma2 player receives the proxy URL.
5. StreamProxy automatically manages:
   - Playlist downloads
   - Stream URL extraction
   - Token handling
   - AES key retrieval
   - Segment decryption
   - Format conversion
   - Caching

---

## 📋 Detailed Workflow

### 1. Playback Interception

`ServiceMonitor.py` hooks into Enigma2's `playService()` method.

When an IPTV service is selected, the plugin:

- Parses the service URL
- Detects the provider
- Generates a local proxy URL

---

### 2. Service Detection

StreamProxy currently supports multiple providers, including:

- DaddyLive
- Vavoo
- Freeshot
- Sport99
- Mixdrop
- Additional compatible services

Each provider has a dedicated extractor module responsible for handling its specific APIs, headers, tokens, and authentication mechanisms.

---

### 3. Local HTTP Server

The HTTP server (`server.py`) listens on port **7860** and exposes several endpoints:

| Endpoint | Description |
|-----------|-------------|
| `/proxy/m3u` | Downloads and rewrites HLS playlists |
| `/proxy/ts` | Retrieves and processes TS/fMP4 segments |
| `/proxy/key` | Retrieves AES encryption keys |
| `/proxy/mpd` | Handles DASH streams using a dummy playlist |

---

### 4. Playlist Processing (`/proxy/m3u`)

When a playlist request is received:

- The original playlist is downloaded.
- Segment URLs are rewritten to point back to the proxy.
- AES key references are redirected to `/proxy/key`.
- Unsupported tracks are removed when necessary.
- The modified playlist is returned to Enigma2.

---

### 5. Segment Processing (`/proxy/ts`)

For each media segment:

1. The segment is downloaded.
2. If encrypted, AES-128 decryption is performed.
3. If the segment is in fMP4 format:
   - It is converted to MPEG-TS for Enigma2 compatibility.
   - Freeshot streams may bypass conversion and be served directly.
4. The processed segment is streamed back to the player.

---

### 6. AES Key Handling (`/proxy/key`)

Encryption keys referenced inside playlists are fetched and cached by StreamProxy.

These keys are then used to decrypt media segments transparently before delivery.

---

### 7. DASH (MPD) Support

Enigma2 does not natively support MPEG-DASH streams.

When a DASH stream is detected:

- StreamProxy intercepts the request.
- A dummy HLS playlist is generated and returned.
- This allows the stream to remain compatible with Enigma2 playback workflows.

---

## 🔐 Decryption and Stream Processing

Most of the stream processing logic is implemented in `AppCore.py`.

Features include:

- AES-128-CBC decryption
- IV extraction from playlists
- Key retrieval and caching
- Playlist rewriting
- Segment manipulation
- Stream conversion
- Automatic token refresh

Supported providers such as DaddyLive and Freeshot can automatically refresh expired tokens when necessary.

---

## ⚡ Cache Management

`cache_manager.py` implements several caching layers to reduce network traffic and CPU usage.

### Playlist Cache

- TTL-based expiration
- Avoids repeated playlist downloads

### Segment Cache

- LRU (Least Recently Used) strategy
- Stores recently requested TS/fMP4 segments

### Key Cache

- Stores AES encryption keys
- Reduces unnecessary requests

---

## 🔌 Extractor Architecture

The `extractor/` directory contains service-specific modules that resolve actual stream URLs.

Examples include:

- `dlhd_extractor.py`
- `vavoo_extractor.py`
- `freeshot_extractor.py`

Each extractor handles:

- API requests
- Authentication
- Headers
- Token generation
- Stream URL extraction

This modular architecture makes it easy to add support for new providers.

---

## 🖥️ User Interface Integration

StreamProxy integrates directly into the Enigma2 user interface.

The configuration screen (`StreamProxySetup.py`) allows users to:

- Enable or disable the proxy
- Change the listening port
- Enable debug logging
- Configure plugin behavior
- Manage advanced settings

The plugin is accessible from the Enigma2 menu system.

---

## 📝 Logging

`StreamProxyLog.py` provides a centralized logging system with multiple log levels:

- `DEBUG`
- `INFO`
- `WARNING`
- `ERROR`

Logs can be displayed in real time and optionally written to a file for troubleshooting and debugging.

---

## 📂 Project Structure

```text
StreamProxy/
├── AppCore.py
├── server.py
├── ServiceMonitor.py
├── StreamProxySetup.py
├── StreamProxyLog.py
├── cache_manager.py
└── extractor/
    ├── dlhd_extractor.py
    ├── vavoo_extractor.py
    ├── freeshot_extractor.py
    └── ...
```

---

## 🎯 Purpose

StreamProxy acts as a compatibility layer between Enigma2 and modern streaming services by:

- Resolving protected stream URLs
- Managing authentication tokens
- Handling encrypted content
- Converting unsupported formats
- Providing a seamless playback experience directly within Enigma2


## Target path:
  /usr/lib/enigma2/python/Plugins/Extensions/StreamProxy

## ZIP install:
  1. Extract this archive on the decoder root filesystem.
  2. Restart Enigma2.

## IPK install:
  opkg install enigma2-plugin-extensions-streamproxy_2026.05.05.0032_all.ipk

## Runtime requirements:
  python3, python3-twisted, python3-requests, python3-pycryptodome

## User config is not bundled. StreamProxy creates SPconfig.txt on first run when missing.


---

### 📜 License Information [![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
This is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation
This plugin is released under GPLv3. See [LICENSE](https://www.gnu.org/licenses/gpl-3.0.html#license-text) for full details.
<img width="120" height="58" alt="GPLv3_Logo svg" src="https://github.com/user-attachments/assets/67d32b0a-2a44-4fa9-a972-202daf28808e" />

---
### 🚨 Disclaimer

The project author is not responsible for how this software is used by others. It is not intended to be used for accessing or distributing copyrighted materials without authorization.
Users are solely responsible for determining the legality of their actions.

This repository has no control over the streams, links, or the legality of the content provided by the different hosts (including all mirror sites). It is the end user's responsibility to ensure the legal use of these streams, and we strongly recommend verifying that the content complies with all applicable laws, including copyright laws and regulations of your countrys jurisdiction before use.

---

⭐️ If you find this plugin useful, please give it a star on GitHub!
Thanks! ❤️ 💞 💖 ❤️‍🔥 💗
