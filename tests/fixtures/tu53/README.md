# TU53 夹具清单（均从真实落盘原件截取或原样复制；只读产生，未调用任何行情/付费接口）

| 夹具 | 来源原件 | 用途 |
|---|---|---|
| daily_bars/{SPCX,SPY,QQQ,TSLA}-alpaca-data.csv | /Users/zhoulei/Documents/us-stock-daily-analyzer/data/tradingagents/cache/<同名>（10-12 批次 20:31–20:32 北京写出，cp -p 保留 mtime） | D2/H2 锚点与波动；sha256 见 evidence 复制记录 |
| daily_bars/SPY-historical-anchors-lowfour-20261004.json | data/evaluation/low-four/testing/SPY-historical-anchors.json | 坏价（68.47）剔除回归 |
| sec/submissions_CIK0001181412_batch20261012.json | data/tradingagents/cache/sec_edgar/submissions_CIK0001181412.json（批次时点） | D3 PIT 与 424B4 检测 |
| supply_events_SPCX_draft.yaml | evidence/SEC_424B4.txt 原文转录（见 evidence/SEC_424B4_lockup_excerpt.txt） | D3 首批录入与测试 |
| results/result_{SPCX,TSLA,SPY,QQQ}_20261012.json | data/runs/2026-10-12/batches/20261012T083007-16293/results/<sym>.json 字段截取（脚本 evidence/scripts/extract_fixtures.py） | 三类验收基线（锚点块、区间原文、买入腿、截断标记） |
| results/result_GSPC_index_20261001.json | data/runs/2026-10-01/batches/20261001T153401-92666/results/^GSPC.json | 指数（代理 SPY）身份样例 |
| results/news_alpaca_market_news_20261012.json | 同上 SPCX.json 的 context_blocks.macro_releases.data.market_news | H1 新闻截断披露夹具（真实 created_at） |
