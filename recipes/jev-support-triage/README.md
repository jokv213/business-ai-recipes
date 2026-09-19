# Recipe #3: Jev Support Triage

日本語中心の**合成**問い合わせを、記録済みのJev Choice応答から担当候補または`review`へ再分類する、キー不要の再現例です。オフライン実行ではTypeSafe、AIモデル、ネットワーク、返信先、外部データベースへアクセスしません。

このrecipeが示すのは、2026-09-19 JSTに行った16件の小標本実験を、同じ入力と公開可能な応答フィールドから再生できることです。実務精度、確率校正、導入効果、プロンプトインジェクション耐性は主張しません。

## 固定した入力と記録済み応答

### 事前ラベル（実行前に固定）

`cases.json` は `SYNTHETIC_ONLY_NOT_PRODUCTION` と明示した16件です。11件は明確な問い合わせ（単一担当10件と対象外1件）、5件は事前にレビュー対象とした曖昧・混合・誘導文です。入力fixtureのSHA-256は次のとおりです。

```text
cases.json  cf03bab36b8914a4393f79f402541c2c0f84c24791368749d734c532743904d5
```

| ID | 事前グループ | 期待ラベル |
| --- | --- | --- |
| `jp-login` | clear | technical |
| `jp-invoice` | clear | billing |
| `jp-demo` | clear | sales |
| `jp-unrelated` | clear | other（レビュー） |
| `jp-double-charge` | clear | billing |
| `jp-error-at-payment` | clear | technical |
| `jp-upgrade` | clear | sales |
| `jp-urgent-login` | clear | technical |
| `jp-quoted-command` | clear | technical |
| `en-double-charge` | clear | billing |
| `en-demo` | clear | sales |
| `jp-mixed-login-price` | review | 未固定（レビュー） |
| `jp-invoice-access` | review | 未固定（レビュー） |
| `jp-vague` | review | 未固定（レビュー） |
| `jp-two-requests` | review | 未固定（レビュー） |
| `jp-injection` | review | 未固定（レビュー） |

### 実測の事実（公開fixtureとして固定）

`observed-answers.json` は、実際のTypeSafe直通実測から公開可能な応答フィールドだけを抽出した**記録済みfixture**です。オフライン実行時にAPIを再呼出しません。

- 実測日時: `2026-09-19T14:00:20+09:00`
- モデル: `jev-1.13.0`
- 16件、各1問のChoice、16件ともHTTP 200で完了したという内部実測記録
- 入力tokens合計: 7,655（記録値）
- 往復時間中央値: 844.5ms、最大: 2,738ms（記録値）
- 記録済み回答fixtureのSHA-256: `444a9d175886b80878fb34841a85064477470bd9ab5054418a04bbe7d55dab9a`

ここでの「10件正しく」は、合成fixtureの事前ラベルとの一致を表すこの標本内の集計であり、日本語の一般的な精度や実運用の成功率ではありません。

## 判定と再現結果

`triage.py` は選択確率が `0.85` 以上、confidenceが `0.65` 以上、かつ選択肢が`other`ではない場合だけ担当候補を自動判定します。それ以外は`review`へ送ります。2つの値は**暫定ゲート**であり、校正済み閾値ではありません。

記録済みfixtureをこのルールで再計算した結果は次のとおりです。

| 区分 | 件数 | オフライン再現結果 |
| --- | ---: | --- |
| 単一担当の明確な問い合わせ | 10 | 期待担当へ自動判定10、誤自動判定0、レビュー0 |
| 対象外（`other`） | 1 | レビュー1 |
| 事前レビュー対象 | 5 | レビュー5、見逃し0 |

## 実行方法

公開パッケージのリポジトリ直下で実行します。

```bash
python3 -B recipes/jev-support-triage/triage.py --offline
python3 -B verify.py
```

オフライン出力には `network_calls=0` と `external_write=false` が含まれます。CIでも`--offline`だけを実行します。

## 任意のライブ再実行（実行していない）

明示的に`--live`を指定した場合だけ、同梱の16件をTypeSafe直通の`https://api.typesafe.ai/v1/systemone`へ`jev-1.13.0`として送ります。入力ファイルを追加指定する機能はなく、合成fixture以外は送れません。認証は環境変数`TYPESAFE_API_KEY`だけから読み、値・認証ヘッダー・providerの本文を出力または保存しません。返信送信、担当登録、その他の外部writeはありません。

```bash
TYPESAFE_API_KEY='（自分で安全に設定）' \
  python3 -B recipes/jev-support-triage/triage.py --live
```

このworkerは`--live`を実行していません。記録済み16件をAPIへ再送しないことが、この候補の目的です。CI、`verify.py`、通常のREADME手順もライブ経路を呼びません。

## 失敗条件と限界

次の場合はfail-closedで停止します。

- fixtureのschema、件数、ID順、合成ラベル、入力SHA-256が一致しない
- model ID、Choiceの選択肢、確率分布、confidence、usageが不正
- 選択確率またはconfidenceが暫定ゲート未満、`other`、対象外、曖昧・混合のいずれか
- `--live`で環境変数がない、HTTP非200、redirect、通信失敗、JSON以外の応答が返る

今回の日本語小標本は16件だけで、英語2件も含みます。明確な文章にconfidence 1.0が多いことは、確率が校正されている証拠ではありません。誘導文1件がレビューになったことも、prompt injection耐性の証明ではありません。文章生成、算術、日付比較、自動承認、実顧客データへの適用はこのrecipeの範囲外です。
