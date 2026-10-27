# Begamob-app-2api

> Begamob「Chat AI: Ask」(com.begamob.chatgpt_openai) v35.2.8 Premium APK 逆向 → 上游协议还原 → OpenAI 兼容 2API demo。**仅用于安全研究与协议学习，请勿商用滥用。**

## TL;DR

上游 `https://chatapi.begamob.com`，核心端点 `POST /api/v1/chat`，鉴权为**客户端自签 JWT（HS256，密钥硬编码在 APK 内）**，无账号体系、无设备绑定、无 IP 限流（实测 50 并发 + 90 连发零 429）。15 个模型全部可用（GPT-4o/4.1/5 全系、Claude 4.5、Gemini 3 Pro、DeepSeek）。

```
python demo_server.py          # 端口 8915
# OpenAI 兼容: POST http://127.0.0.1:8915/v1/chat/completions
curl http://127.0.0.1:8915/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}]}'
```

## 1. APK 概览

| 项 | 值 |
|---|---|
| 包名 | `com.begamob.chatgpt_openai` |
| 版本 | 35.2.8 (352804), 构建 tag `ChatAI_v35.2.8_(352804)_25_08_2026-16_20_release` |
| 大小 | 43 MB, 7 个 dex, 27628 类（jadx 全量反编译通过） |
| 加固 | **无壳**（无 360/腾讯/梆梆；libpglarmor 只是穿山甲广告 SDK） |
| 框架 | Kotlin + Hilt + Retrofit + OkHttp4 + RxJava2/协程 |
| 三方 | Firebase、Adjust、穿山甲(Pangle)、Unity Ads、Moloco、PubNative、IronSource 等广告 SDK |

## 2. 上游协议还原

### 2.1 端点清单（jadx `OpenAiApi.java` 还原）

| 端点 | 用途 | 状态 |
|---|---|---|
| `POST /api/v1/chat` | 主聊天（GPT 系） | ✅ 实测打通 |
| `POST /api/v1/chat_v4` | GPT-4 通道 | ✅ 实测打通 |
| `POST /api/v1/chatCustom` / `/api/v2/chatCustom` / `/api/v3/chatCustom` | 自定义角色聊天 | 已还原，未逐个验证 |
| `POST /api/v2/chat` | 带图片输入聊天 | 已还原 |
| `POST /api/v1/topic_chat` | 话题聊天 | 已还原 |
| `POST /api/v1/summarize_chat` / `uploadSummaryText` | 摘要 | 已还原 |
| `POST /api/v1/suggestChatQuestion` | 推荐提问 | 已还原 |
| `POST api/v1/generate_art`、`/api/v2/art` | AI 绘图（走 aiapi-art.begamob.com） | 已还原 |
| `GET /api/getTime` | 返回 `{token:"毫秒时间戳"}` | ✅ 实测打通 |
| `wss://.../api/v1/ws/chat` | 流式 WebSocket | ⚠️ **服务端未注册（404，7 种变体全测：子协议/别名路径/chat-ai-iaa 域/aiapi-art 域均 404）**，客户端有代码但上游关闭 |

### 2.2 鉴权：客户端自签 JWT（核心发现）

`ax/bx/cx/rf.java`：

```kotlin
// 密钥硬编码，32 字节
val bytes = "stteam-ikameglobal-chatapiopenai".getBytes()
val key = Keys.hmacShaKeyFor(bytes)          // HS256
val claims = mapOf(
    "iat" to now,                              // 秒级 epoch
    "exp" to now + N,                          // 秒级 epoch（偏移任意，实测 +3600 通过）
    "bundleId" to "com.chatbot.ai.aichat.openaibot.chat",
    "os" to "Android",
    "versionApp" to "35.2.8"
)
Jwts.builder().header().add({alg:HS256, typ:JWT}).and().claims(...).signWith(key).compact()
```

Python 复刻（已实测 200）：

```python
import hmac, hashlib, base64, json, time
def b64u(b): return base64.urlsafe_b64encode(b).rstrip(b'=').decode()
now = int(time.time())
h = b64u(json.dumps({"alg":"HS256","typ":"JWT"}).encode())
p = b64u(json.dumps({"iat":now,"exp":now+3600,
      "bundleId":"com.chatbot.ai.aichat.openaibot.chat",
      "os":"Android","versionApp":"35.2.8"}).encode())
jwt = f"{h}.{p}." + b64u(hmac.new(b"stteam-ikameglobal-chatapiopenai",
                                   f"{h}.{p}".encode(), hashlib.sha256).digest())
```

