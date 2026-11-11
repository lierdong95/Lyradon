# SPDX-License-Identifier: MIT
"""Peripheral OneBot observer. No messages sent and no production files written.

Uses explicitly configured loopback HTTP/WS endpoints and keeps only status,
message counts, and whitelisted offline reason codes. Free-form text is discarded. Does not capture
QQ ticket renewal traffic. Stop with Ctrl+C; --once performs one HTTP status read.
"""
import argparse
import asyncio
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

TZ = timezone(timedelta(hours=8))
OUT = Path(__file__).resolve().parent
CONFIG = OUT / 'observer.json'

def redact(value):
    text = str(value or '')[:1024]
    text = re.sub(r'https?://\S+', '<url>', text)
    text = re.sub(r'(?i)(?:bearer\s+\S+|(?:access_?token|token|pskey|p_skey|cookie|a2)\s*[:=]\s*\S+)', '<credential>', text)
    return re.sub(r'\d{7,}', '<id>', text)[:512]

def safe_status(value):
    value = value if isinstance(value,dict) else {}
    return {k:value.get(k) if type(value.get(k)) is bool else None for k in ('online','good')}

def safe_event(event):
    if not isinstance(event,dict):
        return None
    if event.get('post_type') == 'notice' and event.get('notice_type') == 'bot_offline':
        tag = str(event.get('tag') or '')
        return {'kind':'bot_offline','tag':tag if re.fullmatch(r's[0-9]{1,4}', tag) else 'other'}
    if event.get('post_type') == 'meta_event' and event.get('meta_event_type') == 'heartbeat':
        return {'kind':'onebot_heartbeat', **safe_status(event.get('status'))}
    if event.get('post_type') == 'meta_event' and event.get('meta_event_type') == 'lifecycle':
        subtype=event.get('sub_type')
        return {'kind':'onebot_lifecycle','sub_type':subtype if subtype in ('connect','enable','disable') else 'unknown'}
    return None

def endpoints(config):
    selected = []
    for key, scheme, token_key in [('http_url', 'http', 'http_token'), ('ws_url', 'ws', 'ws_token')]:
        uri = config.get(key)
        if not isinstance(uri, str):
            raise ValueError('Configure both HTTP and WebSocket URLs')
        parsed = urlsplit(uri)
        if (parsed.scheme != scheme or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or any(c in uri for c in '\r\n')):
            raise ValueError('Only plain loopback URLs without credentials or query strings are allowed')
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError('Invalid local port')
        token = config.get(token_key, '')
        if not isinstance(token, str) or '\r' in token or '\n' in token:
            raise ValueError('Invalid access token')
        selected.append((uri, token))
    return selected

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('Redirects disabled')

def read_status(endpoint):
    uri,token=endpoint
    headers={'Content-Type':'application/json'}
    if token: headers['Authorization']='Bearer '+token
    req=urllib.request.Request(uri.rstrip('/')+'/get_status', data=b'{}', headers=headers, method='POST')
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        with opener.open(req,timeout=5) as response:
            value=json.loads(response.read(65536))
        if not isinstance(value,dict):
            return {'kind':'http_status','error_type':'UnexpectedResponse'}
        data=value.get('data')
        data=data if isinstance(data,dict) else {}
        return {'kind':'http_status', 'retcode':value.get('retcode') if type(value.get('retcode')) is int else None,
                **safe_status(data), 'bridge_uptime_s':data.get('time') if type(data.get('time')) in (int,float) else None}
    except Exception as exc:
        return {'kind':'http_status','error_type':type(exc).__name__}

