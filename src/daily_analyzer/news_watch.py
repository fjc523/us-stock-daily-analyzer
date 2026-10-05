"""查看器只检查截止后消息，只写独立提示文件，不启动分析。"""
from datetime import datetime, time
from pathlib import Path
import logging
import os
import re
import threading
from daily_analyzer.config import load_credentials, load_watchlist, load_settings
from daily_analyzer.data_sources.alpaca import AlpacaDataSource
from daily_analyzer.storage import atomic_write_json, read_json
from daily_analyzer.time_utils import NEW_YORK, is_trading_day
from daily_analyzer.site import symbol_slug

_LOG = logging.getLogger(__name__)
MAJOR_KEYWORDS = (
    r'\b(?:deliveries|delivery|production|earnings|results|guidance|preannounce|upgrade|downgrade)\b',
    r'\b(?:price target|acquire[sd]?|acquisition|merger|offering|sec|investigation|recall|lawsuit)\b',
    r'\b(?:ceo|cfo|executive)\b.*\b(?:resign\w*|depart\w*|appoint\w*|step\w* down)\b',
    r'交付|产量|财报|业绩|指引|评级|目标价|并购|收购|融资|增发|监管|调查|召回|诉讼|高管变动|首席.*(?:辞职|离职|任命)',
)
_MAJOR = re.compile('|'.join(MAJOR_KEYWORDS), re.IGNORECASE)


def is_major(article):
    return bool(_MAJOR.search(str(article.get('headline', '')) + ' ' + str(article.get('summary', ''))))


def _time(value):
    if not value: return None
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result if result.tzinfo else result.replace(tzinfo=NEW_YORK)
    except ValueError: return None


def check_news(root, *, now=None, source=None):
    """一次多标的查询，按各自报告起点筛选；失败由下一轮重试。"""
    root = Path(root)
    now = (now or datetime.now(NEW_YORK)).astimezone(NEW_YORK)
    if not is_trading_day(now.date()) or not time(4) <= now.time() < time(20): return None
    selected = {}
    for item in load_watchlist(root).active_items:
        result = read_json(root / 'data/runs' / now.date().isoformat() / 'current' / f'{symbol_slug(item.symbol)}.json', {})
        cutoff = _time(result.get('information_through'))
        if result.get('status') == 'success' and cutoff and cutoff < now:
            selected[item.symbol] = (item.analysis_symbol, result.get('run_id'), cutoff, result['information_through'])
    if not selected: return None
    if source is None:
        credentials = load_credentials(root)
        for name, secret in [('APCA_API_KEY_ID', credentials.alpaca_key_id), ('APCA_API_SECRET_KEY', credentials.alpaca_secret_key)]:
            if secret is not None: os.environ.setdefault(name, secret.get_secret_value())
        source = AlpacaDataSource()
    from tradingagents.dataflows.config import run_config
    with run_config({'alpaca_requests_per_minute':load_settings(root).alpaca.requests_per_minute}):
        response = source.news(list(dict.fromkeys(row[0] for row in selected.values())), min(row[2] for row in selected.values()), now, limit=None)
    rows = {}
    for symbol, (proxy, run_id, cutoff, cutoff_text) in selected.items():
        articles, seen = [], set()
        for article in response.get('articles', []):
            published = _time(article.get('created_at'))
            key = article.get('id') or article.get('url') or (article.get('headline'), article.get('created_at'))
            if proxy not in article.get('symbols', []) or not published or not cutoff < published <= now or key in seen: continue
            seen.add(key)
            articles.append({'title':article.get('headline',''), 'summary':article.get('summary',''),
                             'id': article.get('id'), 'symbols': article.get('symbols', []),
                             'published_at':published.isoformat(), 'url':article.get('url',''), 'major':is_major(article)})
        rows[symbol] = {'run_id':run_id, 'information_through':cutoff_text, 'count':len(articles),
                        'major':any(row['major'] for row in articles), 'articles':articles}
    payload = {'checked_at':now.isoformat(), 'trade_date':now.date().isoformat(), 'source':'Alpaca',
               'truncated':bool(response.get('truncated')), 'items':rows}
    atomic_write_json(root / 'data/news_watch.json', payload)
    return payload


class NewsWatcher:
    def __init__(self, root, *, checker=check_news, interval=600):
        self.root, self.checker, self.interval = root, checker, interval
        self.stopped = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.thread = threading.Thread(target=self._run, daemon=True, name='news-watch')
        self.thread.start()

    def _run(self):
        while not self.stopped.is_set():
            try: self.checker(self.root)
            except Exception as exc: _LOG.warning('截止后新闻检查失败：%s，下轮重试', type(exc).__name__)
            if self.stopped.wait(self.interval): break

    def stop(self):
        self.stopped.set()
        if self.thread: self.thread.join(timeout=5)
