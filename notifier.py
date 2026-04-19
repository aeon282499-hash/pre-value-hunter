#!/usr/bin/env python3
"""
販売開始アラート通知
items.yaml の sale_start が1時間以内の商品をDiscordに通知する
"""
import os
import sys
import yaml
import requests
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))


def load_items(path: str = "items.yaml") -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("items", []) if data else []


def send_discord(webhook_url: str, message: str) -> None:
    try:
        resp = requests.post(webhook_url, json={"content": message}, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"Discord通知失敗: {e}")


def check_and_notify(webhook_url: str) -> None:
    now = datetime.now(JST)
    items = load_items()
    alerts = []

    for item in items:
        sale_start = item.get("sale_start", "")
        if not sale_start:
            continue
        try:
            dt = datetime.fromisoformat(str(sale_start)).replace(tzinfo=JST)
        except Exception:
            continue

        diff = (dt - now).total_seconds()
        if 0 < diff <= 3600:
            mins = int(diff // 60)
            alerts.append((item, dt, mins))

    if not alerts:
        print("通知対象なし")
        return

    for item, dt, mins in alerts:
        name = item.get("name") or item.get("url", "")
        url = item.get("url", "")
        price = item.get("list_price", "")
        note = item.get("note", "")
        time_str = dt.strftime("%m/%d %H:%M")

        msg = (
            f"🚨 **{mins}分後に販売開始！**\n"
            f"**{name}**\n"
            f"定価: ¥{price:,}" if isinstance(price, int) else f"定価: ¥{price}"
        )
        msg = (
            f"🚨 **{mins}分後に販売開始！今すぐ準備を！**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"**{name}**\n"
            f"💴 定価: ¥{price:,}\n" if isinstance(price, int) else
            f"🚨 **{mins}分後に販売開始！今すぐ準備を！**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"**{name}**\n"
            f"💴 定価: ¥{price}\n"
        )
        msg = "\n".join([
            f"@everyone 🚨 **{mins}分後に販売開始！今すぐ準備を！**",
            "━━━━━━━━━━━━━━━━━━",
            f"**{name}**",
            f"💴 定価: ¥{price:,}" if isinstance(price, int) else f"💴 定価: ¥{price}",
            f"🕐 販売開始: {time_str} JST",
            f"🔗 {url}",
        ])
        if note:
            msg += f"\n📝 {note}"

        print(msg)
        send_discord(webhook_url, msg)


def main():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL 未設定")
        sys.exit(0)
    check_and_notify(webhook_url)


if __name__ == "__main__":
    main()
