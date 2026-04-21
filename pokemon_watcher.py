#!/usr/bin/env python3
"""
ポケモンカードBOX 在庫・抽選監視 bot

【自動発見】 ポケモンセンターオンライン + 楽天公式ショップ群（ポケセン/ビックカメラ/ノジマ）
【個別URL監視】 watchlist.yaml に追加したURLを直接ポーリング（Amazon・量販店個別ページ対応）

10分ごとに実行。変化があれば Discord @everyone 通知。
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JST = timezone(timedelta(hours=9))
STATE_PATH = Path("data/pokemon_stock.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

# ── ステータス判定 ────────────────────────────────────────────────────
_IN_STOCK  = ["カートに入れる", "カートへ入れる", "購入する", "今すぐ購入", "在庫あり", "add to cart", "buy now", "数量"]
_SOLD_OUT  = ["完売", "在庫なし", "品切れ", "ただいま品切れ", "入荷待ち", "sold out", "在庫切れ", "取り扱いなし", "終了"]
_LOTTERY   = ["抽選受付中", "抽選申込", "抽選に応募", "抽選販売", "抽選受付"]
_PREORDER  = ["予約受付中", "予約する", "予約注文"]

# ── BOX判定 ──────────────────────────────────────────────────────────
_BOX_WORDS     = ["BOX", "ボックス", "box"]
_CARD_BRANDS   = ["ポケモン", "pokemon", "ポケカ", "ワンピース", "one piece", "onepiece", "ワンピカード"]
_EXCLUDE_WORDS = ["スリーブ", "デッキケース", "ファイル", "シール", "バラ", "1パック", "1枚", "グッズ"]

# ── 検索キーワード（複数ブランド対応）────────────────────────────────
SEARCH_KEYWORDS = ["ポケモンカード BOX", "ワンピースカード BOX"]

# ── 楽天公式ショップコード ────────────────────────────────────────────
RAKUTEN_OFFICIAL_SHOPS = {
    "pokemoncenter": "ポケモンセンター公式",
    "biccamera":     "ビックカメラ",
    "nojima-online": "ノジマオンライン",
    "kojima":        "コジマ",
    "joshin":        "ジョーシン",
    "edion":         "エディオン",
    "toysrus-japan": "トイザらス",
}


def _fetch(url: str, timeout: int = 20) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        print(f"  [ERROR] {url[:60]}: {e}")
        return None


def _status(text: str) -> str:
    t = text.lower()
    if any(w.lower() in t for w in _LOTTERY):   return "lottery"
    if any(w.lower() in t for w in _PREORDER):  return "preorder"
    if any(w.lower() in t for w in _IN_STOCK):  return "available"
    if any(w.lower() in t for w in _SOLD_OUT):  return "soldout"
    return "unknown"


def _is_box(name: str) -> bool:
    """トレカBOX商品か判定（ポケモン・ワンピース対応）"""
    n = name.lower()
    ok_card = any(w.lower() in n for w in _CARD_BRANDS)
    ok_box = (
        any(w.lower() in n for w in _BOX_WORDS)
        or ("拡張パック" in name and "カードゲーム" in name)
        or ("強化拡張パック" in name)
        or ("ブースターパック" in name and "カードゲーム" in name)
    )
    ng = any(w in name for w in _EXCLUDE_WORDS)
    return ok_card and ok_box and not ng


def _price(text: str) -> int | None:
    m = re.search(r"[\d,]+", text.replace("，", ","))
    if m:
        v = int(m.group().replace(",", ""))
        return v if 1000 < v < 200000 else None
    return None


def _amazon_seller_is_amazon(soup: BeautifulSoup) -> bool:
    """Amazon商品ページで販売者がAmazon.co.jpかどうか判定する。
    判定できない場合はTrueを返して通知を通す（見逃し防止）。"""
    # buyboxのマーチャント情報を優先チェック
    for sel in [
        "#merchant-info",
        "#tabular-buybox-container",
        "#desktop_buybox",
        "#buybox",
        "#newBuyBoxPrice",
    ]:
        el = soup.select_one(sel)
        if not el:
            continue
        text = el.get_text(" ", strip=True)
        # 明確にAmazon.co.jp以外の販売者名が出ていたら転売屋
        if re.search(r"販売[:：]\s*Amazon\.co\.jp", text, re.IGNORECASE):
            return True
        if re.search(r"販売[:：]", text) and "Amazon.co.jp" not in text:
            return False

    # ページ全体で「販売: Amazon.co.jp」を探す
    page_text = soup.get_text(" ", strip=True)
    if re.search(r"販売[:：]\s*Amazon\.co\.jp", page_text, re.IGNORECASE):
        return True
    # 販売者が明記されていてAmazonでない
    m = re.search(r"販売[:：]\s*(.{1,40}?)(?:\s|　|$)", page_text)
    if m and "Amazon.co.jp" not in m.group(1):
        return False

    return True  # 判定不能 → 通知を通す


# ── 状態ファイル ──────────────────────────────────────────────────────

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


# ── 個別商品ページ監視（Amazon・量販店ページ対応）────────────────────

def check_product_page(url: str) -> dict | None:
    soup = _fetch(url)
    if not soup:
        return None

    page_text = soup.get_text()

    # 商品名
    name = ""
    for sel in ["h1", ".product-name", "[itemprop='name']", ".bc-title", ".commodity_title"]:
        el = soup.select_one(sel)
        if el:
            name = el.get_text(strip=True)[:100]
            if name:
                break

    # 価格
    price = None
    for sel in [".price", "[itemprop='price']", "[class*='price']", ".item-price"]:
        el = soup.select_one(sel)
        if el:
            price = _price(el.get_text())
            if price:
                break

    # ドメインからショップ名
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    retailer = m.group(1) if m else url

    status = _status(page_text)

    # AmazonはAmazon.co.jp販売のみ通知（マーケットプレイス転売屋を除外）
    if "amazon.co.jp" in url.lower() and status == "available":
        if not _amazon_seller_is_amazon(soup):
            status = "soldout"
            print(f"  [Amazon] 転売屋出品のためスキップ: {name[:40]}")

    return {
        "name": name,
        "url": url,
        "retailer": retailer,
        "status": status,
        "price": price,
        "last_checked": datetime.now(JST).isoformat(),
    }


# ── ポケモンセンターオンライン（直スクレイプ）────────────────────────

def search_pokemoncenter() -> list[dict]:
    BASE = "https://www.pokemoncenter-online.com"
    results: list[dict] = []
    seen: set[str] = set()

    # トップページ + 新着ページをスキャン（カテゴリページはURLが不定期変更されるためトップのみ）
    scan_urls = [BASE + "/"]
    for scan_url in scan_urls:
        soup = _fetch(scan_url)
        if not soup:
            continue

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not re.search(r"/\d{13}\.html", href):
                continue
            full_url = urljoin(BASE, href)
            if full_url in seen:
                continue
            seen.add(full_url)

            container = a.find_parent(["li", "div", "article"])
            ctx = container.get_text(strip=True) if container else a.get_text(strip=True)
            if not _is_box(ctx):
                continue

            price = None
            if container:
                el = container.select_one(".price, [class*='price']")
                if el:
                    price = _price(el.get_text())

            status = _status(ctx)
            raw_name = a.get_text(strip=True)
            # 前後の数字/記号ノイズを除去
            clean_name = re.sub(r"^[\d\s]+|[\d\s]+$", "", raw_name).strip() or ctx[:80]
            results.append({
                "name": clean_name[:80],
                "url": full_url,
                "retailer": "ポケモンセンターオンライン",
                "status": status,
                "price": price,
                "last_checked": datetime.now(JST).isoformat(),
            })
        time.sleep(1)

    return results


# ── 楽天API: 複数公式ショップを横断検索 ───────────────────────────────

def search_rakuten_shops(app_id: str, access_key: str) -> list[dict]:
    """各楽天公式ショップでポケモン・ワンピースBOXを検索"""
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
                    print(f"  [{shop_name}] 楽天API {resp.status_code}")
                    continue
                data = resp.json()
            except Exception as e:
                print(f"  [{shop_name}] 楽天APIエラー: {e}")
                continue

            for it in data.get("Items", []):
                item = it if isinstance(it, dict) and "itemName" in it else it.get("Item", {})
                name = item.get("itemName", "")
                if not _is_box(name):
                    continue
                item_url = item.get("itemUrl", "")
                if item_url in seen:
                    continue
                seen.add(item_url)

                availability = item.get("availability", 0)
                results.append({
                    "name": name[:80],
                    "url": item_url,
                    "retailer": f"楽天 {shop_name}",
                    "status": "available" if availability == 1 else "soldout",
                    "price": item.get("itemPrice"),
                    "last_checked": datetime.now(JST).isoformat(),
                })
            time.sleep(1)

    return results


def _scrape_search(base_url_template: str, retailer: str,
                   link_filter_fn, base: str) -> list[dict]:
    """共通スクレイプ処理。SEARCH_KEYWORDSでループして重複排除して返す。"""
    results: list[dict] = []
    seen: set[str] = set()

    for keyword in SEARCH_KEYWORDS:
        url = base_url_template.format(kw=requests.utils.quote(keyword))
        soup = _fetch(url)
        if not soup:
            continue

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not link_filter_fn(href):
                continue
            full_url = urljoin(base, href)
            if full_url in seen:
                continue
            seen.add(full_url)

            container = a.find_parent(["li", "div", "article", "td"])
            ctx = container.get_text(strip=True) if container else a.get_text(strip=True)
            name = a.get_text(strip=True) or ctx[:80]
            if not _is_box(name) and not _is_box(ctx):
                continue

            price = None
            if container:
                el = container.select_one("[class*='price'], .priceTxt, .price")
                if el:
                    price = _price(el.get_text())

            results.append({
                "name": name[:80],
                "url": full_url,
                "retailer": retailer,
                "status": _status(ctx),
                "price": price,
                "last_checked": datetime.now(JST).isoformat(),
            })
        time.sleep(1)

    return results


def search_yodobashi() -> list[dict]:
    return _scrape_search(
        "https://www.yodobashi.com/category/10002000003000000000/?word={kw}&num=50",
        "ヨドバシドットコム",
        lambda h: "/product/" in h,
        "https://www.yodobashi.com",
    )


def search_sevenet() -> list[dict]:
    return _scrape_search(
        "https://7net.omni7.jp/result/keyword/{kw}",
        "セブンネットショッピング",
        lambda h: "/detail/" in h,
        "https://7net.omni7.jp",
    )


def search_yamada() -> list[dict]:
    return _scrape_search(
        "https://www.yamada-denkiweb.com/search/?keyword={kw}&category_id=&sort=&page=1",
        "ヤマダ電機",
        lambda h: bool(re.search(r"/\d+\.html", h)),
        "https://www.yamada-denkiweb.com",
    )


def search_ksdenki() -> list[dict]:
    return _scrape_search(
        "https://www.ksdenki.com/ec/shp/searchList.html?words={kw}",
        "ケーズデンキ",
        lambda h: "/shp/product/" in h or ("/ec/shp/" in h and h.count("/") > 4),
        "https://www.ksdenki.com",
    )


def search_amiami() -> list[dict]:
    return _scrape_search(
        "https://www.amiami.jp/top/search/?s_keywords={kw}&s_st_list_newitem_available=1",
        "あみあみ",
        lambda h: "/detail/?scode=" in h or "/top/detail/" in h,
        "https://www.amiami.jp",
    )


def search_geo() -> list[dict]:
    return _scrape_search(
        "https://ec.geo-online.co.jp/shop/goods/search.aspx?search={kw}&searchf=1",
        "ゲオ",
        lambda h: "/shop/goods/" in h and h != "/shop/goods/search.aspx",
        "https://ec.geo-online.co.jp",
    )


def search_rakuten_scrape() -> list[dict]:
    """楽天APIキー未設定時のフォールバック: ポケセン公式楽天ショップを直スクレイプ"""
    results: list[dict] = []
    seen: set[str] = set()

    # ポケモンセンター公式楽天ショップ内で検索
    url = "https://search.rakuten.co.jp/search/mall/ポケモンカード+BOX/?shopName=pokemoncenter"
    soup = _fetch(url)
    if not soup:
        return []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "item.rakuten.co.jp/pokemoncenter" not in href:
            continue
        if href in seen:
            continue
        seen.add(href)

        container = a.find_parent(["li", "div", "article", "td"])
        ctx = container.get_text(strip=True) if container else a.get_text(strip=True)
        name = a.get_text(strip=True) or ctx[:80]
        if not _is_box(name) and not _is_box(ctx):
            continue

        price = None
        if container:
            el = container.select_one(".price, [class*='price']")
            if el:
                price = _price(el.get_text())

        results.append({
            "name": name[:80],
            "url": href,
            "retailer": "楽天(ポケセン公式)",
            "status": _status(ctx),
            "price": price,
            "last_checked": datetime.now(JST).isoformat(),
        })

    return results


# ── イベント検出 ──────────────────────────────────────────────────────

def detect_events(items: list[dict], state: dict, is_initial: bool = False) -> list[dict]:
    """前回状態と比較して変化をイベントとして返す"""
    events: list[dict] = []
    for item in items:
        url = item["url"]
        prev = state["products"].get(url)

        if prev is None:
            if not is_initial:
                events.append({**item, "event_type": "new"})
                print(f"  🆕 新着: [{item['retailer']}] {item['name'][:40]}")
        else:
            prev_st = prev.get("status", "")
            cur_st  = item["status"]
            if prev_st != cur_st and cur_st in ("available", "lottery", "preorder"):
                etype = "lottery" if cur_st == "lottery" else "restock"
                events.append({**item, "event_type": etype})
                print(f"  🔄 {etype}: [{item['retailer']}] {prev_st}→{cur_st} {item['name'][:35]}")

        state["products"][url] = item
    return events


def check_watchlist(watchlist: dict, state: dict) -> list[dict]:
    """watchlist.yaml 個別URLを直接チェック（量販店・Amazon対応）"""
    events: list[dict] = []
    for product in watchlist.get("watch_products", []):
        pname = product.get("name", "")
        for url in product.get("urls", []):
            result = check_product_page(url)
            time.sleep(1.5)
            if not result:
                continue

            if not result["name"]:
                result["name"] = pname

            prev = state["products"].get(url, {})
            prev_st = prev.get("status", "")
            cur_st  = result["status"]

            if prev_st and prev_st != cur_st and cur_st in ("available", "lottery", "preorder"):
                etype = "lottery" if cur_st == "lottery" else "restock"
                events.append({**result, "event_type": etype})
                print(f"  🚨 変化: {prev_st}→{cur_st} | {result['name'][:40]}")

            state["products"][url] = result

    return events


# ── Discord通知 ──────────────────────────────────────────────────────

_RETAILER_EMOJI = {
    "ポケモンセンターオンライン": "🎮",
    "楽天 ポケモンセンター公式":  "🎮",
    "楽天 ビックカメラ":          "🟡",
    "楽天 ノジマオンライン":       "🔵",
    "楽天 ジョーシン":            "🟣",
    "楽天 エディオン":            "🔴",
    "楽天 トイザらス":            "🧸",
    "楽天(ポケセン公式)":         "🎮",
    "ヨドバシドットコム":          "🟠",
    "セブンネットショッピング":    "🟢",
    "ヤマダ電機":                  "⚡",
    "ケーズデンキ":                "🔌",
    "あみあみ":                    "🎌",
    "ゲオ":                        "🎮",
}
_STATUS_LABEL = {
    "available": "✅ 在庫あり",
    "lottery":   "🎰 抽選受付中",
    "preorder":  "📅 予約受付中",
    "soldout":   "❌ 完売",
    "unknown":   "❓ 不明",
}
_EVENT_HEADER = {
    "new":     "🆕 **新着！**",
    "restock": "🔄 **再入荷！**",
    "lottery": "🎰 **抽選開始！**",
}


def _cart_url(url: str) -> str | None:
    """Amazon商品URLからワンタップカートURLを生成する"""
    m = re.search(r"amazon\.co\.jp/(?:dp|gp/product)/([A-Z0-9]{10})", url)
    if m:
        asin = m.group(1)
        return f"https://www.amazon.co.jp/gp/aws/cart/add.html?ASIN.1={asin}&Quantity.1=1"
    return None


def send_discord(webhook_url: str, events: list[dict]) -> None:
    if not events:
        return

    lines = ["@everyone 🚨 **ポケカBOX アラート！今すぐ確認！**", "━━━━━━━━━━━━━━━━━━"]
    for ev in events[:5]:
        header  = _EVENT_HEADER.get(ev.get("event_type", ""), "📢 **変化あり**")
        emoji   = _RETAILER_EMOJI.get(ev["retailer"], "🏪")
        status  = _STATUS_LABEL.get(ev["status"], ev["status"])
        price_s = f"¥{ev['price']:,}" if ev.get("price") else "価格不明"
        cart    = _cart_url(ev["url"])
        lines += [
            header,
            f"{emoji} {ev['retailer']}  |  {status}  |  {price_s}",
            f"**{ev['name'][:60]}**",
            f"🔗 商品ページ: {ev['url']}",
        ]
        if cart:
            lines.append(f"🛒 **カートに入れる（ワンタップ）**: {cart}")
        lines.append("─────────────")
    if len(events) > 5:
        lines.append(f"... 他 {len(events) - 5} 件")

    msg = "\n".join(lines)[:1990]
    try:
        resp = requests.post(webhook_url, json={"content": msg}, timeout=10)
        resp.raise_for_status()
        print(f"  Discord送信: {len(events)}件")
    except Exception as e:
        print(f"  Discord失敗: {e}")


# ── メイン ────────────────────────────────────────────────────────────

def main() -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    app_id      = os.environ.get("RAKUTEN_APP_ID", "")
    access_key  = os.environ.get("RAKUTEN_ACCESS_KEY", "")

    if not webhook_url:
        print("[INFO] DISCORD_WEBHOOK_URL 未設定（テストモード）")

    try:
        with open("watchlist.yaml", encoding="utf-8") as f:
            watchlist = yaml.safe_load(f) or {}
    except FileNotFoundError:
        watchlist = {}

    state = load_state()
    is_initial = len(state["products"]) == 0
    all_events: list[dict] = []

    # ── 1. watchlist個別URL監視（量販店・Amazon等）───────────────────
    print("\n▶ ウォッチリスト個別URL監視")
    all_events += check_watchlist(watchlist, state)

    # ── 2. ポケモンセンター自動スキャン ─────────────────────────────
    print("\n▶ ポケモンセンターオンライン")
    pc_items = search_pokemoncenter()
    print(f"  {len(pc_items)}件取得")
    all_events += detect_events(pc_items, state, is_initial)
    time.sleep(2)

    # ── 3. 楽天公式ショップ群 ────────────────────────────────────────
    print("\n▶ 楽天公式ショップ (ポケセン・ビックカメラ・ノジマ・ジョーシン・エディオン・トイザらス)")
    if app_id and access_key:
        rakuten_items = search_rakuten_shops(app_id, access_key)
        print(f"  {len(rakuten_items)}件取得")
        all_events += detect_events(rakuten_items, state, is_initial)
    else:
        print("  [楽天APIキー未設定] スキップ（GitHub Secretsに設定済みなら本番で動作）")

    # ── 4. ヨドバシドットコム ────────────────────────────────────────
    print("\n▶ ヨドバシドットコム")
    yodo_items = search_yodobashi()
    print(f"  {len(yodo_items)}件取得")
    all_events += detect_events(yodo_items, state, is_initial)
    time.sleep(2)

    # ── 5. セブンネットショッピング ─────────────────────────────────
    print("\n▶ セブンネットショッピング")
    seven_items = search_sevenet()
    print(f"  {len(seven_items)}件取得")
    all_events += detect_events(seven_items, state, is_initial)
    time.sleep(2)

    # ── 6. ヤマダ電機 ────────────────────────────────────────────────
    print("\n▶ ヤマダ電機")
    yamada_items = search_yamada()
    print(f"  {len(yamada_items)}件取得")
    all_events += detect_events(yamada_items, state, is_initial)
    time.sleep(2)

    # ── 7. ケーズデンキ ──────────────────────────────────────────────
    print("\n▶ ケーズデンキ")
    ks_items = search_ksdenki()
    print(f"  {len(ks_items)}件取得")
    all_events += detect_events(ks_items, state, is_initial)
    time.sleep(2)

    # ── 8. あみあみ ──────────────────────────────────────────────────
    print("\n▶ あみあみ")
    ami_items = search_amiami()
    print(f"  {len(ami_items)}件取得")
    all_events += detect_events(ami_items, state, is_initial)
    time.sleep(2)

    # ── 9. ゲオ ──────────────────────────────────────────────────────
    print("\n▶ ゲオ")
    geo_items = search_geo()
    print(f"  {len(geo_items)}件取得")
    all_events += detect_events(geo_items, state, is_initial)
    time.sleep(2)

    # ── 保存・通知 ───────────────────────────────────────────────────
    state["last_updated"] = datetime.now(JST).isoformat()
    save_state(state)

    if is_initial:
        print(f"\n初回実行: {len(state['products'])}件をベースライン登録（次回から変化を通知）")
    elif all_events:
        if webhook_url:
            send_discord(webhook_url, all_events)
        else:
            for ev in all_events:
                print(f"  [通知スキップ] {ev.get('event_type')} | {ev['name'][:40]}")
    else:
        print("\n変化なし")

    print(f"\n監視中: {len(state['products'])}件")


if __name__ == "__main__":
    main()
