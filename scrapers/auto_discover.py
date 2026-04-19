#!/usr/bin/env python3
"""
公式サイト自動発掘スクレイパー
一番くじ・プレミアムバンダイ(ニュース経由)・ポケモンセンターの新着を自動取得
"""
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _fetch(url: str, timeout: int = 15) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        print(f"  [ERROR] {url}: {e}")
        return None


def _price_int(text: str) -> int | None:
    m = re.search(r"[\d,]+", text.replace("，", ","))
    if m:
        v = int(m.group().replace(",", ""))
        return v if 100 < v < 500000 else None
    return None


def _parse_kuji_date(text: str) -> str:
    """'2026年5月24日' → '2026-05-24 07:00'"""
    m = re.search(r"(\d{4})年(\d{1,2})月(?:(\d{1,2})日)?", text)
    if m:
        y = m.group(1)
        mo = m.group(2).zfill(2)
        d = (m.group(3) or "01").zfill(2)
        return f"{y}-{mo}-{d} 07:00"
    return ""


# ── 一番くじ ──────────────────────────────────────────────────────

def scrape_ichiban_kuji(months_ahead: int = 2) -> list[dict]:
    """1kuji.com の発売予定一覧から商品を取得する"""
    now = datetime.now(JST)
    results: list[dict] = []
    seen_urls: set[str] = set()

    for delta in range(months_ahead + 1):
        total_month = now.month + delta
        year = now.year + (total_month - 1) // 12
        month = (total_month - 1) % 12 + 1
        url = f"https://1kuji.com/products?sale_month={month}&sale_year={year}"
        soup = _fetch(url)
        if not soup:
            time.sleep(1)
            continue

        for li in soup.select("ul.itemList > li"):
            a = li.find("a", href=True)
            if not a:
                continue
            full_url = urljoin("https://1kuji.com", a["href"])
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            name_el = a.select_one("p.itemName")
            date_el = a.select_one("p.date")
            name = name_el.get_text(strip=True) if name_el else ""
            date_text = date_el.get_text(strip=True) if date_el else ""
            if not name:
                continue

            sale_start = _parse_kuji_date(date_text)

            # 個別ページから価格を取得
            list_price = 750
            detail = _fetch(full_url)
            time.sleep(0.5)
            if detail:
                for sel in [".price", "[class*='price']", "strong"]:
                    el = detail.select_one(sel)
                    if el:
                        p = _price_int(el.get_text())
                        if p:
                            list_price = p
                            break

            results.append({
                "url": full_url,
                "name": name,
                "list_price": list_price,
                "category_id": "ichiban_kuji",
                "sale_start": sale_start,
                "deadline": sale_start[:10] if sale_start else "",
                "note": f"[自動取得] {date_text}",
                "source": "auto_ichiban_kuji",
            })
            print(f"  [くじ] {name[:55]}")

        time.sleep(1)

    print(f"  一番くじ計: {len(results)} 件")
    return results


# ── プレミアムバンダイ (電撃ホビーニュース経由) ──────────────────

