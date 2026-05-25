# EXTERNAL_APIS — 外部 API 关键细节 & 避坑清单

本文档记录与外部服务交互时容易踩的坑。**改外部依赖代码前必看。**

---

## OKX V5 现货公开行情

### Endpoint

| 用途 | Method | URL |
|---|---|---|
| 最近 N 根（≤ 1440 历史深度） | `GET` | `https://www.okx.com/api/v5/market/candles` |
| 翻页查更老历史 | `GET` | `https://www.okx.com/api/v5/market/history-candles` |
| 当前价 / 24h 统计 | `GET` | `https://www.okx.com/api/v5/market/ticker` |

公开行情**不需要 API key**。

### Query 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `instId` | ✅ | 交易对，格式 `BTC-USDT`（破折号）。**不是 BTC/USDT，也不是 BTCUSDT。** |
| `bar` | | K 线周期，默认 `1m`。可选值见下。 |
| `limit` | | 单次返回数量，默认 100，**最大 300**。 |
| `before` | | 翻页：返回 `ts < before` 的（用旧 ts） |
| `after` | | 翻页：返回 `ts > after` 的（用新 ts） |

### bar 取值（注意大小写）

```
1s  1m  3m  5m  15m  30m  1H  2H  4H  6H  12H  1D  1W  1M
```

**H/D/W/M 必须大写**；带 `utc` 后缀（如 `1Dutc`）的是按 UTC 时区，否则是 HK（UTC+8）时区。

### 返回结构

```json
{
  "code": "0",
  "msg": "",
  "data": [
    ["1716480000000", "67800.0", "67900.0", "67750.0", "67890.0", "1234.5", "...", "...", "1"],
    ...
  ]
}
```

**`data` 是按 `ts` 倒序**（最新在前）。落到 DataFrame 后一定要 `sort_values('ts')` 翻正。

字段顺序：

| idx | 字段 | 说明 |
|---|---|---|
| 0 | `ts` | 毫秒时间戳（字符串） |
| 1 | `o` | 开盘价 |
| 2 | `h` | 最高价 |
| 3 | `l` | 最低价 |
| 4 | `c` | 收盘价 |
| 5 | `vol` | 成交量（按交易币，即 BTC-USDT 时是 BTC） |
| 6 | `volCcy` | 成交额（按计价币，USDT） |
| 7 | `volCcyQuote` | 成交额（同上，新字段，部分版本有） |
| 8 | `confirm` | `"1"` 表示这根 K 已收盘；`"0"` 表示进行中 |

### 限频

公开行情 `/api/v5/market/candles` ≈ **20 次 / 2 秒**（按 IP）。建议每次请求间隔 ≥ 0.1 秒。

如果限频，OKX 返回 HTTP 429 或 `code != "0"` 且 `msg` 包含 "rate"。

### 业务错误处理

`code` 不是 `"0"` 时就是业务错误，常见：

| code | 含义 |
|---|---|
| `50011` | 请求过于频繁 |
| `51001` | 不存在的 instId |
| `51000` | 参数错误（比如 `bar=1h` 小写） |

### 代码模板

```python
import requests
import pandas as pd

def fetch_candles(inst_id: str, bar: str = "1H", limit: int = 100) -> pd.DataFrame:
    resp = requests.get(
        "https://www.okx.com/api/v5/market/candles",
        params={"instId": inst_id, "bar": bar, "limit": str(limit)},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload["code"] != "0":
        raise RuntimeError(f"OKX error: {payload['code']} {payload['msg']}")

    df = pd.DataFrame(
        payload["data"],
        columns=["ts", "open", "high", "low", "close",
                 "vol", "vol_ccy", "vol_ccy_quote", "confirm"],
    )
    df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "vol", "vol_ccy", "vol_ccy_quote"]:
        df[col] = df[col].astype(float)
    df["confirm"] = df["confirm"] == "1"
    return df.sort_values("ts").reset_index(drop=True)
```

---

## 飞书自建应用发消息

### SDK

```
pip install lark-oapi
```

主包路径 `lark_oapi`，发消息走 `lark_oapi.api.im.v1.*`。

### 准备工作（一次性，需要用户在飞书后台操作）

1. 登录 https://open.feishu.cn → 「开发者后台」→ 「创建企业自建应用」
2. 在「凭证与基础信息」拿到 `App ID` 和 `App Secret`，填入 `.env`
3. 在「权限管理」→「API 权限」开通：
   - `im:message`（发送消息）
   - `im:message.group_at_msg`（可选：群里 @ 用户）
4. 在「应用功能」→「机器人」启用机器人
5. 在「版本管理与发布」发布上线（应用要可用）
6. 用户在目标飞书群里把机器人加进群（@ 添加）
7. 获取 `chat_id`：
   - 方法 A：调 `client.im.v1.chat.list({"page_size": 100})`，找到目标群名对应的 `chat_id`
   - 方法 B：在群里 @ 机器人随便说一句话，开通事件订阅监听 `im.message.receive_v1` 事件，event 里有 `chat_id`
   - 方法 C：飞书移动版进群 → 设置 → 群信息 → 复制群 ID（最快）

### 发文本消息

```python
import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest, CreateMessageRequestBody,
)
import json

client = lark.Client.builder() \
    .app_id(APP_ID) \
    .app_secret(APP_SECRET) \
    .log_level(lark.LogLevel.WARNING) \
    .build()

req = CreateMessageRequest.builder() \
    .receive_id_type("chat_id") \
    .request_body(
        CreateMessageRequestBody.builder()
            .receive_id(CHAT_ID)
            .msg_type("text")
            .content(json.dumps({"text": "Hello from Investment"}))   # ← content 必须是 JSON 字符串
            .build()
    ) \
    .build()

resp = client.im.v1.message.create(req)
if not resp.success():
    raise RuntimeError(f"feishu: code={resp.code} msg={resp.msg}")
```

### 关键坑

1. **`content` 是 JSON 字符串，不是 dict**。`json.dumps({"text": "..."})` 别忘了。
2. `receive_id_type` 决定 `receive_id` 的解释方式：
   - `chat_id`：群（最常用）
   - `open_id`：单个用户
   - `user_id`：企业内 user_id
   - `union_id`：跨应用统一 ID
   - `email`：邮箱
3. SDK 会自动维护 `tenant_access_token`，**不要手动刷**。
4. **client 实例全局复用一个**，不要每次发消息都新建（初始化成本高）。
5. 发卡片消息时 `msg_type="interactive"`，`content` 是卡片 JSON 字符串；schema 看飞书的「消息卡片搭建工具」生成。
6. 失败时 `resp.code` 和 `resp.msg` 给业务错误码，常见：
   - `230001` chat_id 不存在 / 机器人没进群
   - `99991663` token 失效（极少见，SDK 会自动重试）

### 干跑模式（开发用）

`.env` 里 `FEISHU_DRY_RUN=true` 时，notifier 只把消息打印到 stdout，不实际调用飞书 API。本地开发用这个，避免被限频或把群刷爆。

---

## 关于网络访问

- OKX：国内裸连大部分时候 OK，少数运营商有抖动。如果 `requests.get` 经常超时，确认下 `https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1H&limit=1` 在浏览器能不能直接打开。
- 飞书：境内访问 `open.feishu.cn` 没有问题。
