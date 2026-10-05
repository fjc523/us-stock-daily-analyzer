"""批次共享的扩展分钟查询：完整终点、同源字段与有限请求。"""
from collections import deque
from datetime import datetime, time, timedelta
import math
import threading
import time as runtime
from zoneinfo import ZoneInfo

from daily_analyzer.data_sources.futu import _records, futu_code
from daily_analyzer.time_utils import session_bounds

ET = ZoneInfo('America/New_York')


class RequestBudget:
    """所有扩展分钟源共用60次/30秒；每次重试也计数。"""
    def __init__(self, clock=runtime.monotonic, sleep=runtime.sleep):
        self.clock, self.sleep = clock, sleep
        self.calls, self.lock, self.total = deque(), threading.Lock(), 0

    def acquire(self):
        while True:
            with self.lock:
                now = self.clock()
                while self.calls and now - self.calls[0] >= 30:
                    self.calls.popleft()
                if len(self.calls) < 60:
                    self.calls.append(now)
                    self.total += 1
                    return
                delay = self.calls[0] + 30 - now
            self.sleep(max(0, delay))


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def minute_summary(rows, source, start, end, *, cutoff, now):
    """合成fixture和生产raw使用同一终点规则；零量行不能冒充成交。"""
    futu = source == 'futu'
    allowed = min(end, cutoff, now if futu or source == 'boats' else now - timedelta(minutes=15))
    normalized = {}
    for row in rows:
        try:
            raw = datetime.fromisoformat(str(row.get('time_key') if futu else row.get('t')).replace('Z', '+00:00'))
            if raw.tzinfo is None:
                if not futu: continue
                raw = raw.replace(tzinfo=ET)
            stamp = raw if futu else raw + timedelta(minutes=1)
        except (ValueError, TypeError):
            continue
        if stamp.second or stamp.microsecond or not start < stamp <= allowed:
            continue
        volume = _number(row.get('volume') if futu else row.get('v'))
        price = _number(row.get('close') if futu else row.get('c'))
        high, low = _number(row.get('high') if futu else row.get('h')), _number(row.get('low') if futu else row.get('l'))
        if volume is None or volume < 0 or price is None or price <= 0:
            continue
        normalized[stamp] = {'price': price, 'volume': volume, 'high': high, 'low': low}
    traded = [(stamp, row) for stamp, row in sorted(normalized.items()) if row['volume'] > 0]
    result = {'source': '富途ALL完整分钟' if futu else 'Alpaca feed=' + source + ' 完整分钟',
              'time_field': 'futu_kline.time_key' if futu else 'sip_minute.t',
              'volume_scope': '富途本时段口径' if futu else 'SIP全市场本时段口径' if source == 'sip' else 'boats夜盘本时段口径',
              'cumulative_volume': sum(row['volume'] for row in normalized.values()),
              'traded_minutes': len(traded), 'price': None, 'quote_time': None, 'high': None, 'low': None,
              'status': '无成交', 'session_verified': True, 'allowed_endpoint': allowed.isoformat(), 'adjustment': 'raw'}
    if allowed <= start:
        result['status'] = '时段尚未开始'
    if traded:
        last, row = traded[-1]
        result.update(price=row['price'], quote_time=last.isoformat(),
                      high=max((row['high'] for _, row in traded if row['high'] is not None), default=None),
                      low=min((row['low'] for _, row in traded if row['low'] is not None), default=None), status='可用')
    return result


