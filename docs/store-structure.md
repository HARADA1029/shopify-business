# ストア構造設計

## 目的

中古日本フィギュア・おもちゃを海外コレクター向けに販売する Shopify ストアの
コレクション構造、ナビゲーション、フィルター、トップページ導線を設計する。
catalog-migration-planner が移行時のマッピング先として参照できる精度で定義する。

---

## 前提条件

| 項目 | 内容 |
|---|---|
| 商材 | 中古の日本フィギュア・おもちゃ（一点物中心） |
| 顧客像 | 海外コレクター（25〜45歳、US/UK/AU/CA 中心、英語話者） |
| 初期 SKU 数 | 300〜500 |
| 言語 | 英語（ストア全体） |
| 通貨 | USD 表示（Shopify Payments で自動変換） |

### コレクター顧客の購買行動（仮説）

- **作品名で探す**（"I want a Dragon Ball figure"）
- **キャラクター名で探す**（"I want Goku"）→ タグ/フィルターで対応
- **メーカー・ブランドで探す**（"I collect Bandai S.H.Figuarts"）
- **商品タイプで探す**（"I want action figures" / "I want model kits"）
- **新着を見る**（"What just came in?"）
- **セール品を見る**（"Any deals?"）

この購買行動に合わせてコレクション構造を設計する。

---

## コレクション分類の3軸

商品を3つの軸で分類し、それぞれを Shopify のコレクションとして構築する。
顧客はどの軸からでも商品にたどり着ける。

**キャラクター名は独立したコレクション軸にはしない。**
キャラクター数が膨大になりコレクション管理が破綻するため、
タグまたはメタフィールドによるフィルター軸として扱う（後述のフィルター項目を参照）。

### 軸1: 商品タイプ（Type）— 最上位の分類

商品の物理的なカテゴリ。初見の顧客が最初に選ぶ入口。

| コレクション名 | 対象 | 備考 |
|---|---|---|
| Action Figures | アクションフィギュア全般 | S.H.Figuarts, figma, MAFEX 等 |
| Scale Figures | スケールフィギュア | 1/7, 1/8 等のスタチュー系 |
| Model Kits | プラモデル・ガレージキット | ガンプラ、コトブキヤ等 |
| Plush & Soft Toys | ぬいぐるみ・ソフトトイ | |
| Vintage & Retro Toys | ビンテージ・レトロ玩具 | 80〜90年代中心 |
| Other Collectibles | 上記に当てはまらないもの | キーホルダー、缶バッジ等 |

### 軸2: 作品・フランチャイズ（Franchise）— コレクターの主な探し方

作品名ごとのコレクション。コレクターが最も使う軸。

初期は eBay の売上上位フランチャイズから作成し、SKU が増えたら追加する。

| コレクション名 | 備考 |
|---|---|
| Dragon Ball | ドラゴンボール全般 |
| One Piece | ワンピース全般 |
| Naruto | ナルト全般 |
| Gundam | ガンダム全般（プラモ含む） |
| Demon Slayer | 鬼滅の刃 |
| My Hero Academia | 僕のヒーローアカデミア |
| Neon Genesis Evangelion | エヴァンゲリオン |
| Sailor Moon | セーラームーン |
| Pokemon | ポケモン |
| Studio Ghibli | ジブリ作品全般 |

※ 初期移行の 300〜500 SKU に含まれるフランチャイズのみ作成する。
  SKU が5件未満のフランチャイズはコレクションを作らず Other に含める。

### 軸3: メーカー・ブランド（Brand）— 上級コレクター向け

特定メーカーのファンが使う軸。初期は主要メーカーのみ。

| コレクション名 | 備考 |
|---|---|
| Bandai / Banpresto | バンダイ・バンプレスト |
| MegaHouse | メガハウス（P.O.P 等） |
| Good Smile Company | ねんどろいど、figma |
| Kotobukiya | コトブキヤ |
| Tamashii Nations | S.H.Figuarts, Robot 魂 |

※ 軸2と同様、初期は SKU 数に応じて作成する。

---

## 特殊コレクション（運営用）

| コレクション名 | 種別 | 用途 |
|---|---|---|
| New Arrivals | 自動 | 直近30日以内に追加された商品（Shopify の自動コレクション条件で実現） |
| Sale | 手動 | セール対象商品（手動で追加・削除） |
| Staff Picks | 手動 | おすすめ商品（トップページ用） |
| All Products | 自動 | 全商品（Shopify デフォルト） |

