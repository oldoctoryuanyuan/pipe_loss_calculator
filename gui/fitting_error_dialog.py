# gui/fitting_error_dialog.py
"""
管件画图错误/不严谨列表对话框（非模态）
标出对应节点编号及错误原因，此对话框不关闭不影响用户切换程序标签页面、查看预览画布。
"""
import tkinter as tk
from tkinter import ttk


def show_fitting_error_dialog(parent, items, title="管件画图错误/不严谨"):
    """弹出非模态列表对话框。

    :param parent: 父窗口（用于定位，居中显示）
    :param items: [(节点编号, 错误原因), ...]
    """
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.resizable(True, True)

    # 相对程序中心定位
    try:
        parent.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - 760) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - 420) // 2
        dialog.geometry(f"760x420+{max(x, 0)}+{max(y, 0)}")
    except Exception:
        pass

    label = ttk.Label(dialog, wraplength=720,
                      text="以下节点存在画图错误或不严谨，请在预览页面查看，并在CAD中修正后重新读取：")
    label.pack(fill="x", padx=10, pady=(10, 5))

    tree_frame = ttk.Frame(dialog)
    tree_frame.pack(fill="both", expand=True, padx=10, pady=5)
    tree = ttk.Treeview(tree_frame, columns=("node", "reason"), show="headings")
    tree.heading("node", text="节点编号")
    tree.heading("reason", text="错误原因")
    tree.column("node", width=130, anchor="center")
    tree.column("reason", width=600, anchor="w")
    vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vsb.set)
    tree.pack(side="left", fill="both", expand=True)
    vsb.pack(side="left", fill="y")

    for node_id, reason in items:
        tree.insert("", "end", values=(node_id, reason))

    btn = ttk.Button(dialog, text="关闭", command=dialog.destroy)
    btn.pack(pady=(0, 10))

    return dialog
