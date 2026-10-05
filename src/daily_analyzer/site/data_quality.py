"""保存结果的只读数据质量投影，不替历史报告补造证据。"""
from datetime import date, datetime, timedelta
import re
import math
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from daily_analyzer.time_utils import is_trading_day

ET = ZoneInfo('America/New_York')


def stamp(value):
    try:
        value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return value if value.tzinfo else None
    except (ValueError, TypeError):
        return None


def _data(result, key):
    block = (result.get('context_blocks') or {}).get(key) or {}
    return block.get('data') or {}


def quote_quality(result):
    """决策日线与扩展参考分别列示，仅按保存的来源和时间证明。"""
    symbol = result.get('analyzed_symbol') or result.get('symbol')
    anchors = _data(result, 'price_anchors')
    close = (anchors.get('anchors') or {}).get('P_Close') or {}
    source = str(anchors.get('source') or '')
    daily = next((row for row in result.get('data_source_status') or [] if row.get('category') == '日线'), {})
    proved = any(row.get('outcome') == 'success' and row.get('symbol') == symbol and
                 ('SIP' in str(row.get('source')) or 'sip' in str(row.get('source')))
                 for row in daily.get('attempts') or [])
    try:
        close_price = float(close.get('value'))
        valid_price = math.isfinite(close_price) and close_price > 0
    except (ValueError, TypeError):
        close_price, valid_price = None, False
    verified = bool(valid_price and close.get('date') == result.get('price_data_end_date') and
                    anchors.get('symbol') == symbol and 'SIP' in source and proved)
    decision = {'price': close_price if valid_price else None, 'date': close.get('date'), 'source': source,
                'status': '已核实' if verified else '来源/日期证据未核实'}
    references = []
    for key, label in (('after', '最近盘后'), ('overnight', '夜盘'), ('pre', '盘前')):
        row = (_data(result, 'extended_hours').get(symbol) or {}).get(key) or {}
        if not row:
            continue
        minute = bool(row.get('volume_scope'))
        valid = str(row.get('status') or '').startswith('可用') and row.get('session_verified') is not False and stamp(row.get('quote_time')) is not None
        try: valid = valid and math.isfinite(float(row.get('price'))) and float(row['price']) > 0
        except (ValueError, TypeError): valid = False
        warnings = [str(row.get('warning') or '')]
        if 'iex' in str(row.get('source') or '').casefold(): warnings.append('IEX 覆盖不完整')
        warning = '；'.join(dict.fromkeys(part for item in warnings for part in item.split('；') if part))
        references.append({**row, 'label': label, 'display_price': row.get('price') if valid else None,
                           'display_warning': warning,
                           'display_status': row.get('status') if valid else '无有效报价（' + str(row.get('status') or '真实时段时间未知') + '）',
                           'quote_time': row.get('quote_time') or '真实时段时间未知',
                           'volume_label': '时段累计量' if minute else '末笔量（仅参考）' if 'Alpaca' in str(row.get('source')) else '量口径未核实',
                           'volume_value': row.get('cumulative_volume') if minute else row.get('volume'),
                           'range_label': '本时段高/低' if minute else '日线高/低，非本时段' if 'Alpaca' in str(row.get('source')) else '高低口径未核实'})
    summary = f"决策价：{decision['date'] or '日期未知'} 官方收盘 {decision['price'] if decision['price'] is not None else '未提供'}（{decision['status']}，来源 {decision['source'] or '未知'}）"
    for row in references:
        if row['label'] not in {'盘前', '夜盘'}: continue
        if row['display_price'] is None:
            summary += f" · {row['label']}：{row['display_status']}，来源 {row.get('source') or '未知'}"
        else:
            summary += f" · {row['label']} {row['display_price']}（{row['quote_time']}，{row['volume_label']} {row['volume_value'] if row['volume_value'] is not None else '未知'}，来源 {row.get('source') or '未知'}，仅参考）"
        if row['display_warning']: summary += '；' + row['display_warning']
    return {'decision': decision, 'references': references, 'summary': summary}


