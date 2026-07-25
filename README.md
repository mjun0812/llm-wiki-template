# llm-wiki-template

メモの整理とwiki化をLLM (Claude Codeなどのcoding agent) に任せるリポジトリのテンプレート。
人間は雑にメモを置くだけで、原資料の整備と知識ベースの維持はLLMが行う。

## 基本運用

1. 人間は `inbox/` に雑にメモを置く。
2. LLMが `inbox-to-sources` skill で `sources/{category}/` に原資料を移す。
3. LLMが `source-to-wiki` skill で `wiki/` を更新する。
4. LLMが `wiki/index.md` と `wiki/changelog.md` を更新する。
5. 人間が対象を指定したときだけ、LLMが `source-to-html` skill で `html/` にリッチ表現のHTML版wikiページを生成する。

`sources/` は原資料層としてfrontmatter以外の編集を禁止し、整理と要約はすべて `wiki/` 側で行う。
運用ルールの詳細は `AGENTS.md` を参照。

## Structure

- `inbox/` — 未処理メモの投入箱
- `sources/` — 原資料。カテゴリ別サブディレクトリに `YYYY-MM-DD_slug.md` で保存
- `wiki/` — LLMが維持する知識ベース (`index.md` で索引、`changelog.md` で履歴)
- `html/` — LLMが生成するHTML版wiki。ローカルでブラウザ表示する前提で、知識の正本はMarkdown側
- `_template/` — テンプレート (`source.md` / `wiki.md` / `wiki-page.html`)
- `scripts/` — 検証スクリプト
- `.agents/skills/` — local skill

## Skills

- `research-to-inbox` — 与えたテーマをdeep researchして調査メモをinboxに作る
- `inbox-to-sources` — inboxのメモをsourcesへ取り込む
- `source-to-wiki` — sourcesの原資料からwikiを更新する
- `source-to-html` — sourcesとwikiからリッチ表現のHTML版wikiページを生成する
- `wiki-maintenance` — 既存wikiの整理、統合、推敲
- `html-maintenance` — 既存HTMLページの陳腐化検出、再生成、索引整理
- `source-maintenance` — sources配下の配置とfrontmatterの点検
- `japanese-tech-writing` / `stop-ai-slop-jp` — wiki本文の文章規範

## Scripts

検証スクリプトは `scripts/` 以下に配置する。

- `check_sources.py`
  - 対象: `sources/**/*.md`
  - 概要: `sources/` 以下のMarkdownが `_template/source.md` のfrontmatterとファイル名規約を満たしているか検査する。
  - メモ: `model` はLLM生成元を残すための任意frontmatterとして保持できる。
  - 自動修正: なし
- `check_image_links.py`
  - 対象: 既定では `sources/**/*.md`
  - 概要: Markdown画像リンクとObsidian画像リンクのうち、ローカル画像ファイルを指すリンク先が存在するか、URLエンコードやスペースを含まない正規化済みのパスになっているかを検査する。外部URLや画像以外のリンクは対象外。
  - 自動修正: `--fix` でローカル画像リンクをURLデコードし、リンクと画像ファイル名のスペースをアンダースコアに置換し、それでも存在しない画像リンクを削除
- `check_wiki_links.py`
  - 対象: 既定では `wiki/**/*.md`
  - 概要: Wikiページが `wiki/index.md` からリンクされているか、ローカルリンクの参照先が存在するか、リンクテキストがファイル名由来の強調に化けていないかを検査する。画像リンクは `check_image_links.py` が担当するため対象外。
  - メモ: `--check-unreferenced` を付けると、どのWikiページからも参照されていない `sources/` のメモを報告する。原資料の一覧ページを置いて全メモを網羅する運用のときだけ使う。
  - 自動修正: なし
- `check_html.py`
  - 対象: 既定では `html/**/*.html`
  - 概要: HTML版wikiページがテンプレート規約を満たしているか検査する。外部リソース参照・script・iframeの禁止、共通CSSのみの参照、由来meta (`wiki-source`) の宣言、ローカルリンクの存在を確認する。由来metaと参照先Markdownの `updated` がずれた陳腐化は警告として報告し、commitはブロックしない。
  - メモ: `html/index.html` は由来metaの宣言を免除される。
  - 自動修正: なし

各スクリプトは、引数なしでは既定の対象を検査する。
ファイルまたはディレクトリを引数に渡すと、その範囲だけを検査する。

### Lintルール

