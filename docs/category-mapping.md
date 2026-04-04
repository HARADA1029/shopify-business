# カテゴリマッピング定義（eBay → Shopify）

## 目的

eBay の商品データを Shopify の3軸分類（商品タイプ / フランチャイズ / メーカー）に
変換するルールを定義する。
catalog-migration-planner が移行スクリプトを設計する際の参照仕様書として使う。

---

## マッピング全体像

| eBay 側のデータソース | Shopify フィールド | 変換方法 |
|---|---|---|
| eBay Primary Category | **Product Type** | カテゴリ ID ベースのマッピング表（本資料のメイン） |
| Item Specifics: Brand | **Vendor** | 表記ゆれ正規化テーブルで変換 |
| Item Title（キーワード抽出） | **Tags: Franchise** | フランチャイズ名辞書でマッチング |
| Item Title（キーワード抽出） | **Tags: Character** | キャラクター名辞書でマッチング |
| eBay Condition | **Tags: Condition** | Condition 対応表で変換 |

---

## 1. Product Type マッピング（eBay Category → Shopify Type）

### マッピング表

| Shopify Product Type | eBay カテゴリ（推定） | 判定ルール |
|---|---|---|
| **Action Figures** | Anime & Manga > Action Figures / Collectible Animation Action Figures / S.H.Figuarts / figma / MAFEX 等 | 可動関節があり、ポーズを変えられるフィギュア |
| **Scale Figures** | Anime & Manga > Figures / Statues / PVC Figures / Prize Figures 等 | 固定ポーズのスタチュー系。スケール表記（1/7, 1/8 等）があれば確定 |
| **Model Kits** | Models & Kits / Gundam > Model Kits / Garage Kits 等 | 組み立てが必要な商品。完成品は Action Figures または Scale Figures |
| **Plush & Soft Toys** | Stuffed Animals / Plush / Soft Toys 等 | 素材が布・綿のもの |
| **Vintage & Retro Toys** | Vintage Toys / Pre-1990s / Retro 等 | 製造年が1999年以前の商品（初期の仮基準。後述の判定基準参照） |
| **Other Collectibles** | 上記いずれにも該当しないもの | キーホルダー、缶バッジ、クリアファイル、食玩、カード等 |

※ eBay カテゴリ ID は実データのサンプリング後に具体的な ID 番号を確定する。

### 迷いやすいケースの判定基準

#### Action Figures vs Scale Figures

| 判定基準 | Action Figures | Scale Figures |
|---|---|---|
| 可動関節 | あり | なし（固定ポーズ） |
| 代表的な商品ライン | S.H.Figuarts, figma, MAFEX, Revoltech | Banpresto Prize, Alter, Kotobukiya ARTFX |
| スケール表記 | なし or 表記があっても可動 | あり（1/7, 1/8 等） |
| タイトルに "action" を含む | Action Figures 確定 | — |
| タイトルに "statue" "figure" のみ | — | Scale Figures |

**最終判定ルール:**
1. 商品ラインが既知（S.H.Figuarts 等）→ 商品ライン辞書で自動判定
2. スケール表記あり + 可動の記載なし → Scale Figures
3. "action figure" がタイトルに含まれる → Action Figures
4. 上記いずれでもない → **手動確認リストに入れる**（誤分類を防ぐため、デフォルト分類はしない）

#### Model Kits の範囲

| 含める | 含めない |
|---|---|
| 未組立のプラモデル（ガンプラ等） | 組立済み・完成品として販売されている商品 |
| 未組立のガレージキット | 塗装済み完成品のガレージキット → Scale Figures |
| 組立済みだが「Model Kit」として出品 | 素組み完成品で Action Figure として出品 → Action Figures |

**最終判定ルール:**
- eBay カテゴリが Models & Kits 系 → Model Kits
- タイトルに "model kit" "plastic model" "plamo" を含む → Model Kits
- タイトルに "built" "assembled" "painted" を含む → Scale Figures（完成品扱い）

#### Vintage & Retro Toys の判定

| 基準 | ルール |
|---|---|
| 年代判定 | 製造年1999年以前を Vintage & Retro とする（初期の仮基準。サンプル分析後にオーナーと最終ラインを確定する。商材の実態に応じて2004年以前等に調整する余地がある） |
| 年代不明の場合 | タイトルに "vintage" "retro" "classic" を含む → Vintage & Retro |
| eBay カテゴリが Vintage 系 | Vintage & Retro 確定 |
| 1999年以前の作品だが商品自体が新しい | 商品の製造年で判定（作品の年代ではない）。例: 2020年製の初代ガンダムフィギュア → Scale Figures |

