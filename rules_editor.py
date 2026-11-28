"""analysis_rules.json を編集するダイアログ。

本体（kabufilter.py）からは RulesEditor(master, path, check=..., on_saved=...) で開く。
- check(data): 保存前に呼ばれる検証関数。条件式が不正なら例外を投げる。
- on_saved(): 保存後に呼ばれる（チャートの再描画など）。
編集画面に出ない項目（_readme、_comment 以外のダミーキー、color_x など）はそのまま保持する。
"""
import copy
import json
import os
import re
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser

BG = "#1e1e2e"
PANEL = "#181825"
FG = "#cdd6f4"
ENTRY_BG = "#313244"
ACCENT = "#89b4fa"
ERR = "#f38ba8"
OK = "#a6e3a1"

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED = {"Open", "High", "Low", "Close", "Volume", "and", "or", "not", "True", "False"}


# ---------------------------------------------------------------- 純粋関数

def format_rules_json(data, width: int = 100) -> str:
    """設定を JSON 文字列にする。入れ子のない短い dict/list は1行にまとめる。"""
    def dump(v):
        return json.dumps(v, ensure_ascii=False)

    def fmt(v, level):
        pad = "  " * level
        inner = "  " * (level + 1)
        if isinstance(v, dict):
            if not v:
                return "{}"
            if all(not isinstance(x, (dict, list)) or not x for x in v.values()):
                one = "{ " + ", ".join(f"{dump(k)}: {dump(x)}" for k, x in v.items()) + " }"
                if len(pad) + len(one) <= width:
                    return one
            items = [f"{inner}{dump(k)}: {fmt(x, level + 1)}" for k, x in v.items()]
            return "{\n" + ",\n".join(items) + "\n" + pad + "}"
        if isinstance(v, list):
            if not v:
                return "[]"
            if all(not isinstance(x, (dict, list)) for x in v):
                one = "[" + ", ".join(dump(x) for x in v) + "]"
                if len(pad) + len(one) <= width:
                    return one
            items = [f"{inner}{fmt(x, level + 1)}" for x in v]
            return "[\n" + ",\n".join(items) + "\n" + pad + "]"
        return dump(v)

    return fmt(data, 0) + "\n"


def parse_int_list(text: str) -> list:
    """'5, 25, 75' → [5, 25, 75]。数値にできない要素は文字列のまま残す（検証で弾く）。"""
    out = []
    for s in re.split(r"[,\s、]+", text.strip()):
        if not s:
            continue
        try:
            out.append(int(s))
        except ValueError:
            out.append(s)
    return out


def parse_name_list(text: str) -> list:
    """'weak, strong' → ['weak', 'strong']"""
    return [s for s in re.split(r"[,\s、]+", text.strip()) if s]


def validate_rules(data: dict) -> list:
    """設定の形式を検証し、エラーメッセージのリストを返す（空なら OK）。条件式の中身は見ない。"""
    errors = []
    mas = data.get("moving_averages", [])
    if not isinstance(mas, list):
        errors.append("移動平均: リストで指定してください")
        mas = []
    for n in mas:
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            errors.append(f"移動平均: '{n}' は1以上の整数ではありません")

    rules = data.get("rules")
    if not isinstance(rules, list):
        return errors + ["rules がありません"]

    names = []
    for i, r in enumerate(rules, 1):
        name = r.get("name", "")
        label = f"ルール{i}({name or '名前なし'})"
        if not name:
            errors.append(f"{label}: 名前が空です")
        elif not _NAME_RE.match(name):
            errors.append(f"{label}: 名前は英字・数字・_ で、先頭は英字か _ にしてください")
        elif name in _RESERVED or re.fullmatch(r"MA\d+", name):
            errors.append(f"{label}: 名前 '{name}' は予約語です")
        elif name in names:
            errors.append(f"{label}: 名前 '{name}' が重複しています")
        if not str(r.get("when", "")).strip():
            errors.append(f"{label}: 条件式が空です")
        alpha = r.get("alpha", 0.15)
        if not isinstance(alpha, (int, float)) or isinstance(alpha, bool) or not 0 <= alpha <= 1:
            errors.append(f"{label}: 濃さ(alpha)は 0〜1 の数値にしてください")
        layers = r.get("layers", 1)
        if not isinstance(layers, int) or isinstance(layers, bool) or layers < 1:
            errors.append(f"{label}: 重ね塗り(layers)は1以上の整数にしてください")
        names.append(name)

    all_names = set(names)
    for i, r in enumerate(rules, 1):
        for ex in r.get("exclude", []):
            if ex not in all_names:
                errors.append(f"ルール{i}({r.get('name', '')}): 除外 '{ex}' というルールはありません")
    return errors


