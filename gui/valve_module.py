"""
阀门页面模块（改进版）
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import logging
from gui.building_tab_manager import BuildingTabManager

logger = logging.getLogger(__name__)

class ValvePage(ttk.Frame):
    """阀门页面"""
    
    def __init__(self, parent, config_manager, material_manager, cad_data_manager):
        super().__init__(parent)
        self.config_manager = config_manager
        self.material_manager = material_manager
        self.cad_data_manager = cad_data_manager
        
        self.valve_data = []
        self.building_tabs = BuildingTabManager(self, cad_data_manager)
        self.create_widgets()
        self.setup_context_menu()
    
    def create_widgets(self):
        """创建界面控件"""
        self.building_tabs.build()
        # 阀门数据表格
        self.create_valve_table()
    
    def create_valve_table(self):
        """创建阀门数据表格"""
        columns = ("阀门ID", "所在管道ID", "状态", "X坐标", "Y坐标", "Z坐标")
        
        # 创建Treeview
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=25)
        
        # 设置列标题和宽度
        col_widths = {
            "阀门ID": 80,
            "所在管道ID": 100,
            "状态": 80,
            "X坐标": 100,
            "Y坐标": 100,
            "Z坐标": 100
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
        
        # 绑定双击事件编辑状态
        self.tree.bind("<Double-1>", self.on_double_click)

    def setup_context_menu(self):
        """设置右键菜单"""
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="跳转至整体预览",
            command=self.jump_to_valve_global
        )
        self.context_menu.add_command(
            label="跳转至楼层预览",
            command=self.jump_to_valve_floor
        )
        self.context_menu.add_command(
            label="跳转至拼接预览",
            command=self.jump_to_valve_spliced
        )
        self.context_menu.add_separator()
        
        # 绑定右键事件
        self.tree.bind("<Button-3>", self.show_context_menu)
    
    def refresh_data(self):
        """刷新阀门数据（静默模式）"""
        try:
            if not self.cad_data_manager.is_loaded:
                for item in self.tree.get_children():
                    self.tree.delete(item)
                self.valve_data = []
                self.building_tabs.rebuild_tabs()
                return
            
            self.valve_data = self.cad_data_manager.valves
            self.building_tabs.rebuild_tabs()
            self.update_table()
            
            # 记录日志
            logger.info(f"阀门页面已刷新: {len(self.valve_data)} 个阀门")
            
        except Exception as e:
            logger.error(f"刷新阀门数据失败: {e}")
    
    def update_table(self):
        """更新表格数据"""
        # 清空现有数据
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        bid = self.building_tabs.current_id
        data = self.valve_data
        if bid is not None:
            prefix = bid + '_'
            data = [v for v in data if v.valve_id.startswith(prefix)]
        
        # 添加新数据
        for valve in data:
            values = (
                valve.valve_id,
                valve.pipe_id if valve.pipe_id else "未匹配",
                valve.status,
                f"{valve.x:.2f}",
                f"{valve.y:.2f}",
                f"{valve.z:.2f}"
            )
            self.tree.insert("", tk.END, values=values)
    
    
    def on_double_click(self, event):
        """双击编辑阀门状态"""
        item = self.tree.selection()
        if not item:
            return
        
        column = self.tree.identify_column(event.x)
        
        # 只允许编辑状态列（第3列）
        if column != "#3":
            return
        
        # 获取当前状态
        current_values = self.tree.item(item[0], "values")
        if len(current_values) < 3:
            return
        
        current_status = current_values[2]
        valve_id = current_values[0]
        
        # 创建编辑对话框
        dialog = tk.Toplevel(self)
        dialog.title("编辑阀门状态")
        dialog.geometry("300x150")
        dialog.transient(self)
        dialog.grab_set()
        
        ttk.Label(dialog, text=f"阀门 {valve_id} 状态:").pack(pady=10)
        
        status_var = tk.StringVar(value=current_status)
        status_combo = ttk.Combobox(
            dialog,
            textvariable=status_var,
            values=["OPEN", "CLOSED"],
            state="readonly",
            width=10
        )
        status_combo.pack(pady=10)
        
        def save_status():
            new_status = status_var.get()
            # 更新表格
            values = list(current_values)
            values[2] = new_status
            self.tree.item(item[0], values=values)
            
            # 更新数据模型
            for valve in self.valve_data:
                if valve.valve_id == valve_id:
                    valve.status = new_status
                    logger.info(f"阀门 {valve_id} 状态已更新为: {new_status}")
                    break
            
            dialog.destroy()
        
        ttk.Button(dialog, text="保存", command=save_status).pack(pady=10)
    
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

    def jump_to_valve_global(self):
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        if not values:
            return
        preview = self._switch_to_preview()
        if preview:
            preview.jump_to_valve(values[0], to_global=True)

    def jump_to_valve_floor(self):
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        if not values:
            return
        preview = self._switch_to_preview()
        if preview:
            preview.jump_to_valve(values[0], to_global=False)

    def jump_to_valve_spliced(self):
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        if not values:
            return
        preview = self._switch_to_preview()
        if preview:
            preview.jump_to_spliced_view(entity_type="valve", entity_id=values[0])

    def _on_delete_building(self, building_id: str):
        root = self.winfo_toplevel()
        main_app = getattr(root, 'main_app', None)
        if not main_app:
            return
        preview = main_app.pages.get("管网预览")
        if preview:
            preview._on_delete_building(building_id)