| コード    | スクリプト             | ルール                      | 内容                                                                                          |
| --------- | ---------------------- | --------------------------- | --------------------------------------------------------------------------------------------- |
| `SRC001`  | `check_sources.py`     | `missing-frontmatter`       | frontmatterが `---` で始まっていない。                                                        |
| `SRC002`  | `check_sources.py`     | `unterminated-frontmatter`  | frontmatterの終了区切り `---` がない。                                                        |
| `SRC003`  | `check_sources.py`     | `missing-required-key`      | `_template/source.md` にある必須キーがない。                                                  |
| `SRC004`  | `check_sources.py`     | `empty-frontmatter-value`   | 検査対象frontmatterキーの値が空になっている。                                                 |
| `SRC005`  | `check_sources.py`     | `unexpanded-placeholder`    | `{{...}}` 形式のテンプレート値が残っている。                                                  |
| `SRC006`  | `check_sources.py`     | `invalid-filename`          | ファイル名が `YYYY-MM-DD_slug.md` 形式ではない。                                              |
| `SRC007`  | `check_sources.py`     | `created-mismatch`          | ファイル名の日付とfrontmatterの `created` が一致していない。                                  |
| `IMG001`  | `check_image_links.py` | `missing-image`             | ローカル画像リンクの参照先ファイルが存在しない。                                              |
| `IMG002`  | `check_image_links.py` | `noncanonical-image-target` | ローカル画像リンクがURLエンコードされている、またはスペースを含んでいる。                     |
| `WIKI001` | `check_wiki_links.py`  | `unindexed-page`            | Wikiページが `wiki/index.md` からリンクされていない。                                         |
| `WIKI002` | `check_wiki_links.py`  | `missing-link-target`       | ローカルリンクの参照先ファイルが存在しない。                                                  |
| `WIKI003` | `check_wiki_links.py`  | `emphasized-link-label`     | リンクテキストにファイル名のアンダースコアが残り、強調として解釈されている。                  |
| `WIKI004` | `check_wiki_links.py`  | `unreferenced-source`       | `sources/` のメモがどのWikiページからも参照されていない (`--check-unreferenced` 指定時のみ)。 |
| `HTML001` | `check_html.py`        | `external-resource`         | CSS・画像などのリソースを外部URLから読み込んでいる (`a` の外部リンクは対象外)。               |
| `HTML002` | `check_html.py`        | `script-forbidden`          | scriptタグを使用している。                                                                    |
| `HTML003` | `check_html.py`        | `iframe-forbidden`          | iframeタグを使用している。                                                                    |
| `HTML004` | `check_html.py`        | `stylesheet-mismatch`       | stylesheetが共通CSS (`html/assets/style.css`) 1つになっていない。                             |
| `HTML005` | `check_html.py`        | `missing-wiki-source`       | 由来meta (`wiki-source`) が無い、または形式が不正 (`html/index.html` は免除)。                |
| `HTML006` | `check_html.py`        | `missing-link-target`       | ローカルリンクまたは由来metaの参照先ファイルが存在しない。                                    |
| `HTML007` | `check_html.py`        | `unexpanded-placeholder`    | `{{...}}` 形式のテンプレート値が残っている。                                                  |
| `HTML008` | `check_html.py`        | `stale-page`                | 由来metaの `updated` が参照先Markdownの現在値と異なる (警告のみ、commitはブロックしない)。    |

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
python3 scripts/check_wiki_links.py
python3 scripts/check_html.py
```

MarkdownのフォーマットにはoxfmtをPre-commit hookで使用する。
oxfmtはリンクテキスト内のアンダースコアを強調記号として解釈するため、原資料へのリンクを書くときはファイル名をそのまま貼らない。
崩れは `check_wiki_links.py` の `WIKI003` で検出できる。

## 検索 Cheet Sheet

| コマンド                           | 用途                                                    |
| ---------------------------------- | ------------------------------------------------------- |
| `rg 'キーワード'`                  | repo全体を検索する                                      |
| `rg -t md 'キーワード'`            | Markdownファイルだけを検索する                          |
| `rg 'キーワード' wiki/ sources/`   | ディレクトリを絞って検索する                            |
| `rg -g '!archive/**' 'キーワード'` | `archive/` を除外して検索する                           |
| `rg -i 'llm wiki'`                 | 大文字小文字を無視して検索する                          |
| `rg -F '[1]'`                      | 正規表現ではなく固定文字列として検索する (引用番号など) |
| `rg -l 'キーワード'`               | ヒットしたファイル名だけを表示する                      |
| `rg -C 2 'キーワード'`             | ヒット行の前後2行も表示する                             |
| `rg -c 'キーワード'`               | ファイルごとのヒット件数を表示する                      |
