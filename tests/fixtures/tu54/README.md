# Tu54 真实日线输入

从生产既有Alpaca缓存只读提取2026-10-01至10-12的行，不请求网络、不手写价格。通过csv.DictReader按Date过滤、csv.DictWriter保留全部列，统一使用LF换行。

来源链：TradingAgents/tradingagents/dataflows/ohlcv_sources.py:56–69调用vendors/alpaca/ohlcv.py加载器并在清洗前落盘；加载器参数feed=sip、adjustment=all、timeframe=1Day。CSV没有请求元信息，因此不是provider当次HTTP原响应的逐字节证明。

- 原件：`/Users/zhoulei/Documents/us-stock-daily-analyzer/data/tradingagents/cache/SPCX-alpaca-data.csv`；SHA256：`75a0b7e0ddf422c563756167d2e420d6405b562b8c7991230f5fa0e3e0d03038`。
- 原件：`/Users/zhoulei/Documents/us-stock-daily-analyzer/data/tradingagents/cache/SPY-alpaca-data.csv`；SHA256：`8c21914559736f3e6ace6c500e9aef81898fed4e9dd6505777f303d378e8b50f`。
