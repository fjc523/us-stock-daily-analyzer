"""独立离线测试：只允许本地临时 API，记录外网尝试与被测文件指纹。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[6]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tests'))
attempts: list[dict] = []
local: list[str] = []


def digest():
    """冻结源码和共享测试，不读取配置、凭据或运行数据。"""
    paths = sorted(list((ROOT / 'src').rglob('*.py')) + list((ROOT / 'tests').rglob('*.py')))
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def guard(event, args):
    if event == 'socket.connect':
        address = args[1]
        if isinstance(address, tuple) and address[0] in ('127.0.0.1', '::1', 'localhost'):
            local.append(repr(address))
            return
        attempts.append({'event': event, 'address': repr(address)})
        raise AssertionError('独立测试禁止真实外网连接')
    if event == 'socket.getaddrinfo':
        host = args[0]
        if host not in ('127.0.0.1', '::1', 'localhost', None):
            attempts.append({'event': event, 'host': str(host)})
            raise AssertionError('独立测试禁止外网域名查询')


label = os.environ.get('T3_TEST_LABEL', 'round1')
before = digest()
sys.addaudithook(guard)
started = time.monotonic()
code = pytest.main(sys.argv[1:])
after = digest()
changed = [key for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)]
result = {'command': [sys.executable, str(Path(__file__).relative_to(ROOT)), *sys.argv[1:]],
          'pytest_exit_code': int(code), 'elapsed_seconds': time.monotonic() - started,
          'external_network_attempts': attempts, 'local_connection_count': len(local),
          'changed_during_test': changed, 'before_sha256': before, 'after_sha256': after}
(OUT / f'{label}-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print('外网尝试：', attempts)
print('测试期间源码变更：', changed)
raise SystemExit(1 if attempts or changed else int(code))