def rename_in_excludes(rules: list, old: str, new: str):
    """ルール名の変更を、他のルールの exclude にも反映する。"""
    for r in rules:
        if "exclude" in r:
            r["exclude"] = [new if x == old else x for x in r["exclude"]]


# ---------------------------------------------------------------- ダイアログ

class RulesEditor(tk.Toplevel):
    def __init__(self, master, path: str, check=None, on_saved=None):
        super().__init__(master)
        self.path = path
        self.check = check
        self.on_saved = on_saved
        self.title("分析設定（analysis_rules.json）")
        self.geometry("1000x680")
        self.configure(bg=BG)
        self.transient(master)

        with open(path, encoding="utf-8") as f:
            self.data = json.load(f)
        self.data.setdefault("rules", [])
        self._saved_text = format_rules_json(self.data)
        self._cur = None          # 編集中のルールの index
        self._loading = False     # フォームへ値を流し込み中は変更検知しない

        self._build()
        self._load_general()
        self._refresh_list(select=0 if self.data["rules"] else None)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-s>", lambda _: self._save())
        self.grab_set()
        self.focus_set()

    # ---------- 部品
    def _label(self, parent, text, **kw):
        return tk.Label(parent, text=text, bg=kw.pop("bg", BG), fg=kw.pop("fg", FG),
                        font=kw.pop("font", ("", 13)), **kw)

    def _entry(self, parent, var, width=30):
        return tk.Entry(parent, textvariable=var, width=width, bg=ENTRY_BG, fg=FG,
                        insertbackground=FG, font=("", 13), relief=tk.FLAT)

    def _button(self, parent, text, cmd, bg=ACCENT, width=None):
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=BG, font=("", 12, "bold"),
                         relief=tk.FLAT, padx=8, width=width)

    def _color_field(self, parent, var):
        """色入力欄＋見本ボタン（押すと色選択ダイアログ）。"""
        f = tk.Frame(parent, bg=BG)
        self._entry(f, var, width=10).pack(side=tk.LEFT)
        sw = tk.Button(f, width=3, relief=tk.FLAT, command=lambda: self._pick_color(var))
        sw.pack(side=tk.LEFT, padx=6)

        def update(*_):
            c = var.get().strip()
            try:
                self.winfo_rgb(c)
                sw.config(bg=c, activebackground=c, text="")
            except tk.TclError:
                sw.config(bg=ENTRY_BG, activebackground=ENTRY_BG, text="?")
        var.trace_add("write", update)
        update()
        return f

    def _pick_color(self, var):
        try:
            initial = var.get().strip() or None
            self.winfo_rgb(initial or "#ffffff")
        except tk.TclError:
            initial = None
        _, hexcolor = colorchooser.askcolor(initialcolor=initial, parent=self)
        if hexcolor:
            var.set(hexcolor)

    # ---------- 画面構築
    def _build(self):
        style = ttk.Style(self)
        style.configure("Rules.TNotebook", background=BG)
        style.configure("Rules.TNotebook.Tab", font=("", 13), padding=(12, 4))

        nb = ttk.Notebook(self, style="Rules.TNotebook")
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 4))
        rules_tab = tk.Frame(nb, bg=BG)
        general_tab = tk.Frame(nb, bg=BG)
        nb.add(rules_tab, text="分析ルール")
        nb.add(general_tab, text="移動平均・色")
        self._build_rules_tab(rules_tab)
        self._build_general_tab(general_tab)

        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill=tk.X, padx=10, pady=(4, 10))
        self.msg = self._label(bottom, "", fg=ERR, anchor="w", justify=tk.LEFT, wraplength=700)
        self.msg.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._button(bottom, "閉じる", self._on_close, bg="#6c7086").pack(side=tk.RIGHT, padx=4)
        self._button(bottom, "保存", self._save, bg="#b8e6a0").pack(side=tk.RIGHT, padx=4)
        self._button(bottom, "検証", self._validate_only).pack(side=tk.RIGHT, padx=4)

    def _build_rules_tab(self, tab):
        left = tk.Frame(tab, bg=PANEL)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10), pady=6)
        self._label(left, "ルール（上から順に評価）", bg=PANEL).pack(anchor="w", padx=6, pady=(6, 2))
        self.listbox = tk.Listbox(left, width=22, height=14, bg=ENTRY_BG, fg=FG, font=("", 14),
                                  selectbackground=ACCENT, selectforeground=BG,
                                  exportselection=False, relief=tk.FLAT, activestyle="none")
        self.listbox.pack(fill=tk.Y, expand=True, padx=6)
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)

        btns = tk.Frame(left, bg=PANEL)
        btns.pack(pady=6)
        for i, (t, c) in enumerate([("追加", self._add_rule), ("複製", self._dup_rule),
                                    ("削除", self._del_rule), ("↑", lambda: self._move_rule(-1)),
                                    ("↓", lambda: self._move_rule(1))]):
            self._button(btns, t, c, width=4).grid(row=i // 3, column=i % 3, padx=2, pady=2)

        form = tk.Frame(tab, bg=BG)
        form.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=6)
        form.columnconfigure(1, weight=1)
        self.form = form

        self.v_name = tk.StringVar()
        self.v_comment = tk.StringVar()
        self.v_exclude = tk.StringVar()
        self.v_color = tk.StringVar()
        self.v_alpha = tk.StringVar()
        self.v_layers = tk.StringVar()
        self.v_enabled = tk.BooleanVar(value=True)

        row = 0

        def add(label, widget, hint=None):
            nonlocal row
            self._label(form, label).grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=5)
            widget.grid(row=row, column=1, sticky="we", pady=5)
            row += 1
            if hint:
                self._label(form, hint, fg="#7f849c", font=("", 11), anchor="w",
                            justify=tk.LEFT).grid(row=row, column=1, sticky="w")
                row += 1

        add("名前", self._entry(form, self.v_name), "英字・数字・_。他のルールの条件式や除外から参照できる")
        add("メモ", self._entry(form, self.v_comment))
        self.t_when = tk.Text(form, height=4, bg=ENTRY_BG, fg=FG, insertbackground=FG,
                              font=("Consolas", 13), relief=tk.FLAT, wrap=tk.WORD)
        self.t_when.bind("<<Modified>>", self._on_when_modified)
        self.when_hint = self._label(form, "", fg="#7f849c", font=("", 11), anchor="w",
                                     justify=tk.LEFT, wraplength=600)
        add("条件式", self.t_when)
        self.when_hint.grid(row=row, column=1, sticky="w")
        row += 1
        add("除外", self._entry(form, self.v_exclude), "ここに挙げたルールが成立する日は塗らない（カンマ区切り）")
        add("背景色", self._color_field(form, self.v_color))
        add("濃さ(alpha)", tk.Spinbox(form, textvariable=self.v_alpha, from_=0, to=1, increment=0.05,
                                      width=8, bg=ENTRY_BG, fg=FG, buttonbackground=ENTRY_BG,
                                      insertbackground=FG, font=("", 13), relief=tk.FLAT),
            "1回あたりの濃さ 0〜1")
        add("重ね塗り(layers)", tk.Spinbox(form, textvariable=self.v_layers, from_=1, to=10, increment=1,
                                         width=8, bg=ENTRY_BG, fg=FG, buttonbackground=ENTRY_BG,
                                         insertbackground=FG, font=("", 13), relief=tk.FLAT),
            "重ねる回数（濃さの調整）")
        add("有効", tk.Checkbutton(form, variable=self.v_enabled, bg=BG, fg=FG, selectcolor=ENTRY_BG,
                                 activebackground=BG, activeforeground=FG,
                                 text="背景を塗る（OFFでも他ルールからの参照用には評価される）",
                                 font=("", 12), anchor="w"))

        for v in (self.v_name, self.v_comment, self.v_exclude, self.v_color,
                  self.v_alpha, self.v_layers, self.v_enabled):
            v.trace_add("write", lambda *_: self._commit_form())

    def _build_general_tab(self, tab):
        f = tk.Frame(tab, bg=BG)
        f.pack(anchor="nw", padx=10, pady=10)
        self.g = {k: tk.StringVar() for k in
                  ("ma", "btn_on", "btn_off", "up", "down", "nk_line", "nk_alpha")}
        rows = [
            ("移動平均の期間", self._entry(f, self.g["ma"], width=20),
             "カンマ区切り。条件式から MA5, MA25 のように参照できる"),
            ("分析ボタン ON", self._color_field(f, self.g["btn_on"]), None),
            ("分析ボタン OFF", self._color_field(f, self.g["btn_off"]), None),
            ("ローソク足 陽線", self._color_field(f, self.g["up"]), "終値 >= 始値（出来高も同色）"),
            ("ローソク足 陰線", self._color_field(f, self.g["down"]), None),
            ("日経平均 線の色", self._color_field(f, self.g["nk_line"]), None),
            ("日経平均 不透明度", self._entry(f, self.g["nk_alpha"], width=8), "0〜1"),
        ]
        r = 0
        for label, w, hint in rows:
            self._label(f, label).grid(row=r, column=0, sticky="w", padx=(0, 12), pady=6)
            w.grid(row=r, column=1, sticky="w", pady=6)
            if hint:
                self._label(f, hint, fg="#7f849c", font=("", 11)).grid(row=r, column=2, sticky="w", padx=10)
            r += 1

    # ---------- 全般タブ
    def _load_general(self):
        d = self.data
        self.g["ma"].set(", ".join(str(x) for x in d.get("moving_averages", [])))
        self.g["btn_on"].set(d.get("button_colors", {}).get("on", "#b8e6a0"))
        self.g["btn_off"].set(d.get("button_colors", {}).get("off", "#89b4fa"))
        self.g["up"].set(d.get("candle_colors", {}).get("up", "#e74c3c"))
        self.g["down"].set(d.get("candle_colors", {}).get("down", "#2ecc71"))
        self.g["nk_line"].set(d.get("nikkei_colors", {}).get("line", "#f9e2af"))
        self.g["nk_alpha"].set(str(d.get("nikkei_colors", {}).get("alpha", 0.8)))
        self.g["ma"].trace_add("write", lambda *_: self._update_when_hint())

    def _collect_general(self) -> list:
        """全般タブの値を self.data に反映し、エラーのリストを返す。"""
        errors = []
        d = self.data
        d["moving_averages"] = parse_int_list(self.g["ma"].get())
        d.setdefault("button_colors", {}).update(on=self.g["btn_on"].get().strip(),
                                                 off=self.g["btn_off"].get().strip())
        d.setdefault("candle_colors", {}).update(up=self.g["up"].get().strip(),
                                                 down=self.g["down"].get().strip())
        nk = d.setdefault("nikkei_colors", {})
        nk["line"] = self.g["nk_line"].get().strip()
        try:
            a = float(self.g["nk_alpha"].get())
            if not 0 <= a <= 1:
                raise ValueError
            nk["alpha"] = a
        except ValueError:
            errors.append("日経平均 不透明度: 0〜1 の数値にしてください")
        return errors

    # ---------- ルール一覧
    def _refresh_list(self, select=None):
        self.listbox.delete(0, tk.END)
        for r in self.data["rules"]:
            mark = "" if r.get("enabled", True) else "（無効）"
            self.listbox.insert(tk.END, f"{r.get('name', '')}{mark}")
        if select is not None and self.data["rules"]:
            select = max(0, min(select, len(self.data["rules"]) - 1))
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(select)
            self.listbox.see(select)
            self._show_rule(select)
        else:
            self._show_rule(None)

    def _on_list_select(self, _=None):
        sel = self.listbox.curselection()
        if sel and sel[0] != self._cur:
            self._show_rule(sel[0])

    def _show_rule(self, idx):
        self._cur = idx
        self._loading = True
        try:
            r = self.data["rules"][idx] if idx is not None else {}
            self.v_name.set(r.get("name", ""))
            self.v_comment.set(r.get("_comment", ""))
            self.v_exclude.set(", ".join(r.get("exclude", [])))
            self.v_color.set(r.get("color", "#b8e6a0") if r else "")
            self.v_alpha.set(str(r.get("alpha", 0.15)) if r else "")
            self.v_layers.set(str(r.get("layers", 1)) if r else "")
            self.v_enabled.set(r.get("enabled", True))
            self.t_when.delete("1.0", tk.END)
            self.t_when.insert("1.0", r.get("when", ""))
            self.t_when.edit_modified(False)
            state = tk.NORMAL if r else tk.DISABLED
            for w in self.form.winfo_children():
                try:
                    w.config(state=state)
                except tk.TclError:
                    pass
        finally:
            self._loading = False
        self._update_when_hint()

    def _update_when_hint(self):
        ma = " ".join(f"MA{x}" for x in parse_int_list(self.g["ma"].get()) if isinstance(x, int))
        above = [r.get("name", "") for r in self.data["rules"][: self._cur or 0]]
        text = f"使える名前: Open High Low Close Volume {ma}"
        if above:
            text += " / 上のルール: " + " ".join(above)
        text += "\n演算: + - * / > < >= <= == and or not ( )"
        self.when_hint.config(text=text)

    def _on_when_modified(self, _=None):
        if self.t_when.edit_modified():
            self.t_when.edit_modified(False)
            self._commit_form()

    def _commit_form(self):
        """フォームの内容を編集中のルールへ書き戻す。"""
        if self._loading or self._cur is None:
            return
        r = self.data["rules"][self._cur]
        new_name = self.v_name.get().strip()
        old_name = r.get("name", "")
        if new_name != old_name:
            others = {x.get("name") for i, x in enumerate(self.data["rules"]) if i != self._cur}
            if old_name not in others and new_name not in others:
                rename_in_excludes(self.data["rules"], old_name, new_name)
            r["name"] = new_name

        comment = self.v_comment.get().strip()
        if comment:
            r["_comment"] = comment
        else:
            r.pop("_comment", None)
        r["when"] = " ".join(self.t_when.get("1.0", tk.END).split())
        excl = parse_name_list(self.v_exclude.get())
        if excl:
            r["exclude"] = excl
        else:
            r.pop("exclude", None)
        r["color"] = self.v_color.get().strip()
        try:
            r["alpha"] = float(self.v_alpha.get())
        except ValueError:
            r["alpha"] = self.v_alpha.get()
        try:
            r["layers"] = int(self.v_layers.get())
        except ValueError:
            r["layers"] = self.v_layers.get()
        if "enabled" in r or not self.v_enabled.get():
            r["enabled"] = bool(self.v_enabled.get())

        mark = "" if r.get("enabled", True) else "（無効）"
        label = f"{new_name}{mark}"
        if self.listbox.get(self._cur) != label:
            self.listbox.delete(self._cur)
            self.listbox.insert(self._cur, label)
            self.listbox.selection_set(self._cur)

    def _add_rule(self):
        names = {r.get("name") for r in self.data["rules"]}
        i = 1
        while f"rule{i}" in names:
            i += 1
        rule = {"name": f"rule{i}", "when": "Close > MA25", "color": "#b8e6a0",
                "alpha": 0.15, "layers": 1}
        pos = len(self.data["rules"]) if self._cur is None else self._cur + 1
        self.data["rules"].insert(pos, rule)
        self._refresh_list(select=pos)

    def _dup_rule(self):
        if self._cur is None:
            return
        rule = copy.deepcopy(self.data["rules"][self._cur])
        names = {r.get("name") for r in self.data["rules"]}
        base = rule.get("name", "rule")
        i = 2
        while f"{base}_{i}" in names:
            i += 1
        rule["name"] = f"{base}_{i}"
        self.data["rules"].insert(self._cur + 1, rule)
        self._refresh_list(select=self._cur + 1)

    def _del_rule(self):
        if self._cur is None:
            return
        name = self.data["rules"][self._cur].get("name", "")
        if not messagebox.askyesno("削除", f"ルール '{name}' を削除しますか？", parent=self):
            return
        del self.data["rules"][self._cur]
        self._refresh_list(select=self._cur)

    def _move_rule(self, step):
        i = self._cur
        if i is None or not 0 <= i + step < len(self.data["rules"]):
            return
        rules = self.data["rules"]
        rules[i], rules[i + step] = rules[i + step], rules[i]
        self._refresh_list(select=i + step)

    # ---------- 検証・保存
    def _color_errors(self) -> list:
        errors = []
        checks = [("分析ボタン ON", self.data["button_colors"]["on"]),
                  ("分析ボタン OFF", self.data["button_colors"]["off"]),
                  ("ローソク足 陽線", self.data["candle_colors"]["up"]),
                  ("ローソク足 陰線", self.data["candle_colors"]["down"]),
                  ("日経平均 線の色", self.data["nikkei_colors"]["line"])]
        checks += [(f"ルール '{r.get('name', '')}' の背景色", r.get("color", "#b8e6a0"))
                   for r in self.data["rules"]]
        for label, c in checks:
            try:
                self.winfo_rgb(c)
            except (tk.TclError, TypeError):
                errors.append(f"{label}: '{c}' は色として使えません")
        return errors

    def _validate(self) -> bool:
        self._commit_form()
        errors = self._collect_general() + validate_rules(self.data) + self._color_errors()
        if not errors and self.check is not None:
            try:
                self.check(self.data)
            except Exception as e:
                errors.append(str(e))
        if errors:
            self.msg.config(text="\n".join(errors[:5]) + ("\n…" if len(errors) > 5 else ""), fg=ERR)
            return False
        return True

    def _validate_only(self):
        if self._validate():
            self.msg.config(text="問題ありません", fg=OK)

    def _save(self):
        if not self._validate():
            return
        text = format_rules_json(self.data)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, self.path)
        self._saved_text = text
        self.msg.config(text="保存しました", fg=OK)
        if self.on_saved is not None:
            self.on_saved()

    def _dirty(self) -> bool:
        self._commit_form()
        self._collect_general()
        return format_rules_json(self.data) != self._saved_text

    def _on_close(self):
        if self._dirty():
            ans = messagebox.askyesnocancel("閉じる", "変更を保存しますか？", parent=self)
            if ans is None:
                return
            if ans:
                self._save()
                if format_rules_json(self.data) != self._saved_text:
                    return   # 検証エラーで保存できなかった
        self.grab_release()
        self.destroy()