class ExtendedMinuteBatch:
    """一个批次一个实例；缓存原始分钟，按每个查询截止重新过滤。"""
    def __init__(self, alpaca, *, context_factory=None, host='127.0.0.1', port=11111,
                 futu_enabled=True, clock=None, options=None, timeout=10, budget=None):
        self.alpaca, self.context_factory = alpaca, context_factory
        self.host, self.port, self.futu_enabled = host, port, futu_enabled
        self.clock = clock or (lambda: datetime.now(ET))
        self.options, self.timeout = options or {}, timeout
        self.budget = budget or RequestBudget()
        self.lock = threading.RLock()
        self.cache, self.sip_cache, self.errors = {}, {}, {}
        self.health, self.symbols, self.prepared = {}, [], False
        self.history_attempts, self.history_pages = {}, {}
        self.history_lock = threading.Lock()
        self.ranges = {}
        self.used_codes, self.remaining = set(), None
        self.quota_error = None

    def _factory(self):
        if self.context_factory is not None:
            return self.context_factory
        from futu import OpenQuoteContext
        return OpenQuoteContext

    def _bounded_once(self, query):
        """每次尝试拥有独立取消标识，迟到线程不能进入后一次结果。"""
        done, abandoned, lock = threading.Event(), threading.Event(), threading.Lock()
        holder = {}
        def close(context):
            try: context.close()
            except Exception: pass
        def worker():
            context = None
            try:
                context = self._factory()(host=self.host, port=self.port)
                with lock:
                    holder['context'] = context
                    cancelled = abandoned.is_set()
                if cancelled: return
                result = query(context)
                with lock:
                    if not abandoned.is_set(): holder['result'] = result
            except Exception as exc:
                with lock:
                    if not abandoned.is_set(): holder['error'] = exc
            finally:
                done.set()
                if context is not None: close(context)
        threading.Thread(target=worker, daemon=True, name='扩展分钟受限查询').start()
        if not done.wait(self.timeout):
            with lock:
                abandoned.set()
                context = holder.get('context')
            if context is not None:
                threading.Thread(target=close, args=(context,), daemon=True, name='扩展分钟超时清理').start()
            raise TimeoutError('富途分钟10秒超时')
        if 'error' in holder: raise holder['error']
        if 'result' not in holder: raise RuntimeError('富途查询未返回结果')
        return holder['result']

    def _bounded(self, query):
        """超时后不能发布局部结果；重试使用独立连接。"""
        for attempt in range(2):
            self.budget.acquire()
            try:
                return self._bounded_once(query)
            except Exception:
                if attempt == 1: raise

    def prepare(self, symbols, trade_day, price_end, cutoff):
        with self.lock:
            self.symbols = list(dict.fromkeys([*self.symbols, *symbols]))
            if self.prepared: return
            self.prepared = True
            self.trade_day, self.price_end = trade_day, price_end
            prior_natural = trade_day - timedelta(days=1)
            self.ranges = {'today': (trade_day, trade_day), 'history': (min(price_end, prior_natural), prior_natural)}
            self.health = {'checked_at': self.clock().isoformat(), 'symbols': list(self.symbols),
                           'futu': {'status': '未启用'}, 'sip': {'status': '未核验'}}
            if self.futu_enabled:
                def inspect(context):
                    market = context.get_market_state([futu_code(symbol) for symbol in self.symbols])
                    self.budget.acquire()
                    quota = context.get_history_kl_quota(get_detail=True)
                    return market, quota
                try:
                    market_answer, quota_answer = self._bounded(inspect)
                    market_state = {'ret': market_answer[0], 'status': '可达，非分钟权限证明' if market_answer[0] == 0 else '失败',
                                    'reason': '' if market_answer[0] == 0 else str(market_answer[1])[:160]}
                    quota_state = {'ret': quota_answer[0], 'status': '已核查' if quota_answer[0] == 0 else '失败',
                                   'reason': '' if quota_answer[0] == 0 else str(quota_answer[1])[:160]}
                    self.quota_error = quota_state['reason'] or None
                    quota = quota_answer[1] if quota_answer[0] == 0 else None
                    if isinstance(quota, (tuple, list)) and len(quota) >= 2:
                        self.remaining = int(quota[1])
                        self.used_codes = {str(row.get('code')) for row in (quota[2] if len(quota) > 2 else []) or []}
                    elif isinstance(quota, dict):
                        self.remaining = int(quota['remain']) if quota.get('remain') is not None else None
                        self.used_codes = set(quota.get('detail_codes') or [])
                    self.health['futu'] = {'status': '可达，分钟权限待实际查询' if market_answer[0] == quota_answer[0] == 0 else 'preflight部分失败，按实际接口降级',
                                           'market_state': market_state, 'history_quota': quota_state, 'remaining': self.remaining,
                                           'used_codes': sorted(self.used_codes), 'warning': '历史额度低于20' if self.remaining is not None and self.remaining < 20 else ''}
                except Exception as exc:
                    self.health['futu'] = {'status': '失败', 'reason': type(exc).__name__ + '：' + str(exc)[:120]}
            # 第一个合法SIP分钟请求即体检；结果同时进入缓存，不另取snapshot。
            start = datetime.combine(trade_day, time(4), ET)
            end = min(cutoff, self.clock() - timedelta(minutes=15))
            if end <= start:
                _, start = session_bounds(price_end)
                end = datetime.combine(price_end, time(20), ET)
                end = min(end, cutoff, self.clock() - timedelta(minutes=15))
            if start < end:
                try:
                    self._sip('sip', start, end)
                    self.health['sip'] = {'status': '分钟接口可达', 'start': start.isoformat(), 'end': end.isoformat()}
                except Exception as exc:
                    self.health['sip'] = {'status': '失败', 'reason': type(exc).__name__ + '：' + str(exc)[:120]}
            else:
                self.health['sip'] = {'status': '尚无合法可见分钟范围'}

    def _futu(self, symbol, key):
        cache_key = symbol, key
        if cache_key in self.cache: return self.cache[cache_key]
        if cache_key in self.errors: raise RuntimeError(self.errors[cache_key])
        if not self.futu_enabled: raise RuntimeError('富途未启用')
        code = futu_code(symbol)
        if self.remaining is None and code not in self.used_codes:
            raise RuntimeError('历史额度查询失败：' + self.quota_error if self.quota_error else '历史额度未知，未用代码不可保证权限')
        if code not in self.used_codes and self.remaining <= 0:
            raise RuntimeError('富途历史代码额度不足')
        start, end = self.ranges[key]
        rows, token, seen = [], None, set()
        try:
            for page in range(8):
                def query(context):
                    with self.history_lock:
                        if self.history_attempts.get(symbol, 0) >= 32:
                            raise RuntimeError('单标的32次历史调用预算耗尽')
                        self.history_attempts[symbol] = self.history_attempts.get(symbol, 0) + 1
                    if self.context_factory is None:
                        from futu import KLType, AuType, Session
                        ktype, autype, session = KLType.K_1M, AuType.NONE, Session.ALL
                    else:
                        ktype, autype, session = 'K_1M', 'NONE', 'ALL'
                    answer = context.request_history_kline(code, start=start.isoformat(), end=end.isoformat(),
                        ktype=ktype, autype=autype, extended_time=True, session=session, max_count=1000, page_req_key=token)
                    if answer[0] != 0: raise RuntimeError('富途分钟查询失败：' + str(answer[1])[:120])
                    return answer[1], answer[2]
                data, token = self._bounded(query)
                self.history_pages[symbol] = self.history_pages.get(symbol, 0) + 1
                rows.extend(_records(data))
                if not token:
                    self.cache[cache_key] = rows
                    if code not in self.used_codes:
                        self.used_codes.add(code)
                        if self.remaining is not None: self.remaining -= 1
                    return rows
                marker = repr(token)
                if marker in seen: raise RuntimeError('富途分页token循环')
                seen.add(marker)
            raise RuntimeError('富途8页预算耗尽，累计量不完整')
        except Exception as exc:
            self.errors[cache_key] = type(exc).__name__ + '：' + str(exc)[:120]
            raise

    def _sip(self, feed, start, end):
        allowed = min(end, self.clock() - timedelta(minutes=15)) if feed == 'sip' else min(end, self.clock())
        if allowed <= start: return {symbol: [] for symbol in self.symbols}
        # 大范围缓存能用于较早cutoff，归一时再次过滤；新增代码才查询缺失集合。
        merged = {}
        for (cached_feed, cached_start, cached_end, symbols), rows in self.sip_cache.items():
            if cached_feed == feed and cached_start <= start and cached_end >= allowed:
                merged.update({symbol: rows.get(symbol) or [] for symbol in self.symbols if symbol in symbols})
        missing = [symbol for symbol in self.symbols if symbol not in merged]
        if not missing: return merged
        key = feed, start, allowed, tuple(self.symbols)
        error_key = 'sip', feed, start, allowed, tuple(missing)
        if error_key in self.errors: raise RuntimeError(self.errors[error_key])
        try:
            rows = self.alpaca.complete_minute_bars(missing, start, allowed, feed=feed, request_limiter=self.budget)
        except Exception as exc:
            self.errors[error_key] = type(exc).__name__ + '：' + str(exc)[:120]
            raise
        merged.update({symbol: rows.get(symbol) or [] for symbol in missing})
        self.sip_cache[key] = merged
        return merged

    def segment(self, symbol, session, start, end, cutoff, *, close=None, adv20=None, backfill=False):
        with self.lock:
            if symbol not in self.symbols: raise ValueError('代码不在当前批次允许集合')
            feed = 'boats' if session == 'overnight' else 'sip'
            priority = ('futu', feed) if session in {'pre', 'overnight'} else (feed, 'futu')
            if backfill: priority = (feed, 'futu')
            candidates, failures = [], []
            for source in priority:
                try:
                    if source == 'futu':
                        keys = ['history'] if end.date() < self.trade_day else ['today']
                        if start.date() < self.trade_day <= end.date(): keys = ['history', 'today']
                        rows = [row for key in keys for row in self._futu(symbol, key)]
                    else:
                        rows = self._sip(source, start, min(end, cutoff)).get(symbol) or []
                    candidates.append(minute_summary(rows, source, start, end, cutoff=cutoff, now=self.clock()))
                except Exception as exc:
                    failures.append({'source': source, 'reason': type(exc).__name__ + '：' + str(exc)[:120]})
            chosen = next((row for row in candidates if row['status'] == '可用'), candidates[0] if candidates else
                          {'price': None, 'quote_time': None, 'status': '取源失败', 'session_verified': False})
            chosen = dict(chosen, source_failures=failures, official_previous_close=close, benchmark_verified=close is not None)
            chosen['primary_source'] = priority[0]
            chosen['fallback_used'] = bool(chosen.get('source') and ((priority[0] == 'futu') != chosen['source'].startswith('富途')))
            chosen['change_pct'] = (chosen['price'] / close - 1) * 100 if chosen.get('price') and close else None
            others = [row for row in candidates if row is not next((row for row in candidates if row['status'] == '可用'), candidates[0] if candidates else None) and row.get('price')]
            chosen['cross_check'] = [{key: row.get(key) for key in ('source', 'price', 'quote_time', 'cumulative_volume')} for row in others]
            if chosen.get('price') and any(abs(row['price'] / chosen['price'] - 1) > .005 for row in others):
                chosen['warning'] = '来源价差超过0.5%'
            now = self.clock()
            if chosen.get('quote_time'):
                age = (cutoff - datetime.fromisoformat(chosen['quote_time'])).total_seconds()
                chosen['age_seconds'] = max(0, age)
                ended = cutoff >= end
                limit = 45 * 60 if 'feed=sip' in chosen.get('source', '') else 30 * 60
                if not ended and age > limit: chosen['status'] = '过期'
                if ended: chosen['warning'] = '；'.join(filter(None, [chosen.get('warning'), '已结束时段，仅参考']))
            # raw分钟与复权日线量不能直接作比，缺少单位/adjustment证据明确未知。
            compatible = adv20 and adv20.get('adjustment') == 'raw' and adv20.get('source') == 'sip' and adv20.get('count') == 20
            chosen['adv20'] = adv20.get('value') if compatible else None
            chosen['adv20_status'] = '已核实同口径' if compatible else '20日均量口径未核实'
            ratio = chosen.get('cumulative_volume', 0) / chosen['adv20'] if chosen.get('adv20') else None
            chosen['volume_adv20_ratio'] = ratio
            enabled = self.options.get('thin_enabled', True)
            thin = enabled and ((ratio is not None and ratio < self.options.get('thin_adv20_ratio', .0005)) or
                               (chosen.get('traded_minutes') is not None and chosen['traded_minutes'] < self.options.get('thin_min_traded_minutes', 10)))
            chosen['liquidity_note'] = '成交稀薄，仅列示' if thin else '稀薄阈值已关闭' if not enabled else ''
            return chosen
