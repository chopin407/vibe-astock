# 数据获取服务：路由、配置与排障

## 当前入口

页面、MCP、聊天工具和定时任务经 `fetchEndpoint` 使用注册表。六阶段研究经 `runFetchScripts` 执行同一注册表的脚本；二者产物仍各自保存，研究不借用其他运行的证据文件。通用端点经 `fetch_endpoint.py`、源模块、mapper 生成信封；8 个 legacy 脚本保留已有契约。

本轮检查注册表的 183 项端点，逐项核对模块、可调用函数、默认参数和 mapper；这属于静态契约检查，不代表 183 个公网端点都已联网验收。网络验收范围与结果见本机 `.local/data-service-live-audit.json`。

## 按能力选源

| 数据 | 默认路线 | 边界 |
|---|---|---|
| 主要指数中长线、沪深成交额 | TDX 健康检查 → `/index/day` → 腾讯/东财；成交额另有 baostock | 指数不复权，按业务日截断，北证50用 bj 前缀 |
| 个股前复权日线 `fetch_kline` | 已配置 TDX → 腾讯 → 东财 | TDX 先共享健康检查；每次最多800根，不拼接不同复权锚点 |
| 批量/单只行情 `tx_quotes_batch`、`tx_quote` | 腾讯完整行情 → 缺失的沪深京标的由 TDX 补位 | 整行替换，不跨源拼价格与时间戳。TDX 未核验交易所行情时间，不用于需要该时间的盘中确认；缺估值、名称仍报缺口。港美股不送入 TDX |
| 原始 TDX 行情 `tdx_lan_quotes` | 显式调用 `/quote` | 保留源级入口，字段不足输出 partial |
| 涨停/炸板/跌停、昨日涨停池 | 东财原始池 → 共享缓存 → 确定性短线计算 | 不拿当前 TDX 报价代替历史涨停名单或题材原因 |
| 财报、预期、公告、两融、板块资金、题材、海外数据 | 保留各自登记的权威源与业务备源 | TDX 当前财务快照不替代历史时点财务；行业不替代事件题材，不同资金口径不拼接 |

`sources/quotes_service.py` 是行情消费入口；`sources/tencent.py` 等仍保留明确的源级函数，供需要原始口径的取数器使用。自动生成的 `astock_ported.py` 不改写，以免再生成时丢失修改。

## 本地配置

TDX 地址和凭据保存在 `.local/tdx.json`。通用策略保存在 `.local/data-service.json`；文件可省略，使用以下默认值，修改后新取数进程自动读取：

```json
{
  "connect_timeout_sec": 3,
  "http_read_timeout_cap_sec": 30,
  "tdx_read_timeout_sec": 8,
  "tdx_kline_timeout_sec": 60,
  "tdx_health_ttl_sec": 15,
  "tdx_failure_ttl_sec": 10,
  "review_live_cache_sec": 60,
  "review_cache": true
}
```

参数必须为有限正数，最大600秒；`review_cache` 必须为布尔值。配置错误会明确失败，不把错误内容或凭据写进诊断。

共用 requests/urllib HTTP 层尊重来源更短的超时，同时限制连接和读取等待；TDX 前复权全历史计算使用单独的较长读取超时。SDK 自身的内部请求及 legacy 中未使用公共 HTTP 层的请求，仍受原有源超时与 Node 子进程总超时限制；传输超时不是整个复盘任务的总耗时保证。

TDX 健康结果在 `.local/cache/tdx-health/` 跨进程共享：成功15秒、失败10秒，过期重探。缓存键包含配置摘要，修改地址或令牌后不会复用原健康状态；缓存不保存配置原文。TDX 请求绕过环境代理，不跟随重定向。

## 缓存与证据

- 端点快照继续按端点、主体和规范化参数隔离；同查询的并发请求共享一次取数，每个订阅者仍可独立取消。
- 行情与指数趋势等在注册表显式声明 `cache_partial_sec` 的端点，可短期缓存有证据的 partial，最长60秒且受端点更短上限约束。partial 不覆盖已有完整快照；未声明的端点仍不保存 partial，短线未收盘结果保持原规则。
- 内存快照最多256项、序列化数据合计32MiB，过期和最久未使用的条目淘汰；磁盘历史不删除。这是序列化容量限制，不是进程实际内存上限。
- 非法或未来时间的快照不能作为有效缓存。失败、无证据结果不写快照；缺失值、NaN、无穷值不伪装成0。
- 东财池保留跨进程同请求锁和全局限流。盘中原始响应短期共享；所查日期16:30后取得的历史响应归档到 `.local/cache/review-http/`。空池与错误不归档；设置 `review_cache: false` 可绕过原始池缓存，再用页面刷新绕过端点快照。
- 原始响应仍在本次运行保存；行情 mapper 逐行保留实际来源与 raw_ref。通用端点信封的 `used_sources` 根据证据填充，`extra.data_service.attempts` 记录路由尝试、异常类型和耗时，不记录认证头、完整请求URL或异常自由文本。

## 检查命令

在项目根目录执行：

```powershell
# 默认只检查注册契约，不请求行情
.venv\Scripts\python.exe -X utf8 scripts\data-service-check.py

# 另做四项局域网只读探测；不调用模型，不操作交易
.venv\Scripts\python.exe -X utf8 scripts\data-service-check.py --live
```

脚本返回JSON和退出码：契约问题或实际探测失败时为非零。未配置TDX会显示 `unconfigured`，不访问默认地址。检查输出不包含地址、令牌、持仓或成交数据。

页面异常时，先运行检查，再刷新失败模块；查看信封的 `errors`、`missing`、`used_sources`、`extra.data_service` 和实际数据日。健康成功仅表示服务可达，某一路由仍可能缺标的或字段，不能据此抹去缺口。
