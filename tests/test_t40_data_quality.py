"""T40追加只读展示及live类型合同，全部来源和模型均固定mock。"""
from datetime import datetime
from unittest.mock import MagicMock, patch

from daily_analyzer.live_information import _wrap, live_information_scope
from daily_analyzer.site import _source_status
from daily_analyzer.site.data_quality import classify_article, macro_followups, quote_quality, macro_review_marks
from tradingagents.dataflows.config import get_config, run_config
from tradingagents.dataflows.social_result import SocialResult


def test_live_social_attributes_and_offclock_exact():
    value = SocialResult('正文', available=False, effective_posts=0)
    value.source_reason = 'HTTP 429；' + '长正文' * 100
    value.source_outcome = 'failed'
    value.extra = {'任意属性': [1, 2]}
    clock = lambda: datetime.fromisoformat('2026-10-05T08:30:00-04:00')
    wrapped = _wrap(lambda: value)
    with run_config({**get_config(), '_daily_live_information_clock': clock, 'news_cutoff_utc': None}), live_information_scope(clock):
        live = wrapped()
    assert type(live) is SocialResult and str(live).startswith('正文\n\n本次信息检索截止')
    assert all(live.__dict__[key] == original for key, original in value.__dict__.items())
    assert live._daily_live_display_reason == 'HTTP 429'
    assert not hasattr(value, '_daily_live_information_cutoff')
    with run_config({**get_config(), '_daily_live_information_clock': clock, 'news_cutoff_utc': '冻结'}), live_information_scope(clock):
        assert wrapped() is value
    assert wrapped() is value


def test_live_sentiment_four_zero_failure():
    import tradingagents.agents.analysts.sentiment_analyst as module
    clock = lambda: datetime.fromisoformat('2026-10-05T08:30:00-04:00')
    config = {**get_config(), 'stocktwits_enabled': False, 'sentiment_min_social_posts': 3,
              '_daily_live_information_clock': clock, 'news_cutoff_utc': None}
    for available, count in ((True, 4), (True, 0), (False, 0)):
        original = SocialResult('不得进入原因的帖子正文', available=available, effective_posts=count)
        original.source_reason = 'HTTP 429；原长正文' if not available else None
        with patch.object(module.get_news, 'func', return_value='新闻'), patch.object(module, 'jev_screen', return_value=None), patch.object(module, 'fetch_reddit_posts', _wrap(lambda *a, **k: original)), patch.object(module, 'invoke_structured_or_freetext', return_value='固定评分') as invoke, run_config(config), live_information_scope(clock):
            result = module.create_sentiment_analyst(MagicMock(), config)({'company_of_interest': 'TSLA', 'trade_date': '2026-10-05', 'messages': []})
        assert invoke.called == (count >= 3)
        if count == 0:
            assert '不得进入原因' not in result['sentiment_report']
            assert ('Reddit 正常（0 条）' if available else 'HTTP 429') in result['sentiment_report']


def test_applicable_source_denominator_keeps_all_rows():
    records = [{'category': str(i), 'status': status} for i, status in enumerate(['正常'] * 8 + ['降级', '跳过', '失败', '未使用', '未配置', '未开通/不可行'])]
    value = _source_status({'data_source_status': records})
    assert value['total'] == value['normal'] + value['degraded'] + value['failed'] + value['skipped'] == 11
    assert value['inactive'] == 2 and value['unused'] == 1 and len(value['rows']) == 14


def test_quote_decision_proof_and_old_reference_labels():
    result = {'symbol': 'ABC', 'price_data_end_date': '2026-10-02', 'context_blocks': {
        'price_anchors': {'data': {'symbol': 'ABC', 'source': 'Alpaca SIP adjustment=all', 'anchors': {'P_Close': {'value': 12, 'date': '2026-10-02'}}}},
        'extended_hours': {'data': {'ABC': {'overnight': {'price': 13, 'source': 'Alpaca feed=overnight', 'volume': 100}}}}},
        'data_source_status': [{'category': '日线', 'attempts': [{'outcome': 'success', 'symbol': 'ABC', 'source': 'Alpaca SIP adjustment=all'}]}]}
    output = quote_quality(result)
    assert output['decision']['status'] == '已核实'
    assert output['references'][0]['volume_label'] == '末笔量（仅参考）'
    assert output['references'][0]['quote_time'] == '真实时段时间未知'
    result['price_data_end_date'] = '2026-10-01'
    assert quote_quality(result)['decision']['status'] != '已核实'


