# CSV-to-Checked-Report

合成の売上CSVをPython標準ライブラリだけで読み、行数・金額の欠損・不正値・重複ID・合計を決定的に集計するrecipeです。固定の説明文に含まれる数値は集計結果と照合し、成功した場合だけレポートとして返します。実行時にAIモデル、外部API、ネットワーク、顧客データへアクセスしません。

## 実行

リポジトリ直下で実行します。

```bash
python3 -B recipes/csv-to-report/report.py \
  --csv recipes/csv-to-report/sales.csv
```

出力はJSONです。サンプルは4行で、金額が有効な行は3行、欠損は1件、合計は4,500円です。要確認行の元データ値は出力せず、ヘッダーを除く論理データ行番号とflagだけを返します。

```json
{
  "metrics": {
    "status": "REVIEW_REQUIRED",
    "source_rows": 4,
    "valid_amount_rows": 3,
    "missing_amount_rows": 1,
    "invalid_amount_rows": 0,
    "duplicate_record_rows": 0,
    "total_amount_yen": 4500
  },
  "narrative": "CSV集計では、データ行数は4行、金額が有効な行は3行、欠損は1件、数値エラーは0件、重複IDの後続行は0件、合計金額は4,500円です。状態はREVIEW_REQUIREDです。",
  "narrative_verified": true,
  "review_findings": [
    {"data_row": 2, "flags": ["missing_amount"]}
  ]
}
```

## 集計と要確認行

| 項目 | 扱い |
| --- | --- |
| `source_rows` | ヘッダー後のデータレコード数。空CSVまたはヘッダーだけなら0。 |
| `valid_amount_rows` | `amount_yen` が空でない非負整数文字列の行数。 |
| `missing_amount_rows` | `amount_yen` が空欄または値なしの行数。合計には入れない。 |
| `invalid_amount_rows` | 空欄ではないが非負整数として読めない行数。合計には入れない。 |
| `duplicate_record_rows` | 同じ `record_id` の2行目以降の件数。重複行も合計からは除外しない。 |
| `total_amount_yen` | 読み取れた整数金額の合計。 |
| `status` | 0行なら `EMPTY_INPUT`、品質flagがなければ `OK`、欠損・不正値・重複があれば `REVIEW_REQUIRED`。 |
| `review_findings` | 問題のある行だけをCSV順で返す。正常行・空入力は `[]`。 |

`review_findings` の各要素は `{"data_row": 2, "flags": ["missing_amount"]}` の形式です。`data_row` はヘッダーを除いた1-basedの論理データレコード番号で、引用符内の改行は同じ1レコードとして数えます。Python 3.11の `csv.reader.line_num` は読み込んだ物理行数であり、返却レコード数とは異なる場合があるため、ここではCSV readerが返すレコードを順に数えています（[Python 3.11 csv documentation](https://docs.python.org/3.11/library/csv.html)）。

`flags` は同じ行の問題を1件にまとめ、次の固定順で返します。

| flag | 意味 |
| --- | --- |
| `missing_amount` | 金額が空欄または値なし。 |
| `invalid_amount` | 金額が空欄ではないが、非負整数ではない。 |
| `duplicate_record_id` | 先行行に同じIDがある。最初の行には付けず、後続行だけに付ける。 |

`review_findings` に `record_id`、部門名、金額など元CSVのセル値は含めません。人が確認するときは、入力に使ったものと同じ元CSVを開き、ヘッダーの次をデータ行1として論理レコードを数えて該当行を確認してください。引用符内の改行を別行として数えず、テキストエディターの物理行番号ではなくCSVとしての行を使います。表計算ソフトで確認するときも、同じCSVとヘッダーを基準に行を特定し、値の妥当性や重複の正誤は業務担当者が判断します。このrecipeは自動補完・自動修正を行いません。

## 同梱サンプル

| 入力 | 結果 |
| --- | --- |
| `examples/empty.csv` | `EMPTY_INPUT`、0行、`review_findings: []`。 |
| `examples/duplicate.csv` | 後続の重複行だけをflagし、重複を黙って除外しない。 |
| `examples/mixed-strings.csv` | 欠損と不正文字列を別々に数え、要確認行を示す。 |

この例はCSVの業務上の意味、重複の正誤、欠損値の補完方法を判定しません。サンプル値は実在の売上、顧客、導入実績を表しません。
