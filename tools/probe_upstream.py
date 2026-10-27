# -*- coding: utf-8 -*-
"""直连 chatapi.begamob.com 协议复刻探针（独立验证，不依赖 demo gateway）"""
import hmac, hashlib, base64, json, time, sys, os, socket, ssl

UPSTREAM = 'chatapi.begamob.com'
JWT_SECRET = b'stteam-ikameglobal-chatapiopenai'
BUNDLE = 'com.chatbot.ai.aichat.openaibot.chat'
VERSION = '35.2.8'

def b64u(b): return base64.urlsafe_b64encode(b).rstrip(b'=').decode()

def make_jwt(exp_seconds=3600):
    now = int(time.time())
    h = b64u(json.dumps({"alg":"HS256","typ":"JWT"}, separators=(',',':')).encode())
    p = b64u(json.dumps({"iat":now,"exp":now+exp_seconds,"bundleId":BUNDLE,
                         "os":"Android","versionApp":VERSION}, separators=(',',':')).encode())
    return f"{h}.{p}." + b64u(hmac.new(JWT_SECRET, f"{h}.{p}".encode(), hashlib.sha256).digest())

def chat(model, content, max_tokens=50, endpoint='/api/v1/chat', proxy=None):
    proxy = proxy or os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    if proxy:
        phost, pport = proxy.replace('http://','').split(':')
        s = socket.create_connection((phost, int(pport)), timeout=15)
        s.sendall(f'CONNECT {UPSTREAM}:443 HTTP/1.1\r\nHost: {UPSTREAM}:443\r\n\r\n'.encode())
        resp = b''
        while b'\r\n\r\n' not in resp: resp += s.recv(4096)
        assert b' 200 ' in resp.split(b'\r\n')[0], 'proxy connect failed'
    else:
        s = socket.create_connection((UPSTREAM, 443), timeout=15)
    ss = ssl.create_default_context().wrap_socket(s, server_hostname=UPSTREAM)
    body = json.dumps({'model':model,'messages':[{'role':'user','content':content}],
                       'max_tokens':max_tokens}, separators=(',',':')).encode()
    did = 'probe-' + str(os.getpid())
    req = (f'POST {endpoint} HTTP/1.1\r\nHost: {UPSTREAM}\r\n'
           f'Content-Type: application/json\r\nAuthorization: Bearer {make_jwt()}\r\n'
           f'user-header: bundleId:{BUNDLE}/versionApp:{VERSION}/OS:Android/osVersion:33/userId:/deviceId:{did}\r\n'
           f'User-Agent: VersionApp:{VERSION}/AppId:{BUNDLE}/Build:352804/VersionSDK:33/OS:Android/'
           f'UserAgent:okhttp/4.12.0userId:/deviceId:{did}\r\n'
           f'Content-Length: {len(body)}\r\nConnection: close\r\n\r\n').encode() + body
    ss.sendall(req)
    resp = b''
    while True:
        try: chunk = ss.recv(65536)
        except (ssl.SSLWantReadError, ConnectionResetError): break
        if not chunk: break
        resp += chunk
    ss.close()
    head, _, rest = resp.partition(b'\r\n\r\n')
    status = int(head.split(b'\r\n')[0].split()[1])
    if b'chunked' in head:
        out = b''
        while rest:
            line, _, rest = rest.partition(b'\r\n')
            try: n = int(line, 16)
            except ValueError: break
            if n == 0: break
            out += rest[:n]; rest = rest[n+2:]
        rest = out
    return status, rest

if __name__ == '__main__':
    model = sys.argv[1] if len(sys.argv) > 1 else 'gpt-4o-mini'
    text = sys.argv[2] if len(sys.argv) > 2 else 'Say PROBE-OK'
    st, data = chat(model, text)
    print(st, data[:400].decode(errors='replace'))
