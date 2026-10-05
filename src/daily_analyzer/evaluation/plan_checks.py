"""执行条件与R36的确定性核验；只标记，不修改模型值或历史。"""
import math
import re

HIGHS = ('P_High', '20d_High', '60d_High', '252d_High')
MAS = ('close_10_ema', 'close_20_sma', 'close_50_sma', 'close_200_sma')
SUPPORTS = ('P_Low', 'P_High', '20d_Low', '60d_Low', '252d_Low', *MAS, '20d_High', '60d_High', '252d_High')
RR_REASON = re.compile(r'目标要求止损|为满足盈亏比|才能满足盈亏比|放宽[^。；]{0,15}盈亏比|盈亏比不达标|盈亏比要求止损|(?:凑|满足|保证)盈亏比[^。；]{0,15}(?:止损|区间|目标)')


def finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def anchor_values(anchors):
    return {key: price for key, value in (anchors or {}).items()
            if (price := finite(value.get('value') if isinstance(value, dict) else value)) is not None}


def _anchor_names(text, candidates):
    """匹配输入锚点名及常见名称，不能用无名价格造锚点。"""
    text = str(text or '').replace(' ', '').lower()
    def matches(word):
        return re.search(r'(?<![a-z0-9_])' + re.escape(word) + r'(?![a-z0-9_])', text)
    # 显式表键优先于别名，避免同一句里的附带解释覆盖明确键。
    exact = [key for key in candidates if matches(key.lower())]
    if exact:
        yield from exact
        return
    aliases = {'P_High': ('p日高', 'p日高点', 'p日前高'), 'P_Low': ('p日低', 'p日低点'),
               'close_10_ema': ('10ema', 'ema10', '10日ema', '十日ema'),
               'close_20_sma': ('close_20_sma', '20sma', 'sma20', 'ma20', '20日sma', '20日均线', '二十日均线'),
               'close_50_sma': ('close_50_sma', '50sma', 'sma50', 'ma50', '50日sma', '50日均线'),
               'close_200_sma': ('close_200_sma', '200sma', 'sma200', 'ma200', '200日sma', '200日均线'),
               '252d_High': ('252d_high', '252日高', '52周高', '52周高点'),
               '252d_Low': ('252d_low', '252日低', '52周低', '52周低点')}
    for key in candidates:
        words = aliases.get(key, (key.lower(), key.split('d_')[0] + '日' + ('高' if key.endswith('High') else '低')))
        # 所有周期都带数字边界，不能把MA500/120日高/150日均线猜为较短周期。
        if any(matches(word) for word in words):
            yield key


def check_buy_leg(leg, anchors, atr=None, *, config=None, text='', structured=True):
    """同时保留原目标检查与按R36期望目标重算的资格。"""
    config = config or {}
    values = anchor_values(anchors)
    atr = finite(atr if atr is not None else values.get('atr'))
    upper = finite(leg.get('zone_high', leg.get('high')))
    lower = finite(leg.get('zone_low', leg.get('low')))
    stop = finite(leg.get('stop_loss'))
    target = finite(leg.get('first_target'))
    flags = {}
    reason = str(leg.get('reason') or '') + '\n' + str(text or '')
    flags['rr_reason_text'] = bool(RR_REASON.search(reason))
    if atr is None or atr <= 0 or upper is None or lower is None or not values:
        flags['anchors_unavailable'] = True
        return {'d_atr': None, 'rr': None, 'expected_target': None, 'checks': flags, 'qualified': False}
    eps = 1e-9
    # 0.01金额容差只处理显示到分的价位，候选距离仍按0.05ATR严格定义。
    tolerance = 0.01 + eps
    resistance = sorted((values[key], key) for key in (*HIGHS, *MAS) if key in values and values[key] > upper + 0.05 * atr)
    near = [(price, key) for price, key in resistance if key in HIGHS and price - upper < atr - eps]
    expected = next(((price, key) for price, key in resistance if price - upper >= config.get('price_plan_min_target_atr', 1) * atr - eps), None)
    if not resistance:
        expected = (upper + config.get('price_plan_alt_target_atr', 3) * atr, 'ATR替代')
    expected_price = expected[0] if expected else None
    d = (upper - stop) / atr if stop is not None else None
    risk = upper - stop if stop is not None else None
    rr = (target - upper) / risk if target is not None and risk is not None and risk > 0 else None
    expected_rr = (expected_price - upper) / risk if expected_price is not None and risk is not None and risk > 0 else None
    candidates = list(_anchor_names(leg.get('stop_anchor'), SUPPORTS)) if structured else list(SUPPORTS)
    valid_anchor = next((key for key in candidates if key in values and stop is not None and
                         values[key] < upper and stop - tolerance <= values[key] <= stop + config.get('price_plan_stop_buffer_atr_max', 0.5) * atr + tolerance), None)
    flags.update(zone_under_horizontal_resistance=bool(near),
                 target_mismatch=expected_price is None or target is None or abs(target - expected_price) > 0.25 * atr + tolerance,
                 stop_unanchored=valid_anchor is None,
                 stop_distance_out_of_range=d is None or not config.get('price_plan_stop_atr_min', 1) - tolerance / atr <= d <= config.get('price_plan_stop_atr_max', 2.5) + tolerance / atr,
                 rr_below_min=rr is None or rr < config.get('price_plan_min_reward_risk', 1.5) - eps,
                 target_far=target is not None and target - upper > 3 * atr + tolerance,
                 zone_invalid=lower <= 0 or lower > upper)
    if structured:
        flags['target_unanchored'] = expected is None or (expected[1] != 'ATR替代' and expected[1] not in list(_anchor_names(leg.get('target_anchor'), (*HIGHS, *MAS)))) or (expected is not None and expected[1] == 'ATR替代' and leg.get('target_method') != 'ATR替代')
    expected_fails = [key for key in ('zone_under_horizontal_resistance', 'stop_unanchored', 'stop_distance_out_of_range', 'zone_invalid') if flags[key]]
    if flags.get('target_unanchored'):
        expected_fails.append('target_unanchored')
    if expected_rr is None or expected_rr < config.get('price_plan_min_reward_risk', 1.5) - eps:
        expected_fails.append('rr_below_min')
    return {'d_atr': d, 'rr': rr, 'expected_rr': expected_rr,
            'expected_target': {'name': expected[1], 'price': expected_price} if expected else None,
            'stop_anchor': valid_anchor,
            'stop_anchor_name_status': ('recognized' if candidates else 'unrecognized' if leg.get('stop_anchor') else 'missing') if structured else 'parsed_zone',
            'target_anchor_name_status': ('recognized' if list(_anchor_names(leg.get('target_anchor'), (*HIGHS, *MAS))) else 'unrecognized' if leg.get('target_anchor') else 'missing') if structured else 'parsed_zone',
            'checks': flags,
            'r36_expected_fails': expected_fails, 'qualified': not expected_fails}


