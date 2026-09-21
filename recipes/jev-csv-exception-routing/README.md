# Jev CSV Exception Routing

CSVの決定的検査が返した `data_row` と `flags` に添えた**合成説明文だけ**を、固定キーワード基準線と記録済みJev Choiceで担当候補または `review` へ仕分けるoffline recipeです。金額、行数、欠損、不正値、重複IDの判定は既存のCSV recipeが所有します。このrecipeは数値を計算せず、CSVを修正せず、送信・承認・チケット作成を行いません。

## 実行

公開パッケージ直下から、同梱fixtureだけを使って実行します。

```bash
python3 -B recipes/jev-csv-exception-routing/route.py --offline
```

live provider経路は同梱していません。したがってAPIキー、Keychain、ネットワーク、provider本文、外部writeは使いません。`recorded-answers.json` は `jev-1.13.0` のChoice形式を模した**合成の記録済みfixture**で、実際のprovider観測ではありません。

## 同じfixtureの比較

`cases.json` は24件の事前ラベル付き合成所見です。`finding` は既存CSV recipeの値なし出力と同じ `data_row` / `flags` 形式だけを持ち、record ID、部門名、金額などのセル値は持ちません。review群には、曖昧さ、複数部門、引用、誘導文、根拠不足を12件含めています。

固定基準線は説明文に含まれる担当キーワードを数えるだけです。担当語が複数なら `review`、ゼロなら `unclassifiable`、1担当だけなら候補とします。引用や誘導を意味理解しないため、今回の合成例では危険な誤自動が3件あります。

Jev側は記録済みChoiceの `choice`、確率、confidenceだけを読みます。担当Choiceは確率0.85以上かつconfidence 0.65以上のときだけ候補にし、それ以外は `review` へ送ります。Choice欠落は `unclassifiable` です。これは仕分け結果の候補であり、修正・送信・承認の許可ではありません。

今回のoffline再現値は次のとおりです。

| 方法 | 処理 | 自動担当候補 | review/保留 | 分類不能 | 正しい自動候補 | 誤自動 | 危険な誤自動 | review率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 固定キーワード | 24 | 15 | 9 | 4 | 12 | 3 | 3 | 37.50% |
| 記録済みJev Choice | 24 | 11 | 13 | 1 | 11 | 0 | 0 | 54.17% |

基準線に危険な誤自動が残るため、出力の安全判定は `DO_NOT_RECOMMEND_AUTO_ROUTING` です。Jev側の誤自動が0件だったことも、24件の合成fixture内の観測に限られ、一般的な精度・確率校正・実運用の成功を示しません。

## 実測と未実測

- 実測: 24件の同一fixture、固定基準線の決定的な再計算、記録済みChoiceのgate適用、誤自動・review/保留・分類不能・処理件数の比較。
- 未実測: TypeSafeへのlive request、providerの応答時間、input/output token、費用、実顧客データでの精度、第三者利用、担当者の業務成果。
- `measurement` の `elapsed_ms`、`input_tokens`、`cost_estimate_usd` は未計測のため `null` です。費用根拠は「live provider callなし」であり、料金を推定していません。

## 失敗条件と境界

fixtureのlabel、件数、ID順、`data_row`/flag schema、Jev model、確率の合計、Choice順、入力fixture SHAが一致しない場合は停止します。`cases.json` に20件未満、review例6件未満、未対応flag、重複ID/行番号、raw CSV値がある場合も受け付けません。

出力の `false_auto_count` は、reviewと事前ラベルされたケースを担当候補へ送った件数、およびcandidateの担当を外した件数です。危険な誤自動が1件でもあれば、自動担当候補の公開推奨を出しません。人のreview、元CSVの再確認、修正、送信、承認は別工程です。
