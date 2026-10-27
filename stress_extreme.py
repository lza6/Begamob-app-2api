# -*- coding: utf-8 -*-
"""极限压测: 阶梯并发 20/30/50 + 持续压测找 429 阈值 + 长文本边界"""
import json, time, statistics, threading, urllib.request, urllib.error, sys

BASE = 'http://127.0.0.1:8915'

def one(model='gpt-4o-mini', content='Say PING', max_tokens=10, timeout=120):
    t0 = time.time()
    try:
        data = json.dumps({'model':model,'messages':[{'role':'user','content':content}],'max_tokens':max_tokens}).encode()
        r = urllib.request.Request(BASE+'/v1/chat/completions', data=data, headers={'Content-Type':'application/json'})
        resp = urllib.request.urlopen(r, timeout=timeout)
        resp.read()
        return resp.status, time.time()-t0
    except urllib.error.HTTPError as e:
        e.read()
        return e.code, time.time()-t0
    except Exception:
        return 0, time.time()-t0

def wave(conc, label):
    out = []
    def worker(i):
        out.append(one(content=f'Say W{conc}-{i}'))
    ts = [threading.Thread(target=worker,args=(i,)) for i in range(conc)]
    t0 = time.time()
    [t.start() for t in ts]; [t.join() for t in ts]
    wall = time.time()-t0
    codes = {}
    for s,_ in out: codes[s] = codes.get(s,0)+1
    ok = codes.get(200,0)
    dts = [d for s,d in out if s==200]
    p50 = statistics.median(dts) if dts else 0
    print(f'{label:16s} conc={conc:3d}  wall={wall:6.2f}s  ok={ok}/{conc}  codes={codes}  p50={p50:.2f}s max={max(dts) if dts else 0:.2f}s')
    return codes

print('=== 阶梯并发 ===')
for c in (20, 30, 50):
    wave(c, f'阶梯-{c}')
    time.sleep(3)

print('\n=== 持续压测 3轮x30连发 (429探测) ===')
r429 = 0
for rnd in range(3):
    codes = wave(30, f'持续-轮{rnd+1}')
    r429 += codes.get(429,0) + codes.get(502,0)
    time.sleep(5)

print('\n=== 长文本上下文边界 ===')
for n_chars, label in ((2000,'2K字符'), (20000,'20K字符'), (60000,'60K字符'), (120000,'120K字符')):
    s, dt = one(content='重复输出OK ' + 'x'*n_chars + ' 只需回复END', max_tokens=50)
    print(f'{label:10s} -> {s} {dt:.2f}s')

print('\n=== 极限收尾: 单发健康 ===')
s, dt = one()
print('final probe:', s, f'{dt:.2f}s')
