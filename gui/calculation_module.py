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
from typing import Dict

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

        # 当量长度分配明细按钮（仅当量长度法计算后可用）
        self.equiv_detail_btn = ttk.Button(
            buttons_frame,
            text="当量明细",
            command=self.show_equiv_detail_dialog,
            state="disabled",
            width=9
        )
        self.equiv_detail_btn.pack(side="left", padx=(3, 0))

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

        # 内径减1mm计算（仅影响计算输入，不改动管道数据）
        self.inner_minus1_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            unit_frame,
            text="内径减1mm计算",
            variable=self.inner_minus1_var
        ).pack(side="left", padx=(10, 0))

        # 右侧状态文字区域（显示计算进程步骤）
        # 参与弹性伸展，长提示（如"第N轮平差｜第K轮：迭代 x/y..."）不被裁剪
        progress_frame = ttk.Frame(control_container)
        progress_frame.pack(side="left", fill="x", expand=True)

        self.status_label = ttk.Label(progress_frame, text="就绪", width=45, anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)

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
        self.paths_tree.heading("path_id", text="路径ID", command=lambda: self.sort_paths_tree("path_id"))
        self.paths_tree.heading("total_loss", text=f"总水损({pressure_unit})", command=lambda: self.sort_paths_tree("total_loss"))
        self.paths_tree.heading("nodes_path", text="节点路径", command=self.toggle_path_display)

        # 路径表排序状态：缺省按总水损从大到小（降序）
        self.paths_sort_column = "total_loss"
        self.paths_sort_reverse = True

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
        if getattr(self, 'original_results', None) is not None:
            node_results = self.original_results.get("node_results", [])
            self.update_nodes_table(node_results)
            pipe_results = self.original_results.get("pipe_results", [])
            self.update_pipes_table(pipe_results)

    def sort_paths_tree(self, col):
        """路径表排序：新列首次点击时总水损降序、路径ID升序；再次点击同列翻转方向"""
        if self.paths_sort_column == col:
            self.paths_sort_reverse = not self.paths_sort_reverse
        else:
            self.paths_sort_column = col
            self.paths_sort_reverse = (col == "total_loss")  # 总水损首次降序，路径ID首次升序
        self._refresh_paths_table()

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
        """根据当前显示模式重新填充路径表格（按当前排序状态排列）"""
        # 清空表格
        for item in self.paths_tree.get_children():
            self.paths_tree.delete(item)
        
        # 按当前排序状态排列（总水损按数值、路径ID按字符串，均等宽格式可字典序）
        sorted_paths = list(self.all_paths_for_preview)
        if self.paths_sort_column == "total_loss":
            sorted_paths.sort(key=lambda p: p["total_loss"], reverse=self.paths_sort_reverse)
        else:
            sorted_paths.sort(key=lambda p: str(p["id"]), reverse=self.paths_sort_reverse)
        
        path_row = 0
        for path_data in sorted_paths:
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
        columns = ("pipe_id", "node1", "node1_pressure", "node2", "node2_pressure",
                   "nominal_diameter", "inner_diameter", "length", "calc_length",
                   "material", "flow", "velocity", "unit_headloss", "loss",
                   "static_equiv",
                   "eq_45elbow", "eq_90elbow", "eq_reducer", "eq_valve",
                   "dynamic_equiv",
                   "eq_tees", "eq_teeside", "eq_cross_s", "eq_cross_side", "eq_cross_mix")
        
        self.pipes_tree = ttk.Treeview(parent, columns=columns, show="headings", height=12)
        
        # 设置列标题（占位，具体单位在update_table_headers中设置）
        column_headers = {
            "pipe_id": "管道ID",
            "node1": "起点",
            "node1_pressure": "起点压力",
            "node2": "终点", 
            "node2_pressure": "终点压力",
            "nominal_diameter": "公称管径",
            "inner_diameter": "计算内径(mm)",
            "length": "管长(m)",
            "calc_length": "计算长度",
            "material": "管材",
            "flow": "流量",
            "velocity": "流速(m/s)",
            "unit_headloss": "单位水损",
            "loss": "水损",
            "static_equiv": "静态当量(m)",
            "eq_45elbow": "45弯头(m)",
            "eq_90elbow": "90弯头(m)",
            "eq_reducer": "异径(m)",
            "eq_valve": "蝶阀(m)",
            "dynamic_equiv": "动态当量(m)",
            "eq_tees": "三通直通(m)",
            "eq_teeside": "三通侧通(m)",
            "eq_cross_s": "四通直通(m)",
            "eq_cross_side": "四通侧通(m)",
            "eq_cross_mix": "四通混合(m)"
        }
        
        for col, header in column_headers.items():
            self.pipes_tree.heading(col, text=header, command=lambda c=col: self.sort_pipes_tree(c))
        
        # 设置列宽度（不变）
        column_widths = {
            "pipe_id": 60,
            "node1": 60,
            "node1_pressure": 80,
            "node2": 60,
            "node2_pressure": 80,
            "nominal_diameter": 80,
            "inner_diameter": 80,
            "length": 70,
            "calc_length": 80,
            "material": 80,
            "flow": 70,
            "velocity": 70,
            "unit_headloss": 100,
            "loss": 100,
            "static_equiv": 88,
            "eq_45elbow": 70,
            "eq_90elbow": 70,
            "eq_reducer": 70,
            "eq_valve": 70,
            "dynamic_equiv": 88,
            "eq_tees": 80,
            "eq_teeside": 80,
            "eq_cross_s": 80,
            "eq_cross_side": 80,
            "eq_cross_mix": 80
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
        if getattr(self, 'original_results', None) is not None:
            node_results = self.original_results.get("node_results", [])
            self.update_nodes_table(node_results)

    def show_pipes_context_menu(self, event):
        """显示管道表格的右键菜单"""
        pipes_context_menu = tk.Menu(self, tearoff=0)
        pipes_context_menu.add_command(label="跳转至整体预览", command=self.jump_to_pipe_global)
        pipes_context_menu.add_command(label="跳转至楼层预览", command=self.jump_to_pipe_floor)
        pipes_context_menu.add_command(label="跳转至拼接预览", command=self.jump_to_pipe_spliced)
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

    def on_units_changed(self):
        self.on_unit_check_changed()

    def update_pipes_table(self, pipe_results: list):
        self.pipe_results_data = pipe_results.copy()
        for item in self.pipes_tree.get_children():
            self.pipes_tree.delete(item)
        
        flow_factor = 3.6 if self.show_flow_in_m3h else 1.0
        pressure_factor = 0.00980665 if self.show_pressure_in_mpa else 1.0
        self.update_table_headers()

        # 节点压力映射（node_id -> 压力m），用于起点/终点压力列
        node_pressure_map = {}
        if getattr(self, 'original_results', None):
            for node_res in self.original_results.get("node_results", []):
                nid = node_res.get("node_id")
                if nid:
                    node_pressure_map[nid] = node_res.get("pressure_m", 0.0)
        
        # 收集所有管道数据用于排序
        pipe_display_data = []
        for pipe in pipe_results:
            pipe_id = pipe.get("pipe_id", "")
            pid_upper = pipe_id.upper()
            if (pid_upper.startswith(("VP_", "VD_")) or pid_upper == "RESERVOIR"):
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
                # 计算内径 = 原内径 + 修正量（勾选"内径减1mm计算"时为 -1.0）
                inner_diameter = pipe_data.inner_diameter + self._get_inner_diameter_offset()
                nominal_diameter = pipe_data.nominal_diameter
                length = pipe_data.length
                material = pipe_data.material
            else:
                inner_diameter = pipe.get("inner_diameter", 0.0) + self._get_inner_diameter_offset()
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

            # 计算长度：当量长度法结果含 calc_length；否则局部水损系数法 = 几何长度×(1+系数)
            config = self.config_manager.get_live_config()
            calc_length = pipe.get("calc_length", 0.0) or 0.0
            if calc_length <= 0.0:
                # 局部水损系数法：按管网类型取对应系数
                system_type = config.get("system_type", "indoor_hydrant")
                if system_type == "sprinkler":
                    ratio = config.get("local_loss_ratio_sprinkler",
                                       config.get("local_loss_method_ratio", 0.5))
                else:
                    ratio = config.get("local_loss_ratio_hydrant",
                                       config.get("local_loss_method_ratio", 0.3))
                calc_length = length * (1 + ratio)

            # 水损 = 单位水损 × 计算长度（当量长度法用引擎结果，局部水损系数法用放大后长度）
            loss = unit_loss * calc_length
            # 用于显示的单位水损（可保留为 unit_loss，也可用 headloss_per_km/1000）
            unit_headloss = unit_loss
            
            flow_display = abs(flow) * flow_factor
            loss_display = loss * pressure_factor
            unit_headloss_display = unit_headloss * pressure_factor

            # 当量长度分配数据（仅当量长度法计算后存在，否则为 None 显示 "—"）
            static_equiv = getattr(pipe_data, 'static_equiv', None) if pipe_data else None
            dynamic_equiv = getattr(pipe_data, 'dynamic_equiv', None) if pipe_data else None
            
            # 当量来源明细 {显示名: 长度m}，供静态/动态明细列拆分显示
            equiv_detail_map = {}
            if pipe_data:
                detail = getattr(pipe_data, 'equiv_detail', None)
                if detail:
                    for name, val in detail:
                        equiv_detail_map[name] = val

            # 起点/终点压力（原始m，显示时乘 pressure_factor）
            node1 = pipe.get("node1", "")
            node2 = pipe.get("node2", "")
            node1_pressure = node_pressure_map.get(node1, None)
            node2_pressure = node_pressure_map.get(node2, None)
            
            # 存储显示值和排序用的数值
            pipe_display_data.append({
                "pipe_id": pipe_id,
                "node1": node1,
                "node1_pressure": node1_pressure,
                "node2": node2,
                "node2_pressure": node2_pressure,
                "nominal_diameter": nominal_diameter,
                "inner_diameter": inner_diameter,
                "length": length,
                "calc_length": calc_length,
                "material": material,
                "flow": flow_display,
                "velocity": velocity,
                "unit_headloss": unit_headloss_display,
                "loss": loss_display,
                "static_equiv": static_equiv,
                "dynamic_equiv": dynamic_equiv,
                "eq_45elbow": equiv_detail_map.get("45弯头"),
                "eq_90elbow": equiv_detail_map.get("90弯头"),
                "eq_reducer": equiv_detail_map.get("异径"),
                "eq_valve": equiv_detail_map.get("蝶阀"),
                "eq_tees": equiv_detail_map.get("三通直通"),
                "eq_teeside": equiv_detail_map.get("三通侧通"),
                "eq_cross_s": equiv_detail_map.get("四通直通"),
                "eq_cross_side": equiv_detail_map.get("四通侧通"),
                "eq_cross_mix": equiv_detail_map.get("四通混合"),
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
        elif col in ("node1_pressure", "node2_pressure", "calc_length",
                     "static_equiv", "dynamic_equiv",
                     "eq_45elbow", "eq_90elbow", "eq_reducer", "eq_valve",
                     "eq_tees", "eq_teeside", "eq_cross_s", "eq_cross_side", "eq_cross_mix"):
            pipe_display_data.sort(key=lambda x: x[col] if x[col] is not None else -1e18,
                                   reverse=reverse)
        else:
            # 默认按管道ID排序
            pipe_display_data.sort(key=lambda x: x["pipe_id"], reverse=reverse)
        
        # 插入数据
        row_number = 0
        
        # 保存计算后的管道数据，供预览页面使用
        self.pipe_display_data = pipe_display_data

        config = self.config_manager.get_live_config()
        max_v = config.get("max_velocity", 5.0)
        min_v = config.get("min_velocity", 2.0)

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
                f"{pipe['node1_pressure'] * pressure_factor:.2f}" if pipe['node1_pressure'] is not None else "—",
                pipe["node2"],
                f"{pipe['node2_pressure'] * pressure_factor:.2f}" if pipe['node2_pressure'] is not None else "—",
                pipe["nominal_diameter"],
                f"{pipe['inner_diameter']:.1f}" if pipe['inner_diameter'] else "0.0",
                f"{pipe['length']:.2f}" if pipe['length'] else "0.00",
                f"{pipe['calc_length']:.2f}" if pipe['calc_length'] else "0.00",
                pipe["material"],
                f"{pipe['flow']:.3f}",
                f"{pipe['velocity']:.3f}" if pipe['velocity'] else "0.00",
                f"{pipe['unit_headloss']:.6f}",
                f"{pipe['loss']:.4f}",
                f"{pipe['static_equiv']:.3f}" if pipe['static_equiv'] is not None else "—",
                f"{pipe['eq_45elbow']:.3f}" if pipe['eq_45elbow'] is not None else "—",
                f"{pipe['eq_90elbow']:.3f}" if pipe['eq_90elbow'] is not None else "—",
                f"{pipe['eq_reducer']:.3f}" if pipe['eq_reducer'] is not None else "—",
                f"{pipe['eq_valve']:.3f}" if pipe['eq_valve'] is not None else "—",
                f"{pipe['dynamic_equiv']:.3f}" if pipe['dynamic_equiv'] is not None else "—",
                f"{pipe['eq_tees']:.3f}" if pipe['eq_tees'] is not None else "—",
                f"{pipe['eq_teeside']:.3f}" if pipe['eq_teeside'] is not None else "—",
                f"{pipe['eq_cross_s']:.3f}" if pipe['eq_cross_s'] is not None else "—",
                f"{pipe['eq_cross_side']:.3f}" if pipe['eq_cross_side'] is not None else "—",
                f"{pipe['eq_cross_mix']:.3f}" if pipe['eq_cross_mix'] is not None else "—"
            ))
            base_tag = "evenrow" if row_number % 2 == 0 else "oddrow"
            all_tags = (base_tag,) + tuple(tags) if tags else (base_tag,)
            self.pipes_tree.item(item_id, tags=all_tags)
            row_number += 1
        


    def setup_bindings(self):
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="跳转至整体预览", command=self.jump_to_node_global)
        self.context_menu.add_command(label="跳转至楼层预览", command=self.jump_to_node_floor)
        self.context_menu.add_command(label="跳转至拼接预览", command=self.jump_to_node_spliced)
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
        success, message, demand_models = self.inp_generator.generate_inp_file(
            self.cad_data_manager,
            project_dir,
            demand_groups,
            inner_diameter_offset=self._get_inner_diameter_offset()
        )
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

        # 模式A：消火栓管网（无喷头，读取CAD时自动判定为 indoor_hydrant）可用
        if mode == 'A':
            if system_type == "sprinkler":
                messagebox.showwarning("不匹配", "模式A（有总流量）仅支持消火栓管网，喷淋管网请使用模式B/C")
                return
            self.run_mode_A(system_type)
        elif mode in ('B', 'C'):
            if system_type not in ("indoor_hydrant", "sprinkler"):
                messagebox.showwarning("不匹配", "模式B/C（压力驱动）仅支持室内消火栓或喷淋，请在设置页面选择对应类型")
                return
            # B/C模式弹出计算方法选择菜单：局部水损系数法 / 当量长度法
            self._show_method_menu(mode, system_type)
        else:
            pass

    def _show_method_menu(self, mode, system_type):
        """在计算按钮处弹出计算方法选择菜单"""
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="局部水损系数法",
                         command=lambda: self._on_method_selected(mode, system_type, "ratio"))
        menu.add_command(label="当量长度法",
                         command=lambda: self._on_method_selected(mode, system_type, "equiv"))
        # 支状喷淋倒推法：仅喷淋管网，且需存在设置了最低水压的勾选用水点组
        has_min_pressure = any(
            g.is_selected and g.min_pressure > 0
            for g in self.cad_data_manager.demand_groups.values())
        if system_type == "sprinkler" and has_min_pressure:
            menu.add_command(label="支状喷淋倒推法",
                             command=lambda: self._on_method_selected(mode, system_type, "tz"))
        try:
            x = self.calculate_btn.winfo_rootx()
            y = self.calculate_btn.winfo_rooty() + self.calculate_btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _on_method_selected(self, mode, system_type, method):
        """用户从菜单中选择计算方法后，立即按对应方法计算"""
        if method == "equiv":
            self.run_equiv_length(mode, system_type)
        elif method == "tz":
            self.run_tianzheng(mode, system_type)
        else:
            self.run_pressure_driven(mode, system_type)

    def run_mode_A(self, system_type):
        """模式A：室外消防，使用虚拟节点"""
        # 与B/C模式一致：先确定项目目录并记录当前CAD文件，
        # 否则切换页面触发 refresh_data 时 current_cad_file 为空，会误清空计算结果表
        self.get_current_project_dir()
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
            calc_type=system_type,       # 传入系统类型（可能用于将来扩展）
            inner_diameter_offset=self._get_inner_diameter_offset()
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
        # 当量长度法：引擎 _notify 已向状态栏推送"第N轮平差"提示，
        # 此处不再覆盖，避免轮次提示被"正在计算模型..."冲掉。
        if not getattr(self, '_engine_progress_msg', False):
            self.status_label.config(text=status["status"])
        if status["is_running"]:
            self.after(500, self.monitor_calculation_progress)

    def run_pressure_driven(self, mode, system_type):
        """启动压力驱动计算线程（局部水损系数法）"""
        self.get_current_project_dir()
        # 获取计算参数
        K, Ad, Ld, B, Hak, calc_type, k_value_map, tolerance = self._prepare_solver_params(system_type)

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
            progress_callback=self._update_solver_progress,
            pressure_tolerance=tolerance,
            inner_diameter_offset=self._get_inner_diameter_offset(),
        )
        solver.k_value_map = k_value_map

        def thread_func():
            success, results, message = solver.solve()
            self.after(0, self._on_pressure_driven_finished, success, results, message)

        self.is_calculating = True
        self.calculate_btn.config(state="disabled")
        self.export_btn.config(state="disabled")
        self.calculation_thread = threading.Thread(target=thread_func, daemon=True)
        self.calculation_thread.start()
        self._engine_progress_msg = False
        self._engine_round_msg = None
        self.monitor_calculation_progress()

    def _get_inner_diameter_offset(self) -> float:
        """内径修正量（mm）：勾选"内径减1mm计算"时返回 -1.0，否则 0.0。

        显示层（管道结果表"计算内径"列）与计算层共用同一来源，保证一致。
        """
        return -1.0 if getattr(self, 'inner_minus1_var', None) and self.inner_minus1_var.get() else 0.0

    def _prepare_solver_params(self, system_type):
        """准备压力驱动求解器公共参数（局部水损系数法与当量长度法共用）"""
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

        # 构建 per-node K 值映射
        # sprinkler_k_map 的键是喷头短管起点节点（base，如 N_0584，不带 _S），
        # 而用水点节点是喷头短管末端（N_0584_S），计算时按用水点节点 ID 查 K，
        # 因此这里将 base 与 _S 双向映射，保证预览页修改的 K 值真正生效。
        k_value_map: Dict[str, float] = {}
        default_K = float(K)
        for node_id, k_val in self.cad_data_manager.sprinkler_k_map.items():
            k_value_map.setdefault(node_id, k_val)
            if node_id.endswith("_S"):
                k_value_map.setdefault(node_id[:-2], k_val)
            else:
                k_value_map.setdefault(node_id + "_S", k_val)
        for group in self.cad_data_manager.demand_groups.values():
            for demand_node in group.demand_nodes:
                nid = demand_node.node_id
                if nid not in k_value_map:
                    base_id = nid[:-2] if nid.endswith("_S") else nid
                    k_value_map[nid] = k_value_map.get(base_id, default_K)

        # 模式C主判据：最不利用水点超压≤该值即终止本轮二分（用户可配置，缺省0.1m）
        tolerance = float(config.get("pressure_tolerance", 0.1))
        return K, Ad, Ld, B, Hak, calc_type, k_value_map, tolerance

    def run_equiv_length(self, mode, system_type):
        """启动当量长度法计算线程（B/C模式）"""
        self.get_current_project_dir()
        K, Ad, Ld, B, Hak, calc_type, k_value_map, tolerance = self._prepare_solver_params(system_type)

        # 导入当量长度法引擎
        from core.equiv_length_engine import EquivLengthEngine

        engine = EquivLengthEngine(
            cad_data_manager=self.cad_data_manager,
            config_manager=self.config_manager,
            calc_type=calc_type,
            mode=mode,
            sprinkler_K=K,
            hydrant_Ad=Ad,
            hydrant_Ld=Ld,
            hydrant_B=B,
            hydrant_Hak=Hak,
            k_value_map=k_value_map,
            progress_callback=self._update_solver_progress,
            pressure_tolerance=tolerance,
            inner_diameter_offset=self._get_inner_diameter_offset(),
        )

        # 读取CAD时已缓存的自环管道列表（起点=终点），无需重新分析。
        # 提醒用户计算时会忽略，确认后继续
        self_loop_pipes = list(getattr(self.cad_data_manager, 'self_loop_pipes', []) or [])
        if self_loop_pipes:
            detail = "\n".join(
                f"管道{pid}（起点=终点，长度"
                f"{self.cad_data_manager.pipe_by_id[pid].length:.3f}m）"
                if pid in self.cad_data_manager.pipe_by_id else f"管道{pid}"
                for pid in self_loop_pipes
            )
            proceed = messagebox.askyesno(
                "发现自环管道",
                f"以下自环管道（起点=终点）在计算中将被自动忽略，不参与水力计算：\n\n"
                f"{detail}\n\n是否继续计算？\n"
                f"（建议在CAD中删除这些管道后重新读取）",
                icon="warning")
            if not proceed:
                logger.info("当量长度法：用户取消计算（自环管道警告）")
                return

        def thread_func():
            success, results, message = engine.solve()
            self.after(0, self._on_equiv_length_finished, success, results, message, engine)

        self.is_calculating = True
        self.calculate_btn.config(state="disabled")
        self.export_btn.config(state="disabled")
        self.calculation_thread = threading.Thread(target=thread_func, daemon=True)
        self.calculation_thread.start()
        self._engine_progress_msg = True   # 当量长度法：状态栏由引擎"第N轮平差"提示驱动
        self._engine_round_msg = None      # "第N轮平差"常驻前缀（solver 二分提示拼在其右侧）
        self.monitor_calculation_progress()

    def run_tianzheng(self, mode, system_type):
        """启动支状喷淋倒推法计算线程（独立逐段计算，不使用 WNTR）"""
        self.get_current_project_dir()
        config = self.config_manager.get_live_config()
        tz_ratio = float(config.get("tz_ratio_sprinkler", 0.015))
        # 复用公共参数准备：K 值、per-node K 映射
        K, Ad, Ld, B, Hak, calc_type, k_value_map, tolerance = self._prepare_solver_params(system_type)

        # 勾选的用水点节点（跳过状态为"关"的用水点，如位于检修管道上的用水点）
        selected_node_ids = set()
        for group in self.cad_data_manager.demand_groups.values():
            if not group.is_selected:
                continue
            for demand_node in group.demand_nodes:
                if demand_node.status == "关":
                    logger.info(f"用水点 {demand_node.node_id} 状态为关，跳过（不参与计算）")
                    continue
                node = self.cad_data_manager.node_by_id.get(demand_node.node_id)
                if node and node.is_active:
                    selected_node_ids.add(demand_node.node_id)
        if not selected_node_ids:
            messagebox.showwarning("缺少输入", "没有可用的勾选喷头节点，请先勾选用水点组")
            return
        # 目标压力 = 勾选组最低工作压力最大值
        targets = [g.min_pressure for g in self.cad_data_manager.demand_groups.values()
                   if g.is_selected and g.min_pressure > 0]
        if not targets:
            messagebox.showwarning("缺少输入", "支状喷淋倒推法需要至少一个勾选用水点组设置了最低工作压力")
            return
        target_min_pressure = max(targets)

        from core.tianzheng_tree_solver import TianzhengTreeSolver
        solver = TianzhengTreeSolver(
            cad_data_manager=self.cad_data_manager,
            sprinkler_K=K,
            target_min_pressure=target_min_pressure,
            selected_node_ids=selected_node_ids,
            k_value_map=k_value_map,
            tz_ratio=tz_ratio,
            progress_callback=self._update_solver_progress,
            inner_diameter_offset=self._get_inner_diameter_offset(),
        )

        def thread_func():
            success, results, message = solver.solve()
            self.after(0, self._on_tianzheng_finished, success, results, message, solver)

        self.is_calculating = True
        self.calculate_btn.config(state="disabled")
        self.export_btn.config(state="disabled")
        self.calculation_thread = threading.Thread(target=thread_func, daemon=True)
        self.calculation_thread.start()
        self._engine_progress_msg = True   # 状态栏由求解器"支状喷淋倒推法：第N轮"提示驱动
        self._engine_round_msg = None
        self.monitor_calculation_progress()

    def _on_tianzheng_finished(self, success, results, message, solver=None):
        """支状喷淋倒推法计算完成回调"""
        self.is_calculating = False
        self.calculate_btn.config(state="normal")
        self.export_btn.config(state="normal")
        if success:
            # 保留求解器的管件分析与当量分配数据，供明细对话框/表格/预览着色使用
            self.equiv_analysis = solver.analysis if solver else None
            self.equiv_l_current = dict(solver.l_current) if solver else {}
            self.equiv_kinds = dict(solver.kinds) if solver else {}
            self.equiv_coeff = float(solver.tz_ratio) if solver else 0.0
            self._attach_pipe_equiv()
            if hasattr(self, 'equiv_detail_btn'):
                self.equiv_detail_btn.config(state="normal")
            self.original_results = results.copy()
            self.display_results(results)
            self.status_label.config(text="计算完成")
            self._save_results_to_project(results)
            self.show_temp_message("计算成功")
            logger.info(f"支状喷淋倒推法计算成功: {message}")
        else:
            self._clear_equiv_data()
            self.status_label.config(text="计算失败")
            messagebox.showerror("支状喷淋倒推法计算失败", message)
            logger.error(f"支状喷淋倒推法计算失败: {message}")

    def _on_equiv_length_finished(self, success, results, message, engine=None):
        """当量长度法计算完成回调"""
        self.is_calculating = False
        self.calculate_btn.config(state="normal")
        self.export_btn.config(state="normal")
        if success:
            # 保留引擎的管件分析与当量分配数据，供明细对话框/表格/预览着色使用
            self.equiv_analysis = engine.analysis if engine else None
            self.equiv_l_current = dict(engine.l_current) if engine else {}
            self.equiv_kinds = dict(getattr(engine, 'kinds', {}) or {}) if engine else {}
            self.equiv_coeff = float(getattr(engine, 'coeff', 0.0)) if engine else 0.0
            self._attach_pipe_equiv()
            if hasattr(self, 'equiv_detail_btn'):
                self.equiv_detail_btn.config(state="normal")
            self.original_results = results.copy()
            self.display_results(results)
            self.status_label.config(text="计算完成")
            self._save_results_to_project(results)
            self.show_temp_message("计算成功")
            logger.info(f"当量长度法计算成功: {message}")
        else:
            # 先读取是否已转换过（防止转换后仍失败时再次弹转换对话框），再清数据
            already_standardized = getattr(self, '_equiv_standardized', False)
            self._clear_equiv_data()
            self.status_label.config(text="计算失败")
            # 失败信息中包含缺失数据/画图错误详情（含节点、管道编号）
            # 画图错误时提供"转为标准管件计算"选项（仅当量长度法，且未转换过，避免循环弹窗）
            if "画图错误" in (message or "") and not already_standardized:
                self._show_error_standardize_dialog(message, engine)
            else:
                messagebox.showerror("当量长度法计算失败", message)
                logger.error(f"当量长度法计算失败: {message}")

    def _show_error_standardize_dialog(self, message: str, engine):
        """画图错误警示对话框：取消（原确定，作用=取消计算）/ 转为标准管件计算"""
        import tkinter as tk
        from tkinter import ttk, scrolledtext
        dialog = tk.Toplevel(self)
        dialog.title("当量长度法计算失败")
        dialog.transient(self.winfo_toplevel())
        dialog.resizable(True, True)
        dialog.minsize(600, 400)
        # 相对主窗口居中
        self.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - 680) // 2
        y = self.winfo_rooty() + (self.winfo_height() - 460) // 2
        dialog.geometry(f"680x460+{max(x, 0)}+{max(y, 0)}")
        dialog.grab_set()

        # 顶部：标题提示
        top = ttk.Frame(dialog, padding=(12, 10, 12, 0))
        top.pack(fill="x")
        ttk.Label(top, text="管网存在画图错误或不严谨，无法按当量长度法计算：",
                  foreground="red").pack(anchor="w")

        # 中部：错误信息（可滚动，完整显示所有错误节点）
        msg_frame = ttk.Frame(dialog, padding=12)
        msg_frame.pack(fill="both", expand=True)
        txt = scrolledtext.ScrolledText(
            msg_frame, wrap="word", height=8,
            font=("TkDefaultFont", 9), state="disabled")
        txt.pack(fill="both", expand=True)
        txt.configure(state="normal")
        txt.insert("1.0", message)
        txt.configure(state="disabled")

        # 转换规则说明
        tip = ("若选择「转为标准管件计算」：\n"
               "连接2根管道的节点按最近角度转为45°或90°弯头；\n"
               "连接3根管道的节点转为三通（最接近180°的两管按直通处理）；\n"
               "连接4根管道的节点转为四通（对向两管两两算作直通）；\n"
               "连接5根及以上管道的节点仍为错误，无法计算。")
        ttk.Label(msg_frame, text=tip, foreground="gray",
                  justify="left", wraplength=620).pack(anchor="w", pady=(8, 0))

        # 底部：按钮（固定可见）
        btn_frame = ttk.Frame(dialog, padding=(12, 0, 12, 12))
        btn_frame.pack(side="bottom", fill="x")
        ttk.Button(btn_frame, text="取消",
                   command=lambda: self._close_dialog_cancel(dialog)).pack(side="right", padx=(8, 0))
        ttk.Button(btn_frame, text="转为标准管件计算",
                   command=lambda: self._standardize_and_retry(dialog, engine)).pack(side="right")

    def _close_dialog_cancel(self, dialog):
        """取消按钮：关闭对话框，取消计算"""
        try:
            dialog.grab_release()
        except Exception:
            pass
        dialog.destroy()
        logger.info("当量长度法：用户选择取消计算（画图错误）")

    def _standardize_and_retry(self, dialog, engine):
        """转为标准管件计算：关闭对话框，以转换模式重新计算"""
        try:
            dialog.grab_release()
        except Exception:
            pass
        dialog.destroy()
        self._equiv_standardized = True   # 防止转换后仍失败时再次弹转换对话框
        self.status_label.config(text="正在转为标准管件计算...")
        # 复用引擎：传入第一次检测的分析结果（engine.analysis 已保存），
        # 转换只针对第一次检测发现的错误节点，不重复分析整个管网
        first_analysis = getattr(engine, 'analysis', None)
        def thread_func():
            success, results, message = engine.solve(
                standardize_errors=True, analysis=first_analysis)
            self.after(0, self._on_equiv_length_finished, success, results, message, engine)

        self.is_calculating = True
        self.calculate_btn.config(state="disabled")
        self.export_btn.config(state="disabled")
        self.calculation_thread = threading.Thread(target=thread_func, daemon=True)
        self.calculation_thread.start()
        self._engine_progress_msg = True
        self._engine_round_msg = None
        self.monitor_calculation_progress()

    def _attach_pipe_equiv(self):
        """把静态/动态当量汇总与来源明细挂到管道对象上，供预览着色与表格列展示使用"""
        if not getattr(self, 'equiv_analysis', None):
            return
        from core.equiv_length_engine import gather_pipe_equiv, build_pipe_equiv_detail
        if not self.cad_data_manager:
            return
        static, dynamic = gather_pipe_equiv(self.equiv_analysis, self.equiv_l_current)
        detail = build_pipe_equiv_detail(self.equiv_analysis, self.equiv_l_current,
                                         self.cad_data_manager, getattr(self, 'equiv_kinds', {}))
        for pipe in self.cad_data_manager.pipes:
            pipe.static_equiv = static.get(pipe.pipe_id, 0.0)
            pipe.dynamic_equiv = dynamic.get(pipe.pipe_id, 0.0)
            pipe.equiv_detail = detail.get(pipe.pipe_id, [])

    def _clear_equiv_data(self):
        """清空当量长度分配数据（非当量法计算 / 计算失败 / 重置时调用）"""
        self.equiv_analysis = None
        self.equiv_l_current = {}
        self.equiv_kinds = {}
        self._equiv_standardized = False
        self.equiv_coeff = 0.0
        if hasattr(self, 'equiv_detail_btn'):
            self.equiv_detail_btn.config(state="disabled")
        if self.cad_data_manager:
            for pipe in self.cad_data_manager.pipes:
                if hasattr(pipe, 'static_equiv'):
                    del pipe.static_equiv
                if hasattr(pipe, 'dynamic_equiv'):
                    del pipe.dynamic_equiv
                if hasattr(pipe, 'equiv_detail'):
                    del pipe.equiv_detail

    def show_equiv_detail_dialog(self):
        """弹出当量长度分配明细对话框（非模态）"""
        if not getattr(self, 'equiv_analysis', None):
            messagebox.showwarning("无当量数据", "请先使用「当量长度法」完成一次计算")
            return
        try:
            from gui.equiv_length_dialog import show_equiv_length_dialog
            show_equiv_length_dialog(self, self.equiv_analysis, self.equiv_l_current,
                                     self.cad_data_manager, self.equiv_kinds)
        except Exception as e:
            messagebox.showerror("打开失败", f"无法打开当量长度明细:\n{e}")
            logger.error(f"打开当量长度明细失败: {e}")

    def _update_solver_progress(self, progress, status):
        """更新进度文字（由求解器回调，显示计算步骤）"""
        if progress is None:
            # 引擎 _notify 的"第N轮平差"消息：作为常驻前缀保存
            self._engine_round_msg = status
        prefix = getattr(self, '_engine_round_msg', None)
        if prefix and progress is not None:
            self.status_label.config(text=f"{prefix}｜{status}")
        else:
            self.status_label.config(text=prefix if prefix else status)

    def _on_pressure_driven_finished(self, success, results, message):
        self.is_calculating = False
        self.calculate_btn.config(state="normal")
        self.export_btn.config(state="normal")
        if success:
            self._clear_equiv_data()   # 非当量长度法：清除上次当量分配数据
            self.original_results = results.copy()
            self.display_results(results)
            self.status_label.config(text="计算完成")
            self._save_results_to_project(results)
            self.show_temp_message("计算成功")
            logger.info(f"压力驱动计算成功: {message}")

        else:
            self.status_label.config(text="计算失败")
            messagebox.showerror("计算失败", message)
            logger.error(f"压力驱动计算失败: {message}")


    def on_calculation_success(self, results: dict):
        self.is_calculating = False
        self.calculate_btn.config(state="normal")
        self.export_btn.config(state="normal")
        self.status_label.config(text="计算完成")
        self._clear_equiv_data()   # 非当量长度法：清除上次当量分配数据
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
        if getattr(self, 'original_results', None) is not None:
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
                    "起点压力(m)": pipe["node1_pressure"] if pipe["node1_pressure"] is not None else "",
                    "终点": pipe["node2"],
                    "终点压力(m)": pipe["node2_pressure"] if pipe["node2_pressure"] is not None else "",
                    "公称管径": pipe["nominal_diameter"],
                    "内径(mm)": pipe["inner_diameter"],
                    "管长(m)": pipe["length"],
                    "计算长度(m)": pipe["calc_length"],
                    "管材": pipe["material"],
                    "流量(L/s)": pipe.get("raw_flow", 0.0),          # 原始流量，带符号
                    "流速(m/s)": pipe["velocity"],
                    "单位水损(m/m)": pipe["sort_unit_headloss"],
                    "水损(m)": pipe["sort_loss"],
                    "静态当量(m)": pipe["static_equiv"] if pipe["static_equiv"] is not None else "",
                    "45弯头(m)": pipe["eq_45elbow"] if pipe["eq_45elbow"] is not None else "",
                    "90弯头(m)": pipe["eq_90elbow"] if pipe["eq_90elbow"] is not None else "",
                    "异径(m)": pipe["eq_reducer"] if pipe["eq_reducer"] is not None else "",
                    "蝶阀(m)": pipe["eq_valve"] if pipe["eq_valve"] is not None else "",
                    "动态当量(m)": pipe["dynamic_equiv"] if pipe["dynamic_equiv"] is not None else "",
                    "三通直通(m)": pipe["eq_tees"] if pipe["eq_tees"] is not None else "",
                    "三通侧通(m)": pipe["eq_teeside"] if pipe["eq_teeside"] is not None else "",
                    "四通直通(m)": pipe["eq_cross_s"] if pipe["eq_cross_s"] is not None else "",
                    "四通侧通(m)": pipe["eq_cross_side"] if pipe["eq_cross_side"] is not None else "",
                    "四通混合(m)": pipe["eq_cross_mix"] if pipe["eq_cross_mix"] is not None else ""
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
        self.status_label.config(text="计算失败")
        messagebox.showerror("计算失败", error_msg)
        logger.error(f"计算失败: {error_msg}")

    def display_results(self, results: dict, skip_paths: bool = False):
        self.original_results = results.copy()
        node_results = results.get("node_results", [])
        self.update_nodes_table(node_results)
        pipe_results = results.get("pipe_results", [])
        self.update_pipes_table(pipe_results)
        if not skip_paths:
            self.find_and_display_all_paths(results)
        self.status_label.config(text="计算完成")

        pipe_dict = {}
        # ===== 修改：传递所有管道类型的计算结果（P_, R_, B_, L_） =====
        for pipe in self.pipe_display_data:
            pipe_id = pipe["pipe_id"]
            # 去掉过滤条件，所有管道都传递
            pipe_dict[pipe_id] = {
                "flow_lps": pipe.get("raw_flow", 0.0),   # 原始流量带符号
                "total_loss": pipe.get("sort_loss", 0.0),
                "velocity_mps": pipe.get("velocity", 0.0)  # 流速用于预览页面着色
            }
        root = self.winfo_toplevel()
        main_app = getattr(root, 'main_app', None)
        if main_app and hasattr(main_app, 'pages'):
            preview_page = main_app.pages.get("管网预览")
            if preview_page:
                preview_page.set_calculation_results(pipe_dict)
                logger.info(f"已传递 {len(pipe_dict)} 条管道计算结果到预览页面")
        # 传递节点压力 和 节点流量
        node_pressure_dict = {}
        node_flow_dict = {}
        for node_res in results.get("node_results", []):
            node_id = node_res["node_id"]
            if node_id.upper().startswith(("D_", "VD_", "RESERVOIR")):
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
            node_flow_dict[node_id] = node_res.get("demand_lps", 0.0)
        if main_app and hasattr(main_app, 'pages'):
            preview_page = main_app.pages.get("管网预览")
            if preview_page:
                preview_page.set_node_pressures(node_pressure_dict)
                preview_page.set_node_flows(node_flow_dict)
                logger.info(f"已传递 {len(node_pressure_dict)} 个节点压力和 {len(node_flow_dict)} 个节点流量到预览页面")                


    def update_nodes_table(self, node_results: list):
        for item in self.nodes_tree.get_children():
            self.nodes_tree.delete(item)

        pipe_results = self.original_results.get("pipe_results", [])
        real_pipes = [p for p in pipe_results if self.cad_data_manager.id_type(p.get("pipe_id", "")) == "P"]
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
        # 全部管道（含 VP_D 虚拟管道、B_ 支管）的进出流量：仅用于 A 模式（虚拟节点）用水点流量计算。
        # 普通节点与供水点仍使用上面的 P_ 管道统计，显示不受影响。
        all_outflow = {}
        all_inflow = {}
        for pipe in pipe_results:
            n1 = pipe.get("node1", "")
            n2 = pipe.get("node2", "")
            flow = pipe.get("flow_lps", 0.0)
            abs_flow = abs(flow)
            if flow > 0:
                all_outflow[n1] = all_outflow.get(n1, 0.0) + abs_flow
                all_inflow[n2] = all_inflow.get(n2, 0.0) + abs_flow
            elif flow < 0:
                all_outflow[n2] = all_outflow.get(n2, 0.0) + abs_flow
                all_inflow[n1] = all_inflow.get(n1, 0.0) + abs_flow

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
            if node_id.upper() == "RESERVOIR" or node_id.upper().startswith(("D_", "VD_")):
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
                # 用水点：B/C 模式 demand_lps 非0，需求即流量（原行为不变）；
                # A模式（虚拟节点）自身 demand=0，取连接管道（含 VP_D/B_）较大方向流量
                demand_lps = node.get("demand_lps", 0.0)
                if demand_lps > 0:
                    node_flow = demand_lps
                else:
                    node_flow = max(all_outflow.get(node_id, 0.0), all_inflow.get(node_id, 0.0))
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

        # 保存节点ID -> 结果（raw_flow L/s, raw_pressure m）映射，供供水点和用水点页面按节点ID直接显示
        self._node_result_map = {n["node_id"]: n for n in display_nodes}

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

        # 最低压力：优先标红用水点中压力最低的行（最不利用水点），无用水点时兜底全局最低
        water_nodes = [n for n in display_nodes if "用水点" in n["node_type"]]
        if water_nodes:
            min_raw_pressure = min(n["raw_pressure"] for n in water_nodes)
        else:
            min_raw_pressure = min(n["raw_pressure"] for n in display_nodes)

        row_number = 0
        for node in display_nodes:
            # 根据复选框决定是否跳过流量为零的节点
            # （用水点节点始终显示：A模式虚拟节点下需求在D_虚拟节点上，实际用水点节点自身demand为0）
            if not self.show_zero_flow_var.get():
                # 判断流量是否为零（用水点节点用 demand_lps，普通节点用 node_flow）
                flow_abs = abs(node.get("raw_flow", 0.0)) if "raw_flow" in node else 0.0
                if flow_abs < 0.001 and "用水点" not in node["node_type"]:
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
            pid_upper = pipe_id.upper()
            if (pid_upper.startswith(("VP_", "VD_")) or pid_upper == "RESERVOIR"):
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
        # 打印前10条管道的流量信息（调试用）
        for pipe in pipe_results[:10]:
            logger.debug(f"管道 {pipe['pipe_id']}: {pipe['node1']} -> {pipe['node2']}, flow={pipe['flow_lps']:.3f}")
        
        # 获取所有供水点节点
        supply_nodes = []
        if self.cad_data_manager and hasattr(self.cad_data_manager, 'supply_nodes'):
            for supply in self.cad_data_manager.supply_nodes:
                supply_nodes.extend(supply.node_ids)
        supply_nodes = list(set(supply_nodes))
        
        # 获取所有被勾选的用水点节点（跳过状态为"关"的用水点）
        demand_nodes = []
        if self.cad_data_manager and hasattr(self.cad_data_manager, 'demand_groups'):
            for group in self.cad_data_manager.demand_groups.values():
                if group.is_selected:
                    for demand_node in group.demand_nodes:
                        if demand_node.status == "关":
                            continue
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
                        pipe_length = pipe.get("calc_length", 0.0) or pipe.get("length", 0.0)
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
                            pipe_length = pipe.get("calc_length", 0.0) or pipe.get("length", 0.0)
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
        if getattr(self, 'original_results', None) is not None:
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
                if (next_node.upper().startswith(("RESERVOIR", "VD_", "D_"))):
                    continue
                if next_node not in visited:
                    visited.add(next_node)
                    path.append(next_node)
                    dfs(next_node, visited, path)
                    path.pop()
                    visited.remove(next_node)
        if (start.upper().startswith(("RESERVOIR", "VD_", "D_"))):
            return paths
        visited = {start}
        dfs(start, visited, [start])
        return paths

    def on_unit_check_changed(self):
        self.show_flow_in_m3h = self.flow_unit_var.get()
        self.show_pressure_in_mpa = self.pressure_unit_var.get()
        self.update_table_headers()
        if getattr(self, 'original_results', None) is not None:
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
            self.pipes_tree.heading("node1_pressure", text=f"起点压力({pressure_unit})")
            self.pipes_tree.heading("node2_pressure", text=f"终点压力({pressure_unit})")
            self.pipes_tree.heading("calc_length", text="计算长度(m)")
        if hasattr(self, 'paths_tree'):
            self.paths_tree.heading("total_loss", text=f"总水损({pressure_unit})")



    def export_results(self):
        if not hasattr(self, 'original_results'):
            messagebox.showwarning("无结果", "请先进行计算")
            return
        default_name = os.path.basename(self.current_project_dir) + "_results"
        file_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx"), ("JSON文件", "*.json"), ("所有文件", "*.*")],
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
                "压力单位": "MPa" if self.show_pressure_in_mpa else "m",
                "计算方法": "当量长度法" if getattr(self, 'equiv_analysis', None) else "压力驱动/局部水损系数法",
                "当量系数": self.equiv_coeff if getattr(self, 'equiv_analysis', None) else ""
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
            if values and len(values) >= 15:
                export_data["管道结果"].append({
                    "管道ID": values[0],
                    "起点": values[1],
                    "起点压力": values[2],
                    "终点": values[3],
                    "终点压力": values[4],
                    "公称管径": values[5],
                    "内径(mm)": values[6],
                    "管长(m)": values[7],
                    "计算长度(m)": values[8],
                    "管材": values[9],
                    "流量": values[10],
                    "流速(m/s)": values[11],
                    "单位水损(m/m)": values[12],
                    "水损(m)": values[13],
                    "静态当量(m)": values[14],
                    "45弯头(m)": values[15] if len(values) >= 16 else "",
                    "90弯头(m)": values[16] if len(values) >= 17 else "",
                    "异径(m)": values[17] if len(values) >= 18 else "",
                    "蝶阀(m)": values[18] if len(values) >= 19 else "",
                    "动态当量(m)": values[19] if len(values) >= 20 else "",
                    "三通直通(m)": values[20] if len(values) >= 21 else "",
                    "三通侧通(m)": values[21] if len(values) >= 22 else "",
                    "四通直通(m)": values[22] if len(values) >= 23 else "",
                    "四通侧通(m)": values[23] if len(values) >= 24 else "",
                    "四通混合(m)": values[24] if len(values) >= 25 else ""
                })
        for item in self.paths_tree.get_children():
            values = self.paths_tree.item(item, "values")
            if values and len(values) >= 3:
                export_data["路径结果"].append({
                    "路径ID": values[0],
                    "总水损(m)": values[1],
                    "节点路径": values[2]
                })
        # 当量长度法：附加分配明细与管道汇总两个区块
        equiv_detail, equiv_summary = self._build_equiv_export_blocks()
        if equiv_detail is not None:
            export_data["当量长度分配"] = equiv_detail
            export_data["管道当量汇总"] = equiv_summary

        # ===== 增加：管道/节点/阀门/供水点/用水点页面内容 =====
        # 管道与节点忽略无效项（is_active=False）
        if self.cad_data_manager is not None:
            export_data["管道数据"] = [
                {
                    "管道ID": p.pipe_id,
                    "起点": p.start_node_id,
                    "终点": p.end_node_id,
                    "管径": p.nominal_diameter,
                    "内径(mm)": p.inner_diameter,
                    "管长(m)": p.length,
                    "状态": p.status,
                    "类型": p.pipe_type,
                    "管材": p.material,
                }
                for p in self.cad_data_manager.pipes if p.is_active
            ]
            export_data["节点数据"] = [
                {
                    "节点ID": n.node_id,
                    "状态": n.status,
                    "X坐标": n.x,
                    "Y坐标": n.y,
                    "Z坐标": n.z,
                    "节点类型": n.node_type,
                    "连接管道": "、".join(n.connected_pipes or []),
                }
                for n in self.cad_data_manager.nodes if n.is_active
            ]
            export_data["阀门数据"] = [
                {
                    "阀门ID": v.valve_id,
                    "所在管道ID": v.pipe_id if v.pipe_id else "未匹配",
                    "状态": v.status,
                    "X坐标": v.x,
                    "Y坐标": v.y,
                    "Z坐标": v.z,
                }
                for v in self.cad_data_manager.valves
            ]
            # 供水点压力优先取计算结果（C模式后 supply_nodes[0].pressure 保持输入值0，
            # 计算结果中的供水点节点压力仍在 node_results 中，导出保留计算值）
            _supply_pressure_map = {}
            if getattr(self, 'original_results', None):
                for _nr in self.original_results.get("node_results", []):
                    _supply_pressure_map[_nr["node_id"]] = _nr.get("pressure_m", 0.0)
            export_data["供水点数据"] = [
                {
                    "组ID": s.group_id,
                    "节点列表": "、".join(s.node_ids),
                    "压力": (_supply_pressure_map.get(s.node_ids[0], s.pressure)
                             if s.node_ids else s.pressure),
                }
                for s in self.cad_data_manager.supply_nodes
            ]
            demand_rows = []
            for gid, group in self.cad_data_manager.demand_groups.items():
                base_info = {
                    "组ID": gid,
                    "参与计算": "是" if group.is_selected else "否",
                    "总流量": group.total_flow,
                    "最低水压": group.min_pressure,
                }
                if not group.demand_nodes:
                    demand_rows.append({**base_info, "节点ID": "", "状态": "",
                                        "流量": "", "压力": ""})
                for node in group.demand_nodes:
                    demand_rows.append({**base_info, "节点ID": node.node_id,
                                        "状态": node.status, "流量": node.flow,
                                        "压力": node.pressure})
            export_data["用水点数据"] = demand_rows
        return export_data

    def _build_equiv_export_blocks(self):
        """构造当量长度分配明细与管道汇总（无当量数据时返回 (None, None)）"""
        if not getattr(self, 'equiv_analysis', None):
            return None, None
        from core.equiv_length_engine import (
            collect_equiv_detail_rows, collect_equiv_summary_rows,
        )
        detail = collect_equiv_detail_rows(
            self.equiv_analysis, self.equiv_l_current, self.cad_data_manager,
            getattr(self, 'equiv_kinds', {}))
        summary = collect_equiv_summary_rows(
            self.cad_data_manager, self.equiv_analysis, self.equiv_l_current,
            float(getattr(self, 'equiv_coeff', 0.0) or 0.0))
        return detail, summary

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
                if data.get("当量长度分配"):
                    pd.DataFrame(data["当量长度分配"]).to_excel(
                        writer, sheet_name='当量长度分配', index=False)
                if data.get("管道当量汇总"):
                    pd.DataFrame(data["管道当量汇总"]).to_excel(
                        writer, sheet_name='管道当量汇总', index=False)
                # 管道/节点/阀门/供水点/用水点页面数据
                for key, sheet_name in (("管道数据", "管道数据"),
                                        ("节点数据", "节点数据"),
                                        ("阀门数据", "阀门数据"),
                                        ("供水点数据", "供水点数据"),
                                        ("用水点数据", "用水点数据")):
                    if data.get(key):
                        pd.DataFrame(data[key]).to_excel(
                            writer, sheet_name=sheet_name, index=False)
                df_settings = pd.DataFrame([data["计算设置"]])
                df_settings.to_excel(writer, sheet_name='计算设置', index=False)
        except ImportError:
            messagebox.showerror("导出失败", "导出Excel需要pandas库，请先安装：\npip install pandas openpyxl")

    def show_context_menu(self, event):
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

    def jump_to_node_global(self):
        selection = self.nodes_tree.selection()
        if not selection:
            return
        values = self.nodes_tree.item(selection[0], "values")
        if not values:
            return
        preview = self._switch_to_preview()
        if preview:
            preview.jump_to_node(values[0], to_global=True)

    def jump_to_node_floor(self):
        selection = self.nodes_tree.selection()
        if not selection:
            return
        values = self.nodes_tree.item(selection[0], "values")
        if not values:
            return
        preview = self._switch_to_preview()
        if preview:
            preview.jump_to_node(values[0], to_global=False)

    def jump_to_pipe_global(self):
        selection = self.pipes_tree.selection()
        if not selection:
            return
        values = self.pipes_tree.item(selection[0], "values")
        if not values:
            return
        preview = self._switch_to_preview()
        if preview:
            preview.jump_to_pipe(values[0], to_global=True)

    def jump_to_pipe_floor(self):
        selection = self.pipes_tree.selection()
        if not selection:
            return
        values = self.pipes_tree.item(selection[0], "values")
        if not values:
            return
        preview = self._switch_to_preview()
        if preview:
            preview.jump_to_pipe(values[0], to_global=False)

    def jump_to_node_spliced(self):
        selection = self.nodes_tree.selection()
        if not selection:
            return
        values = self.nodes_tree.item(selection[0], "values")
        if not values:
            return
        preview = self._switch_to_preview()
        if preview:
            preview.jump_to_spliced_view(entity_type="node", entity_id=values[0])

    def jump_to_pipe_spliced(self):
        selection = self.pipes_tree.selection()
        if not selection:
            return
        values = self.pipes_tree.item(selection[0], "values")
        if not values:
            return
        preview = self._switch_to_preview()
        if preview:
            preview.jump_to_spliced_view(entity_type="pipe", entity_id=values[0])

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
                # 旧CAD的计算结果与路径对当前数据无效：一并清除，
                # 并清空预览页路径列表，避免"路径表空而预览残留旧路径高亮"（区域模式读取新CAD时尤为明显）
                self.all_paths_for_preview = []
                self.node_total_loss = {}
                self.original_results = None
                root = self.winfo_toplevel()
                main_app = getattr(root, 'main_app', None)
                if main_app and hasattr(main_app, 'pages'):
                    preview_page = main_app.pages.get("管网预览")
                    if preview_page:
                        preview_page.set_path_list([])
        if self.cad_data_manager.is_loaded:
            self.calculate_btn.config(state="normal")
        self.update_table_headers()
        self.status_label.config(text="就绪")
        # 如果已有计算结果，重新显示（刷新场景跳过路径重算，避免导入后多次重复计算）
        if hasattr(self, 'original_results') and self.original_results:
            self.display_results(self.original_results, skip_paths=True)
            
        
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
        min_v = config.get("min_velocity", 2.0)

        pipe_results = self.original_results.get("pipe_results", [])
        modified = False
        for pipe_res in pipe_results:
            pipe_id = pipe_res.get("pipe_id", "")
            # 跳过消火栓支管（始终DN65）
            if self.cad_data_manager.id_type(pipe_id) == "B":
                continue
            # 只处理P_、SP_、R_、L_开头管道
            if not (self.cad_data_manager.id_type(pipe_id) == "P" or self.cad_data_manager.id_type(pipe_id) == "SP" or
                    self.cad_data_manager.id_type(pipe_id) == "R" or self.cad_data_manager.id_type(pipe_id) == "L"):
                continue
            velocity = pipe_res.get("velocity_mps", 0.0)
            if (high and velocity > max_v) or (not high and velocity < min_v):
                pipe = self.cad_data_manager.pipe_by_id.get(pipe_id)
                if not pipe:
                    continue
                current_dn = pipe.nominal_diameter
                direction = "up" if high else "down"
                material = pipe.material
                new_dn = self.material_manager.get_next_diameter(
                    current_dn, direction, material, dia_system_type
                )
                # 消火栓模式管径保护
                if raw_system_type in ("indoor_hydrant", "outdoor_hydrant"):
                    dn_num = 0
                    if current_dn.startswith("DN"):
                        try: dn_num = int(current_dn[2:])
                        except: pass
                    if dn_num == 65:
                        continue  # 所有DN65跳过
                    if self.cad_data_manager.id_type(pipe_id) == "R" or self.cad_data_manager.id_type(pipe_id) == "L":
                        if dn_num < 100:
                            continue  # R_/L_只处理DN100+
                        if not high:
                            try:
                                if new_dn.startswith("DN") and int(new_dn[2:]) < 100:
                                    continue  # 不下调到DN100以下
                            except:
                                pass
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
        # 初始化/清空当量长度分配数据（按钮可能尚未创建，_clear_equiv_data 内有保护）
        self.equiv_analysis = None
        self.equiv_l_current = {}
        self.equiv_coeff = 0.0
        self._clear_equiv_data()
        # 清空表格
        for tree in [self.paths_tree, self.nodes_tree, self.pipes_tree]:
            for item in tree.get_children():
                tree.delete(item)
        # 重置按钮状态
        self.calculate_btn.config(state="disabled" if not self.cad_data_manager.is_loaded else "normal")
        self.export_btn.config(state="disabled")
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

       