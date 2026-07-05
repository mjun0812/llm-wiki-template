# llm-wiki-template

メモの整理とwiki化をLLM (Claude Codeなどのcoding agent) に任せるリポジトリのテンプレート。
人間は雑にメモを置くだけで、原資料の整備と知識ベースの維持はLLMが行う。

## 基本運用

1. 人間は `inbox/` に雑にメモを置く。
2. LLMが `inbox-to-sources` skill で `sources/{category}/` に原資料を移す。
3. LLMが `source-to-wiki` skill で `wiki/` を更新する。
4. LLMが `wiki/index.md` と `wiki/changelog.md` を更新する。

`sources/` は原資料層としてfrontmatter以外の編集を禁止し、整理と要約はすべて `wiki/` 側で行う。
運用ルールの詳細は `AGENTS.md` を参照。

## Structure

- `inbox/` — 未処理メモの投入箱
- `sources/` — 原資料。カテゴリ別サブディレクトリに `YYYY-MM-DD_title.md` で保存
- `wiki/` — LLMが維持する知識ベース (`index.md` で索引、`changelog.md` で履歴)
- `_template/` — Markdownテンプレート (`source.md` / `wiki.md`)
- `scripts/` — 検証スクリプト
- `.agents/skills/` — local skill

## Skills

- `inbox-to-sources` — inboxのメモをsourcesへ取り込む
- `source-to-wiki` — sourcesの原資料からwikiを更新する
- `wiki-maintenance` — 既存wikiの整理、統合、推敲
- `source-maintenance` — sources配下の配置とfrontmatterの点検
- `japanese-tech-writing` / `stop-ai-slop-jp` — wiki本文の文章規範

## Setup

1. このテンプレートから新規リポジトリを作成する。
2. pre-commit hookを導入する。

```sh
pre-commit install
```

検証は次のコマンドでも手動実行できる。

```sh
python3 scripts/check_sources.py
python3 scripts/check_image_links.py
```

MarkdownのフォーマットにはoxfmtをPre-commit hookで使用する。