def self_test():
    assert safe_event({'post_type':'message','message':'PRIVATE CONTENT','sender':{'user_id':123456789}}) is None
    assert safe_event({'post_type':'notice','notice_type':'group_recall','user_id':123456789}) is None
    assert safe_event({'post_type':'meta_event','meta_event_type':'heartbeat','status':{'online':True,'good':False,'secret':'x'}}) == {'kind':'onebot_heartbeat','online':True,'good':False}
    notice=safe_event({'post_type':'notice','notice_type':'bot_offline','tag':'s26','message':'123456789 token=abc'})
    assert 'message' not in notice
    assert notice['tag'] == 's26'
    assert 'abcdef' not in redact('accessToken=abcdef')
    assert 'abcxyz' not in redact('Bearer abcxyz')
    try:
        endpoints({'http_url':'http://example.org/','ws_url':'ws://127.0.0.1/'})
    except ValueError:
        pass
    else:
        raise AssertionError('Remote endpoint not rejected')
    print('PASS: filtering, redaction, and local-only checks; no network access')

async def observe(args):
    import websockets
    class LocalConnect(websockets.connect):
        def process_redirect(self, exc):
            return exc  # never forward a local credential to another endpoint
    config = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    if config.get('enabled') is not True:
        print('Observer disabled; no endpoint accessed.')
        return
    targets=endpoints(config)
    logpath=OUT/('status_'+datetime.now(TZ).strftime('%Y%m%d_%H%M%S_%f')+'.jsonl')
    counts=Counter()
    start=time.monotonic()
    def emit(value):
        record={'observed_at':datetime.now(TZ).isoformat(timespec='seconds'),
                'elapsed_s':round(time.monotonic()-start,3), **value}
        with logpath.open('a',encoding='utf-8') as f:
            f.write(json.dumps(record,ensure_ascii=False)+'\n')
        if value['kind'] in ('bot_offline','started','stopped'):
            print(json.dumps(record,ensure_ascii=False),flush=True)
    emit({'kind':'started','mode':'once' if args.once else 'bounded','duration_minutes':args.minutes,
          'qq_heartbeat_packets_captured':False})
    print('Output:',str(logpath),flush=True)
    if args.once:
        result=await asyncio.to_thread(read_status,targets[0])
        emit(result)
        print(json.dumps(result),flush=True)
        emit({'kind':'stopped'})
        return
    async def poll():
        while True:
            emit(await asyncio.to_thread(read_status,targets[0]))
            emit({'kind':'message_counts','counts':dict(counts)})
            counts.clear()
            await asyncio.sleep(args.interval)
    async def listen():
        uri,token=targets[1]
        headers={'Authorization':'Bearer '+token} if token else None
        while True:
            try:
                # No application messages, no active WS ping, no remote proxy.
                async with LocalConnect(uri,additional_headers=headers,proxy=None,
                        ping_interval=None,open_timeout=5,close_timeout=2,max_size=4*1024*1024) as ws:
                    emit({'kind':'ws_connected'})
                    async for raw in ws:
                        try: event=json.loads(raw)
                        except (ValueError,TypeError): continue
                        safe=safe_event(event)
                        if safe: emit(safe)
                        elif isinstance(event,dict) and event.get('post_type')=='message':
                            kind=event.get('message_type')
                            counts[kind if kind in ('group','private') else 'other'] += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                emit({'kind':'ws_disconnected','error_type':type(exc).__name__})
            await asyncio.sleep(10)
    jobs=[asyncio.create_task(poll()),asyncio.create_task(listen())]
    try:
        await asyncio.sleep(args.minutes*60)
    finally:
        for job in jobs: job.cancel()
        await asyncio.gather(*jobs,return_exceptions=True)
        emit({'kind':'stopped'})

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=CONFIG)
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--minutes',type=float,default=360)
    parser.add_argument('--interval',type=float,default=30)
    options=parser.parse_args()
    CONFIG = options.config
    if not 0 < options.minutes <= 1440 or not 10 <= options.interval <= 300:
        parser.error('minutes must be >0 and <=1440; interval must be 10..300')
    if options.self_test:
        self_test()
    else:
        try: asyncio.run(observe(options))
        except KeyboardInterrupt: print('Observer stopped.')
        except Exception as exc: raise SystemExit('Observer setup failed: '+type(exc).__name__)