def test_delivery_followup_conservative_facts():
    result = {'symbol': 'ABC', 'name': 'Example', 'information_through': '2026-10-05T08:30:00-04:00',
              'reports': {'news_report': '[2026-10-02] ABC Q3 deliveries 486,532 vehicles beating estimates'}}
    article = {'title': 'ABC Delivered More Cars Than Wall Street Expected', 'summary': 'ABC Q3 delivery follow-up commentary', 'published_at': '2026-10-05T08:54:00-04:00', 'major': True}
    assert classify_article(article, result)['classification'] == '已纳入事件的跟进报道'
    for summary in ('new guidance 500,000', 'Q3 deliveries 500,000 vehicles', 'Q4 deliveries beat estimates', 'new earnings results 200'):
        assert classify_article({**article, 'summary': summary}, result)['major']
    assert classify_article({**article, 'published_at': '2026-10-09T08:54:00-04:00'}, result)['major']
    etf = {'symbol': 'SPY', 'type': 'etf'}
    assert classify_article({'title': 'Unrelated company contract', 'symbols': ['ABC'], 'major': False}, etf)['folded']
    assert not classify_article({'title': 'Unrelated company contract', 'symbols': ['SPY'], 'major': False}, etf)['folded']


def test_macro_clock_no_actual_is_not_published():
    result = {'symbol': 'ABC', 'run_id': 'run', 'information_through': '2026-10-05T08:30:00-04:00',
              'context_blocks': {'macro_releases': {'data': {'as_of': '2026-10-05T08:30:00-04:00', 'calendars': {'economics': [
                  {'title': '美国ISM', 'star': 'HIGH', '发布时间ET': '2026-10-05T10:00:00-04:00', 'actual': '尚未发布', 'consensus': '52', 'previous': '51'}]}}}}}
    assert macro_followups([result], {}, datetime.fromisoformat('2026-10-05T09:59:00-04:00'))[0]['status'] == '待公布'
    assert '实际值未到' in macro_followups([result], {}, datetime.fromisoformat('2026-10-05T10:05:00-04:00'))[0]['status']
    event = result['context_blocks']['macro_releases']['data']['calendars']['economics'][0]
    event['actual'] = '53'
    # 来源检查时点早于发布，不能因有一个数字就称已公布。
    assert '实际值未到' in macro_followups([result], {}, datetime.fromisoformat('2026-10-05T10:05:00-04:00'))[0]['status']
    result['context_blocks']['macro_releases']['data']['as_of'] = '2026-10-05T10:03:00-04:00'
    assert '已公布未重跑' in macro_followups([result], {}, datetime.fromisoformat('2026-10-05T10:05:00-04:00'))[0]['status']


def test_review_counterexamples_event_date_new_facts_and_missing_quarter():
    article = {'title': 'ABC Q3 delivery commentary beating estimates', 'summary': 'Analyst opinion',
               'published_at': '2026-10-05T08:54:00-04:00', 'major': True}
    result = {'symbol': 'ABC', 'information_through': '2026-10-05T08:30:00-04:00', 'reports': {
        'news_report': '报告2026-10-05\n[2026-08-01] ABC Q3 deliveries 486,532 vehicles beating estimates'}}
    assert classify_article(article, result)['major']
    result['reports']['news_report'] = '[2026-10-02] ABC Q3 deliveries 486,532 vehicles beating estimates'
    for changes in ({'summary': 'New product launch'}, {'summary': 'New details announced today'},
                    {'title': 'ABC deliveries beating estimates'}, {'summary': 'Delivery update commentary'}):
        assert classify_article({**article, **changes}, result)['major']
    assert not classify_article(article, result)['major']
    assert classify_article({**article, 'title': 'ABC Delivered More Cars Than Wall Street Expected', 'summary': 'Follow-up commentary'}, result)['major']
    # 不能把其他发行人的同季度数量/日期或另一季度拼到ABC当前事件。
    for report in ('[2026-10-02] XYZ Q3 deliveries 486,532 vehicles beating estimates',
                   'ABC Q3 deliveries 486,532 vehicles beating estimates\n\n[2026-10-02] XYZ Q4 deliveries 500,000 vehicles beating estimates'):
        result['reports']['news_report'] = report
        assert classify_article(article, result)['major']


