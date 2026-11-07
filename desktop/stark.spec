# PyInstaller build of the STARK AI desktop app:  pyinstaller desktop/stark.spec --noconfirm
# Needs the static dashboard first:  cd apps/web && STARK_DESKTOP_BUILD=1 npm run build
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "services/api/stark/__init__.py").read_text()).group(1)
WEB = ROOT / "apps/web/out"
if not (WEB / "index.html").exists():
    sys.exit("Build the dashboard first: cd apps/web && STARK_DESKTOP_BUILD=1 npm run build")

# imageio_ffmpeg's FFmpeg binary (video studio) is collected by its PyInstaller hook (pyinstaller-hooks-contrib).
# whisper.cpp's shared libraries sit next to the extension module in site-packages; collect them explicitly so
# the extension finds them through @rpath / the DLL search path in the bundle.
import glob
import sysconfig

WHISPER_LIBS = []
for base in {sysconfig.get_paths()["platlib"], sysconfig.get_paths()["purelib"]}:
    for pat in ("libwhisper*", "libggml*", "whisper*.dll", "ggml*.dll", "pywhispercpp/.dylibs/*", "pywhispercpp.libs/*"):
        WHISPER_LIBS += [(p, ".") for p in glob.glob(str(Path(base) / pat)) if Path(p).is_file()]
print("whisper libraries:", [Path(p).name for p, _ in WHISPER_LIBS])

hidden = (["keyring.backends.macOS"] if sys.platform == "darwin" else ["keyring.backends.Windows"]) + ["imageio_ffmpeg", "pywhispercpp", "pywhispercpp.model", "_pywhispercpp", "numpy", "sounddevice"] + collect_submodules("stark") + collect_submodules("uvicorn")
a = Analysis(
    [str(ROOT / "desktop/stark_desktop.py")],
    pathex=[str(ROOT / "services/api")],
    binaries=WHISPER_LIBS,
    datas=[(str(ROOT / "agents"), "agents"), (str(WEB), "web")] + collect_data_files("stark")
    + copy_metadata("pywhispercpp"),  # it reads its own version at import time
    hiddenimports=hidden,
    excludes=["playwright", "tkinter", "pytest"],
)
pyz = PYZ(a.pure)
icon = str(ROOT / "desktop/assets" / ("icon.icns" if sys.platform == "darwin" else "icon.ico"))
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="STARK AI", console=False, icon=icon,
          disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, name="STARK AI")
if sys.platform == "darwin":
    app = BUNDLE(
        coll, name="STARK AI.app", icon=icon, bundle_identifier="com.nexonic.starkos", version=VERSION,
        info_plist={
            "CFBundleName": "STARK AI", "CFBundleDisplayName": "STARK AI", "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION, "LSMinimumSystemVersion": "11.0", "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.productivity",
            "NSHumanReadableCopyright": "© 2026 Shahrukh Khalid. MIT License.",
            "NSMicrophoneUsageDescription": "STARK AI listens only while you hold the talk button, so you can "
                                            "speak to Vision and Wanda.",
        },
    )
