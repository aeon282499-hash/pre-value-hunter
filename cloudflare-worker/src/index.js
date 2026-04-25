/**
 * amazon-pokemon-watcher — Cloudflare Worker
 * ============================================
 * Amazon定価販売のポケカ/ワンピースカードBOXを毎分監視。
 * 在庫が「Amazon.co.jp販売」で復活した瞬間にDiscord通知。
 *
 * 構成:
 *   - 毎分 cron で起動（GitHub Actionsの5分よりはるかに速い）
 *   - 15ASINを並列fetch（~3秒で全件チェック完了）
 *   - 状態をCloudflare KVに保存して差分検知
 *
 * 環境変数（wrangler secret）:
 *   DISCORD_WEBHOOK_URL
 *
 * KV Namespace:
 *   STOCK_STATE（前回チェック結果保存用）
 */

const ASINS = [
  // MEGAシリーズ（最重要・新弾）
  { asin: "B0DKHHYTGJ", name: "拡張パック ロケット団の栄光 BOX" },
  { asin: "B0F18J2CJF", name: "MEGA メガブレイブ BOX" },
  { asin: "B0F189YH8W", name: "MEGA メガシンフォニア BOX" },
  { asin: "B0F18B4CVX", name: "MEGA プレミアムトレーナーBOX" },
  { asin: "B0FLCWJ1VK", name: "MEGA ハイクラスパック MEGAドリームex BOX" },
  { asin: "B0FSJXSPPX", name: "MEGA ムニキスゼロ BOX" },
  { asin: "B0G1XB2STM", name: "MEGA ニンジャスピナー BOX" },
  { asin: "B0F9KJGGZ5", name: "MEGA インフェルノX BOX" },
  // 旧弾プレ値
  { asin: "B0BT15FD3J", name: "ポケモンカード151 BOX【再販監視】" },
  // ワンピースカード
  { asin: "B0CW1GY7WK", name: "ワンピース 双璧の覇者 BOX (OP-06)" },
  { asin: "B0D3J2GRKB", name: "ワンピース 500年後の未来 BOX (OP-07)" },
  { asin: "B0DHXNQV8L", name: "ワンピース 二つの伝説 BOX (OP-08)" },
  { asin: "B0DQZMYZLJ", name: "ワンピース 新世界の皇帝たち BOX (OP-09)" },
  // SVシリーズ
  { asin: "B0D5Y3DNHQ", name: "ナイトワンダラー BOX" },
  { asin: "B0DTYYKH3N", name: "デッキビルドBOX バトルパートナーズ" },
];

const USER_AGENTS = [
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
];

function pickUA() {
  return USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)];
}

/**
 * Amazon商品ページの状態を判定
 * @returns {Promise<{status: string, detail?: string}>}
 *   status: "available_amazon" | "marketplace_only" | "out_of_stock" | "fetch_error" | "exception"
 */
async function checkAmazon(asin) {
  const url = `https://www.amazon.co.jp/dp/${asin}`;
  try {
    const res = await fetch(url, {
      headers: {
        "User-Agent": pickUA(),
        "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
      },
      cf: { cacheTtl: 0, cacheEverything: false },
    });
    if (!res.ok) {
      return { status: "fetch_error", detail: `HTTP ${res.status}` };
    }
    const text = await res.text();

    // CAPTCHA / アクセス拒否
    if (/Robot Check|automated access|api-services-support/i.test(text)) {
      return { status: "fetch_error", detail: "captcha_or_blocked" };
    }

    // 在庫キーワード
    const inStock = /カートに入れる|今すぐ買う|今すぐ購入|add to cart|buy now/i.test(text);
    if (!inStock) {
      return { status: "out_of_stock" };
    }

    // 販売者がAmazon.co.jpか判定
    const isAmazonSeller =
      /販売[:：]\s*<[^>]+>?\s*Amazon\.co\.jp/i.test(text) ||
      /販売[:：]\s*Amazon\.co\.jp/i.test(text) ||
      /sold by\s*<[^>]+>?\s*Amazon\.co\.jp/i.test(text);

    if (!isAmazonSeller) {
      // 販売者明記が見つからない or マーケットプレイスのみ
      return { status: "marketplace_only" };
    }

    return { status: "available_amazon" };
  } catch (e) {
    return { status: "exception", detail: String(e) };
  }
}

/**
 * Discord通知（在庫復活時）
 */
