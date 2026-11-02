# PyInstaller build of the STARK OS desktop app:  pyinstaller desktop/stark.spec --noconfirm
# Needs the static dashboard first:  cd apps/web && STARK_DESKTOP_BUILD=1 npm run build
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "services/api/stark/__init__.py").read_text()).group(1)
WEB = ROOT / "apps/web/out"
if not (WEB / "index.html").exists():
    sys.exit("Build the dashboard first: cd apps/web && STARK_DESKTOP_BUILD=1 npm run build")

# imageio_ffmpeg's FFmpeg binary (video studio) is collected by its PyInstaller hook (pyinstaller-hooks-contrib).
hidden = ["imageio_ffmpeg", "pywhispercpp", "pywhispercpp.model", "_pywhispercpp", "numpy"] + collect_submodules("stark") + collect_submodules("uvicorn") + ["keyring.backends.macOS", "keyring.backends.Windows"]
a = Analysis(
    [str(ROOT / "desktop/stark_desktop.py")],
    pathex=[str(ROOT / "services/api")],
    datas=[(str(ROOT / "agents"), "agents"), (str(WEB), "web")] + collect_data_files("stark"),
    hiddenimports=hidden,
    excludes=["playwright", "tkinter", "pytest"],
)
pyz = PYZ(a.pure)
icon = str(ROOT / "desktop/assets" / ("icon.icns" if sys.platform == "darwin" else "icon.ico"))
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="STARK OS", console=False, icon=icon,
          disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, name="STARK OS")
if sys.platform == "darwin":
    app = BUNDLE(
        coll, name="STARK OS.app", icon=icon, bundle_identifier="com.nexonic.starkos", version=VERSION,
        info_plist={
            "CFBundleName": "STARK OS", "CFBundleDisplayName": "STARK OS", "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION, "LSMinimumSystemVersion": "11.0", "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.productivity",
            "NSHumanReadableCopyright": "© 2026 Shahrukh Khalid. MIT License.",
        },
    )
