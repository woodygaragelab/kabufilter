"""
Holt法（減衰トレンド付き）による予測サンプル

処理の流れ
1. データ読み込み
2. 全データでモデルを学習し、パラメータと将来予測を表示
3. ローリング検証で、ナイーブ法・Holt法（減衰なし）と精度を比較
4. グラフを出力

必要なライブラリ:
    pip install pandas numpy statsmodels matplotlib
"""
import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

warnings.filterwarnings("ignore")  # 最適化の収束警告などを非表示

# ===== 設定 =====
CSV_PATH = "sample_data.csv"
HORIZON = 5         # 何ステップ先まで予測するか
TRAIN_WINDOW = 60   # 学習に使う直近データの点数（Noneなら全期間）
EVAL_START = 120    # ローリング検証を始める位置


# ===== 1. データ読み込み =====
df = pd.read_csv(CSV_PATH, parse_dates=["date"], index_col="date")
s = df["value"].asfreq("D")


def fit_holt(series, damped=True):
    """Holt法を学習して返す"""
    model = ExponentialSmoothing(
        series,
        trend="add",
        damped_trend=damped,
        initialization_method="estimated",
    )
    return model.fit(optimized=True)


# ===== 2. 全データ（直近TRAIN_WINDOW点）で学習・予測 =====
train = s if TRAIN_WINDOW is None else s.iloc[-TRAIN_WINDOW:]
fit = fit_holt(train, damped=True)

print("=== 推定パラメータ ===")
print(f"α (水準の平滑化)  : {fit.params['smoothing_level']:.3f}")
print(f"β (トレンドの平滑化): {fit.params['smoothing_trend']:.3f}")
print(f"φ (減衰係数)      : {fit.params['damping_trend']:.3f}")
print("  ※ φが1に近いほど傾きをそのまま延長、小さいほど早く水平に近づく")

forecast = fit.forecast(HORIZON)

# 予測区間（残差の標準偏差とステップ数から簡易的に算出）
resid_sd = np.std(fit.resid, ddof=1)
steps = np.arange(1, HORIZON + 1)
z80 = 1.2816  # 80%区間
lower = forecast - z80 * resid_sd * np.sqrt(steps)
upper = forecast + z80 * resid_sd * np.sqrt(steps)

result = pd.DataFrame({"予測値": forecast, "下限(80%)": lower, "上限(80%)": upper}).round(2)
print(f"\n=== {HORIZON}ステップ先までの予測 ===")
print(result)


# ===== 3. ローリング検証 =====
# 各時点 t までのデータで学習し、h ステップ先を予測して実績と比べる
records = []
for t in range(EVAL_START, len(s) - HORIZON + 1):
    hist = s.iloc[:t] if TRAIN_WINDOW is None else s.iloc[max(0, t - TRAIN_WINDOW):t]
    actual = s.iloc[t:t + HORIZON].values

    f_damped = fit_holt(hist, damped=True).forecast(HORIZON).values
    f_holt = fit_holt(hist, damped=False).forecast(HORIZON).values
    f_naive = np.repeat(hist.iloc[-1], HORIZON)

    for h in range(HORIZON):
        records.append({
            "origin": s.index[t - 1], "h": h + 1, "actual": actual[h],
            "Holt(減衰)": f_damped[h], "Holt(減衰なし)": f_holt[h], "ナイーブ": f_naive[h],
        })

ev = pd.DataFrame(records)
methods = ["Holt(減衰)", "Holt(減衰なし)", "ナイーブ"]
mae = ev.groupby("h").apply(
    lambda g: pd.Series({m: np.mean(np.abs(g[m] - g["actual"])) for m in methods})
).round(2)
print("\n=== ローリング検証 MAE（ステップ別）===")
print(mae)
print("\n全体MAE:")
print(mae.mean().round(2))


# ===== 4. グラフ出力 =====
fig, axes = plt.subplots(2, 1, figsize=(11, 8))

# 上段: 実績・当てはめ値・将来予測
ax = axes[0]
ax.plot(s.index, s.values, color="gray", lw=1, label="Actual")
ax.plot(fit.fittedvalues.index, fit.fittedvalues.values, color="tab:blue", lw=1.5,
        label=f"Fitted (last {len(train)} pts)")
ax.plot(forecast.index, forecast.values, color="tab:red", marker="o", label="Forecast")
ax.fill_between(forecast.index, lower, upper, color="tab:red", alpha=0.2, label="80% interval")
ax.set_title("Holt's damped trend: fit and forecast")
ax.legend()
ax.grid(alpha=0.3)

# 下段: 1ステップ先予測の誤差推移（変化点で誤差が増える様子を確認）
ax = axes[1]
h1 = ev[ev["h"] == 1].set_index("origin")
for m, c in zip(methods, ["tab:red", "tab:blue", "tab:green"]):
    ax.plot(h1.index, (h1[m] - h1["actual"]).abs(), lw=1, color=c, label=m.replace("Holt(減衰)", "Holt damped").replace("Holt(減衰なし)", "Holt").replace("ナイーブ", "Naive"))
ax.set_title("Absolute error of 1-step-ahead forecast (rolling)")
ax.legend()
ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig("holt_forecast.png", dpi=120)
print("\nholt_forecast.png を出力しました")