async function notifyDiscord(webhook, asin, name, prevStatus, newStatus) {
  const url = `https://www.amazon.co.jp/dp/${asin}`;
  const cartUrl = `https://www.amazon.co.jp/gp/aws/cart/add.html?ASIN.1=${asin}&Quantity.1=1`;

  const content =
    `🚨 **Amazon定価復活！即タップ！** 🚨\n` +
    `\n` +
    `**${name}**\n` +
    `🛒 **[ワンタップでカートに追加](${cartUrl})**\n` +
    `📦 [商品ページ](${url})\n` +
    `\n` +
    `状態遷移: \`${prevStatus}\` → \`${newStatus}\``;

  const payload = {
    content: content,
    embeds: [{
      title: name,
      url: cartUrl,
      color: 0xff6b00, // オレンジ（緊急色）
      footer: { text: `ASIN: ${asin} / 検知: Cloudflare Worker (1分間隔)` },
      timestamp: new Date().toISOString(),
    }],
  };

  try {
    await fetch(webhook, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    console.error("Discord notify failed:", e);
  }
}

/**
 * 全ASINをチェック・差分通知・状態更新
 */
async function runChecks(env) {
  const checks = ASINS.map(async ({ asin, name }) => {
    const result = await checkAmazon(asin);
    const prevState = (await env.STOCK_STATE.get(asin)) || "unknown";

    // 新規 in_stock 検知
    if (result.status === "available_amazon" && prevState !== "available_amazon") {
      console.log(`[ALERT] ${asin} ${name}: ${prevState} → ${result.status}`);
      if (env.DISCORD_WEBHOOK_URL) {
        await notifyDiscord(env.DISCORD_WEBHOOK_URL, asin, name, prevState, result.status);
      }
    }

    // 状態変化があった時のみKV書き込み（Free planの1日1,000書き込み上限対策）
    if (result.status !== prevState) {
      await env.STOCK_STATE.put(asin, result.status, {
        expirationTtl: 86400 * 30, // 30日
      });
    }

    return { asin, name, prevState, ...result };
  });

  return await Promise.all(checks);
}

export default {
  /**
   * Cloudflare Cron Trigger
   * wrangler.toml の crons = ["* * * * *"] で毎分起動
   */
  async scheduled(event, env, ctx) {
    const startTime = Date.now();
    const results = await runChecks(env);
    const elapsed = Date.now() - startTime;

    const summary = results.reduce((acc, r) => {
      acc[r.status] = (acc[r.status] || 0) + 1;
      return acc;
    }, {});
    console.log(`[scheduled] ${elapsed}ms / ${ASINS.length}件 / 集計:`, JSON.stringify(summary));

    // 検知失敗が多い場合はログ警告
    const errCount = (summary.fetch_error || 0) + (summary.exception || 0);
    if (errCount > ASINS.length / 2) {
      console.warn(`[scheduled] 取得失敗多数: ${errCount}/${ASINS.length}（Amazon側でブロックされた可能性）`);
    }
  },

  /**
   * 手動テスト用 HTTP fetch
   *   GET / → 簡易ステータス
   *   GET /check → 全ASINを即時チェック（KV更新なし・通知なし）
   *   GET /run → 全ASINチェック（KV更新あり・通知あり）
   *   GET /state → 現在のKV状態一覧
   */
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === "/check") {
      // 通知・KV更新せずチェックのみ
      const results = await Promise.all(
        ASINS.map(async ({ asin, name }) => {
          const result = await checkAmazon(asin);
          return { asin, name, ...result };
        })
      );
      return new Response(JSON.stringify(results, null, 2), {
        headers: { "Content-Type": "application/json; charset=utf-8" },
      });
    }

    if (url.pathname === "/run") {
      const results = await runChecks(env);
      return new Response(JSON.stringify(results, null, 2), {
        headers: { "Content-Type": "application/json; charset=utf-8" },
      });
    }

    if (url.pathname === "/state") {
      const states = await Promise.all(
        ASINS.map(async ({ asin, name }) => ({
          asin,
          name,
          state: (await env.STOCK_STATE.get(asin)) || "unknown",
        }))
      );
      return new Response(JSON.stringify(states, null, 2), {
        headers: { "Content-Type": "application/json; charset=utf-8" },
      });
    }

    return new Response(
      `amazon-pokemon-watcher\n` +
      `毎分Amazon在庫をチェックしDiscord通知します。\n\n` +
      `Endpoints:\n` +
      `  GET /check  — 即時チェック（KV更新・通知なし）\n` +
      `  GET /run    — 即時チェック＋KV更新＋通知\n` +
      `  GET /state  — 現在のKV状態\n`,
      { headers: { "Content-Type": "text/plain; charset=utf-8" } }
    );
  },
};
