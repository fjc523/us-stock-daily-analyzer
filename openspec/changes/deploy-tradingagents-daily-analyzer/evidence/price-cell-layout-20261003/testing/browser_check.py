"""隔离固定报告样本，以真实 Chrome 检查价格单元格边界并截图。"""
import base64
import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from websockets.sync.client import connect
from daily_analyzer.site import build_site, render_home

REPO = Path(__file__).resolve().parents[6]
OUT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("site_fixtures", REPO / "tests/test_site.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)

MEASURE = r"""(() => {
const rect = r => ({left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height});
const rows = [...document.querySelectorAll('.watch-table tbody tr')].map(row => {
 const cells=[...row.querySelectorAll(':scope > td')], price=row.querySelector(':scope > .analysis-price'), status=price.nextElementSibling;
 const cellInfo = cell => {
  const box=cell.getBoundingClientRect(), walker=document.createTreeWalker(cell,NodeFilter.SHOW_TEXT);
  const texts=[]; let node;
  while(node=walker.nextNode()) {
   if(!node.textContent.trim() || !node.parentElement.checkVisibility())continue;
   const range=document.createRange();range.selectNodeContents(node);
   const rectangles=[...range.getClientRects()].filter(r=>r.width&&r.height);
   texts.push({text:node.textContent.trim(),rects:rectangles.map(rect),inside:rectangles.every(r=>r.left>=box.left-1&&r.right<=box.right+1&&r.top>=box.top-1&&r.bottom<=box.bottom+1)});
  }
  return {box:rect(box),whiteSpace:getComputedStyle(cell).whiteSpace,texts};
 };
 const p=cellInfo(price),s=cellInfo(status);
 return {symbol:cells[0].querySelector('.symbol').textContent,price:p,status:s,
  overlap:Math.min(p.box.right,s.box.right)>Math.max(p.box.left,s.box.left)+1&&Math.min(p.box.bottom,s.box.bottom)>Math.max(p.box.top,s.box.top)+1};
});
return {url:location.pathname,width:innerWidth,scrollWidth:document.documentElement.scrollWidth,rows};
})()"""

def main():
    with tempfile.TemporaryDirectory(prefix="price-cell-fixed-") as directory:
        root = Path(directory)
        day = "2026-10-02"
        results = [fixtures._result(symbol, day) for symbol in ("NVDA", "SMTC", "TSLA")]
        results[1]["status"] = "running"
        results[1]["duration_seconds"] = None
        fixtures._analysis_fixture(results[2], price=357.13)
        for result in results:
            result["data_source_status"] = [{"name":"Alpaca", "status":"正常", "reason":"固定样本"}]
            fixtures._write_json(root / "data/runs" / day / "current" / (result["symbol"] + ".json"), result)
        (root / "config").mkdir()
        (root / "config/watchlist.yaml").write_text("items:\n" + "".join(f"- symbol: {r['symbol']}\n  type: stock\n  enabled: true\n" for r in results))
        now = datetime(2026, 10, 2, 9, 0, tzinfo=ZoneInfo("America/New_York"))
        assert build_site(root, now=now)["ok"]
        (root / "site/index.html").write_text(render_home(root, now=now, managed=True), encoding="utf-8")
        analysis = {"busy":True,"active_symbols":["SMTC"],"items":{"SMTC":{"status":"running","stage":"正在分析市场与新闻","elapsed_seconds":125,"estimated_percent":42,"remaining_seconds":180,"estimate_source":"其他配置参考","estimate_samples":2}},"run":{"progress":{"completed":0,"total":1}}}

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(root / "site"), **kwargs)
            def do_GET(self):
                if self.path == "/api/analysis":
                    body=json.dumps(analysis).encode();self.send_response(200);self.send_header("Content-Type","application/json");self.end_headers();self.wfile.write(body)
                else:
                    super().do_GET()
            def do_POST(self):
                raise AssertionError("隔离验证不允许写操作")
            def log_message(self, *args):
                pass

        server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        chrome=subprocess.Popen(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome","--headless=new","--remote-debugging-port=0","--no-first-run","--no-default-browser-check",f"--user-data-dir={root / 'chrome'}","about:blank"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            active=root / "chrome/DevToolsActivePort"
            for _ in range(100):
                if active.exists():break
                time.sleep(.1)
            port=active.read_text().splitlines()[0]
            tabs=json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
            target=next(tab for tab in tabs if tab["type"]=="page" and tab["url"]=="about:blank")
            with connect(target["webSocketDebuggerUrl"],max_size=16*1024*1024) as ws:
                counter=0
                def cdp(method, params=None):
                    nonlocal counter
                    counter+=1;ws.send(json.dumps({"id":counter,"method":method,"params":params or {}}))
                    while True:
                        value=json.loads(ws.recv(timeout=15))
                        if value.get("id")==counter:
                            assert "error" not in value,value
                            return value.get("result",{})
                cdp("Page.enable");cdp("Network.enable")
                cdp("Network.setBlockedURLs",{"urls":["https://*","http://*.com/*","http://*.net/*"]})
                reports=[]
                for page in ("index.html",f"days/{day}/index.html"):
                    for width in (tuple(map(int,sys.argv[1:])) or (1440,390,320)):
                        cdp("Emulation.setDeviceMetricsOverride",{"width":width,"height":1200,"deviceScaleFactor":1,"mobile":False})
                        cdp("Page.navigate",{"url":f"http://127.0.0.1:{server.server_port}/{page}"})
                        time.sleep(.8)
                        report=cdp("Runtime.evaluate",{"expression":MEASURE,"returnByValue":True})["result"]["value"]
                        reports.append(report)
                        name=("home" if page=="index.html" else "overview")+f"-{width}"
                        shot=cdp("Page.captureScreenshot",{"format":"png","captureBeyondViewport":True})["data"]
                        (OUT / f"{name}.png").write_bytes(base64.b64decode(shot))
                previous=json.loads((OUT / "measurements.json").read_text()) if sys.argv[1:] and (OUT / "measurements.json").exists() else []
                current_keys={(r["url"],r["width"]) for r in reports}
                previous=[r for r in previous if (r["url"],r["width"]) not in current_keys]
                (OUT / "measurements.json").write_text(json.dumps(previous+reports,ensure_ascii=False,indent=2),encoding="utf-8")
                failures=[]
                known_residuals=[]
                for report in reports:
                    if report["scrollWidth"]>report["width"]:failures.append((report["url"],report["width"],"页面水平溢出"))
                    for row in report["rows"]:
                        if row["overlap"]:failures.append((report["url"],report["width"],row["symbol"],"单元格重叠"))
                        for key in ("price","status"):
                            for text in row[key]["texts"]:
                                if not text["inside"]:
                                    item=(report["url"],report["width"],row["symbol"],key,text["text"])
                                    # 经理确认：801px来源摘要箭头为未改动的既有范围外问题，保留披露。
                                    if report["width"]==801 and key=="status" and text["text"]=="›":known_residuals.append(item)
                                    else:failures.append(item)
                print(json.dumps({"reports":len(reports),"failures":failures,"known_residuals":known_residuals},ensure_ascii=False))
                assert not failures,failures
        finally:
            chrome.terminate();chrome.wait(timeout=10);server.shutdown()

if __name__ == "__main__":
    main()
