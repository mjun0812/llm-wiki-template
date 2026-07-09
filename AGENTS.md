# AGENTS.md

## ディレクトリ構造

- `inbox/` — 未処理メモの投入箱。LLMがここから `sources/` へ取り込む。
- `sources/` — 原資料。原則として内容を書き換えない。カテゴリ別のサブディレクトリに分かれるが、構成は固定ではなく新規メモに応じて見直してよい。
- `wiki/` — LLMが整形・統合して維持する知識ベース。`index.md` で索引、`changelog.md` で取り込み履歴を管理する。
- `_template/` — Markdownのテンプレート (`source.md` / `wiki.md`)。
- `scripts/` — 検証スクリプト (`check_sources.py` / `check_image_links.py`)。
- `.agents/skills/` — local skill (`inbox-to-sources` など)。

## 基本方針

- 常に日本語で作業する。
- 英語の原資料も、`wiki/` では日本語で整理、要約、索引化する。
- 英語の原資料を `sources/` に保存する場合は、原文をなるべく維持し、翻訳で置き換えない。
- `sources/` のカテゴリは出所ではなく内容 (トピック) で決める。AI回答による下調べもトピック別カテゴリに置き、frontmatter の `model` で出所を区別する。AI回答は未検証の調査メモとして扱う。
- 特定トピックに収まらないアイデア・仮説は `sources/ideas/` に保存する。
- 取り込み時は `wiki/index.md` と `wiki/changelog.md` を更新する。
- `wiki/changelog.md` は最新の履歴が一番上に来るように追記する。
- 新規Markdownを作る場合は、用途に合う `_template/` 以下のテンプレートを使う。
- ユーザーが与えたテーマを調べて調査メモを作るときは、local skill の `research-to-inbox` を必ず使う。メモは `inbox/` に保存し、以降は通常のinbox処理に乗せる。
- `inbox/` から `sources/` へメモを取り込むときは、local skill の `inbox-to-sources` を必ず使う。ファイル名規約 (`YYYY-MM-DD_slug.md`)、frontmatter整備、`scripts/check_sources.py` での検証はそこに集約してある。
- `sources/` から `wiki/` を更新するときは、local skill の `source-to-wiki` を必ず使う。原資料は編集せず、Wiki本文、関連リンク、`wiki/index.md`、`wiki/changelog.md` の更新に集中する。
- `wiki/` 以下の本文を作成・更新する場合は、local skillの `japanese-tech-writing` と `stop-ai-slop-jp` を使い、日本語文書として読みやすく、AI臭の少ない文章に整える。
- このリポジトリの元になったtemplate repoの更新を取り込むときは、local skill の `template-sync` を必ず使う。更新の提示と選択、ファイル単位の適用はそこに集約してある。
- Markdown内の画像リンク (`![alt](path)`) は、原則として **そのMarkdownファイルからの相対パス** で記述する。リポジトリのclone先やマウントパスに依存せず、GitHubやエディタプレビューで一貫して解決できるようにするため。外部画像は絶対URLで指定してよい。

## メモの検索

1. まず `rg -t md` でMarkdownファイルを全文検索する。`sources/` には英語の原資料がそのまま残っているため、日本語と英語の両方のキーワードで検索する。
2. 検索対象は目的で使い分ける。整理済みの知識は `wiki/`、詳細や原文は `sources/`、未処理メモは `inbox/`。例: `rg -t md 'キーワード' wiki/ sources/`
3. キーワードで見つからないときは `wiki/index.md` から主題ページをたどる。
4. 時期が分かっている場合は、`sources/` のファイル名規約 (`YYYY-MM-DD_slug.md`) を使って `ls sources/*/2026-07-*` のように絞り込める。

`rg` の具体的なオプション例は README の「検索 Cheet Sheet」を参照。

## Wikiの品質方針

- Wikiページは主題単位で作る。「1カテゴリ = 1ページ」の巨大なまとめページや、「○○メモの整理」のようなカタログページは作らない。
- 本文には原資料から抽出した知識 (結論、手順の骨子、判断とその理由) を書く。原資料へのリンク紹介文を並べるだけの本文にしない。具体的な設定値や長い手順は原資料リンクに逃がす。
- 原資料に書かれていない一般論や助言を本文に足さない。
- 件数などの統計値を本文に書かない。原資料の増減ですぐ古くなる。
- 主題として書くことがまだ無いメモは、無理にWiki化しない。ページを作るのは、複数メモの統合や横断整理に価値が出てからでよい。

## テンプレート運用

- 通常のWikiページを作る場合は `_template/wiki.md` を使う。
- `sources/` 以下に原資料を保存する場合は `_template/source.md` を使う (取り込みは `inbox-to-sources` skill が担う)。
- `updated` はファイルを実質的に更新した日付に合わせる。

## inbox処理

1. `inbox-to-sources` skill で `inbox/` のメモを `sources/{category}/` に取り込む。ファイル名規約、frontmatter整備、検証スクリプトの実行はskill側で完結する。skill実行後は `inbox/` 直下に `.md` が残らない。
2. 内容を整理して `wiki/` の適切なページを作成・更新する。
3. 関連する既存ページへリンクを追加する。
4. `wiki/index.md` を更新する。
5. `wiki/changelog.md` の先頭に処理履歴を追記する。
