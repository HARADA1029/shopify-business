# Shopify ストア初期設定 → インポート → 公開チェックリスト

## 最重要方針: eBay 既存事業の保護

**本プロジェクトでは、eBay 既存アカウント・既存出品に変更を加えない。**

| ルール | 詳細 |
|--------|------|
| **eBay 出品の変更禁止** | タイトル・説明文・画像・価格・設定など、既存出品への書き込み操作は一切行わない |
| **読み取り専用 API のみ使用** | GetMyeBaySelling / GetItem など、データ取得の API のみ。ReviseItem / EndItem / AddItem などの書き込み系 API は使用しない |
| **eBay → Shopify への誘導禁止** | eBay の listing / description / images / messages に Shopify の URL やストア名を記載しない（eBay の off-eBay 誘導ポリシー違反リスク） |
| **Shopify は独立チャネル** | Shopify は eBay と完全に独立した追加の販売チャネルとして構築する。eBay の運営に影響を与えない |
| **eBay 既存売上が最優先** | Shopify は追加の売上機会であり、eBay の既存売上を犠牲にしない |

将来的に在庫同期（eBay で売れたら Shopify を非公開にする等）を導入する際も、
方式決定・テスト検証を経てから慎重に進める。事前に原田の承認を得てから実施する。


## 前提

- プラン: Basic（¥4,850/月）で開始（`docs/shopify-plan-comparison.md` に基づく）
- ストア構造: `docs/store-structure.md` に基づく
- 投入データ: `shopify_import.csv`（100件・415行・draft 状態）
- 投入方式: CSV インポート（`docs/shopify-import-method.md` に基づく）


## Phase 1: ストア開設・基本設定

ストア開設直後に行う設定。インポート前に完了させる。

### 1-1. アカウント・プラン

- [ ] Shopify アカウント作成
- [ ] Basic プラン（月払い）を選択
- [ ] ストア名を設定（仮でよい。後から変更可能）
- [ ] ストアの通貨を **USD** に設定
- [ ] ストアの言語を **English** に設定
- [ ] タイムゾーンを **Asia/Tokyo** に設定

### 1-2. Shopify Payments（決済）

- [ ] Shopify Payments を有効化
- [ ] 事業者情報を入力（本人確認・口座登録）
- [ ] PayPal を連携（Shopify Payments と併用）
- [ ] テストモードを有効化（テスト注文用）

### 1-3. テーマ

- [ ] 無料テーマを選定（推奨: Dawn または Refresh）
  - Dawn: Shopify 公式。シンプル・高速。カスタマイズ性高
  - Refresh: 商品画像を大きく見せるレイアウト。コレクター商材向き
- [ ] ロゴを設定（初期はテキストロゴでよい）
- [ ] カラースキームを設定（白ベース + アクセント色）
- [ ] フォントを設定（デフォルトでよい）

### 1-4. 必須ページ

- [ ] **Shipping Policy** — 配送方法・到着目安・送料テーブル
- [ ] **Return Policy** — 返品条件・期限・送料負担
- [ ] **FAQ** — よくある質問（関税・配送日数・状態表記の説明）
- [ ] **About Us** — ストア紹介（日本から直送、ホビー・コレクター商品の専門性）
- [ ] **Contact** — 問い合わせフォーム（Shopify 標準の contact ページ）
- [ ] **特定商取引法に基づく表記** — 日本の法律要件（Shopify Payments 利用に必須）

**参考文テンプレート（Shipping Policy）:**
```
All items ship directly from Japan via tracked international shipping.
Estimated delivery: 5–14 business days.
Import duties, taxes, and customs fees are not included in the item price
and are the buyer's responsibility.
```

### 1-5. Shipping（配送設定）

- [ ] Shipping ゾーンを作成
  - Zone 1: United States
  - Zone 2: United Kingdom, Canada, Australia
  - Zone 3: Rest of World
- [ ] 配送料テーブルを設定（重量ベース）

初期の暫定配送料（後から調整可能）:

| ゾーン | 〜500g | 〜1kg | 〜2kg |
|--------|-------:|------:|------:|
| US | $15 | $20 | $30 |
| UK/CA/AU | $18 | $25 | $35 |
| Rest of World | $20 | $28 | $40 |

- [ ] 発送元住所を設定（日本の住所）

### 1-6. Taxes（税金設定）

- [ ] 商品価格に税を含めない設定を確認（海外向けは税別が標準）
- [ ] 日本の消費税は海外発送なら免税（輸出免税）→ 設定不要を確認

### 1-7. ドメイン

- [ ] 初期は `{store-name}.myshopify.com` で運用（無料）
- [ ] 独自ドメインは売上が出てから検討（後回し可能）


## Phase 2: Automated Collection 作成

CSV インポート **前に** 作成する。インポートと同時にタグベースで自動振り分けされる。

### 商品タイプ別コレクション

| Collection 名 | 条件 |
|---|---|
| - [ ] Action Figures | Tag = `Action Figures` |
| - [ ] Figures & Statues | Tag = `Scale Figures` |
| - [ ] Plush & Soft Toys | Tag = `Plush & Soft Toys` |
| - [ ] Trading Cards | Tag = `Trading Cards` |
| - [ ] Video Games | Tag = `Video Games` |
| - [ ] Media & Books | Tag = `Media & Books` |
| - [ ] Electronic Toys | Tag = `Electronic Toys` |

### 特殊コレクション

| Collection 名 | 種類 | 条件 |
|---|---|---|
| - [ ] New Arrivals | Automated | Product created date is within the last 30 days |
| - [ ] All Products | Automated | Shopify デフォルト（自動で存在） |
| - [ ] Sale | Manual | 手動で追加（初期は空でよい） |

### ナビゲーション