def leg_conflict_flags(rating, buy_legs, reduce_legs, *, enabled=True):
    """持仓条件冲突只是提示，不改价、不改评级。"""
    buy = [leg for leg in (buy_legs or []) if isinstance(leg, dict)]
    active_buy = [leg for leg in buy if leg.get('status') in ('可执行', '待触发')]
    reduce = [leg for leg in (reduce_legs or []) if isinstance(leg, dict)]
    risk = [leg for leg in reduce if leg.get('kind') == '风险减配']
    return {'buy_leg_conflicts_rating': rating in ('Underweight', 'Sell') and any(leg.get('status') in ('可执行', '待触发') for leg in buy),
            'risk_trigger_above_buy_zone': any(finite(s.get('trigger_price')) is not None and finite(b.get('zone_low')) is not None and finite(s.get('trigger_price')) > finite(b.get('zone_low')) + 0.01 for s in risk for b in active_buy),
            'risk_reduce_missing_post_allocation': any(finite(leg.get('post_allocation_pct')) is None for leg in risk),
            'legs_missing': enabled and not buy and not reduce}


def decision_plan_checks(result, config):
    """仅正式新结果调用；旧记录渲染不重新核验。"""
    from .price_plans import extract_plans
    blocks = result.get('context_blocks') or {}
    anchors = ((blocks.get('price_anchors') or {}).get('data') or {}).get('anchors') or {}
    flags = dict(result.get('decision_flags') or {})
    checks = {}
    for layer, key in (('trader', 'trader_proposal'), ('pm', 'pm_decision')):
        data = (result.get('structured') or {}).get(key) or {}
        buy = data.get('buy_legs') or []
        reduce = data.get('reduce_legs') or []
        if config.get('price_plan_legs', True):
            flags[layer] = {**(flags.get(layer) or {}), **leg_conflict_flags(data.get('rating') or data.get('action') or result.get('final_rating'), buy, reduce)}
        if config.get('price_plan_target_rule', 'r36') == 'r36':
            if buy or reduce:
                # 原始建/加仓正文仍是检查来源，不因结构腿存在跳过禁止倒推措辞。
                original_text = '\n'.join(str(data.get(name) or '') for name in ('entry_plan', 'add_plan'))
                checks[layer] = [{**check_buy_leg(leg, anchors, config=config, text=original_text), 'status': leg.get('status')}
                                 for leg in buy if isinstance(leg, dict)]
            else:
                plans = extract_plans(result, layer=layer)
                checks[layer] = [{**check_buy_leg(plan, anchors, config=config, text=plan.get('text'), structured=False), 'status': 'parsed_zone'}
                                 for name, plan in plans.items() if name != 'reduce_plan' and plan.get('parse_status') == 'parsed']
    if checks:
        flags['plan_checks'] = checks
    return flags


