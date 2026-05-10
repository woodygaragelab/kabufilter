"""テスト用サンプルCSVを生成する。実際のstooq形式に合わせています。"""
import pandas as pd
import numpy as np
from datetime import date, timedelta

np.random.seed(42)
days = 120
start = date.today() - timedelta(days=days * 1.5)
biz_days = pd.bdate_range(start=start, periods=days)

close = 2500.0
rows = []
for d in biz_days:
    open_ = close * (1 + np.random.uniform(-0.005, 0.005))
    high = open_ * (1 + np.random.uniform(0.0, 0.02))
    low = open_ * (1 - np.random.uniform(0.0, 0.02))
    close = open_ * (1 + np.random.uniform(-0.015, 0.015))
    high = max(high, open_, close)
    low = min(low, open_, close)
    volume = int(np.random.randint(3_000_000, 10_000_000))
    rows.append({"Date": d.date(), "Open": round(open_, 1), "High": round(high, 1),
                 "Low": round(low, 1), "Close": round(close, 1), "Volume": volume})

df = pd.DataFrame(rows)
df.to_csv("7203.jp_d.csv", index=False)
print(f"7203.jp_d.csv を生成しました ({len(df)} 件)")