def test_chinese_single_event_adjacent_explicit_date_and_nonfinite_price():
    result = {'symbol': 'ABC', 'information_through': '2026-10-05T08:30:00-04:00', 'reports': {
        'news_report': '## ABC 新闻分析 2026-10-05\n\nABC第三季度交付486,532辆，交付超预期。\n\n交付数据在10月2日开盘前公布。'}}
    article = {'title': 'ABC Delivered More Cars Than Expected, Analyst Still Wary',
               'summary': 'ABC beating Q3 delivery estimates, valuation commentary', 'published_at': '2026-10-05T08:54:00-04:00', 'major': True}
    output = classify_article(article, result)
    assert not output['major'] and '2026-10-02' in output['evidence']
    result['context_blocks'] = {'price_anchors': {'data': {'symbol': 'ABC', 'source': 'Alpaca SIP',
                               'anchors': {'P_Close': {'value': float('inf'), 'date': '2026-10-02'}}}}}
    result['price_data_end_date'] = '2026-10-02'
    result['data_source_status'] = [{'category': '日线', 'attempts': [{'outcome': 'success', 'symbol': 'ABC', 'source': 'SIP'}]}]
    assert quote_quality(result)['decision']['status'] != '已核实'
    assert quote_quality(result)['decision']['price'] is None


def test_macro_late_calendar_dedup_and_row_marks_no_unrelated_event():
    result = {'symbol': 'ABC', 'run_id': 'run', 'information_through': '2026-10-05T08:30:00-04:00',
        'final_trade_decision': 'ISM公布后复核', 'late_macro': [{'title': 'US ISM Services PMI', 'created_at': '2026-10-05T10:00:00-04:00'}],
        'context_blocks': {'macro_releases': {'data': {'as_of': '2026-10-05T10:05:00-04:00', 'calendars': {'economics': [
        {'title': 'US ISM Services PMI', '发布时间ET': '2026-10-05T10:00:00-04:00', 'star': 'HIGH', 'actual': '55'}]}}}}}
    now = datetime.fromisoformat('2026-10-05T10:05:00-04:00')
    assert macro_followups([result], {}, now) == []
    result['late_macro'] = []
    events = macro_followups([result], {}, now)
    assert macro_review_marks(result, events)[0]['status'] == '已公布，未重跑'
    result['final_trade_decision'] = '财报发布后复核'
    assert macro_review_marks(result, events) == []
    result['final_trade_decision'] = '10-05数据后复核'
    assert macro_review_marks(result, events)
    result['late_macro'] = [{'title': 'USA ISM Services PMI 55 Vs 54 Est.', 'created_at': '2026-10-05T10:00:00-04:00'}]
    result['context_blocks']['macro_releases']['data']['calendars']['economics'][0]['title'] = '美国9月ISM非制造业PMI'
    assert macro_followups([result], {}, now) == []
    result['late_macro'][0]['title'] = 'USA ISM Services New Orders 55 Vs 54 Est.'
    assert macro_followups([result], {}, now)


def test_invalid_old_pre_reference_not_labeled_valid():
    result = {'symbol': 'ABC', 'context_blocks': {'extended_hours': {'data': {'ABC': {'pre': {
        'price': 194.91, 'quote_time': '2026-10-02T15:59:59-04:00', 'source': 'Alpaca feed=iex',
        'status': '非本时段数据', 'session_verified': False, 'volume': 100}}}}}}
    quality = quote_quality(result)
    assert quality['references'][0]['display_price'] is None
    assert '盘前：无有效报价' in quality['summary'] and '194.91' not in quality['summary']


