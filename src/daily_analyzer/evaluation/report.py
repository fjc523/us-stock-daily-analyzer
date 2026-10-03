"""无模型的评级分布、排序能力、朴素基线与分层归因。"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import math
from pathlib import Path
import time
from typing import Any

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from daily_analyzer.time_utils import NEW_YORK, parse_trade_date
from .settlement import load_outcomes, number

SCORES = {"Buy": 2, "Overweight": 1, "Hold": 0, "Underweight": -1, "Sell": -2}
LAYERS = {"rm": "研究经理", "trader": "交易员", "pm": "组合经理"}


def spearman(scores: list[float], returns: list[float]) -> float | None:
    """平均秩处理并列，常数评分或收益没有定义。"""
    if len(scores) < 2 or len(set(scores)) < 2 or len(set(returns)) < 2:
        return None
    ranks = pd.Series(scores, dtype=float).rank(method="average").to_numpy()
    outcomes = pd.Series(returns, dtype=float).rank(method="average").to_numpy()
    return float(np.corrcoef(ranks, outcomes)[0, 1])


def rank_ic(samples: list[dict[str, Any]]) -> dict[str, Any]:
    dates = defaultdict(list)
    for row in samples:
        dates[row["date"]].append(row)
    eligible = [group for group in dates.values() if len(group) >= 5]
    valid = []
    valid_n = 0
    for group in eligible:
        value = spearman([row["score"] for row in group], [row["return"] for row in group])
        if value is not None:
            valid.append(value)
            valid_n += len(group)
    if not valid:
        value = spearman([row["score"] for row in samples], [row["return"] for row in samples])
        return {"mode": "池化", "n": len(samples), "valid_dates": 0, "eligible_dates": len(eligible), "mean": value, "std": None, "t": None}
    average = float(np.mean(valid))
    std = float(np.std(valid, ddof=1)) if len(valid) >= 2 else None
    t = average / (std / math.sqrt(len(valid))) if std is not None and std > 0 else None
    return {"mode": "横截面", "n": valid_n, "valid_dates": len(valid), "eligible_dates": len(eligible), "mean": average, "std": std, "t": t}


def bootstrap_mean(values: list[float], *, seed: int = 20261003) -> list[float | None]:
    """固定种子的1000次重采样均值区间，仅描述当前样本。"""
    if not values:
        return [None, None]
    rng = np.random.default_rng(seed)
    array = np.asarray(values, dtype=float)
    # 分批控制内存，保留固定随机序列和1000次统计定义。
    means = np.concatenate([rng.choice(array, size=(100, len(array)), replace=True).mean(axis=1) for _ in range(10)])
    return [float(value) for value in np.percentile(means, [2.5, 97.5])]


def summary(values: list[float]) -> dict[str, Any]:
    return {"n": len(values), "mean": float(np.mean(values)) if values else None,
            "median": float(np.median(values)) if values else None, "ci": bootstrap_mean(values)}


def hit_rates(samples: list[dict[str, Any]], window: int) -> dict[str, Any]:
    three, signs = [], []
    for row in samples:
        predicted = 1 if row["score"] > 0 else -1 if row["score"] < 0 else 0
        if row.get("atr_pct") is not None:
            deadzone = 0.5 * row["atr_pct"] * math.sqrt(window)
            actual = 1 if row["return"] > deadzone else -1 if row["return"] < -deadzone else 0
            three.append(actual == predicted)
        if predicted:
            signs.append((row["return"] > 0 and predicted > 0) or (row["return"] < 0 and predicted < 0))
    return {"three_n": len(three), "three": sum(three) / len(three) if three else None,
            "sign_n": len(signs), "sign": sum(signs) / len(signs) if signs else None}


def samples_for(rows: list[dict[str, Any]], layer: str, window: int) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        outcome = row.get("windows", {}).get(str(window), {})
        score = SCORES.get(row.get("ratings", {}).get(layer))
        value = number(outcome.get("primary_return"))
        if outcome.get("status") != "settled" or score is None or value is None:
            continue
        anchors = row.get("anchors", {})
        close = number(anchors.get("P_Close"), positive=True)
        atr = number(anchors.get("atr"), positive=True)
        samples.append({"date": row["trade_date"], "score": score, "return": value,
                        "atr_pct": atr / close if atr is not None and close is not None else None,
                        "close": close, "ma200": number(anchors.get("close_200_sma"), positive=True),
                        "momentum": number(row.get("momentum_20d")), "record": row})
    return samples


def metrics(samples: list[dict[str, Any]], window: int) -> dict[str, Any]:
    return {"n": len(samples), "hits": hit_rates(samples, window), "ic": rank_ic(samples),
            "groups": {rating: summary([row["return"] for row in samples if row["score"] == score]) for rating, score in SCORES.items()}}


def baseline_comparison(samples: list[dict[str, Any]], window: int) -> dict[str, Any]:
    missing = {"ATR/P_Close": sum(row["atr_pct"] is None for row in samples),
               "MA200/P_Close": sum(row["ma200"] is None or row["close"] is None for row in samples),
               "20日动量": sum(row["momentum"] is None for row in samples)}
    common = [row for row in samples if row["atr_pct"] is not None and row["close"] is not None and row["ma200"] is not None and row["momentum"] is not None]
    mapping = {"永远Hold": lambda row: 0, "永远看多": lambda row: 1,
               "200日均线趋势": lambda row: 1 if row["close"] > row["ma200"] else -1,
               "20日动量符号": lambda row: 1 if row["momentum"] > 0 else -1}
    comparisons = {"模型同样本": metrics(common, window)}
    for name, scoring in mapping.items():
        comparisons[name] = metrics([{**row, "score": scoring(row)} for row in common], window)
    return {"n": len(common), "excluded": len(samples) - len(common), "missing": missing, "metrics": comparisons}


def attribution(rows: list[dict[str, Any]], window: int) -> dict[str, Any]:
    result = {}
    for previous, following in (("rm", "trader"), ("trader", "pm")):
        groups = {"上调": [], "下调": []}
        for row in rows:
            outcome = row.get("windows", {}).get(str(window), {})
            value = number(outcome.get("primary_return"))
            before, after = (SCORES.get(row.get("ratings", {}).get(layer)) for layer in (previous, following))
            if outcome.get("status") != "settled" or value is None or before is None or after is None:
                continue
            if after != before:
                groups["上调" if after > before else "下调"].append(value)
        result[f"{previous}→{following}"] = {name: summary(values) for name, values in groups.items()}
    return result


def distributions(rows: list[dict[str, Any]], layer: str, *, weekly: bool = False) -> list[dict[str, Any]]:
    dates = defaultdict(list)
    for row in rows:
        day = date.fromisoformat(row["trade_date"])
        key = (day - timedelta(days=day.weekday())).isoformat() if weekly else day.isoformat()
        dates[key].append(row)
    output = []
    for day, group in sorted(dates.items()):
        ratings = Counter(row.get("ratings", {}).get(layer) for row in group)
        n = sum(ratings.get(name, 0) for name in SCORES)
        regimes = Counter(row.get("market_regime") or "缺失" for row in group)
        output.append({"date": day, "n": n, "missing": len(group) - n,
                       "counts": {name: ratings.get(name, 0) for name in SCORES}, "regimes": dict(regimes)})
    return output


def bearish_warning(rows: list[dict[str, Any]]) -> bool:
    valid_days = sorted({date.fromisoformat(row["trade_date"]) for row in rows if xcals.get_calendar("XNYS").is_session(pd.Timestamp(row["trade_date"]))})
    if not valid_days:
        return False
    calendar = xcals.get_calendar("XNYS")
    last = pd.Timestamp(valid_days[-1])
    expected = [calendar.session_offset(last, offset).date().isoformat() for offset in range(-9, 1)]
    strong = 0
    for day in expected:
        group = [row for row in rows if row["trade_date"] == day and row.get("ratings", {}).get("pm") in SCORES]
        if not group or any(SCORES[row["ratings"]["pm"]] > 0 for row in group):
            return False
        regimes = Counter(row.get("market_regime") for row in group if row.get("market_regime"))
        if regimes.get("偏强", 0) > sum(regimes.values()) / 2:
            strong += 1
    return strong > 5


def analyze(rows: list[dict[str, Any]], *, window: int = 5, layer: str = "all") -> dict[str, Any]:
    layers = list(LAYERS) if layer == "all" else [layer]
    result = {"rows": len(rows), "window": window, "warning": bearish_warning(rows), "layers": {}, "attribution": attribution(rows, window)}
    for name in layers:
        samples = samples_for(rows, name, window)
        result["layers"][name] = {"metrics": metrics(samples, window), "baselines": baseline_comparison(samples, window),
            "daily": distributions(rows, name), "weekly": distributions(rows, name, weekly=True),
            "entry_groups": {basis: summary([s["return"] for s in samples if s["record"]["entry"]["basis"] == basis]) for basis in sorted({s["record"]["entry"]["basis"] for s in samples})},
            "asset_groups": {metric: summary([s["return"] for s in samples if s["record"]["primary_metric"] == metric]) for metric in sorted({s["record"]["primary_metric"] for s in samples})},
            "sector_aux": summary([value for s in samples if (value := number(s["record"]["windows"][str(window)].get("excess_vs_sector"))) is not None])}
    return result


def _value(value: Any, *, percentage: bool = False) -> str:
    if value is None:
        return "未定义/不可用"
    return f"{value * 100:.2f}%" if percentage else f"{value:.4f}"


def _sample_note(n: int) -> str:
    return f"n={n}" + ("；样本不足，仅供参考" if n < 30 else "")


def _metric_lines(label: str, result: dict[str, Any]) -> list[str]:
    hits, ic = result["hits"], result["ic"]
    return [f"{label}：{_sample_note(result['n'])}",
            f"- 三分类命中率：{_value(hits['three'], percentage=True)}（{_sample_note(hits['three_n'])}）；符号命中率（不含Hold）：{_value(hits['sign'], percentage=True)}（{_sample_note(hits['sign_n'])}）。",
            f"- Rank IC（{ic['mode']}）：均值 {_value(ic['mean'])}，标准差 {_value(ic['std'])}，t值 {_value(ic['t'])}；{_sample_note(ic['n'])}，有效横截面日期 {ic['valid_dates']}/{ic['eligible_dates']}。"]


def _group_table(groups: dict[str, dict[str, Any]], label: str) -> list[str]:
    lines = [f"\n{label}", "", "| 分组 | 样本数与限制 | 主口径均值 | 中位数 | 均值95%区间 |", "|---|---|---:|---:|---|"]
    for name, group in groups.items():
        low, high = group["ci"]
        lines.append(f"| {name} | {_sample_note(group['n'])} | {_value(group['mean'], percentage=True)} | {_value(group['median'], percentage=True)} | {_value(low, percentage=True)} 至 {_value(high, percentage=True)} |")
    return lines


def render_report(rows: list[dict[str, Any]], result: dict[str, Any], now: datetime) -> str:
    window = result["window"]
    lines = [f"# 评级评估报告 · {now.date().isoformat()}", "", f"生成时刻：{now.isoformat(timespec='seconds')}；窗口：{window}交易日；默认current筛选；{_sample_note(len(rows))}。", "",
             "本报告仅描述已观察样本，不证明策略有效性。真实未来窗口尚未成熟的记录保持 pending；未来运行验收为 NOT_TESTED。"]
    if result["warning"]:
        lines += ["", '<span style="color:red">告警：最近10个实际交易日均有观测，PM 看多占比为0，且多数日市场环境偏强。</span>']
    statuses = Counter(row.get("windows", {}).get(str(window), {}).get("status", "未配置") for row in rows)
    lines += ["", "窗口状态：" + "；".join(f"{key} n={value}" for key, value in sorted(statuses.items())) + "。"]
    for layer, data in result["layers"].items():
        lines += ["", f"## {LAYERS[layer]}", ""]
        for period, title in (("daily", "每日"), ("weekly", "每周（周一为起点）")):
            lines += ["", f"{title}评级分布", "", "| 日期 | 样本数与限制 | Buy | Overweight | Hold | Underweight | Sell | 缺评级 | 同期市场环境（记录数） |", "|---|---|---:|---:|---:|---:|---:|---:|---|"]
            for row in data[period]:
                parts = [f"{row['counts'][rating] / row['n'] * 100:.1f}%" if row['n'] else "不可用" for rating in SCORES]
                lines.append(f"| {row['date']} | {_sample_note(row['n'])} | " + " | ".join(parts) + f" | {row['missing']} | {row['regimes']} |")
        lines += ["", *_metric_lines("全部成熟可评估样本", data["metrics"])]
        lines += _group_table(data["metrics"]["groups"], "按评级分档收益")
        baseline = data["baselines"]
        lines += ["", f"四基线同样本比较：{_sample_note(baseline['n'])}；剔除 {baseline['excluded']}；缺项计数（可重叠）{baseline['missing']}。"]
        for name, metric in baseline["metrics"].items():
            lines += ["", *_metric_lines(name, metric)]
        lines += _group_table(data["entry_groups"], "按入场类型分组（盘中为收盘近似）")
        lines += _group_table(data["asset_groups"], "按资产主口径分组（raw_return=绝对收益）")
        lines += _group_table({"股票板块超额辅助": data["sector_aux"]}, "板块辅助口径（非主口径）")
    lines += ["", "## 改评级子样本归因", "", "上/下调的收益仅描述对应子样本，不代表改动因果效果。"]
    for transition, groups in result["attribution"].items():
        lines += _group_table(groups, transition)
    lines += ["", "## 口径说明", "",
        "1. 唯一键run_id+symbol；只读取is_current=true，按trade_date筛选；重复非current运行保留审计而不重复统计。收益为小数比例，未模拟资金、组合、交易成本。指数使用代理ETF；指数/配置宽基主口径绝对收益，股票/其他ETF主口径对SPY超额，股票板块超额为辅助；SPY代理对自身超额为空。",
        "2. finished_at开盘前取当日开，开盘至实际收盘（含边界）取当日收盘近似；收盘后/休市取下一交易日开。XNYS含假日/半日市；开盘窗口N含入场日，收盘窗口N从下一交易日起；标的和基准入场类型/出场收盘相同；每个资产窗口在同一来源和同次复权快照取入场/出场，窗口pricing记录实际价格与来源，顶层entry.price保留首次展示观测（可能不同复权单位），不用于后续复权收益；只用完整日线，缺价不可用、未成熟pending。",
        "3. Buy/Overweight/Hold/Underweight/Sell评分=2/1/0/-1/-2。死区d=0.5×分析时ATR14/P_Close×sqrt(N)；收益>d涨、<-d跌、边界含在平。看多对应涨、Hold对应平、看空对应跌；缺ATR/P_Close不进入三分类。符号命中率排除Hold，收益0无方向命中。",
        "4. Spearman采用并列平均秩；同日n≥5计算横截面，报告有效日期IC均值、样本标准差、t=均值/(标准差/sqrt(有效日期数))。无有效横截面改池化并注明。常数评分/收益IC未定义；仅一个有效日期或标准差0时标准差/t相应未定义；池化不报时间序列t。",
        "5. 评级组均值/中位数；95%区间为1000次固定种子20261003重采样均值的2.5/97.5百分位，确定可复现。小样本或单样本区间不证明有效性，n<30仅供参考。",
        "6. 四基线：永远Hold评分0；永远看多评分1；P_Close>分析时MA200评分1否则-1；截至分析P的20交易日收益>0评分1否则-1。模型与四基线共享收益、评级、ATR/P_Close、MA200及动量完备交集，剔除与缺项可重叠计数；常数基线IC未定义。",
        "7. 分布按日期/周一分组，缺评级不填Hold；市场环境保持原始记录。告警需要最近10个实际交易日均有评级观测、PM看多为0且超过半数日期多数记录环境偏强，缺日期不补造。三层改评级只统计双方评级与成熟主收益均可用的上/下调样本。",
        "8. 每个指标标对应n，IC另标有效日期数；不同指标缺项覆盖可能不同。板块辅助分组的均值/中位数/区间使用板块超额，其余使用主收益。不同资产口径混合统计同时提供分组，不能当投资组合表现。",
        "", "## 预留：点位检验与概率校准", "", "本批未实现 C4/D2，NOT_TESTED。",
    ]
    return "\n".join(lines) + "\n"


def evaluate(root: str | Path, *, since: str | None = None, window: int = 5, layer: str = "all", now: datetime | None = None) -> dict[str, Any]:
    """纯本地报告生成，不读取行情、不调用模型。"""
    started = time.perf_counter()
    if window not in {5, 10, 20} or layer not in {*LAYERS, "all"}:
        raise ValueError("窗口或决策层参数无效")
    first = parse_trade_date(since).isoformat() if since else None
    root = Path(root)
    path = root / "data/evaluation/outcomes.jsonl"
    if not path.exists():
        raise ValueError("尚无outcomes，请先运行settle")
    rows = [row for row in load_outcomes(path) if row.get("is_current") is True and (first is None or row["trade_date"] >= first)]
    now = now or datetime.now(NEW_YORK)
    result = analyze(rows, window=window, layer=layer)
    target = root / f"data/evaluation/reports/{now.date().isoformat()}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_report(rows, result, now), encoding="utf-8")
    return {"ok": True, "path": str(target), "records": len(rows), "window": window, "layer": layer, "seconds": round(time.perf_counter() - started, 6)}
