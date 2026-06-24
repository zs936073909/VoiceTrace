"""VoiceTrace Windows 一键打包脚本

生成独立可执行文件：
    python build_windows.py

输出位置：
    dist/VoiceTrace/VoiceTrace.exe

双击 VoiceTrace.exe 即可启动软件，无需 Python 环境。
"""
import os
import sys
import shutil
import stat
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
APP_NAME = "VoiceTrace"
MAIN_SCRIPT = "main.py"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
SPEC_FILE = PROJECT_ROOT / f"{APP_NAME}.spec"


def _rmtree_longpath(path: Path):
    """处理 Windows 长路径/只读文件删除"""
    if not path.exists():
        return

    def _on_rm_error(func, fpath, exc_info):
        try:
            os.chmod(fpath, stat.S_IWRITE)
            func(fpath)
        except Exception:
            pass

    try:
        shutil.rmtree(path, onerror=_on_rm_error)
    except Exception as e:
        print(f"  警告: 清理 {path} 时出错: {e}")


def clean():
    """清理旧的打包产物"""
    print(">> Cleaning previous build artifacts...")
    _rmtree_longpath(DIST_DIR)
    _rmtree_longpath(BUILD_DIR)
    if SPEC_FILE.exists():
        SPEC_FILE.unlink()


def build():
    """调用 PyInstaller 打包"""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--paths", ".",
        # 数据文件
        "--add-data", "config;config",
        "--add-data", "models;models",
        "--add-data", "docs;docs",
        # 核心包 - 确保 PyInstaller 能发现本地 voicetrace 子包
        "--hidden-import", "voicetrace",
        "--hidden-import", "voicetrace.core",
        "--hidden-import", "voicetrace.ui",
        "--hidden-import", "voicetrace.data",
        "--hidden-import", "voicetrace.utils",
        # PySide6 模块
        "--hidden-import", "PySide6.QtCharts",
        "--hidden-import", "PySide6.QtMultimedia",
        "--hidden-import", "PySide6.QtMultimediaWidgets",
        "--hidden-import", "PySide6.QtOpenGL",
        "--hidden-import", "PySide6.QtSvg",
        # 常用第三方库
        "--hidden-import", "sklearn",
        "--hidden-import", "sklearn.metrics.pairwise",
        "--hidden-import", "librosa",
        "--hidden-import", "soundfile",
        "--hidden-import", "pydub",
        "--hidden-import", "webrtcvad",
        "--hidden-import", "reportlab",
        "--hidden-import", "reportlab.lib.pagesizes",
        "--hidden-import", "reportlab.lib.styles",
        "--hidden-import", "reportlab.platypus",
        "--hidden-import", "reportlab.pdfbase",
        "--hidden-import", "reportlab.pdfbase.ttfonts",
        "--hidden-import", "numpy",
        "--hidden-import", "cv2",
        "--hidden-import", "requests",
        "--hidden-import", "parselmouth",
        "--hidden-import", "faster_whisper",
        "--hidden-import", "torch",
        "--hidden-import", "torchaudio",
        "--hidden-import", "jieba",
        "--hidden-import", "py_fsrs",
        # 收集子模块
        "--collect-submodules", "voicetrace",
        "--collect-submodules", "librosa",
        "--collect-submodules", "sklearn",
        "--collect-submodules", "reportlab",
        "--collect-submodules", "mediapipe",
        "--collect-submodules", "cv2",
        "--collect-submodules", "parselmouth",
        "--collect-submodules", "faster_whisper",
        "--collect-submodules", "torch",
        MAIN_SCRIPT,
    ]
    print(">> Running PyInstaller...")
    print(" ", " ".join(cmd))
    subprocess.check_call(cmd, cwd=PROJECT_ROOT)


def create_shortcut_script():
    """在 dist 目录生成创建桌面快捷方式的 PowerShell 脚本"""
    exe_path = DIST_DIR / APP_NAME / f"{APP_NAME}.exe"
    ps_path = DIST_DIR / APP_NAME / "创建桌面快捷方式.ps1"
    ps_content = f"""$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:USERPROFILE\\Desktop\\VoiceTrace.lnk")
$Shortcut.TargetPath = "{exe_path.resolve()}"
$Shortcut.WorkingDirectory = "{(DIST_DIR / APP_NAME).resolve()}"
$Shortcut.Save()
Write-Host "桌面快捷方式已创建"
"""
    ps_path.write_text(ps_content, encoding="utf-8")


def main():
    clean()
    build()
    create_shortcut_script()
    output = DIST_DIR / APP_NAME
    print("\n" + "=" * 60)
    print("Build complete!")
    print(f"输出目录: {output}")
    print(f"双击启动: {output / f'{APP_NAME}.exe'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
