import pandas as pd
import requests
import io

# JPX公式の上場銘柄一覧Excel
JPX_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"

def download_prime_codes(output_file: str = "prime_codes.csv"):
    print("JPXから上場銘柄一覧をダウンロード中...")
    response = requests.get(JPX_URL, timeout=30)
    response.raise_for_status()

    df = pd.read_excel(io.BytesIO(response.content), header=0)

    # 東証プライム内国株式のみ抽出
    prime = df[df["市場・商品区分"] == "プライム（内国株式）"].copy()
    prime = prime[["コード", "銘柄名"]].rename(columns={"コード": "Code", "銘柄名": "Name"})
    prime["Code"] = prime["Code"].astype(str).str.zfill(4)
    prime = prime.reset_index(drop=True)

    prime.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"保存しました: {output_file}  ({len(prime)}銘柄)")
    print(prime.head(10))

if __name__ == "__main__":
    download_prime_codes()
