import os
import random
import requests


_DUMMY_CATALOG = {
    "ポケカ 限定": [
        {"name": "ポケモンカード 151 コレクションボックス【限定版】", "list_price": 5478, "review_count": 312},
        {"name": "ポケモンカードゲーム スカーレット&バイオレット 強化拡張パック 限定BOX", "list_price": 7920, "review_count": 188},
        {"name": "ポケカ クレイバースト プレミアムトレーナーBOX", "list_price": 11000, "review_count": 95},
    ],
    "ワンピースカード 限定": [
        {"name": "ワンピースカードゲーム 頂上決戦 BOX 限定スリーブ付き", "list_price": 4180, "review_count": 204},
        {"name": "ONE PIECEカードゲーム プレミアムBOX ルフィ", "list_price": 8800, "review_count": 77},
    ],
    "遊戯王 限定": [
        {"name": "遊戯王 25th Anniversary コレクションBOX 限定", "list_price": 6600, "review_count": 143},
        {"name": "遊戯王 COLLECTORS RARE 限定セット", "list_price": 3300, "review_count": 89},
    ],
    "デュエマ 限定": [
        {"name": "デュエルマスターズ プレイス 限定カードパック", "list_price": 2200, "review_count": 55},
    ],
    "MTG 限定": [
        {"name": "マジック：ザ・ギャザリング 特別版ドラフトBOX 日本語版", "list_price": 9900, "review_count": 38},
    ],
    "最強ジャンプ 付録": [
        {"name": "最強ジャンプ 2025年最新号 付録:限定カード5枚セット", "list_price": 680, "review_count": 721},
        {"name": "最強ジャンプ バックナンバー 付録付き", "list_price": 680, "review_count": 302},
    ],
    "Vジャンプ 付録": [
        {"name": "Vジャンプ 2025年3月号 付録:遊戯王限定カード", "list_price": 730, "review_count": 512},
        {"name": "Vジャンプ バックナンバー 付録付き", "list_price": 730, "review_count": 188},
    ],
    "コロコロ 付録": [
        {"name": "月刊コロコロコミック 最新号 付録:限定ミニフィギュア", "list_price": 530, "review_count": 634},
    ],
    "一番くじ 限定": [
        {"name": "一番くじ ドラゴンボール 超激戦 A賞フィギュア", "list_price": 880, "review_count": 445},
        {"name": "一番くじ ワンピース 頂上決戦 ラストワン賞", "list_price": 880, "review_count": 312},
        {"name": "一番くじ 鬼滅の刃 柱合会議 B賞フィギュア", "list_price": 880, "review_count": 278},
    ],
    "食玩 限定": [
        {"name": "食玩 ドラゴンボール超 フィギュアシリーズ 全6種BOX", "list_price": 3960, "review_count": 166},
        {"name": "食玩 ポケモン ポケットモンスター フィギュア 全8種", "list_price": 2640, "review_count": 234},
    ],
    "プライズ 限定": [
        {"name": "プライズ SPM フィギュア 鬼滅の刃 炭治郎", "list_price": 1980, "review_count": 89},
    ],
    "ねんどろいど 限定": [
        {"name": "ねんどろいど 限定版 初音ミク 16th Anniversary", "list_price": 8800, "review_count": 67},
        {"name": "ねんどろいど ゼルダの伝説 リンク 限定DX版", "list_price": 9900, "review_count": 43},
    ],
    "figma 限定": [
        {"name": "figma 呪術廻戦 五条悟 術式展開ver. 限定版", "list_price": 9350, "review_count": 52},
    ],
    "プライズフィギュア": [
        {"name": "プライズ フィギュア チェンソーマン マキマ 全高21cm", "list_price": 2860, "review_count": 128},
        {"name": "プライズ フィギュア ジョジョの奇妙な冒険 ダイオ 限定", "list_price": 3520, "review_count": 77},
    ],
    "Apple 限定 コラボ": [
        {"name": "AirPods Pro 2nd Gen 限定カラー コレクターズエディション", "list_price": 39800, "review_count": 23},
    ],
    "コラボ イヤホン 限定": [
        {"name": "ソニー WF-1000XM5 アニメコラボ限定版 ワイヤレスイヤホン", "list_price": 28600, "review_count": 31},
        {"name": "JBL × キャラクターコラボ LIVE FREE 2 限定カラー", "list_price": 16500, "review_count": 18},
    ],
}

_DEFAULT_DUMMY = [
    {"name": "限定コレクターズアイテム", "list_price": 3300, "review_count": 50},
]


def _parse_item(raw: dict, keyword: str) -> dict:
    item = raw.get("Item", raw)
    images = item.get("mediumImageUrls", [])
    image_url = images[0].get("imageUrl", "") if images else ""
    return {
        "name": item.get("itemName", ""),
        "list_price": int(item.get("itemPrice", 0)),
        "url": item.get("itemUrl", ""),
        "image": image_url,
        "shop": item.get("shopName", ""),
        "review_count": int(item.get("reviewCount", 0)),
        "is_limited_first_come": False,
        "entry_windows": 1,
        "source": "rakuten",
    }


def _dummy_items(keyword: str) -> list[dict]:
    catalog = _DUMMY_CATALOG.get(keyword, _DEFAULT_DUMMY)
    results = []
    for d in catalog:
        item = {
            "name": d["name"],
            "list_price": d["list_price"],
            "url": "https://item.rakuten.co.jp/example/dummy/",
            "image": "",
            "shop": "サンプルショップ",
            "review_count": d["review_count"],
            "is_limited_first_come": random.random() > 0.6,
            "entry_windows": random.randint(1, 3),
            "source": "rakuten_dummy",
        }
        results.append(item)
    return results


def search_rakuten(keyword: str, app_id: str, hits: int = 10) -> list[dict]:
    access_key = os.environ.get("RAKUTEN_ACCESS_KEY", "")
    if not app_id or not access_key:
        print(f"  [DUMMY] Rakuten: {keyword}")
        return _dummy_items(keyword)

    url = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260401"
    params = {
        "applicationId": app_id,
        "accessKey": access_key,
        "keyword": keyword,
        "hits": hits,
        "sort": "-reviewCount",
        "format": "json",
        "availability": 1,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        raw_items = data.get("Items", [])
        results = []
        for raw in raw_items:
            parsed = _parse_item(raw, keyword)
            if parsed["list_price"] > 0:
                results.append(parsed)
        print(f"  [API] Rakuten: {keyword} → {len(results)}件")
        return results
    except Exception as e:
        print(f"  [ERROR] Rakuten API失敗 ({keyword}): {e} → ダミーで代替")
        return _dummy_items(keyword)
