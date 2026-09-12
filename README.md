# Business AI Recipes #1: Evidence-First Meeting Tasks

[![Verify](https://github.com/jokv213/business-ai-recipes/actions/workflows/verify.yml/badge.svg)](https://github.com/jokv213/business-ai-recipes/actions/workflows/verify.yml)

作者: **Naoya / jokv213**

議事録から出典付きタスク案を作り、人が確認した根拠行だけをローカルの模擬タスクDBへ重複なく登録する、最小の実行例です。標準ライブラリだけで動き、実行時にモデル、外部リポジトリ、タスク管理サービス、ネットワークへアクセスしません。

AIが議事録中の「見送り」「未決定」「第三者メールの引用」を実行指示として扱う事故を、入力境界と再検証でどう減らすかをコードで確認できます。完成済みのSaaSではなく、業務AIへ組み込む前に信頼境界を議論・検証するためのrecipeです。

`fixtures/selected_model_output.json` は選定済み出力を固定した**合成fixture**で、実行時のモデル呼び出しではありません。`SYNTHETIC_ONLY_NOT_PRODUCTION` と記載された値は、本番データ、導入実績、実利用者の成功率、費用削減額を表しません。

## 検証範囲

- `fixtures/human_review.json` は、呼び出し元がモデル出力とは別に渡すレビュー入力の合成例です。この例では L2 と L3 だけを人が実行対象として確認した、という境界を表します。これは実在の人がレビューした証拠ではありません。
- L4（見送り）、L5（第三者メール内の引用）、L6（未決定）はこのレビュー入力に含まれないため、タイトルと引用が一致するschema準拠提案でも候補になりません。拒否理由は固定文言の検出ではなく、根拠行IDが別入力の確認リストにないことです。
- L3の担当と期限は不明なので `null` のままです。
- 合成データによるローカル模擬では、初回は2件、同一入力の再実行は0件、保存合計は2件を確認します。`external_write` は `false` です。

これは構造とローカル処理の検証に限られます。議事録の意味、承認者の本人性、レビュー入力の作成経路をパッケージが証明するものではありません。問い合わせ先、導入実績、利用者数、商用条件は掲載していません。

## 実行方法

必要なのは Python 3.11 以上です。追加のPythonパッケージはありません。

```bash
cd public-package
python3 run_demo.py
python3 verify.py
```

両CLIは同梱の合成fixtureだけを使い、任意のモデル出力やレビュー入力を受け取りません。`run_demo.py` は一時ディレクトリ内のSQLite DBへ模擬登録して、実行後にDBを削除します。`verify.py` は同じ入力契約の拒否条件も検査します。別の一時ディレクトリへこのフォルダだけをコピーして再現できます。

実行結果は次の条件を満たします。

```text
first_run.inserted=2
repeat_run.inserted=0
repeat_run.total_stored=2
external_write=False
```

試して動かなかった点、実運用へ移す際に不足する境界、次に見たい業務例があれば、[Issue](https://github.com/jokv213/business-ai-recipes/issues)へ再現条件と一緒に残してください。

## API入力契約と信頼境界

アプリから利用する場合、`prepare()` には議事録、モデル出力、人が確認した実行対象の根拠行を**別々の入力**として渡します。

```python
transcript = read_json("synthetic_meeting.json")
model_output = read_json("selected_model_output.json")
human_review = read_json("human_review.json")

plan = prepare(transcript, model_output, human_review=human_review)
approval = approve(plan, "local-operator", human_review=human_review)
result = apply_local(plan, approval, "tasks.sqlite3", human_review=human_review)
```

レビュー入力は次のschemaです（`source_hash` は `recipe.digest(transcript)` が返すSHA-256値です）。

```json
{
  "schema_version": 1,
  "meeting_id": "synthetic-luna-launch-20260910",
  "source_hash": "5c3383e686e67462466c0c7896e336cdd68fc8e757891dd8719664e6e548d86e",
  "human_confirmed_action_line_ids": ["L2", "L3"]
}
```

レビュー入力が欠落・不正、会議IDやsource hashが不一致、根拠行IDが未知または重複、提案の根拠に未確認行が含まれる場合は `Refused` で停止します。提案の全根拠行が確認リストに含まれる必要があります。モデル出力に `human_review` や信頼ラベルを追加しても、厳密なschema検査で拒否されます。`validate_plan()`、`approve()`、`apply_local()` も同じレビュー入力を別途要求してplanと照合するため、plan内の値だけでレビュー範囲を昇格できません。

ただし、このデータ形式は署名でも本人確認でもありません。パッケージはレビュー入力が本当に人から来たかを判定できません。実利用側は、モデルが書き換えられない独立した人間向け画面・手順からレビュー値を集め、対象の会議と根拠行の前後文脈を人が確認してください。`approve()` のactor文字列もローカル模擬用で、認証された承認者を表しません。

この境界は一般的なprompt injectionを完全には防止しません。コードは引用、見送り、否定、未決定などの意味を自動判定せず、確認済み行に含まれる指示的な文章も検知しきれません。人による行の選定と、ローカル模擬の最終承認を省略しないでください。

## 同梱ファイル

```text
README.md
LICENSE
recipe.py
run_demo.py
verify.py
fixtures/synthetic_meeting.json
fixtures/selected_model_output.json
fixtures/human_review.json
```

コードと合成fixtureは MIT License で公開しています。
