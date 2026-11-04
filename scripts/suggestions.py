"""Build concise daily questions using only the report's existing signals."""
from datetime import date
from math import isfinite

ITEMS = {
    'north_scrap_price': '北部廢鋼', 'billet_price': '小鋼胚',
    'fengxing_rebar_price': '豐興鋼筋', 'h_beam_price': '東鋼H型鋼',
    'csc_wire_rod_price': '中鋼棒線',
}
PRACTICAL = [
    '鋼價波動時，工程合約的物價調整要注意什麼？',
    '鋼構工程的銲接和螺栓接合，施工時要注意什麼？',
    '鋼筋採購時，如何核對材質證明與檢驗？',
    '基地開挖前，地質鑽探與地下水位要怎麼確認？',
    '山坡地開發前，水土保持計畫該如何確認？',
]
FALLBACK = [
    '最新鋼筋與廢鋼行情有什麼變化？',
    '網站如何看待鋼材後續走勢？',
    '水泥和砂石最近的物價指數如何？',
    '鋼價波動時，工程合約的物價調整要注意什麼？',
]

def make_suggestions(report):
    if not isinstance(report, dict):
        return list(FALLBACK)
    try:
        day = date.fromisoformat(report.get('date', ''))
    except (TypeError, ValueError):
        return list(FALLBACK)
    price_data = report.get('taiwan_prices') or {}
    if not isinstance(price_data, dict):
        return list(FALLBACK)
    candidates = []
    for key, name in ITEMS.items():
        p = price_data.get(key)
        if not isinstance(p, dict) or p.get('stale'):
            continue
        value, delta, period, unit = p.get('value'), p.get('mom_change'), p.get('month'), p.get('unit')
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and isfinite(x) for x in (value, delta)):
            continue
        if not isinstance(period, str) or len(period) != 7 or period[4] != '-' or not period[:4].isdigit() or not period[5:].isdigit() or not 1 <= int(period[5:]) <= 12:
            continue
        if unit not in ('元/公斤', '元/公噸') or value - delta <= 0 or delta == 0:
            continue
        strength = abs(delta / (value - delta))
        if strength < 0.003:
            continue
        magnitude = f'{abs(delta):,.2f}'.rstrip('0').rstrip('.')
        month = f'{period[:4]}年{int(period[5:])}月'
        direction = '上漲' if delta > 0 else '下跌'
        candidates.append((strength, key, f'{month}{name}月均價{direction}{magnitude}{unit}，採購該注意什麼？'))
    candidates.sort(reverse=True)
    result = []
    if candidates:
        # Rotate among the strongest moves so the set can change day to day.
        result.append(candidates[day.toordinal() % min(3, len(candidates))][2])
    forecast = report.get('price_forecast') if isinstance(report.get('price_forecast'), dict) else {}
    forecasts = forecast.get('items') if isinstance(forecast.get('items'), dict) else {}
    targets = forecast.get('targets') if isinstance(forecast.get('targets'), dict) else {}
    preferred = [k for k in ITEMS if isinstance(forecasts.get(k), dict) and
                 isinstance(forecasts[k].get('next_month'), dict) and
                 forecasts[k]['next_month'].get('direction') in ('up', 'down', 'stable') and
                 isinstance(targets.get(k), dict) and isinstance(targets[k].get('target_month'), str)]
    if preferred:
        key = preferred[day.toordinal() % len(preferred)]
        month = targets[key]['target_month']
        if len(month) == 7 and month[4] == '-' and month[:4].isdigit() and month[5:].isdigit() and 1 <= int(month[5:]) <= 12:
            direction = {'up': '偏漲', 'down': '偏跌', 'stable': '持平'}[forecasts[key]['next_month']['direction']]
            result.append(f"網站預測{month[:4]}年{int(month[5:])}月{ITEMS[key]}{direction}，依據與反方看法是什麼？")
    if all(isinstance(price_data.get(k), dict) and not price_data[k].get('stale') and price_data[k].get('value') is not None for k in ('north_scrap_price', 'fengxing_rebar_price')):
        result.append('最近廢鋼和鋼筋價格如何變化？對工程採購有什麼影響？')
    result.append(PRACTICAL[day.toordinal() % len(PRACTICAL)])
    for q in FALLBACK:
        if len(result) >= 4:
            break
        if q not in result:
            result.append(q)
    return result[:4]
