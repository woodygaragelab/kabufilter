import yfinance as yf
from datetime import datetime
import pandas as pd

results = []
codes = [7203,7267]
for code in codes:
    ticker = f"{code}.T"
    
    try:
        data = yf.download(ticker, period="3d", interval="1d", progress=False)
        print(data)
        if not data.empty:
            row = data.iloc[-1]
            results.append({
                "Code": code,
                "Date": data.index[-1],
                "Close": row["Close"],
                "Volume": row["Volume"]
            })
    except:
        continue

df_result = pd.DataFrame(results)

today = datetime.today().strftime("%Y%m%d")
df_result.to_csv(f"tse_prime_{today}.csv", index=False)