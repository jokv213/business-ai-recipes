# Jev meeting-line judgment

このrecipeは、同梱の合成議事録6行と、JevのChoice応答を模した**手書きの記録済み合成fixture**から、議事録行を次の4クラスへ構造化する最小例です。

- `action_candidate`: 実行候補らしい行。ただし候補であり、承認・タスク登録ではない
- `decision`: 決定、見送り、確定した結果
- `quote_or_context`: 引用、背景、会議の前提
- `undecided`: 未決定、保留、曖昧な行

## オフライン再現

このコマンドはネットワーク、モデル、APIキーを使いません。

```bash
python3 -B recipes/meeting-line-judgment/recipe.py
```

2026-09-19に記録したfixtureは `live_api_call=false`、`record_origin=hand_authored_synthetic_fixture_not_api_observation` です。`jev-1.13.0` は判定契約のモデル欄であり、この議事録仮説をJevへライブ送信した実測結果ではありません。従って、このfixtureを実測精度・実利用結果・校正済み確率とは呼びません。

暫定ゲートは選択確率 `0.85` 以上かつconfidence `0.65` 以上です。ゲートを通る `action_candidate` は1行、`decision`・引用/文脈・未決定・曖昧/確信度不足のreview行は5行です。行の判定後も全候補に人間確認が必要で、`external_write=false`、承認・返信・タスク登録は実装していません。

日付、担当者、数値はJevの入力・出力から抽出、検証、保存しません。必要になった場合は、コードの決定的な検証と人間レビューで別途扱います。

## 任意のライブ境界

ライブ経路を明示的に選ぶ場合だけ、TypeSafe直通のJev 1.13.0へ同梱の合成6行を送ります。Keychainは使わず、環境変数だけを読みます。

```bash
TYPESAFE_API_KEY='（値は表示・保存しない）' \
  python3 -B recipes/meeting-line-judgment/recipe.py --live
```

実際のキー、認証ヘッダー、provider本文は出力・保存しません。redirectは追従せず、別ホストへ資格情報を渡しません。応答を検証してメモリ上の判定に使うだけで、返信、承認、タスク登録、その他の業務外部writeは行いません。キーなしの `--live` は拒否されます。worker検証ではこの経路を実行していませんが、親側の合成fixture限定測定では6/6回成功し、1行を候補、5行をreviewへ送っただけで、provider本文は保存していません。測定の壁時計は3,957.8ms、input token数と費用はrecipe境界で返さないため未測定です。この結果は小標本の境界確認であり、一般精度・実利用・費用の証拠ではありません。

## 失敗条件と限界

次の場合はfail-closedで `review` または拒否します。

- `action_candidate` 以外のクラス
- 選択確率またはconfidenceが暫定ゲート未満
- fixtureが明示する曖昧フラグ
- 会議ID、source hash、行ID、Choiceのクラス、確率分布、モデル名の不一致
- 記録済みfixtureの実測/本番ラベル欠落、または `--live` で同梱fixture以外を指定

引用文・背景・見送り・未決定を意味的に完全判定できること、日本語の一般精度、実顧客データでの安全性、継続利用、費用、公開後の利用者反応は検証していません。小さな合成標本なので、成功してもJevの一般的な精度やプロンプトインジェクション耐性を証明しません。曖昧な行をJevが高confidenceで誤って `action_candidate` と返す可能性も残るため、候補を自動実行しない人間確認が境界です。
