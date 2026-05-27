"""Tushare 数据接口层

将交易系统所需的数据映射到对应的 Tushare API 调用。
所有函数已内置 rate limit 和异常保护。
"""

import pandas as pd

from .tushare_client import cached_query, get_pro, safe_query

# ── 市场级接口 ─────────────────────────────────────────────────────


@safe_query
@cached_query
def fetch_index_daily(ts_code: str, trade_date: str = None,
                      start_date: str = None, end_date: str = None) -> pd.DataFrame | None:
    """指数日线行情

    常用指数代码:
        000001.SH  上证综指
        399001.SZ  深证成指
        399006.SZ  创业板指
        000688.SH  科创50
        000300.SH  沪深300
        000905.SH  中证500
    """
    pro = get_pro()
    kwargs = {"ts_code": ts_code}
    if trade_date:
        kwargs["trade_date"] = trade_date
    elif start_date:
        kwargs["start_date"] = start_date
        if end_date:
            kwargs["end_date"] = end_date
    return pro.index_daily(**kwargs)


@safe_query
@cached_query
def fetch_limit_list(trade_date: str, limit_type: str = None) -> pd.DataFrame | None:
    """涨跌停和炸板数据

    limit_type: U=涨停 D=跌停 Z=炸板, 不传则全取
    """
    pro = get_pro()
    kwargs = {"trade_date": trade_date}
    df = pro.limit_list_d(**kwargs)
    if limit_type and df is not None and "limit" in df.columns:
        df = df[df["limit"].astype(str) == limit_type]
    return df


@safe_query
@cached_query
def fetch_limit_cpt_list(trade_date: str) -> pd.DataFrame | None:
    """涨停最强板块统计"""
    pro = get_pro()
    return pro.limit_cpt_list(trade_date=trade_date)


@safe_query
@cached_query
def fetch_stk_limit(trade_date: str, ts_code: str = None) -> pd.DataFrame | None:
    """每日涨跌停价格（含连板统计）"""
    pro = get_pro()
    kwargs = {"trade_date": trade_date}
    if ts_code:
        kwargs["ts_code"] = ts_code
    return pro.stk_limit(**kwargs)


# ── 板块级接口 ─────────────────────────────────────────────────────


@safe_query
@cached_query
def fetch_ths_index() -> pd.DataFrame | None:
    """同花顺板块分类列表"""
    pro = get_pro()
    return pro.ths_index()


@safe_query
@cached_query
def fetch_ths_daily(trade_date: str = None, ts_code: str = None,
                    start_date: str = None, end_date: str = None) -> pd.DataFrame | None:
    """同花顺板块指数日线行情"""
    pro = get_pro()
    kwargs = {}
    if trade_date:
        kwargs["trade_date"] = trade_date
    if ts_code:
        kwargs["ts_code"] = ts_code
    if start_date:
        kwargs["start_date"] = start_date
    if end_date:
        kwargs["end_date"] = end_date
    return pro.ths_daily(**kwargs)


@safe_query
@cached_query
def fetch_ths_member(ts_code: str) -> pd.DataFrame | None:
    """同花顺板块成分股"""
    pro = get_pro()
    return pro.ths_member(ts_code=ts_code)


# ── 个股级接口 ─────────────────────────────────────────────────────


@safe_query
@cached_query
def fetch_daily(trade_date: str = None, ts_code: str = None,
                start_date: str = None, end_date: str = None) -> pd.DataFrame | None:
    """A股日线行情

    单日全市场: fetch_daily(trade_date='20260523')
    单股多日:   fetch_daily(ts_code='000001.SZ', start_date='20260501', end_date='20260523')
    """
    pro = get_pro()
    kwargs = {}
    if trade_date:
        kwargs["trade_date"] = trade_date
    if ts_code:
        kwargs["ts_code"] = ts_code
    if start_date:
        kwargs["start_date"] = start_date
    if end_date:
        kwargs["end_date"] = end_date
    return pro.daily(**kwargs)


@safe_query
@cached_query
def fetch_daily_basic(trade_date: str = None, ts_code: str = None) -> pd.DataFrame | None:
    """每日指标：换手率、流通市值、市盈率等"""
    pro = get_pro()
    kwargs = {}
    if trade_date:
        kwargs["trade_date"] = trade_date
    if ts_code:
        kwargs["ts_code"] = ts_code
    return pro.daily_basic(**kwargs)


@safe_query
@cached_query
def fetch_stock_basic(exchange: str = "", list_status: str = "L") -> pd.DataFrame | None:
    """股票列表（仅上市状态）"""
    pro = get_pro()
    return pro.stock_basic(exchange=exchange, list_status=list_status,
                           fields="ts_code,symbol,name,area,industry,market,list_date")


@safe_query
@cached_query
def fetch_moneyflow(trade_date: str = None, ts_code: str = None) -> pd.DataFrame | None:
    """个股资金流向"""
    pro = get_pro()
    kwargs = {}
    if trade_date:
        kwargs["trade_date"] = trade_date
    if ts_code:
        kwargs["ts_code"] = ts_code
    return pro.moneyflow(**kwargs)


@safe_query
@cached_query
def fetch_moneyflow_hsgt(trade_date: str = None,
                         start_date: str = None, end_date: str = None) -> pd.DataFrame | None:
    """沪深港通资金流向"""
    pro = get_pro()
    kwargs = {}
    if trade_date:
        kwargs["trade_date"] = trade_date
    if start_date:
        kwargs["start_date"] = start_date
    if end_date:
        kwargs["end_date"] = end_date
    return pro.moneyflow_hsgt(**kwargs)


# ── 交易日历 ───────────────────────────────────────────────────────


@safe_query
@cached_query
def fetch_trade_cal(exchange: str = "SSE", start_date: str = None,
                    end_date: str = None) -> pd.DataFrame | None:
    """交易日历"""
    pro = get_pro()
    kwargs = {"exchange": exchange}
    if start_date:
        kwargs["start_date"] = start_date
    if end_date:
        kwargs["end_date"] = end_date
    return pro.trade_cal(**kwargs)
