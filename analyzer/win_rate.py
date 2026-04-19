import math


def estimate_win_rate(category: dict, item: dict) -> float:
    """
    カテゴリのベース当選確率に、商品人気・応募窓口数・先着/抽選フラグで補正をかける。
    返り値: 0.01〜0.50 の float
    """
    base = category.get("win_rate_base", 0.10)

    # レビュー数が多い＝競争率高い → 当選確率を下げる
    review_count = item.get("review_count", 0)
    popularity_factor = 1.0 / (1.0 + math.log1p(review_count / 50.0))

    # 先着フラグがあれば当選確率を上げる（先着は素早さ勝負なので多少有利とみなす）
    is_lp = item.get("is_limited_first_come", False)
    type_factor = 1.3 if is_lp else 1.0

    # 複数応募窓口がある場合は有利
    entry_windows = max(1, item.get("entry_windows", 1))
    window_factor = 1.0 + 0.1 * math.log(entry_windows)

    rate = base * popularity_factor * type_factor * window_factor

    # クランプ
    return max(0.01, min(0.50, rate))
