---
name: template-sync
description: このリポジトリの元になったtemplate repo (mjun0812/llm-wiki-template) の直近の更新を確認し、どの更新を取り込むかをユーザーに選択させて適用するSkill。ユーザーが「templateの更新を取り込んで」「template repoに追従して」「templateとの差分を確認して」「template-syncして」「upstreamの更新を確認して」のように依頼したら必ずこのSkillを使うこと。inbox/ sources/ wiki/ などのコンテンツ層は対象外で、skillやスクリプトなどtemplate管理ファイルの同期だけを行う。
---

# template-sync

このリポジトリの元になったtemplate (`https://github.com/mjun0812/llm-wiki-template`) の直近の更新を確認し、ユーザーが選んだ更新だけを取り込む。
templateとgit履歴を共有している必要はない。templateをremoteとしてfetchし、template側のcommit・PRを更新単位として提示して、選ばれたファイルの内容をそのまま持ってくる。mergeやcherry-pickはしない。

同期状態は記録しない。毎回templateの直近のcommitを見せて、取り込むものをユーザーに選ばせる。

`--dry-run` が指定された場合は、更新一覧の提示までで終了する。remoteの追加とfetch以外は何も変更しない。

## 不変条件

- **コンテンツ層に触らない**：対象外ファイルは、templateの更新に含まれていても取り込まない。
- **選択されなかった更新は適用しない**：まとめて取り込んだ方が楽でも、ユーザーの選択に従う。
- **コミットしない**：適用はstageまで。コミットはユーザーに委ねる。

## 対象外ファイル

次のパスは自分のリポジトリ側の所有物なので、同期しない。**これ以外はすべて同期対象**。

- `inbox/` `sources/` `wiki/`

## 手順

### 1. 前提確認

次のどれかに該当したら、理由を伝えて終了する。

- `origin` がtemplate本体 (`mjun0812/llm-wiki-template`) を指している。ここはtemplate本体なので取り込むものがない。
- 対象外以外のパスに未コミットの変更がある。適用がstageを使うため、先にコミットか退避を促す。

`template` remoteが無ければ `https://github.com/mjun0812/llm-wiki-template.git` で追加する。既にあればそのURLを尊重する。追加したら `git fetch template` する。

### 2. 更新の収集

`git log --oneline -20 template/main` で直近のcommitを確認する。遡る範囲はユーザーの指定 (「直近10件」「先月以降」など) があればそれに従う。

各commitの変更ファイルを `git show --name-status <sha>` で確認し、対象外パスにしか触れていないcommitは候補から外す。
変更ファイルの現在の内容がすべてtemplate/mainと一致しているcommitも、取り込み済みとして候補から外す (`git diff template/main -- <files>` が空なら一致。削除されたファイルは手元にも無ければ一致扱い)。
候補が1件も残らなければ「取り込む更新がない」と報告して終了する。

### 3. グループ化と提示

commitメッセージ末尾のPR番号 (`(#N)`) やmerge commitを手がかりに、同じPR由来のcommitは1グループにまとめる。単独のcommitは1 commit = 1グループ。

グループ一覧を新しい順の表 (更新内容 / commit・PR / 変更ファイル) で提示する。変更ファイルからは対象外パスを除く。

適用はtemplateの最新内容 (`template/main`) で行うため、同じファイルに触るグループの片方だけを選ぶと、もう片方の変更も一緒に入る。ファイルが重なるグループがある場合は、その旨を表に添える。

### 4. 選択

AskUserQuestion (multiSelect) で取り込むグループを選択させる。選択UIが無い環境では、番号付き一覧を提示して返答で受け取る。
ユーザーが依頼時に対象を指定済みの場合 (「全部取り込んで」「skillの更新だけ」など) は、質問を省略して指定に従う。

### 5. 適用と報告

選択されたグループの変更ファイル (対象外パスを除く) を操作する。

- 追加・変更されたファイル：`git checkout template/main -- <file>`
- 削除されたファイル：自分のリポジトリ側に残っていれば `git rm <file>`
- リネームは削除と追加の組として扱う

いずれもstageまで進む。

最後に次を報告する。

- 取り込んだグループと見送ったグループ
- 変更はstage済みでコミットは未実施であること (コミットメッセージ案を1つ添える)

## 避けること

- templateとのmergeやcherry-pick。履歴を共有している保証がないので事故のもと。
- 対象外パスへの波及。
- 選択を待たずに全部適用する。
- 適用後のcommitやpush。