#### Other Collectibles に分類される商品

| 商品例 | 備考 |
|---|---|
| キーホルダー・ストラップ | フィギュアではない小物 |
| 缶バッジ・ピンバッジ | |
| クリアファイル・ポスター | 紙製品 |
| 食玩（開封済み・フィギュア以外） | 食玩フィギュアは Scale Figures |
| トレーディングカード | |
| アクリルスタンド | |

**判定ルール:** 上記5タイプのいずれにも該当しない → Other Collectibles

---

## 2. Vendor マッピング（eBay Brand → Shopify Vendor）

### 表記ゆれ正規化テーブル

| Shopify Vendor（正規化後） | eBay 側の表記パターン（推定） |
|---|---|
| **Bandai** | Bandai, BANDAI, バンダイ, Bandai Namco |
| **Banpresto** | Banpresto, BANPRESTO, バンプレスト |
| **Good Smile Company** | Good Smile, Good Smile Company, GSC, グッドスマイル |
| **Kotobukiya** | Kotobukiya, KOTOBUKIYA, コトブキヤ, Koto |
| **MegaHouse** | MegaHouse, Megahouse, MEGAHOUSE, メガハウス |
| **Tamashii Nations** | Tamashii Nations, TAMASHII NATIONS, 魂ネイションズ |
| **Kaiyodo** | Kaiyodo, KAIYODO, 海洋堂 |
| **Medicom Toy** | Medicom, Medicom Toy, MEDICOM, メディコム |
| **Takara Tomy** | Takara Tomy, TAKARA TOMY, Takara, Tomy, タカラトミー |
| **Funko** | Funko, FUNKO |

**変換ルール:**
1. eBay の Brand フィールドが入力済み → 正規化テーブルで変換
2. Brand が空欄 → Item Title からメーカー名をキーワードマッチで抽出
3. どちらでも特定できない → Vendor を空欄にする（Shopify 上は "Unknown" 表示を避け、空欄のまま）

※ サンプリング後に実際の表記パターンを確認し、テーブルを更新する。

---

## 3. Franchise タグマッピング（Item Title → Tags）

### フランチャイズ名辞書

Item Title に以下のキーワードが含まれていたら、対応する Franchise タグを付与する。

| Franchise タグ | マッチキーワード（大文字小文字区別なし） |
|---|---|
| **Dragon Ball** | dragon ball, dragonball, dbz, db super |
| **One Piece** | one piece, onepiece |
| **Naruto** | naruto, boruto, shippuden |
| **Gundam** | gundam, ガンダム |
| **Demon Slayer** | demon slayer, kimetsu |
| **My Hero Academia** | my hero academia, boku no hero, mha |
| **Neon Genesis Evangelion** | evangelion, eva unit, nerv |
| **Sailor Moon** | sailor moon |
| **Pokemon** | pokemon, pikachu, pokémon |
| **Studio Ghibli** | ghibli, totoro, spirited away, kiki, mononoke, howl |
| **Jujutsu Kaisen** | jujutsu kaisen, jujutsu |
| **Attack on Titan** | attack on titan, shingeki |
| **Chainsaw Man** | chainsaw man |
| **Spy x Family** | spy x family, spy family |

**変換ルール:**
1. タイトルに複数のフランチャイズキーワードが含まれる場合 → 最初にマッチしたものを Primary Franchise タグとする。2つ目以降もタグとして追加する
2. どのキーワードにもマッチしない → Franchise タグなし。手動で確認する対象リストに入れる
3. フランチャイズ辞書は随時追加する。サンプリング後に上位10を確定する

---

## 4. Character タグマッピング（Item Title → Tags）

キャラクター名は数が膨大なため、フランチャイズのような固定辞書ではなく、
以下の方法で抽出する。

**抽出方法（優先順）:**
1. eBay Item Specifics に Character フィールドがあれば → そのまま使用
2. Character フィールドが空 → タイトルからフランチャイズ名・メーカー名・商品タイプを除いた残りの固有名詞部分を抽出（ルールベースまたは手動確認）

**初期バッチでの方針:**
- Item Specifics の Character フィールド入力率が50%以上 → 入力済みの商品は自動抽出、空欄は省略
- 入力率が50%未満 → **初期バッチでは Character タグを省略する**。Product Type / Franchise / Vendor の3軸を優先し、Character は後続バッチで整備する。初期ストアの検索・フィルター体験への影響は限定的（Shopify のサイト内検索でタイトル中のキャラクター名はヒットする）

---

## 5. Condition マッピング（eBay Condition → Tags）

