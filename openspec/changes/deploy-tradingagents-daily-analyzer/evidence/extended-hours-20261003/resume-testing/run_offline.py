"""离线测试拒绝出网；不替代适配器固定响应。"""
import socket
import sys
import pytest
attempts=[]
def denied(self,address):
 attempts.append(repr(address))
 raise AssertionError('独立测试禁止网络连接')
socket.socket.connect=denied
socket.socket.connect_ex=denied
exit_code=pytest.main(sys.argv[1:])
print('网络连接尝试：', attempts)
raise SystemExit(1 if attempts else exit_code)
