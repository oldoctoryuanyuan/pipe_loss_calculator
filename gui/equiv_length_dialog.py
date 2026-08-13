# gui/equiv_length_dialog.py
"""
当量长度分配明细对话框（非模态）

显示每个管件（弯头/异径/阀门/三通/四通）的当量长度分配给了哪些管道，
支持按管件类型筛选、双击行跳转预览定位。此对话框不关闭不影响用户切换
程序标签页面、查看预览画布。
"""
import tkinter as tk
from tkinter import ttk
from typing import Dict

FILTER_ALL = "全部"
FILTERS = [FILTER_ALL, "三通直通", "三通侧通", "四通直通", "四通侧通", "四通混合",
           "45弯头", "90弯头", "异径", "蝶阀"]


def _is_match(ftype: str, cat: str, filter_key: str) -> bool:
    """按筛选关键字匹配行（ftype=管件类型, cat=类别）"""
    if filter_key == FILTER_ALL:
        return True
    if filter_key in ("三通直通", "三通侧通", "四通直通", "四通侧通", "四通混合"):
        return cat == filter_key
    if filter_key == "蝶阀":
        return ftype == "蝶阀"
    if filter_key == "异径":
        return ftype == "异径"
    return ftype == filter_key


def show_equiv_length_dialog(calc_page, analysis, l_current, cad,
                             kinds: Dict = None):
    """弹出当量长度分配明细对话框。

    :param calc_page: 计算页面实例（用于跳转预览）
    :param analysis:  FittingAnalysisResult（管件分类 + 静态当量）
    :param l_current: {(node_id, pipe_id): 动态当量长度}
    :param cad:       CADDataManager（用于查管道管径、阀门）
    :param kinds:     {(node_id, pipe_id): 直通/侧通/混合}（用于类别细分）
    """
    from core.equiv_length_engine import collect_equiv_detail_rows

    dialog = tk.Toplevel(calc_page)
    dialog.title("当量长度分配明细")
    dialog.resizable(True, True)

    # 相对计算页居中定位
    try:
        calc_page.update_idletasks()
        x = calc_page.winfo_rootx() + (calc_page.winfo_width() - 720) // 2
        y = calc_page.winfo_rooty() + (calc_page.winfo_height() - 480) // 2
        dialog.geometry(f"720x480+{max(x, 0)}+{max(y, 0)}")
    except Exception:
        pass

    rows = collect_equiv_detail_rows(analysis, l_current, cad, kinds)

    # 顶部：筛选下拉 + 计数
    top = ttk.Frame(dialog)
    top.pack(fill="x", padx=10, pady=(10, 5))
    ttk.Label(top, text="筛选:").pack(side="left")
    filter_var = tk.StringVar(value=FILTER_ALL)
    combo = ttk.Combobox(top, textvariable=filter_var, values=FILTERS,
                         state="readonly", width=10)
    combo.pack(side="left", padx=(4, 10))
    count_var = tk.StringVar(value=f"共 {len(rows)} 条")
    ttk.Label(top, textvariable=count_var).pack(side="left")
    ttk.Label(top, text="双击行可在预览中定位").pack(side="right")

    # 明细表格
    tree_frame = ttk.Frame(dialog)
    tree_frame.pack(fill="both", expand=True, padx=10, pady=5)
    columns = ("node", "ftype", "dn", "pipe", "value", "cat", "note")
    headers = ("节点/阀门", "管件类型", "管径", "分配管道", "当量长度(m)", "类别", "说明")
    widths = {"node": 100, "ftype": 70, "dn": 60, "pipe": 90,
              "value": 90, "cat": 90, "note": 220}
    tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=18)
    for col, h in zip(columns, headers):
        tree.heading(col, text=h)
    for col, w in widths.items():
        tree.column(col, width=w)
    vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    vsb.pack(side="right", fill="y")
    hsb.pack(side="bottom", fill="x")
    tree.pack(fill="both", expand=True)

    def refresh(_=None):
        tree.delete(*tree.get_children())
        fk = filter_var.get()
        n = 0
        for r in rows:
            if not _is_match(r.get("管件类型", ""), r.get("类别", ""), fk):
                continue
            tree.insert("", "end", values=(
                r.get("节点", ""),
                r.get("管件类型", ""),
                r.get("管径", ""),
                r.get("分配管道", ""),
                r.get("当量长度(m)", 0.0),
                r.get("类别", ""),
                r.get("说明", ""),
            ))
            n += 1
        count_var.set(f"共 {n} 条")

    combo.bind("<<ComboboxSelected>>", refresh)
    refresh()

    def on_double(event):
        item = tree.focus()
        if not item:
            return
        vals = tree.item(item, "values")
        if not vals:
            return
        node_id = vals[0]
        pipe_id = vals[3]
        try:
            preview = calc_page._switch_to_preview()
            if preview is None:
                return
            # 优先定位节点（真实管网节点），否则定位管道（阀门等行）
            if node_id and cad and cad.node_by_id.get(node_id):
                preview.jump_to_node(node_id, to_global=True)
            elif pipe_id:
                preview.jump_to_pipe(pipe_id, to_global=True)
        except Exception:
            pass

    tree.bind("<Double-1>", on_double)

    btn = ttk.Button(dialog, text="关闭", command=dialog.destroy)
    btn.pack(pady=(0, 10))

    return dialog
