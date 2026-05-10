import yfinance as yf
import sys
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

def download_stock(code: str):
    ticker = f"{code}.T"
    data = yf.download(ticker, period="70d", interval="1d", progress=False)

    if data.empty:
        print(f"データが取得できませんでした: {ticker}")
        return

    data = data.tail(50)

    output_file = os.path.join(DATA_DIR, f"{code}.csv")
    data.to_csv(output_file)
    print(f"保存しました: {output_file} ({len(data)}日分)")
    print(data)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python download_stock.py <銘柄コード>")
        print("例: python download_stock.py 7203")
        sys.exit(1)

    code = sys.argv[1]
    download_stock(code)
