# tcg-restock-notifier

トレーディングカードの抽選受付開始・即時購入の在庫復活を検知して Discord に通知するツール。
5分おきに GitHub Actions が対象ページをチェックし、変化があれば Discord Webhook 経由で通知します。
状態(`state.json`)はリポジトリにコミットされるため、通知先が Discord アカウントである限り、iPhone の機種変更・故障があっても引き継ぎ不要です。

## セットアップ

1. **Discord Webhook を作る**
   Discord サーバー → 通知を受け取りたいチャンネルの設定 → 連携サービス → ウェブフック → 新しいウェブフック → URLをコピー。

2. **GitHub リポジトリを作る**
   このフォルダの中身を新規リポジトリに push する。

   ```
   git init
   git add .
   git commit -m "init"
   git branch -M main
   git remote add origin <あなたのリポジトリURL>
   git push -u origin main
   ```

3. **Secrets を登録**
   リポジトリの Settings → Secrets and variables → Actions → New repository secret
   - Name: `DISCORD_WEBHOOK_URL`
   - Value: 手順1でコピーしたURL

4. **Actions を有効化**
   Actions タブで workflow を確認し、`Run workflow` で手動実行して動作確認する。以降は5分おきに自動実行されます。

## 監視対象の追加・変更

`targets.yaml` にエントリを追記するだけです。

```yaml
- name: "わかりやすい名前"
  url: "https://example.com/product/xxxx"
  keyword: "SOLD OUT"
  alert_on: "disappear"   # キーワードが消えたら通知(売り切れ表示が消えた=買える)
```

- `alert_on: "appear"` → キーワードが新しく出現したら通知(例: 「抽選受付中」の文字が出た)
- `alert_on: "disappear"` → キーワードが消えたら通知(例: 「SOLD OUT」の文字が消えた)

実際のページを見て、対象商品ページで在庫あり/なしがどんな文言で表示されるか確認し、`keyword` と `alert_on` を調整してください。

## ローカルでのテスト

```
pip install -r requirements.txt
$env:DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/xxxx"
python check.py
```

## 既知の注意点

- ポケモンセンターオンラインは Bot 対策(WAF)がある可能性があり、`requests` での取得がブロックされる/正しいHTMLが返らない場合があります。その場合はヘッダー調整やヘッドレスブラウザ(Playwright等)への切り替えが必要です。
- Amazon・楽天などの大手ECモールはスクレイピングが利用規約に抵触しやすいため、意図的に対象外にしています。
