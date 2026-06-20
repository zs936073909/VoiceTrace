"""VoiceTrace Windows 打包脚本"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
APP_NAME = "VoiceTrace"
MAIN_SCRIPT = "main.py"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
SPEC_FILE = PROJECT_ROOT / f"{APP_NAME}.spec"


def clean():
    # Windows 长路径支持：使用 \\?\ 前缀
    for d in [DIST_DIR, BUILD_DIR]:
        if d.exists():
            _rmtree_longpath(d)
    if SPEC_FILE.exists():
        SPEC_FILE.unlink()


def _rmtree_longpath(path: Path):
    """处理 Windows 长路径删除"""
    import stat
    # 使用 \\?\ 前缀支持长路径
    long_path = "\\\\?\\" + str(path.resolve())
    def _on_rm_error(func, fpath, exc_info):
        # 只读文件强制删除
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)
    try:
        shutil.rmtree(long_path, onerror=_on_rm_error)
    except Exception as e:
        print(f"  警告: 清理 {path} 时出错: {e}")
        print(f"  可手动删除该目录后重试")


def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--paths", "..",
        "--add-data", "config;config",
        "--hidden-import", "PySide6.QtCharts",
        "--hidden-import", "PySide6.QtMultimedia",
        "--hidden-import", "PySide6.QtMultimediaWidgets",
        "--hidden-import", "sklearn.metrics.pairwise",
        "--hidden-import", "librosa",
        "--hidden-import", "webrtcvad",
        "--hidden-import", "pydub",
        "--hidden-import", "soundfile",
        "--hidden-import", "reportlab",
        "--hidden-import", "reportlab.lib.pagesizes",
        "--hidden-import", "reportlab.lib.styles",
        "--hidden-import", "reportlab.platypus",
        "--hidden-import", "reportlab.pdfbase",
        "--hidden-import", "reportlab.pdfbase.ttfonts",
        # 台风训练相关
        "--hidden-import", "mediapipe",
        "--hidden-import", "cv2",
        "--hidden-import", "requests",
        "--collect-submodules", "librosa",
        "--collect-submodules", "sklearn",
        "--collect-submodules", "reportlab",
        "--collect-submodules", "mediapipe",
        MAIN_SCRIPT,
    ]
    print(">> Running:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=PROJECT_ROOT)


def main():
    print(">> Cleaning previous build artifacts...")
    clean()
    print(">> Building VoiceTrace for Windows...")
    build()
    output = DIST_DIR / APP_NAME
    print(f"\nBuild complete!")
    print(f"Output: {output}")
    print(f"Executable: {output / f'{APP_NAME}.exe'}")


if __name__ == "__main__":
    main()
