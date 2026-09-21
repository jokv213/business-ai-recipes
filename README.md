# Business AI Recipes

[![Verify](https://github.com/jokv213/business-ai-recipes/actions/workflows/verify.yml/badge.svg)](https://github.com/jokv213/business-ai-recipes/actions/workflows/verify.yml)

作者: **Naoya / jokv213**

## Recipe #1: Evidence-First Meeting Tasks

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

必要なのは Python 3.11 以上です。追加のPythonパッケージはありません。cloneまたはZIP展開後、このREADMEと `recipe.py` があるリポジトリ直下で実行します。

```bash
python3 -B run_demo.py
python3 -B verify.py
python3 -B recipes/meeting-line-judgment/recipe.py
```

両CLIとline recipeは同梱の合成fixtureだけを使い、任意のモデル出力やレビュー入力を受け取りません。`run_demo.py` は一時ディレクトリ内のSQLite DBへ模擬登録して、実行後にDBを削除します。`verify.py` は同じ入力契約の拒否条件に加え、行判定のreview移行、キーなしlive拒否、ネットワーク境界のテストを検査します。別の一時ディレクトリへこのフォルダだけをコピーして再現できます。

実行結果は次の条件を満たします。

```text
first_run.inserted=2
repeat_run.inserted=0
repeat_run.total_stored=2
external_write=False
line_judgment.action_candidate_count=1
line_judgment.review_count=5
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

## Recipe #2: Jev Meeting Line Judgment

`recipes/meeting-line-judgment/recipe.py` は、同梱の合成議事録6行を `action_candidate` / `decision` / `quote_or_context` / `undecided` に分け、実行候補以外、曖昧、確信度不足、引用・文脈、未決定を `review` へ送る公開candidateです。候補も自動承認・自動タスク登録はせず、全候補に人間確認を要求します。

この候補の同梱fixtureは、2026-09-19作成の**手書き・記録済み合成fixture**で、`live_api_call=false`、`record_origin=hand_authored_synthetic_fixture_not_api_observation` と明示しています。fixtureのモデル欄 `jev-1.13.0` は対象契約であり、fixture自体はlive観測、実測精度、実利用結果を示しません。既存の問い合わせ分類16件の2026-09-19ライブ実測を、この議事録行判定のfixtureへ流用していません。

親側の公開前境界測定では、2026-09-21 18:02:18 JSTに同梱の合成6行だけをJevへ6回送信し、6/6回成功、1行をaction candidate、5行をreviewへ送った。壁時計は3,957.8msで、provider本文は保存していない。input token数と費用はrecipe境界で返さないため未測定であり、この小標本は一般精度、実利用、費用の証拠ではない。候補は引き続き人間確認前提で、自動承認・タスク登録・返信は行わない。

暫定ゲートは選択確率 `0.85` 以上かつconfidence `0.65` 以上です。fixtureでは1行が `action_candidate` 候補、5行が `review` になります。`decision`、`quote_or_context`、`undecided`、曖昧フラグ付き行、確率・confidence不足はreviewです。日付・担当者・数値の抽出・検証・保存はこのrecipeの責務外で、Jevへ委ねません。

オフライン再現:

```bash
python3 -B recipes/meeting-line-judgment/recipe.py
```

任意の `--live` は、`TYPESAFE_API_KEY` を明示したときだけ、TypeSafe直通のJev `jev-1.13.0` へ同梱の合成6行を送ります。Keychainは使わず、キー、認証ヘッダー、provider本文を出力・保存しません。返信、承認、タスク登録、その他の業務外部writeは行わず、キーなしでは拒否します。workerの検証ではライブ経路を実行していません。

失敗条件は、固定4クラス以外、選択確率またはconfidenceが閾値未満、曖昧フラグ、会議ID/source hash/行ID/Choice分布/モデル名の不一致、非合成またはliveと偽装されたfixtureです。引用・背景・見送り・未決定を意味的に完全判定できること、日本語の一般精度、実顧客データでの安全性、確率校正、プロンプトインジェクション耐性、費用、継続利用、公開後の反応は未検証です。小標本の成功を実績や一般精度と扱わず、高confidenceの誤判定も人間確認で止めます。

## Recipe #3: CSV-to-Checked-Report

合成CSVの行数・欠損・不正値・重複ID・合計を決定的に集計し、説明文内の数値が計算結果と一致するか検算します。実行時にAIや外部APIは呼びません。集計ルールと失敗例は[recipe README](recipes/csv-to-report/README.md)を参照してください。

リポジトリ直下から実行します。

```bash
python3 -B recipes/csv-to-report/report.py \
  --csv recipes/csv-to-report/sales.csv
```

合成入力は4行で、金額有効3行・欠損1件・合計4,500円です。欠損があるため `REVIEW_REQUIRED` となり、利用前に元CSVを人が確認します。空入力、重複、欠損と不正文字列の組み合わせも同じ公開検証で確認します。

## Recipe #4: Jev Support Triage

日本語中心の合成問い合わせ16件を、記録済みfixtureに固定したTypeSafe Jev `jev-1.13.0` のChoice応答から担当候補または `review` へ再分類するrecipeです。オフライン経路はキー不要・ネットワーク不要で、実測回答を無意味に再送しません。詳細は[recipe README](recipes/jev-support-triage/README.md)を参照してください。

事前ラベルは明確な11件（単一担当10件、対象外1件）とレビュー対象5件です。2026-09-19 14:00 JSTの記録済み実測は16件すべてHTTP 200、単一担当10件の一致10・誤自動判定0、対象外1件とレビュー対象5件をレビュー送りでした。これは合成小標本の観測値であり、一般的な日本語精度・確率校正・実運用成果・誘導文耐性を示しません。

暫定ゲートは選択確率 `0.85` 以上かつconfidence `0.65` 以上、`other` は常にレビューです。`python3 -B recipes/jev-support-triage/triage.py --offline` で `network_calls=0` と `external_write=false` を確認できます。任意の `--live` は同梱合成fixtureだけを、環境変数 `TYPESAFE_API_KEY` でTypeSafe直通へ送る経路ですが、この公開候補・CI・通常手順では実行していません。返信や外部writeは行いません。

## Recipe #5: Jev CSV Exception Routing

既存のCSV決定的検査が返す `data_row` と `flags` に添えた合成説明文24件を、固定キーワード基準線と記録済みJev Choiceで担当候補または `review` へ仕分けます。金額・件数・欠損・不正値・重複IDの判定はPython側に残し、Jevの出力だけで修正、送信、承認はしません。詳細は[recipe README](recipes/jev-csv-exception-routing/README.md)を参照してください。

今回の同一fixture比較は、基準線が自動候補15・review/保留9・分類不能4・誤自動3、記録済みJevが自動候補11・review/保留13・分類不能1・誤自動0でした。基準線に危険な誤自動が3件あるため、結果は `DO_NOT_RECOMMEND_AUTO_ROUTING` です。これは24件の合成fixture内の観測であり、実際のprovider観測、token・費用、実顧客データの精度、導入成果を示しません。

```bash
python3 -B recipes/jev-csv-exception-routing/route.py --offline
```

このrecipeにはlive provider経路がありません。`recorded-answers.json` は `jev-1.13.0` のChoice形式を模した合成記録で、`observed_at=null`、provider call 0、network call 0、external write `false` です。

## 同梱ファイル

```text
.github/workflows/verify.yml
.gitignore
AGENTS.md
README.md
LICENSE
recipe.py
run_demo.py
verify.py
fixtures/synthetic_meeting.json
fixtures/selected_model_output.json
fixtures/human_review.json
fixtures/meeting_line_judgment.json
recipes/meeting-line-judgment/README.md
recipes/meeting-line-judgment/recipe.py
recipes/csv-to-report/README.md
recipes/csv-to-report/report.py
recipes/csv-to-report/sales.csv
recipes/csv-to-report/examples/empty.csv
recipes/csv-to-report/examples/duplicate.csv
recipes/csv-to-report/examples/mixed-strings.csv
recipes/jev-support-triage/README.md
recipes/jev-support-triage/cases.json
recipes/jev-support-triage/observed-answers.json
recipes/jev-support-triage/triage.py
recipes/jev-csv-exception-routing/README.md
recipes/jev-csv-exception-routing/cases.json
recipes/jev-csv-exception-routing/recorded-answers.json
recipes/jev-csv-exception-routing/route.py
```

コードと合成fixtureは MIT License で公開しています。