def _trusted_url(value):
    parsed = urlparse(str(value or ''))
    return parsed.scheme in {'https', 'http'} and bool(parsed.hostname) and parsed.path not in {'', '/'} and not re.search(r'(?i)/(?:quote|quotes|symbol|symbols|stock)/', parsed.path)


def _delivery_facts(text):
    """只提取有限交付事实，评论百分比不作为交付数量。"""
    quarter = re.findall(r'(?i)\bQ([1-4])\b|第([一二三四])季度', text)
    quarters = {a or str('一二三四'.index(b) + 1) for a, b in quarter}
    beats = bool(re.search(r'(?i)beat\w*|topping expectations?|more cars than.*expected|超(?:过|出)?.*预期|比[^；;。\n]{0,40}预期高', text))
    misses = bool(re.search(r'(?i)miss\w*|低于.*预期|比[^；;。\n]{0,40}预期低', text))
    direction = 'beat' if beats and not misses else 'miss' if misses and not beats else None
    numbers = set()
    quantity = r'([1-9]\d{2,}(?:,\d{3})*|[1-9]\d{0,2}(?:,\d{3})+)'
    for match in re.finditer(r'(?i)(?:deliver(?:y|ies|ed)|交付(?:量|总量|数据)?)[\s:：]*' + quantity, text):
        numbers.add(match.group(1).replace(',', ''))
    for match in re.finditer(r'(?i)' + quantity + r'\s+vehicles?\s+deliveries', text):
        numbers.add(match.group(1).replace(',', ''))
    return quarters, direction, numbers


def _issuer_present(text, names):
    for name in names:
        if not name: continue
        if name.isascii():
            if re.search(r'(?i)(?<![A-Za-z0-9])' + re.escape(name) + r'(?![A-Za-z0-9])', text): return True
        elif name in text:
            return True
    return False


def _event_dates(text, year):
    """日期必须出现在交付事实/公布日期句，报告头不能作为事件日期。"""
    dates = set()
    for line in text.splitlines():
        if not re.search(r'(?i)deliver\w*|交付', line): continue
        for raw in re.findall(r'\d{4}-\d{2}-\d{2}', line):
            try: dates.add(date.fromisoformat(raw))
            except ValueError: pass
        if year:
            for month, day in re.findall(r'(?<!\d)(\d{1,2})月(\d{1,2})日', line):
                try: dates.add(date(year, int(month), int(day)))
                except ValueError: pass
    return dates


def _delivery_events(result, names, cutoff):
    """每条证据独立绑定发行人/季度/数量/方向/事件日，不能跨事件合并。"""
    consistency = result.get('consistency_input') or {}
    texts = [str((result.get('reports') or {}).get('news_report') or ''),
             str((consistency.get('reports') or {}).get('news_report') or ''),
             str(result.get('injected_context') or '')]
    events = []
    for text in texts:
        blocks = [block.strip() for block in re.split(r'\n\s*\n|(?=^\s*\[\d{4}-\d{2}-\d{2}\])', text, flags=re.MULTILINE) if block.strip()]
        for index, block in enumerate(blocks):
            clauses = [clause.strip() for clause in re.split(r'[。；;!?]|\.(?:\s|$)|\n', block) if clause.strip()]
            facts = [(clause, *_delivery_facts(clause)) for clause in clauses]
            delivery_count = sum(bool(quantities) for _, _, _, quantities in facts)
            for clause, quarter, direction, quantities in facts:
                # 发行人/季度/交付数量/交付方向均须在同一事实句，股票涨跌或其他发行人不能补证。
                if len(quarter) != 1 or len(quantities) != 1 or not direction or not _issuer_present(clause, names): continue
                dates = _event_dates(clause, cutoff.year if cutoff else None)
                if not dates and delivery_count == 1 and index + 1 < len(blocks):
                    following = blocks[index + 1]
                    # 只有明确紧随该单事件的公布日期段才能承接日期，报告头不参与。
                    if re.match(r'(?i)^(?:交付数据|delivery data)', following):
                        dates = _event_dates(following, cutoff.year if cutoff else None)
                if len(dates) != 1: continue
                events.append({'quarter': next(iter(quarter)), 'quantity': next(iter(quantities)),
                               'direction': direction, 'date': next(iter(dates))})
    return events



