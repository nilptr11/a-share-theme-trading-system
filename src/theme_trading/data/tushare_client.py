"""Tushare 代理客户端基础模块。"""

import functools
import os
import time
from pathlib import Path

import pandas as pd
import tushare as ts
from dotenv import load_dotenv
from tushare.pro import client as _ts_client

_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_ENV_FILE)

MIN_INTERVAL = 0.6
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.0
_last_call: float = 0.0
_auth_failed_reason: str | None = None
_auth_skip_reported = False


class TushareConfigError(RuntimeError):
    pass


class TushareAuthError(RuntimeError):
    pass


_AUTH_ERROR_HINTS = (
    "tenant key expired",
    "unauthorized",
    "permission",
    "没有访问该接口的权限",
    "权限",
)


def is_tushare_auth_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(hint.lower() in message for hint in _AUTH_ERROR_HINTS)


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _configure_proxy() -> None:
    proxy_url = _env("TUSHARE_PROXY_URL")
    if proxy_url:
        _ts_client.DataApi._DataApi__http_url = proxy_url


def _get_token() -> str:
    token = _env("TUSHARE_TOKEN")
    if not token:
        raise TushareConfigError("缺少 TUSHARE_TOKEN，请在项目根目录 .env 中配置或导出环境变量。")
    return token


_configure_proxy()


def _rate_limit():
    """确保两次 API 调用间隔 ≥ MIN_INTERVAL 秒"""
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_call = time.time()


def get_pro():
    """获取已配置的 tushare pro 客户端"""
    return ts.pro_api(_get_token())


def safe_query(fn):
    """装饰器：自动 rate limit + 失败重试 + 异常转 None"""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        global _auth_failed_reason, _auth_skip_reported
        if _auth_failed_reason is not None:
            if not _auth_skip_reported:
                print(f"[tushare] 已检测到鉴权失败，跳过后续请求: {_auth_failed_reason}")
                _auth_skip_reported = True
            return None

        for attempt in range(1, MAX_RETRIES + 1):
            _rate_limit()
            try:
                result = fn(*args, **kwargs)
                if result is None or (isinstance(result, pd.DataFrame) and len(result) == 0):
                    return None
                return result
            except TushareConfigError:
                raise
            except Exception as e:
                if is_tushare_auth_error(e):
                    _auth_failed_reason = str(e)
                    _auth_skip_reported = False
                    print(f"[tushare] {fn.__name__} 鉴权失败，不重试: {e}; args={args}, kwargs={kwargs}")
                    return None
                if attempt >= MAX_RETRIES:
                    print(f"[tushare] {fn.__name__} 查询失败: {e}; args={args}, kwargs={kwargs}")
                    return None
                wait = RETRY_BACKOFF_SECONDS * attempt
                print(f"[tushare] {fn.__name__} 第 {attempt}/{MAX_RETRIES} 次查询失败，{wait:.0f}s 后重试: {e}")
                time.sleep(wait)
        return None

    return wrapper


def cache_key(*args, **kwargs):
    """生成缓存键"""
    return (args, tuple(sorted(kwargs.items())))


_cache: dict = {}
CACHE_ENABLED = True


def cached_query(fn):
    """装饰器：同一会话内相同参数不重复请求"""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if CACHE_ENABLED:
            key = (fn.__name__, cache_key(*args, **kwargs))
            if key in _cache:
                return _cache[key]
        result = fn(*args, **kwargs)
        if CACHE_ENABLED and result is not None:
            key = (fn.__name__, cache_key(*args, **kwargs))
            _cache[key] = result
        return result

    return wrapper


def clear_cache():
    """清空请求缓存"""
    global _auth_failed_reason, _auth_skip_reported
    _cache.clear()
    _auth_failed_reason = None
    _auth_skip_reported = False