def execution_matrix(rating, target_pct, buy_legs, reduce_legs, tolerance=10):
    """用户自行对照持仓，系统不读取账户。"""
    def val(value, *, price=True):
        parsed = finite(value)
        return (f'{parsed:.2f}' if price else f'{parsed:g}') if parsed is not None else '（未提供）'
    buy = [x for x in (buy_legs or []) if isinstance(x, dict)]
    reduce = [x for x in (reduce_legs or []) if isinstance(x, dict)]
    active = [x for x in buy if x.get('status') in ('可执行', '待触发')]
    if rating in ('Underweight', 'Sell'):
        entry = f'不新建仓（评级{rating}）'
        add = '不加仓（评级偏空，目标为上限）'
    elif active:
        pieces = []
        for leg in active:
            prefix = f'待触发：收盘站上{val(leg.get("trigger_price"))}后 ' if leg.get('status') == '待触发' else '可执行：'
            pieces.append(prefix + f'{val(leg.get("zone_low"))}–{val(leg.get("zone_high"))}，止损{val(leg.get("stop_loss"))}，目标{val(leg.get("first_target"))}（{leg.get("target_method") or "未提供"}）')
        entry = '；'.join(pieces)
        add = f'同上，补至{val(target_pct, price=False)}%' if finite(target_pct) is not None else '同上；最终目标配置未提供，先复评后确认补仓差额'
    else:
        observations = list(dict.fromkeys(val(x.get('trigger_price') if finite(x.get('trigger_price')) is not None else x.get('zone_low')) for x in buy if finite(x.get('trigger_price')) is not None or finite(x.get('zone_low')) is not None))
        entry = '暂无合格买点' + ('；观察 ' + ' / '.join(observations) if observations else '')
        add = '暂无合格买点；仅复评，不补仓'
    excess = [x for x in reduce if x.get('kind') == '超配回落']
    risk = [x for x in reduce if x.get('kind') == '风险减配']
    high = '；'.join((f'{val(x.get("zone_low"))}–{val(x.get("zone_high"))} 受阻' if x.get('trigger_rule') == '进入区间受阻' else str(x.get('trigger_rule') or '条件未提供')) + f'减至{val(target_pct, price=False)}%' for x in excess) or '仅超出目标部分按条件减回目标；未提供时机'
    risk_parts = []
    for item in risk:
        trigger = item.get('trigger_rule') or '未提供条件'
        price = finite(item.get('trigger_price'))
        if price is not None:
            trigger += val(price)
        if item.get('reason'):
            trigger += '（' + str(item['reason']) + '）'
        post = finite(item.get('post_allocation_pct'))
        risk_parts.append(trigger + ' → 降至' + val(post, price=False) + ('%' if post is not None else '') + '并复评')
    risk_text = '；'.join(risk_parts) or '未提供风险减配条件'
    parsed_tolerance = finite(tolerance)
    tolerance_note = (f'与目标相差<{parsed_tolerance:g}个百分点视为已达标'
                      if parsed_tolerance is not None and parsed_tolerance > 0 else '容差关闭，按目标精确比较')
    buy_details = []
    for item in buy:
        buy_details.append(f'{item.get("kind") or "未提供类别"}｜{item.get("status") or "未提供状态"}｜'
                           f'{item.get("trigger_rule") or "未提供触发"} {val(item.get("trigger_price"))}｜'
                           f'连续确认{val(item.get("confirm_days"), price=False)}日｜区间{val(item.get("zone_low"))}–{val(item.get("zone_high"))}｜'
                           f'止损{val(item.get("stop_loss"))}（{item.get("stop_anchor") or "锚点未提供"}）｜'
                           f'目标{val(item.get("first_target"))}（{item.get("target_method") or "方法未提供"}；{item.get("target_anchor") or "锚点未提供"}）｜'
                           + str(item.get('reason') or ''))
    reduction_details = [f'{item.get("kind") or "未提供类别"}｜{item.get("trigger_rule") or "触发未提供"} {val(item.get("trigger_price"))}｜'
                         f'区间{val(item.get("zone_low"))}–{val(item.get("zone_high"))}｜减后配置{val(item.get("post_allocation_pct"), price=False)}'
                         + ('%' if finite(item.get('post_allocation_pct')) is not None else '') + '｜' + str(item.get('reason') or '') for item in reduce]
    output = []
    for label, text in [('无仓', entry), ('低于目标', add), ('高于目标', high), ('风险', risk_text)]:
        details = buy_details if label in ('无仓', '低于目标') else reduction_details
        output.append({'label': label, 'text': text, 'full_text': text + '\n' + '\n'.join(details), 'tolerance_note': tolerance_note})
    return output
