"""查看器与主线程共用的批次追加请求通道。"""
import fcntl
import json
import os
from contextlib import contextmanager


@contextmanager
def append_lock(batch_dir):
    with (batch_dir / 'append.lock').open('a') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def read_requests(batch_dir, offset=0):
    path = batch_dir / 'append_requests.jsonl'
    if not path.exists():
        return [], offset
    with path.open('r', encoding='utf-8') as stream:
        stream.seek(offset)
        rows = [json.loads(line) for line in stream.readlines() if line.strip()]
        return rows, stream.tell()


def write_request(batch_dir, request):
    with (batch_dir / 'append_requests.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(request, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


STOP_MESSAGES = {
    'skipped_quota': 'Codex额度已用尽，本批已停止派发',
    'skipped_fatal': 'Codex配置错误，本批已停止派发',
    'skipped_timeout': '批次已达到最长运行时间',
}
