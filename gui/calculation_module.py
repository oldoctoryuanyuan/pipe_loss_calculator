"""
计算页面 - 集成完整的计算功能
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import sys
import threading
import json
import time
from datetime import datetime
import logging

# 导入核心计算模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.inp_generator import INPGenerator
from core.epanet_calculator import EpanetCalculator
from core.result_parser import ResultParser

logger = logging.getLogger(__name__)

class CalculationPage(ttk.Frame):
    """计算页面"""
    
    def __init__(self, parent, config_manager, material_manager, cad_data_manager):
        super().__init__(parent)
        self.config_manager = config_manager
        self.material_manager = material_manager
        self.cad_data_manager = cad_data_manager
        
        # 初始化计算组件
        self.inp_generator = INPGenerator(config_manager, material_manager)
        self.epanet_calc = EpanetCalculator("epanet2.2")
        # 传递cad_data_manager给ResultParser
        self.result_parser = ResultParser(cad_data_manager)
        
        # 项目目录管理
        self.projects_base_dir = "projects"
        self.current_project_dir = ""
        self.current_cad_file = ""
        
        # 计算状态
        self.is_calculating = False
        self.calculation_thread = None
        
        # 单位转换相关
        self.show_flow_in_m3h = False  # 是否显示为m³/h
        self.show_pressure_in_mpa = False  # 是否显示为MPa
        
        # 创建界面
        self.create_widgets()
        self.setup_bindings()
        
        # 注意：先创建widgets，再绑定鼠标滚轮事件
        # 因为bind_mouse_wheel需要访问已经创建的表格控件
        self.bind_mouse_wheel()
        
        # 路径显示模式：'nodes' 或 'pipes'
        self.path_display_mode = 'nodes'
        # 用于存储节点总水损的字典
        self.node_total_loss = {}
        
        # 保存路径原始数据，用于切换显示
        self.all_paths_for_preview = []

        logger.info("计算页面初始化完成")

    def bind_mouse_wheel(self):
        """绑定鼠标滚轮事件 - 仅针对表格内部滚动"""
        # 表格滚动函数
        def table_mouse_wheel(event, table):
            table.yview_scroll(int(-1 * (event.delta / 120)), "units")

        # 为每个表格绑定自己的滚轮事件
        if hasattr(self, 'nodes_tree'):
            self.nodes_tree.bind("<MouseWheel>", 
                               lambda e: table_mouse_wheel(e, self.nodes_tree))
        if hasattr(self, 'pipes_tree'):
            self.pipes_tree.bind("<MouseWheel>", 
                               lambda e: table_mouse_wheel(e, self.pipes_tree))
        if hasattr(self, 'paths_tree'):
            self.paths_tree.bind("<MouseWheel>", 
                               lambda e: table_mouse_wheel(e, self.paths_tree))
        
        # 绑定按钮-4和按钮-5（兼容Linux）
        self.bind_all("<Button-4>", lambda e: self._handle_mouse_wheel(e, -3))
        self.bind_all("<Button-5>", lambda e: self._handle_mouse_wheel(e, 3))

    def _handle_mouse_wheel(self, event, delta):
        """处理鼠标滚轮事件的辅助函数"""
        widget = event.widget
        if widget in [self.nodes_tree, self.pipes_tree, self.paths_tree]:
            widget.yview_scroll(delta, "units")

    def create_widgets(self):
        """创建界面控件 - 使用pack布局，无外部滚动条"""
        # 1. 控制面板 - 使用Frame固定布局
        control_frame = ttk.LabelFrame(self, text="计算控制", padding=10)
        control_frame.pack(fill="x", padx=5, pady=5)

        # 创建水平容器，所有控件放在一行
        control_container = ttk.Frame(control_frame)
        control_container.pack(fill="x", expand=True)

        # 左侧按钮区域 - 使用固定宽度确保对齐
        buttons_frame = ttk.Frame(control_container)
        buttons_frame.pack(side="left", fill="y", padx=(0, 10))
        
        # 开始计算按钮
        self.calculate_btn = ttk.Button(
            buttons_frame, 
            text="▶ 开始计算", 
            command=self.start_calculation,
            state="disabled",
            width=12
        )
        self.calculate_btn.pack(side="left", padx=(0, 5))

        # 导出结果按钮
        self.export_btn = ttk.Button(
            buttons_frame, 
            text="导出结果", 
            command=self.export_results,
            state="disabled",
            width=10
        )
        self.export_btn.pack(side="left")

        # 单位选择框区域
        unit_frame = ttk.Frame(control_container)
        unit_frame.pack(side="left", fill="y", padx=(0, 10))

        # 流量单位选择框
        self.flow_unit_var = tk.BooleanVar(value=False)
        self.flow_unit_check = ttk.Checkbutton(
            unit_frame,
            text="流量单位(m³/h)",
            variable=self.flow_unit_var,
            command=self.on_unit_check_changed
        )
        self.flow_unit_check.pack(side="left", padx=(0, 5))

        # 压力单位选择框
        self.pressure_unit_var = tk.BooleanVar(value=False)
        self.pressure_unit_check = ttk.Checkbutton(
            unit_frame,
            text="压力单位(MPa)",
            variable=self.pressure_unit_var,
            command=self.on_unit_check_changed
        )
        self.pressure_unit_check.pack(side="left")

        # 显示无流量节点和管道
        self.show_zero_flow_var = tk.BooleanVar(value=False)
        self.show_zero_flow_check = ttk.Checkbutton(
            unit_frame,
            text="显示无流量节点和管道",
            variable=self.show_zero_flow_var,
            command=self.on_show_zero_flow_changed
        )
        self.show_zero_flow_check.pack(side="left", padx=(10, 0))

        # 右侧进度区域
        progress_frame = ttk.Frame(control_container)
        progress_frame.pack(side="left", fill="y")

        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate', length=120)
        self.progress_bar.pack(side="left", padx=(0, 5))

        self.status_label = ttk.Label(progress_frame, text="就绪", width=15)
        self.status_label.pack(side="left")

        # 中间的弹性空间，确保左右两侧不重叠
        ttk.Frame(control_container).pack(side="left", fill="x", expand=True)

        # 创建垂直分割的 PanedWindow，直接放在 self 中
        self.vertical_paned = ttk.PanedWindow(self, orient="vertical")
        self.vertical_paned.pack(fill="both", expand=True, padx=5, pady=5)

        # 2. 详细计算结果（作为第一个窗格）
        results_frame = ttk.LabelFrame(self.vertical_paned, text="详细计算结果", padding=5)
        self.vertical_paned.add(results_frame, weight=3)  # 权重3，初始占比大

        # 创建节点和管道表格的笔记本
        self.results_notebook = ttk.Notebook(results_frame)
        self.results_notebook.pack(fill="both", expand=True)

        # 节点结果标签页
        self.nodes_tab = ttk.Frame(self.results_notebook)
        self.results_notebook.add(self.nodes_tab, text="节点结果")
        self.create_nodes_table(self.nodes_tab)

        # 管道结果标签页
        self.pipes_tab = ttk.Frame(self.results_notebook)
        self.results_notebook.add(self.pipes_tab, text="管道结果")
        self.create_pipes_table(self.pipes_tab)

        # 3. 路径列表（作为第二个窗格）
        paths_frame = ttk.LabelFrame(self.vertical_paned, text="供水点→用水点路径", padding=5)
        self.vertical_paned.add(paths_frame, weight=1)  # 权重1，初始占比小

        # 路径表格
        columns = ("path_id", "total_loss", "nodes_path")
        self.paths_tree = ttk.Treeview(paths_frame, columns=columns, show="headings", height=8)

        # 设置列标题 - 根据压力单位选择显示不同的单位
        pressure_unit = "MPa" if self.show_pressure_in_mpa else "m"
        self.paths_tree.heading("path_id", text="路径ID")
        self.paths_tree.heading("total_loss", text=f"总水损({pressure_unit})")
        self.paths_tree.heading("nodes_path", text="节点路径", command=self.toggle_path_display)

        # 设置列宽度 - 前四列宽度进一步缩小，最后一列宽度加大
        self.paths_tree.column("path_id", width=70, minwidth=70, stretch=False)
        self.paths_tree.column("total_loss", width=80, minwidth=80, stretch=False)
        self.paths_tree.column("nodes_path", width=600, minwidth=400, stretch=True)  # 节点路径列可拉伸

        # 滚动条
        paths_scrollbar = tk.Scrollbar(
            paths_frame, 
            orient="vertical", 
            command=self.paths_tree.yview,
            width=10
        )
        self.paths_tree.configure(yscrollcommand=paths_scrollbar.set)

        self.paths_tree.pack(side="left", fill="both", expand=True)
        paths_scrollbar.pack(side="right", fill="y")
        # 新增：配置隔行标签
        self.paths_tree.tag_configure("evenrow", background="white")
        self.paths_tree.tag_configure("oddrow", background="#e6f0ff")

    def on_show_zero_flow_changed(self):
        """显示无流量节点和管道选项改变时刷新表格"""
        if hasattr(self, 'original_results'):
            node_results = self.original_results.get("node_results", [])
            self.update_nodes_table(node_results)
            pipe_results = self.original_results.get("pipe_results", [])
            self.update_pipes_table(pipe_results)

    def toggle_path_display(self):
        """切换路径显示模式：节点路径 ↔ 管道路径"""
        if self.path_display_mode == 'nodes':
            self.path_display_mode = 'pipes'
            self.paths_tree.heading("nodes_path", text="管道路径")
        else:
            self.path_display_mode = 'nodes'
            self.paths_tree.heading("nodes_path", text="节点路径")
        
        # 重新填充路径表格
        if hasattr(self, 'all_paths_for_preview'):
            self._refresh_paths_table()

    def _refresh_paths_table(self):
        """根据当前显示模式重新填充路径表格"""
        # 清空表格
        for item in self.paths_tree.get_children():
            self.paths_tree.delete(item)
        
        path_row = 0
        for path_data in self.all_paths_for_preview:
            if self.path_display_mode == 'nodes':
                display_str = path_data["node_path"]
            else:
                display_str = path_data["pipe_path"]
            
            item_id = self.paths_tree.insert("", "end", values=(
                path_data["id"],
                f"{path_data['total_loss']:.4f}",
                display_str
            ))
            tag = "evenrow" if path_row % 2 == 0 else "oddrow"
            self.paths_tree.item(item_id, tags=(tag,))
            path_row += 1

    def create_pipes_table(self, parent):
        """创建管道结果表格 - 添加排序功能"""
        columns = ("pipe_id", "node1", "node2", "nominal_diameter", "inner_diameter", 
                "length", "material", "flow", "velocity", "unit_headloss", 
                "loss", "status")
        
        self.pipes_tree = ttk.Treeview(parent, columns=columns, show="headings", height=12)
        
        # 设置列标题（占位，具体单位在update_table_headers中设置）
        column_headers = {
            "pipe_id": "管道ID",
            "node1": "起点",
            "node2": "终点", 
            "nominal_diameter": "公称管径",
            "inner_diameter": "内径(mm)",
            "length": "管长(m)",
            "material": "管材",
            "flow": "流量",
            "velocity": "流速(m/s)",
            "unit_headloss": "单位水损",
            "loss": "水损",
            "status": "状态"
        }
        
        for col, header in column_headers.items():
            self.pipes_tree.heading(col, text=header, command=lambda c=col: self.sort_pipes_tree(c))
        
        # 设置列宽度（不变）
        column_widths = {
            "pipe_id": 60,
            "node1": 60,
            "node2": 60,
            "nominal_diameter": 80,
            "inner_diameter": 80,
            "length": 70,
            "material": 80,
            "flow": 70,
            "velocity": 70,
            "unit_headloss": 100,
            "loss": 100,
            "status": 60
        }
        for col, width in column_widths.items():
            self.pipes_tree.column(col, width=width)
        
        # 滚动条
        scrollbar = tk.Scrollbar(parent, orient="vertical", command=self.pipes_tree.yview, width=10)
        self.pipes_tree.configure(yscrollcommand=scrollbar.set)
        
        self.pipes_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 新增：配置隔行标签
        self.pipes_tree.tag_configure("evenrow", background="white")
        self.pipes_tree.tag_configure("oddrow", background="#e6f0ff")
        self.pipes_tree.tag_configure("high_velocity", foreground="red")
        self.pipes_tree.tag_configure("low_velocity", foreground="blue")
        
        # 初始化排序状态
        self.pipes_sort_column = "pipe_id"
        self.pipes_sort_reverse = False
        
        # 绑定右键菜单
        self.pipes_tree.bind("<Button-3>", self.show_pipes_context_menu)
        
        return self.pipes_tree

    def sort_pipes_tree(self, col):
        """对管道表格进行排序"""
        if self.pipes_sort_column == col:
            self.pipes_sort_reverse = not self.pipes_sort_reverse
        else:
            self.pipes_sort_column = col
            self.pipes_sort_reverse = False
        if hasattr(self, 'pipe_results_data'):
            self.update_pipes_table(self.pipe_results_data)

    def determine_mode(self):
        supply_pressure_valid = any(s.pressure > 0 for s in self.cad_data_manager.supply_nodes)
        # 只考虑被勾选的组
        demand_flow_valid = any(g.is_selected and g.total_flow > 0 for g in self.cad_data_manager.demand_groups.values())
        demand_min_pressure_valid = any(g.is_selected and g.min_pressure > 0 for g in self.cad_data_manager.demand_groups.values())
        
        # 模式A：供水点压力 + 至少一个勾选组有总流量
        if supply_pressure_valid and demand_flow_valid:
            return 'A'
        # 模式B：仅供水点压力，且无勾选组有总流量或最低水压
        elif supply_pressure_valid and not demand_flow_valid and not demand_min_pressure_valid:
            return 'B'
        # 模式C：仅最低水压，且无供水点压力，且至少一个勾选组有最低水压
        elif not supply_pressure_valid and demand_min_pressure_valid:
            return 'C'
        else:
            return None

    def create_nodes_table(self, parent):
        """创建节点结果表格 - 增加实际压力列"""
        columns = ("node_id", "node_type", "flow", "pressure")  # 增加实际压力列
        self.nodes_tree = ttk.Treeview(parent, columns=columns, show="headings", height=10)
        
        # 设置列标题
        self.nodes_tree.heading("node_id", text="节点ID", command=lambda: self.sort_nodes_tree("node_id"))
        self.nodes_tree.heading("node_type", text="节点类型")
        
        # 根据单位设置动态设置流量和压力列标题
        flow_unit = "m³/h" if self.show_flow_in_m3h else "L/s"
        pressure_unit = "MPa" if self.show_pressure_in_mpa else "m"
        
        self.nodes_tree.heading("flow", text=f"流量({flow_unit})", command=lambda: self.sort_nodes_tree("flow"))
        self.nodes_tree.heading("pressure", text=f"节点压力({pressure_unit})", 
                                command=lambda: self.sort_nodes_tree("pressure"))
        
        # 设置列宽度
        self.nodes_tree.column("node_id", width=75)
        self.nodes_tree.column("node_type", width=80)
        self.nodes_tree.column("flow", width=68)
        self.nodes_tree.column("pressure", width=100)
        
        # 滚动条
        scrollbar = tk.Scrollbar(
            parent, 
            orient="vertical", 
            command=self.nodes_tree.yview,
            width=10
        )
        self.nodes_tree.configure(yscrollcommand=scrollbar.set)
        
        self.nodes_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 配置隔行标签和最低压力标签
        self.nodes_tree.tag_configure("evenrow", background="white")
        self.nodes_tree.tag_configure("oddrow", background="#e6f0ff")  # 浅蓝色
        self.nodes_tree.tag_configure("min_pressure", foreground="red", font=('TkDefaultFont', 9, 'bold'))
        
        # 初始化排序状态
        self.nodes_sort_column = "node_id"
        self.nodes_sort_reverse = False
        
        return self.nodes_tree

    def sort_nodes_tree(self, col):
        """对节点表格进行排序"""
        if self.nodes_sort_column == col:
            self.nodes_sort_reverse = not self.nodes_sort_reverse
        else:
            self.nodes_sort_column = col
            self.nodes_sort_reverse = False
        if hasattr(self, 'original_results'):
            node_results = self.original_results.get("node_results", [])
            self.update_nodes_table(node_results)

    def show_pipes_context_menu(self, event):
        """显示管道表格的右键菜单"""
        pipes_context_menu = tk.Menu(self, tearoff=0)
        pipes_context_menu.add_command(
            label="反写管道ID和水损到CAD",
            command=self.write_back_pipe_loss_to_cad
        )
        pipes_context_menu.add_separator()
        pipes_context_menu.add_command(label="复制选中项", command=self.copy_selected_pipes)
        pipes_context_menu.add_separator()
        pipes_context_menu.add_command(
            label="校正管径（全管网）",
            command=self.correct_all_pipe_diameters
        )
        pipes_context_menu.add_command(
            label="优化管径（全管网）",
            command=self.optimize_all_pipe_diameters
        )
        try:
            pipes_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            pipes_context_menu.grab_release()

    def write_back_pipe_loss_to_cad(self):
        """将管道ID、流量和总水损反写到CAD - 修正版"""
        if not hasattr(self, 'pipe_display_data') or not self.pipe_display_data:
            messagebox.showwarning("无数据", "没有管道结果数据可反写")
            return
        
        try:
            pipes_to_write = []
            flow_unit_str = "m³/h" if self.show_flow_in_m3h else "L/s"
            pressure_unit_str = "MPa" if self.show_pressure_in_mpa else "m"
            
            for pipe in self.pipe_display_data:
                pipe_id = pipe["pipe_id"]
                if not pipe_id.startswith("P_"):
                    continue
                pipe_data = self.cad_data_manager.pipe_by_id.get(pipe_id)
                if not pipe_data:
                    continue
                
                flow = pipe.get("raw_flow", 0.0)          # 原始流量带符号
                total_loss = pipe.get("sort_loss", 0.0)   # 原始水损（未转换单位）
                if self.show_flow_in_m3h:
                    flow_display = abs(flow * 3.6)
                else:
                    flow_display = abs(flow)
                data_line = f"{pipe_id}_{flow_display:.2f}{flow_unit_str}_{total_loss:.3f}{pressure_unit_str}"
                pipe_data.display_text = data_line
                pipe_data.flow_value = flow
                pipe_data.show_arrow = (flow != 0)
                pipes_to_write.append(pipe_data)
            
            if not pipes_to_write:
                messagebox.showwarning("无数据", "没有找到可反写的管道数据")
                return
            
            success, fail, message, _ = self.cad_data_manager.write_back_to_cad("pipes", pipes_to_write)
            if success > 0:
                self.show_temp_message(f"成功反写 {success} 条管道的数据和箭头到CAD")
                logger.info(f"管道反写结果: {message}")
                for pipe in pipes_to_write:
                    for attr_name in ['display_text', 'flow_value', 'show_arrow']:
                        if hasattr(pipe, attr_name):
                            delattr(pipe, attr_name)
            else:
                messagebox.showwarning("反写失败", message)
                
        except Exception as e:
            error_msg = f"反写异常: {str(e)}"
            logger.error(error_msg)
            messagebox.showerror("错误", error_msg)

    def on_units_changed(self):
        self.on_unit_check_changed()

    def copy_selected_pipes(self):
        selection = self.pipes_tree.selection()
        if not selection:
            return
        self.show_temp_message(f"已复制 {len(selection)} 条管道数据")

    def update_pipes_table(self, pipe_results: list):
        self.pipe_results_data = pipe_results.copy()
        for item in self.pipes_tree.get_children():
            self.pipes_tree.delete(item)
        
        flow_factor = 3.6 if self.show_flow_in_m3h else 1.0
        pressure_factor = 0.00980665 if self.show_pressure_in_mpa else 1.0
        self.update_table_headers()
        
        # 收集所有管道数据用于排序
        pipe_display_data = []
        for pipe in pipe_results:
            pipe_id = pipe.get("pipe_id", "")
            if pipe_id.startswith("VP_") or pipe_id.startswith("VD_") or pipe_id == "RESERVOIR":
                continue
            pipe_data = None
            if self.cad_data_manager:
                pipe_data = self.cad_data_manager.pipe_by_id.get(pipe_id)
                if not pipe_data:
                    for p in self.cad_data_manager.pipes:
                        if p.pipe_id == pipe_id:
                            pipe_data = p
                            break
            if pipe_data:
                inner_diameter = pipe_data.inner_diameter
                nominal_diameter = pipe_data.nominal_diameter
                length = pipe_data.length
                material = pipe_data.material
            else:
                inner_diameter = pipe.get("inner_diameter", 0.0)
                nominal_diameter = pipe.get("nominal_diameter", "")
                length = pipe.get("length", 0.0)
                material = pipe.get("material", "")
            
            flow = pipe.get("flow_lps", 0.0)
            velocity = pipe.get("velocity_mps", 0.0)
            headloss_per_km = pipe.get("headloss_per_km", 0.0)

            # 单位水损 (m/m) 优先从 headloss_m 获取，若为0则从 headloss_per_km 计算
            unit_loss = pipe.get("headloss_m", 0.0)
            if unit_loss == 0.0 and length > 0:
                unit_loss = headloss_per_km / 1000.0

            local_loss_ratio = self.config_manager.get_live_config().get("local_loss_ratio", 0.3)
            loss = unit_loss * length * (1 + local_loss_ratio)

            # 用于显示的单位水损（可保留为 unit_loss，也可用 headloss_per_km/1000）
            unit_headloss = unit_loss
            
            flow_display = abs(flow) * flow_factor
            loss_display = loss * pressure_factor
            unit_headloss_display = unit_headloss * pressure_factor
            
            # 存储显示值和排序用的数值
            pipe_display_data.append({
                "pipe_id": pipe_id,
                "node1": pipe.get("node1", ""),
                "node2": pipe.get("node2", ""),
                "nominal_diameter": nominal_diameter,
                "inner_diameter": inner_diameter,
                "length": length,
                "material": material,
                "flow": flow_display,
                "velocity": velocity,
                "unit_headloss": unit_headloss_display,
                "loss": loss_display,
                "status": pipe.get("status", "Open"),
                "raw_flow": flow,                # 原始流量（带符号）用于预览页面
                "sort_flow": abs(flow),          # 绝对值用于排序
                "sort_velocity": velocity,
                "sort_unit_headloss": unit_headloss,
                "sort_loss": loss
            })
        
        if not pipe_display_data:
            return
        
        # 排序
        col = self.pipes_sort_column
        reverse = self.pipes_sort_reverse
        if col == "pipe_id":
            pipe_display_data.sort(key=lambda x: x["pipe_id"], reverse=reverse)
        elif col == "flow":
            pipe_display_data.sort(key=lambda x: x["sort_flow"], reverse=reverse)
        elif col == "velocity":
            pipe_display_data.sort(key=lambda x: x["sort_velocity"], reverse=reverse)
        elif col == "unit_headloss":
            pipe_display_data.sort(key=lambda x: x["sort_unit_headloss"], reverse=reverse)
        elif col == "loss":
            pipe_display_data.sort(key=lambda x: x["sort_loss"], reverse=reverse)
        else:
            # 默认按管道ID排序
            pipe_display_data.sort(key=lambda x: x["pipe_id"], reverse=reverse)
        
        # 插入数据
        row_number = 0
        
        # 保存计算后的管道数据，供预览页面使用
        self.pipe_display_data = pipe_display_data

        config = self.config_manager.get_live_config()
        max_v = config.get("max_velocity", 5.0)
        min_v = config.get("min_velocity", 1.0)

        for pipe in pipe_display_data:
            # 根据复选框决定是否跳过流量为零的管道
            if not self.show_zero_flow_var.get():
                if abs(pipe["raw_flow"]) < 0.001:
                    continue
            # 确定颜色tag
            velocity = pipe["velocity"]
            tags = []
            if velocity > max_v:
                tags.append("high_velocity")
            elif velocity < min_v:
                tags.append("low_velocity")
            # 插入行
            item_id = self.pipes_tree.insert("", "end", values=(
                pipe["pipe_id"],
                pipe["node1"],
                pipe["node2"],
                pipe["nominal_diameter"],
                f"{pipe['inner_diameter']:.1f}" if pipe['inner_diameter'] else "0.0",
                f"{pipe['length']:.2f}" if pipe['length'] else "0.00",
                pipe["material"],
                f"{pipe['flow']:.3f}",
                f"{pipe['velocity']:.3f}" if pipe['velocity'] else "0.00",
                f"{pipe['unit_headloss']:.6f}",
                f"{pipe['loss']:.4f}",
                pipe["status"]
            ))
            base_tag = "evenrow" if row_number % 2 == 0 else "oddrow"
            all_tags = (base_tag,) + tuple(tags) if tags else (base_tag,)
            self.pipes_tree.item(item_id, tags=all_tags)
            row_number += 1
        


    def setup_bindings(self):
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="复制选中项", command=self.copy_selected)
        self.context_menu.add_command(label="导出选中路径", command=self.export_selected_path)
        self.nodes_tree.bind("<Button-3>", self.show_context_menu)
        self.paths_tree.bind("<Button-3>", self.show_context_menu)

    def get_current_project_dir(self):
        if not self.cad_data_manager.is_loaded:
            messagebox.showwarning("无数据", "请先加载CAD数据")
            return None
        cad_file_path = self.cad_data_manager.cad_file_path
        if not cad_file_path:
            messagebox.showwarning("无CAD文件", "未找到当前CAD文件路径")
            return None
        cad_name = os.path.splitext(os.path.basename(cad_file_path))[0]
        base_dir = self.projects_base_dir
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
        project_index = 1
        while True:
            project_dir_name = f"{cad_name}_{project_index:03d}"
            project_dir = os.path.join(base_dir, project_dir_name)
            if not os.path.exists(project_dir):
                os.makedirs(project_dir)
                self.current_project_dir = project_dir
                self.current_cad_file = cad_file_path
                self.cad_data_manager.current_project_dir = self.current_project_dir
                logger.info(f"创建项目目录: {project_dir}")
                break
            meta_file = os.path.join(project_dir, "project_meta.json")
            if os.path.exists(meta_file):
                try:
                    with open(meta_file, 'r') as f:
                        meta = json.load(f)
                    if meta.get("cad_file") == cad_file_path:
                        self.current_project_dir = project_dir
                        self.current_cad_file = cad_file_path
                        self.cad_data_manager.current_project_dir = self.current_project_dir                        
                        logger.info(f"使用现有项目目录: {project_dir}")
                        break
                except:
                    pass
            project_index += 1
        self.save_project_metadata()
        return self.current_project_dir

    def save_project_metadata(self):
        if not self.current_project_dir:
            return
        meta = {
            "cad_file": self.cad_data_manager.cad_file_path,
            "created_at": datetime.now().isoformat(),
            "last_calculated": "",
            "config": self.config_manager.get_live_config(),
            "summary": self.cad_data_manager.get_summary()
        }
        meta_file = os.path.join(self.current_project_dir, "project_meta.json")
        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

    def update_project_metadata(self, calculation_info: dict):
        if not self.current_project_dir:
            return
        meta_file = os.path.join(self.current_project_dir, "project_meta.json")
        if os.path.exists(meta_file):
            try:
                with open(meta_file, 'r') as f:
                    meta = json.load(f)
                meta["last_calculated"] = datetime.now().isoformat()
                meta["last_calculation"] = calculation_info
                with open(meta_file, 'w', encoding='utf-8') as f:
                    json.dump(meta, f, indent=2, ensure_ascii=False)
            except:
                pass

    def generate_inp_file(self):
        if not self.cad_data_manager.is_loaded:
            messagebox.showwarning("无数据", "请先加载CAD数据")
            return
        project_dir = self.get_current_project_dir()
        if not project_dir:
            return
        demand_groups = {}
        try:
            if hasattr(self.cad_data_manager, 'demand_groups'):
                demand_groups = self.cad_data_manager.demand_groups
                formatted_groups = {}
                for group_id, group in demand_groups.items():
                    formatted_groups[group_id] = {
                        "is_selected": group.is_selected,
                        "total_flow": group.total_flow,
                        "demand_nodes": group.demand_nodes
                    }
                demand_groups = formatted_groups
        except Exception as e:
            logger.warning(f"获取用水点组数据失败: {e}")
        self.status_label.config(text="正在生成INP文件...")
        self.progress_bar.start()
        success, message, demand_models = self.inp_generator.generate_inp_file(
            self.cad_data_manager,
            project_dir,
            demand_groups
        )
        self.progress_bar.stop()
        if success:
            self.status_label.config(text=f"INP文件生成成功: {message}")
            self.calculate_btn.config(state="normal")
            self.demand_models = demand_models
            self.show_temp_message("INP文件生成成功")
        else:
            self.status_label.config(text=f"生成失败: {message}")
            messagebox.showerror("生成失败", f"生成INP文件失败:\n{message}")

    def start_calculation(self):
        """开始计算（根据模式分流）"""
        if self.is_calculating:
            return

        # 判断模式
        mode = self.determine_mode()
        if mode is None:
            messagebox.showwarning("输入无效", "请检查供水点压力和用水点组输入，必须符合模式A/B/C之一")
            return

        # 获取系统类型（从配置）
        config = self.config_manager.get_live_config()
        system_type = config.get("system_type", "outdoor_hydrant")

        # 模式A：室外消火栓或任何有总流量的情况
        if mode == 'A':
            if system_type != "outdoor_hydrant":
                messagebox.showwarning("不匹配", "模式A（有总流量）仅支持室外消火栓管网类型，请在设置页面选择室外消火栓")
                return
            self.run_mode_A(system_type)
        elif mode in ('B', 'C'):
            if system_type not in ("indoor_hydrant", "sprinkler"):
                messagebox.showwarning("不匹配", "模式B/C（压力驱动）仅支持室内消火栓或喷淋，请在设置页面选择对应类型")
                return
            self.run_pressure_driven(mode, system_type)
        else:
            pass

    def run_mode_A(self, system_type):
        """模式A：室外消防，使用虚拟节点"""
        # 准备用水点组数据（同原有逻辑）
        demand_groups = {}
        try:
            if hasattr(self.cad_data_manager, 'demand_groups'):
                groups = self.cad_data_manager.demand_groups
                formatted = {}
                for gid, group in groups.items():
                    formatted[gid] = {
                        "is_selected": getattr(group, 'is_selected', False),
                        "total_flow": getattr(group, 'total_flow', 0.0),
                        "demand_nodes": getattr(group, 'demand_nodes', [])
                    }
                demand_groups = formatted
        except Exception as e:
            logger.warning(f"获取用水点组数据失败: {e}")

        # 生成INP文件
        success, message, demand_models = self.inp_generator.generate_inp_file(
            self.cad_data_manager,
            self.current_project_dir,
            demand_groups,
            no_virtual=False,          # 模式A使用虚拟节点
            calc_type=system_type       # 传入系统类型（可能用于将来扩展）
        )

        if not success:
            messagebox.showerror("生成INP失败", message)
            return

        self.demand_models = demand_models
        inp_file = os.path.join(self.current_project_dir, "network.inp")

        # 启动计算线程（同原有逻辑）
        self.is_calculating = True
        self.calculate_btn.config(state="disabled")
        self.export_btn.config(state="disabled")
        self.calculation_thread = threading.Thread(
            target=self.run_calculation_thread,
            args=(inp_file,)
        )
        self.calculation_thread.daemon = True
        self.calculation_thread.start()
        self.monitor_calculation_progress()

    def run_calculation_thread(self, inp_file: str):
        try:
            success, message, _ = self.epanet_calc.run_analysis(
                inp_file, timeout=120
            )
            if success:
                results_obj = self.epanet_calc.last_results
                wn = self.epanet_calc.last_wn
                parse_success, parse_msg, results = self.result_parser.parse_report_file(
                    None, results_obj=results_obj, wn=wn
                )
                if parse_success:
                    self.calculation_results = results
                    calc_info = {
                        "inp_file": inp_file,
                        "timestamp": datetime.now().isoformat(),
                        "summary": results.get("summary", {})
                    }
                    self.update_project_metadata(calc_info)
                    self.after(0, self.on_calculation_success, results)
                else:
                    self.after(0, self.on_calculation_error, f"解析失败: {parse_msg}")
            else:
                self.after(0, self.on_calculation_error, f"计算失败: {message}")
        except Exception as e:
            self.after(0, self.on_calculation_error, f"计算异常: {str(e)}")

    def monitor_calculation_progress(self):
        if not self.is_calculating:
            return
        status = self.epanet_calc.get_status()
        self.progress_bar["value"] = status["progress"]
        self.status_label.config(text=status["status"])
        if status["is_running"]:
            self.after(500, self.monitor_calculation_progress)

    def run_pressure_driven(self, mode, system_type):
        """启动压力驱动计算线程"""
        self.get_current_project_dir()
        # 获取计算参数
        config = self.config_manager.get_live_config()
        K = config.get("sprinkler_K", 80)
        Ad = config.get("hydrant_Ad", 0.00172)
        Ld = config.get("hydrant_Ld", 25)
        B = config.get("hydrant_B", 1.577)
        Hak = config.get("hydrant_Hak", 2.0)

        # 映射系统类型到求解器的 calc_type
        if system_type == "indoor_hydrant":
            calc_type = "hydrant"
        else:
            calc_type = "sprinkler"

        # 导入求解器
        from core.pressure_driven_solver import PressureDrivenSolver

        solver = PressureDrivenSolver(
            cad_data_manager=self.cad_data_manager,
            config_manager=self.config_manager,
            calc_type=calc_type,
            mode=mode,
            sprinkler_K=K,
            hydrant_Ad=Ad,
            hydrant_Ld=Ld,
            hydrant_B=B,
            hydrant_Hak=Hak,
            progress_callback=self._update_solver_progress
        )

        def thread_func():
            success, results, message = solver.solve()
            self.after(0, self._on_pressure_driven_finished, success, results, message)

        self.is_calculating = True
        self.calculate_btn.config(state="disabled")
        self.export_btn.config(state="disabled")
        self.calculation_thread = threading.Thread(target=thread_func, daemon=True)
        self.calculation_thread.start()
        self.monitor_calculation_progress()

    def _update_solver_progress(self, progress, status):
        """更新进度（由求解器回调）"""
        self.progress_bar["value"] = progress
        self.status_label.config(text=status)

    def _on_pressure_driven_finished(self, success, results, message):
        self.is_calculating = False
        self.calculate_btn.config(state="normal")
        self.export_btn.config(state="normal")
        if success:
            self.original_results = results.copy()
            self.display_results(results)
            self.progress_bar["value"] = 100
            self.status_label.config(text="计算完成")
            self._save_results_to_project(results)
            self.show_temp_message("计算成功")
            logger.info(f"压力驱动计算成功: {message}")

        else:
            self.progress_bar["value"] = 0
            self.status_label.config(text="计算失败")
            messagebox.showerror("计算失败", message)
            logger.error(f"压力驱动计算失败: {message}")


    def on_calculation_success(self, results: dict):
        self.is_calculating = False
        self.calculate_btn.config(state="normal")
        self.export_btn.config(state="normal")
        self.progress_bar["value"] = 100
        self.status_label.config(text="计算完成")
        self.original_results = results.copy()
        if self.cad_data_manager and hasattr(self.cad_data_manager, 'nodes'):
            for node_result in results.get("node_results", []):
                node_id = node_result["node_id"]
                cad_node = self.cad_data_manager.node_by_id.get(node_id)
                if cad_node:
                    node_result["node_type"] = cad_node.node_type
        self.display_results(results)
        self._save_results_to_project(results)
        self.show_temp_message("计算完成")
        logger.info("计算成功完成")

    def _save_results_to_project(self, results):
        """保存计算结果到项目目录的 results.json"""
        if not self.current_project_dir:
            return
        import json
        from datetime import datetime

        # 尝试导入 numpy，用于类型转换
        try:
            import numpy as np
        except ImportError:
            np = None

        # 递归转换 numpy 类型为 Python 原生类型
        def convert_to_serializable(obj):
            if np is not None:
                if isinstance(obj, np.integer):
                    return int(obj)
                elif isinstance(obj, np.floating):
                    return float(obj)
                elif isinstance(obj, np.ndarray):
                    return obj.tolist()
            if isinstance(obj, (list, tuple)):
                return [convert_to_serializable(item) for item in obj]
            elif isinstance(obj, dict):
                return {key: convert_to_serializable(value) for key, value in obj.items()}
            else:
                return obj

        # 构建保存的数据结构
        save_data = {
            "计算时间": datetime.now().isoformat(),
            "设置": {
                "流量单位": "m³/h" if self.show_flow_in_m3h else "L/s",
                "压力单位": "MPa" if self.show_pressure_in_mpa else "m"
            }
        }

        # 1. 节点结果（从 original_results 中提取）
        if hasattr(self, 'original_results'):
            node_results = self.original_results.get("node_results", [])
            save_data["节点结果"] = convert_to_serializable(node_results)

        # 2. 管道结果（从 pipe_display_data 中获取，包含计算后的水损和流量）
        if hasattr(self, 'pipe_display_data') and self.pipe_display_data:
            pipe_data_for_save = []
            for pipe in self.pipe_display_data:
                # 构建清晰的管道结果字典
                pipe_copy = {
                    "管道ID": pipe["pipe_id"],
                    "起点": pipe["node1"],
                    "终点": pipe["node2"],
                    "公称管径": pipe["nominal_diameter"],
                    "内径(mm)": pipe["inner_diameter"],
                    "管长(m)": pipe["length"],
                    "管材": pipe["material"],
                    "流量(L/s)": pipe.get("raw_flow", 0.0),          # 原始流量，带符号
                    "流速(m/s)": pipe["velocity"],
                    "单位水损(m/m)": pipe["sort_unit_headloss"],
                    "水损(m)": pipe["sort_loss"],
                    "状态": pipe["status"]
                }
                pipe_data_for_save.append(pipe_copy)
            save_data["管道结果"] = convert_to_serializable(pipe_data_for_save)

        # 3. 路径结果（从 all_paths_for_preview 中获取）
        if hasattr(self, 'all_paths_for_preview') and self.all_paths_for_preview:
            path_data_for_save = []
            for path in self.all_paths_for_preview:
                path_copy = {
                    "路径ID": path["id"],
                    "起点": path["start"],
                    "终点": path["end_group"],
                    "节点路径": path["node_path"],
                    "管道路径": path["pipe_path"],
                    "总水损(m)": path["total_loss"],
                    "总长度(m)": path["length"]
                }
                path_data_for_save.append(path_copy)
            save_data["路径结果"] = convert_to_serializable(path_data_for_save)

        # 4. 原始结果（可选，保留原始 WNTR 结果作为备份）
        save_data["原始结果"] = convert_to_serializable(results)

        # 写入文件
        file_path = os.path.join(self.current_project_dir, "results.json")
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=2, ensure_ascii=False)
            logger.info(f"计算结果已保存至 {file_path}")
        except Exception as e:
            logger.error(f"保存结果文件失败: {e}")

    def on_calculation_error(self, error_msg: str):
        self.is_calculating = False
        self.calculate_btn.config(state="normal")
        self.progress_bar["value"] = 0
        self.status_label.config(text="计算失败")
        messagebox.showerror("计算失败", error_msg)
        logger.error(f"计算失败: {error_msg}")

    def display_results(self, results: dict):
        self.original_results = results.copy()
        node_results = results.get("node_results", [])
        self.update_nodes_table(node_results)
        pipe_results = results.get("pipe_results", [])
        self.update_pipes_table(pipe_results)
        self.find_and_display_all_paths(results)
        self.status_label.config(text="计算完成")
        self.progress_bar["value"] = 100

        pipe_dict = {}
        # ===== 修改：传递所有管道类型的计算结果（P_, R_, B_, L_） =====
        for pipe in self.pipe_display_data:
            pipe_id = pipe["pipe_id"]
            # 去掉过滤条件，所有管道都传递
            pipe_dict[pipe_id] = {
                "flow_lps": pipe.get("raw_flow", 0.0),   # 原始流量带符号
                "total_loss": pipe.get("sort_loss", 0.0)
            }
        root = self.winfo_toplevel()
        main_app = getattr(root, 'main_app', None)
        if main_app and hasattr(main_app, 'pages'):
            preview_page = main_app.pages.get("管网预览")
            if preview_page:
                preview_page.set_calculation_results(pipe_dict)
                logger.info(f"已传递 {len(pipe_dict)} 条管道计算结果到预览页面")
        # 传递节点压力
        node_pressure_dict = {}
        for node_res in results.get("node_results", []):
            node_id = node_res["node_id"]
            if node_id.startswith(("D_", "VD_", "RESERVOIR")):
                continue
            # 跳过检修节点：所有连接管道都已关闭
            if self.cad_data_manager and hasattr(self.cad_data_manager, 'node_by_id'):
                cn = self.cad_data_manager.node_by_id.get(node_id)
                if cn and cn.connected_pipes:
                    has_open = False
                    for pid in cn.connected_pipes:
                        p = self.cad_data_manager.pipe_by_id.get(pid)
                        if p and p.status == "开":
                            has_open = True
                            break
                    if not has_open:
                        continue
            node_pressure_dict[node_id] = node_res.get("pressure_m", 0.0)
        if main_app and hasattr(main_app, 'pages'):
            preview_page = main_app.pages.get("管网预览")
            if preview_page:
                preview_page.set_node_pressures(node_pressure_dict)
                logger.info(f"已传递 {len(node_pressure_dict)} 个节点压力到预览页面")                


    def update_nodes_table(self, node_results: list):
        for item in self.nodes_tree.get_children():
            self.nodes_tree.delete(item)

        pipe_results = self.original_results.get("pipe_results", [])
        real_pipes = [p for p in pipe_results if p.get("pipe_id", "").startswith("P_")]
        outflow = {}
        inflow = {}
        for pipe in real_pipes:
            n1 = pipe.get("node1", "")
            n2 = pipe.get("node2", "")
            flow = pipe.get("flow_lps", 0.0)
            abs_flow = abs(flow)
            if flow > 0:
                outflow[n1] = outflow.get(n1, 0.0) + abs_flow
                inflow[n2] = inflow.get(n2, 0.0) + abs_flow
            elif flow < 0:
                outflow[n2] = outflow.get(n2, 0.0) + abs_flow
                inflow[n1] = inflow.get(n1, 0.0) + abs_flow

        node_type_map = {}
        if self.cad_data_manager and hasattr(self.cad_data_manager, 'nodes'):
            for node in self.cad_data_manager.nodes:
                node_type_map[node.node_id] = node.node_type

        selected_demand_node_ids = set()
        for group in self.cad_data_manager.demand_groups.values():
            if group.is_selected:
                for demand_node in group.demand_nodes:
                    selected_demand_node_ids.add(demand_node.node_id)

        flow_factor = 3.6 if self.show_flow_in_m3h else 1.0
        pressure_factor = 0.00980665 if self.show_pressure_in_mpa else 1.0

        # 获取供水点压力（假设第一个供水点组）
        supply_pressure = 0.0
        if self.cad_data_manager.supply_nodes:
            supply_pressure = self.cad_data_manager.supply_nodes[0].pressure

        display_nodes = []
        for node in node_results:
            node_id = node["node_id"]
            if node_id == "RESERVOIR" or node_id.startswith("D_"):
                continue
            node_type = node_type_map.get(node_id, "普通节点")
            if "用水点" in node_type and node_id not in selected_demand_node_ids:
                continue
            # 跳过所有连接管道都已关闭的节点（检修区中的孤立节点）
            if self.cad_data_manager and hasattr(self.cad_data_manager, 'node_by_id'):
                cad_node = self.cad_data_manager.node_by_id.get(node_id)
                if cad_node and cad_node.connected_pipes:
                    has_open = False
                    for pid in cad_node.connected_pipes:
                        p = self.cad_data_manager.pipe_by_id.get(pid)
                        if p and p.status == "开":
                            has_open = True
                            break
                    if not has_open:
                        continue

            # 从节点结果中获取流量（压力驱动计算的结果）
            # 注意：节点结果中 demand_lps 是用水点的需求，供水点无需求
            if "用水点" in node_type:
                # 用水点：直接使用计算结果中的需求
                node_flow = node.get("demand_lps", 0.0)
            elif "供水点" in node_type:
                # 供水点：流量为流出该节点的管道流量之和
                node_flow = outflow.get(node_id, 0.0)
            else:
                # 普通节点：取平均
                total = outflow.get(node_id, 0.0) + inflow.get(node_id, 0.0)
                node_flow = total / 2.0

            pressure = node["pressure_m"]  # WNTR 计算的无局部水损压力
            node_flow_display = node_flow * flow_factor
            pressure_display = pressure * pressure_factor
            flow_format = f"{node_flow_display:.3f}"
            pressure_format = f"{pressure_display:.3f}" if self.show_pressure_in_mpa else f"{pressure_display:.2f}"

            display_nodes.append({
                "node_id": node_id,
                "node_type": node_type,
                "flow": node_flow_display,
                "pressure": pressure_display,
                "display_flow": flow_format,
                "display_pressure": pressure_format,
                "raw_pressure": pressure,
                "raw_flow": node_flow, 
                "sort_group": 0 if "供水点" in node_type else (1 if "用水点" in node_type else 2)
            })

        if not display_nodes:
            return

        # 分组排序
        col = self.nodes_sort_column
        reverse = self.nodes_sort_reverse
        display_nodes.sort(key=lambda x: x["sort_group"])

        group_start = 0
        for group_val in [0, 1, 2]:
            group_nodes = [n for n in display_nodes if n["sort_group"] == group_val]
            if group_nodes:
                if col == "node_id":
                    group_nodes.sort(key=lambda x: x["node_id"], reverse=reverse)
                elif col == "flow":
                    group_nodes.sort(key=lambda x: x["flow"], reverse=reverse)
                elif col == "pressure":
                    group_nodes.sort(key=lambda x: x["pressure"], reverse=reverse)
                else:
                    group_nodes.sort(key=lambda x: x["node_id"], reverse=reverse)
                display_nodes[group_start:group_start + len(group_nodes)] = group_nodes
                group_start += len(group_nodes)

        min_raw_pressure = min(n["raw_pressure"] for n in display_nodes)

        row_number = 0
        for node in display_nodes:
            # 根据复选框决定是否跳过流量为零的节点
            if not self.show_zero_flow_var.get():
                # 判断流量是否为零（用水点节点用 demand_lps，普通节点用 node_flow）
                flow_abs = abs(node.get("raw_flow", 0.0)) if "raw_flow" in node else 0.0
                if flow_abs < 0.001:
                    continue
            item_id = self.nodes_tree.insert("", "end", values=(
                node["node_id"],
                node["node_type"],
                node["display_flow"],
                node["display_pressure"]
            ))
            base_tag = "evenrow" if row_number % 2 == 0 else "oddrow"
            tags = [base_tag]
            if node["raw_pressure"] == min_raw_pressure:
                tags.append("min_pressure")
            self.nodes_tree.item(item_id, tags=tags)
            row_number += 1

    def find_and_display_all_paths(self, results: dict):
        """查找并显示所有基于流向的路径，同时计算节点总水损"""
        self.all_paths_for_preview = []   # 重置路径列表
        self.node_total_loss = {}         # 重置节点水损字典
        logger.info("开始查找基于流向的所有路径...")
       
        # 清空路径表格
        for item in self.paths_tree.get_children():
            self.paths_tree.delete(item)
        
        # 确保变量存在
        supply_nodes = []
        demand_nodes = []

        pipe_results = results.get("pipe_results", [])
        node_results = results.get("node_results", [])
        if not pipe_results:
            logger.warning("没有管道结果数据")
            return
        
        # 构建有向图和管道信息字典
        directed_graph = {}
        pipe_info = {}
        for pipe in pipe_results:
            pipe_id = pipe.get("pipe_id", "")
            if pipe_id.startswith("VP_") or pipe_id.startswith("VD_") or pipe_id == "RESERVOIR":
                continue
            n1 = pipe.get("node1", "")
            n2 = pipe.get("node2", "")
            flow = pipe.get("flow_lps", 0.0)
            if n1 and n2:
                pipe_info[(n1, n2)] = pipe
                pipe_info[(n2, n1)] = pipe
                if flow > 0.001:
                    if n1 not in directed_graph:
                        directed_graph[n1] = []
                    directed_graph[n1].append(n2)
                elif flow < -0.001:
                    if n2 not in directed_graph:
                        directed_graph[n2] = []
                    directed_graph[n2].append(n1)
        
        logger.info(f"构建的有向图包含 {len(directed_graph)} 个节点")
        # 打印有向图节点列表（前10个）
        logger.info(f"有向图节点示例: {list(directed_graph.keys())[:10]}")
        # 检查供水点和用水点是否在图内
        for supply in supply_nodes:
            logger.info(f"供水点 {supply} 在图中: {supply in directed_graph}")
        for demand in demand_nodes[:5]:
            logger.info(f"用水点 {demand} 在图中: {demand in directed_graph}")
        # 打印前10条管道的流量信息
        for pipe in pipe_results[:10]:
            logger.info(f"管道 {pipe['pipe_id']}: {pipe['node1']} -> {pipe['node2']}, flow={pipe['flow_lps']:.3f}")
        
        # 获取所有供水点节点
        supply_nodes = []
        if self.cad_data_manager and hasattr(self.cad_data_manager, 'supply_nodes'):
            for supply in self.cad_data_manager.supply_nodes:
                supply_nodes.extend(supply.node_ids)
        supply_nodes = list(set(supply_nodes))
        
        # 获取所有被勾选的用水点节点
        demand_nodes = []
        if self.cad_data_manager and hasattr(self.cad_data_manager, 'demand_groups'):
            for group in self.cad_data_manager.demand_groups.values():
                if group.is_selected:
                    for demand_node in group.demand_nodes:
                        if demand_node.node_id not in demand_nodes:
                            demand_nodes.append(demand_node.node_id)
        if not demand_nodes:
            # 如果从勾选组未找到，则从节点结果中找有需求的节点
            for node in node_results:
                if node.get("demand_lps", 0.0) > 0.001:
                    demand_nodes.append(node["node_id"])
        
        logger.info(f"找到供水点: {supply_nodes}")
        logger.info(f"找到用水点: {demand_nodes}")
        
        if not supply_nodes or not demand_nodes:
            logger.warning("未找到供水点或用水点")
            return
        
        pressure_factor = 0.00980665 if self.show_pressure_in_mpa else 1.0
        pressure_unit = "MPa" if self.show_pressure_in_mpa else "m"
        self.paths_tree.heading("total_loss", text=f"总水损({pressure_unit})")
        
        path_id = 1
        path_row = 0
        found_paths = 0
        max_paths_per_pair = 10
        visited_pairs = set()
        
        for supply in supply_nodes:
            if supply not in directed_graph:
                continue
            for demand in demand_nodes:
                if supply == demand:
                    continue
                pair_key = f"{supply}_{demand}"
                if pair_key in visited_pairs:
                    continue
                visited_pairs.add(pair_key)
                
                paths = self.find_directed_paths(directed_graph, supply, demand, max_paths_per_pair)
                for path in paths:
                    if len(path) < 2:
                        continue
                    
                    total_friction_loss = 0.0
                    total_length = 0.0
                    path_valid = True
                    pipe_ids = []
                    # 计算路径总沿程水损和总长度，同时收集管道ID
                    for i in range(len(path) - 1):
                        n1, n2 = path[i], path[i+1]
                        pipe = pipe_info.get((n1, n2))
                        if not pipe:
                            path_valid = False
                            logger.debug(f"路径无效: 管道缺失 {n1}→{n2}")
                            break
                        unit_loss = pipe.get("headloss_m", 0.0)
                        pipe_length = pipe.get("length", 0.0)
                        friction_loss_pipe = unit_loss * pipe_length
                        total_friction_loss += abs(friction_loss_pipe)
                        total_length += pipe_length
                        pipe_ids.append(pipe.get("pipe_id", ""))
                    
                    if not path_valid or total_friction_loss < 0:
                        continue
                    
                    # 计算路径总水损
                    total_loss = total_friction_loss
                    
                    # 计算路径上每个节点的累计水损（用于实际压力）
                    accumulated_loss = 0.0
                    # 供水点本身水损为0
                    self.node_total_loss[supply] = 0.0
                    for i in range(len(path) - 1):
                        n1, n2 = path[i], path[i+1]
                        pipe = pipe_info.get((n1, n2))
                        if pipe:
                            unit_loss = pipe.get("headloss_m", 0.0)
                            pipe_length = pipe.get("length", 0.0)
                            pipe_friction = unit_loss * pipe_length
                            accumulated_loss += pipe_friction
                            # 节点处总水损 = 累计沿程水损 + 累计局部水损（按比例）
                            node_total_loss = accumulated_loss
                            if n2 not in self.node_total_loss or node_total_loss > self.node_total_loss[n2]:
                                self.node_total_loss[n2] = node_total_loss
                    
                    # 格式化显示值
                    friction_loss_display = total_friction_loss * pressure_factor
                    total_loss_display = total_loss * pressure_factor
                    node_path_str = " → ".join(path)
                    pipe_path_str = " → ".join(pipe_ids)
                    
                    # 存储路径数据（同时包含预览所需字段和表格显示所需字段）
                    path_data = {
                        "id": f"PATH_{path_id:03d}",
                        "nodes": path,
                        "pipes": pipe_ids,
                        "node_path": node_path_str,
                        "pipe_path": pipe_path_str,
                        "total_loss": total_loss_display,
                        "loss": total_loss,
                        "start": supply,          # 预览页面需要
                        "end_group": demand,      # 预览页面需要
                        "length": total_length    # 预览页面需要
                    }
                    self.all_paths_for_preview.append(path_data)
                    
                    # 根据当前显示模式插入表格
                    if self.path_display_mode == 'nodes':
                        display_str = node_path_str
                    else:
                        display_str = pipe_path_str
                    
                    item_id = self.paths_tree.insert("", "end", values=(
                        path_data["id"],
                        f"{total_loss_display:.4f}",
                        display_str
                    ))
                    tag = "evenrow" if path_row % 2 == 0 else "oddrow"
                    self.paths_tree.item(item_id, tags=(tag,))
                    path_row += 1
                    path_id += 1
                    found_paths += 1
        
        logger.info(f"共找到 {found_paths} 条基于流向的有效路径")
        logger.info(f"准备传递给预览页面的路径数: {len(self.all_paths_for_preview)}")
        
        # 刷新路径表格（确保显示最新）
        self._refresh_paths_table()
        
        # 传递给预览页面
        root = self.winfo_toplevel()
        main_app = getattr(root, 'main_app', None)
        if main_app and hasattr(main_app, 'pages'):
            preview_page = main_app.pages.get("管网预览")
            if preview_page:
                preview_page.set_path_list(self.all_paths_for_preview)
                logger.info("已调用预览页面的 set_path_list")
        
        # 刷新节点表格以更新实际压力
        if hasattr(self, 'original_results'):
            self.update_nodes_table(self.original_results.get("node_results", []))

    def find_directed_paths(self, graph, start, end, max_paths=10):
        paths = []
        def dfs(current, visited, path):
            if len(paths) >= max_paths:
                return
            if current == end:
                paths.append(path.copy())
                return
            downstream_nodes = graph.get(current, [])
            for next_node in downstream_nodes:
                if (next_node.startswith("RESERVOIR") or 
                    next_node.startswith("VD_") or 
                    next_node.startswith("D_")):
                    continue
                if next_node not in visited:
                    visited.add(next_node)
                    path.append(next_node)
                    dfs(next_node, visited, path)
                    path.pop()
                    visited.remove(next_node)
        if (start.startswith("RESERVOIR") or 
            start.startswith("VD_") or 
            start.startswith("D_")):
            return paths
        visited = {start}
        dfs(start, visited, [start])
        return paths

    def on_unit_check_changed(self):
        self.show_flow_in_m3h = self.flow_unit_var.get()
        self.show_pressure_in_mpa = self.pressure_unit_var.get()
        self.update_table_headers()
        if hasattr(self, 'original_results'):
            node_results = self.original_results.get("node_results", [])
            self.update_nodes_table(node_results)
            pipe_results = self.original_results.get("pipe_results", [])
            self.update_pipes_table(pipe_results)
            self.find_and_display_all_paths(self.original_results)

    def update_table_headers(self):
        demand_unit = "m³/h" if self.show_flow_in_m3h else "L/s"
        pressure_unit = "MPa" if self.show_pressure_in_mpa else "m"
        if hasattr(self, 'nodes_tree'):
            self.nodes_tree.heading("flow", text=f"流量({demand_unit})")
            self.nodes_tree.heading("pressure", text=f"节点压力({pressure_unit})")
        if hasattr(self, 'pipes_tree'):
            self.pipes_tree.heading("flow", text=f"流量({demand_unit})")
            self.pipes_tree.heading("loss", text=f"水损({pressure_unit})")
            self.pipes_tree.heading("unit_headloss", text=f"单位水损({pressure_unit}/m)")
        if hasattr(self, 'paths_tree'):
            self.paths_tree.heading("total_loss", text=f"总水损({pressure_unit})")



    def export_results(self):
        if not hasattr(self, 'original_results'):
            messagebox.showwarning("无结果", "请先进行计算")
            return
        default_name = os.path.basename(self.current_project_dir) + "_results"
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON文件", "*.json"), ("Excel文件", "*.xlsx"), ("所有文件", "*.*")],
            initialfile=default_name
        )
        if not file_path:
            return
        try:
            export_data = self.collect_all_table_data()
            if file_path.endswith('.json'):
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, indent=2, ensure_ascii=False)
            elif file_path.endswith('.xlsx'):
                self.export_to_excel(file_path, export_data)
            self.show_temp_message(f"结果已导出: {file_path}")
            logger.info(f"结果导出成功: {file_path}")
        except Exception as e:
            messagebox.showerror("导出失败", f"导出结果失败:\n{str(e)}")
            logger.error(f"导出结果失败: {e}")

    def collect_all_table_data(self):
        export_data = {
            "节点结果": [],
            "管道结果": [],
            "路径结果": [],
            "计算设置": {
                "流量单位": "m³/h" if self.show_flow_in_m3h else "L/s",
                "压力单位": "MPa" if self.show_pressure_in_mpa else "m"
            }
        }
        for item in self.nodes_tree.get_children():
            values = self.nodes_tree.item(item, "values")
            if values:
                export_data["节点结果"].append({
                    "节点ID": values[0],
                    "节点类型": values[1],
                    "流量": values[2],
                    "压力": values[3]
                })
        for item in self.pipes_tree.get_children():
            values = self.pipes_tree.item(item, "values")
            if values and len(values) >= 12:
                export_data["管道结果"].append({
                    "管道ID": values[0],
                    "起点": values[1],
                    "终点": values[2],
                    "公称管径": values[3],
                    "内径(mm)": values[4],
                    "管长(m)": values[5],
                    "管材": values[6],
                    "流量": values[7],
                    "流速(m/s)": values[8],
                    "单位水损(m/m)": values[9],
                    "水损(m)": values[10],
                    "状态": values[11]
                })
        for item in self.paths_tree.get_children():
            values = self.paths_tree.item(item, "values")
            if values and len(values) >= 3:
                export_data["路径结果"].append({
                    "路径ID": values[0],
                    "总水损(m)": values[1],
                    "节点路径": values[2]
                })
        return export_data

    def export_to_excel(self, file_path: str, data: dict):
        try:
            import pandas as pd
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                if data["节点结果"]:
                    df_nodes = pd.DataFrame(data["节点结果"])
                    df_nodes.to_excel(writer, sheet_name='节点结果', index=False)
                if data["管道结果"]:
                    df_pipes = pd.DataFrame(data["管道结果"])
                    df_pipes.to_excel(writer, sheet_name='管道结果', index=False)
                if data["路径结果"]:
                    df_paths = pd.DataFrame(data["路径结果"])
                    df_paths.to_excel(writer, sheet_name='路径结果', index=False)
                df_settings = pd.DataFrame([data["计算设置"]])
                df_settings.to_excel(writer, sheet_name='计算设置', index=False)
        except ImportError:
            messagebox.showerror("导出失败", "导出Excel需要pandas库，请先安装：\npip install pandas openpyxl")

    def export_selected_path(self):
        selection = self.paths_tree.selection()
        if not selection:
            return
        item = self.paths_tree.item(selection[0])
        values = item["values"]
        messagebox.showinfo("导出路径", f"将导出路径: {values[0]}")

    def copy_selected(self):
        selection = self.paths_tree.selection()
        if selection:
            self.show_temp_message(f"已复制 {len(selection)} 条路径数据")

    def show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def show_temp_message(self, message: str, duration: int = 2000):
        root = self.winfo_toplevel()
        if hasattr(root, 'show_temp_message'):
            root.show_temp_message(message, duration)

    def refresh_data(self):
        if self.cad_data_manager.is_loaded:
            cad_file = self.cad_data_manager.cad_file_path
            if cad_file != self.current_cad_file:
                self.current_project_dir = ""
                self.current_cad_file = ""
                self.calculate_btn.config(state="disabled")
                self.export_btn.config(state="disabled")
                for tree in [self.paths_tree, self.nodes_tree, self.pipes_tree]:
                    for item in tree.get_children():
                        tree.delete(item)
        if self.cad_data_manager.is_loaded:
            self.calculate_btn.config(state="normal")
        self.update_table_headers()
        self.status_label.config(text="就绪")
        # 如果已有计算结果，重新显示
        if hasattr(self, 'original_results') and self.original_results:
            self.display_results(self.original_results)
            
        
    def correct_all_pipe_diameters(self):
        """全管网校正管径（流速过高）"""
        self._adjust_all_pipe_diameters(high=True)

    def optimize_all_pipe_diameters(self):
        """全管网优化管径（流速过低）"""
        self._adjust_all_pipe_diameters(high=False)

    def _adjust_all_pipe_diameters(self, high: bool):
        if not hasattr(self, 'original_results'):
            messagebox.showwarning("无计算结果", "请先进行计算")
            return

        config = self.config_manager.get_live_config()
        raw_system_type = config.get("system_type", "outdoor_hydrant")
        # 映射到 material_manager 可识别的类型（用于管径列表）
        if raw_system_type == "indoor_hydrant":
            dia_system_type = "hydrant"
        elif raw_system_type == "sprinkler":
            dia_system_type = "sprinkler"
        else:
            dia_system_type = "hydrant"  # 室外消火栓默认按室内消火栓处理（但实际不应调用此方法）
        max_v = config.get("max_velocity", 5.0)
        min_v = config.get("min_velocity", 1.0)

        pipe_results = self.original_results.get("pipe_results", [])
        modified = False
        for pipe_res in pipe_results:
            pipe_id = pipe_res.get("pipe_id", "")
            if not pipe_id.startswith("P_"):
                continue
            velocity = pipe_res.get("velocity_mps", 0.0)
            if (high and velocity > max_v) or (not high and velocity < min_v):
                pipe = self.cad_data_manager.pipe_by_id.get(pipe_id)
                if not pipe:
                    continue
                # 跳过支管（消火栓模式下）
                if pipe.pipe_type == "支管":
                    continue
                current_dn = pipe.nominal_diameter
                direction = "up" if high else "down"
                # 使用管道自身的管材
                material = pipe.material
                new_dn = self.material_manager.get_next_diameter(
                    current_dn, direction, material, dia_system_type
                )
                if new_dn != current_dn:
                    new_info = self.material_manager.get_diameter_info(material, new_dn)
                    pipe.nominal_diameter = new_dn
                    pipe.inner_diameter = new_info.get("inner", 0.0)
                    modified = True

        if modified:
            # 更新管道类型
            self.cad_data_manager.update_pipe_types(config)
            # 刷新各页面
            root = self.winfo_toplevel()
            if hasattr(root, 'main_app'):
                root.main_app.refresh_all_pages()
            self.show_temp_message("管径已调整，请重新计算", 2000)
        else:
            self.show_temp_message("没有需要调整的管道", 2000)

    def reset_state(self):
        """重置计算页面状态（清除计算结果和缓存）"""
        self.original_results = None
        self.pipe_display_data = []
        self.all_paths_for_preview = []
        self.node_total_loss = {}
        # 清空表格
        for tree in [self.paths_tree, self.nodes_tree, self.pipes_tree]:
            for item in tree.get_children():
                tree.delete(item)
        # 重置按钮状态
        self.calculate_btn.config(state="disabled" if not self.cad_data_manager.is_loaded else "normal")
        self.export_btn.config(state="disabled")
        self.progress_bar["value"] = 0
        self.status_label.config(text="就绪")

    def get_state_for_export(self) -> dict:
        """返回计算结果状态，供导出使用。"""
        if not hasattr(self, "original_results") or self.original_results is None:
            return None
        return {
            "original_results": self.original_results,
            "pipe_display_data": getattr(self, "pipe_display_data", []),
            "all_paths_for_preview": getattr(self, "all_paths_for_preview", []),
            "node_total_loss": getattr(self, "node_total_loss", {}),
            "show_flow_in_m3h": self.show_flow_in_m3h,
            "show_pressure_in_mpa": self.show_pressure_in_mpa,
            "show_zero_flow_var": self.show_zero_flow_var.get(),
        }

    def restore_imported_state(self, data: dict):
        """从导入数据恢复计算结果和显示状态。"""
        if data is None:
            return
        self.original_results = data.get("original_results")
        self.pipe_display_data = data.get("pipe_display_data", [])
        self.all_paths_for_preview = data.get("all_paths_for_preview", [])
        self.node_total_loss = data.get("node_total_loss", {})
        self.show_flow_in_m3h = data.get("show_flow_in_m3h", False)
        self.show_pressure_in_mpa = data.get("show_pressure_in_mpa", False)

        # 更新复选框
        self.flow_unit_var.set(self.show_flow_in_m3h)
        self.pressure_unit_var.set(self.show_pressure_in_mpa)
        self.show_zero_flow_var.set(data.get("show_zero_flow_var", False))

        # 渲染结果
        if self.original_results:
            self.display_results(self.original_results)
            self.calculate_btn.config(state="normal")
            self.export_btn.config(state="normal")

       