def _article_delivery_facts(title, summary, names):
    """新文章只合并标题目标交付主张及同主体交付摘要，不借比较/股票句字段。"""
    delivery = r'(?i)deliver\w*|交付'
    title_delivery = bool(re.search(delivery, title))
    # 标题已明确交付事件时，摘要的比较公司不能补充标题发行人身份。
    if title_delivery and not _issuer_present(title, names):
        return set(), None, set(), False
    clauses = [title] if title_delivery else []
    for clause in re.split(r'[。；;!?]|\.(?:\s|$)|\n', summary):
        if not re.search(delivery, clause): continue
        # 英文明确主体必须在标题中或是目标发行人；无主体短语可承接已绑定标题。
        subject = re.match(r"\s*([A-Z][A-Za-z0-9]*(?:'[sS])?)\b", clause)
        token = subject.group(1).removesuffix("'s").removesuffix("'S") if subject else ''
        # 仅标题交付主语位置已有的名称可作通用别名，不能拿“Analyst”等评论词继承。
        aliases = re.findall(r'\b([A-Z][a-z][A-Za-z0-9]*)\s+(?i:deliver\w*)', title)
        same_subject = bool(token) and (_issuer_present(token, names) or token.casefold() in {alias.casefold() for alias in aliases})
        if not token:
            same_subject = any(name and not name.isascii() and clause.strip().startswith(name) for name in names)
        if not same_subject:
            # 泛称评论/缺主体短语不能继承标题发行人；未明确的字段保持缺失。
            continue
        if not title_delivery and not _issuer_present(clause, names): continue
        clauses.append(clause)
    facts = ' '.join(clauses)
    quarter, direction, quantities = _delivery_facts(facts)
    return quarter, direction, quantities, bool(clauses) and (title_delivery or _issuer_present(facts, names))


