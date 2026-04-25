# amazon-pokemon-watcher (Cloudflare Worker)

Amazon定価販売のポケカ・ワンピースカードBOXを **毎分** 監視し、在庫復活した瞬間にDiscord通知するCloudflare Worker。

## なぜCloudflare Worker？

| 監視方法 | cron間隔 | 検知遅延 | 実装 |
|---|---|---|---|
| GitHub Actions（既存） | 5分 | 4〜8分 | Python |
| **Cloudflare Worker（新）** | **1分** | **35秒〜1分** | JavaScript |

Cloudflareエッジから直接fetch → Runner起動オーバーヘッドゼロ・高速。

## セットアップ手順

### 1. wrangler CLI ログイン

スイングシグナル用のCloudflare Workerと同じアカウントを使うので、すでにログイン済みのはず。

```cmd
cd C:\Users\星野\pre-value-hunter\cloudflare-worker
wrangler whoami
```

未ログインの場合:
```cmd
wrangler login
```

### 2. KV namespace 作成

```cmd
wrangler kv namespace create STOCK_STATE
```

出力例:
```
{ binding = "STOCK_STATE", id = "abc123def456..." }
```

この `id` を `wrangler.toml` の `REPLACE_WITH_KV_ID` 部分に貼り付け。

### 3. Discord Webhook URL 設定

```cmd
wrangler secret put DISCORD_WEBHOOK_URL
```

→ プロンプトに既存のDiscord Webhook URL貼り付け（pokemon_watcher.py が使っているのと同じものでOK）。

### 4. デプロイ

```cmd
wrangler deploy
```

これで毎分自動実行が開始されます。

### 5. 動作テスト（任意）

デプロイ後、以下のURLにアクセスして即時チェック可能:

```
https://amazon-pokemon-watcher.<your-subdomain>.workers.dev/check
```

返却JSONで各ASINの状態を確認できます。

## エンドポイント

| URL | 動作 |
|---|---|
| `/` | 説明表示 |
| `/check` | 全ASIN即時チェック（KV更新・通知なし）|
| `/run` | 全ASINチェック＋KV更新＋通知（cronと同じ）|
| `/state` | 現在のKV状態一覧 |

## ASIN一覧

`src/index.js` の `ASINS` 配列を編集することで監視対象を変更可能。
新しいBOXを追加するときは ASIN と name を追記してデプロイし直すだけ。

## 既存システムとの関係

GitHub Actions側の `pokemon_watcher.py`（5分cron・9サイト）はそのまま稼働継続。
このWorkerは **Amazon専用の高速版** として並走。

- Amazon定価復活通知 → Cloudflare Worker（1分・速い）
- 量販店・抽選販売の通知 → GitHub Actions（5分・幅広い）

## トラブルシューティング

### CAPTCHA / アクセス拒否で取得失敗
Amazon側がCloudflareのIPをブロック気味な場合あり。`/check` で `fetch_error: captcha_or_blocked` が連発する場合:

1. UA をローテーションする（既に3種類で実装済み）
2. fetch間隔をずらす（現状並列）
3. Workers Free plan のリクエスト上限（1日10万）に注意

### KV使用量（Free plan: 1日10万読み込み・1,000書き込み）
- **読み込み**: 毎分15 × 60 × 24 = 21,600/日 → ✅ 余裕
- **書き込み**: 状態変化時のみ実装済み → ASIN1個が頻繁に在庫変動しない限り問題なし