def test_actual_home_row_macro_mark_and_time_quality_visible(tmp_path):
    from daily_analyzer.site import render_home
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/watchlist.yaml').write_text('items:\n  - {symbol: ABC, type: stock}\n')
    result = {'symbol': 'ABC', 'type': 'stock', '_date': '2026-10-05', '_slug': 'ABC', 'run_id': 'run',
              'status': 'success', 'information_through': '2026-10-05T08:30:00-04:00',
              'final_trade_decision': 'ISM公布后复核',
              'context_blocks': {'macro_releases': {'data': {'as_of': '2026-10-05T10:05:00-04:00',
              'calendars': {'economics': [{'title': 'US ISM Services PMI', '发布时间ET': '2026-10-05T10:00:00-04:00',
                                         'star': 'HIGH', 'actual': '55', 'consensus': '54', 'previous': '53'}]}}}}}
    html = render_home(tmp_path, now=datetime.fromisoformat('2026-10-05T10:05:00-04:00'), grouped={'2026-10-05': [result]})
    row = html.split('aria-label="自选建议与相对基准强弱"')[1].split('</tbody>')[0]
    assert 'data-macro-review>已公布，未重跑' in row
    assert 'data-time-quality-summary' in row and 'data-time-quality-summary' in row.split('<td><span data-report-summary>')[1]
    assert row.index('data-macro-review') < row.index('<summary>时间与质量</summary>')
    result['context_blocks']['macro_releases']['data']['calendars']['economics'][0]['actual'] = '尚未发布'
    row = render_home(tmp_path, now=datetime.fromisoformat('2026-10-05T09:59:00-04:00'), grouped={'2026-10-05': [result]}).split('aria-label="自选建议与相对基准强弱"')[1].split('</tbody>')[0]
    assert 'data-macro-review>待复核：US ISM Services PMI' in row
    result['late_macro'] = [{'title': 'US ISM Services PMI', 'created_at': '2026-10-05T10:00:00-04:00'}]
    row = render_home(tmp_path, now=datetime.fromisoformat('2026-10-05T10:05:00-04:00'), grouped={'2026-10-05': [result]}).split('aria-label="自选建议与相对基准强弱"')[1].split('</tbody>')[0]
    assert 'data-macro-review' not in row


def test_symbol_tags_not_issuer_and_old_same_title_not_same_event():
    result = {'symbol': 'ABC', 'information_through': '2026-10-05T08:30:00-04:00', 'reports': {
        'news_report': '[2026-10-02] ABC Q3 deliveries 486,532 vehicles beating estimates'}}
    article = {'title': 'XYZ Q3 deliveries beating estimates: Analyst commentary', 'symbols': ['ABC'],
        'published_at': '2026-10-05T08:54:00-04:00', 'major': True}
    assert classify_article(article, result)['major']
    result['context_blocks'] = {'macro_releases': {'data': {'as_of': '2026-10-05T10:05:00-04:00', 'calendars': {'economics': [
        {'title': 'US ISM Services PMI', '发布时间ET': '2026-10-05T10:00:00-04:00', 'star': 'HIGH', 'actual': '55'}]}}}}
    result['late_macro'] = [{'title': 'US ISM Services PMI', 'created_at': '2026-10-02T10:00:00-04:00'}]
    now = datetime.fromisoformat('2026-10-05T10:05:00-04:00')
    assert macro_followups([result], {}, now)
    result['late_macro'][0].pop('created_at')
    assert macro_followups([result], {}, now)
    result['late_macro'][0]['created_at'] = '2026-10-05T10:00:00-04:00'
    assert macro_followups([result], {}, now) == []


def test_iex_warning_and_source_visible_summary_and_reference():
    result = {'symbol': 'SPY', 'context_blocks': {'extended_hours': {'data': {'SPY': {'pre': {
        'price': 769.31, 'quote_time': '2026-10-05T08:25:28-04:00', 'source': 'Alpaca feed=iex',
        'status': '可用', 'session_verified': True, 'volume': 78, 'warning': '来源前收盘与P官方收盘不一致（超过0.1%）'}}}}}}
    quality = quote_quality(result)
    assert 'Alpaca feed=iex' in quality['summary'] and 'IEX 覆盖不完整' in quality['summary']
    assert 'IEX 覆盖不完整' in quality['references'][0]['display_warning']
    assert '来源前收盘' in quality['references'][0]['display_warning']


