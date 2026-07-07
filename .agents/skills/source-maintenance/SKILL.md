---
name: source-maintenance
description: sources/ 配下の既存原資料を点検し、本文を変えずに配置、ファイル名、画像の相対関係、frontmatter のテンプレート準拠を確認・修正するSkill。ユーザーが「sourcesを点検して」「sourcesを整理して」「原資料を整備して」「source-maintenanceして」のように依頼したら使うこと。inbox/ からの新規取り込みは inbox-to-sources を、wiki/ 側の整理は wiki-maintenance を使う。本文の要約・推敲は対象外。
---

# source-maintenance

`sources/` 配下の既存原資料を保守する。
新規取り込みではなく、すでに `sources/` にあるファイルの配置、ファイル名、frontmatter、画像配置を点検・修正する。

最初に `sources/` 配下を確認し、`.md` が1件も無ければ「点検対象がない」と報告して終了する。
`--dry-run` が指定された場合は、scriptを `--fix` なしで実行し、手順3までの点検結果 (診断一覧と移動・修正の予定) を提示して終了する。ファイルの移動・編集は一切行わない。

## ルール

- **本文編集禁止**：編集できるのはfrontmatterブロックだけ。frontmatter以降の本文、引用、リンク、画像パス、コードブロックは1バイトも書き換えない。
- **移動は `git mv`**：Markdownや画像を動かす場合は履歴を保つため `git mv` を使う。
- **画像の相対パス維持**：本文が `images/foo.png` を参照しているなら、移動後も同じ相対関係で参照できる場所に置く。本文中の画像パスは書き換えない。
- **分解・統合禁止**：1つのメモを分割しない。複数メモを1ファイルへ統合しない。
- **取り込み禁止**：`inbox/` からの移動は `inbox-to-sources` の範囲であり、このSkillでは新規取り込みを行わない。
- **wiki更新禁止**：`wiki/` 配下のページは更新しない。

## 対象

- 原資料：`sources/{category}/YYYY-MM-DD_title.md`
- 画像：各カテゴリ内の `images/`

## 手順

### 1. 検証scriptでファイルの不備を修正する

最初にscriptでfrontmatter、ファイル名、配置の機械的な不整合を出す。

原資料は `scripts/check_sources.py` の診断に従う。

```sh
python scripts/check_sources.py
python scripts/check_image_links.py --fix ./sources
```

scriptの診断結果を見て、sources/ 配下のファイルを点検・修正する。
修正対象は、欠落している必須key、空値、ファイル名と `title` / `created` の不一致、日付形式、frontmatter区切りの破損に絞る。
余分なfrontmatter keyは原則として残す。
画像のリンク切れがあった場合は、repo全体から画像を探し、相対パスを維持できる場所に移動する。
画像が見つからない場合は、リンク切れのまま報告する。

### 2. 現状を読む

`sources/` 直下のディレクトリ構造やカテゴリ、診断対象のMarkdown、画像ディレクトリを確認する。
必要なら対象ファイルのfrontmatterと本文冒頭だけを読み、テーマ、ファイル名、画像参照を把握する。

### 3. 配置を点検する

必ずすべてのファイルの概要を把握する。
ファイル数が多い場合は、ディレクトリごとに点検し、移動先のカテゴリやトピックを決める。

原資料は `sources/{category}/YYYY-MM-DD_title.md` に置く。

配置を見直す基準:

- 既存カテゴリや既存トピックに素直に収まるなら新設しない。
- 1ファイルしか入らないカテゴリを濫造しない。
- `misc/`, `others`, `uncategorized` のような無情報カテゴリは作らない。
- カテゴリは出所ではなく内容 (トピック) で決める。AI回答による下調べや未検証の調査メモも、明確なトピックがあれば該当カテゴリに置く。
- 特定トピックに収まらないアイデア・仮説は `sources/ideas/` に寄せる。

移動する場合は、関連画像も同じ相対関係を保てる場所へ `git mv` する。

### 4. 再検証する

修正後に同じscriptを再実行する。

```sh
python scripts/check_sources.py
```

エラーが出た場合は該当ファイルだけを直し、修正対象の診断が消えるまで繰り返す。
余分なfrontmatter keyだけの診断は、削除せず報告する。

### 5. 報告する

次を簡潔に報告する。

- 点検または修正した範囲
- 移動したファイルと移動理由
- frontmatter修正件数
- 検証結果
- 大きな再編候補や重複候補があれば、その候補