> **坑**：exp 必须是**秒级** epoch。用毫秒会 401 `auth_invalid`。

### 2.3 必带 Header（jadx `tl3.java` / `OpenAiUtils.java`）

```
Authorization: Bearer <JWT>
user-header: bundleId:com.chatbot.ai.aichat.openaibot.chat/versionApp:35.2.8/OS:Android/osVersion:33/userId:/deviceId:<任意串>
User-Agent: VersionApp:35.2.8/AppId:com.chatbot.ai.aichat.openaibot.chat/Build:352804/VersionSDK:33/OS:Android/UserAgent:okhttp/4.12.0userId:/deviceId:<同上>
```

- `userId` 可为空、`deviceId` 任意值均通过 → **无设备绑定**
- `osVersion`/`VersionSDK` 用真实 SDK int（如 33）即可

### 2.4 请求/响应

请求体 = 标准 OpenAI 格式：

```json
{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}],"max_tokens":1024,"temperature":0.7}
```

响应为**非标准**结构（无 id/usage）：

```json
{"type":"com.ikame.model.ResponseResultDto.ChatCompletionDto",
 "choices":[{"index":0,"message":{"role":"assistant","content":"..."},"finish_reason":"stop"}]}
```

错误格式：
- 参数错：`400` + Spring 默认 `{timestamp,path,status,error,requestId}`
- 鉴权失败：`401` + `{"error":{"code":"401","message":"auth_invalid"}}`

### 2.5 模型矩阵（15/15 实测 200）

```
gpt-4o-mini  gpt-4o  gpt-4.1  gpt-4.1-mini  gpt-5  gpt-5-mini
claude-3.7-sonnet  claude-4.5-sonnet  claude-4.5-opus
gemini-2.5-flash  gemini-3-pro
deepseek  claude  gemini  gpt        <- 短别名也有效（上游兜底）
```

> ⚠️ **无效模型名不报错**：`nonexistent-xyz` 也返回 200（上游兜底默认模型）。渠道层做模型映射时要自己校验。
>
> ⚠️ **上下文硬上限 = 128K 中文字符**（127,900 过 / 128,000 报 400 `request_invalid`，二分法实测）。渠道层建议 127K 截断保护。

### 2.6 辅助发现

- `OpenAI-Organization` 头：AES-ECB 加密 blob（密文 `Sc7P6bs4...`，key 为 61 位数字串），仅 art 绘图域拦截器（`nn.java`）使用，聊天链路不需要
- color-phone-2.begamob.com 走固定 Bearer `DtP24ZfVPocadM9ZkDH0yA8fDmKCMK5a`（`rs3.java`）
- 流式：客户端用 WebSocket（`e16.java`），但服务端 404 → **上游当前无可用流式**，2API 侧需网关模拟 SSE

## 3. demo 交付

| 文件 | 说明 |
|---|---|
| `demo_server.py` | 端口 8915。OpenAI 兼容 `/v1/chat/completions`（非流式 + SSE 本地模拟）、`/v1/models`、`/health`、`/stats`、`/`（demo 页）、JWT 自动签发 |
| `demo.html` | 中文聊天页：15 模型分组下拉、流式打字机、健康检查面板 |
| `stress_test.py` | 第一轮 12 场景（基线/流式 TTFT/强模型/错误路径/并发 x10） |
| `stress_extreme.py` | 极限压测：阶梯并发 20/30/50、持续 3x30 连发 429 探测、长文本上下文边界 |
| `tools/probe_upstream.py` | 直连上游复刻脚本（绕过 demo，独立验证协议） |

## 4. 压测结论（本机 → 上游）

见 `benchmark_results.md`（第一轮 12/12 PASS + 极限压测数据）。

## 5. 目录

```
├── README.md
├── demo_server.py
├── demo.html
├── stress_test.py
├── stress_extreme.py
├── benchmark_results.md
└── tools/
    └── probe_upstream.py
```

## License

研究用途。不提供任何担保。
