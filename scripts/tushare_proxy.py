"""Tushare 代理客户端基础模块。"""

import functools
import os
import time
from pathlib import Path

import pandas as pd
import tushare as ts
from dotenv import load_dotenv
from tushare.pro import client as _ts_client

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_FILE)

MIN_INTERVAL = 0.6
_last_call: float = 0.0


class TushareConfigError(RuntimeError):
    pass


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
    """装饰器：自动 rate limit + 异常转 None"""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        _rate_limit()
        try:
            result = fn(*args, **kwargs)
            if result is None or (isinstance(result, pd.DataFrame) and len(result) == 0):
                return None
            return result
        except TushareConfigError:
            raise
        except Exception as e:
            print(f"[tushare] {fn.__name__} 查询失败: {e}")
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
    _cache.clear()
