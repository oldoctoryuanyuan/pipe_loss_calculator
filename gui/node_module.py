"""
节点页面模块
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import logging

logger = logging.getLogger(__name__)

class NodePage(ttk.Frame):
    """节点页面"""
    
    def __init__(self, parent, config_manager, material_manager, cad_data_manager):
        super().__init__(parent)
        self.config_manager = config_manager
        self.material_manager = material_manager
        self.cad_data_manager = cad_data_manager
        
        self.node_data = []
        self.create_widgets()
        self.setup_context_menu()
    
    def create_widgets(self):
        """创建界面控件"""
        # ========== 已注释：未使用的工具栏代码 ==========
        # 注释原因：工具栏代码已弃用，刷新功能通过右键菜单实现
        # toolbar = ttk.Frame(self)
        # toolbar.pack(fill=tk.X, padx=5, pady=2)
        # refresh_btn = ttk.Button(
        #     toolbar,
        #     text="刷新数据",
        #     command=self.refresh_data
        # )
        # refresh_btn.pack(side=tk.LEFT, padx=2)
        
        # 节点数据表格
        self.create_node_table()

    def create_node_table(self):
        """创建节点数据表格"""
        style = ttk.Style()
        style.configure("Treeview", rowheight=25)

        # 初始列（后续会在update_table中动态更新）
        columns = ["节点ID", "状态", "X坐标", "Y坐标", "Z坐标", "节点类型"]
        
        # 创建Treeview，设置height为20行（确保超出时出现滚动条）
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=20)

        # 创建滚动条
        scrollbar = tk.Scrollbar(self, orient="vertical", command=self.tree.yview, width=10)
        self.tree.configure(yscrollcommand=scrollbar.set)

        # 布局：必须先pack滚动条（右侧），再pack表格（左侧），这样表格才能正确填充剩余空间
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        # 配置无效行样式
        self.tree.tag_configure('inactive', foreground='gray')

    def setup_context_menu(self):
        """设置右键菜单"""
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="跳转至整体预览",
            command=self.jump_to_node_global
        )
        self.context_menu.add_command(
            label="跳转至楼层预览",
            command=self.jump_to_node_floor
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="刷新",
            command=self.refresh_data
        )
        
        # 绑定右键事件
        self.tree.bind("<Button-3>", self.show_context_menu)
    
    def refresh_data(self):
        """刷新节点数据（静默模式）"""
        try:
            if not self.cad_data_manager.is_loaded:
                # 不显示弹窗，只清空表格
                for item in self.tree.get_children():
                    self.tree.delete(item)
                return
            
            # 直接从 CADDataManager 获取最新节点数据
            self.node_data = self.cad_data_manager.nodes

            # 关键修改：确保用水点节点的状态从需求组同步
            for node in self.node_data:
                # 检查是否为用水点
                if node.node_type and node.node_type.startswith("用水点"):
                    # 查找对应的需求节点
                    for group_id, group in self.cad_data_manager.demand_groups.items():
                        for demand_node in group.demand_nodes:
                            if demand_node.node_id == node.node_id:
                                # 同步状态
                                node.status = demand_node.status
                                break

            self.update_table()
            
        except Exception as e:
            logger.error(f"刷新节点数据失败: {e}")
            # 不显示弹窗
    
    def update_table(self):
        """更新表格数据（仅当列数变化时才重设列，否则只更新行）"""
        # 1. 计算当前所需最大连接管道数
        max_connections = 0
        for node in self.node_data:
            conn_len = len(node.connected_pipes) if node.connected_pipes else 0
            if conn_len > max_connections:
                max_connections = conn_len

        # 2. 构建所需的列标题列表
        base_columns = ["节点ID", "状态", "X坐标", "Y坐标", "Z坐标", "节点类型"]
        new_columns = base_columns + [f"连接管道{i+1}" for i in range(max_connections)]

        # 3. 仅当列结构发生变化时，才重新配置Treeview列
        current_columns = list(self.tree['columns'])
        if current_columns != new_columns:
            self.tree.configure(columns=new_columns)
            for col in new_columns:
                self.tree.heading(col, text=col)
                self.tree.column(col, width=100, anchor="center")

        # 4. 清空现有行数据
        for item in self.tree.get_children():
            self.tree.delete(item)

        # 5. 插入新数据（列数已确定）
        for node in self.node_data:
            values = [
                node.node_id,
                node.status,
                f"{node.x:.2f}",
                f"{node.y:.2f}",
                f"{node.z:.2f}",
                node.node_type
            ]
            # 填充连接管道列
            if node.connected_pipes:
                for i in range(max_connections):
                    values.append(node.connected_pipes[i] if i < len(node.connected_pipes) else "")
            else:
                values.extend([""] * max_connections)
        
            item = self.tree.insert("", tk.END, values=values)
            if not node.is_active:
                self.tree.item(item, tags=('inactive',))

        # 6. 强制刷新布局（确保滚动条更新）
        self.tree.update_idletasks()
           
    
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
            return None, None
        notebook = main_app.notebook
        for tab_id in notebook.tabs():
            if notebook.tab(tab_id, "text") == "管网预览":
                notebook.select(tab_id)
                break
        return main_app.pages.get("管网预览"), main_app

    def jump_to_node_global(self):
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        if not values:
            return
        preview = self._switch_to_preview()[0]
        if preview:
            preview.jump_to_node(values[0], to_global=True)

    def jump_to_node_floor(self):
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        if not values:
            return
        preview = self._switch_to_preview()[0]
        if preview:
            preview.jump_to_node(values[0], to_global=False)