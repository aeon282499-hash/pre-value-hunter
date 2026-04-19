"""
メーカー公式抽選情報取得モジュール。
プレバン（プレミアムバンダイ）・GSC（グッドスマイルカンパニー）などのRSS/HTMLをパース。
現在はダミー実装。将来的にRSSフィードと差し替え予定。
"""
from datetime import datetime, timedelta


_DUMMY_LOTTERIES = [
    {
        "name": "【プレバン】機動戦士ガンダム METAL ROBOT魂 νガンダム (Ka signature) 限定版",
        "list_price": 22000,
        "mercari_estimate": 42000,
        "source_url": "https://p-bandai.jp/",
        "image": "",
        "shop": "プレミアムバンダイ",
        "review_count": 0,
        "is_limited_first_come": False,
        "entry_windows": 1,
        "category": "フィギュア",
        "category_id": "figure",
        "deadline": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
        "source": "official_dummy",
    },
    {
        "name": "【GSC】ねんどろいど ブルーアーカイブ アリス 限定版",
        "list_price": 9900,
        "mercari_estimate": 22000,
        "source_url": "https://www.goodsmile.info/",
        "image": "",
        "shop": "グッドスマイルオンラインショップ",
        "review_count": 0,
        "is_limited_first_come": False,
        "entry_windows": 2,
        "category": "フィギュア",
        "category_id": "figure",
        "deadline": (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d"),
        "source": "official_dummy",
    },
    {
        "name": "【プレバン】一番くじ ドラゴンボール超 ブロリー A賞 フィギュア",
        "list_price": 880,
        "mercari_estimate": 3800,
        "source_url": "https://p-bandai.jp/",
        "image": "",
        "shop": "プレミアムバンダイ",
        "review_count": 0,
        "is_limited_first_come": False,
        "entry_windows": 1,
        "category": "一番くじ・食玩",
        "category_id": "ichiban_kuji",
        "deadline": (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d"),
        "source": "official_dummy",
    },
]


def get_official_lotteries() -> list[dict]:
    """
    ダミー: 公式抽選情報を返す。
    実装時はRSSパースやHTMLスクレイピングに差し替える。
    """
    print("  [DUMMY] 公式抽選情報を取得中...")
    return _DUMMY_LOTTERIES
