---
name: source-to-html
description: sources/ の原資料と wiki/ の確定した結論を読み、リッチ表現のHTML版wikiページを html/ に生成するSkill。ユーザーが「このテーマをHTML化して」「html wikiを作って」「source-to-htmlして」のように対象を指定して依頼したときだけ使うこと。Markdown側 (sources/ wiki/) の編集は対象外で、HTMLページの生成、html/index.html と wiki/changelog.md の更新だけを行う。既存HTMLページの点検・再生成・削除は html-maintenance を使う。
---

# source-to-html

`sources/` の原資料と関連する `wiki/` ページを読み、リッチ表現のHTMLページを `html/` に生成する。
Markdown側の編集、既存HTMLページの保守はこのSkillの範囲外。

最初に対象を確認し、ユーザーがテーマや対象ページを指定していなければ、対象を確認して終了する。ユーザーの指定なしに生成するページを自分で選ばない。
`--dry-run` が指定された場合は、手順1〜2 (対象確認と構成決定) だけを行い、生成予定のページ構成を提示して終了する。ファイルの作成・編集は一切行わない。

## ルール

- **知識の正本は常にMarkdown**：新しい知識・主張・結論をHTMLに直接書かない。統合的な結論・判断は `wiki/` の記述に従い、矛盾させない。`wiki/` にまだ無い結論が必要になったら、先に `source-to-wiki` でwiki側を更新するよう報告する。
- **転記と表現はHTMLの自由**：`sources/` からの詳細な転記・要約と、視覚的な再構成 (カード、画像の横並び、表、折りたたみ) はHTML側の役割。`wiki/` のページ分けに縛られなくてよい。複数wikiページの統合も、1主題の掘り下げもできる。
- **Markdown側は読むだけ**：`sources/` と `wiki/` 本文を変更しない。更新するのは `html/` 配下、`wiki/changelog.md` のみ。
- **テンプレート必須**：ページは `_template/wiki-page.html` から作る。CSSは `assets/style.css` だけを参照し、style属性の直書きは最小限にする。
- **JSなし・外部参照なし**：script・iframeは使わない。インタラクティブ表現はHTML標準要素 (`details` の折りたたみなど) で行う。画像を含むリソースはrepo内の相対パスで参照する。
- **由来metaを必ず宣言する**：内容の根拠にしたすべての `sources/` `wiki/` のMarkdownを `<meta name="wiki-source" content="<repo相対パス> <そのファイルのfrontmatter updated>">` で1件ずつ宣言する。読んだが使わなかったファイルは含めない。
- **手修正しない前提で作る**：生成後のHTMLは編集せず、更新はページ丸ごと再生成する (`html-maintenance` の範囲)。
- **日本語で書く**：原資料が英語でも本文は日本語にする。

## 手順

### 1. 対象を確認する

ユーザーが指定したテーマ・ページについて、根拠になる `sources/` のメモと、関連する `wiki/` ページ、`wiki/index.md` を読む。
`html/index.html` があれば読み、既存ページとの重複を確認する。

### 2. 構成を決める

Markdownでは表現しにくい形 (比較のカード化、画像の横並び、手順の折りたたみ) が活きる構成に組み直す。
テキストを流し込むだけならHTML化する価値が薄いため、その場合は生成を勧めない理由を報告して終了してよい。

### 3. ページを生成する

`_template/wiki-page.html` を元に `html/<slug>.html` を作る。slugは内容が分かる短いkebab-caseにする。

- プレースホルダー (`{{...}}`) をすべて展開する。
- ヘッダーの provenance には生成日と正本への相対リンクを入れる。
- 由来metaには根拠にした全Markdownを宣言する。`updated` が無いファイルは `created` を使う。
- フッターの「正本・参照元」に、由来metaと同じファイルへの相対リンクを列挙する。リンクテキストのアンダースコアはスペースに置き換える。
- 共通CSSのコンポーネント (`.card-grid` / `.figure-row` / `.callout` / `.badge` / `details`) を優先して使う。

### 4. 索引を更新する

`html/index.html` を作成・更新し、全ページへのリンク一覧を維持する。
索引も `_template/wiki-page.html` を元にするが、由来metaは不要 (検証も免除される)。

### 5. changelogを更新する

`wiki/changelog.md` の先頭に履歴を追記する。

```markdown
## [YYYY-MM-DD] html | <短い説明>

- `<sources/wiki>` をもとに `html/<slug>.html` を生成しました。
```

### 6. 検証する

- `python3 scripts/check_html.py` を実行し、エラーが無いことを確認する。
- `git diff` で `sources/` と `wiki/` (changelog以外) に変更がないことを確認する。
- ユーザーにブラウザでの表示確認 (`open html/<slug>.html`) を促す。

## 報告

次を簡潔に報告する。

- 生成したページと、その根拠にした `sources/` / `wiki/` ファイル
- `html/index.html` / `wiki/changelog.md` の更新有無
- 検証結果と、表示確認用のコマンド
- wiki側に先に書くべき結論が見つかった場合は、`source-to-wiki` の実行提案
