"""
供水点和用水点页面模块（修复版）
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import logging

logger = logging.getLogger(__name__)

class SupplyDemandPage(ttk.Frame):
    """供水点和用水点页面"""
    
    def __init__(self, parent, config_manager, material_manager, cad_data_manager):
        super().__init__(parent)
        self.config_manager = config_manager
        self.material_manager = material_manager
        self.cad_data_manager = cad_data_manager
        
        # 数据缓存
        self.supply_groups = []
        self.demand_groups = {}
        
        # 存储组框架和树控件，用于刷新
        self.group_frames = {}
        
        self.create_widgets()
        self.setup_context_menu()
    
    def create_widgets(self):
        """创建界面控件"""
        # 创建画布和细滚动条
        self.canvas = tk.Canvas(self, highlightthickness=0, background="white")
        self.scrollbar = tk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
            width=10
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        # 创建内部框架
        self.inner_frame = ttk.Frame(self.canvas)
        self.canvas_frame = self.canvas.create_window((0, 0), window=self.inner_frame, anchor="nw")
        
        # 布局
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        
        # 绑定事件
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.inner_frame.bind("<Configure>", self.on_frame_configure)
        
        # 绑定鼠标滚轮
        self.bind_mouse_wheel()
        
        # 创建内容
        self.create_content()
    
    def bind_mouse_wheel(self):
        """绑定鼠标滚轮事件"""
        def on_mouse_wheel(event):
            # ✅ 检查鼠标是否在这个页面区域内
            try:
                widget = event.widget
                parent = widget
                while parent:
                    if parent == self:
                        # 在当前页面内，执行滚动
                        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                        return
                    parent = parent.master
            except:
                pass
        
        # ✅ 使用bind_all，但在回调中检查鼠标位置
        self.bind_all("<MouseWheel>", on_mouse_wheel)

    
    def on_canvas_configure(self, event):
        """画布大小变化"""
        self.canvas.itemconfig(self.canvas_frame, width=event.width)
        # ✅ 重新计算滚动区域
        self.on_frame_configure()


    def on_frame_configure(self, event=None):
        """内部框架大小变化"""
        self.inner_frame.update_idletasks()
        
        # 获取内部框架的实际尺寸
        frame_height = self.inner_frame.winfo_reqheight()
        frame_width = self.inner_frame.winfo_reqwidth()
        canvas_height = self.canvas.winfo_height()
        
        # ✅ 关键：scrollregion的高度取实际内容高度和canvas高度的最大值
        # 这样可以防止向上滚动时出现空白
        scroll_height = max(frame_height, canvas_height) if canvas_height > 1 else frame_height
        
        self.canvas.configure(scrollregion=(0, 0, frame_width, scroll_height))

    def create_content(self):
        """创建页面内容"""
        # ✅ 获取配置中的单位（使用get_live_config）
        config = self.config_manager.get_live_config()
        pressure_unit = config.get("pressure_unit", "m")
        
        # 供水点区域
        self.supply_frame = ttk.LabelFrame(self.inner_frame, text="供水点数据")
        self.supply_frame.pack(fill=tk.X, padx=10, pady=(10, 10))
        
        # 供水点表格
        columns = ("组ID", "节点列表", f"压力({pressure_unit})")
        self.supply_tree = ttk.Treeview(
            self.supply_frame,
            columns=columns,
            show="headings",
            height=1
        )
        
        col_widths = {"组ID": 100, "节点列表": 200, f"压力({pressure_unit})": 100}
        for col in columns:
            self.supply_tree.heading(col, text=col)
            width = col_widths.get(col, 150)
            self.supply_tree.column(col, width=width, anchor="center")
        
        # 绑定双击编辑压力
        self.supply_tree.bind("<Double-1>", self.on_supply_tree_double_click)
        
        self.supply_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 用水点区域
        self.demand_container = ttk.Frame(self.inner_frame)
        self.demand_container.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        # 初始显示提示
        self.no_demand_label = ttk.Label(
            self.demand_container,
            text="未找到用水点数据",
            font=("Arial", 10)
        )
        self.no_demand_label.pack(pady=20)

    def refresh_data(self):
        """刷新数据"""
        try:
            self.supply_groups = self.cad_data_manager.supply_nodes
            self.demand_groups = self.cad_data_manager.demand_groups
            self.refresh_supply_table()
            self.refresh_demand_groups()
        except Exception as e:
            logger.error(f"刷新供水点和用水点数据失败: {e}")

    def refresh_supply_table(self):
        """刷新供水点表格"""
        # 清空表格
        for item in self.supply_tree.get_children():
            self.supply_tree.delete(item)
        
        # 如果没有供水点数据
        if not self.supply_groups:
            self.supply_tree.insert("", tk.END, values=("暂无数据", "", ""))
            return
        
        # 添加数据
        for group in self.supply_groups:
            self.supply_tree.insert("", tk.END, values=(
                group.group_id,
                ", ".join(group.node_ids),
                f"{group.pressure:.2f}"
            ))
    
    def refresh_demand_groups(self):
        """刷新用水点组"""
        # 移除提示标签
        if hasattr(self, 'no_demand_label'):
            self.no_demand_label.destroy()
        
        # 清空现有组
        for widget in self.demand_container.winfo_children():
            widget.destroy()
        
        # 清空组框架缓存
        self.group_frames.clear()
        # ✅ 删除 self.flow_unit_combos.clear() 这一行
        
        # 如果没有用水点组，显示提示
        if not self.demand_groups:
            ttk.Label(
                self.demand_container,
                text="未找到用水点数据",
                font=("Arial", 10)
            ).pack(pady=20)
            return
        
        # 创建每个用水点组
        for group_id, group in self.demand_groups.items():
            self.create_demand_group_section(group_id, group)
        
        # 刷新后立即更新滚动区域
        self.inner_frame.update_idletasks()
        self.on_frame_configure()

    def create_demand_group_section(self, group_id, group):
        """创建用水点组显示区域（新增最低水压输入）"""
        # 获取配置中的单位
        config = self.config_manager.get_live_config()
        default_flow_unit = config.get("flow_unit", "L/s")
        pressure_unit = config.get("pressure_unit", "m")   # 新增：用于最低水压单位

        # 组框架
        group_frame = ttk.LabelFrame(self.demand_container, text=f"用水点组：{group_id}")
        group_frame.pack(fill=tk.X, padx=5, pady=5)

        # 绑定右键菜单到组框架（保留原有）
        group_frame.bind("<Button-3>", self.show_context_menu)

        # 存储组框架引用（保留原有）
        self.group_frames[group_id] = group_frame

        # 组控制行
        control_frame = ttk.Frame(group_frame)
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        # 勾选框（同现有代码）
        check_var = tk.BooleanVar(value=group.is_selected)
        check_btn = ttk.Checkbutton(
            control_frame,
            variable=check_var,
            command=lambda g=group, v=check_var: self.toggle_group_selection(g, v.get())
        )
        check_btn.pack(side=tk.LEFT, padx=(0, 10))

        # 总流量标签（同现有代码）
        ttk.Label(control_frame, text="总流量:").pack(side=tk.LEFT)

        # 总流量输入框（同现有代码）
        if default_flow_unit == "m³/h":
            init_flow = group.total_flow * 3.6
        else:
            init_flow = group.total_flow
        flow_var = tk.StringVar(value=f"{init_flow:.2f}")
        flow_entry = ttk.Entry(control_frame, textvariable=flow_var, width=8)
        flow_entry.pack(side=tk.LEFT, padx=5)
        unit_label = ttk.Label(control_frame, text=default_flow_unit)
        unit_label.pack(side=tk.LEFT, padx=(0, 10))

        # ----- 新增：最低水压输入 -----
        ttk.Label(control_frame, text="最低水压:").pack(side=tk.LEFT, padx=(10, 2))
        min_pressure_var = tk.StringVar(value=f"{group.min_pressure:.2f}" if group.min_pressure else "")
        min_pressure_entry = ttk.Entry(control_frame, textvariable=min_pressure_var, width=8)
        min_pressure_entry.pack(side=tk.LEFT, padx=2)
        min_pressure_unit_label = ttk.Label(control_frame, text=pressure_unit)
        min_pressure_unit_label.pack(side=tk.LEFT)

        # 保存最低水压的回调
        def save_min_pressure(event=None):
            try:
                val = float(min_pressure_var.get())
                group.min_pressure = val
            except ValueError:
                min_pressure_var.set("0.00")
                group.min_pressure = 0.0

        min_pressure_entry.bind("<FocusOut>", save_min_pressure)
        min_pressure_entry.bind("<Return>", save_min_pressure)
        # ---------------------------------

        # 保存总流量的回调（同现有代码）
        def save_flow(event=None, g=group, fv=flow_var):
            try:
                input_val = float(fv.get())
                current_config = self.config_manager.get_live_config()
                flow_unit = current_config.get("flow_unit", "L/s")
                if flow_unit == "m³/h":
                    g.total_flow = input_val / 3.6
                else:
                    g.total_flow = input_val
            except ValueError:
                # 恢复显示为存储的 L/s 值（需转换为当前单位）
                current_config = self.config_manager.get_live_config()
                flow_unit = current_config.get("flow_unit", "L/s")
                if flow_unit == "m³/h":
                    display_val = g.total_flow * 3.6
                else:
                    display_val = g.total_flow
                fv.set(f"{display_val:.2f}")

        flow_entry.bind("<FocusOut>", save_flow)
        flow_entry.bind("<Return>", save_flow)

        # 用水点表格（同现有代码）
        columns = ("节点ID", "状态", "流量", "压力")
        actual_rows = len(group.demand_nodes)
        display_rows = actual_rows if actual_rows > 0 else 4
        tree = ttk.Treeview(
            group_frame,
            columns=columns,
            show="headings",
            height=display_rows
        )

        # 绑定右键菜单到表格（保留原有）
        tree.bind("<Button-3>", self.show_context_menu)

        col_widths = {"节点ID": 80, "状态": 60, "流量": 80, "压力": 80}
        for col in columns:
            tree.heading(col, text=col)
            width = col_widths.get(col, 100)
            tree.column(col, width=width, anchor="center")

        # 添加数据
        for node in group.demand_nodes:
            tree.insert("", tk.END, values=(
                node.node_id,
                node.status,
                f"{node.flow:.2f}",
                f"{node.pressure:.2f}"
            ))

        tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        # 存储树的引用（保留原有）
        group.tree_widget = tree


    def on_units_changed(self):
        """单位改变时刷新显示"""
        self.full_refresh()

    def toggle_group_selection(self, group, is_selected):
        """切换组选择状态"""
        group.is_selected = is_selected
        
        # 立即更新组内节点状态
        new_status = "开" if is_selected else "关"
        for node in group.demand_nodes:
            node.status = new_status
            
            # 同步到节点管理器
            if node.node_id in self.cad_data_manager.node_by_id:
                self.cad_data_manager.node_by_id[node.node_id].status = new_status
        
        # ✅ 只更新表格显示，不刷新整个页面
        for group_obj in self.demand_groups.values():
            if group_obj.group_id == group.group_id:
                self.update_demand_table_display(group_obj)
                break
    
    def update_demand_table_display(self, group):
        """只更新指定组的表格显示，不刷新整个页面"""
        if hasattr(group, 'tree_widget'):
            tree_height = max(len(group.demand_nodes), 1)
            group.tree_widget.configure(height=tree_height)
            for item in group.tree_widget.get_children():
                group.tree_widget.delete(item)
            for node in group.demand_nodes:
                group.tree_widget.insert("", tk.END, values=(
                    node.node_id,
                    node.status,
                    f"{node.flow:.2f}",
                    f"{node.pressure:.2f}"
                ))
    
    def update_node_page(self):
        """更新节点页面状态"""
        # 标记数据已更改，节点页面会在下次刷新时更新
        pass
    
    def on_supply_tree_double_click(self, event):
        """供水点表格双击编辑压力（原位编辑）"""
        item = self.supply_tree.selection()
        if not item:
            return
        
        column = self.supply_tree.identify_column(event.x)
        item_id = item[0]
        
        # 只允许编辑压力列（第三列）
        if column != "#3":
            return
        
        # 获取当前值
        values = list(self.supply_tree.item(item_id, "values"))
        if len(values) < 3:
            return
        
        group_id = values[0]
        current_pressure = values[2]
        
        # 查找对应的供水点组
        target_group = None
        for group in self.supply_groups:
            if group.group_id == group_id:
                target_group = group
                break
        
        if not target_group:
            return
        
        # 获取单元格位置
        bbox = self.supply_tree.bbox(item_id, 2)  # 压力列索引为2
        if not bbox:
            return
        
        x, y, width, height = bbox
        
        # 创建编辑框
        edit_var = tk.StringVar(value=current_pressure)
        edit_entry = ttk.Entry(self.supply_tree, textvariable=edit_var, width=10)
        edit_entry.place(x=x, y=y, width=width, height=height)
        edit_entry.focus_set()
        edit_entry.select_range(0, tk.END)
        
        def save_pressure(event=None):
            new_pressure_str = edit_var.get().strip()
            edit_entry.destroy()
            
            try:
                pressure = float(new_pressure_str)
                
                # 更新数据模型
                target_group.pressure = pressure
                
                # 更新表格显示
                values[2] = f"{pressure:.2f}"
                self.supply_tree.item(item_id, values=values)
                
            except ValueError:
                # 恢复原值
                values[2] = current_pressure
                self.supply_tree.item(item_id, values=values)
        
        def cancel_edit(event=None):
            edit_entry.destroy()
        
        edit_entry.bind("<Return>", save_pressure)
        edit_entry.bind("<FocusOut>", save_pressure)  # 光标离开保存
        edit_entry.bind("<Escape>", cancel_edit)
    
    def setup_context_menu(self):
        """设置右键菜单"""
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(
            label="导出选中组为CSV",
            command=self.export_selected_groups
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="刷新数据",
            command=self.full_refresh
        )
        
        # ✅ 绑定右键事件到多个区域
        self.supply_tree.bind("<Button-3>", self.show_context_menu)
        self.canvas.bind("<Button-3>", self.show_context_menu)
        self.inner_frame.bind("<Button-3>", self.show_context_menu)
        self.supply_frame.bind("<Button-3>", self.show_context_menu)
        self.demand_container.bind("<Button-3>", self.show_context_menu)

    def full_refresh(self):
        """完整刷新页面（包括单位）"""
        try:
            # ✅ 获取最新配置
            config = self.config_manager.get_live_config()
            pressure_unit = config.get("pressure_unit", "m")
            flow_unit = config.get("flow_unit", "L/s")

            # 更新供水点表格列标题（压力单位）
            columns = ("组ID", "节点列表", f"压力({pressure_unit})")
            for i, col in enumerate(columns):
                self.supply_tree.heading(f"#{i+1}", text=col)

            # 刷新数据
            self.supply_groups = self.cad_data_manager.supply_nodes
            self.demand_groups = self.cad_data_manager.demand_groups

            # 刷新供水点表格
            self.refresh_supply_table()

            # 强制刷新用水点组（重新创建以更新单位）
            self.refresh_demand_groups()

        except Exception as e:
            logger.error(f"完整刷新页面失败: {e}")

    def show_context_menu(self, event):
        """显示右键菜单"""
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()
    
    def export_selected_groups(self):
        """导出选中组为CSV"""
        try:
            # 获取选中组
            selected_groups = [
                g for g in self.demand_groups.values()
                if g.is_selected
            ]
            
            if not selected_groups:
                messagebox.showwarning("警告", "没有选中的用水点组")
                return
            
            # 选择保存路径
            default_dir = os.path.dirname(self.cad_data_manager.cad_file_path) \
                if self.cad_data_manager.cad_file_path else os.getcwd()
            
            file_path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV文件", "*.csv")],
                initialdir=default_dir,
                initialfile="用水点数据.csv"
            )
            
            if file_path:
                import pandas as pd
                
                # 收集数据
                data = []
                for group in selected_groups:
                    for node in group.demand_nodes:
                        data.append({
                            "组ID": group.group_id,
                            "节点ID": node.node_id,
                            "状态": node.status,
                            "流量": node.flow,
                            "压力": node.pressure
                        })
                
                if data:
                    df = pd.DataFrame(data)
                    df.to_csv(file_path, index=False, encoding='utf-8-sig')
                    messagebox.showinfo("导出成功", f"已导出 {len(data)} 个用水点")
                else:
                    messagebox.showwarning("警告", "没有可导出的数据")
                    
        except Exception as e:
            messagebox.showerror("导出失败", f"导出失败:\n{str(e)}")
