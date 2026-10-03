"""隔离页面点击验证：固定报告、模型目录与禁止启动的分析替身。"""
import json, runpy, subprocess, threading, sys
from pathlib import Path
from tempfile import mkdtemp
from datetime import datetime
from zoneinfo import ZoneInfo
from daily_analyzer.site import build_site
import daily_analyzer.viewer as viewer

repo=Path.cwd()
evidence=repo/'openspec/changes/deploy-tradingagents-daily-analyzer/evidence/dialog-backdrop-20261003/testing'
root=Path(mkdtemp(prefix='us-stock-dialog-fixture-20261003-'))
helpers=runpy.run_path(str(repo/'tests/test_site.py'))
helpers['_fixture'](root)
(root/'config').mkdir()
(root/'config/watchlist.yaml').write_text('items:\n  - {symbol: NVDA, type: stock, name: 隔离样例}\n',encoding='utf-8')
(root/'config/settings.yaml').write_text('{}\n')
result=helpers['_result']('NVDA','2026-10-01')
chart={'dates':['2026-09-28','2026-09-29','2026-09-30'],'stock':[100,120,90],'benchmark':[100,95,110],'sources':['固定隔离复权样例']}
result['context_blocks']['sector_strength']['data']={'symbol':'NVDA','sector_etf':'XLK','comparisons':[{'symbol':c,'kind':k,'excess_20d':.02,'chart':chart} for c,k in [('XLK','sector'),('QQQ','index')]]}
helpers['_write_json'](root/'data/runs/2026-10-01/current/NVDA.json',result)
assert build_site(root,now=datetime(2026,10,2,8,tzinfo=ZoneInfo('America/New_York')))['ok']
viewer.load_codex_models=lambda: {'models':[{'id':'gpt-6.1-sol','name':'隔离模型','reasoning_efforts':['medium','xhigh'],'default_effort':'medium'}],'source':'固定隔离目录','updated_at':'固定时间'}
class Launcher:
    def snapshot(self):return {'busy':False,'items':{}}
    def start(self,*a,**kw):raise AssertionError('禁止启动分析')
server=viewer.create_server(root,port=0,resolver=lambda symbol:{'symbol':symbol,'type':'stock','name':'隔离标的','source':'固定隔离身份'},launcher=Launcher())
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
config={'root':str(root),'base':f'http://127.0.0.1:{server.server_port}','evidence':str(evidence),'chrome':'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','tools':'/tmp/us-stock-dialog-testing-20261003-tools'}
(evidence/'browser-config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2))
try:
    rc=subprocess.run(['node',str(evidence/(sys.argv[1] if len(sys.argv)>1 else 'browser-clicks.cjs')),str(evidence/'browser-config.json')]).returncode
finally:
    server.shutdown();thread.join();server.server_close()
sys.exit(rc)