- [ ] メインメニューに商品タイプ別コレクションを追加
- [ ] フッターメニューに Shipping Policy / Return Policy / FAQ / About / Contact を追加


## Phase 3: CSV インポート

### インポート前の最終チェック

- [ ] `shopify_import.csv` のファイルエンコーディングが UTF-8 であること
- [ ] CSV の行数が 415行（ヘッダー除く）であること
- [ ] 全100商品の Status が `draft` であること
- [ ] Image Src の URL が eBay CDN を指していること（`https://i.ebayimg.com/...`）
- [ ] Automated Collection が7つ + New Arrivals + All Products 作成済みであること

### インポート手順

```
1. Shopify 管理画面 → Products → Import
2. shopify_import.csv を選択
3. プレビュー画面で以下を確認:
   - 商品数: 100
   - 「Overwrite existing products with matching handles」は OFF
4. Import products をクリック
5. インポート完了を待つ（数分）
6. 完了通知を確認
```

### インポート直後の確認

- [ ] Products 一覧に 100件が表示されるか
- [ ] 全100件が **Draft** 状態であるか
- [ ] 任意の5件を開いて以下を確認:
  - [ ] Title が正しいか
  - [ ] 画像が正しく読み込まれているか
  - [ ] Price / Compare at price が正しいか
  - [ ] Description が正しく表示されるか
  - [ ] Tags が付いているか
  - [ ] Vendor が入っているか（入っている商品について）
- [ ] Automated Collection に自動振り分けされているか
  - [ ] Action Figures コレクションに商品が入っているか
  - [ ] Trading Cards コレクションに商品が入っているか


## Phase 4: 10件試験公開

### 試験公開する10件の選び方

以下の条件を満たす商品を手動で選ぶ:

| 条件 | 理由 |
|------|------|
| 画像が3枚以上 | 商品ページの見栄えを確認 |
| 異なる Product Type から選ぶ | コレクション振り分けの動作確認 |
| 価格帯が $100〜$500 に収まる | 高額品は試験段階ではリスク |
| Vendor が入っている | フィルター動作の確認 |

### 公開手順

```
1. Products 一覧で10件を選択
2. More actions → Set as active
3. ストアのフロントエンドで表示を確認
```

### 試験公開チェックリスト

**商品ページ:**
- [ ] 商品画像が正しく表示されるか（全画像・拡大表示）
- [ ] タイトルが正しいか
- [ ] 価格が表示されるか（Price + Compare at price の取消線）
- [ ] Description が読みやすいか
- [ ] 「Add to cart」ボタンが機能するか

**コレクションページ:**
- [ ] 各コレクションに商品が正しく入っているか
- [ ] コレクションページでサムネイル・価格・タイトルが表示されるか
- [ ] ソート（Price: Low to High 等）が機能するか

**ナビゲーション:**
- [ ] メインメニューからコレクションに遷移できるか
- [ ] フッターリンクが正しく機能するか

**カート・チェックアウト:**
- [ ] 商品をカートに追加できるか
- [ ] カートページで商品・価格・数量が正しいか
- [ ] Checkout に進めるか
- [ ] 配送先住所の入力ができるか
- [ ] 配送料が正しく計算されるか（Shipping ゾーン設定通りか）
- [ ] テスト注文が完了するか（Shopify Payments テストモード使用）

**モバイル表示:**
- [ ] スマートフォンで商品ページが正しく表示されるか
- [ ] 画像のスワイプが動作するか
- [ ] Add to cart → Checkout の流れがモバイルで問題ないか

**SEO:**
- [ ] 商品ページの `<title>` タグが正しいか
- [ ] URL が Handle ベースで生成されているか（例: `/products/pokemon-card-lugia-...`）

**メール通知:**
- [ ] テスト注文後に注文確認メールが送られるか
- [ ] メール内の商品名・価格・配送先が正しいか


## Phase 5: 残り90件公開 → ソフトローンチ

### 公開判断基準

以下の **すべて** を満たしたら残り90件を公開する:

| # | 基準 | 確認方法 |
|---|------|---------|
| 1 | 10件の商品ページが正しく表示される | 目視確認 |
| 2 | テスト注文が checkout まで完了する | テストモードで実行 |
| 3 | 配送料が正しく計算される | US / UK / AU の住所で確認 |
| 4 | Collection の自動振り分けが動作している | 各コレクションページを確認 |
| 5 | モバイル表示に重大な問題がない | スマートフォンで確認 |
| 6 | 必須ページ（Shipping / Return / FAQ）が公開済み | ページを確認 |

### 公開手順

```
1. Products 一覧で Draft 商品を全選択
2. More actions → Set as active
3. 段階的に公開する場合:
   - Day 1: 30件公開
   - Day 2: 30件公開
   - Day 3: 30件公開
   → New Arrivals コレクションに自然な入れ替わりが生まれる
```

### 公開後の初動確認

- [ ] Google Search Console にサイトマップを送信
- [ ] Google Analytics を設定（Shopify 標準連携）
- [ ] SNS でストアオープンを告知（任意）

**再掲: eBay からの誘導は行わない。**
Shopify への集客は SEO・SNS・広告など eBay 外のチャネルのみで行う。


## Phase 6: 公開後1週間の監視項目

| 項目 | 頻度 | 確認内容 |
|------|------|---------|
| 注文 | 毎日 | 注文が入った場合の処理フロー確認 |
| 在庫同期 | 毎日 | eBay で売れた商品が Shopify に残っていないか（手動チェック） |
| 画像 | 3日後 | eBay CDN の画像が消えていないか（5件サンプル確認） |
| アクセス | 1週間後 | Google Analytics でトラフィックを確認 |
| エラー | 毎日 | Shopify の通知にエラーが出ていないか |