def test_delivery_direction_quantity_and_issuer_same_fact_sentence():
    result = {'symbol': 'ABC', 'information_through': '2026-10-05T08:30:00-04:00'}
    article = {'title': 'ABC Q3 deliveries beating estimates: Analyst commentary',
               'published_at': '2026-10-05T08:54:00-04:00', 'major': True}
    for report in ('[2026-10-02] ABC Q3 deliveries 486,532 missed estimates. ABC shares beating expectations',
                   '[2026-10-02] ABC Q3 analyst commentary. XYZ deliveries 486,532 beating estimates',
                   'ABC Q3 deliveries 486,532 beating estimates. [2026-10-02] XYZ Q4 deliveries 500,000 beating estimates'):
        result['reports'] = {'news_report': report}
        assert classify_article(article, result)['major']


def test_new_article_delivery_fields_do_not_borrow_comparison_issuer():
    result = {'symbol': 'ABC', 'information_through': '2026-10-05T08:30:00-04:00',
              'reports': {'news_report': '[2026-10-02] ABC Q3 deliveries 486,532 vehicles beating estimates'}}
    article = {'published_at': '2026-10-05T08:54:00-04:00', 'major': True}
    for title, summary in (
        ('XYZ Q3 deliveries beating estimates: analyst commentary', 'ABC valuation is discussed as a comparison'),
        ('ABC deliveries beating estimates: analyst commentary', 'XYZ Q3 delivery valuation discussion'),
        ('ABC Q3 deliveries: analyst commentary', 'XYZ shares beating expectations'),
        ('ABC deliveries beating estimates: analyst commentary', 'Analyst commentary on XYZ Q3 deliveries'),
        ('ABC Q3 deliveries: analyst commentary', 'Analyst commentary on XYZ deliveries beating estimates'),
    ):
        assert classify_article({**article, 'title': title, 'summary': summary}, result)['major']
    assert not classify_article({**article, 'title': 'ABC Delivered More Cars Than Expected, Analyst Still Wary',
                                'summary': 'ABC beating Q3 delivery estimates, valuation commentary'}, result)['major']


def test_macro_nbsp_calendar_merge_three_times_and_counterexamples():
    result = {'symbol': 'SPY', 'run_id': 'run', 'information_through': '2026-10-05T08:30:00-04:00',
              'final_trade_decision': 'ISM PMI数据公布后复核', 'context_blocks': {'macro_releases': {'data': {
                  'as_of': '2026-10-05T08:31:00-04:00', 'calendars': {'economics': [
                      {'title': '美国9月ISM非制造业PMI', 'star': 'HIGH', '发布时间ET': '2026-10-05T10:00:00-04:00', 'consensus': '55', 'previous': '55.4'},
                      {'title': '美国9月标普全球服务业PMI终值', 'star': 'HIGH', '发布时间ET': '2026-10-05T09:45:00-04:00', 'previous': '58.7'}]}}}}}
    articles = [
        {'title': 'ISM Non-Manufacturing PMI For September\xa054.9 Vs 55.1 Est.', 'published_at': '2026-10-05T10:00:30-04:00'},
        {'title': 'USA S&P Global Services PMI For September\xa058.8 Vs 58.7 Est.', 'published_at': '2026-10-05T09:45:17-04:00'}]
    for time in ('09:59', '10:05', '12:00'):
        watch = {'SPY': {'run_id': 'run', 'information_through': result['information_through'], 'checked_at': '2026-10-05T' + time + ':00-04:00', 'articles': articles}}
        rows = macro_followups([result], watch, datetime.fromisoformat(watch['SPY']['checked_at']))
        assert len(rows) == 2
        ism, services = rows
        if time == '09:59': assert ism['status'] == '待公布'
        else:
            assert (ism['actual'], ism['estimate'], ism['prior'], ism['source']) == ('54.9', '55.1', '55.4', '标题 + 保存日历')
            assert len(macro_review_marks(result, rows)) == 2
        assert (services['actual'], services['estimate'], services['prior']) == ('58.8', '58.7', '58.7')
    assert classify_article(articles[0], result)['macro']
    for title in ('Japan ISM Non-Manufacturing PMI 54.9 Vs. 55.1 Est.', 'ISM Non-Manufacturing PMI guidance vs $1.2B', 'USA S&P Global Manufacturing PMI 50.1 Vs 50.2 Prior'):
        watch['SPY']['articles'] = [{'title': title, 'published_at': '2026-10-05T10:00:30-04:00'}]
        rows = macro_followups([result], watch, datetime.fromisoformat(watch['SPY']['checked_at']))
        assert rows[0]['actual'] == '未到'
    assert rows[-1]['actual'] == '50.1' and rows[-1]['prior'] == '50.2'


