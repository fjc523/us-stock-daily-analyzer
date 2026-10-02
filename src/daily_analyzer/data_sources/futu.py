"""富途 OpenD QUOTE 订阅及快照生命周期。"""

from __future__ import annotations

import time
import threading
from collections import deque
from collections.abc import Iterable, Mapping
from typing import Any, Callable


def futu_code(symbol: str) -> str:
    normalized = str(symbol).strip().upper().removeprefix("US.").replace("-", ".")
    return f"US.{normalized}" if normalized else ""


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [dict(value)]
    if hasattr(value, "to_dict"):
        try:
            rows = value.to_dict(orient="records")
            return [dict(row) for row in rows]
        except (TypeError, ValueError):
            pass
    if hasattr(value, "iterrows"):
        return [dict(row) for _, row in value.iterrows()]
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


class FutuQuoteManager:
    """管理单批次订阅；OpenD 不可用或额度不足时改用快照。"""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 11111,
        max_subscriptions: int = 40,
        context_factory: Callable[..., Any] | None = None,
        quote_subtype: Any | None = None,
        ret_ok: int = 0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.host = host
        self.port = port
        self.max_subscriptions = max_subscriptions
        self.context_factory = context_factory
        self.quote_subtype = quote_subtype
        self.ret_ok = ret_ok
        self.clock = clock
        self.sleep = sleep
        self.context: Any | None = None
        self.mode = "unavailable"
        self.warning: str | None = None
        self.symbols: list[str] = []
        self.subscribed_codes: list[str] = []
        self._subscription_started_at: float | None = None
        self._snapshot_calls: deque[float] = deque()
        self._closed = False

    def _load_futu(self) -> tuple[Callable[..., Any], Any]:
        if self.context_factory is not None:
            return self.context_factory, self.quote_subtype or "QUOTE"
        from futu import OpenQuoteContext, SubType

        return self.context_factory or OpenQuoteContext, self.quote_subtype or SubType.QUOTE

    def start_batch(self, symbols: Iterable[str]) -> FutuQuoteManager:
        self.symbols = list(dict.fromkeys(s for s in (futu_code(x) for x in symbols) if s))
        if not self.symbols:
            self.mode = "unavailable"
            self.warning = "没有待订阅代码"
            return self
        try:
            factory, self.quote_subtype = self._load_futu()
            self.context = factory(host=self.host, port=self.port)
            ret, subscription = self.context.query_subscription(is_all_conn=True)
            if ret != self.ret_ok:
                self.mode = "snapshot"
                self.warning = "无法查询富途订阅额度，改用快照"
                return self
            remain = int((subscription or {}).get("remain", 0))
            if len(self.symbols) > self.max_subscriptions or remain < len(self.symbols):
                self.mode = "snapshot"
                self.warning = "额度不足，使用快照"
                return self
            for offset in range(0, len(self.symbols), self.max_subscriptions):
                chunk = self.symbols[offset : offset + self.max_subscriptions]
                ret, result = self.context.subscribe(
                    chunk,
                    [self.quote_subtype],
                    is_first_push=False,
                    subscribe_push=False,
                    extended_time=True,
                )
                if ret != self.ret_ok:
                    self.mode = "snapshot"
                    self.warning = "富途订阅失败，改用快照"
                    return self
                self.subscribed_codes.extend(chunk)
                if self._subscription_started_at is None:
                    self._subscription_started_at = self.clock()
            self.mode = "subscription"
        except Exception as exc:
            self.mode = "unavailable"
            self.warning = f"富途 OpenD 不可用：{type(exc).__name__}"
            if self.context is not None and not self.subscribed_codes:
                self._close_context()
        return self

    def get_quotes(self, symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
        codes = list(dict.fromkeys(s for s in (futu_code(x) for x in symbols) if s))
        if not codes or self.context is None or self.mode == "unavailable":
            return {}
        output: dict[str, dict[str, Any]] = {}
        if self.mode == "subscription":
            for offset in range(0, len(codes), self.max_subscriptions):
                chunk = codes[offset : offset + self.max_subscriptions]
                try:
                    ret, rows = self.context.get_stock_quote(chunk)
                except Exception as exc:
                    self.warning = f"富途订阅报价不可用：{type(exc).__name__}"
                    continue
                if ret == self.ret_ok:
                    output.update(self._index_rows(rows))
                else:
                    self.warning = "富途订阅报价不可用：接口返回失败"
            return output
        return self.get_snapshots(codes)

    def get_snapshots(self, symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
        """显式读取富途快照，供订阅报价缺项时逐级降级。"""
        codes = list(dict.fromkeys(s for s in (futu_code(x) for x in symbols) if s))
        if not codes or self.context is None:
            return {}
        output: dict[str, dict[str, Any]] = {}
        for offset in range(0, len(codes), 400):
            chunk = codes[offset : offset + 400]
            self._respect_snapshot_limit()
            try:
                ret, rows = self.context.get_market_snapshot(chunk)
            except Exception as exc:
                self.warning = f"富途快照不可用：{type(exc).__name__}"
                continue
            if ret == self.ret_ok:
                output.update(self._index_rows(rows))
            else:
                self.warning = "富途快照不可用：接口返回失败"
        return output

    def _respect_snapshot_limit(self) -> None:
        now = self.clock()
        while self._snapshot_calls and now - self._snapshot_calls[0] >= 30:
            self._snapshot_calls.popleft()
        if len(self._snapshot_calls) >= 60:
            delay = max(0.0, 30 - (now - self._snapshot_calls[0]))
            self.sleep(delay)
            now = self.clock()
            while self._snapshot_calls and now - self._snapshot_calls[0] >= 30:
                self._snapshot_calls.popleft()
        self._snapshot_calls.append(now)

    @staticmethod
    def _index_rows(rows: Any) -> dict[str, dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        for row in _records(rows):
            code = str(row.get("code") or "").strip().upper()
            if code:
                indexed[code] = row
        return indexed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.context is not None and self.subscribed_codes:
                started_at = self._subscription_started_at
                elapsed = self.clock() - (started_at if started_at is not None else self.clock())
                if elapsed < 60:
                    self.sleep(60 - elapsed)
                try:
                    ret, result = self.context.unsubscribe(
                        self.subscribed_codes, [self.quote_subtype]
                    )
                    if ret != self.ret_ok:
                        self.warning = "富途取消订阅失败：接口返回失败"
                except Exception as exc:
                    self.warning = f"富途取消订阅失败：{type(exc).__name__}"
        finally:
            self._close_context()

    def _close_context(self) -> None:
        context, self.context = self.context, None
        if context is not None:
            try:
                context.close()
            except Exception:
                pass

    def __enter__(self) -> FutuQuoteManager:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


class FutuDataSource:
    """按接口缓存批次数据；日K订阅保持共享连接，其余接口使用短连接。"""

    def __init__(self, host="127.0.0.1", port=11111, context_factory=None,
                 clock=time.monotonic, timer_factory=threading.Timer):
        self.host, self.port = host, port
        self.context_factory = context_factory
        self._cache = {}
        self._lock = threading.RLock()
        self._clock, self._timer_factory = clock, timer_factory
        self._daily_context = None
        self._daily_subscriptions = {}
        self._daily_timers = {}

    def clear_cache(self):
        with self._lock:
            self._cache.clear()

    def _call(self, method, **kwargs):
        from tradingagents.dataflows.errors import VendorUnavailableError
        import futu
        key = (method, repr(sorted(kwargs.items())))
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            context = None
            from time import perf_counter
            started = perf_counter()
            try:
                factory = self.context_factory or futu.OpenQuoteContext
                context = factory(host=self.host, port=self.port)
                if method == "get_cur_kline":
                    subscribed = context.subscribe([kwargs["code"]], [kwargs["ktype"]], subscribe_push=False)
                    if subscribed[0] != 0:
                        raise VendorUnavailableError("富途收益率期货日K订阅不可用（权限或额度不足）")
                response = getattr(context, method)(**kwargs)
                if response[0] != 0:
                    text = str(response[1])
                    reason = "协议不支持（需OpenD 10.11）" if "协议" in text else "限频或额度不足" if any(x in text for x in ("频", "额度", "quota")) else "参数非法" if any(x in text for x in ("入参", "参数", "上限值")) else "权限不足" if "权限" in text else "接口不可用"
                    raise VendorUnavailableError(f"富途{method}：{reason}")
                from tradingagents.dataflows.vendor_observer import report_vendor
                report_vendor(method, "futu", "success", duration=perf_counter()-started)
                self._cache[key] = response[1:]
                return response[1:]
            except VendorUnavailableError as exc:
                from tradingagents.dataflows.vendor_observer import report_vendor
                report_vendor(method, "futu", "failed", error=str(exc), duration=perf_counter()-started)
                raise
            except Exception as exc:
                from tradingagents.dataflows.vendor_observer import report_vendor
                report_vendor(method, "futu", "failed", error=type(exc).__name__, duration=perf_counter()-started)
                raise VendorUnavailableError(f"富途{method}：{type(exc).__name__}") from exc
            finally:
                if context is not None:
                    context.close()

    def daily_bars(self, symbol, start, end):
        """优先复用订阅日K；仅超出当前日K覆盖时使用历史额度。"""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        start, end = str(start)[:10], str(end)[:10]
        today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        current = self._current_daily_bars(futu_code(symbol))
        if start < current["Date"].min():
            import logging
            logging.getLogger(__name__).info("富途%s：请求早于当前日K覆盖，改用历史接口并消耗历史K线额度", symbol)
            current = self._history_daily_bars(symbol, start, end)
        return current.loc[(current["Date"] >= start) & (current["Date"] <= end)
                           & (current["Date"] < today)].copy().reset_index(drop=True)

    def _current_daily_bars(self, code):
        """共享连接保持本项目的订阅满60秒；后台退订不阻塞分析。"""
        import futu
        from tradingagents.dataflows.errors import VendorUnavailableError
        key = ("current_daily", code)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            try:
                if self._daily_context is None:
                    factory = self.context_factory or futu.OpenQuoteContext
                    self._daily_context = factory(host=self.host, port=self.port)
                context = self._daily_context
                if code not in self._daily_subscriptions:
                    ret, quota = context.query_subscription(is_all_conn=True)
                    if ret != 0 or int((quota or {}).get("remain", 0)) < 1:
                        raise VendorUnavailableError("富途日K订阅额度不足或无法查询")
                    ret, detail = context.subscribe([code], [futu.SubType.K_DAY], subscribe_push=False)
                    if ret != 0:
                        raise VendorUnavailableError("富途日K订阅不可用：" + str(detail))
                    self._daily_subscriptions[code] = self._clock()
                    timer = self._timer_factory(60, lambda: self._release_daily(code))
                    self._daily_timers[code] = timer
                    timer.start()
                ret, rows = context.get_cur_kline(code, num=1000, ktype=futu.KLType.K_DAY, autype=futu.AuType.QFQ)
                if ret != 0:
                    raise VendorUnavailableError("富途订阅日K读取不可用：" + str(rows))
                frame = self._daily_frame(rows)
                if frame.empty:
                    raise VendorUnavailableError("富途订阅日K为空")
                self._cache[key] = frame
                return frame
            except Exception as exc:
                if not self._daily_subscriptions and self._daily_context is not None:
                    self._daily_context.close()
                    self._daily_context = None
                if isinstance(exc, VendorUnavailableError):
                    raise
                raise VendorUnavailableError(f"富途日K：{type(exc).__name__}") from exc

    def _release_daily(self, code):
        import futu
        import logging
        with self._lock:
            if code not in self._daily_subscriptions:
                return
            if self._clock() - self._daily_subscriptions[code] < 60:
                return
            timer = self._daily_timers.pop(code, None)
            if timer is not None:
                timer.cancel()
            try:
                ret, detail = self._daily_context.unsubscribe([code], [futu.SubType.K_DAY])
                if ret != 0:
                    logging.getLogger(__name__).warning("富途日K退订失败：%s", detail)
            except Exception as exc:
                logging.getLogger(__name__).warning("富途日K退订异常：%s", type(exc).__name__)
            finally:
                self._daily_subscriptions.pop(code, None)
                if not self._daily_subscriptions:
                    self._daily_context.close()
                    self._daily_context = None

    def close_batch(self):
        """批次结束释放已满60秒的订阅；较新的订阅仍由原定时器释放。"""
        with self._lock:
            for code in list(self._daily_subscriptions):
                self._release_daily(code)

    @staticmethod
    def _daily_frame(rows):
        import pandas as pd
        frame = pd.DataFrame(_records(rows)).rename(columns={"time_key":"Date","open":"Open","high":"High","low":"Low","close":"Close","volume":"Volume"})
        if not frame.empty:
            frame["Date"] = pd.to_datetime(frame["Date"]).dt.strftime("%Y-%m-%d")
            frame = frame[["Date", "Open", "High", "Low", "Close", "Volume"]].sort_values("Date").drop_duplicates("Date")
        return frame

    def _history_daily_bars(self, symbol, start, end):
        """超出订阅覆盖时保留历史接口分页。"""
        rows = []
        token = None
        while True:
            data, token = self._call("request_history_kline", code=futu_code(symbol), start=str(start), end=str(end),
                                     ktype="K_DAY", autype="qfq", max_count=1000, page_req_key=token)
            rows.extend(_records(data))
            if not token:
                break
        return self._daily_frame(rows)

    def fundamentals(self, ticker, curr_date):
        from tradingagents.dataflows.date_window import is_historical
        from tradingagents.dataflows.errors import VendorUnavailableError
        if is_historical(curr_date):
            raise VendorUnavailableError("富途当前估值没有历史版本，不能用于回放")
        rows = _records(self._call("get_market_snapshot", code_list=[futu_code(ticker)])[0])
        if not rows:
            raise VendorUnavailableError("富途估值快照为空")
        row = rows[0]
        valuation = self._call("get_valuation_detail", code=futu_code(ticker))[0]
        values = {"官方前收盘": row.get("prev_close_price"), "快照现价（独立列示）": row.get("last_price"),
                  "市盈率TTM": row.get("equity_pe_ratio"), "市净率": row.get("equity_pb_ratio"),
                  "总市值": row.get("equity_market_val"), "52周高": row.get("highest52weeks_price"),
                  "52周低": row.get("lowest52weeks_price"), "快照时间": row.get("update_time"),
                  "估值类型": valuation.get("valuation_type"), "估值分位%": valuation.get("trend", {}).get("valuation_percentile"),
                  "分位时间": valuation.get("last_update_time_str")}
        return _futu_markdown("估值", [values], "估值依据prev_close_price；实时分位按其独立更新时间，非盘前价重算。")

    def insiders(self, ticker, curr_date):
        from datetime import date
        curr_date = curr_date or date.today().isoformat()
        rows = _records(self._call("get_insider_trade_list", code=futu_code(ticker), num=30)[0])
        rows = [row for row in rows if str(row.get("max_trade_date_str", "")) <= curr_date]
        for row in rows:
            row["交易性质"] = "Form 144拟售，非已完成出售" if row.get("is_proposed_sale_of_securities") else "实际交易（以原披露类型为准）"
        return _futu_markdown("内部人交易", rows, "披露日期与成交日期不相同；拟售不计入实际成交。")

    def news(self, ticker, start_date, end_date):
        from tradingagents.dataflows.config import get_config
        from tradingagents.dataflows.errors import VendorUnavailableError
        from datetime import datetime
        cutoff = get_config().get("news_cutoff_utc")
        rows = _records(self._call("get_search_news", keyword=ticker, max_count=30)[0])
        output = []
        for row in rows:
            stamp = str(row.get("publish_time", ""))
            try:
                day = datetime.strptime(stamp.split()[0], "%Y/%m/%d").date().isoformat()
            except ValueError:
                continue
            if start_date <= day <= end_date and not (cutoff and day >= end_date):
                output.append(row)
        if not output:
            raise VendorUnavailableError("富途搜索未返回可核验日期的区间新闻")
        return _futu_markdown("资讯", output, "发布时间仅到日，无法核验日内截止；回放排除截止当日。搜索不保证完整覆盖。")

    def statements(self, statement_type, ticker, freq, curr_date):
        data = self._call("get_financials_statements", code=futu_code(ticker), statement_type=statement_type, financial_type=7 if freq == "annual" else 9, num=8)[0]
        rows = []
        for report in data.get("report_list", []):
            if str(report.get("date_time_str", "")) > curr_date:
                continue
            for item in report.get("item_list", []):
                rows.append({"报告期": report.get("period_text"), "截止日": report.get("date_time_str"),
                             "币种": report.get("currency_code"), **item})
        return _futu_markdown("财务报表", rows, "按报告期列示，同比/环比为百分数；报告期不等于披露日，历史版本未核验。", limit=160)

    def macro(self, indicator, curr_date, look_back_days=365):
        from datetime import date, timedelta
        from tradingagents.dataflows.errors import VendorUnavailableError
        aliases = {"cpi": "CPI同比", "core_cpi": "核心CPI同比", "CPIAUCSL": "CPI同比", "CPILFESL": "核心CPI同比",
                   "unemployment_rate": "失业率", "UNRATE": "失业率", "nonfarm_payrolls": "非农就业", "PAYEMS": "非农就业",
                   "gdp": "GDP", "real_gdp": "GDP", "initial_claims": "初次申请失业救济", "ICSA": "初次申请失业救济",
                   "fed_funds_rate": "联邦基金", "DGS10": "10年期国债", "10y_treasury": "10年期国债"}
        if indicator in {"10y_treasury", "DGS10", "10Ymain", "US.10Ymain"}:
            return self._treasury_yield_futures(curr_date, look_back_days)
        needle = aliases.get(indicator, indicator)
        listing = _records(self._call("get_macro_indicator_list", region="US")[0])
        match = next((row for row in listing if needle in row.get("name", "") and not (needle == "CPI同比" and "核心" in row["name"])), None)
        if match is None:
            raise VendorUnavailableError(f"富途未匹配宏观指标{indicator}")
        rows = _records(self._call("get_macro_indicator_history", indicator_id=int(match["indicator_id"]), time=curr_date, max_count=40)[0])
        start = (date.fromisoformat(curr_date)-timedelta(days=look_back_days)).isoformat()
        from tradingagents.dataflows.config import get_config
        last_day = "<" if get_config().get("news_cutoff_utc") else "<="
        rows = [row for row in rows if start <= str(row.get("release_time", ""))[:10] <= curr_date
                and not (last_day == "<" and str(row.get("release_time", ""))[:10] == curr_date)]
        return _futu_markdown("宏观历史："+match["name"], rows, "按来源发布日期筛选，发布时间字符串的时区未核验；回放排除截止当日。PERCENT数值为比例，如0.025=2.5%，不将统计期当发布时间。")

    def _treasury_yield_futures(self, curr_date, look_back_days):
        """10Y合约以收益率报价，仅使用已完成日K作为宏观代理。"""
        from datetime import date, timedelta
        import futu
        from tradingagents.dataflows.config import get_config
        from tradingagents.dataflows.errors import NoMarketDataError
        from daily_analyzer.context.market_data import previous_trading_day
        configured_end = get_config().get("price_data_end_date")
        end = min(date.fromisoformat(curr_date), date.fromisoformat(configured_end) if configured_end else previous_trading_day(curr_date))
        start = end - timedelta(days=look_back_days)
        from tradingagents.dataflows.errors import VendorUnavailableError
        denied_key = ("treasury_futures_denied",)
        with self._lock:
            if denied_key in self._cache:
                raise VendorUnavailableError(self._cache[denied_key])
        try:
            frame = self._call("get_cur_kline", code="US.10Ymain", num=1000, ktype=futu.KLType.K_DAY, autype=futu.AuType.NONE)[0]
        except VendorUnavailableError as exc:
            if "权限" in str(exc):
                # 本账户缺少 CME 行情权限时，同一批次内不再重复订阅。
                with self._lock:
                    self._cache[denied_key] = f"{exc}（本批次不再重试）"
            raise
        rows = [{"日期":str(row.get("time_key", ""))[:10], "收益率%":row.get("close"), "来源代码":"US.10Ymain"}
                for row in _records(frame) if start.isoformat() <= str(row.get("time_key", ""))[:10] <= end.isoformat()]
        if not rows:
            raise NoMarketDataError("US.10Ymain", "US.10Ymain", "没有已完成的收益率期货日K")
        rows.sort(key=lambda row: row["日期"])
        return _futu_markdown("10年期美债收益率期货代理", rows[-40:],
            f"截至P={end}；US.10Ymain直接以收益率百分数报价，4.240表示4.240%。期货主连为代理，主连换月可能不连续，不等同FRED DGS10现货序列；最多读取最近1000根，不保证覆盖全部请求历史。")

    def calendars(self, start, end, symbols, cutoff):
        from datetime import timedelta
        from zoneinfo import ZoneInfo
        earnings, economics, warnings = [], [], []
        current = start
        while current <= end:
            finish = min(current + timedelta(days=6), end)
            try:
                rows = _records(self._call("get_earnings_calendar", market="US", begin_date=current.isoformat(), end_date=finish.isoformat())[0])
                earnings.extend(row for row in rows if row.get("security") in {futu_code(symbol) for symbol in symbols})
            except Exception as exc:
                warnings.append("财报日历不可用："+type(exc).__name__)
            try:
                page = None
                while True:
                    response = self._call("get_economic_calendar", begin_date=current.isoformat(), end_date=finish.isoformat(), count=100, next_page=page)
                    rows = _records(response[0])
                    for row in rows:
                        if str(row.get("country", "")).upper() not in {"美国", "US", "USA", "UNITED STATES"}:
                            continue
                        from datetime import datetime
                        stamp = row.get("timestamp")
                        if stamp:
                            released = datetime.fromtimestamp(float(stamp), ZoneInfo("America/New_York"))
                            if not current <= released.date() <= finish:
                                continue
                            row["发布时间ET"] = released.isoformat()
                            if float(stamp) > cutoff.timestamp():
                                row["actual"] = "尚未发布"
                        economics.append(row)
                    if len(response) < 3 or not response[2]:
                        break
                    page = response[1]
            except Exception as exc:
                warnings.append("经济日历不可用："+type(exc).__name__)
            current = finish + timedelta(days=1)
        return {"earnings": earnings, "economics": economics, "warnings": list(dict.fromkeys(warnings))}

    def identity(self, ticker):
        rows = _records(self._call("get_stock_basicinfo", market="US", code_list=[futu_code(ticker)])[0])
        result = {"company_name": rows[0].get("name")} if rows else {}
        profile = self._call("get_company_profile", code=futu_code(ticker))[0]
        profile_rows = _records(profile)
        result["business"] = next((str(row.get("value")) for row in profile_rows if row.get("name") == "公司简介"), "")
        return result


def _futu_markdown(title, rows, note="", limit=40):
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo
    text = json.dumps(rows[:limit], ensure_ascii=False, default=str)
    return f"## 富途{title}\n查询时点：{datetime.now(ZoneInfo('America/New_York')).isoformat()}\n{note}\n{text if rows else '无可用记录'}"


_DATA_SOURCE = None
_DATA_SOURCE_LOCK = threading.Lock()


def get_shared_data_source():
    global _DATA_SOURCE
    with _DATA_SOURCE_LOCK:
        if _DATA_SOURCE is None:
            _DATA_SOURCE = FutuDataSource()
    return _DATA_SOURCE
