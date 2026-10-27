# -*- coding: utf-8 -*-
"""ChatAI 35.2.8 demo gateway 第一轮压测: 基线/流式/并发/错误路径"""
import json, time, statistics, threading, urllib.request, urllib.error, sys

BASE = 'http://127.0.0.1:8915'
results = []

def req(path, body=None, timeout=90, stream=False):
    t0 = time.time()
    try:
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(BASE+path, data=data, headers={'Content-Type':'application/json'})
        resp = urllib.request.urlopen(r, timeout=timeout)
        if stream:
            first = None; chunks = 0; total = b''
            while True:
                line = resp.readline()
                if not line: break
                if line.startswith(b'data: ') and b'[DONE]' not in line:
                    if first is None: first = time.time()-t0
                    chunks += 1; total += line
            return resp.status, time.time()-t0, {'ttft':first,'chunks':chunks}
        return resp.status, time.time()-t0, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, time.time()-t0, e.read()[:150].decode(errors='replace')
    except Exception as e:
        return 0, time.time()-t0, str(e)[:100]

def scenario(name, fn, expect=None):
    st, dt, extra = fn()
    ok = (st == expect) if expect is not None else (200 <= st < 300)
    results.append((name, ok, st, dt, extra))
    print(f"{'PASS' if ok else 'FAIL'}  {name:34s} {st}  {dt:6.2f}s  {str(extra)[:90]}")

# 1 健康检查
scenario('health', lambda: req('/health'))
# 2 模型列表
scenario('models list', lambda: req('/v1/models'))
# 3 非流式基线 x3
for i in range(3):
    scenario(f'non-stream baseline #{i+1}', lambda: req('/v1/chat/completions',
        {'model':'gpt-4o-mini','messages':[{'role':'user','content':'Reply with exactly: BENCH-OK'}],'max_tokens':30}))
# 4 流式
scenario('stream TTFT', lambda: req('/v1/chat/completions',
    {'model':'gpt-4o-mini','messages':[{'role':'user','content':'Count 1 to 5 slowly'}],'max_tokens':60,'stream':True},
    stream=True))
# 5 强模型
scenario('premium model claude-4.5-sonnet', lambda: req('/v1/chat/completions',
    {'model':'claude-4.5-sonnet','messages':[{'role':'user','content':'Reply: PREMIUM-OK'}],'max_tokens':30}))
# 6 错误路径: 无效模型
scenario('invalid model -> upstream err', lambda: req('/v1/chat/completions',
    {'model':'nonexistent-xyz','messages':[{'role':'user','content':'hi'}],'max_tokens':10}))
# 7 错误路径: 空 messages
scenario('empty messages', lambda: req('/v1/chat/completions',
    {'model':'gpt-4o-mini','messages':[],'max_tokens':10}))
# 8 错误路径: 未知路由
scenario('unknown route 404', lambda: req('/v1/nope'), expect=404)
# 9 并发 x10
def conc():
    out = []
    def worker(i):
        out.append(req('/v1/chat/completions',
            {'model':'gpt-4o-mini','messages':[{'role':'user','content':f'Say C-{i}'}],'max_tokens':20},
            timeout=120))
    ts = [threading.Thread(target=worker,args=(i,)) for i in range(10)]
    t0=time.time()
    [t.start() for t in ts]; [t.join() for t in ts]
    oks = sum(1 for s,_,_ in out if 200<=s<300)
    dts = [d for _,d,_ in out]
    return 200 if oks==10 else 500, time.time()-t0, f'{oks}/10 ok p50={statistics.median(dts):.2f}s max={max(dts):.2f}s'
scenario('concurrency x10', conc)
# 10 stats 一致性
scenario('stats consistency', lambda: req('/stats'))

print('\n==== SUMMARY ====')
npass = sum(1 for _,ok,_,_,_ in results if ok)
print(f'{npass}/{len(results)} PASS')
sys.exit(0 if npass==len(results) else 1)
