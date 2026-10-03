"""周末/假日管理入口使用固定时钟、临时项目和假进程。"""
import json
import threading
from datetime import datetime
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from daily_analyzer.append_requests import read_requests
from daily_analyzer.manual_analysis import AnalysisLauncher
from daily_analyzer.storage import atomic_write_json, run_lock
from daily_analyzer.viewer import create_server


def _project(root):
    (root / 'config').mkdir()
    (root / 'config/watchlist.yaml').write_text(
        'items:\n  - {symbol: NVDA, type: stock}\n'
        '  - {symbol: QQQ, type: etf}\n  - {symbol: MSFT, type: stock, enabled: false}\n')
    return root


def _request(base, body):
    request = Request(base + '/api/analysis', data=json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json'})
    try:
        response = urlopen(request, timeout=3)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read())


@pytest.mark.parametrize('stamp', ['2026-10-03T11:17:00-04:00',
                                    '2026-09-07T09:40:00-04:00'])
@pytest.mark.parametrize('body,symbols', [({'symbol': 'NVDA'}, ['NVDA']),
                                        ({'scope': 'all'}, ['NVDA', 'QQQ'])])
def test_休市单只与全部HTTP使用现有命令不启动真实分析(tmp_path, monkeypatch, stamp, body, symbols):
    root = _project(tmp_path)
    monkeypatch.setattr('daily_analyzer.viewer.InstrumentResolver', lambda root: lambda symbol: {})
    calls = []
    process = SimpleNamespace(poll=lambda: None)
    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return process
    launcher = AnalysisLauncher(root, popen=fake_popen, clock=lambda: datetime.fromisoformat(stamp))
    server = create_server(root, port=0, launcher=launcher)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f'http://127.0.0.1:{server.server_port}'
        status, result = _request(base, body)
        assert status == 202 and result['status'] == 'running'
        assert len(calls) == 1
        command, options = calls[0]
        assert command[-3:] == ['--tickers', ','.join(symbols), '--force']
        assert '--date' not in command and '--scheduled' not in command
        assert options['cwd'] == root
        assert _request(base, body)[0] == 409
        assert len(calls) == 1
        assert not (root / 'data/status.json').exists()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_周末busy追加仅写请求不改批次也不创建进程(tmp_path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.setattr('daily_analyzer.viewer.InstrumentResolver', lambda root: lambda symbol: {})
    directory = root / 'data/runs/2026-10-03/batches/fixed'
    atomic_write_json(directory / 'batch.json', {
        'run_id': 'fixed', 'trade_date': '2026-10-03', 'status': 'running',
        'accepting_appends': True, 'items': {'NVDA': {'symbol': 'NVDA', 'status': 'running'}}})
    atomic_write_json(root / 'data/status.json', {'last_run': {
        'trade_date': '2026-10-03', 'run_id': 'fixed', 'started_at': '2026-10-03T10:00:00-04:00'}})
    original = (directory / 'batch.json').read_bytes()
    def forbid_popen(*args, **kwargs):
        pytest.fail('追加禁止产生第二个分析进程')
    launcher = AnalysisLauncher(root, popen=forbid_popen,
                                clock=lambda: datetime.fromisoformat('2026-10-03T11:17:00-04:00'))
    with run_lock(root):
        result = launcher.start(scope='all')
        assert result['message'] == '已加入当前批次'
        assert [row['symbol'] for row in read_requests(directory)[0]] == ['QQQ']
        assert (directory / 'batch.json').read_bytes() == original
