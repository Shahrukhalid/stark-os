# Third-party software in the desktop app

| Component | Used for | License |
|---|---|---|
| [FFmpeg](https://ffmpeg.org) (static build shipped by imageio-ffmpeg) | Video studio: trim, resize, convert, captions, thumbnails | GPL v3 (the builds include GPL components such as x264) |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | Provides the FFmpeg binary | BSD-2-Clause |
| [pywebview](https://github.com/r0x0r/pywebview) | Native window | BSD-3-Clause |
| [keyring](https://github.com/jaraco/keyring) | macOS Keychain / Windows Credential Manager | MIT |
| [PyInstaller](https://pyinstaller.org) | Packaging | GPL v2 with bootloader exception |

FFmpeg runs as a separate program; STARK OS calls it with command-line arguments and does not link to it.
FFmpeg source code: https://ffmpeg.org/download.html · build details: https://github.com/imageio/imageio-binaries
