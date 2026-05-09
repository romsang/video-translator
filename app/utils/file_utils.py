"""
file_utils.py — 文件与目录管理工具
负责创建工作目录、管理中间文件、清理临时文件
"""

import shutil
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_dirs(config: dict) -> None:
    """
    启动时确保所有必要目录存在。
    如果目录不存在则自动创建。
    """
    for key in ("workspace", "outputs"):
        path = Path(config["paths"][key])
        path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"目录就绪: {path}")


def get_task_workspace(task_id: str, config: dict) -> Path:
    """
    获取指定任务的工作目录路径。
    结构：workspace/<task_id>/
    每个任务独立一个子目录，避免文件冲突。
    """
    path = Path(config["paths"]["workspace"]) / task_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_output_dir(task_id: str, config: dict) -> Path:
    """
    获取指定任务的输出目录路径。
    结构：outputs/<task_id>/
    """
    path = Path(config["paths"]["outputs"]) / task_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def cleanup_workspace(task_id: str, config: dict) -> None:
    """
    删除任务的工作目录（中间文件）。
    只保留 outputs/ 下的最终产物。
    """
    workspace = Path(config["paths"]["workspace"]) / task_id
    if workspace.exists():
        shutil.rmtree(workspace)
        logger.info(f"[{task_id}] 中间文件已清理: {workspace}")


def safe_stem(filename: str) -> str:
    """
    从文件名提取安全的词干（去除扩展名，替换空格）。
    例：'my video.mp4' -> 'my_video'
    """
    return Path(filename).stem.replace(" ", "_")
