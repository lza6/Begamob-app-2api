# -*- coding: utf-8 -*-
"""
ChatAI (com.begamob.chatgpt_openai v35.2.8) demo gateway
- /v1/chat/completions  OpenAI 兼容 (stream + non-stream)，透传上游 chatapi.begamob.com
- /v1/models            15 模型列表
- /api/getTime          上游透传
- /health /stats        本地
端口 8915
"""
import json, hmac, hashlib, base64, time, threading, socket, ssl, os, queue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = 'chatapi.begamob.com'
JWT_SECRET = b'stteam-ikameglobal-chatapiopenai'
BUNDLE = 'com.chatbot.ai.aichat.openaibot.chat'
VERSION = '35.2.8'
MODELS = ['gpt-4o-mini','gpt-4o','gpt-4.1','gpt-4.1-mini','gpt-5','gpt-5-mini',
          'claude-3.7-sonnet','claude-4.5-sonnet','claude-4.5-opus',
          'gemini-2.5-flash','gemini-3-pro','deepseek','claude','gemini','gpt']

stats = {'requests':0, 'upstream_ok':0, 'upstream_err':0, 'errors':[]}
stats_lock = threading.Lock()

def b64u(b): return base64.urlsafe_b64encode(b).rstrip(b'=').decode()

def make_jwt(exp_seconds=3600):
    now = int(time.time())
    h = b64u(json.dumps({'alg':'HS256','typ':'JWT'}, separators=(',',':')).encode())
    p = b64u(json.dumps({'iat':now,'exp':now+exp_seconds,'bundleId':BUNDLE,
                         'os':'Android','versionApp':VERSION}, separators=(',',':')).encode())
    sig = b64u(hmac.new(JWT_SECRET, f'{h}.{p}'.encode(), hashlib.sha256).digest())
    return f'{h}.{p}.{sig}'

def upstream_headers():
    did = 'demo-gateway-' + str(os.getpid())
    return {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + make_jwt(),
        'user-header': f'bundleId:{BUNDLE}/versionApp:{VERSION}/OS:Android/osVersion:33/userId:/deviceId:{did}',
        'User-Agent': f'VersionApp:{VERSION}/AppId:{BUNDLE}/Build:352804/VersionSDK:33/OS:Android/UserAgent:okhttp/4.12.0userId:/deviceId:{did}',
    }

