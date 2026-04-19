"""
メルカリ相場取得モジュール。
現在はダミー実装。将来的に非公式APIや手動更新CSVと差し替え予定。

NOTE: メルカリ公式APIは現時点で一般公開されていないため、
      実装する場合はメルカリの利用規約を必ず確認すること。
"""
import random


def get_mercari_price(item_name: str, list_price: float,
                      multiplier_min: float = 1.5,
                      multiplier_max: float = 3.0) -> float | None:
    """
    ダミー: リスト価格に対してランダムなプレミアム倍率を掛けた相場を返す。
    プレミア感のないもの（倍率が低い）は None を返す確率を上げる。

    Returns:
        推定メルカリ売値（円）、または相場なしの場合 None
    """
    if list_price <= 0:
        return None

    # 20% の確率でプレ値がつかない（転売メリットなし）扱い
    if random.random() < 0.20:
        return None

    multiplier = random.uniform(multiplier_min, multiplier_max)
    estimated = list_price * multiplier

    # メルカリの出品単位（50円単位に丸める）
    estimated = round(estimated / 50) * 50
    return float(estimated)
