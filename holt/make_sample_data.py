"""
サンプルデータ作成スクリプト
- 日次データ 300点
- 季節性なし、トレンドあり
- 測定できない外部要因を想定し、途中で傾きが3回変わる
"""
import numpy as np
import pandas as pd

rng = np.random.default_rng(42)

n = 300
dates = pd.date_range("2025-01-01", periods=n, freq="D")

# 区間ごとの傾き（1日あたりの増減）
# 0-99: 緩やかに増加 / 100-169: 急増 / 170-239: 横ばい～微減 / 240-299: 再び増加
segments = [(0, 100, 0.3), (100, 170, 1.2), (170, 240, -0.2), (240, 300, 0.6)]

slope = np.zeros(n)
for start, end, s in segments:
    slope[start:end] = s

trend = 100 + np.cumsum(slope)            # 初期値100から傾きを積み上げ
noise = rng.normal(0, 2.0, n)             # 観測ノイズ
value = trend + noise

df = pd.DataFrame({"date": dates, "value": value.round(2)})
df.to_csv("sample_data.csv", index=False)
print(df.head())
print(f"sample_data.csv を作成しました（{n}行）")
