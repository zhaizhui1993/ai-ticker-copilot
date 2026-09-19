"""采集基座：DataSource 协议、TTL 两级缓存、网络重试。

规格：docs/03-collectors/base-cache.md
- TTL 两级缓存：内存 dict + 磁盘 pickle（data/cache/）；
  行情 15min、FRED 12h、X 24h/博主；事件管道不依赖缓存（增量去重本身防重）
- 重试：tenacity 指数退避重试 2 次（业务类错误如 429 由降级协议处理，不硬刚）
"""

import hashlib
import pickle
import threading
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from config.settings import settings
from tenacity import retry, stop_after_attempt, wait_exponential


@runtime_checkable
class DataSource(Protocol):
    """所有采集源的统一协议（契约 §10.2①）：name 供状态页/日志使用。"""

    name: str


def network_retry(fn: Callable) -> Callable:
    """指数退避重试 2 次（共 3 次尝试），耗尽后抛原异常。"""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )(fn)


def _cache_dir() -> Path:
    path = Path(settings.cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def ttl_cache(prefix: str, ttl_seconds: int, disk: bool = True) -> Callable:
    """两级 TTL 缓存装饰器。

    - 内存层：进程内 dict，命中直接返回
    - 磁盘层：pickle 落盘（进程重启后仍可命中），路径 data/cache/{prefix}_{key}.pickle
    - 键：由参数 repr 的 sha256 生成（参数须可稳定 repr：str/int/float）
    """

    def decorator(fn: Callable) -> Callable:
        memory: dict[str, tuple[float, Any]] = {}
        lock = threading.Lock()

        def _key(args: tuple, kwargs: dict) -> str:
            raw = repr((args, sorted(kwargs.items())))
            return hashlib.sha256(raw.encode()).hexdigest()[:16]

        def _disk_path(key: str) -> Path:
            return _cache_dir() / f"{prefix}_{key}.pickle"

        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = _key(args, kwargs)
            now = time.time()
            with lock:
                hit = memory.get(key)
            if hit and now - hit[0] < ttl_seconds:
                return hit[1]

            path = _disk_path(key) if disk else None
            if path is not None and path.exists():
                try:
                    saved_at, value = pickle.loads(path.read_bytes())
                    if now - saved_at < ttl_seconds:
                        with lock:
                            memory[key] = (saved_at, value)
                        return value
                except Exception:
                    path.unlink(missing_ok=True)  # 损坏的缓存直接丢弃

            value = fn(*args, **kwargs)

            with lock:
                memory[key] = (now, value)
            if path is not None:
                try:
                    path.write_bytes(pickle.dumps((now, value)))
                except Exception:
                    pass  # 磁盘缓存失败不影响主流程
            return value

        wrapper.memory = memory  # 暴露内存层供测试
        return wrapper

    return decorator
