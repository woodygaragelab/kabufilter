import tkinter as tk
from tkinter import ttk, messagebox
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
from matplotlib.transforms import blended_transform_factory
import json
import os
from datetime import datetime
import signal
import threading
import yfinance as yf
import matplotlib
from rules_editor import RulesEditor

matplotlib.rcParams["font.family"] = ["Yu Gothic", "Meiryo", "MS Gothic", "DejaVu Sans"]

CHART_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(CHART_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
VIEW_DAYS_CHOICES = ["200", "75", "25"]  # 横倍率の選択肢（表示する営業日数）
VIEW_DAYS_DEFAULT = "200"


def view_start_num(dates, end_num: float, days: int) -> float:
    """表示最終日 end_num を含めて days 営業日分さかのぼった日の日付番号を返す。
    dates は昇順の日付番号の配列。データが足りなければ先頭の日付を返す。"""
    idx = int((dates <= end_num).sum())  # 表示最終日までの本数
    if idx == 0:
        return end_num - days
    return float(dates[max(idx - days, 0)])

def load_csv(code: str) -> pd.DataFrame:
    filename = os.path.join(DATA_DIR, f"{code}.csv")
    if not os.path.exists(filename):
        raise FileNotFoundError(f"ファイルが見つかりません: {filename}")

    # yfinance出力CSVは先頭にPrice/Ticker/Dateの3行ヘッダがあるため2・3行目をスキップ
    df = pd.read_csv(filename, skiprows=[1, 2], index_col=0)
    df.index.name = "Date"
    df = df.reset_index()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.dropna(subset=["Date", "Open", "High", "Low", "Close"])
    if df.empty:
        raise ValueError("有効なデータがありません")

    df = df.sort_values("Date").reset_index(drop=True)
    return df


def calc_stats(df: pd.DataFrame) -> dict:
    """終値・移動平均・売買高・トレンド判定を計算して辞書で返す。"""
    def _r(v):
        return round(float(v), 1) if pd.notna(v) else None
    def _b(v):
        return bool(v) if pd.notna(v) else None

    close = df["Close"].iloc[-1]
    ma25  = df["Close"].rolling(25).mean().iloc[-1]
    ma75  = df["Close"].rolling(75).mean().iloc[-1]
    ma200 = df["Close"].rolling(200).mean().iloc[-1]
    tv    = df["Volume"] * df["Close"] / 1e8
    tv25  = tv.rolling(25).mean().iloc[-1]
    tv75  = tv.rolling(75).mean().iloc[-1]

    close_above_ma25 = _b(close > ma25)          if pd.notna(ma25) else None
    ma25_above_ma75  = _b(ma25  > ma75)           if pd.notna(ma75) else None
    trend            = _b(close > ma25 > ma75)    if pd.notna(ma25) and pd.notna(ma75) else None
    tv75_above_10    = _b(tv75 > 10)              if pd.notna(tv75) else None

    return {
        "Close":          _r(close),
        "MA25":           _r(ma25),
        "MA75":           _r(ma75),
        "MA200":          _r(ma200),
        "Turnover":       _r(tv.iloc[-1]),
        "TurnoverMA25":   _r(tv25),
        "TurnoverMA75":   _r(tv75),
        "CloseAboveMA25": close_above_ma25,
        "MA25AboveMA75":  ma25_above_ma75,
        "Trend":          trend,
        "TV75Above10":    tv75_above_10,
    }


def update_period_title(ax_price):
    """現在の表示範囲を YYYY/MM/DD-YYYY/MM/DD で右上に表示する。"""
    x0, x1 = ax_price.get_xlim()
    d0 = mdates.num2date(x0).strftime("%Y/%m/%d")
    d1 = mdates.num2date(x1).strftime("%Y/%m/%d")
    ax_price.set_title(f"{d0}-{d1}", loc="right", fontsize=14)


RULES_PATH = os.path.join(CHART_DIR, "analysis_rules.json")
_rules_cache = {"mtime": None, "data": None}


def load_analysis_rules() -> dict:
    """analysis_rules.json を読み込む（更新日時が変わったときだけ再読込）。"""
    mtime = os.path.getmtime(RULES_PATH)
    if _rules_cache["mtime"] != mtime:
        with open(RULES_PATH, encoding="utf-8") as f:
            _rules_cache["data"] = json.load(f)
        _rules_cache["mtime"] = mtime
    return _rules_cache["data"]


def analysis_button_color(on: bool) -> str:
    try:
        colors = load_analysis_rules().get("button_colors", {})
    except Exception:
        colors = {}
    return colors.get("on", "#b8e6a0") if on else colors.get("off", "#89b4fa")


def candle_colors() -> tuple[str, str]:
    """ローソク足（出来高含む）の (陽線色, 陰線色)。設定がなければ既定色。"""
    try:
        c = load_analysis_rules().get("candle_colors", {})
    except Exception:
        c = {}
    return c.get("up", "#e74c3c"), c.get("down", "#2ecc71")


def nikkei_colors() -> tuple[str, float]:
    """日経平均の折れ線の (色, 不透明度)。設定がなければ既定値。"""
    try:
        c = load_analysis_rules().get("nikkei_colors", {})
    except Exception:
        c = {}
    return c.get("line", "#f9e2af"), float(c.get("alpha", 0.8))


NIKKEI_CODE = "N225"


def download_nikkei():
    """日経平均(^N225)を取得して data/N225.csv に保存する。"""
    data = yf.download("^N225", period="800d", interval="1d", progress=False)
    if data.empty:
        raise ValueError("日経平均のデータ取得に失敗しました")
    data.tail(400).to_csv(os.path.join(DATA_DIR, f"{NIKKEI_CODE}.csv"))


def ensure_nikkei():
    """data/N225.csv が無い、または今日更新していなければダウンロードする。"""
    path = os.path.join(DATA_DIR, f"{NIKKEI_CODE}.csv")
    if os.path.exists(path):
        updated = datetime.fromtimestamp(os.path.getmtime(path)).date()
        if updated == datetime.today().date():
            return
    download_nikkei()


def eval_rules(df: pd.DataFrame, rules: dict) -> dict:
    """全ルールの when を評価し、{ルール名: bool の Series} を返す（exclude は未適用）。"""
    env = pd.DataFrame({c: df[c].to_numpy() for c in ("Open", "High", "Low", "Close", "Volume") if c in df})
    for n in rules.get("moving_averages", []):
        env[f"MA{int(n)}"] = df["Close"].rolling(int(n)).mean().to_numpy()

    matched = {}
    for r in rules["rules"]:
        name = r["name"]
        try:
            m = env.eval(r["when"], engine="python")
        except Exception as e:
            raise ValueError(f"ルール '{name}' の条件式が不正です: {r['when']} ({e})") from e
        m = pd.Series(m, index=env.index).fillna(False).astype(bool)
        matched[name] = m
        env[name] = m
    return matched


def rule_mask(df: pd.DataFrame, name: str, rules: dict | None = None):
    """背景に塗られる日（when が成立し、exclude のルールが不成立の日）の bool Series。"""
    rules = rules or load_analysis_rules()
    matched = eval_rules(df, rules)
    rule = next(r for r in rules["rules"] if r["name"] == name)
    m = matched[name]
    for ex in rule.get("exclude", []):
        m = m & ~matched[ex]
    return m


def highlight_layers(df: pd.DataFrame, rules: dict | None = None) -> list[tuple]:
    """設定ファイルのルールを評価し、描画用の [(mask, color, alpha), ...] を返す。"""
    rules = rules or load_analysis_rules()
    matched = eval_rules(df, rules)

    layers = []
    for r in rules["rules"]:
        if not r.get("enabled", True):
            continue
        m = matched[r["name"]]
        for ex in r.get("exclude", []):
            m = m & ~matched[ex]
        layer = (m.to_numpy(), r.get("color", "#b8e6a0"), float(r.get("alpha", 0.15)))
        layers.extend([layer] * int(r.get("layers", 1)))
    return layers


def _span_runs(ax_list, dates, mask, alpha, color="#b8e6a0"):
    """mask が True の連続区間ごとに背景の帯を引く。"""
    i, n = 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            for ax in ax_list:
                ax.axvspan(dates[i] - 0.5, dates[j] + 0.5, color=color, alpha=alpha, zorder=0, lw=0)
            i = j + 1
        else:
            i += 1


def draw_candlestick(ax_price, ax_vol, df: pd.DataFrame, code: str, name: str = "", ratio: float = 2.0, view_end=None,
                     highlight: bool = False, ax_nk=None, nk_df: pd.DataFrame | None = None,
                     view_days: int = 200):
    ax_price.clear()
    ax_vol.clear()
    if ax_nk is not None:
        ax_nk.clear()
        ax_nk.set_visible(nk_df is not None)
        ax_nk.xaxis.set_visible(False)
        ax_nk.patch.set_visible(False)

    dates = mdates.date2num(df["Date"].to_numpy().astype("datetime64[ms]").astype(object))
    width = 0.6

    # 条件に合う日の背景を塗る（条件・色は analysis_rules.json）
    if highlight:
        for mask, color, alpha in highlight_layers(df):
            _span_runs((ax_price, ax_vol), dates, mask, alpha, color)

    up_color, down_color = candle_colors()
    for date, row in zip(dates, df.itertuples()):
        color = up_color if row.Close >= row.Open else down_color

        # ローソク足の実体
        body_low = min(row.Open, row.Close)
        body_high = max(row.Open, row.Close)
        rect = Rectangle(
            (date - width / 2, body_low),
            width,
            body_high - body_low,
            color=color,
            zorder=3,
        )
        ax_price.add_patch(rect)

        # ヒゲ
        ax_price.plot(
            [date, date], [row.Low, body_low], color=color, linewidth=1, zorder=2
        )
        ax_price.plot(
            [date, date], [body_high, row.High], color=color, linewidth=1, zorder=2
        )

        # 売買高（Volume × Close、億円単位）
        vol_color = up_color if row.Close >= row.Open else down_color
        turnover = (
            row.Volume * row.Close / 1e8
            if hasattr(row, "Volume") and pd.notna(row.Volume)
            else 0
        )
        bar = Rectangle(
            (date - width / 2, 0),
            width,
            turnover,
            color=vol_color,
            alpha=0.7,
        )
        ax_vol.add_patch(bar)

    # 移動平均線
    for window, color in [(5, "#a6e3a1"), (25, "#f38ba8"), (75, "#89dceb"), (200, "#cba6f7")]:
        ma = df["Close"].rolling(window).mean()
        valid = ma.notna()
        if valid.any():
            ax_price.plot(
                dates[valid.values],
                ma[valid].values,
                color=color,
                linewidth=1.5,
                label=f"MA{window}",
                zorder=4,
            )
    ax_price.legend(fontsize=12, loc="upper left")

    # 軸設定
    # 表示期間：表示最終日までの view_days 営業日分（縦軸も表示期間内のデータで決める）
    end_num = mdates.date2num(view_end if view_end is not None else df["Date"].iloc[-1])
    start_num = view_start_num(dates, end_num, view_days)
    ax_price.set_xlim(start_num - 1, end_num + 1)
    vis = (dates >= start_num) & (dates <= end_num)
    if not vis.any():
        vis[:] = True
    vdf = df[vis]
    price_max = vdf["High"].max()
    margin = price_max * 0.02
    y_top = price_max + margin
    y_bottom = (vdf["Low"].min() - margin) if ratio <= 1.0 else (y_top / ratio)
    ax_price.set_ylim(y_bottom, y_top)

    # 日経平均（右軸に重ねる。縦軸は表示期間内の日経自身の範囲）
    if ax_nk is not None and nk_df is not None:
        nk_dates = mdates.date2num(nk_df["Date"].to_numpy().astype("datetime64[ms]").astype(object))
        nk_color, nk_alpha = nikkei_colors()
        ax_nk.plot(nk_dates, nk_df["Close"].to_numpy(), color=nk_color, alpha=nk_alpha,
                   linewidth=1.2, zorder=5)
        nk_vis = (nk_dates >= start_num) & (nk_dates <= end_num)
        nk_close = nk_df["Close"][nk_vis] if nk_vis.any() else nk_df["Close"]
        nk_lo, nk_hi = nk_close.min(), nk_close.max()
        nk_margin = (nk_hi - nk_lo) * 0.05 or nk_hi * 0.01
        ax_nk.set_ylim(nk_lo - nk_margin, nk_hi + nk_margin)
        ax_nk.set_xlim(ax_price.get_xlim())
        ax_nk.set_ylabel("日経平均", fontsize=16, color=nk_color)
        ax_nk.tick_params(axis="y", labelsize=15, colors=nk_color)
        ax_nk.yaxis.set_label_position("right")
        ax_nk.yaxis.tick_right()
        ax_nk.patch.set_visible(False)

    ax_price.set_title(f"{code}  {name}", fontsize=19)
    update_period_title(ax_price)
    ax_price.set_ylabel("価格", fontsize=16)
    ax_price.tick_params(labelsize=15)
    ax_price.xaxis.set_major_formatter(mdates.DateFormatter("%y/%m/%d"))
    ax_price.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax_price.grid(True, alpha=0.3)

    ax_vol.set_xlim(ax_price.get_xlim())
    if "Volume" in df.columns and df["Volume"].notna().any():
        turnover = df["Volume"] * df["Close"] / 1e8
        turnover_max = turnover[vis].max()
        ax_vol.set_ylim(0, turnover_max * 1.2)
        for window, color in [(25, "#f38ba8"), (75, "#89dceb"), (200, "#cba6f7")]:
            ma = turnover.rolling(window).mean()
            valid = ma.notna()
            if valid.any():
                ax_vol.plot(
                    dates[valid.values],
                    ma[valid].values,
                    color=color,
                    linewidth=1.5,
                    label=f"MA{window}",
                    zorder=4,
                )
        ax_vol.legend(fontsize=12, loc="upper left")
    ax_vol.set_ylabel("売買高(億円)", fontsize=16)
    ax_vol.tick_params(labelsize=15)
    ax_vol.xaxis.set_major_formatter(mdates.DateFormatter("%y/%m/%d"))
    ax_vol.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax_vol.grid(True, alpha=0.3)

    plt.setp(ax_price.get_xticklabels(), rotation=30, ha="right")
    plt.setp(ax_vol.get_xticklabels(), rotation=30, ha="right")


class ChartApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("kabufilter")
        self.geometry("1400x800")
        self.configure(bg="#1e1e2e")
        self._xlsx_lock            = threading.Lock()
        self._codes                = []
        self._filtered_codes       = []
        self._programmatic_select  = False
        self._build_ui()

    def _build_ui(self):
        self.code_var  = tk.StringVar(value="7203")
        self.ratio_var = tk.StringVar(value="4.0")
        self.days_var  = tk.StringVar(value=VIEW_DAYS_DEFAULT)
        # コンボボックスのドロップダウン（選択肢一覧）の文字サイズ
        self.option_add("*TCombobox*Listbox.font", ("", 20))

        # メインエリア（左リスト＋右チャート）
        content = tk.Frame(self, bg="#1e1e2e")
        content.pack(fill=tk.BOTH, expand=True)

        # 左パネル：銘柄リスト
        left = tk.Frame(content, bg="#181825", width=370)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(12, 0), pady=4)
        left.pack_propagate(False)

        cb_frame = tk.Frame(left, bg="#181825")
        cb_frame.pack(pady=(6, 2))
        self.cat1_var = tk.BooleanVar(value=True)
        self.cat2_var = tk.BooleanVar(value=True)
        self.cat3_var = tk.BooleanVar(value=True)
        self.cat4_var = tk.BooleanVar(value=True)
        self.cat5_var = tk.BooleanVar(value=True)
        ckb_opts = dict(bg="#181825", fg="#cdd6f4", selectcolor="#181825",
                        activebackground="#181825", activeforeground="#cdd6f4",
                        font=("", 14), command=self._apply_filter)
        tk.Checkbutton(cb_frame, text="1", variable=self.cat1_var, **ckb_opts).pack(
            side=tk.LEFT, padx=(8, 4))
        tk.Checkbutton(cb_frame, text="2", variable=self.cat2_var, **ckb_opts).pack(
            side=tk.LEFT, padx=(4, 4))
        tk.Checkbutton(cb_frame, text="3", variable=self.cat3_var, **ckb_opts).pack(
            side=tk.LEFT, padx=(4, 4))
        tk.Checkbutton(cb_frame, text="4", variable=self.cat4_var, **ckb_opts).pack(
            side=tk.LEFT, padx=(4, 4))
        tk.Checkbutton(cb_frame, text="5", variable=self.cat5_var, **ckb_opts).pack(
            side=tk.LEFT, padx=(4, 8))
        tk.Button(
            cb_frame,
            text="DL",
            command=self._force_download,
            bg="#89b4fa",
            fg="#1e1e2e",
            font=("", 13, "bold"),
            relief=tk.FLAT,
            padx=6,
        ).pack(side=tk.LEFT, padx=(4, 8))

        # 列ごとのフィルタ入力欄
        self._filter_frame = tk.Frame(left, bg="#181825")
        self._filter_frame.pack(fill=tk.X, padx=4, pady=(0, 0))

        self.code_filter_var = tk.StringVar()
        self.name_filter_var = tk.StringVar()
        self.cat_filter_var  = tk.StringVar()

        ttk.Entry(self._filter_frame, textvariable=self.code_filter_var, font=("", 13), width=1).grid(
            row=0, column=0, sticky="ew")
        ttk.Entry(self._filter_frame, textvariable=self.name_filter_var, font=("", 13), width=1).grid(
            row=0, column=1, sticky="ew")
        ttk.Entry(self._filter_frame, textvariable=self.cat_filter_var,  font=("", 13), width=1).grid(
            row=0, column=2, sticky="ew")
        # スクロールバー幅分のスペーサー（後で実幅に更新）
        self._sb_spacer = tk.Frame(self._filter_frame, bg="#181825", width=17)
        self._sb_spacer.grid(row=0, column=3)

        self._filter_frame.columnconfigure(0, minsize=62,  weight=0)
        self._filter_frame.columnconfigure(1, minsize=80,  weight=1)
        self._filter_frame.columnconfigure(2, minsize=88,  weight=0)
        self._filter_frame.columnconfigure(3, minsize=17,  weight=0)

        for var in (self.code_filter_var, self.name_filter_var, self.cat_filter_var):
            var.trace_add("write", lambda *_: self._apply_filter())

        # Treeview スタイル
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Stock.Treeview",
                        background="#1e1e2e", foreground="#cdd6f4",
                        fieldbackground="#1e1e2e", font=("", 15), rowheight=30)
        style.configure("Stock.Treeview.Heading",
                        background="#252535", foreground="#cdd6f4", font=("", 12, "bold"))
        style.map("Stock.Treeview",
                  background=[("selected", "#89b4fa")],
                  foreground=[("selected", "#1e1e2e")])

        tree_frame = tk.Frame(left, bg="#181825")
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        self._tree_sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        self._tree_sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree = ttk.Treeview(
            tree_frame,
            columns=("code", "name", "category"),
            show="headings",
            yscrollcommand=self._tree_sb.set,
            style="Stock.Treeview",
            selectmode="browse",
        )
        self.tree.heading("code",     text="コード")
        self.tree.heading("name",     text="銘柄名")
        self.tree.heading("category", text="分類")
        self.tree.column("code",     width=62,  minwidth=50, stretch=False)
        self.tree.column("name",     width=170, minwidth=80, stretch=True)
        self.tree.column("category", width=88,  minwidth=60, stretch=False)
        self.tree.tag_configure("today", foreground="#cdd6f4")
        self.tree.tag_configure("old",   foreground="#6c7086")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self._tree_sb.config(command=self.tree.yview)

        self._codes = self._load_my_codes()
        self._filtered_codes = self._codes[:]
        self._apply_filter()
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Configure>", lambda _: self._sync_filter_columns())
        self.after_idle(self._sync_filter_columns)
        self.bind("<Up>",   self._on_key_nav)
        self.bind("<Down>", self._on_key_nav)
        # Treeview 標準の↑↓移動との二重移動を防ぐ（"break" で標準処理を止める）
        self.tree.bind("<Up>",   self._on_key_nav)
        self.tree.bind("<Down>", self._on_key_nav)
        for w in (self, self.tree):
            w.bind("<Left>",  self._on_key_date)
            w.bind("<Right>", self._on_key_date)

        # 右パネル：チャート
        right = tk.Frame(content, bg="#1e1e2e")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8, pady=4)

        chart_top = tk.Frame(right, bg="#1e1e2e")
        chart_top.pack(fill=tk.X, pady=(2, 0))

        # 右端：分類チェックボックス・保存（RIGHT から積む）
        self.category_var = tk.StringVar()
        tk.Button(
            chart_top,
            text="保存",
            command=self._save_category,
            bg="#a6e3a1",
            fg="#1e1e2e",
            font=("", 17, "bold"),
            relief=tk.FLAT,
            padx=10,
        ).pack(side=tk.RIGHT, padx=(0, 4))
        self.chart_cat5_var = tk.BooleanVar()
        self.chart_cat4_var = tk.BooleanVar()
        self.chart_cat3_var = tk.BooleanVar()
        self.chart_cat2_var = tk.BooleanVar()
        self.chart_cat1_var = tk.BooleanVar()
        ckb_opts = dict(bg="#1e1e2e", fg="#cdd6f4", selectcolor="#1e1e2e",
                        activebackground="#1e1e2e", activeforeground="#cdd6f4",
                        font=("", 14), command=self._on_chart_cat_toggle)
        tk.Checkbutton(chart_top, text="監視(5)", variable=self.chart_cat5_var, **ckb_opts).pack(
            side=tk.RIGHT, padx=(0, 4))
        tk.Checkbutton(chart_top, text="注目(4)", variable=self.chart_cat4_var, **ckb_opts).pack(
            side=tk.RIGHT, padx=(0, 4))
        tk.Checkbutton(chart_top, text="前兆(3)", variable=self.chart_cat3_var, **ckb_opts).pack(
            side=tk.RIGHT, padx=(0, 4))
        tk.Checkbutton(chart_top, text="上昇(2)", variable=self.chart_cat2_var, **ckb_opts).pack(
            side=tk.RIGHT, padx=(0, 4))
        tk.Checkbutton(chart_top, text="出来高(1)", variable=self.chart_cat1_var, **ckb_opts).pack(
            side=tk.RIGHT, padx=(8, 4))

        # 左：ステータス → 縦倍率 → 横倍率
        self.status = tk.Label(
            chart_top, text="", bg="#1e1e2e", fg="#f38ba8", font=("", 16)
        )
        self.status.pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(chart_top, text="縦倍率:", bg="#1e1e2e", fg="#cdd6f4", font=("", 17)).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ratio_cb = ttk.Combobox(
            chart_top, textvariable=self.ratio_var,
            values=["1.5", "2.0", "3.0", "4.0"], width=4, font=("", 17), state="readonly"
        )
        ratio_cb.pack(side=tk.LEFT, padx=4)
        ratio_cb.bind("<<ComboboxSelected>>", lambda _: self._show_chart())

        tk.Label(chart_top, text="横倍率:", bg="#1e1e2e", fg="#cdd6f4", font=("", 17)).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        days_cb = ttk.Combobox(
            chart_top, textvariable=self.days_var,
            values=VIEW_DAYS_CHOICES, width=4, font=("", 17), state="readonly"
        )
        days_cb.pack(side=tk.LEFT, padx=4)
        days_cb.bind("<<ComboboxSelected>>", lambda _: self._show_chart())
        tk.Label(chart_top, text="日", bg="#1e1e2e", fg="#cdd6f4", font=("", 17)).pack(
            side=tk.LEFT, padx=(0, 4)
        )

        self.analyze_on = False
        self.analyze_btn = tk.Button(
            chart_top, text="分析", command=self._on_analyze,
            bg="#89b4fa", fg="#1e1e2e", font=("", 17, "bold"), relief=tk.FLAT, padx=10,
        )
        self.analyze_btn.pack(side=tk.LEFT, padx=4)

        self._rules_dlg = None
        tk.Button(
            chart_top, text="⚙", command=self._open_rules_editor,
            bg="#89b4fa", fg="#1e1e2e", font=("", 17, "bold"), relief=tk.FLAT, padx=6,
        ).pack(side=tk.LEFT, padx=(0, 4))

        self.nikkei_on = False
        self.nikkei_btn = tk.Button(
            chart_top, text="日経", command=self._on_nikkei,
            bg="#89b4fa", fg="#1e1e2e", font=("", 17, "bold"), relief=tk.FLAT, padx=10,
        )
        self.nikkei_btn.pack(side=tk.LEFT, padx=4)

        plt.style.use("dark_background")
        self.fig, (self.ax_price, self.ax_vol) = plt.subplots(
            2, 1, figsize=(10, 6), gridspec_kw={"height_ratios": [3, 1]}, facecolor="#1e1e2e"
        )
        self.ax_nk = self.ax_price.twinx()   # 日経平均を重ねる右軸（OFF時は非表示）
        self.ax_nk.set_visible(False)
        self.fig.subplots_adjust(hspace=0.05, bottom=0.12, right=0.80)

        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self._ch_vp = self._ch_vv = self._ch_hp = self._ch_hv = None
        self._val_text = None
        self._val_df = None
        self._val_dates = None
        self._nk_df = None
        self._nk_dates = None
        self._drag_press_x      = None
        self._drag_xlim          = None
        self._programmatic_select = False
        self._view_end           = None   # 表示最終日（None=データの最終日）
        self._view_code          = None
        self.canvas.mpl_connect("button_press_event",   self._on_button_press)
        self.canvas.mpl_connect("button_release_event", self._on_button_release)
        self.canvas.mpl_connect("motion_notify_event",  self._on_mouse_move)
        self.canvas.mpl_connect("axes_leave_event",     lambda _: self._hide_crosshair())
        self.canvas.mpl_connect("scroll_event",         self._on_scroll)

        self._show_chart()

    def _read_excel(self) -> pd.DataFrame | None:
        """my_codes.xlsx を読み込む。存在しない場合は CSV から生成して再試行。"""
        path     = os.path.join(CHART_DIR, "my_codes.xlsx")
        csv_path = os.path.join(CHART_DIR, "my_codes.csv")
        with self._xlsx_lock:
            if not os.path.exists(path):
                if os.path.exists(csv_path):
                    pd.read_csv(csv_path, dtype={"Code": str}).to_excel(path, index=False)
                else:
                    return None
            try:
                return pd.read_excel(path, dtype={"Code": str, "Category": str})
            except Exception:
                return None

    def _load_my_codes(self) -> list:
        df = self._read_excel()
        if df is None:
            return []
        df["Code"] = df["Code"].str.zfill(4)
        if "Category" not in df.columns:
            df["Category"] = ""
        df["Category"] = df["Category"].fillna("")
        if "DataDate" not in df.columns:
            df["DataDate"] = ""
        df["DataDate"] = pd.to_datetime(df["DataDate"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
        return list(zip(df["Code"], df["Name"], df["Category"], df["DataDate"]))

    def _sync_filter_columns(self):
        self.update_idletasks()
        code_w = self.tree.column("code",     "width")
        cat_w  = self.tree.column("category", "width")
        sb_w   = max(self._tree_sb.winfo_width(), 1)
        self._filter_frame.columnconfigure(0, minsize=code_w, weight=0)
        self._filter_frame.columnconfigure(2, minsize=cat_w,  weight=0)
        self._filter_frame.columnconfigure(3, minsize=sb_w,   weight=0)
        self._sb_spacer.configure(width=sb_w)

    def _on_key_nav(self, event):
        if isinstance(self.focus_get(), (ttk.Entry, tk.Entry)):
            return
        children = self.tree.get_children()
        if not children:
            return
        # 表示中のリスト順で現在位置を求める（選択が無ければ code_var の銘柄を参照）
        children = list(children)
        sel = self.tree.selection()
        cur = sel[0] if sel else None
        if cur is None:
            code = self.code_var.get().strip().zfill(4)
            for iid in children:
                if str(self.tree.item(iid)["values"][0]).zfill(4) == code:
                    cur = iid
                    break
        if cur is None:
            new_item = children[0] if event.keysym == "Down" else children[-1]
        else:
            idx = children.index(cur)
            if event.keysym == "Down":
                idx = min(idx + 1, len(children) - 1)
            else:
                idx = max(idx - 1, 0)
            new_item = children[idx]
        self._programmatic_select = True
        self.tree.selection_set(new_item)
        self.tree.see(new_item)
        self._programmatic_select = False
        code = str(self.tree.item(new_item)["values"][0]).zfill(4)
        self.code_var.set(code)
        self._load_category(code)
        self._download_and_show()
        return "break"

    def _on_tree_select(self, *_):
        if self._programmatic_select:
            return
        selection = self.tree.selection()
        if not selection:
            return
        code = str(self.tree.item(selection[0])["values"][0]).zfill(4)
        self.code_var.set(code)
        self._load_category(code)
        self._download_and_show()

    def _apply_filter(self):
        today = pd.Timestamp.today().strftime("%Y-%m-%d")
        code_q = self.code_filter_var.get().strip().lower()
        name_q = self.name_filter_var.get().strip().lower()
        cat_q  = self.cat_filter_var.get().strip().lower()
        cb1 = self.cat1_var.get()
        cb2 = self.cat2_var.get()
        cb3 = self.cat3_var.get()
        cb4 = self.cat4_var.get()
        cb5 = self.cat5_var.get()
        self._filtered_codes = [
            (c, n, cat, dd) for c, n, cat, dd in self._codes
            if (not code_q or code_q in c.lower())
            and (not name_q or name_q in n.lower())
            and (not cat_q  or cat_q  in cat.lower())
            and (not cb1 or "1" in cat)
            and (not cb2 or "2" in cat)
            and (not cb3 or "3" in cat)
            and (not cb4 or "4" in cat)
            and (not cb5 or "5" in cat)
        ]
        # 選択コードを保存（tree 選択 → code_var の順で参照）
        sel = self.tree.selection()
        if sel:
            selected_code = str(self.tree.item(sel[0])["values"][0]).zfill(4)
        else:
            selected_code = self.code_var.get().strip() or None

        self._programmatic_select = True
        self.tree.delete(*self.tree.get_children())
        for code, name, category, datadate in self._filtered_codes:
            tag = "today" if datadate == today else "old"
            iid = self.tree.insert("", tk.END, values=(code, name, category), tags=(tag,))
            if code == selected_code:
                self.tree.selection_set(iid)
                self.tree.see(iid)
        self._programmatic_select = False

    def _load_category(self, code: str):
        mc = self._read_excel()
        if mc is None:
            self.category_var.set("")
            self.chart_cat1_var.set(False)
            self.chart_cat2_var.set(False)
            return
        mc["Code"] = mc["Code"].str.zfill(4)
        row = mc[mc["Code"] == code]
        if not row.empty and "Category" in mc.columns:
            val = row["Category"].iloc[0]
            val = "" if pd.isna(val) else str(val)
            self.category_var.set(val)
            self.chart_cat1_var.set("1" in val)
            self.chart_cat2_var.set("2" in val)
            self.chart_cat3_var.set("3" in val)
            self.chart_cat4_var.set("4" in val)
            self.chart_cat5_var.set("5" in val)
        else:
            self.category_var.set("")
            self.chart_cat1_var.set(False)
            self.chart_cat2_var.set(False)
            self.chart_cat3_var.set(False)
            self.chart_cat4_var.set(False)
            self.chart_cat5_var.set(False)

    def _update_excel_row(self, code: str, updates: dict):
        import openpyxl
        path = os.path.join(CHART_DIR, "my_codes.xlsx")
        if not os.path.exists(path):
            return

        with self._xlsx_lock:
            try:
                # pandas で行番号を確実に特定
                df = pd.read_excel(path, dtype={"Code": str})
                df["Code"] = df["Code"].str.strip().str.zfill(4)
                matches = df.index[df["Code"] == code].tolist()
                if not matches:
                    return
                excel_row = matches[0] + 2  # DataFrame は 0 始まり、Excel は 1 始まり＋ヘッダ行

                wb = openpyxl.load_workbook(path)
                ws = wb.active

                # ヘッダ行から列名→列番号のマップを構築
                headers = {}
                max_col = 0
                for cell in ws[1]:
                    if cell.value is not None:
                        headers[str(cell.value).strip()] = cell.column
                        max_col = max(max_col, cell.column)

                # 存在しない列はヘッダ行末尾に追加
                for col_name in updates:
                    if col_name not in headers:
                        max_col += 1
                        ws.cell(row=1, column=max_col).value = col_name
                        headers[col_name] = max_col

                for col_name, value in updates.items():
                    ws.cell(row=excel_row, column=headers[col_name]).value = value

                wb.save(path)
            except Exception:
                pass

    def _on_chart_cat_toggle(self):
        cat = ("1" if self.chart_cat1_var.get() else "") + \
              ("2" if self.chart_cat2_var.get() else "") + \
              ("3" if self.chart_cat3_var.get() else "") + \
              ("4" if self.chart_cat4_var.get() else "") + \
              ("5" if self.chart_cat5_var.get() else "")
        self.category_var.set(cat)
        self._save_category()

    def _save_category(self):
        code = self.code_var.get().strip()
        if not code:
            return
        self._update_excel_row(code, {"Category": self.category_var.get().strip()})
        self._refresh_listbox()
        self.status.config(text=f"{code} の分類を保存しました")

    def _refresh_listbox(self):
        self._codes = self._load_my_codes()
        self._apply_filter()

    def _force_download(self):
        codes = [c for c, *_ in self._filtered_codes]
        if not codes:
            return
        total = len(codes)
        self.status.config(text=f"0 / {total} ダウンロード中...")
        self.update_idletasks()

        def task():
            errors = []
            try:
                ensure_nikkei()
            except Exception:
                pass   # 日経の取得失敗は個別株の更新を妨げない
            for i, code in enumerate(codes, 1):
                self.after(0, lambda i=i, c=code: self.status.config(
                    text=f"{i} / {total}  {c} ダウンロード中..."))
                try:
                    ticker = f"{code}.T"
                    data = yf.download(ticker, period="800d", interval="1d", progress=False)
                    if data.empty:
                        errors.append(code)
                        continue
                    data = data.tail(400)
                    data.to_csv(os.path.join(DATA_DIR, f"{code}.csv"))
                    self._update_excel_row(code, {"DataDate": datetime.today().replace(
                        hour=0, minute=0, second=0, microsecond=0)})
                except Exception:
                    errors.append(code)
                    continue
                try:
                    self._save_stats(code, load_csv(code))
                except Exception:
                    pass

            self.after(0, self._refresh_listbox)
            self.after(0, self._show_chart)
            if errors:
                msg = f"完了（失敗 {len(errors)} 件: {', '.join(errors[:5])}{'…' if len(errors) > 5 else ''}）"
            else:
                msg = f"{total} 件のダウンロードが完了しました"
            self.after(0, lambda: self.status.config(text=msg))

        threading.Thread(target=task, daemon=True).start()

    def _download_and_show(self):
        code = self.code_var.get().strip()
        if not code:
            return
        today = pd.Timestamp.today().strftime("%Y-%m-%d")
        datadate = next((dd for c, *_, dd in self._codes if c == code), "")
        if datadate == today:
            self._show_chart()
            return
        self.status.config(text=f"{code} をダウンロード中...")
        self.update_idletasks()

        def task():
            try:
                try:
                    ensure_nikkei()
                except Exception:
                    pass   # 日経の取得失敗は個別株の更新を妨げない（日経ON時に表示側でエラー表示）
                ticker = f"{code}.T"
                data = yf.download(ticker, period="800d", interval="1d", progress=False)
                if data.empty:
                    self.after(0, lambda: self.status.config(text=f"データ取得失敗: {ticker}"))
                    return
                data = data.tail(400)
                data.to_csv(os.path.join(DATA_DIR, f"{code}.csv"))
                self._update_excel_row(code, {"DataDate": datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)})
                self._save_stats(code, load_csv(code))
                self.after(0, self._refresh_listbox)
                self.after(0, self._show_chart)
            except Exception as e:
                msg = f"ダウンロードエラー: {e}"
                self.after(0, lambda m=msg: self.status.config(text=m))

        threading.Thread(target=task, daemon=True).start()

    def _init_crosshair(self):
        kw = dict(color="#6c7086", linewidth=0.8, linestyle="--", visible=False, zorder=10)
        self._ch_vp = self.ax_price.axvline(0, **kw)
        self._ch_vv = self.ax_vol.axvline(0, **kw)
        self._ch_hp = self.ax_price.axhline(0, **kw)
        self._ch_hv = self.ax_vol.axhline(0, **kw)

        # チャート右上（チャート外）の値表示（終値・MA5・MA5/MA25・MA25・MA75 を縦並び）
        self._val_text = self.ax_price.text(
            1.13, 1.0, "", transform=self.ax_price.transAxes, ha="left", va="top",
            fontsize=14, color="#cdd6f4", linespacing=1.6, zorder=11)

        # 日付ラベル（各チャート下端）・価格ラベル（各チャート左端）
        tkw = dict(
            color="#cdd6f4", fontsize=12, visible=False, zorder=11,
            bbox=dict(boxstyle="square,pad=0.2", fc="#313244", ec="none", alpha=0.9),
        )
        self._ch_date = {}
        self._ch_val = {}
        for ax in (self.ax_price, self.ax_vol):
            self._ch_date[ax] = ax.text(
                0, 0, "", ha="center", va="bottom",
                transform=blended_transform_factory(ax.transData, ax.transAxes), **tkw)
            self._ch_val[ax] = ax.text(
                0, 0, "", ha="left", va="center",
                transform=blended_transform_factory(ax.transAxes, ax.transData), **tkw)

    def _set_values(self, x=None):
        """チャート上部に終値・MA5/25/75を表示する。x=None のときは表示最終日の値。"""
        df = self._val_df
        if df is None or self._val_text is None:
            return
        if x is None:
            x = mdates.date2num(self._view_end)
        i = int(self._val_dates.searchsorted(x + 0.5, side="right")) - 1   # x を含む日（x 以前で最後の日）
        i = min(max(i, 0), len(df) - 1)
        r = df.iloc[i]

        def f(v):
            return f"{v:,.1f}" if pd.notna(v) else "-"

        ratio = f"{r['MA5'] / r['MA25']:.3f}" if pd.notna(r["MA5"]) and pd.notna(r["MA25"]) else "-"
        text = (f"{r['Date']:%Y/%m/%d}\n"
                f"終値  {f(r['Close'])}\n"
                f"MA5  {f(r['MA5'])}\n"
                f"MA5/MA25  {ratio}\n"
                f"MA25  {f(r['MA25'])}\n"
                f"MA75  {f(r['MA75'])}")
        if self._nk_df is not None and self._nk_dates is not None:
            j = int(self._nk_dates.searchsorted(x + 0.5, side="right")) - 1
            if j >= 0:
                text += f"\n日経  {f(self._nk_df['Close'].iloc[j])}"
        self._val_text.set_text(text)

    def _event_axes(self, event):
        """イベントのある軸。重ねた日経の右軸（ax_nk）は価格軸として扱う。"""
        return self.ax_price if event.inaxes is self.ax_nk else event.inaxes

    def _on_scroll(self, event):
        if self._event_axes(event) not in (self.ax_price, self.ax_vol):
            return
        ratios = ["1.5", "2.0", "3.0", "4.0"]
        cur = self.ratio_var.get()
        idx = ratios.index(cur) if cur in ratios else 1
        if event.step > 0:
            idx = max(idx - 1, 0)
        else:
            idx = min(idx + 1, len(ratios) - 1)
        self.ratio_var.set(ratios[idx])
        self._show_chart()

    def _on_button_press(self, event):
        if event.button == 1 and self._event_axes(event) in (self.ax_price, self.ax_vol):
            self._drag_press_x = event.x
            self._drag_xlim    = self.ax_price.get_xlim()
            self.canvas.get_tk_widget().config(cursor="fleur")

    def _on_button_release(self, event):
        if event.button == 1:
            self._drag_press_x = None
            self._drag_xlim    = None
            self.canvas.get_tk_widget().config(cursor="")

    def _on_mouse_move(self, event):
        # ドラッグスクロール
        if self._drag_press_x is not None and event.x is not None:
            xlim = self._drag_xlim
            ax_w = self.ax_price.get_position().width * self.fig.get_size_inches()[0] * self.fig.dpi
            if ax_w > 0:
                dx = (event.x - self._drag_press_x) * (xlim[1] - xlim[0]) / ax_w
                self.ax_price.set_xlim(xlim[0] - dx, xlim[1] - dx)
                self.ax_vol.set_xlim(xlim[0] - dx, xlim[1] - dx)
                update_period_title(self.ax_price)
            self.canvas.draw_idle()
            return

        # クロスヘア更新
        if self._ch_vp is None:
            return
        ax = self._event_axes(event)
        if ax not in (self.ax_price, self.ax_vol):
            self._hide_crosshair()
            return
        x, y = event.xdata, event.ydata
        if x is None or y is None:
            return
        if event.inaxes is self.ax_nk:
            # ydata は日経側の値なので、価格軸の値に変換し直す
            x, y = self.ax_price.transData.inverted().transform((event.x, event.y))
        self._ch_vp.set_xdata([x])
        self._ch_vv.set_xdata([x])
        self._ch_vp.set_visible(True)
        self._ch_vv.set_visible(True)
        if ax is self.ax_price:
            self._ch_hp.set_ydata([y])
            self._ch_hp.set_visible(True)
            self._ch_hv.set_visible(False)
        else:
            self._ch_hv.set_ydata([y])
            self._ch_hv.set_visible(True)
            self._ch_hp.set_visible(False)

        # ラベル更新（マウスのあるチャートにのみ表示）
        for other in (self.ax_price, self.ax_vol):
            visible = other is ax
            self._ch_date[other].set_visible(visible)
            self._ch_val[other].set_visible(visible)
        self._set_values(x)
        self._ch_date[ax].set_x(x)
        self._ch_date[ax].set_text(mdates.num2date(x).strftime("%Y/%m/%d"))
        self._ch_val[ax].set_y(y)
        self._ch_val[ax].set_text(f"{y:,.1f}" if ax is self.ax_price else f"{y:,.2f}")
        self.canvas.draw_idle()

    def _hide_crosshair(self):
        if self._ch_vp is None:
            return
        for line in (self._ch_vp, self._ch_vv, self._ch_hp, self._ch_hv,
                     *self._ch_date.values(), *self._ch_val.values()):
            line.set_visible(False)
        self._set_values(None)
        self.canvas.draw_idle()

    def _on_key_date(self, event):
        """←/→ で表示最終日を 1 日戻す／進める。"""
        if isinstance(self.focus_get(), (ttk.Entry, tk.Entry, ttk.Combobox)):
            return
        if self._view_end is None:
            return "break"
        step = -1 if event.keysym == "Left" else 1
        self._view_end = self._view_end + pd.Timedelta(days=step)
        self._show_chart()
        return "break"

    def _on_analyze(self):
        """分析（分類2の日の背景ハイライト）のON/OFFを切り替える。"""
        self.analyze_on = not self.analyze_on
        self.analyze_btn.config(bg=analysis_button_color(self.analyze_on))
        self._show_chart()

    def _open_rules_editor(self):
        """analysis_rules.json の編集ダイアログを開く（開いていれば前面に出す）。"""
        if self._rules_dlg is not None and self._rules_dlg.winfo_exists():
            self._rules_dlg.lift()
            return
        try:
            self._rules_dlg = RulesEditor(self, RULES_PATH, check=self._check_rules,
                                          on_saved=self._on_rules_saved)
        except Exception as e:
            self.status.config(text=f"エラー: {e}")

    def _check_rules(self, rules: dict):
        """表示中の銘柄で条件式を評価してみる（データが無ければ省略）。不正なら例外。"""
        try:
            df = load_csv(self.code_var.get().strip())
        except Exception:
            return
        highlight_layers(df, rules)

    def _on_rules_saved(self):
        _rules_cache["mtime"] = None
        self.analyze_btn.config(bg=analysis_button_color(self.analyze_on))
        self.nikkei_btn.config(bg=analysis_button_color(self.nikkei_on))
        self._show_chart()

    def _on_nikkei(self):
        """日経平均の重ね表示のON/OFFを切り替える。"""
        self.nikkei_on = not self.nikkei_on
        self.nikkei_btn.config(bg=analysis_button_color(self.nikkei_on))
        self._show_chart()

    def _load_nikkei(self) -> pd.DataFrame | None:
        """日経ON時のみ日経平均を読み込む（無い／古ければダウンロード）。"""
        if not self.nikkei_on:
            return None
        ensure_nikkei()
        return load_csv(NIKKEI_CODE)

    def _show_chart(self):
        code = self.code_var.get().strip()
        if not code:
            return
        try:
            df = load_csv(code)
            nk_df = self._load_nikkei()
            name = next((n for c, n, *_ in self._codes if c == code), "")
            # 表示最終日：銘柄が変わったらデータの最終日に戻し、データ範囲内に収める
            first, last = df["Date"].iloc[0], df["Date"].iloc[-1]
            if code != self._view_code or self._view_end is None:
                self._view_code = code
                self._view_end = last
            self._view_end = min(max(self._view_end, first), last)
            draw_candlestick(self.ax_price, self.ax_vol, df, code, name,
                             ratio=float(self.ratio_var.get()), view_end=self._view_end,
                             highlight=self.analyze_on, ax_nk=self.ax_nk, nk_df=nk_df,
                             view_days=int(self.days_var.get()))
            self._nk_df = nk_df
            self._nk_dates = (mdates.date2num(nk_df["Date"].to_numpy().astype("datetime64[ms]").astype(object))
                              if nk_df is not None else None)
            self._val_df = df.assign(
                MA5=df["Close"].rolling(5).mean(),
                MA25=df["Close"].rolling(25).mean(),
                MA75=df["Close"].rolling(75).mean(),
            )
            self._val_dates = mdates.date2num(df["Date"].to_numpy().astype("datetime64[ms]").astype(object))
            self._init_crosshair()
            self._set_values(None)
            self.canvas.draw()
            self.status.config(text=f"{len(df)}件のデータを読み込みました")
        except FileNotFoundError as e:
            self.status.config(text=str(e))
        except Exception as e:
            self.status.config(text=f"エラー: {e}")

    def _save_stats(self, code: str, df: pd.DataFrame):
        stats = calc_stats(df)
        new_cat = ""
        if stats.get("TV75Above10"):
            new_cat += "1"
        if stats.get("Trend"):
            new_cat += "2"
        # 分類3: 分析ルール strong の背景が最終日に付く（ルールが読めなければ従来値を引き継ぐ）
        strong_last = None
        try:
            strong_last = bool(rule_mask(df, "strong").iloc[-1])
        except Exception:
            pass
        if strong_last:
            new_cat += "3"
        # 手動設定の分類4・5（ルールが使えないときは3も）は保持する
        mc = self._read_excel()
        if mc is not None and "Category" in mc.columns:
            mc["Code"] = mc["Code"].str.zfill(4)
            row = mc[mc["Code"] == code]
            if not row.empty:
                old = row["Category"].iloc[0]
                old = "" if pd.isna(old) else str(old)
                keep = "45" if strong_last is not None else "345"
                new_cat += "".join(c for c in keep if c in old)
        stats["Category"] = new_cat
        self._update_excel_row(code, stats)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = ChartApp()
    app.mainloop()
