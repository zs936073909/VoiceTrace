"""下载 MediaPipe 模型文件

运行此脚本会自动下载台风训练所需的模型：
- face_landmarker.task（面部分析）
- pose_landmarker_lite.task（身体姿态分析）

模型来源：Google MediaPipe 官方仓库
"""
import os
import sys
import urllib.request
from pathlib import Path


MODELS = {
    "face_landmarker.task": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    "pose_landmarker_lite.task": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
}


def download(url: str, dest: Path):
    """下载单个文件并显示进度"""
    print(f"下载: {url}")
    print(f"保存到: {dest}")

    def report(block_num, block_size, total_size):
        downloaded = block_num * block_size
        percent = min(100, downloaded / total_size * 100) if total_size else 0
        sys.stdout.write(f"\r进度: {percent:.1f}%")
        sys.stdout.flush()

    try:
        urllib.request.urlretrieve(url, dest, reporthook=report)
        print("\n完成")
        return True
    except Exception as e:
        print(f"\n下载失败: {e}")
        return False


def main():
    # 模型目录：项目根目录 / models
    models_dir = Path(__file__).parent.parent / "models"
    models_dir.mkdir(exist_ok=True)

    all_ok = True
    for filename, url in MODELS.items():
        dest = models_dir / filename
        if dest.exists():
            print(f"{filename} 已存在，跳过")
            continue
        if not download(url, dest):
            all_ok = False

    if all_ok:
        print("\n所有模型下载完成")
    else:
        print("\n部分模型下载失败，请检查网络连接")
        sys.exit(1)


if __name__ == "__main__":
    main()