| eBay Condition | Shopify Condition タグ |
|---|---|
| New / Brand New | Mint |
| New Other / Open Box | Near Mint |
| Used - Like New | Near Mint |
| Used - Very Good | Good |
| Used / Pre-Owned | Good |
| Used - Good | Good |
| Used - Acceptable | Fair |
| For Parts / Not Working | **初期移行から除外** |

※ eBay の実データで使用されている Condition 値を確認した後に確定する。
  上記は eBay 標準値に基づく推定。

---

## 6. 商品タイトルの変換ルール

### 変換フォーマット

```
[Franchise] [Character] [Product Line] ([Maker]) - [Condition]
```

### 変換例

| eBay Title（原文） | Shopify Title（変換後） |
|---|---|
| S.H.Figuarts Dragon Ball Z Son Goku BANDAI Used | Dragon Ball Z - Son Goku - S.H.Figuarts (Bandai) - Good |
| One Piece P.O.P Roronoa Zoro MegaHouse Figure Near Mint | One Piece - Roronoa Zoro - P.O.P (MegaHouse) - Near Mint |
| HG 1/144 RX-78-2 Gundam Bandai Plastic Model Kit New | Gundam - RX-78-2 Gundam - HG 1/144 (Bandai) - Mint |

### 変換ルール

1. **フランチャイズ名を先頭に移動** — SEO と一覧表示で作品名が最初に見える
2. **キャラクター名をフランチャイズの次に配置** — フランチャイズ内での識別
3. **商品ライン名を含める** — コレクターはライン名で探す（S.H.Figuarts, P.O.P 等）
4. **メーカー名は括弧内に** — Vendor フィールドと重複するため控えめに
5. **Condition をハイフン区切りで末尾に** — 一覧画面で状態がすぐ分かる
6. **不要な語句を削除** — "Free Shipping", "Rare!!", "L@@K" 等の eBay 特有の煽り文句

### 自動変換が困難なケース

| ケース | 対応方針 |
|---|---|
| タイトルが日本語のみ | 初期移行から除外。後続バッチで英語タイトルを手動作成 |
| フランチャイズが特定できない | 手動確認リストに入れる |
| 複数フランチャイズにまたがる（コラボ商品等） | Primary フランチャイズを手動で判定 |
| 商品ライン名が不明 | 省略して `[Franchise] [Character] ([Maker]) - [Condition]` とする |

---

## 例外ルール・エッジケース

### 1商品が複数タイプにまたがる場合

| ケース | 判定 |
|---|---|
| ガンプラ（Model Kit）だが完成品として販売 | タイトルに "built" "assembled" → Scale Figures |
| 食玩のミニフィギュア | サイズ・品質で判定。コレクション性が高い → Scale Figures。それ以外 → Other |
| セット商品（フィギュア + アクリルスタンド） | メインの商品で判定。フィギュアがメイン → Scale Figures |

### 初期移行で例外扱いにする商品群

| 商品群 | 理由 | 対応 |
|---|---|---|
| **マッピング不能品** | eBay カテゴリとタイトルのどちらからも Product Type を判定できない | 手動確認リストに入れ、初期移行では後回し |
| **コラボ・クロスオーバー商品** | フランチャイズの自動判定が困難 | 手動確認リストに入れる |
| **大型セット・まとめ売り** | 1商品に複数アイテムが含まれ、分類が複雑 | 初期移行から除外。個別分割後に対応 |
| **eBay カテゴリが "Other" のみ** | Product Type の自動判定が不可能 | 手動確認リストに入れる |

---

## マッピング確定の進め方

### Step 1: サンプル検証（Day 5）
- ebay-data-analysis.md の50件サンプルに対して本マッピングルールを試適用
- 自動判定できた割合 / 手動確認が必要な割合を計測

### Step 2: ルール調整（Day 5〜6）
- 自動判定率が80%未満の場合、辞書やルールを拡充
- 新たに見つかった表記ゆれをテーブルに追加

### Step 3: 全件適用（Day 6〜7）
- 移行対象 300〜500 SKU に本マッピングを適用
- 手動確認リストを作成（目標: 全体の10%以下に抑える）

---

## オーナー確認事項

- [ ] eBay で使用している主な商品カテゴリの一覧（上位10カテゴリ）
- [ ] Action Figures と Scale Figures の境界ルールはこの基準でよいか（自社の分類感覚と合っているか）
- [ ] Vintage & Retro の年代基準（仮: 1999年以前）は妥当か、調整したい年代ラインがあるか
- [ ] メーカー名の表記ゆれで、上記テーブルにない頻出パターンがあるか
- [ ] 商品タイトルの変換フォーマットはこの形でよいか
- [ ] eBay Item Specifics の Character フィールドの入力率（大まかな感覚で可）
