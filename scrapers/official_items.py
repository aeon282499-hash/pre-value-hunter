import re
import time
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _fetch(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        print(f"  [ERROR] 取得失敗 {url}: {e}")
        return None


def _price_int(text: str) -> int | None:
    m = re.search(r"[\d,]+", text.replace("，", ","))
    if m:
        return int(m.group().replace(",", ""))
    return None


def _parse_pbandai(soup: BeautifulSoup) -> dict:
    name = ""
    price = None
    h = soup.find("h1")
    if h:
        name = h.get_text(strip=True)
    for sel in [".price", ".item-price", "[class*='price']", "strong"]:
        el = soup.select_one(sel)
        if el:
            p = _price_int(el.get_text())
            if p and 100 < p < 500000:
                price = p
                break
    return {"name": name, "list_price": price}


def _parse_pokemoncenter(soup: BeautifulSoup) -> dict:
    name = ""
    price = None
    h = soup.find("h1")
    if h:
        name = h.get_text(strip=True)
    for sel in [".price", ".product-price", "[class*='price']"]:
        el = soup.select_one(sel)
        if el:
            p = _price_int(el.get_text())
            if p and 100 < p < 500000:
                price = p
                break
    return {"name": name, "list_price": price}


def _parse_generic(soup: BeautifulSoup) -> dict:
    name = ""
    price = None
    for tag in ["h1", "h2"]:
        h = soup.find(tag)
        if h:
            name = h.get_text(strip=True)
            break
    for sel in [".price", "[class*='price']", "[itemprop='price']", "strong"]:
        for el in soup.select(sel):
            p = _price_int(el.get_text())
            if p and 100 < p < 500000:
                price = p
                break
        if price:
            break
    return {"name": name, "list_price": price}


_PARSERS = {
    "p-bandai.jp": _parse_pbandai,
    "pokemoncenter-online.com": _parse_pokemoncenter,
    "ichiban-kuji.com": _parse_generic,
    "konamistyle.jp": _parse_generic,
    "takaratomy-mall.jp": _parse_generic,
}


def fetch_official_item(entry: dict) -> dict | None:
    url = entry.get("url", "").strip()
    if not url:
        return None

    domain = ""
    for d in _PARSERS:
        if d in url:
            domain = d
            break

    soup = _fetch(url)
    time.sleep(1)
    if not soup:
        return None

    parser = _PARSERS.get(domain, _parse_generic)
    fetched = parser(soup)

    name = entry.get("name") or fetched.get("name") or ""
    list_price = entry.get("list_price") or fetched.get("list_price")

    if not name or not list_price:
        print(f"  [WARN] 名前/価格が取得できませんでした: {url}")
        if not name:
            name = url
        if not list_price:
            return None

    return {
        "name": name,
        "list_price": int(list_price),
        "url": url,
        "image": "",
        "shop": domain or "公式サイト",
        "review_count": 0,
        "is_limited_first_come": False,
        "entry_windows": 1,
        "source": "official_manual",
        "deadline": entry.get("deadline", ""),
        "note": entry.get("note", ""),
        "category_id": entry.get("category_id", "figure"),
    }


def load_auto_items(path: str = "auto_items.yaml") -> list[dict]:
    """auto_discover.py が生成した auto_items.yaml を読み込む"""
    import yaml
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        entries = data.get("items", []) if data else []
        results = []
        for entry in entries:
            if not entry.get("url"):
                continue
            item = {
                "name": entry.get("name", entry["url"]),
                "list_price": int(entry.get("list_price", 0)),
                "url": entry["url"],
                "image": "",
                "shop": "公式サイト",
                "review_count": 0,
                "is_limited_first_come": True,
                "entry_windows": 1,
                "source": entry.get("source", "auto_discover"),
                "category_id": entry.get("category_id", "figure"),
                "sale_start": entry.get("sale_start", ""),
                "deadline": entry.get("deadline", ""),
                "note": entry.get("note", ""),
            }
            if item["list_price"] > 0 and item["name"]:
                results.append(item)
        return results
    except FileNotFoundError:
        return []


def load_manual_items(path: str = "items.yaml") -> list[dict]:
    import yaml
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        entries = data.get("items", []) if data else []
        results = []
        for entry in entries:
            if not entry.get("url"):
                continue
            print(f"  [公式] {entry['url'][:60]}")
            item = fetch_official_item(entry)
            if item:
                results.append(item)
        return results
    except FileNotFoundError:
        return []
