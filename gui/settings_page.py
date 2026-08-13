# pipe_loss_calculator/gui/settings_page.py
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from config.config_manager import ConfigManager
from config.material_manager import MaterialManager
from .layer_manager import MultiLayerManager
from .color_diameter_table_config import ColorDiameterTableConfig
import copy

class ToolTip:
    """简单的悬停提示类"""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        widget.bind('<Enter>', self.enter)
        widget.bind('<Leave>', self.leave)

    def enter(self, event=None):
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify='left',
                         background="#ffffe0", relief='solid', borderwidth=1,
                         font=("tahoma", "8", "normal"))
        label.pack()

    def leave(self, event=None):
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None

class SettingsPage(ttk.Frame):
    def __init__(self, parent, config_manager: ConfigManager, material_manager: MaterialManager, cad_data_manager=None):
        """初始化设置页面
        
        Args:
            parent: 父容器
            config_manager: 配置管理器
            material_manager: 管材管理器
            cad_data_manager: CAD数据管理器 (可选)
        """
        super().__init__(parent)
        self.config_manager = config_manager
        self.material_manager = material_manager
        self.cad_data_manager = cad_data_manager
        
        self.is_loading_cad = False
        self.loading_status_var = tk.StringVar(value="等待读取")
        self.region_mode_var = tk.BooleanVar(
            value=self.config_manager.get_global_setting("region_mode_enabled", False)
        )

        # 当前内存中的配置（不自动保存到方案）
        self.current_config = {}

        # 标高管材分段（内存持有，导出项目时同步导出；不写入通用json）
        self.elevation_materials = {
            "enabled": False,
            "segments": [
                {"material": "镀锌钢管", "lower": None, "upper": None},
                {"material": "加厚钢管", "lower": None, "upper": None},
                {"material": "无缝钢管", "lower": None, "upper": None},
            ],
            "outdoor_material": "K9球墨铸铁管",
        }
        
        # 创建滚动容器
        self.create_scrollable_container()
        
        # 加载当前方案配置到内存
        self.load_current_config()
        
        # 创建所有控件
        self.create_widgets()
        
        # 初始加载数据
        self.update_all_widgets()

        # ✅ 在所有控件创建完成后绑定滚轮事件
        self.bind_mouse_wheel()

    def load_current_config(self):
        """从当前方案加载配置到内存（使用深拷贝确保独立）"""
        scheme_config = self.config_manager.get_current_config()
        # 使用深拷贝确保每个方案的配置完全独立
        self.current_config = copy.deepcopy(scheme_config)
    
    def create_scrollable_container(self):
        """创建可滚动的容器"""
        # 创建画布和滚动条
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.v_scrollbar = tk.Scrollbar(
            self, 
            orient="vertical", 
            command=self.canvas.yview,
            width=10
        )
        
        # 配置画布
        self.canvas.configure(yscrollcommand=self.v_scrollbar.set)
        
        # 创建内部框架
        self.inner_frame = ttk.Frame(self.canvas)
        self.canvas_frame = self.canvas.create_window((0, 0), window=self.inner_frame, anchor="nw")
        
        # 布局
        self.v_scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        
        # 绑定事件
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.inner_frame.bind("<Configure>", self.on_frame_configure)
        
        # ✅ 注意：不在这里调用 bind_mouse_wheel()
        # 因为此时 inner_frame 还没有子控件

    def bind_mouse_wheel(self):
        """绑定鼠标滚轮事件"""
        def on_mouse_wheel(event):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
        # ✅ 绑定滚轮事件到self（整个页面框架）
        self.bind("<MouseWheel>", on_mouse_wheel)
        self.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))
        
        # ✅ 递归绑定所有子控件
        def bind_to_all_children(widget):
            widget.bind("<MouseWheel>", on_mouse_wheel)
            widget.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
            widget.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))
            for child in widget.winfo_children():
                bind_to_all_children(child)
        
        # 绑定到canvas和inner_frame的所有子控件
        bind_to_all_children(self.canvas)
        bind_to_all_children(self.inner_frame)

    def on_canvas_configure(self, event):
        """画布大小变化时调整内部框架宽度"""
        self.canvas.itemconfig(self.canvas_frame, width=event.width)
        self.update_scroll_region()
    
    def on_frame_configure(self, event=None):
        """内部框架大小变化时更新滚动区域"""
        self.update_scroll_region()
    
    def update_scroll_region(self):
        """更新滚动区域 - 修复空白问题"""
        self.inner_frame.update_idletasks()
        frame_width = self.inner_frame.winfo_reqwidth()
        frame_height = self.inner_frame.winfo_reqheight()
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        scroll_width = max(canvas_width, frame_width)
        scroll_height = max(canvas_height, frame_height)
        self.canvas.configure(scrollregion=(0, 0, scroll_width, scroll_height))
    
    def create_widgets(self):
        """创建所有控件"""
        # 创建左右分栏容器
        main_paned = ttk.PanedWindow(self.inner_frame, orient="horizontal")
        main_paned.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 左面板
        left_panel = ttk.Frame(main_paned)
        main_paned.add(left_panel, weight=3)
        
        # 右面板
        right_panel = ttk.Frame(main_paned)
        main_paned.add(right_panel, weight=2)
        
        # 创建左面板内容
        self.create_left_panel(left_panel)
        
        # 创建右面板内容
        self.create_right_panel(right_panel)
        
        # 添加一个空行来调整布局
        ttk.Label(self.inner_frame, text="").pack()
        
        # 强制设置初始分隔位置
        self.after(100, lambda: self.set_initial_paned_position(main_paned))
        
        # 启动时若上次为区域模式，更新状态提示
        if self.region_mode_var.get():
            self.loading_status_var.set("进入区域管网模式")
    
    def set_initial_paned_position(self, paned_window):
        """设置 PanedWindow 的初始分隔位置"""
        # 获取总宽度
        total_width = paned_window.winfo_width()
        
        # 如果总宽度为 0 或很小，说明窗口还未完全渲染，延迟重试
        if total_width <= 1:
            self.after(100, lambda: self.set_initial_paned_position(paned_window))
            return
        
        # 按照 3:2 的比例计算分隔位置（左侧占 3/5）
        sash_position = int(total_width * 3 / 5)
        
        # 设置分隔条位置
        paned_window.sashpos(0, sash_position)
    
    
    def create_left_panel(self, parent):
        """创建左面板内容"""
        # CAD文件设置区域
        cad_frame = ttk.LabelFrame(parent, text="CAD文件设置（需在autocad中同步打开需计算的cad文件）")
        cad_frame.pack(fill="x", padx=5, pady=(0, 10))
        
        # 第一行：路径输入和浏览按钮
        row1 = ttk.Frame(cad_frame)
        row1.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(row1, text="Cad路径:").pack(side="left", padx=(0, 5))
        
        self.cad_file_var = tk.StringVar(
            value=self.config_manager.get_global_setting("last_cad_file", "")
        )
        
        self.cad_entry = ttk.Entry(row1, textvariable=self.cad_file_var, width=35)
        self.cad_entry.pack(side="left", padx=5, expand=True, fill="x")
        
        ttk.Button(
            row1,
            text="浏览",
            command=self.browse_cad_file,
            width=8
        ).pack(side="left", padx=2)
        
        # 第二行：预处理复选框、读取按钮和状态显示
        row2 = ttk.Frame(cad_frame)
        row2.pack(fill="x", padx=10, pady=(0, 5))
        
        # DXF读取复选框（放在最左侧，缺省勾选）
        self.dxf_read_var = tk.BooleanVar(value=self.current_config.get("use_dxf_read", False))
        dxf_read_check = ttk.Checkbutton(
            row2,
            text="DXF读取",
            variable=self.dxf_read_var,
            command=lambda: self.on_config_change("use_dxf_read", self.dxf_read_var.get())
        )
        dxf_read_check.pack(side="left", padx=(0, 10))

        # 区域管网模式复选框
        self.region_mode_check = ttk.Checkbutton(
            row2,
            text="区域管网模式",
            variable=self.region_mode_var,
            command=self._on_region_mode_toggle
        )
        self.region_mode_check.pack(side="left", padx=(0, 10))
        
        # 读取按钮
        self.load_button = ttk.Button(
            row2,
            text="读取单体管网",
            command=self.load_cad_data,
            width=10
        )
        self.load_button.pack(side="left", padx=(0, 10))
        
        # 读取状态标签
        self.load_status_label = ttk.Label(
            row2,
            textvariable=self.loading_status_var,
            foreground="blue"
        )
        self.load_status_label.pack(side="left", padx=10)
        
        # 为读取按钮添加 tooltip
        ToolTip(self.load_button, "需要多端点多段线拆分和跨线分割时，勾选预处理框")
        
        # 第三行：管网类型选择（同一行）
        row3 = ttk.Frame(cad_frame)
        row3.pack(fill="x", padx=10, pady=(0, 5))
        
        # 图层图块设置（合并）
        combined_frame = ttk.LabelFrame(parent, text="图层图块设置")

        def on_pipe_layers(layers):
            self.on_config_change("pipe_layers", layers)
        def on_riser_layers(layers):
            self.on_config_change("riser_layers", layers)
        def on_riser_note_layers(layers):
            self.on_config_change("riser_note_layers", layers)

        self.multi_layer_manager = MultiLayerManager(
            combined_frame,
            self.config_manager,
            callbacks={
                'pipe': on_pipe_layers,
                'riser': on_riser_layers,
                'riser_note': on_riser_note_layers,
            }
        )
        self.multi_layer_manager.pack(fill="x", padx=5, pady=(5, 0))

        ttk.Separator(combined_frame, orient="horizontal").pack(fill="x", padx=20, pady=5)

        def on_valve_block(values):
            self.on_config_change("valve_block_name", ", ".join(values))
        def on_hydrant_block(values):
            self.on_config_change("hydrant_block_name", ", ".join(values))
        def on_sprinkler_block(values):
            self.on_config_change("sprinkler_block_name", ", ".join(values))

        self.multi_block_manager = MultiLayerManager(
            combined_frame,
            self.config_manager,
            callbacks={
                'valve': on_valve_block,
                'hydrant': on_hydrant_block,
                'sprinkler': on_sprinkler_block,
            },
            types=[
                ('valve', '阀门块名'),
                ('hydrant', '消火栓块名'),
                ('sprinkler', '喷头块名'),
            ],
            history_prefix="blocks"
        )
        self.multi_block_manager.pack(fill="x", padx=5, pady=(0, 5))

        align_frame = ttk.Frame(combined_frame)
        align_frame.pack(fill="x", padx=5, pady=(0, 5))
        ttk.Label(align_frame, text="对齐点块名:").pack(side="left")
        self.align_block_var = tk.StringVar(value=self.current_config.get("align_block_name", "Floorbase"))
        align_entry = ttk.Entry(align_frame, textvariable=self.align_block_var)
        align_entry.pack(side="left", fill="x", expand=True, padx=(5, 10))
        align_entry.bind("<FocusOut>",
                         lambda e: self.on_config_change("align_block_name", self.align_block_var.get()))
        ttk.Label(align_frame, text="属性字段:").pack(side="left")
        self.align_attr_var = tk.StringVar(value=self.current_config.get("align_attribute_name", "Elevation"))
        attr_entry = ttk.Entry(align_frame, textvariable=self.align_attr_var)
        attr_entry.pack(side="left", fill="x", expand=True, padx=(5, 0))
        attr_entry.bind("<FocusOut>",
                        lambda e: self.on_config_change("align_attribute_name", self.align_attr_var.get()))

        combined_frame.pack(fill="x", padx=5, pady=(0, 10))

        # 单位与管材设置（合并）
        unit_material_frame = ttk.LabelFrame(parent, text="单位与管材设置")
        unit_material_frame.pack(fill="x", padx=5, pady=(0, 10))

        # 水平容器，放置六个列
        columns_frame = ttk.Frame(unit_material_frame)
        columns_frame.pack(fill="x", padx=5, pady=5)

        # 列1：画图单位
        unit_col1 = ttk.Frame(columns_frame)
        unit_col1.pack(side="left", padx=5, fill="y", expand=True)
        ttk.Label(unit_col1, text="画图单位:").pack(anchor="w", pady=(0, 5))
        self.drawing_unit_var = tk.StringVar(value=self.current_config.get("drawing_unit", "毫米"))
        drawing_unit_combo = ttk.Combobox(
            unit_col1,
            textvariable=self.drawing_unit_var,
            values=["毫米", "厘米", "米"],
            state="readonly",
            width=6
        )
        drawing_unit_combo.pack(anchor="w")
        drawing_unit_combo.bind("<<ComboboxSelected>>",
                                lambda e: self.on_config_change("drawing_unit", self.drawing_unit_var.get()))

        # 列2：流量单位
        unit_col2 = ttk.Frame(columns_frame)
        unit_col2.pack(side="left", padx=5, fill="y", expand=True)
        ttk.Label(unit_col2, text="流量单位:").pack(anchor="w", pady=(0, 5))
        self.flow_unit_var = tk.StringVar(value=self.current_config.get("flow_unit", "L/s"))
        flow_unit_combo = ttk.Combobox(
            unit_col2,
            textvariable=self.flow_unit_var,
            values=["L/s", "m³/h"],
            state="readonly",
            width=6
        )
        flow_unit_combo.pack(anchor="w")
        flow_unit_combo.bind("<<ComboboxSelected>>",
                             lambda e: self.on_config_change("flow_unit", self.flow_unit_var.get()))

        # 列3：压力单位
        unit_col3 = ttk.Frame(columns_frame)
        unit_col3.pack(side="left", padx=5, fill="y", expand=True)
        ttk.Label(unit_col3, text="压力单位:").pack(anchor="w", pady=(0, 5))
        self.pressure_unit_var = tk.StringVar(value=self.current_config.get("pressure_unit", "m"))
        pressure_unit_combo = ttk.Combobox(
            unit_col3,
            textvariable=self.pressure_unit_var,
            values=["m", "MPa"],
            state="readonly",
            width=6
        )
        pressure_unit_combo.pack(anchor="w")
        pressure_unit_combo.bind("<<ComboboxSelected>>",
                                 lambda e: self.on_config_change("pressure_unit", self.pressure_unit_var.get()))

        # 列4：匹配容差
        unit_col4 = ttk.Frame(columns_frame)
        unit_col4.pack(side="left", padx=5, fill="y", expand=True)
        ttk.Label(unit_col4, text="容差(mm):").pack(anchor="w", pady=(0, 5))
        self.tolerance_var = tk.StringVar(value=str(self.current_config.get("tolerance", 10.0)))
        tolerance_entry = ttk.Entry(unit_col4, textvariable=self.tolerance_var, width=8)
        tolerance_entry.pack(anchor="w")
        tolerance_entry.bind("<FocusOut>", lambda e: self.on_tolerance_changed())

        # 列5：管材管理按钮 + 管材下拉框（按钮在上，下拉框在下）
        unit_col5 = ttk.Frame(columns_frame)
        unit_col5.pack(side="left", padx=5, fill="y", expand=True)
        # 按钮行：管材C值（原"管理"按钮）+ 局部水损系数
        btn_row5 = ttk.Frame(unit_col5)
        btn_row5.pack(anchor="w", pady=(0, 5))
        manage_btn = ttk.Button(btn_row5, text="管材C值", command=self.manage_materials, width=8)
        manage_btn.pack(side="left")
        ttk.Button(btn_row5, text="局部水损系数", command=self.edit_local_loss_coeffs, width=11).pack(side="left", padx=(5, 0))
        ttk.Button(btn_row5, text="标高管材", command=self.edit_elevation_materials, width=9).pack(side="left", padx=(5, 0))
        # 管材下拉框（移除标签）
        self.material_var = tk.StringVar(value=self.current_config.get("pipe_material", "镀锌钢管"))
        self.material_combo = ttk.Combobox(
            unit_col5,
            textvariable=self.material_var,
            values=self.material_manager.get_materials(),
            state="readonly",
            width=12
        )
        self.material_combo.pack(anchor="w")
        self.material_combo.bind("<<ComboboxSelected>>", lambda e: self.on_material_changed())

        # 列6：空列（用于平衡布局，也可移除）
        # unit_col6 = ttk.Frame(columns_frame)
        # unit_col6.pack(side="left", padx=5, fill="y", expand=True)
        # 可放置其他控件或留空

        # 底部容差说明（跨越所有列）
        self.tolerance_note = ttk.Label(
            unit_material_frame,
            text="容差：管道与管道端点的距离偏差、阀门与管道的距离偏差、供水点和用水点与管道端点的距离偏差，超过此距离将不认为是连接的。",
            font=("Arial", 8),
            foreground="gray",
            justify=tk.LEFT
        )
        self.tolerance_note.pack(side="bottom", fill="x", padx=5, pady=(0, 5))

        # 动态更新 wraplength
        def update_tolerance_wraplength(event):
            new_width = event.width - 20
            if new_width > 50:
                self.tolerance_note.config(wraplength=new_width)

        unit_material_frame.bind("<Configure>", update_tolerance_wraplength)
        



        # 计算公式区域
        formula_frame = ttk.LabelFrame(parent, text="计算公式")
        formula_frame.pack(fill="x", padx=5, pady=(0, 10))

        # 公式原文
        formula_text = """喷头：q = (K·√(0.1·P))/60     消火栓：Hxh = Ad·Ld·q² + q²/B + Hak"""
        ttk.Label(formula_frame, text=formula_text, justify=tk.LEFT).pack(anchor="w", padx=5, pady=5)
        
        # ========== 新增：变量含义说明 ==========
        meaning_frame = ttk.Frame(formula_frame)
        meaning_frame.pack(fill="x", padx=5, pady=(0,5))
        
        # 喷头含义
        ttk.Label(meaning_frame, text="喷头：q 喷头流量 (L/s), P 喷头压力m ()", 
                font=("Arial", 8), foreground="gray").pack(side="left", padx=(0,20))
        # 消火栓含义
        ttk.Label(meaning_frame, text="消火栓：Hxh 栓口压力 (m), q 栓口流量 (L/s)", 
                font=("Arial", 8), foreground="gray").pack(side="left")
        # ======================================

        # 参数输入表格
        param_frame = ttk.Frame(formula_frame)
        param_frame.pack(fill="x", padx=5, pady=5)

        # 列标题
        headers = ["喷头K", "水带比阻Ad", "水带长度Ld(m)", "水枪特性B", "栓口水损Hak(m)", "最高流速(m/s)", "最低流速(m/s)"]
        for i, h in enumerate(headers):
            ttk.Label(param_frame, text=h, font=('Arial', 9, 'bold')).grid(row=0, column=i, padx=5, pady=2)

        # 创建变量并绑定
        self.k_var = tk.StringVar(value=str(self.current_config.get("sprinkler_K", 80)))
        self.ad_var = tk.StringVar(value=str(self.current_config.get("hydrant_Ad", 0.00172)))
        self.ld_var = tk.StringVar(value=str(self.current_config.get("hydrant_Ld", 25)))
        self.b_var = tk.StringVar(value=str(self.current_config.get("hydrant_B", 1.577)))
        self.hak_var = tk.StringVar(value=str(self.current_config.get("hydrant_Hak", 2.0)))
        self.max_velocity_var = tk.StringVar(value=str(self.current_config.get("max_velocity", 5.0)))
        self.min_velocity_var = tk.StringVar(value=str(self.current_config.get("min_velocity", 2.0)))
        self.up_pipe_len_var = tk.StringVar(value=str(self.current_config.get("sprinkler_up_pipe_len", 0.6)))
        self.down_pipe_len_var = tk.StringVar(value=str(self.current_config.get("sprinkler_down_pipe_len", 0.2)))
        self.pressure_tol_var = tk.StringVar(value=str(self.current_config.get("pressure_tolerance", 0.1)))
        
        # 喷头K输入框改为Combobox，可输入可选择
        k_combo = ttk.Combobox(param_frame, textvariable=self.k_var, values=[80, 115, 161, 200, 202, 242, 320, 363], width=8, state='readonly')
        k_combo.grid(row=1, column=0, padx=5, pady=2)

        # 其他输入框保持Entry
        ad_entry = ttk.Entry(param_frame, textvariable=self.ad_var, width=8)
        ld_entry = ttk.Entry(param_frame, textvariable=self.ld_var, width=8)
        b_entry = ttk.Entry(param_frame, textvariable=self.b_var, width=8)
        hak_entry = ttk.Entry(param_frame, textvariable=self.hak_var, width=8)
        max_v_entry = ttk.Entry(param_frame, textvariable=self.max_velocity_var, width=8)
        min_v_entry = ttk.Entry(param_frame, textvariable=self.min_velocity_var, width=8)
        max_v_entry.grid(row=1, column=5, padx=5, pady=2)
        min_v_entry.grid(row=1, column=6, padx=5, pady=2)

        # 喷头短立管长度输入框单独一行（避免被遮挡）
        ttk.Label(param_frame, text="上喷短管长度(m):").grid(row=2, column=0, sticky="e", padx=5, pady=2)
        up_len_entry = ttk.Entry(param_frame, textvariable=self.up_pipe_len_var, width=8)
        up_len_entry.grid(row=2, column=1, sticky="w", padx=5, pady=2)
        ttk.Label(param_frame, text="下喷短管长度(m):").grid(row=2, column=2, sticky="e", padx=5, pady=2)
        down_len_entry = ttk.Entry(param_frame, textvariable=self.down_pipe_len_var, width=8)
        down_len_entry.grid(row=2, column=3, sticky="w", padx=5, pady=2)
        # 计算结果允许误差（模式C二分主判据：最不利用水点超压≤该值即终止，缺省0.1m）
        ttk.Label(param_frame, text="计算结果允许误差(m):").grid(row=2, column=4, sticky="e", padx=5, pady=2)
        tol_entry = ttk.Entry(param_frame, textvariable=self.pressure_tol_var, width=8)
        tol_entry.grid(row=2, column=5, sticky="w", padx=5, pady=2)
        
        max_v_entry.bind("<FocusOut>", lambda e: self.on_velocity_changed())
        min_v_entry.bind("<FocusOut>", lambda e: self.on_velocity_changed())
        
        ad_entry.grid(row=1, column=1, padx=5, pady=2)
        ld_entry.grid(row=1, column=2, padx=5, pady=2)
        b_entry.grid(row=1, column=3, padx=5, pady=2)
        hak_entry.grid(row=1, column=4, padx=5, pady=2)
        
        # 流速说明
        velocity_note = ttk.Label(
            formula_frame,
            text="最高流速为消防管道最高允许速度，用以校核管径；最低流速为用户期望的消防管道最低流速，用以优化管径。",
            font=("Arial", 8),
            foreground="gray",
            justify=tk.LEFT,
            wraplength=500  # 可根据需要调整
        )
        velocity_note.pack(fill="x", padx=5, pady=(0, 5))
        def update_note_wraplength(event):
            new_width = event.width - 20
            if new_width > 50:
                velocity_note.config(wraplength=new_width)
        velocity_note.bind("<Configure>", update_note_wraplength)

        # 绑定更新事件（值改变时保存到 live_config）
        def on_param_change(var, key):
            try:
                val = float(var.get())
                self.on_config_change(key, val)
            except ValueError:
                pass  # 忽略非法输入，保持原值

        for var, key in [(self.k_var, "sprinkler_K"), (self.ad_var, "hydrant_Ad"),
                         (self.ld_var, "hydrant_Ld"), (self.b_var, "hydrant_B"),
                         (self.hak_var, "hydrant_Hak"), (self.up_pipe_len_var, "sprinkler_up_pipe_len"),
                         (self.down_pipe_len_var, "sprinkler_down_pipe_len"),
                         (self.pressure_tol_var, "pressure_tolerance")]:
            var.trace('w', lambda *a, v=var, k=key: on_param_change(v, k))
        

    def create_right_panel(self, parent):
        """创建右面板内容"""
        self.color_table = ColorDiameterTableConfig(
            parent,
            self.config_manager,
            self.material_manager,
            on_change_callback=self.on_color_table_changed
        )
        self.color_table.pack(fill="both", expand=True, padx=5, pady=5)

        # 在颜色对照表下方添加操作说明标签
        self.operation_note = ttk.Label(
            parent,
            text="操作方法：双击单元格编辑内容，双击'✓'添加新行，双击'×'删除该行。所有修改在光标离开单元格时自动保存。",
            font=("Arial", 9),
            foreground="#666666",
            justify=tk.LEFT  # 左对齐便于换行阅读
        )
        self.operation_note.pack(side="bottom", fill="x", padx=10, pady=(0, 5))

        # 动态更新 wraplength
        def update_note_wraplength(event):
            # 获取 parent（右面板）当前宽度，减去左右边距（10+10=20像素）
            new_width = event.width - 20
            if new_width > 50:  # 避免宽度过小
                self.operation_note.config(wraplength=new_width)

        parent.bind("<Configure>", update_note_wraplength)
        
    def on_config_change(self, key: str, value):
        """配置发生变化时更新内存配置"""
        self.current_config[key] = value
        new = copy.deepcopy(self.current_config)
        # 非系统类型改动时保留读取 CAD 时的自动检测结果（防止检测值被方案旧值覆盖）
        if key != "system_type":
            live = self.config_manager.get_live_config()
            if live and live.get("system_type"):
                new["system_type"] = live["system_type"]
        # 同步到config_manager的live_config
        self.config_manager.set_live_config(new)
        # 如果更改的是单位，通知所有页面
        if key in ['flow_unit', 'pressure_unit']:
            root = self.winfo_toplevel()
            if hasattr(root, 'main_app'):
                root.main_app.notify_units_changed()
    
    def on_material_changed(self):
        """管材类型变化处理"""
        material = self.material_var.get()
        self.on_config_change("pipe_material", material)
        self.color_table.set_material(material)
        self.update_all_material_combos()
        # 注意：切换管材只影响后续读取CAD时的默认管材，
        # 已读入管道的管材/内径保持CAD读入时状态，不作更改
    
    def on_tolerance_changed(self):
        """容差变化处理"""
        try:
            tolerance = float(self.tolerance_var.get())
            self.on_config_change("tolerance", tolerance)
        except ValueError:
            self.tolerance_var.set(str(self.current_config.get("tolerance", 10.0)))
    
    def on_layers_changed(self, layers):
        """图层变化处理"""
        self.on_config_change("pipe_layers", layers)

    def on_riser_layers_changed(self, layers):
        """立管图层变化处理"""
        self.on_config_change("riser_layers", layers)

    def on_riser_note_layers_changed(self, layers):
        """立管标注图层变化处理"""
        self.on_config_change("riser_note_layers", layers)
    
    def on_color_table_changed(self, color_data):
        """颜色管径对照表变化处理"""
        # 注意：现在颜色-管径数据直接保存在materials.json中
        # 这个回调可能不再需要，但保留以备其他用途
        pass
    
    def browse_cad_file(self):
        """浏览选择CAD文件"""
        file_path = filedialog.askopenfilename(
            title="选择CAD文件",
            filetypes=[("CAD Files", "*.dwg *.dxf"), ("All files", "*.*")]
        )
        if file_path:
            self.cad_file_var.set(file_path)
            # 只保存路径，不立即加载
            self.config_manager.update_global_setting("last_cad_file", file_path)
            self.loading_status_var.set("已选择文件，点击'读取CAD数据'按钮开始读取")
    
    def _on_region_mode_toggle(self):
        """区域管网模式复选框切换"""
        new_state = self.region_mode_var.get()
        self.config_manager.update_global_setting("region_mode_enabled", new_state)

        if new_state:
            # 进入区域管网模式
            if self.cad_data_manager and self.cad_data_manager.is_loaded:
                result = messagebox.askyesno(
                    "确认操作",
                    "此操作相当于重启程序，将删除内存中的所有数据，且无法撤销。",
                    icon="warning"
                )
                if result:
                    self._clear_and_enter_region_mode("进入区域管网模式")
                else:
                    self.region_mode_var.set(False)
                    self.config_manager.update_global_setting("region_mode_enabled", False)
            else:
                self.loading_status_var.set("进入区域管网模式")
        else:
            # 退出区域管网模式
            if self.cad_data_manager and self.cad_data_manager.is_loaded:
                result = messagebox.askyesno(
                    "确认操作",
                    "此操作相当于重启程序，将删除内存中的所有数据，且无法撤销。",
                    icon="warning"
                )
                if result:
                    self._clear_and_enter_region_mode("退出区域管网模式")
                else:
                    self.region_mode_var.set(True)
                    self.config_manager.update_global_setting("region_mode_enabled", True)
            else:
                self.loading_status_var.set("退出区域管网模式")

    def _clear_and_enter_region_mode(self, status_text: str):
        """清空所有数据并更新状态"""
        self.cad_data_manager.clear_all_data()
        self.loading_status_var.set(status_text)
        root = self.winfo_toplevel()
        if hasattr(root, 'main_app'):
            root.main_app.reset_calculation_and_preview()
            root.main_app.update_status()
            # 刷新所有数据页面
            for name in ['管道', '节点', '阀门', '供水点和用水点']:
                if name in root.main_app.pages:
                    root.main_app.pages[name].refresh_data()

    def _prompt_building_id(self) -> str | None:
        """弹出楼栋ID输入对话框（区域模式专用）。返回楼栋ID或None（取消）"""
        import re
        dialog = tk.Toplevel(self)
        dialog.title("楼栋信息")
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.update_idletasks()
        w, h = 450, 240
        pw = self.winfo_toplevel().winfo_width()
        ph = self.winfo_toplevel().winfo_height()
        px = self.winfo_toplevel().winfo_x()
        py = self.winfo_toplevel().winfo_y()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        dialog.geometry(f"{w}x{h}+{x}+{y}")

        result = {'id': '', 'confirmed': False}

        id_frame = ttk.Frame(dialog, padding=10)
        id_frame.pack(fill='x')
        ttk.Label(id_frame, text="楼栋ID：").pack(side='left')
        id_var = tk.StringVar()
        id_entry = ttk.Entry(id_frame, textvariable=id_var, width=20)
        id_entry.pack(side='left', padx=(10, 0))
        id_entry.focus_set()

        outdoor_frame = ttk.Frame(dialog, padding=10)
        outdoor_frame.pack(fill='x')
        outdoor_var = tk.BooleanVar(value=False)
        outdoor_check = ttk.Checkbutton(
            outdoor_frame,
            text="标记为室外管网",
            variable=outdoor_var,
            command=lambda: _on_outdoor_toggle()
        )
        outdoor_check.pack(side='left')
        if 'ZT' in self.cad_data_manager.building_data:
            outdoor_check.config(state='disabled')

        def _on_outdoor_toggle():
            if outdoor_var.get():
                id_var.set('ZT')
                id_entry.config(state='disabled')
            else:
                id_var.set('')
                id_entry.config(state='normal')

        # 管网类型选择
        type_frame = ttk.Frame(dialog, padding=10)
        type_frame.pack(fill='x')
        ttk.Label(type_frame, text="管网类型:").pack(side='left')
        # 区域单体缺省为室内消火栓（不沿用当前配置——当前配置可能是上次读入单体的类型）
        sys_type_var = tk.StringVar(value="indoor_hydrant")
        for text, val in [("室外消火栓", "outdoor_hydrant"), ("室内消火栓", "indoor_hydrant"), ("喷淋", "sprinkler")]:
            ttk.Radiobutton(type_frame, text=text, variable=sys_type_var,
                            value=val).pack(side='left', padx=5)

        type_name_map = {"outdoor_hydrant": "室外消火栓", "indoor_hydrant": "室内消火栓", "sprinkler": "喷淋"}
        type_hint = ttk.Label(dialog, text=f"⚠ 当前管网类型：室内消火栓（务必与CAD图纸一致）",
                              foreground="red", padding=(10, 0))
        type_hint.pack(fill='x')

        def _on_type_changed(*_):
            """单选按钮变化时同步更新警示文字"""
            type_hint.config(
                text=f"⚠ 当前管网类型：{type_name_map.get(sys_type_var.get(), '未知')}（务必与CAD图纸一致）")

        for child in type_frame.winfo_children():
            if isinstance(child, ttk.Radiobutton):
                child.configure(command=_on_type_changed)
        sys_type_var.trace_add("write", _on_type_changed)

        error_label = ttk.Label(dialog, text="", foreground="red", padding=10)
        error_label.pack(fill='x')

        def _on_ok():
            bid = id_var.get().strip()
            if not re.match(r'^[a-zA-Z0-9_]+$', bid):
                error_label.config(text="楼栋ID格式错误：仅允许字母、数字、下划线")
                return
            if bid in self.cad_data_manager.building_data:
                error_label.config(text=f"楼栋ID '{bid}' 已存在，请换一个")
                return
            result['id'] = bid
            # 保存管网类型到配置
            self.current_config["system_type"] = sys_type_var.get()
            self.on_config_change("system_type", sys_type_var.get())
            result['confirmed'] = True
            dialog.destroy()

        btn_frame = ttk.Frame(dialog, padding=10)
        btn_frame.pack(fill='x')
        ttk.Button(btn_frame, text="确定", command=_on_ok).pack(side='right', padx=5)
        ttk.Button(btn_frame, text="取消", command=dialog.destroy).pack(side='right', padx=5)
        dialog.bind('<Return>', lambda e: _on_ok())
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        dialog.grab_set()
        self.wait_window(dialog)
        return result['id'] if result['confirmed'] else None

    def load_cad_data(self):
        """读取CAD数据"""
        if self.is_loading_cad:
            return
        
        cad_file = self.cad_file_var.get()
        if not cad_file:
            self.loading_status_var.set("错误：请先选择CAD文件")
            return
        
        # 检查文件是否存在
        if not os.path.exists(cad_file):
            self.loading_status_var.set("错误：文件不存在")
            return

        is_region = self.region_mode_var.get()
        building_id = ""
        if is_region:
            building_id = self._prompt_building_id()
            if building_id is None:
                return
            # 检查文件是否已作为其他单体读入
            existing_bid = self.cad_data_manager.get_building_id_by_file(cad_file)
            if existing_bid is not None and existing_bid != building_id:
                if not messagebox.askyesno("提示",
                        f"此CAD文件已作为单体「{existing_bid}」读入。\n"
                        f"是否继续以新楼栋号「{building_id}」读入？"):
                    return
                # 移除旧关联，后续 load_cad_file 会写入新关联
                if building_id in self.cad_data_manager.building_file_paths:
                    del self.cad_data_manager.building_file_paths[building_id]
        
        # 禁用按钮，防止重复点击
        self.is_loading_cad = True
        self.load_button.config(state=tk.DISABLED)
        self.loading_status_var.set(f"[{building_id}] 正在读取CAD文件..." if building_id else "正在读取CAD文件...")
        self.update_idletasks()  # 强制更新UI
        
        # 在新线程中读取
        import threading
        
        def load_cad_thread():
            try:
                # 在线程内设置 _building_id，防止早期 return 未清理
                if building_id:
                    self.cad_data_manager._building_id = building_id
                # 定义进度回调，通过 after 更新UI
                def progress_callback(message):
                    self.after(0, lambda msg=message: self.loading_status_var.set(
                        f"[{building_id}] {msg}" if building_id else msg
                    ))
                # 调用CAD数据管理器加载文件
                success = self.cad_data_manager.load_cad_file(
                    cad_file, 
                    force_reload=True,
                    progress_callback=progress_callback
                )
                
                if success:
                    # 获取摘要信息
                    summary = self.cad_data_manager.get_summary()
                    pipes_count = summary.get("管道数量", 0)
                    nodes_count = summary.get("节点数量", 0)
                    
                    prefix = f"[{building_id}] " if building_id else ""
                    # 管件画图错误分析（每栋读取完毕即弹非模态列表）
                    error_items = []
                    try:
                        from core.fitting_analyzer import analyze_fittings
                        # 区域模式逐单体读取：只分析当前单体的管道（ID带"{building_id}_"前缀），
                        # 避免重复提示其它已读单体的画图错误。
                        pipe_ids = None
                        if building_id:
                            pipe_ids = {
                                p.pipe_id for p in self.cad_data_manager.pipes
                                if p.pipe_id.startswith(f"{building_id}_")
                            }
                        analysis = analyze_fittings(self.cad_data_manager, pipe_ids=pipe_ids)
                        error_items = list(analysis.error_nodes)
                        # 缓存自环管道列表供计算时直接读取（避免重复分析）；
                        # 区域模式只缓存当前单体的自环管道（避免覆盖其它单体的缓存）
                        if building_id:
                            current_self_loops = set(getattr(
                                self.cad_data_manager, 'self_loop_pipes', []) or [])
                            current_self_loops.update(analysis.self_loop_pipes)
                            self.cad_data_manager.self_loop_pipes = list(current_self_loops)
                        else:
                            self.cad_data_manager.self_loop_pipes = list(analysis.self_loop_pipes)
                        # 自环管道（起点=终点）：不阻塞计算但需提醒用户修复CAD
                        for pid in analysis.self_loop_pipes:
                            pipe = self.cad_data_manager.pipe_by_id.get(pid)
                            node_id = pipe.start_node_id if pipe else ""
                            length = f"，长度{pipe.length:.3f}m" if pipe else ""
                            error_items.append(
                                (node_id, f"自环管道{pid}（起点=终点{length}），请在CAD中检查该管道"))
                    except Exception:
                        error_items = []
                    # 在主线程中更新UI
                    self.after(0, lambda: self.show_load_result(
                        True, 
                        f"{prefix}成功读取 {pipes_count} 条管道，{nodes_count} 个节点"
                    ))
                    if error_items:
                        from gui.fitting_error_dialog import show_fitting_error_dialog
                        self.after(0, lambda items=error_items: show_fitting_error_dialog(
                            self.winfo_toplevel(), items))
                else:
                    prefix = f"[{building_id}] " if building_id else ""
                    self.after(0, lambda: self.show_load_result(False, f"{prefix}CAD文件读取失败"))
                
            except Exception as e:
                error_msg = str(e)
                self.after(0, lambda: self.show_load_result(False, f"读取出错: {error_msg}"))
            finally:
                if building_id:
                    self.cad_data_manager._building_id = ""
        
        # 启动读取线程
        thread = threading.Thread(target=load_cad_thread, daemon=True)
        thread.start()

    def show_load_result(self, success, message):
        """显示读取结果"""
        self.is_loading_cad = False
        self.load_button.config(state=tk.NORMAL)
        
        if success:
            # 保存最后一次成功读取的文件路径到全局设置
            self.config_manager.update_global_setting("last_cad_file", self.cad_file_var.get())
            self.loading_status_var.set(f"✓ {message}")
            self.load_status_label.config(foreground="green")

            # 通知主程序更新底部状态栏
            root = self.winfo_toplevel()
            if hasattr(root, 'main_app'):
                root.main_app.update_status()
            if not self.region_mode_var.get():
                root.main_app.reset_calculation_and_preview()
            for name in ['管道', '节点', '阀门', '供水点和用水点']:
                if name in root.main_app.pages:
                    root.main_app.pages[name].refresh_data()
            if '管网预览' in root.main_app.pages:
                root.main_app.pages['管网预览'].refresh_data()
        else:
            self.loading_status_var.set(f"✗ {message}")
            self.load_status_label.config(foreground="red")
     


    def update_all_widgets(self):
        """更新所有控件显示"""
        # 更新CAD文件路径
        self.cad_file_var.set(self.config_manager.get_global_setting("last_cad_file", ""))
        
        # 更新多图层管理器
        pipe_layers = self.current_config.get("pipe_layers", [])
        self.multi_layer_manager.set_entry_text('pipe', ", ".join(pipe_layers))
        riser_layers = self.current_config.get("riser_layers", [])
        self.multi_layer_manager.set_entry_text('riser', ", ".join(riser_layers))
        riser_note_layers = self.current_config.get("riser_note_layers", [])
        self.multi_layer_manager.set_entry_text('riser_note', ", ".join(riser_note_layers))

        # 更新单位设置
        self.drawing_unit_var.set(self.current_config.get("drawing_unit", "毫米"))
        self.flow_unit_var.set(self.current_config.get("flow_unit", "L/s"))
        self.pressure_unit_var.set(self.current_config.get("pressure_unit", "m"))
        self.tolerance_var.set(str(self.current_config.get("tolerance", 10.0)))
        
        # 更新管材设置
        material = self.current_config.get("pipe_material", "镀锌钢管")
        self.material_var.set(material)
        
        # 更新图块设置
        self.multi_block_manager.set_entry_text('valve', self.current_config.get("valve_block_name", "valve"))
        self.multi_block_manager.set_entry_text('hydrant', self.current_config.get("hydrant_block_name", "hydrant"))
        self.multi_block_manager.set_entry_text('sprinkler', self.current_config.get("sprinkler_block_name", ""))
        self.align_block_var.set(self.current_config.get("align_block_name", "Floorbase"))
        self.align_attr_var.set(self.current_config.get("align_attribute_name", "Elevation"))

        
        # 更新计算设置
        self.tolerance_var.set(str(self.current_config.get("tolerance", 10.0)))
        
        # 更新颜色管径对照表
        self.color_table.set_material(material)
        self.dxf_read_var.set(self.current_config.get("use_dxf_read", False))
        
        # 更新新增的配置
        self.max_velocity_var.set(str(self.current_config.get("max_velocity", 5.0)))
        self.min_velocity_var.set(str(self.current_config.get("min_velocity", 2.0)))


    def update_all_material_combos(self):
        """更新所有管材下拉框"""
        materials = self.material_manager.get_materials()
        
        if not materials:
            return
        
        # 更新主设置页面的管材下拉框
        # 我们需要找到主设置页面的管材下拉框
        # 由于我们的GUI结构比较复杂，我们直接通过变量名来更新
        
        # 首先，更新主设置页面中的管材下拉框
        # 我们需要找到所有的Combobox组件并检查它们是否是管材下拉框
        
        def find_and_update_material_combos(widget):
            """递归查找并更新管材下拉框"""
            try:
                # 如果是Combobox，检查是否为管材下拉框
                if isinstance(widget, ttk.Combobox):
                    # 获取当前值
                    current_val = widget.get()
                    # 检查这个值是否在管材列表中，或者下拉框的值列表是否包含管材
                    if current_val in materials or widget['values']:
                        # 检查下拉框的第一个值是否在管材列表中
                        if widget['values'] and widget['values'][0] in materials:
                            widget['values'] = materials
                            # 如果当前值不在新列表中，设置为第一个值
                            if current_val not in materials:
                                widget.set(materials[0])
                # 递归检查子组件
                for child in widget.winfo_children():
                    find_and_update_material_combos(child)
            except:
                pass
        
        # 从主窗口开始查找
        find_and_update_material_combos(self.inner_frame)
        
        # 更新当前方案的管材选择下拉框
        # 我们需要确保主设置页面的管材下拉框被更新
        # 由于material_combo可能没有被正确引用，我们直接更新变量
        
        # 获取当前管材值
        current_material = self.material_var.get()
        
        # 如果当前管材不在新列表中，设置为第一个管材
        if current_material not in materials:
            if materials:
                self.material_var.set(materials[0])
                self.on_material_changed()

    def edit_local_loss_coeffs(self):
        """局部水损系数对话框：3x2表格（消火栓/喷淋 x 局部水损比例法/当量长度法/支状喷淋倒推法）

        当前计算使用 A1 单元格（消火栓-局部水损比例法）的值，其余单元格备用；
        第三行「支状喷淋倒推法」仅喷淋适用：消火栓列显示"—"且不可编辑。
        修改经"确定"保存到 config.json，可记住用户设置。
        """
        cfg = self.current_config

        def get_value(new_key, old_key, default):
            if new_key in cfg:
                return cfg[new_key]
            if old_key and old_key in cfg:
                return cfg[old_key]
            return default

        values = {
            "row1": (get_value("local_loss_ratio_hydrant", "local_loss_method_ratio", 0.3),
                     get_value("local_loss_ratio_sprinkler", None, 0.5)),
            "row2": (get_value("equiv_len_ratio_hydrant", None, 0.1),
                     get_value("equiv_len_ratio_sprinkler", "equiv_length_method_ratio", 0.05)),
            "row3": ("—", get_value("tz_ratio_sprinkler", None, 0.015)),
        }

        dialog = tk.Toplevel(self)
        dialog.title("局部水损系数")
        dialog.geometry("400x230")
        self.center_dialog(dialog)
        dialog.transient(self)
        dialog.grab_set()

        table = ttk.Treeview(dialog, columns=("A", "B"), show="tree headings", height=3)
        table.heading("#0", text="计算方法")
        table.heading("A", text="消火栓局部水损")
        table.heading("B", text="喷淋局部水损")
        table.column("#0", width=130, anchor="center")
        table.column("A", width=120, anchor="center")
        table.column("B", width=120, anchor="center")
        table.insert("", "end", iid="row1", text="局部水损比例法",
                     values=(values["row1"][0], values["row1"][1]))
        table.insert("", "end", iid="row2", text="当量长度法",
                     values=(values["row2"][0], values["row2"][1]))
        table.insert("", "end", iid="row3", text="支状喷淋倒推法",
                     values=(values["row3"][0], values["row3"][1]))
        table.pack(fill="both", expand=True, padx=10, pady=(10, 5))

        tip = ttk.Label(dialog, text="双击单元格修改数值（支状喷淋倒推法仅喷淋适用）",
                        foreground="#666666")
        tip.pack(anchor="w", padx=10, pady=(0, 5))

        # 双击编辑单元格（模式参考 supply_demand_module 的树双击编辑）
        def on_double_click(event):
            region = table.identify("region", event.x, event.y)
            if region not in ("cell", "tree"):
                return
            item_id = table.identify_row(event.y)
            col = table.identify_column(event.x)
            if not item_id or not col.startswith("#"):
                return
            col_index = 1 if col == "#1" else 2  # #0 为行名不可编辑
            if col == "#0":
                return
            if item_id == "row3" and col == "#1":
                return  # 支状喷淋倒推法仅喷淋可用：消火栓列"—"锁定不可修改
            x, y, width, height = table.bbox(item_id, col)
            if not x:
                return
            current_value = table.set(item_id, col)
            edit_var = tk.StringVar(value=current_value)
            edit_entry = ttk.Entry(table, textvariable=edit_var, width=width // 8)
            edit_entry.place(x=x, y=y, width=width, height=height)
            edit_entry.focus_set()
            edit_entry.select_range(0, tk.END)

            def save_edit(event=None):
                new_text = edit_var.get().strip()
                edit_entry.destroy()
                try:
                    float(new_text)
                except ValueError:
                    table.set(item_id, col, current_value)
                    return
                table.set(item_id, col, new_text)

            def cancel_edit(event=None):
                edit_entry.destroy()

            edit_entry.bind("<Return>", save_edit)
            edit_entry.bind("<FocusOut>", save_edit)
            edit_entry.bind("<Escape>", cancel_edit)

        table.bind("<Double-1>", on_double_click)

        def save_and_close():
            try:
                new_vals = {
                    "local_loss_ratio_hydrant": float(table.set("row1", "A")),      # A1 当前计算使用
                    "local_loss_ratio_sprinkler": float(table.set("row1", "B")),    # B1 备用
                    "equiv_len_ratio_hydrant": float(table.set("row2", "A")),       # A2 备用
                    "equiv_len_ratio_sprinkler": float(table.set("row2", "B")),     # B2 备用
                    "tz_ratio_sprinkler": float(table.set("row3", "B")),            # B3 支状喷淋倒推法
                }
            except ValueError:
                messagebox.showerror("错误", "所有单元格必须是有效数字", parent=dialog)
                return
            for key, value in new_vals.items():
                self.current_config[key] = value
            self.config_manager.set_live_config(self.current_config)
            for key, value in new_vals.items():
                self.config_manager.update_current_config(key, value)
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=(0, 10))
        ttk.Button(btn_frame, text="确定", command=save_and_close, width=10).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="取消", command=dialog.destroy, width=10).pack(side="left", padx=5)

    def edit_elevation_materials(self):
        """标高管材分段对话框。

        加压管网底部压力最大、顶部最小：行1~3 管材按承压从低到高固定排列
        （行1 镀锌、行2 加厚、行3 无缝），标高范围表达式与之配套——
        承压最低的行1 对应最高标高段（压力最小），承压最高的行3 对应最低标高段（压力最大）：
          行1：H > [下限]（[下限] < H）
          行2：[下限] < H ≤ [上限]
          行3：H ≤ [上限]
        管材留空 = 该行不生效；输入框留空 = 该端不限。
        行4 为室外管网专属（管材下拉可用，标高列不可用，显示"不参与标高分段"）。
        顶部「启用标高管材」复选框：
        - 打开时记录快照；确定时按快照与当前状态对比分派
          （内容未变 → 仅保存；勾选 → 应用；取消勾选且原本勾选 → 恢复统一管材）；
        - 「取消」按钮不保存任何修改。
        """
        materials = self.material_manager.get_materials()
        if not materials:
            messagebox.showwarning("无管材", "管材列表为空，请先添加管材", parent=self)
            return

        # 打开时快照（对比用）
        initial = copy.deepcopy(self.elevation_materials)
        cur = self.elevation_materials

        dialog = tk.Toplevel(self)
        dialog.title("标高管材分段")
        dialog.geometry("520x300")
        self.center_dialog(dialog)
        dialog.transient(self)
        dialog.grab_set()

        # 启用复选框
        enabled_var = tk.BooleanVar(value=bool(cur.get("enabled", False)))
        enable_chk = ttk.Checkbutton(dialog, text="启用标高管材（按标高分段赋予不同管材）",
                                     variable=enabled_var)
        enable_chk.pack(anchor="w", padx=10, pady=(10, 5))

        tip = ttk.Label(dialog,
                        text="说明：低标高层压力最大，请将承压高的管材放在低标高分段。\n"
                             "H 为楼面标高；管材留空表示该分段不生效。",
                        foreground="#666666", justify="left")
        tip.pack(anchor="w", padx=10, pady=(0, 5))

        # 分段表格区（常驻控件）：行1~3 室内分段（承压从低到高：镀锌/加厚/无缝），行4 室外管网（标高不可用）
        segs = cur.get("segments", [])
        default_segs = [
            {"material": "镀锌钢管", "lower": None, "upper": None},
            {"material": "加厚钢管", "lower": None, "upper": None},
            {"material": "无缝钢管", "lower": None, "upper": None},
        ]
        seg_data = [
            segs[i] if i < len(segs) else default_segs[i] for i in range(3)
        ]

        grid = ttk.Frame(dialog)
        grid.pack(fill="x", padx=10, pady=(0, 5))

        # 表头
        ttk.Label(grid, text="分段", width=8).grid(row=0, column=0, padx=(0, 8), pady=2)
        ttk.Label(grid, text="管材", width=12).grid(row=0, column=1, padx=(0, 8), pady=2)
        ttk.Label(grid, text="标高范围(m)", width=26).grid(row=0, column=2, pady=2)

        row_names = ["行1", "行2", "行3"]
        # 行1（镀锌，承压最低）: 下限 < H（最高段，压力最小）
        # 行2（加厚）        : 下限 < H ≤ 上限
        # 行3（无缝，承压最高）: H ≤ 上限（最低段，压力最大）
        row_modes = ["lower_only", "both", "upper_only"]
        seg_vars = []       # [StringVar(material), StringVar(lower), StringVar(upper)]
        combos = []
        for i, name in enumerate(row_names):
            seg = seg_data[i]
            ttk.Label(grid, text=name, width=8).grid(row=i + 1, column=0, padx=(0, 8), pady=2)
            mat_var = tk.StringVar(value=seg.get("material", "") or "")
            combo = ttk.Combobox(grid, textvariable=mat_var, values=materials,
                                 state="readonly", width=12)
            combo.grid(row=i + 1, column=1, padx=(0, 8), pady=2)
            combos.append(combo)

            lower_var = tk.StringVar(
                value="" if seg.get("lower") is None else str(seg["lower"]))
            upper_var = tk.StringVar(
                value="" if seg.get("upper") is None else str(seg["upper"]))

            range_frame = ttk.Frame(grid)
            range_frame.grid(row=i + 1, column=2, pady=2, sticky="w")
            mode = row_modes[i]
            if mode == "lower_only":
                # [下限] < H
                e1 = ttk.Entry(range_frame, textvariable=lower_var, width=8)
                e1.pack(side="left")
                ttk.Label(range_frame, text="< H").pack(side="left", padx=(4, 0))
            elif mode == "both":
                # [下限] < H ≤ [上限]
                e1 = ttk.Entry(range_frame, textvariable=lower_var, width=8)
                e1.pack(side="left")
                ttk.Label(range_frame, text="< H ≤").pack(side="left", padx=(4, 0))
                e2 = ttk.Entry(range_frame, textvariable=upper_var, width=8)
                e2.pack(side="left", padx=(4, 0))
            else:
                # H ≤ [上限]
                ttk.Label(range_frame, text="H ≤").pack(side="left")
                e = ttk.Entry(range_frame, textvariable=upper_var, width=8)
                e.pack(side="left", padx=(4, 0))

            seg_vars.append((mat_var, lower_var, upper_var))

        # 行4：室外管网（管材下拉可用，标高不可用），默认 K9球墨铸铁管
        ttk.Label(grid, text="室外管网", width=8).grid(row=4, column=0, padx=(0, 8), pady=2)
        outdoor_default = cur.get("outdoor_material", "") or ""
        if not outdoor_default and materials:
            k9 = next((m for m in materials if "K9" in m or "铸铁" in m), "")
            outdoor_default = k9
        outdoor_var = tk.StringVar(value=outdoor_default)
        ttk.Combobox(grid, textvariable=outdoor_var, values=materials,
                     state="readonly", width=12).grid(row=4, column=1, padx=(0, 8), pady=2)
        ttk.Label(grid, text="室外管网不参与标高分段", foreground="#999999"
                  ).grid(row=4, column=2, pady=2, sticky="w")

        def build_state():
            """从控件读取当前编辑内容（未保存）"""
            new_segs = []
            for mat_var, lower_var, upper_var in seg_vars:
                lower_s = lower_var.get().strip()
                upper_s = upper_var.get().strip()
                new_segs.append({
                    "material": mat_var.get().strip(),
                    "lower": float(lower_s) if lower_s else None,
                    "upper": float(upper_s) if upper_s else None,
                })
            outdoor = outdoor_var.get().strip()
            return new_segs, outdoor

        def apply_or_restore(new_segs, outdoor):
            """按快照与当前状态对比分派：应用 / 恢复 / 仅保存"""
            cdm = self.cad_data_manager
            if not cdm or not getattr(cdm, "is_loaded", False):
                return
            try:
                if enabled_var.get():
                    count = cdm.apply_elevation_materials(new_segs, outdoor)
                    if count:
                        messagebox.showinfo("标高管材",
                                            f"已按标高管材分段更新 {count} 条管道的管材。\n"
                                            f"请重新进行水力计算以获取新结果。",
                                            parent=dialog)
                elif initial.get("enabled"):
                    count = cdm.restore_uniform_material()
                    if count:
                        messagebox.showinfo("标高管材",
                                            f"已恢复 {count} 条管道为统一管材。\n"
                                            f"请重新进行水力计算以获取新结果。",
                                            parent=dialog)
            except Exception as e:
                logger = __import__("logging").getLogger(__name__)
                logger.error(f"标高管材应用失败: {e}", exc_info=True)
                messagebox.showerror("应用失败", f"标高管材应用失败:\n{e}", parent=dialog)

        def save_and_close():
            try:
                new_segs, outdoor = build_state()
            except ValueError:
                messagebox.showerror("错误", "标高必须是数字或留空", parent=dialog)
                return
            new_enabled = enabled_var.get()
            # 快照与当前对比：内容未变且勾选状态未变 → 仅保存
            changed = (new_enabled != initial.get("enabled")
                       or outdoor != initial.get("outdoor_material")
                       or new_segs != initial.get("segments"))
            cur["enabled"] = new_enabled
            cur["segments"] = new_segs
            cur["outdoor_material"] = outdoor
            if changed:
                apply_or_restore(new_segs, outdoor)
            # 刷新所有页面（管材变化影响表格/预览显示）
            root = self.winfo_toplevel()
            if hasattr(root, "main_app") and changed:
                try:
                    root.main_app.refresh_all_pages()
                except Exception:
                    pass
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=(0, 10))
        ttk.Button(btn_frame, text="确定", command=save_and_close, width=10).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="取消", command=dialog.destroy, width=10).pack(side="left", padx=5)

    def manage_materials(self):
        """管理管材对话框（简化版，只管理基本信息）"""
        dialog = tk.Toplevel(self)
        dialog.title("管材管理")
        dialog.geometry("400x300")
        
        # 居中对话框
        self.center_dialog(dialog)
        
        dialog.transient(self)
        dialog.grab_set()
        
        # 左侧：现有管材列表
        list_frame = ttk.LabelFrame(dialog, text="现有管材")
        list_frame.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        
        # 管材列表
        materials = self.material_manager.get_materials()
        self.material_listbox = tk.Listbox(list_frame)
        self.material_listbox.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.refresh_material_list(dialog)  # 使用刷新方法
        
        # 右侧：操作按钮
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(side="right", fill="y", padx=5, pady=5)
        
        ttk.Button(btn_frame, text="新增", command=lambda: self.add_material_dialog(dialog), 
                width=10).pack(pady=5)
        ttk.Button(btn_frame, text="修改", command=lambda: self.edit_material_dialog(dialog), 
                width=10).pack(pady=5)
        ttk.Button(btn_frame, text="删除", command=lambda: self.delete_material_dialog(dialog), 
                width=10).pack(pady=5)
        ttk.Button(btn_frame, text="关闭", command=dialog.destroy, 
            width=10).pack(pady=20)
    
    def create_material_basic_page(self, parent, parent_dialog):
        """创建管材基本信息页面"""
        # 左侧：现有管材列表
        list_frame = ttk.LabelFrame(parent, text="现有管材")
        list_frame.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        
        # 管材列表
        materials = self.material_manager.get_materials()
        self.material_listbox = tk.Listbox(list_frame)
        self.material_listbox.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.refresh_material_list(parent_dialog)  # 使用刷新方法
        
        # 右侧：操作按钮
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(side="right", fill="y", padx=5, pady=5)
        
        ttk.Button(btn_frame, text="新增", command=lambda: self.add_material_dialog(parent_dialog), 
                width=10).pack(pady=5)
        ttk.Button(btn_frame, text="修改", command=lambda: self.edit_material_dialog(parent_dialog), 
                width=10).pack(pady=5)
        ttk.Button(btn_frame, text="删除", command=lambda: self.delete_material_dialog(parent_dialog), 
                width=10).pack(pady=5)
    
    def create_color_table_page(self, parent, parent_dialog):
        """创建颜色-管径对照表编辑页面"""
        # 选择管材
        select_frame = ttk.Frame(parent)
        select_frame.pack(fill="x", padx=5, pady=5)
        
        ttk.Label(select_frame, text="选择管材:").pack(side="left", padx=5)
        
        self.color_table_material_var = tk.StringVar()
        materials = self.material_manager.get_materials()
        if materials:
            self.color_table_material_var.set(materials[0])
        
        material_combo = ttk.Combobox(
            select_frame,
            textvariable=self.color_table_material_var,
            values=materials,
            state="readonly",
            width=20
        )
        material_combo.pack(side="left", padx=5)
        material_combo.bind("<<ComboboxSelected>>", lambda e: self.load_color_table_for_material(parent))
        
        # 颜色-管径对照表
        table_frame = ttk.LabelFrame(parent, text="颜色-管径对照表")
        table_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # 创建Treeview
        columns = ("颜色", "公称管径", "内径(mm)")
        self.color_table_tree = ttk.Treeview(
            table_frame, 
            columns=columns, 
            show="headings",
            height=15,
            selectmode="browse"
        )
        
        # 设置列标题和宽度
        self.color_table_tree.heading("颜色", text="颜色代码")
        self.color_table_tree.heading("公称管径", text="公称管径")
        self.color_table_tree.heading("内径(mm)", text="内径(mm)")
        
        self.color_table_tree.column("颜色", width=100, anchor="center")
        self.color_table_tree.column("公称管径", width=150, anchor="center")
        self.color_table_tree.column("内径(mm)", width=150, anchor="center")
        
        # 添加滚动条
        tree_scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.color_table_tree.yview)
        self.color_table_tree.configure(yscrollcommand=tree_scrollbar.set)
        
        # 放置Treeview和滚动条
        self.color_table_tree.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)
        tree_scrollbar.pack(side="right", fill="y", padx=(0, 5), pady=5)
        
        # 绑定双击编辑事件
        self.color_table_tree.bind("<Double-1>", lambda e: self.edit_color_table_cell(parent_dialog))
        
        # 操作按钮
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x", padx=5, pady=5)
        
        ttk.Button(btn_frame, text="添加行", command=lambda: self.add_color_table_row(parent_dialog),
                  width=10).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="删除行", command=lambda: self.delete_color_table_row(parent_dialog),
                  width=10).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="保存", command=lambda: self.save_color_table(parent_dialog),
                  width=10).pack(side="right", padx=5)
        
        # 初始加载数据
        if materials:
            self.load_color_table_for_material(parent)
    
    def load_color_table_for_material(self, parent):
        """加载指定管材的颜色-管径对照表"""
        material = self.color_table_material_var.get()
        if not material:
            return
        
        # 清空现有行
        for item in self.color_table_tree.get_children():
            self.color_table_tree.delete(item)
        
        # 从管材管理器获取数据
        color_table = self.material_manager.get_color_diameter_table(material)
        
        if not color_table:
            return
        
        # 按公称管径排序
        def sort_key(item):
            diameter_str = item[1]["nominal"]
            try:
                return int(diameter_str[2:]) if diameter_str.startswith("DN") else 0
            except:
                return 0
        
        sorted_items = sorted(color_table.items(), key=sort_key)
        
        # 添加数据行
        for color, info in sorted_items:
            nominal_diameter = info["nominal"]
            inner_diameter = info["inner"]
            
            self.color_table_tree.insert("", "end", values=(
                color,
                nominal_diameter,
                f"{inner_diameter:.1f}" if inner_diameter > 0 else ""
            ))
    
    def edit_color_table_cell(self, parent_dialog):
        """编辑颜色-管径对照表单元格"""
        selection = self.color_table_tree.selection()
        if not selection:
            return
        
        item_id = selection[0]
        values = list(self.color_table_tree.item(item_id, "values"))
        column = self.color_table_tree.identify_column(self.color_table_tree.winfo_pointerx() - self.color_table_tree.winfo_rootx())
        
        # 确定列索引
        if column == "#1":
            column_index = 0  # 颜色
        elif column == "#2":
            column_index = 1  # 公称管径
        elif column == "#3":
            column_index = 2  # 内径
        else:
            return
        
        # 创建编辑对话框
        dialog = tk.Toplevel(parent_dialog)
        dialog.title("编辑")
        dialog.geometry("300x150")
        
        # 居中对话框
        self.center_dialog(dialog)
        dialog.transient(parent_dialog)
        dialog.grab_set()
        
        current_value = values[column_index]
        column_names = ["颜色代码", "公称管径", "内径(mm)"]
        
        ttk.Label(dialog, text=f"{column_names[column_index]}:").pack(pady=10)
        
        edit_var = tk.StringVar(value=current_value)
        edit_entry = ttk.Entry(dialog, textvariable=edit_var, width=20)
        edit_entry.pack(pady=10)
        edit_entry.focus_set()
        edit_entry.select_range(0, tk.END)
        
        def save_edit():
            new_value = edit_var.get().strip()
            
            # 验证
            if column_index == 2:  # 内径列
                try:
                    float(new_value)
                except ValueError:
                    messagebox.showerror("错误", "内径必须是数字", parent=dialog)
                    return
            
            # 更新Treeview
            values[column_index] = new_value
            self.color_table_tree.item(item_id, values=values)
            
            dialog.destroy()
        
        # 保存按钮
        ttk.Button(dialog, text="保存", command=save_edit, width=10).pack(pady=10)
        
        # 绑定回车键
        dialog.bind('<Return>', lambda e: save_edit())
    
    def add_color_table_row(self, parent_dialog):
        """添加新行到颜色-管径对照表"""
        # 创建添加对话框
        dialog = tk.Toplevel(parent_dialog)
        dialog.title("添加新行")
        dialog.geometry("300x200")
        
        # 居中对话框
        self.center_dialog(dialog)
        dialog.transient(parent_dialog)
        dialog.grab_set()
        
        # 颜色代码
        ttk.Label(dialog, text="颜色代码:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        color_var = tk.StringVar()
        color_entry = ttk.Entry(dialog, textvariable=color_var, width=15)
        color_entry.grid(row=0, column=1, padx=10, pady=10)
        
        # 公称管径
        ttk.Label(dialog, text="公称管径:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        nominal_var = tk.StringVar()
        nominal_entry = ttk.Entry(dialog, textvariable=nominal_var, width=15)
        nominal_entry.grid(row=1, column=1, padx=10, pady=10)
        
        # 内径
        ttk.Label(dialog, text="内径(mm):").grid(row=2, column=0, padx=10, pady=10, sticky="w")
        inner_var = tk.StringVar()
        inner_entry = ttk.Entry(dialog, textvariable=inner_var, width=15)
        inner_entry.grid(row=2, column=1, padx=10, pady=10)
        
        def save_row():
            color = color_var.get().strip()
            nominal = nominal_var.get().strip()
            inner = inner_var.get().strip()
            
            if not color or not nominal or not inner:
                messagebox.showerror("错误", "所有字段都必须填写", parent=dialog)
                return
            
            try:
                inner_value = float(inner)
            except ValueError:
                messagebox.showerror("错误", "内径必须是数字", parent=dialog)
                return
            
            # 添加到Treeview
            self.color_table_tree.insert("", "end", values=(color, nominal, f"{inner_value:.1f}"))
            
            dialog.destroy()
        
        # 保存按钮
        ttk.Button(dialog, text="保存", command=save_row, width=10).grid(row=3, column=0, padx=10, pady=20)
        
        # 取消按钮
        ttk.Button(dialog, text="取消", command=dialog.destroy, width=10).grid(row=3, column=1, padx=10, pady=20)
        
        # 绑定回车键
        dialog.bind('<Return>', lambda e: save_row())
        
        # 将焦点设置到颜色输入框
        color_entry.focus_set()
    
    def delete_color_table_row(self, parent_dialog):
        """删除颜色-管径对照表行"""
        selection = self.color_table_tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请选择要删除的行", parent=parent_dialog)
            return
        
        if messagebox.askyesno("确认删除", "确定要删除选中的行吗？", parent=parent_dialog):
            for item_id in selection:
                self.color_table_tree.delete(item_id)
    
    def save_color_table(self, parent_dialog):
        """保存颜色-管径对照表到materials.json"""
        material = self.color_table_material_var.get()
        if not material:
            messagebox.showerror("错误", "请选择管材", parent=parent_dialog)
            return
        
        # 从Treeview获取所有数据
        color_table = {}
        for item_id in self.color_table_tree.get_children():
            values = self.color_table_tree.item(item_id, "values")
            if len(values) >= 3:
                color = values[0]
                nominal = values[1]
                try:
                    inner = float(values[2])
                except ValueError:
                    inner = 0.0
                
                color_table[color] = {"nominal": nominal, "inner": inner}
        
        # 保存到管材管理器
        self.material_manager.update_color_diameter_table(material, color_table)
        
        messagebox.showinfo("成功", f"管材 '{material}' 的颜色-管径对照表已保存", parent=parent_dialog)
    
    def add_material_dialog(self, parent_dialog):
        """新增管材对话框（简化版，只设置名称和粗糙系数）"""
        dialog = tk.Toplevel(parent_dialog)
        dialog.title("新增管材")
        dialog.geometry("300x150")
        
        # 居中对话框
        self.center_dialog(dialog)
        
        dialog.transient(parent_dialog)
        dialog.grab_set()
        
        # 管材名称
        ttk.Label(dialog, text="管材名称:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        name_entry = ttk.Entry(dialog, width=20)
        name_entry.grid(row=0, column=1, padx=10, pady=10)
        
        # 粗糙系数
        ttk.Label(dialog, text="粗糙系数:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        roughness_entry = ttk.Entry(dialog, width=20)
        roughness_entry.grid(row=1, column=1, padx=10, pady=10)
        roughness_entry.insert(0, "130")
        
        def save_material():
            name = name_entry.get().strip()
            roughness_str = roughness_entry.get().strip()
            
            if not name:
                messagebox.showerror("错误", "管材名称不能为空", parent=dialog)
                return
            
            if name in self.material_manager.get_materials():
                messagebox.showerror("错误", f"管材 '{name}' 已存在", parent=dialog)
                return
            
            try:
                roughness = float(roughness_str)
            except ValueError:
                messagebox.showerror("错误", "粗糙系数必须是数字", parent=dialog)
                return
            
            # 添加新管材，颜色-管径对照表为空，用户可在主界面添加
            self.material_manager.add_material(name, roughness, {})
            
            # 更新所有管材下拉框
            self.update_all_material_combos()
            
            # 更新管材管理对话框中的列表
            self.refresh_material_list(parent_dialog)
            
            # 如果用户当前使用的是这个新管材，更新显示
            if hasattr(self, 'material_combo'):
                self.material_combo['values'] = self.material_manager.get_materials()
            
            # 关闭对话框
            dialog.destroy()
        
        # 保存按钮
        ttk.Button(dialog, text="保存", command=save_material, width=10).grid(row=2, column=0, padx=10, pady=20)
        
        # 取消按钮
        ttk.Button(dialog, text="取消", command=dialog.destroy, width=10).grid(row=2, column=1, padx=10, pady=20)
        
        # 绑定回车键到保存
        dialog.bind('<Return>', lambda e: save_material())
        
        # 将焦点设置到名称输入框
        name_entry.focus_set()

    def refresh_material_list(self, parent_dialog):
        """刷新管材管理对话框中的列表"""
        if hasattr(self, 'material_listbox'):
            # 重新获取管材列表
            materials = self.material_manager.get_materials()
            self.material_listbox.delete(0, tk.END)
            if not materials:
                self.material_listbox.insert(tk.END, "暂无管材，请点击新增")
            else:
                for material in materials:
                    roughness = self.material_manager.get_roughness(material)
                    self.material_listbox.insert(tk.END, f"{material} (C={roughness})")                                                                             

    def edit_material_dialog(self, parent_dialog):
        """修改管材对话框（简化版，只修改名称和粗糙系数）"""
        selection = self.material_listbox.curselection()
        if not selection:
            messagebox.showwarning("警告", "请选择要修改的管材", parent=parent_dialog)
            return

        index = selection[0]
        materials = self.material_manager.get_materials()
        if index >= len(materials):
            return

        material = materials[index]
        current_roughness = self.material_manager.get_roughness(material)

        dialog = tk.Toplevel(parent_dialog)
        dialog.title("修改管材")
        dialog.geometry("250x180")  # 稍微增加高度以容纳提示行
        self.center_dialog(dialog)
        dialog.transient(parent_dialog)
        dialog.grab_set()

        # 管材名称
        ttk.Label(dialog, text="管材名称:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        name_entry = ttk.Entry(dialog, width=20)
        name_entry.grid(row=0, column=1, padx=10, pady=10)
        name_entry.insert(0, material)

        # 粗糙系数
        ttk.Label(dialog, text="粗糙系数:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        roughness_entry = ttk.Entry(dialog, width=20)
        roughness_entry.grid(row=1, column=1, padx=10, pady=10)
        roughness_entry.insert(0, str(current_roughness))

        # 如果是默认管材，插入提示行
        info_row = 2
        if self.material_manager.is_default_material(material):
            info_label = ttk.Label(
                dialog,
                text="这是默认管材，修改仅保存在用户配置中",
                foreground="blue",
                font=("Arial", 9)
            )
            info_label.grid(row=info_row, column=0, columnspan=2, padx=10, pady=5, sticky="w")
            info_row += 1

        # 保存和取消按钮（放在一个框架中，便于居中）
        btn_frame = ttk.Frame(dialog)
        btn_frame.grid(row=info_row, column=0, columnspan=2, pady=20)

        def save_changes():
            new_name = name_entry.get().strip()
            roughness_str = roughness_entry.get().strip()

            if not new_name:
                messagebox.showerror("错误", "管材名称不能为空", parent=dialog)
                return

            try:
                new_roughness = float(roughness_str)
            except ValueError:
                messagebox.showerror("错误", "粗糙系数必须是数字", parent=dialog)
                return

            if new_name != material:
                # 检查新名称是否已存在
                if new_name in self.material_manager.materials:
                    messagebox.showerror("错误", f"管材 '{new_name}' 已存在", parent=dialog)
                    return

                # 获取原管材的颜色-管径对照表
                color_table = self.material_manager.get_color_diameter_table(material)

                # 删除旧管材，添加新管材
                self.material_manager.delete_material(material)
                self.material_manager.add_material(new_name, new_roughness, color_table)

                # 如果当前使用的是这个管材，更新当前配置
                current_material = self.material_var.get()
                if current_material == material:
                    self.material_var.set(new_name)
                    self.on_material_changed()
            else:
                # 只修改粗糙系数
                self.material_manager.update_material(material, roughness=new_roughness)
                self.update_roughness_display()

            # 更新所有管材下拉框
            self.update_all_material_combos()
            # 更新管材管理对话框中的列表
            self.refresh_material_list(parent_dialog)

            dialog.destroy()

        ttk.Button(btn_frame, text="保存", command=save_changes, width=10).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="取消", command=dialog.destroy, width=10).pack(side="left", padx=5)

        # 绑定回车键到保存
        dialog.bind('<Return>', lambda e: save_changes())

        name_entry.focus_set()
        name_entry.select_range(0, tk.END)

    
    def delete_material_dialog(self, parent_dialog):
        """删除管材确认"""
        selection = self.material_listbox.curselection()
        if not selection:
            messagebox.showwarning("警告", "请选择要删除的管材", parent=parent_dialog)
            return
        
        index = selection[0]
        materials = self.material_manager.get_materials()
        
        # 检查索引是否有效
        if index >= len(materials) or index < 0:
            messagebox.showerror("错误", "选择的管材无效", parent=parent_dialog)
            return
        
        material = materials[index]
        
        # 检查是否是当前正在使用的管材
        current_material = self.material_var.get()
        if material == current_material:
            messagebox.showwarning("警告", "不能删除当前正在使用的管材", parent=parent_dialog)
            return
        
        # 检查是否为默认管材（从默认管材文件中读取，而不是硬编码）
        if self.material_manager.is_default_material(material):
            if not messagebox.askyesno("确认删除", 
                                    f"确定要删除默认管材 '{material}' 吗？\n\n"
                                    f"注意：这是默认管材，删除后可能影响其他方案的使用。\n"
                                    f"如需重新添加，可以点击主界面的'恢复默认'按钮。", 
                                    parent=parent_dialog):
                return
        
        if messagebox.askyesno("确认删除", f"确定要删除管材 '{material}' 吗？", parent=parent_dialog):
            try:
                # 删除管材
                self.material_manager.delete_material(material)
                
                # 更新管材管理对话框中的列表
                self.refresh_material_list(parent_dialog)
                
                # 更新所有管材下拉框
                self.update_all_material_combos()
                
            except Exception as e:
                messagebox.showerror("错误", f"删除管材失败: {str(e)}", parent=parent_dialog)

    def center_dialog(self, dialog):
        """将对话框居中到主窗口"""
        dialog.update_idletasks()
        width = dialog.winfo_width()
        height = dialog.winfo_height()
        
        # 获取主窗口位置和大小
        x = self.winfo_rootx() + (self.winfo_width() // 2) - (width // 2)
        y = self.winfo_rooty() + (self.winfo_height() // 2) - (height // 2)
        
        dialog.geometry(f"{width}x{height}+{x}+{y}")

    def _show_auto_dismiss_popup(self, message, duration=3000):
        """在主窗口右下角显示半透明自动消失的提示窗口"""
        root = self.winfo_toplevel()
        root.update_idletasks()
        x = root.winfo_rootx() + root.winfo_width() - 320
        y = root.winfo_rooty() + root.winfo_height() - 100
        popup = tk.Toplevel(root)
        popup.overrideredirect(True)
        popup.geometry(f"300x80+{x}+{y}")
        popup.attributes('-topmost', True)
        popup.attributes('-alpha', 0.9)
        popup.configure(bg='#333333')
        label = tk.Label(popup, text=message, fg='white', bg='#333333',
                         font=('Arial', 10), wraplength=280, justify='left')
        label.pack(expand=True, fill='both', padx=10, pady=10)
        popup.after(duration, popup.destroy)
        
    def on_velocity_changed(self):
        """最高/最低流速修改时验证并保存"""
        try:
            max_v = float(self.max_velocity_var.get())
            min_v = float(self.min_velocity_var.get())
            if max_v < min_v:
                messagebox.showerror("输入错误", "最高流速不能低于最低流速！")
                # 恢复原值
                self.max_velocity_var.set(str(self.current_config.get("max_velocity", 5.0)))
                self.min_velocity_var.set(str(self.current_config.get("min_velocity", 2.0)))
                return
            self.on_config_change("max_velocity", max_v)
            self.on_config_change("min_velocity", min_v)
        except ValueError:
            messagebox.showerror("输入错误", "流速必须为数字")
            self.max_velocity_var.set(str(self.current_config.get("max_velocity", 5.0)))
            self.min_velocity_var.set(str(self.current_config.get("min_velocity", 2.0)))
    
