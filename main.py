#!/usr/bin/env python3
"""
プレ値ハンター - 毎日自動リサーチパイプライン
usage: python main.py
       RAKUTEN_APP_ID が未設定でもダミーデータで動作します。
"""
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import requests
import yaml

from analyzer.profit import calculate_profit, calculate_amazon_profit, best_channel, calculate_expected_value
from analyzer.win_rate import estimate_win_rate
from dashboard.render import render_dashboard
from scrapers.mercari import get_mercari_price
from scrapers.official import get_official_lotteries
from scrapers.rakuten import search_rakuten


def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def process_item(item: dict, cat: dict, config: dict) -> dict | None:
    name = item.get("name", "")
    list_price = item.get("list_price", 0)
    if list_price <= 0:
        return None

    # 中古品・業者向け大量セット除外
    ng_words = ["中古", "used", "ジャンク", "まとめ売り", "大量", "bulk"]
    if any(w in name.lower() for w in ng_words):
        return None

    # 高額品除外（小型転売向けでない）
    max_price = config["thresholds"].get("max_list_price", 50000)
    if list_price > max_price:
        return None

    # メルカリ相場（ダミー or 実装済み）
    mercari_price = item.get("mercari_estimate") or get_mercari_price(
        item["name"],
        list_price,
        multiplier_min=cat.get("premium_multiplier_min", 1.5),
        multiplier_max=cat.get("premium_multiplier_max", 3.0),
    )
    if mercari_price is None:
        return None

    mercari_profit, mercari_rate = calculate_profit(
        sell_price=mercari_price,
        list_price=list_price,
        fee_rate=config["fees"]["mercari_rate"],
        shipping=config["fees"]["shipping"],
    )

    amz_cfg = config["fees"]["amazon"]
    referral_rate = amz_cfg["referral_rates"].get(cat["id"], amz_cfg["referral_rates"]["default"])
    amazon_profit, amazon_rate = calculate_amazon_profit(
        sell_price=mercari_price,
        list_price=list_price,
        referral_rate=referral_rate,
        fba_fee=amz_cfg["fba_fee_small"],
    )

    channel = best_channel(mercari_profit, amazon_profit)
    profit = amazon_profit if channel == "amazon" else mercari_profit
    profit_rate = amazon_rate if channel == "amazon" else mercari_rate

    win_rate = estimate_win_rate(category=cat, item=item)
    expected_value = calculate_expected_value(profit, win_rate)

    thr = config["thresholds"]
    if profit < thr["min_profit"] or profit_rate < thr["min_profit_rate"]:
        return None

    return {
        "name": item["name"],
        "category": cat["name"],
        "category_id": cat["id"],
        "list_price": int(list_price),
        "mercari_price": int(mercari_price),
        "profit": round(profit),
        "profit_rate": round(profit_rate * 100, 1),
        "mercari_profit": round(mercari_profit),
        "amazon_profit": round(amazon_profit),
        "best_channel": channel,
        "win_rate": round(win_rate * 100, 1),
        "expected_value": round(expected_value),
        "url": item.get("url", item.get("source_url", "")),
        "image": item.get("image", ""),
        "shop": item.get("shop", ""),
        "source": item.get("source", "unknown"),
    }


def run_pipeline(config: dict) -> list[dict]:
    app_id = os.environ.get("RAKUTEN_APP_ID", "")
    access_key = os.environ.get("RAKUTEN_ACCESS_KEY", "")
    if not app_id or not access_key:
        print("[INFO] RAKUTEN_APP_ID/RAKUTEN_ACCESS_KEY 未設定 → ダミーデータで実行します")

    all_results: list[dict] = []

    # ── 1. Rakuten 検索 ────────────────────────────────────────────
    for cat in config["categories"]:
        print(f"\n▶ カテゴリ: {cat['name']}")
        seen_names: set[str] = set()

        for keyword in cat["keywords"]:
            items = search_rakuten(keyword, app_id, config["rakuten"]["hits_per_keyword"])
            for item in items:
                if item["name"] in seen_names:
                    continue
                seen_names.add(item["name"])

                result = process_item(item, cat, config)
                if result:
                    all_results.append(result)
            time.sleep(1)

        print(f"  → 条件クリア: {len([r for r in all_results if r['category_id'] == cat['id']])} 件")

    # ── 2. 公式抽選情報 ───────────────────────────────────────────
    print("\n▶ 公式抽選情報")
    # 公式アイテムはカテゴリIDから設定を引く
    cat_map = {c["id"]: c for c in config["categories"]}
    for lot in get_official_lotteries():
        cat = cat_map.get(lot.get("category_id", ""), config["categories"][0])
        result = process_item(lot, cat, config)
        if result:
            all_results.append(result)

    # ── 3. 重複排除 & ソート ──────────────────────────────────────
    unique: dict[str, dict] = {}
    for r in all_results:
        key = r["name"]
        if key not in unique or r["expected_value"] > unique[key]["expected_value"]:
            unique[key] = r

    sorted_results = sorted(unique.values(), key=lambda x: x["expected_value"], reverse=True)
    return sorted_results


def send_discord(webhook_url: str, top_items: list[dict]) -> None:
    lines = ["**📦 プレ値ハンター - 本日のトップ商品**\n"]
    for i, item in enumerate(top_items, 1):
        lines.append(
            f"**{i}. {item['name']}**\n"
            f"　期待値 ¥{item['expected_value']:,} ／ 利益 ¥{item['profit']:,} ／ 当選確率 {item['win_rate']}%\n"
            f"　{item['url']}\n"
        )
    payload = {"content": "\n".join(lines)[:2000]}
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        print("Discord通知を送信しました")
    except Exception as e:
        print(f"Discord通知失敗: {e}")


def main() -> None:
    config = load_config()
    items = run_pipeline(config)

    print(f"\n✅ 合計 {len(items)} 件が条件を満たしました")

    # JSON 保存
    Path("data").mkdir(exist_ok=True)
    output = {
        "generated_at": datetime.now().isoformat(),
        "total_items": len(items),
        "total_expected_value": sum(i["expected_value"] for i in items),
        "items": items,
    }
    with open("data/latest.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("💾 data/latest.json を保存しました")

    # ダッシュボード生成
    render_dashboard(output, config)
    print("🎨 docs/index.html を生成しました")

    # Discord 通知
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if webhook_url:
        top_n = config.get("discord", {}).get("top_n", 3)
        send_discord(webhook_url, items[:top_n])

    # サマリー表示
    print("\n━━ TOP 5 ━━")
    for item in items[:5]:
        print(
            f"  [{item['category']}] {item['name'][:40]}\n"
            f"    期待値¥{item['expected_value']:,} / 利益¥{item['profit']:,} / 当選{item['win_rate']}%"
        )


if __name__ == "__main__":
    main()
