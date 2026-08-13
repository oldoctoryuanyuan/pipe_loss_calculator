"""
管道页面模块
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os

import logging
from gui.building_tab_manager import BuildingTabManager

logger = logging.getLogger(__name__)

class PipePage(ttk.Frame):
    """管道页面"""
    
    def __init__(self, parent, config_manager, material_manager, cad_data_manager, status_callback=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.material_manager = material_manager
        self.cad_data_manager = cad_data_manager
        self.status_callback = status_callback
        
        self.pipe_data = []
        self.building_tabs = BuildingTabManager(self, cad_data_manager)
        self.create_widgets()
        self.setup_context_menu()
    
    def create_widgets(self):
        """创建界面控件"""
        
        self.building_tabs.build()
        # 管道数据表格
        self.create_pipe_table()
    
    def create_pipe_table(self):
        """创建管道数据表格"""
        columns = ("管段ID", "起点", "终点", "管径", "内径(mm)", "管长(m)", "状态", "类型", "管材")
        
        # 创建Treeview
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=25)
        
        # 设置列标题和宽度
        col_widths = {
            "管段ID": 80,
            "起点": 80,
            "终点": 80,
            "管径": 80,
            "内径(mm)": 80,
            "管长(m)": 80,
            "状态": 60,
            "类型": 60,
            "管材": 100
        }
        
        for col in columns:
            self.tree.heading(col, text=col)
            width = col_widths.get(col, 100)
            self.tree.column(col, width=width, anchor="center")
        
        # 细滚动条
        scrollbar = tk.Scrollbar(
            self,
            orient="vertical",
            command=self.tree.yview,
            width=10
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        # 布局
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5)
        # 配置无效行样式
        self.tree.tag_configure('inactive', foreground='gray')

    def setup_context_menu(self):
        """设置右键菜单"""
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="跳转至整体预览",
            command=self.jump_to_pipe_global
        )
        self.context_menu.add_command(
            label="跳转至楼层预览",
            command=self.jump_to_pipe_floor
        )
        self.context_menu.add_command(
            label="跳转至拼接预览",
            command=self.jump_to_pipe_spliced
        )
        self.context_menu.add_separator()
        
        # 绑定右键事件
        self.tree.bind("<Button-3>", self.show_context_menu)
    def refresh_data(self):
        """刷新管道数据"""
        if not self.cad_data_manager.is_loaded:
            for item in self.tree.get_children():
                self.tree.delete(item)
            self.pipe_data = []
            self.building_tabs.rebuild_tabs()
            return
        
        try:
            self.pipe_data = self.cad_data_manager.pipes
            self.building_tabs.rebuild_tabs()
            self.update_table()
            
            if len(self.pipe_data) == 0:
                if self.status_callback:
                    self.status_callback("警告：未识别到任何管道，请检查图层和颜色设置", is_error=True)
                
        except Exception as e:
            if self.status_callback:
                self.status_callback(f"刷新失败: {str(e)}", is_error=True)
    
    def update_table(self):
        """更新表格数据"""
        # 清空现有数据
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        bid = self.building_tabs.current_id
        data = self.pipe_data
        if bid is not None:
            prefix = bid + '_'
            data = [p for p in data if p.pipe_id.startswith(prefix)]
        
        # 添加新数据
        for pipe in data:
            values = (
                pipe.pipe_id,
                pipe.start_node_id,
                pipe.end_node_id,
                pipe.nominal_diameter,
                f"{pipe.inner_diameter:.1f}",
                f"{pipe.length:.2f}",
                pipe.status,
                pipe.pipe_type,
                pipe.material
            )
            item = self.tree.insert("", tk.END, values=values)
            if not pipe.is_active:
                self.tree.item(item, tags=('inactive',))
    
    
    def show_context_menu(self, event):
        """显示右键菜单"""
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _switch_to_preview(self):
        root = self.winfo_toplevel()
        main_app = getattr(root, 'main_app', None)
        if not main_app:
            return None
        notebook = main_app.notebook
        for tab_id in notebook.tabs():
            if notebook.tab(tab_id, "text") == "管网预览":
                notebook.select(tab_id)
                break
        return main_app.pages.get("管网预览")

    def jump_to_pipe_global(self):
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        if not values:
            return
        preview = self._switch_to_preview()
        if preview:
            preview.jump_to_pipe(values[0], to_global=True)

    def jump_to_pipe_floor(self):
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        if not values:
            return
        preview = self._switch_to_preview()
        if preview:
            preview.jump_to_pipe(values[0], to_global=False)

    def jump_to_pipe_spliced(self):
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        if not values:
            return
        preview = self._switch_to_preview()
        if preview:
            preview.jump_to_spliced_view(entity_type="pipe", entity_id=values[0])

    def _on_delete_building(self, building_id: str):
        root = self.winfo_toplevel()
        main_app = getattr(root, 'main_app', None)
        if not main_app:
            return
        preview = main_app.pages.get("管网预览")
        if preview:
            preview._on_delete_building(building_id)