def classify_article(article, result):
    """证据不足重大新闻保持红色；跟进只能用已保存的具体事件。"""
    title = str(article.get('title') or article.get('headline') or '')
    text = title + ' ' + str(article.get('summary') or '')
    base = {**article, 'classification': '重大消息未纳入/需核查，建议复跑' if article.get('major') else '一般新增消息',
            'evidence': '', 'folded': False}
    if re.search(r'(?i)^USA\s|美国.*(?:PMI|ISM|非农|失业率|CPI|PCE)', title):
        return dict(base, classification='宏观数据', macro=True, major=False)
    # 原始输入中具体文章id/URL必须在同一条有限事实中，不能靠笼统run_mentions。
    saved = []
    def collect(value):
        if isinstance(value, dict):
            if value.get('url') or value.get('id'):
                saved.append(value)
            for child in value.values(): collect(child)
        elif isinstance(value, list):
            for child in value: collect(child)
    collect(result.get('consistency_input') or {})
    new_q, new_dir, new_n = _delivery_facts(text)
    new_numeric = set(re.findall(r'\b\d+(?:[.,]\d+)*\b', text))
    for item in saved:
        same = bool(article.get('id') and article.get('id') == item.get('id')) or (_trusted_url(article.get('url')) and article.get('url') == item.get('url'))
        old_text = str(item.get('title') or item.get('headline') or '') + ' ' + str(item.get('summary') or '')
        if same and text.strip() == old_text.strip():
            return dict(base, major=False, classification='已纳入同一文章', evidence='具体文章id/URL及事实一致')
        if same and new_numeric - set(re.findall(r'\b\d+(?:[.,]\d+)*\b', old_text)):
            return base
    if re.search(r'(?i)guidance|earnings|preannounce|指引|财报|业绩', text):
        return base
    delivery = bool(re.search(r'(?i)deliver\w*|交付', text))
    symbol = str(result.get('analyzed_symbol') or result.get('symbol') or '')
    names = [symbol, str(result.get('name') or '')]
    new_q, new_dir, new_n, issuer = _article_delivery_facts(title, str(article.get('summary') or ''), names)
    published, cutoff = stamp(article.get('published_at')), stamp(result.get('information_through'))
    commentary = bool(re.search(r'(?i)commentary|comment\w*|analyst|wary|valuation|opinion|解读|评论|估值|分析师|观点', text))
    new_action = bool(re.search(r'(?i)\b(?:new|update\w*|announce\w*|launch\w*|introduc\w*|revis\w*)\b|新(?:增|产品|事实|细节)|更新|宣布|发布新|上调|下调|修订', text))
    if delivery and issuer and commentary and not new_action and len(new_q) == 1 and published and cutoff:
        for event in _delivery_events(result, names, cutoff.astimezone(ET)):
            if event['quarter'] not in new_q or event['direction'] != new_dir or new_n - {event['quantity']}: continue
            event_day = event['date']
            if event_day > cutoff.astimezone(ET).date() or event_day > published.astimezone(ET).date(): continue
            cursor, days = event_day, 0
            while cursor < published.astimezone(ET).date():
                cursor += timedelta(days=1)
                days += int(is_trading_day(cursor))
            if days <= 3:
                return dict(base, major=False, classification='已纳入事件的跟进报道', evidence=f"交付事件 {event_day.isoformat()} · Q{event['quarter']} · 已纳入数量 {event['quantity']}及方向一致")
    if result.get('type') in {'etf', 'index'}:
        symbols = article.get('symbols') or []
        market = bool(re.search(r'(?i)\b(?:market|index|S&P|Nasdaq|Dow|stocks|wall street)\b|大盘|指数|美股', text))
        related = len(symbols) == 1 and symbol in symbols or symbol in symbols[:3]
        if not market and not related and not article.get('major'):
            return dict(base, classification='个股噪声（展开可见）', folded=True)
    return base


def _macro_key(title):
    """只用于同一已保存宏观名称的中英文去重，不猜缺失实际值。"""
    text = str(title).casefold()
    family = None
    if 'ism' in text:
        if re.search(r'services|non.manufacturing|非制造|服务', text): family = 'ism_services'
        elif re.search(r'manufacturing|制造', text): family = 'ism_manufacturing'
    elif re.search(r's&p global|标普全球', text):
        if re.search(r'services|服务', text): family = 'sp_services'
        elif re.search(r'composite|综合', text): family = 'sp_composite'
        elif re.search(r'manufacturing|制造', text): family = 'sp_manufacturing'
    if family is None: return None
    sub = 'pmi' if 'pmi' in text else None
    for key, pattern in (('new_orders', r'new orders|新订单'), ('prices', r'prices|物价'),
                         ('employment', r'employment|就业'), ('supplier', r'supplier|供应商'), ('inventory', r'inventor|库存')):
        if re.search(pattern, text): sub = key
    return (family, sub) if sub else None


def _already_late_macro(result, title, published):
    for late in result.get('late_macro') or []:
        old_title = str(late.get('title') or late.get('headline') or '')
        old_time = stamp(late.get('created_at') or late.get('published_at'))
        if not old_time or not published or old_time.astimezone(ET).date() != published.astimezone(ET).date(): continue
        if old_title.casefold() == str(title).casefold(): return True
        if _macro_key(title) and _macro_key(title) == _macro_key(old_title): return True
    return False


