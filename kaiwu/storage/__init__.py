"""storage 子包 — ErrorKB / ExperienceStore 单例缓存

MCP Server 是长驻进程，每次工具调用不应重新加载磁盘文件。
用模块级缓存保证整个进程生命周期内只实例化一次。
线程安全：使用 threading.Lock 保护初始化。
"""

from __future__ import annotations

import threading

_error_kb_instance = None
_experience_store_instance = None
_error_kb_lock = threading.Lock()
_experience_store_lock = threading.Lock()


def get_error_kb():
    """获取 ErrorKB 单例（线程安全）"""
    global _error_kb_instance
    if _error_kb_instance is None:
        with _error_kb_lock:
            if _error_kb_instance is None:
                from kaiwu.storage.error_kb import ErrorKB
                _error_kb_instance = ErrorKB()
    return _error_kb_instance


def get_experience_store():
    """获取 ExperienceStore 单例（线程安全）"""
    global _experience_store_instance
    if _experience_store_instance is None:
        with _experience_store_lock:
            if _experience_store_instance is None:
                from kaiwu.storage.experience import ExperienceStore
                _experience_store_instance = ExperienceStore()
    return _experience_store_instance
