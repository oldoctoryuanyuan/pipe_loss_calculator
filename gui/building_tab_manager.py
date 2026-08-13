import tkinter as tk
from tkinter import ttk


class BuildingTabManager:
    """区域管网模式下管道/节点/阀门页面的楼栋二级标签管理器。

    委托给每个页面使用，消除三页间的代码重复。
    调用方需提供：
      - page: ttk.Frame 子类（负责 update_table()）
      - cad_data_manager: 提供 get_building_ids()
    调用方通过 building_tabs.current_id 获取选中楼栋ID（None=全部）。

    与楼层标签做法一致：
      build() 时一次 pack，永不 pack_forget；
      rebuild_tabs 用 unbind/rebind，无 _rebuilding flag。
    """

    def __init__(self, page, cad_data_manager):
        self.page = page
        self.cad_data_manager = cad_data_manager
        self.current_id = None
        self.notebook = None

    def build(self):
        self.notebook = ttk.Notebook(self.page)
        self.notebook.pack(fill=tk.X, padx=5, pady=(5, 0))

    def rebuild_tabs(self):
        if self.notebook is None:
            return
        old_id = self.current_id   # 记住离开时的选中楼栋
        self.notebook.unbind("<<NotebookTabChanged>>")
        self.notebook.unbind("<Button-3>")
        for tab_id in self.notebook.tabs():
            self.notebook.forget(tab_id)
        building_ids = self.cad_data_manager.get_building_ids()
        if not building_ids:
            self.current_id = None
        else:
            for bid in building_ids:
                self.notebook.add(ttk.Frame(self.notebook), text=bid)
            if not self.notebook.winfo_ismapped():
                self.notebook.pack(fill=tk.X, padx=5, pady=(5, 0))
            # 恢复上次选中的楼栋子标签（该楼栋可能已删除则回退到第一个）
            if old_id in building_ids:
                self.notebook.select(building_ids.index(old_id))
                self.current_id = old_id
            else:
                self.notebook.select(0)
                self.current_id = building_ids[0]
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.notebook.bind("<Button-3>", self._on_building_tab_right_click)

    def _on_building_tab_right_click(self, event):
        """楼栋标签右键菜单：删除单体"""
        if self.notebook is None or not self.notebook.tabs():
            return
        try:
            idx = self.notebook.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return
        building_ids = self.cad_data_manager.get_building_ids()
        if not building_ids or idx < 0 or idx >= len(building_ids):
            return
        bid = building_ids[idx]
        menu = tk.Menu(self.notebook, tearoff=0)
        menu.add_command(label="删除单体", command=lambda: self.page._on_delete_building(bid))
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()

    def _on_tab_changed(self, event=None):
        building_ids = self.cad_data_manager.get_building_ids()
        if not building_ids:
            self.current_id = None
            self.page.update_table()
            return
        try:
            idx = self.notebook.index(self.notebook.select())
        except tk.TclError:
            return
        if 0 <= idx < len(building_ids):
            self.current_id = building_ids[idx]
        self.page.update_table()