def upstream_post(path, body, timeout=60):
    """通过系统代理 CONNECT 直连上游，返回 (status, data_bytes)"""
    proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    if proxy:
        phost, pport = proxy.replace('http://','').split(':')
        s = socket.create_connection((phost, int(pport)), timeout=15)
        s.sendall(f'CONNECT {UPSTREAM}:443 HTTP/1.1\r\nHost: {UPSTREAM}:443\r\n\r\n'.encode())
        resp = b''
        while b'\r\n\r\n' not in resp: resp += s.recv(4096)
        if b' 200 ' not in resp.split(b'\r\n')[0]:
            raise RuntimeError('proxy connect failed: ' + resp[:100].decode(errors='replace'))
    else:
        s = socket.create_connection((UPSTREAM, 443), timeout=15)
    ss = ssl.create_default_context().wrap_socket(s, server_hostname=UPSTREAM)
    data = json.dumps(body, separators=(',',':')).encode()
    hdrs = upstream_headers()
    req = (f'POST {path} HTTP/1.1\r\nHost: {UPSTREAM}\r\n'
           f'Content-Type: {hdrs["Content-Type"]}\r\nAuthorization: {hdrs["Authorization"]}\r\n'
           f'user-header: {hdrs["user-header"]}\r\nUser-Agent: {hdrs["User-Agent"]}\r\n'
           f'Content-Length: {len(data)}\r\nConnection: close\r\n\r\n').encode() + data
    ss.sendall(req)
    resp = b''
    while True:
        try:
            chunk = ss.recv(65536)
        except (ssl.SSLWantReadError, ConnectionResetError):
            break
        if not chunk: break
        resp += chunk
    ss.close()
    head, _, rest = resp.partition(b'\r\n\r\n')
    status = int(head.split(b'\r\n')[0].split()[1])
    # handle chunked
    if b'chunked' in head:
        body_out = b''
        while rest:
            line, _, rest = rest.partition(b'\r\n')
            try: n = int(line, 16)
            except ValueError: break
            if n == 0: break
            body_out += rest[:n]; rest = rest[n+2:]
        rest = body_out
    return status, rest

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, fmt, *args):
        pass  # 静默，压测时避免 IO 干扰

    def _json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        with stats_lock: stats['requests'] += 1
        if self.path == '/':
            html = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'demo.html'), 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return
        if self.path == '/health':
            return self._json(200, {'status':'ok','service':'chatai-3528-demo','ts':int(time.time()*1000)})
        if self.path == '/stats':
            with stats_lock: s = dict(stats)
            return self._json(200, s)
        if self.path == '/v1/models':
            return self._json(200, {'object':'list','data':[{'id':m,'object':'model','owned_by':'begamob'} for m in MODELS]})
        if self.path.startswith('/api/getTime'):
            st, data = upstream_post('/api/getTime'.replace('POST','GET') if False else '/api/getTime', {}, timeout=10) if False else (None, None)
            # getTime 是 GET：手动
            try:
                import urllib.request
                r = urllib.request.Request(f'https://{UPSTREAM}/api/getTime', headers={'User-Agent':'okhttp/4.12.0'})
                resp = urllib.request.urlopen(r, timeout=10)
                return self._json(200, json.loads(resp.read()))
            except Exception as e:
                return self._json(502, {'error': str(e)})
        return self._json(404, {'error':'not found'})

    def do_POST(self):
        with stats_lock: stats['requests'] += 1
        try:
            n = int(self.headers.get('Content-Length') or 0)
            req = json.loads(self.rfile.read(n) or b'{}')
        except Exception as e:
            return self._json(400, {'error':{'message':'bad json: '+str(e)}})

        if self.path != '/v1/chat/completions':
            return self._json(404, {'error':'not found'})

        model = req.get('model') or 'gpt-4o-mini'
        messages = req.get('messages') or []
        stream = bool(req.get('stream'))
        upstream_body = {
            'model': model,
            'messages': [{'role':m.get('role','user'),'content':m.get('content','')} for m in messages],
            'max_tokens': req.get('max_tokens') or 1024,
            'temperature': req.get('temperature', 0.7),
        }
        t0 = time.time()
        try:
            st, data = upstream_post('/api/v1/chat', upstream_body)
        except Exception as e:
            with stats_lock:
                stats['upstream_err'] += 1; stats['errors'].append(str(e)[:200])
            return self._json(502, {'error':{'message':'upstream: '+str(e)[:200]}})
        dt = time.time() - t0
        if st != 200:
            with stats_lock: stats['upstream_err'] += 1
            return self._json(502, {'error':{'message':f'upstream {st}: {data[:200].decode(errors="replace")}'}})
        try:
            ud = json.loads(data)
            content = ud['choices'][0]['message']['content']
        except Exception as e:
            with stats_lock: stats['upstream_err'] += 1
            return self._json(502, {'error':{'message':'parse: '+str(e)+' raw: '+data[:200].decode(errors='replace')}})
        with stats_lock: stats['upstream_ok'] += 1

        cid = 'chatcmpl-' + b64u(os.urandom(9))
        if not stream:
            return self._json(200, {
                'id': cid, 'object':'chat.completion','created':int(time.time()),
                'model': model,
                'choices':[{'index':0,'message':{'role':'assistant','content':content},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':0,'completion_tokens':0,'total_tokens':0},
                'x_upstream_ms': round(dt*1000),
            })
        # SSE 流式（上游无流式 → 本地切词模拟）
        self.send_response(200)
        self.send_header('Content-Type','text/event-stream')
        self.send_header('Cache-Control','no-cache')
        self.send_header('Connection','close')
        self.end_headers()
        self.close_connection = True
        def send_chunk(delta):
            ev = {'id':cid,'object':'chat.completion.chunk','created':int(time.time()),'model':model,
                  'choices':[{'index':0,'delta':delta,'finish_reason':None}]}
            self.wfile.write(b'data: ' + json.dumps(ev, ensure_ascii=False).encode() + b'\n\n')
            self.wfile.flush()
        try:
            send_chunk({'role':'assistant'})
            for ch in content:
                send_chunk({'content':ch}); time.sleep(0.01)
            ev = {'id':cid,'object':'chat.completion.chunk','created':int(time.time()),'model':model,
                  'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}
            self.wfile.write(b'data: ' + json.dumps(ev).encode() + b'\n\n')
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

if __name__ == '__main__':
    port = 8915
    print(f'ChatAI 35.2.8 demo gateway on :{port}  upstream={UPSTREAM}  models={len(MODELS)}')
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
