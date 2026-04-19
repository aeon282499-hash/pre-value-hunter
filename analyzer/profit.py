def calculate_profit(sell_price: float, list_price: float,
                     fee_rate: float = 0.10, shipping: int = 210) -> tuple[float, float]:
    net_revenue = sell_price * (1.0 - fee_rate)
    profit = net_revenue - shipping - list_price
    profit_rate = profit / list_price if list_price > 0 else 0.0
    return profit, profit_rate


def calculate_amazon_profit(sell_price: float, list_price: float,
                             referral_rate: float = 0.10,
                             fba_fee: int = 350) -> tuple[float, float]:
    """Amazon FBA想定: 参照料 + FBA手数料 - 仕入れ値"""
    net_revenue = sell_price * (1.0 - referral_rate) - fba_fee
    profit = net_revenue - list_price
    profit_rate = profit / list_price if list_price > 0 else 0.0
    return profit, profit_rate


def best_channel(mercari_profit: float, amazon_profit: float) -> str:
    """利益が高い販路を返す。同率ならAmazon優先（FBA楽）"""
    if amazon_profit >= mercari_profit:
        return "amazon"
    return "mercari"


def calculate_expected_value(profit: float, win_rate: float) -> float:
    return profit * win_rate
