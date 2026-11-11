# SPDX-License-Identifier: MIT
"""Local fixture integration test; never connects to the real bot endpoints."""
import asyncio
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory

import websockets

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('observer_under_test',ROOT/'observe_status.py')
observer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)
fixture = None  # Created only when this test is explicitly executed.
requests=[]

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', '0')))
        requests.append((self.path,self.headers.get('Authorization')))
        payload=json.dumps({'retcode':0,'data':{'online':True,'good':True,'time':15,'unused':'NEVER_LOG_THIS'}}).encode()
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

async def run():
    http=HTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=http.serve_forever,daemon=True)
    worker.start()
    received=[]
    async def handler(ws):
        assert ws.request.headers.get('Authorization')=='Bearer fixture-token'
        await ws.send(json.dumps({'post_type':'message','message_type':'group','raw_message':'PRIVATE_FIXTURE_TEXT','sender':{'nickname':'PRIVATE_NAME'}}))
        await ws.send(json.dumps({'post_type':'meta_event','meta_event_type':'heartbeat','status':{'online':True,'good':True,'secret':'NEVER_LOG_THIS'}}))
        await ws.send(json.dumps({'post_type':'notice','notice_type':'bot_offline','tag':'s26','message':'登录认证失效 user=123456789 accessToken=fixture-secret'}))
        try:
            async for frame in ws:
                received.append(frame)
        except websockets.exceptions.ConnectionClosed:
            pass
    try:
        async with websockets.serve(handler,'127.0.0.1',0) as server:
            wsport=server.sockets[0].getsockname()[1]
            config={'enabled':True, 'http_url':f'http://127.0.0.1:{http.server_port}',
                    'ws_url':f'ws://127.0.0.1:{wsport}',
                    'http_token':'fixture-token','ws_token':'fixture-token'}
            observer.CONFIG=fixture/'fixture-config.json'
            observer.CONFIG.write_text(json.dumps(config),encoding='utf-8')
            observer.OUT=fixture
            await observer.observe(SimpleNamespace(once=False,minutes=.05,interval=10))
    finally:
        http.shutdown()
        http.server_close()
        worker.join(timeout=2)
    output=next(fixture.glob('status_*.jsonl')).read_text(encoding='utf-8')
    records=[json.loads(line) for line in output.splitlines()]
    assert any(r['kind']=='bot_offline' and r['tag']=='s26' for r in records)
    assert any(r['kind']=='http_status' and r.get('online') is True for r in records), records
    assert any(r['kind']=='onebot_heartbeat' for r in records)
    for forbidden in ('PRIVATE_FIXTURE_TEXT','PRIVATE_NAME','NEVER_LOG_THIS','fixture-token','fixture-secret','123456789'):
        assert forbidden not in output
    assert requests == [('/get_status','Bearer fixture-token')]
    assert received == []
    result={'passed':True,'real_bot_accessed':False,
            'ws_application_frames_sent_by_observer':0,'chat_text_and_secrets_saved':False}
    print(json.dumps(result))

if __name__ == '__main__':
    with TemporaryDirectory(prefix='onebot-observer-test-') as directory:
        fixture = Path(directory)
        asyncio.run(run())
