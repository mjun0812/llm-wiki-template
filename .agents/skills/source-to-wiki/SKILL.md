---
name: source-to-wiki
description: sources/ にある原資料を読み、wiki/ 以下の日本語Wikiページへ整理・統合し、関連リンク、wiki/index.md、wiki/changelog.md を更新するSkill。ユーザーが「sourcesをwiki化して」「source-to-wikiして」「取り込んだメモをwikiに整理して」「wikiを更新して」のように依頼したら必ず使うこと。sources/ の本文編集やファイル移動は対象外で、原資料をもとにした知識ベース更新だけを行う。
---

# source-to-wiki

`sources/` の原資料を読み、`wiki/` 以下の日本語Wikiを更新する。
`sources/` 側の移動、frontmatter整備、本文編集はこのSkillの範囲外。

## 併用するSkill

`wiki/` の本文を書く・更新する前に、local skill の `japanese-tech-writing` と `stop-ai-slop-jp` を読む。
最終本文は、日本語の技術文書として読みやすく、AI臭の少ない文章に整える。

## ルール

- **sources編集禁止**：`sources/` 配下は読むだけにする。frontmatter、本文、画像パス、ファイル名を変更しない。
- **根拠を残す**：Wikiページのfrontmatter `sources` または本文の「参照元」に、使った原資料への相対リンクを必ず残す。
- **過度に要約しない**：原資料の事実、判断、未確認事項を混ぜない。推測は推測として書く。
- **ページは主題単位**：1メモごとに機械的にWikiページを作らない。逆に、カテゴリ全体を1ページに集めた「○○メモの整理」のようなカタログページも作らない。「NFS運用」「PyTorchのCUDA環境構築」のように、主題で括れる範囲を1ページにする。
- **リンク紹介文の羅列にしない**：本文には原資料から抽出した知識 (結論、手順の骨子、判断とその理由) を書く。「XはYのメモである。Zを見る」という紹介文だけで本文を構成しない。
- **統計値を書かない**：件数などの統計は原資料の増減ですぐ古くなるため、本文に書かない。
- **index/changelog更新**：Wiki本文を更新したら、`wiki/index.md` と `wiki/changelog.md` も更新する。

## 対象の決め方

ユーザーが対象ファイルやカテゴリを指定した場合は、その範囲だけ処理する。
指定がない場合は、直近で追加・変更された `sources/**/*.md` を `git status --short` や更新日時から確認する。

`sources/ideas/` のアイデアメモは、未検証の仮説やAI回答による下調べを含むことがあるため、1メモごとに機械的にWiki化しない。
継続テーマ、実装方針、研究テーマとして整理する価値が出たものだけ、`wiki/projects/`、`wiki/research/`、`wiki/tech/` などの既存カテゴリに統合する。
通常の原資料からWikiページを作る場合は、`_template/wiki.md` を使う。

## 手順

### 1. 現状を読む

- 対象の `sources/` メモを読む。
- 関連する既存Wikiページ、`wiki/index.md`、`wiki/changelog.md` を読む。
- 既存ページに統合するか、新規ページを作るかを決める。統合先が複数の主題を抱えて肥大している場合は、そこへ追記し続けず、主題に合う新規ページを作る。肥大したページの分割が必要なら、最後の報告で `wiki-maintenance` の実行を提案する。
- 主題としてまだ書くことが無いメモは、無理にWiki化せず、その旨を報告する。

### 2. Wikiページを作成・更新する

新規ページを作る場合は、`_template/wiki.md` を使う。
ファイル名は内容が分かる短い名前にし、既存のカテゴリ構成に合わせる。
必要なら `wiki/{category}/` を作るが、1ページだけの細かすぎるカテゴリは避ける。

frontmatterは次を基準にする。

```yaml
---
title: "<title>"
aliases: []
category: "<category>"
tags: []
status: draft
sources:
  - "<relative-path-to-sources>/<category>/YYYY-MM-DD_title.md"
related: []
created: "<YYYY-MM-DD>"
updated: "<YYYY-MM-DD>"
---
```

- `title` はページ内容を端的に表す。
- `category` は `wiki/index.md` の主要カテゴリに合わせる。
- `sources` は使った原資料への相対リンクを入れる。`wiki/` 直下のページなら `../sources/...`、`wiki/{category}/` 配下のページなら `../../sources/...` のように、ページ位置からの相対パスにする。
- `related` は既存Wikiページと明確に関連する場合だけ入れる。
- `updated` は実質更新日を入れる。

本文は次の方針で書く。

- 結論、背景、具体、未確認事項を分ける。
- 原資料が英語でも、日本語で整理する。
- 原資料の引用が必要な場合は短くし、基本は要約する。
- 出典のない一般化や断定を避ける。
- 原資料同士が矛盾する場合は、統合せず違いを明示する。

### 3. 関連リンクを張る

更新したWikiページから関連ページへリンクする。
必要なら関連ページ側にもリンクを追加する。
ただし、関連が弱いページへ網羅的にリンクしない。

### 4. indexを更新する

`wiki/index.md` の該当カテゴリにページを追加する。
既存のカテゴリ説明を大きく変えない。
カテゴリを新設する場合は、なぜ既存カテゴリでは足りないかを最後の報告に含める。

### 5. changelogを更新する

`wiki/changelog.md` の先頭に履歴を追記する。
形式は既存の見出しに合わせる。

```markdown
## [YYYY-MM-DD] update | <短い説明>

- `<source>` をもとに `<wiki>` を作成・更新しました。
- `wiki/index.md` にリンクを追加しました。
```

最新の履歴が一番上に来るようにする。

### 6. 検証する

- `oxfmt` で編集したMarkdownを整形する。
- `scripts/check_image_links.py` を実行し、Markdown画像リンクが壊れていないことを確認する。
- `git diff` で `sources/` に意図しない変更がないことを確認する。

## 報告

次を簡潔に報告する。

- 作成・更新したWikiページ
- 使った原資料
- `wiki/index.md` / `wiki/changelog.md` の更新有無
- 新設カテゴリがあればその理由
- 検証結果