def macro_followups(results, watches, now):
    """只读取存量日历及截止绑定的标题，时钟经过不等于数据公布。"""
    rows, seen = [], set()
    for result in results:
        cutoff = stamp(result.get('information_through'))
        if not cutoff: continue
        data = _data(result, 'macro_releases')
        block = (result.get('context_blocks') or {}).get('macro_releases') or {}
        checked = stamp(data.get('as_of') or block.get('as_of'))
        calendar = data.get('calendars') or {}
        for event in calendar.get('economics') or []:
            published = stamp(event.get('发布时间ET'))
            if not published and event.get('timestamp'):
                try: published = datetime.fromtimestamp(float(event['timestamp']), ET)
                except (ValueError, TypeError): continue
            if not published or published.date() != now.astimezone(ET).date() or published <= cutoff or str(event.get('star')) != 'HIGH': continue
            if _already_late_macro(result, event.get('title'), published): continue
            key = (event.get('title'), published.isoformat())
            if key in seen: continue
            seen.add(key)
            actual = event.get('actual')
            available = bool(actual not in (None, '', '尚未发布', '未发布', '--') and checked and published <= checked <= now)
            rows.append({'title': event.get('title'), 'published_at': published.isoformat(), 'actual': actual if available else '未到',
                         'estimate': event.get('consensus') or '未提供', 'prior': event.get('previous') or '未提供',
                         'status': '已公布未重跑 · 待复核' if available else '待公布' if now < published else '发布时间已过，实际值未到 · 待复核',
                         'source': '富途保存日历', 'checked_at': checked.isoformat() if checked else '来源时点未提供'})
        watch = watches.get(result.get('symbol')) or {}
        if watch.get('run_id') != result.get('run_id') or watch.get('information_through') != result.get('information_through'): continue
        checktime = stamp(watch.get('checked_at'))
        if not checktime or checktime > now: continue
        articles = []
        for article in watch.get('articles') or []:
            published = stamp(article.get('published_at'))
            if not published or not cutoff < published <= now or _already_late_macro(result, article.get('title'), published): continue
            if classify_article(article, result).get('macro'):
                articles.append({'headline': article.get('title'), 'created_at': article.get('published_at')})
        from daily_analyzer.context.providers import _classify_macro_articles
        releases, _, unparsed, _ = _classify_macro_articles(articles)
        releases += unparsed
        for event in releases:
            key = (event.get('title'), event.get('created_at'))
            if key in seen: continue
            seen.add(key)
            rows.append({**event, 'title': event.get('title') or event.get('name'), 'published_at': event.get('created_at'),
                         'estimate': event.get('estimate') or '未提供', 'prior': event.get('prior') or '未提供',
                         'actual': event.get('actual') or '未到', 'status': '已公布未重跑 · 待复核' if event.get('actual') else '实际值未到 · 待复核',
                         'source': watch.get('source') or '保存的宏观标题', 'checked_at': checktime.isoformat()})
    return rows


def macro_review_marks(result, events):
    """逐标的复核标识仅绑定正文明确关联的已保存经济事件。"""
    texts = [str(result.get(key) or '') for key in ('final_trade_decision', 'trader_investment_plan', 'investment_plan')]
    texts.append(str((result.get('reports') or {}).get('final_trade_decision') or ''))
    sentences = [sentence for text in texts for sentence in re.split(r'[。\n]', text)
                 if re.search(r'(?:发布|公布|数据)[^。\n]{0,60}后[^。\n]{0,12}复核', sentence)]
    marks = []
    for event in events:
        title = str(event.get('title') or '')
        published = stamp(event.get('published_at'))
        tokens = set(re.findall(r'(?i)ISM|PMI|CPI|PCE|GDP|非农|失业率|零售销售', title))
        associated = False
        for sentence in sentences:
            same_tokens = any(token.casefold() in sentence.casefold() for token in tokens)
            dated_data = published and '数据' in sentence and (published.astimezone(ET).strftime('%m-%d') in sentence or
                        f'{published.astimezone(ET).month}月{published.astimezone(ET).day}日' in sentence)
            if title in sentence or same_tokens or dated_data:
                associated = True
        if associated:
            marks.append({'title': title, 'status': '已公布，未重跑' if '已公布' in event['status'] else '待复核：' + title,
                          'detail': event['status']})
    return marks
