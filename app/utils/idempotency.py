"""幂等：Redis 有就用 Redis，没有就退化成进程内字典（本地/测试足够）。

验收项常见措辞「重复提交只落一次」「幂等」「回调重复不重复处理」——都用这个封装：
    with idem("esign:callback", sign_id) as first:
        if not first:
            raise_conflict("duplicate callback")
"""
import os
from contextlib import contextmanager
from threading import Lock

_MEM: dict[str, str] = {}
_LOCK = Lock()
_TTL = 24 * 3600


def _redis():
    try:
        import redis  # 延迟导入：没装也不影响本地跑

        return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), socket_timeout=1)
    except Exception:
        return None


@contextmanager
def idem(namespace: str, key: str, ttl: int = _TTL):
    """yield True 表示首次占用；False 表示重复。异常时释放占用，允许重试。"""
    full = f"idem:{namespace}:{key}"
    r = _redis()
    token = os.urandom(8).hex()
    if r is not None:
        try:
            first = bool(r.set(full, token, nx=True, ex=ttl))
        except Exception:
            r = None
            first = None
        if first is not None:
            try:
                yield first
            except Exception:
                if first:
                    try:
                        r.delete(full)
                    except Exception:
                        pass
                raise
            return
    with _LOCK:
        first = full not in _MEM
        if first:
            _MEM[full] = token
    try:
        yield first
    except Exception:
        if first:
            with _LOCK:
                _MEM.pop(full, None)
        raise
