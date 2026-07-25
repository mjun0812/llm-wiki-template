---
name: html-maintenance
description: html/ 以下の既存HTML版wikiページを点検し、由来metaの比較による陳腐化検出、ページ丸ごとの再生成、不要ページの削除、html/index.html の整理を行うSkill。ユーザーが「html wikiを更新して」「古いhtmlを再生成して」「html-maintenanceして」のように依頼したら使うこと。新規ページの生成は source-to-html を使う。自動では実行せず、ユーザーの依頼があったときだけ動く。
---

# html-maintenance

`html/` 以下の既存ページを点検し、最新のMarkdown (正本) に追随させる。
新規ページの生成は `source-to-html` の範囲。陳腐化ページの再生成も、通常は `source-to-html` の自動実行 (inbox処理) が担う。このSkillは、削除、索引整理、手動での全体点検に使う。

最初に `html/` 配下を確認し、`index.html` 以外のページが1件も無ければ「点検対象がない」と報告して終了する。
`--dry-run` が指定された場合は、手順1〜2 (点検と方針決定) だけを行い、ページごとの方針 (再生成・削除・維持) を提示して終了する。ファイルの作成・編集・削除は一切行わない。

## ルール

- **HTMLは手修正しない**：部分的な編集はせず、更新はページ丸ごとの再生成で行う。再生成は `source-to-html` と同じルール (テンプレート、JSなし、由来meta、日本語) に従う。
- **知識の正本は常にMarkdown**：再生成でも新しい知識・結論を足さない。結論は `wiki/` の現在の記述に従う。
- **Markdown側は読むだけ**：`sources/` と `wiki/` 本文を変更しない。更新するのは `html/` 配下、`wiki/changelog.md` のみ。
- **削除は根拠を確認してから**：由来のMarkdownが削除・統合されて主題が消えたページだけ削除する。削除したら `html/index.html` からもリンクを外す。
- **index/changelog更新**：ページを再生成・削除したら、`html/index.html` と `wiki/changelog.md` も更新する。

## 手順

### 1. 点検する

`python3 scripts/check_html.py` を実行し、次を把握する。

- `HTML008` (警告): 由来metaより参照先Markdownが新しい、陳腐化したページ
- `HTML006`: 由来metaやリンクの参照先が消えているページ
- その他のエラー

あわせて `html/index.html` と実ファイルの一覧を突き合わせ、索引の漏れ・リンク切れを確認する。

### 2. 方針を決める

ページごとに次のどれかを決める。

- **再生成**：陳腐化したページ。由来のMarkdownを読み直し、ページ丸ごと作り直す
- **削除**：由来のMarkdownが無くなり、主題が消えたページ
- **維持**：警告・エラーが無いページ

### 3. 再生成する

由来metaに列挙されたMarkdownと、関連する `wiki/` の現在の内容を読み直し、`_template/wiki-page.html` を元にページを作り直す。

- 由来metaの `updated` を各ファイルの現在の値に更新する。
- 構成の見直し (使うコンポーネント、統合するページの範囲) もこの時点で行ってよい。

### 4. 索引を更新する

`html/index.html` を実ファイルの一覧に合わせて更新する。

### 5. changelogを更新する

`wiki/changelog.md` の先頭に履歴を追記する。

```markdown
## [YYYY-MM-DD] html | <短い説明>

- `html/<slug>.html` を再生成・削除しました。
```

### 6. 検証する

- `python3 scripts/check_html.py` を実行し、エラーと `HTML008` 警告が解消されたことを確認する。
- `git diff` で `sources/` と `wiki/` (changelog以外) に変更がないことを確認する。

## 報告

次を簡潔に報告する。

- 再生成・削除・維持としたページとその理由
- `html/index.html` / `wiki/changelog.md` の更新有無
- 検証結果 (残った警告があればその理由)