**New Arrivals の初期運用に関する注意:**
初期移行時は全商品の作成日が同時期になるため、New Arrivals に全商品が入ってしまう。
ソフトローンチ初期は以下のいずれかで対処する:
- **段階投入:** 商品を数日に分けて公開し、New Arrivals が自然に入れ替わるようにする
- **手動調整:** 初期は New Arrivals を自動コレクションではなく手動コレクションで運用し、安定後に自動に切り替える

---

## ナビゲーション構造

### ヘッダーナビゲーション（メインメニュー）

```
Shop ▼           Franchises ▼         Brands ▼        New Arrivals    Sale
├ Action Figures  ├ Dragon Ball        ├ Bandai
├ Scale Figures   ├ One Piece          ├ MegaHouse
├ Model Kits      ├ Naruto             ├ Good Smile
├ Plush & Soft    ├ Gundam             ├ Kotobukiya
├ Vintage & Retro ├ Demon Slayer       ├ Tamashii Nations
├ Other           ├ More Franchises... └ More Brands...
└ All Products    └ (残りは一覧ページ)
```

**設計方針:**
- ドロップダウンは各カテゴリ5〜6件まで。それ以上は「More...」リンクで一覧ページに飛ばす
- New Arrivals と Sale はドロップダウンなしの直リンク（目立たせる）
- モバイルではハンバーガーメニューに折りたたむ

### フッターナビゲーション

```
Shop              Help                About
├ New Arrivals    ├ Shipping Policy   ├ About Us
├ All Products    ├ Return Policy     ├ Contact
├ Sale            ├ FAQ               └ 特定商取引法に基づく表記
└ Gift Cards      └ Contact
```

---

## フィルター・ソート

Shopify のコレクションページで使えるフィルター軸。

### フィルター項目

| フィルター | 実装方法 | 備考 |
|---|---|---|
| Price | Shopify 標準 | 価格帯でフィルター |
| Availability | Shopify 標準 | In Stock のみ（基本的に全商品 In Stock のはず） |
| Franchise | 商品タグ | タグに作品名を入れておく |
| Character | 商品タグまたはメタフィールド | キャラクター名。コレクションにはせずフィルター軸として提供する。メタフィールドを使えば検索・フィルターの精度が上がるが、初期はタグ運用でも可 |
| Brand | 商品 Vendor フィールド | Shopify 標準のフィルター |
| Condition | 商品タグ | "Mint", "Near Mint", "Good", "Fair"（後述の注記参照） |

### Condition 表記に関する注記

Condition の4段階（Mint / Near Mint / Good / Fair）は本設計の仮定義。
eBay 側では独自の状態表記（例: "Used - Like New", "Used - Good" 等）を使用している可能性がある。
catalog-migration-planner が移行スクリプトを設計する際に、
**eBay 側の既存 Condition 表記との対応表** を作成する必要がある。

### ソート順

| ソート | 備考 |
|---|---|
| Newest | デフォルト。新着順。コレクターは新入荷を最優先で見る |
| Price: Low to High | 予算で探す顧客向け |
| Price: High to Low | 高額レア品を探す顧客向け |
| Best Selling | 売上実績が溜まってから有効（初期は機能しない） |

---

## トップページ導線設計

### 構成案（上から順に）

| セクション | 内容 | 目的 |
|---|---|---|
| **Hero Banner** | ストアのキャッチコピー + CTA ボタン（"Shop Now"） | 初訪問者にストアの特徴を一瞬で伝える |
| **New Arrivals** | 新着商品カルーセル（8〜12件） | リピーター・コレクターが最初に見る場所 |
| **Shop by Franchise** | フランチャイズ別のアイコンタイル（6〜10件） | 作品名で探したい顧客の入口 |
| **Staff Picks** | おすすめ商品（4〜8件） | 高品質な商品を目立たせて信頼感を作る |
| **Shop by Type** | 商品タイプ別のバナー（3〜4件） | タイプで探したい顧客の入口 |
| **About / Trust** | 「日本から直接発送」「eBay で○件の取引実績」等 | 海外顧客の不安を払拭する信頼要素 |
| **Newsletter Signup** | メールアドレス取得フォーム | リピーター育成の基盤 |

### Hero Banner のキャッチコピー案

| 案 | ニュアンス |
|---|---|
| "Authentic Japanese Figures & Toys — Shipped Directly from Japan" | 日本直送の信頼感を訴求 |
| "Rare & Vintage Japanese Collectibles — Curated for Collectors" | コレクター向けのキュレーション感 |
| "Your Source for Pre-Owned Japanese Figures" | シンプルに商材を伝える |

※ ブランド名が決まってから最終確定する。

---

## 商品ページの構成要素

