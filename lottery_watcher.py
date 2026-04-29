#!/usr/bin/env python3
"""
ポケモンカード 抽選販売リサーチ（1日1回）

各小売店の検索結果から「抽選受付中 / 抽選販売 / 抽選申込」状態の商品だけを抽出し、
前回からの差分（新規受付）をDiscordに通知する。
"""
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JST = timezone(timedelta(hours=9))
STATE_PATH = Path("data/lottery_state.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

LOTTERY_WORDS = ["抽選受付中", "抽選申込", "抽選に応募", "抽選販売", "抽選受付", "応募受付中"]
CARD_BRANDS = ["ポケモン", "pokemon", "ポケカ"]
EXCLUDE_WORDS = ["スリーブ", "デッキケース", "ファイル", "シール", "1パック", "1枚", "グッズ", "プレイマット"]

SEARCH_KEYWORDS = ["ポケモンカード 抽選", "ポケモン 抽選販売", "ポケカ 抽選"]

RAKUTEN_OFFICIAL_SHOPS = {
    "pokemoncenter": "ポケモンセンター公式",
    "biccamera":     "ビックカメラ",
    "nojima-online": "ノジマオンライン",
    "kojima":        "コジマ",
    "joshin":        "ジョーシン",
    "edion":         "エディオン",
    "toysrus-japan": "トイザらス",
}


def fetch(url: str, timeout: int = 20) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        print(f"  [ERROR] {url[:70]}: {e}")
        return None


def is_lottery(text: str) -> bool:
    t = text.lower()
    return any(w.lower() in t for w in LOTTERY_WORDS)


def is_pokemon_card(text: str) -> bool:
    n = text.lower()
    if not any(w.lower() in n for w in CARD_BRANDS):
        return False
    if any(w in text for w in EXCLUDE_WORDS):
        return False
    return True


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"products": {}}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def search_pokemoncenter() -> list[dict]:
    """ポケモンセンターオンラインの抽選ページ"""
    BASE = "https://www.pokemoncenter-online.com"
    results: list[dict] = []
    seen: set[str] = set()

    soup = fetch(BASE + "/")
    if not soup:
        return []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        full_url = urljoin(BASE, href)
        if full_url in seen:
            continue

        container = a.find_parent(["li", "div", "article"])
        ctx = container.get_text(" ", strip=True) if container else a.get_text(strip=True)

        if not is_lottery(ctx):
            continue
        if not is_pokemon_card(ctx):
            continue

        seen.add(full_url)
        name = a.get_text(strip=True) or ctx[:80]
        results.append({
            "name": name[:80],
            "url": full_url,
            "retailer": "ポケモンセンターオンライン",
            "last_checked": datetime.now(JST).isoformat(),
        })

    return results


def search_rakuten_shops(app_id: str, access_key: str) -> list[dict]:
    """楽天API経由で公式ショップの抽選販売商品を検索"""
    results: list[dict] = []
    seen: set[str] = set()

    for shop_code, shop_name in RAKUTEN_OFFICIAL_SHOPS.items():
        for keyword in SEARCH_KEYWORDS:
            api_url = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260401"
            params = {
                "applicationId": app_id,
                "accessKey":     access_key,
                "keyword":       keyword,
                "shopCode":      shop_code,
                "hits":          20,
                "sort":          "-updateTimestamp",
                "formatVersion": 2,
            }
            try:
                resp = requests.get(api_url, params=params, timeout=15)
                if resp.status_code != 200:
                    continue
                data = resp.json()
            except Exception as e:
                print(f"  [{shop_name}] {e}")
                continue

            for it in data.get("Items", []):
                item = it if isinstance(it, dict) and "itemName" in it else it.get("Item", {})
                name = item.get("itemName", "")
                caption = item.get("itemCaption", "")
                blob = name + " " + caption
                if not is_lottery(blob) or not is_pokemon_card(blob):
                    continue
                item_url = item.get("itemUrl", "")
                if item_url in seen:
                    continue
                seen.add(item_url)
                results.append({
                    "name": name[:80],
                    "url": item_url,
                    "retailer": f"楽天 {shop_name}",
                    "last_checked": datetime.now(JST).isoformat(),
                })
            time.sleep(1)

    return results


_RETAILER_EMOJI = {
    "ポケモンセンターオンライン": "🎮",
    "楽天 ポケモンセンター公式":  "🎮",
    "楽天 ビックカメラ":          "🟡",
    "楽天 ノジマオンライン":      "🔵",
    "楽天 ジョーシン":            "🟣",
    "楽天 エディオン":            "🔴",
    "楽天 トイザらス":            "🧸",
    "楽天 コジマ":                "🟠",
}


def send_discord(webhook_url: str, new_items: list[dict]) -> None:
    if not new_items:
        return

    lines = [
        f"@everyone 🎰 **ポケカ抽選販売 新規{len(new_items)}件**",
        "━━━━━━━━━━━━━━━━━━",
    ]
    for item in new_items[:10]:
        emoji = _RETAILER_EMOJI.get(item["retailer"], "🏪")
        lines += [
            f"{emoji} **{item['retailer']}**",
            f"**{item['name'][:60]}**",
            f"🔗 {item['url']}",
            "─────────────",
        ]
    if len(new_items) > 10:
        lines.append(f"... 他 {len(new_items) - 10} 件")

    msg = "\n".join(lines)[:1990]
    try:
        resp = requests.post(webhook_url, json={"content": msg}, timeout=10)
        resp.raise_for_status()
        print(f"  Discord送信: {len(new_items)}件")
    except Exception as e:
        print(f"  Discord失敗: {e}")


def main() -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    app_id      = os.environ.get("RAKUTEN_APP_ID", "")
    access_key  = os.environ.get("RAKUTEN_ACCESS_KEY", "")

    if not webhook_url:
        print("[INFO] DISCORD_WEBHOOK_URL 未設定（テストモード）")

    state = load_state()
    is_initial = len(state["products"]) == 0
    all_items: list[dict] = []

    print("\n▶ ポケモンセンターオンライン")
    pc = search_pokemoncenter()
    print(f"  {len(pc)}件抽選")
    all_items += pc
    time.sleep(2)

    print("\n▶ 楽天公式ショップ")
    if app_id and access_key:
        rk = search_rakuten_shops(app_id, access_key)
        print(f"  {len(rk)}件抽選")
        all_items += rk
    else:
        print("  [楽天APIキー未設定] スキップ")

    new_items: list[dict] = []
    for item in all_items:
        url = item["url"]
        if url not in state["products"]:
            new_items.append(item)
        state["products"][url] = item

    state["last_updated"] = datetime.now(JST).isoformat()
    save_state(state)

    if is_initial:
        print(f"\n初回実行: {len(state['products'])}件をベースライン登録")
    elif new_items:
        print(f"\n新規抽選: {len(new_items)}件")
        if webhook_url:
            send_discord(webhook_url, new_items)
    else:
        print("\n新規抽選なし")

    print(f"\n監視中: {len(state['products'])}件")


if __name__ == "__main__":
    main()
