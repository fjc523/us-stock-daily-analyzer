"""截止后新闻检查只写提示文件，覆盖真实交付新闻回归样例。"""
from datetime import datetime
from pathlib import Path
import threading
from daily_analyzer.news_watch import check_news, is_major, NewsWatcher
from daily_analyzer.storage import atomic_write_json
from daily_analyzer.time_utils import NEW_YORK
import pytest


def project(root):
    (root/'config').mkdir()
    (root/'config/watchlist.yaml').write_text('items:\n  - symbol: TSLA\n    type: stock\n  - symbol: SPY\n    type: etf\n')
    for symbol, cutoff in [('TSLA','2026-10-02T09:00:17-04:00'),('SPY','2026-10-02T09:05:00-04:00')]:
        atomic_write_json(root/f'data/runs/2026-10-02/current/{symbol}.json',
                          {'symbol':symbol,'status':'success','run_id':'fixture','information_through':cutoff})
    return root


def article(stamp='2026-10-02T13:04:19Z', title='Tesla Q3 Deliveries Beat Expectations',symbols=None):
    return {'id':stamp+title, 'created_at':stamp, 'headline':title, 'symbols':symbols or ['TSLA','SPY'],
            'summary':'', 'url':'https://example.test/delivery'}


class Source:
    def __init__(self,rows): self.rows,self.calls=rows,[]
    def news(self,*args,**kwargs):
        self.calls.append((args,kwargs))
        return {'articles':self.rows,'truncated':False}


def test_multisymbol_cutoffs_no_other_write_and_tsla_delivery_regression(tmp_path):
    root=project(tmp_path)
    before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    source=Source([article(),article(),article('2026-10-02T13:00:17Z','截止时刻'),
                   article('2026-10-02T13:06:00Z','Ordinary market discussion', ['SPY']),
                   article('2026-10-02T13:20:00Z','未来消息')])
    result=check_news(root,now=datetime(2026,10,2,9,10,tzinfo=NEW_YORK),source=source)
    assert len(source.calls)==1 and source.calls[0][0][0]==['TSLA','SPY']
    assert result['items']['TSLA']['count']==1
    assert result['items']['TSLA']['major'] is True
    assert result['items']['TSLA']['articles'][0]['published_at']=='2026-10-02T13:04:19+00:00'
    assert result['items']['SPY']['count']==1
    assert result['items']['SPY']['major'] is False
    assert {str(p):p.read_bytes() for p in root.rglob('*') if p.is_file() and p.name!='news_watch.json'}==before
    assert not (root/'data/run.lock').exists()


@pytest.mark.parametrize('stamp',['2026-10-03T10:00:00','2026-10-02T03:59:00','2026-10-02T20:00:00'])
def test_outside_session_no_query(tmp_path,stamp):
    root=project(tmp_path);source=Source([])
    assert check_news(root,now=datetime.fromisoformat(stamp).replace(tzinfo=NEW_YORK),source=source) is None
    assert not source.calls and not (root/'data/news_watch.json').exists()


@pytest.mark.parametrize('title,major',[('Q3 Deliveries Report',True),('Quarterly earnings and guidance',True),
    ('Broker upgrades price target',True),('Company merger offering',True),('SEC investigation',True),
    ('CEO resigns',True),('董事会宣布首席执行官离职',True),('发布交付数据与业绩指引',True),
    ('The second wave of discussion',False),('A resulting change in prices',False),('SECURITY update',False)])
def test_major_keywords_and_word_boundaries(title,major):
    assert is_major({'headline':title}) is major


def test_background_retry_and_stop(tmp_path):
    calls=[]; retried=threading.Event()
    def checker(root):
        calls.append(root)
        if len(calls)==1: raise RuntimeError('本轮故障')
        retried.set()
    watcher=NewsWatcher(tmp_path,checker=checker,interval=0.01)
    watcher.start()
    assert retried.wait(2)
    watcher.stop()
    assert len(calls)>=2 and not watcher.thread.is_alive()


def test_failed_fetch_preserves_previous_hint(tmp_path):
    root=project(tmp_path)
    path=root/'data/news_watch.json';atomic_write_json(path,{'previous':True})
    previous=path.read_bytes()
    class Failed:
        def news(self,*args,**kwargs): raise RuntimeError('查询失败')
    with pytest.raises(RuntimeError): check_news(root,now=datetime(2026,10,2,10,tzinfo=NEW_YORK),source=Failed())
    assert path.read_bytes()==previous