| 要素 | 内容 | 備考 |
|---|---|---|
| 商品タイトル | 英語。フランチャイズ名 + キャラ名 + 商品タイプ + メーカー | SEO とフィルターの両方に効く |
| 商品画像 | 最低3枚（正面・背面・付属品/箱） | 中古のため状態が分かる画像が重要 |
| 価格 | USD 表示 | |
| Condition | 商品状態（Mint / Near Mint / Good / Fair） | タグとしても設定する。eBay 既存表記との対応表は別途作成 |
| Description | 英語の商品説明。状態の詳細、付属品の有無、サイズ | |
| Franchise タグ | 作品名（例: "Dragon Ball"） | フィルター・自動コレクション用 |
| Character タグ | キャラクター名（例: "Son Goku"） | フィルター用。コレクションにはしない |
| Vendor | メーカー名（例: "Bandai"） | Shopify 標準フィールド |
| Product Type | 商品タイプ（例: "Action Figure"） | Shopify 標準フィールド |

### 商品タイトルの命名規則（案）

```
[Franchise] [Character] [Product Line] [Maker] - [Condition]
例: Dragon Ball Z - Son Goku - S.H.Figuarts (Bandai) - Near Mint
```

※ catalog-migration-planner がこの規則に沿って eBay タイトルを変換する。

---

## 推奨構成案まとめ

```
ストア
├── [Nav] Shop（商品タイプ別: 6カテゴリ）
├── [Nav] Franchises（作品別: 初期10前後、SKU数に応じて増減）
├── [Nav] Brands（メーカー別: 初期5前後）
├── [Nav] New Arrivals（自動/手動: 初期は段階投入で調整）
├── [Nav] Sale（手動）
├── [Top] Hero Banner → New Arrivals → Franchise タイル → Staff Picks → Type バナー → Trust → Newsletter
├── [Filter] Price / Franchise / Character（タグ） / Brand / Condition
├── [Sort] Newest（デフォルト）/ Price
└── [Product] タイトル命名規則 + 状態表記 + タグ体系（Character はフィルター軸）
```

---

## 初期 300〜500 SKU の並べ方

1. **全商品を商品タイプ（軸1）に分類する** — 必ず1つのタイプに属する
2. **フランチャイズ（軸2）のタグを付ける** — SKU 5件以上のフランチャイズはコレクション化。5件未満はタグのみ
3. **キャラクター名をタグとして付ける** — コレクションにはせず、フィルター軸として機能させる
4. **メーカー（軸3）を Vendor フィールドに入れる** — 自動でフィルター対象になる
5. **Condition タグを付ける** — Mint / Near Mint / Good / Fair の4段階（eBay 既存表記との対応表は別途作成）
6. **New Arrivals は段階投入で調整** — 全商品を一度に公開せず、数日に分けて公開することで新着の入れ替わりを自然に見せる
7. **Staff Picks は移行後に手動で10〜20件選定** — トップページの目玉になる高品質・人気商品

---

## catalog-migration-planner への申し送り事項

移行スクリプト設計時に、以下のフィールドマッピングが必要:

| Shopify フィールド | データソース | 変換ルール |
|---|---|---|
| Title | eBay タイトル | 命名規則に沿って再構成 |
| Product Type | eBay カテゴリ | カテゴリマッピング表で変換 |
| Vendor | eBay の Item Specifics 等 | メーカー名を抽出 |
| Tags | eBay タイトル + カテゴリ | フランチャイズ名 + キャラクター名 + Condition を抽出 |
| Body HTML | eBay 商品説明 | 英語のまま。Shopify テンプレートに合わせて整形 |
| Images | eBay 画像 URL | 再アップロード or CDN 参照（別途決定） |
| Price | eBay 価格 | USD のまま。マージン調整は別途検討 |

**追加で必要な対応表:**
- eBay Condition 表記 → Shopify Condition タグの対応表

---

## オーナー確認事項

- [ ] 3軸分類（商品タイプ / フランチャイズ / メーカー）の方針でよいか
- [ ] キャラクター名はコレクションにせずタグ/フィルター運用でよいか
- [ ] 初期のフランチャイズ一覧は eBay 売上上位から選定してよいか（具体的な作品リストはオーナーの方が正確に持っている）
- [ ] 商品状態の表記は Mint / Near Mint / Good / Fair の4段階でよいか（eBay で使っている表記があれば教えてほしい）
- [ ] 商品タイトルの命名規則案でよいか
- [ ] ブランド名・ドメイン名の方向性（ストア名・Hero Banner の表現に影響）
- [ ] eBay の取引実績数をストアの信頼要素として掲載してよいか