def test_report_brief_classified_major_count_and_details_preserve_content(tmp_path):
    import json
    from bs4 import BeautifulSoup
    from daily_analyzer.site import render_home
    (tmp_path / 'config').mkdir()
    (tmp_path / 'data').mkdir()
    (tmp_path / 'config/watchlist.yaml').write_text('items:\n  - {symbol: ABC, type: stock}\n')
    result = {'symbol': 'ABC', 'type': 'stock', '_date': '2026-10-05', '_slug': 'ABC', 'run_id': 'run',
              'status': 'success', 'information_through': '2026-10-05T08:30:00-04:00',
              'reports': {'news_report': '[2026-10-02] ABC Q3 deliveries 486,532 vehicles beating estimates'},
              'data_source_status': [{'category': '日线', 'status': '降级'}]}
    article = {'title': 'ABC Delivered More Cars Than Wall Street Expected', 'summary': 'ABC Q3 delivery follow-up commentary',
               'published_at': '2026-10-05T08:54:00-04:00', 'major': True}
    watch = {'run_id': 'run', 'information_through': result['information_through'], 'count': 2, 'major': True,
             'articles': [article, {**article, 'id': 2}]}
    (tmp_path / 'data/news_watch.json').write_text(json.dumps({'trade_date': '2026-10-05', 'checked_at': '2026-10-05T10:05:00-04:00', 'items': {'ABC': watch}}))
    html = render_home(tmp_path, now=datetime.fromisoformat('2026-10-05T10:05:00-04:00'), grouped={'2026-10-05': [result]})
    soup = BeautifulSoup(html, 'html.parser')
    details = soup.select_one('[data-report-details]')
    assert details.select_one('summary').get_text() == '数据源 降级1'
    assert 'source-degraded' not in details.select_one('summary').get('class', [])
    assert details.select('[data-news-watch] p.source-degraded') == []
    assert details.select_one('[data-time-quality-summary]') and details.select_one('[data-news-watch]')
    assert '已纳入事件的跟进报道' in details.get_text()


def test_shared_macro_marks_skip_already_included_late_macro():
    result = {'final_trade_decision': 'ISM公布后复核', 'late_macro': [
        {'title': 'USA ISM Services PMI 54.9 Vs 55.1 Est.', 'created_at': '2026-10-05T10:00:30-04:00'}]}
    events = [{'title': '美国9月ISM非制造业PMI', 'published_at': '2026-10-05T10:00:00-04:00',
               'status': '已公布未重跑 · 待复核'}]
    assert macro_review_marks(result, events) == []
    result['late_macro'] = []
    assert macro_review_marks(result, events)[0]['status'] == '已公布，未重跑'


def test_unmatched_macro_titles_keep_numeric_units():
    result = {'symbol': 'SPY', 'run_id': 'run', 'information_through': '2026-10-05T08:30:00-04:00'}
    titles = [('USA Nonfarm Payrolls For Sept. 29K Vs 89K Est.', '29K', '89K'),
              ('USA CPI YoY For September 3.0% Vs 2.9% Est.', '3.0%', '2.9%')]
    watches = {'SPY': {'run_id': 'run', 'information_through': result['information_through'],
                       'checked_at': '2026-10-05T10:05:00-04:00', 'articles': [
                           {'title': title, 'published_at': '2026-10-05T10:00:00-04:00'} for title, _, _ in titles]}}
    rows = macro_followups([result], watches, datetime.fromisoformat('2026-10-05T10:05:00-04:00'))
    assert [(row['actual'], row['estimate']) for row in rows] == [(actual, estimate) for _, actual, estimate in titles]