def scrape_pbandai_via_news() -> list[dict]:
    """電撃ホビーのプレバン記事ページを巡回してP-Bandai商品情報を取得する"""
    results: list[dict] = []
    seen_urls: set[str] = set()

    # 記事一覧ページを取得
    index_soup = _fetch("https://hobby.dengeki.com/tag/p-bandai/")
    if not index_soup:
        print("  プレバン計: 0 件")
        return results

    # 各記事へのリンクを収集
    article_links: list[str] = []
    for a in index_soup.select("h2 a, h3 a, .entry-title a, .entry-card-title a"):
        href = a.get("href", "")
        if href and "dengeki.com" in href and href not in article_links:
            article_links.append(href)
        if len(article_links) >= 15:  # 最新15記事まで
            break

    for article_url in article_links:
        soup = _fetch(article_url)
        time.sleep(0.8)
        if not soup:
            continue

        # 記事タイトル
        title_el = soup.select_one("h1, .entry-title")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            continue

        # P-Bandai商品URLを本文から抽出
        pbandai_url = ""
        for a in soup.find_all("a", href=True):
            if "p-bandai.jp" in a["href"] and "/item/" in a["href"]:
                pbandai_url = a["href"]
                break
        if not pbandai_url or pbandai_url in seen_urls:
            continue

        # 価格を本文テキストから抽出
        body_text = soup.get_text()
        price = None
        for m in re.finditer(r"(?:税込|定価|価格)[^\d]*([0-9,]+)\s*円", body_text):
            p = _price_int(m.group(1))
            if p:
                price = p
                break
        if not price:
            continue

        seen_urls.add(pbandai_url)
        results.append({
            "url": pbandai_url,
            "name": title,
            "list_price": price,
            "category_id": "figure",
            "sale_start": "",
            "deadline": "",
            "note": "[自動取得] 電撃ホビー経由",
            "source": "auto_pbandai_news",
        })
        print(f"  [プレバン] {title[:55]}")

    print(f"  プレバン計: {len(results)} 件")
    return results


# ── ポケモンセンターオンライン ────────────────────────────────────

def scrape_pokemon_center() -> list[dict]:
    """ポケモンセンタートップから商品URLを収集して新着・抽選情報を取得する"""
    results: list[dict] = []
    seen_urls: set[str] = set()
    BASE = "https://www.pokemoncenter-online.com"

    soup = _fetch(BASE + "/")
    if not soup:
        print("  ポケモンセンター計: 0 件")
        return results

    # トップページの商品URL(/990000XXXXXXXXX.html)を収集
    product_urls: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"/\d{13}\.html", href):
            full = urljoin(BASE, href)
            if full not in seen_urls:
                seen_urls.add(full)
                product_urls.append(full)

    for prod_url in product_urls[:20]:
        prod_soup = _fetch(prod_url)
        time.sleep(0.8)
        if not prod_soup:
            continue

        name_el = prod_soup.select_one("h1, .product-name, [itemprop='name']")
        name = name_el.get_text(strip=True) if name_el else ""
        if not name:
            continue

        price_el = prod_soup.select_one(".price, [itemprop='price'], [class*='price']")
        price = _price_int(price_el.get_text()) if price_el else None
        if not price:
            continue

        results.append({
            "url": prod_url,
            "name": name,
            "list_price": price,
            "category_id": "trading_card",
            "sale_start": "",
            "deadline": "",
            "note": "[自動取得] ポケモンセンター",
            "source": "auto_pokemon_center",
        })
        print(f"  [ポケセン] {name[:55]}")

    print(f"  ポケモンセンター計: {len(results)} 件")
    return results


# ── メイン ────────────────────────────────────────────────────────

def discover_all() -> list[dict]:
    """全サイトから新着アイテムを発掘して返す"""
    print("\n▶ 自動発掘: 一番くじ")
    items = scrape_ichiban_kuji(months_ahead=2)

    print("\n▶ 自動発掘: プレミアムバンダイ (ニュース経由)")
    items += scrape_pbandai_via_news()

    print("\n▶ 自動発掘: ポケモンセンター")
    items += scrape_pokemon_center()

    return items


def save_auto_items(items: list[dict], path: str = "auto_items.yaml") -> None:
    """発掘アイテムをYAMLに保存。items.yamlの手動登録と重複するURLは除外する。"""
    manual_urls: set[str] = set()
    try:
        with open("items.yaml", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for entry in (data.get("items", []) if data else []):
            if entry.get("url"):
                manual_urls.add(entry["url"])
    except FileNotFoundError:
        pass

    seen_urls: set[str] = set(manual_urls)
    unique: list[dict] = []
    for item in items:
        url = item.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(item)

    output = {
        "generated_at": datetime.now(JST).isoformat(),
        "items": unique,
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(output, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"💾 {path} に {len(unique)} 件保存しました")


if __name__ == "__main__":
    found = discover_all()
    save_auto_items(found)
