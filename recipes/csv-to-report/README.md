# CSV-to-Checked-Report

このrecipeは合成の売上CSVから、行数・金額の欠損・不正値・重複ID・合計を決定的に集計し、固定の説明文に含まれる数値が集計結果と一致するか確認します。Python標準ライブラリだけを使い、実行時にAIモデル、外部API、ネットワーク、顧客データへアクセスしません。

## 実行

リポジトリ直下で実行します。

```bash
python3 -B recipes/csv-to-report/report.py \
  --csv recipes/csv-to-report/sales.csv
```

合成CSVは4行です。実行結果では有効金額3行、欠損1件、合計4,500円となり、説明文の数値検算に成功します。品質フラグがあるため状態は `REVIEW_REQUIRED` です。

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
  "narrative_verified": true
}
```

## 失敗ケースと扱い

- `examples/empty.csv`: ヘッダーのみを0行として `EMPTY_INPUT` にする。
- `examples/duplicate.csv`: 後続の重複行を1件と数えて `REVIEW_REQUIRED` にする。重複行は勝手に除外せず、入力どおり合計する。
- `examples/mixed-strings.csv`: 欠損と整数でない文字列を別々に数え、合計からは除外して `REVIEW_REQUIRED` にする。
- 必須列の欠落、不正なCSV行、空のrecord IDはエラーとして停止する。

この例はCSVの業務上の意味、重複の正誤、欠損値の補完方法を判定しません。`REVIEW_REQUIRED` の入力を業務で使う前に、人が元CSVを確認してください。サンプル値は実在の売上、顧客、導入実績を表しません。
