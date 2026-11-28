# kabufilter

日本株（東証プライム）の日足チャートを閲覧・分類・絞り込みする Tkinter デスクトップアプリ。
起動: `python kabufilter.py`（または `kabufilter.bat`）

## 構成
- `kabufilter.py`: 本体。`ChartApp`（GUI）、`load_csv`、`calc_stats`、`draw_candlestick`
- `rules_editor.py`: `analysis_rules.json` の編集ダイアログ（`RulesEditor`、⚙ボタンから開く）と検証・整形の純粋関数
- `analysis_rules.json`: 分析の判定条件と色の設定
- `data/`: yfinance 形式の株価 CSV（git 管理外）
- `my_codes.xlsx`, `my_codes_eps.xlsx`: 個人の銘柄リスト（git 管理外）
- `prime_codes.csv`, `download_prime_codes.py`: プライム銘柄コードの取得
- `holt/`, `old/`, `test.py`: 実験用・旧版（本体とは独立）

## 設計方針
- 判定条件と色は `analysis_rules.json` に集約し、コードに直書きしない。
  - 項目: `rules`（分析ルール）、`moving_averages`（移動平均の期間）、`button_colors`（分析ボタン色）、`candle_colors`（ローソク足・出来高の色 up/down）
  - ルールの項目: `name` / `when` / `exclude` / `color` / `alpha` / `layers` / `enabled`
  - `when` は pandas.eval 形式。`MA<期間>` と、上に書いたルール名を参照できる
  - `exclude` に挙げたルールが成立する日は、そのルールの背景を塗らない
  - 更新日時を見て再読込するので、設定変更に再起動は不要
  - 設定が欠けている・読めない場合は従来の既定色にフォールバックする
  - 条件式が不正なら例外を投げ、ステータスバーに `エラー: …` と表示する
- `analysis_rules.json` のコメントは JSON 標準に従い、ダミーキー（`_readme`、`_comment` など）で書く。`//` や `/* */` は使わない。読み込み側はこれらのキーを無視する。
- リファクタリングでは、変更前と出力が同じになることをテストで確認する。
- CSV は yfinance 出力で先頭 3 行がヘッダのため、2・3行目をスキップして読む。銘柄コードは 4 桁にゼロ埋めする。

## 現在の分析ルール
- base: MA5×1.02 > MA25 > MA75（黄緑、薄い）
- strong: base かつ MA5×0.98 < MA25（黄緑、濃い）
- weak: strong かつ 終値 < MA25（赤系、strong と同じ濃さ。黄緑とは重ねない）

## 作業方針
- コミットは依頼があったときだけ行う。
- 個人データ（`data/`、`*.xlsx`）は `.gitignore` で除外し、コミットしない。
- 返答は日本語で、結論と変更点を簡潔に伝える。
- 設定の仕様を変えたときは、`analysis_rules.json` の `_readme` も更新する。
- GUI の目視確認はできないので、構文チェックと純粋関数のテストで検証し、未確認の範囲は明記する。
