# pipe_loss_calculator/gui/settings_page.py
import os
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
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

        # 当前内存中的配置（不自动保存到方案）
        self.current_config = {}
        
        # 创建滚动容器
        self.create_scrollable_container()
        
        # 加载当前方案配置到内存
        self.load_current_config()
        
        # 创建所有控件
        self.create_widgets()
        
        # 绑定方案切换事件
        self.bind_events()
        
        # 初始加载数据
        self.update_all_widgets()

        # ✅ 在所有控件创建完成后绑定滚轮事件
        self.bind_mouse_wheel()

    def load_current_config(self):
        """从当前方案加载配置到内存（使用深拷贝确保独立）"""
        scheme_config = self.config_manager.get_current_config()
        # 使用深拷贝确保每个方案的配置完全独立
        self.current_config = copy.deepcopy(scheme_config)
    
    def save_current_config(self):
        """保存当前内存配置到当前方案"""
        self.config_manager.update_current_config(self.current_config)

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
        # 方案管理区域
        scheme_frame = ttk.LabelFrame(parent, text="方案管理")
        scheme_frame.pack(fill="x", padx=5, pady=(0, 10))
        
        ttk.Label(scheme_frame, text="当前方案:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        
        # 方案下拉框（不显示临时方案）
        self.scheme_combo = ttk.Combobox(
            scheme_frame,
            values=self.config_manager.get_visible_schemes(),
            state="readonly",
            width=20
        )
        self.scheme_combo.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        
        # 保存按钮
        ttk.Button(
            scheme_frame,
            text="保存",
            command=self.save_as_new_scheme,
            width=6
        ).grid(row=0, column=2, padx=2, pady=5)
        
        # 更新按钮
        ttk.Button(
            scheme_frame,
            text="更新",
            command=self.update_current_scheme,
            width=6
        ).grid(row=0, column=3, padx=2, pady=5)
        
        # 删除按钮
        ttk.Button(
            scheme_frame,
            text="删除",
            command=self.delete_current_scheme,
            width=6
        ).grid(row=0, column=4, padx=2, pady=5)
        
        scheme_frame.grid_columnconfigure(1, weight=1)
        
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
        
        # 预处理复选框（放在左侧）
        self.preprocess_var = tk.BooleanVar(value=self.current_config.get("preprocess_cad", False))
        preprocess_check = ttk.Checkbutton(
            row2,
            text="预处理",
            variable=self.preprocess_var,
            command=lambda: self.on_config_change("preprocess_cad", self.preprocess_var.get())
        )
        preprocess_check.pack(side="left", padx=(0, 10))
        
        # 读取按钮
        self.load_button = ttk.Button(
            row2,
            text="读取文件",
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
        
        # 第三行：局部水损比例和管网类型选择（同一行）
        row3 = ttk.Frame(cad_frame)
        row3.pack(fill="x", padx=10, pady=(0, 5))
        
        # 局部水损比例
        ttk.Label(row3, text="局部水损比例:").pack(side="left", padx=(0,5))
        self.local_loss_ratio_var = tk.StringVar(value=str(self.current_config.get("local_loss_ratio", 0.3)))
        local_loss_entry = ttk.Entry(row3, textvariable=self.local_loss_ratio_var, width=6)
        local_loss_entry.pack(side="left", padx=(0,10))
        local_loss_entry.bind("<FocusOut>", lambda e: self.on_config_change("local_loss_ratio", float(self.local_loss_ratio_var.get())))
        
        # 管网类型
        ttk.Label(row3, text="管网类型:").pack(side="left", padx=(10,5))
        self.system_type_var = tk.StringVar(value=self.current_config.get("system_type", "outdoor_hydrant"))
        # 室外消火栓
        ttk.Radiobutton(row3, text="室外消火栓", variable=self.system_type_var,
                        value="outdoor_hydrant", command=self.on_system_type_changed).pack(side="left", padx=5)
        # 室内消火栓
        ttk.Radiobutton(row3, text="室内消火栓", variable=self.system_type_var,
                        value="indoor_hydrant", command=self.on_system_type_changed).pack(side="left", padx=5)
        # 喷淋
        ttk.Radiobutton(row3, text="喷淋", variable=self.system_type_var,
                        value="sprinkler", command=self.on_system_type_changed).pack(side="left", padx=5)
      
        # 多图层管理（横管、立管、立管标注）
        def on_pipe_layers(layers):
            self.on_config_change("pipe_layers", layers)
        def on_riser_layers(layers):
            self.on_config_change("riser_layers", layers)
        def on_riser_note_layers(layers):
            self.on_config_change("riser_note_layers", layers)

        self.multi_layer_manager = MultiLayerManager(
            parent,
            self.config_manager,
            callbacks={
                'pipe': on_pipe_layers,
                'riser': on_riser_layers,
                'riser_note': on_riser_note_layers
            }
        )
        self.multi_layer_manager.pack(fill="x", padx=5, pady=(0, 10))

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
        # 管理按钮
        manage_btn = ttk.Button(unit_col5, text="管理", command=self.manage_materials, width=8)
        manage_btn.pack(anchor="w", pady=(0, 5))
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
        
        # 图块设置区域
        block_frame = ttk.LabelFrame(parent, text="图块设置")
        block_frame.pack(fill="x", padx=5, pady=(0, 10))

        # 创建一个网格布局，3列（阀门+消火栓、对齐点、喷头）
        block_row = ttk.Frame(block_frame)
        block_row.pack(fill="x", padx=5, pady=5)
        for i in range(3):
            block_row.columnconfigure(i, weight=1)

        # 阀门图块列
        valve_col = ttk.Frame(block_row)
        valve_col.grid(row=0, column=0, padx=5, sticky="nsew")
        valve_row1 = ttk.Frame(valve_col)
        valve_row1.pack(anchor="w", pady=(0, 2), fill="x")
        ttk.Label(valve_row1, text="阀门块名:").pack(side="left")
        self.valve_block_var = tk.StringVar(value=self.current_config.get("valve_block_name", "valve"))
        valve_entry = ttk.Entry(valve_row1, textvariable=self.valve_block_var)
        valve_entry.pack(side="left", padx=(5, 0), fill="x", expand=True)
        valve_entry.bind("<FocusOut>",
                         lambda e: self.on_config_change("valve_block_name", self.valve_block_var.get()))
        valve_row2 = ttk.Frame(valve_col)
        valve_row2.pack(anchor="w", pady=(0, 2), fill="x")
        ttk.Label(valve_row2, text="消火栓名:").pack(side="left")
        self.hydrant_block_var = tk.StringVar(value=self.current_config.get("hydrant_block_name", "hydrant"))
        hydrant_entry = ttk.Entry(valve_row2, textvariable=self.hydrant_block_var)
        hydrant_entry.pack(side="left", padx=(5, 0), fill="x", expand=True)
        hydrant_entry.bind("<FocusOut>",
                        lambda e: self.on_config_change("hydrant_block_name", self.hydrant_block_var.get()))

        # 对齐点图块列
        align_col = ttk.Frame(block_row)
        align_col.grid(row=0, column=1, padx=5, sticky="nsew")
        align_row1 = ttk.Frame(align_col)
        align_row1.pack(anchor="w", pady=(0, 2), fill="x")
        ttk.Label(align_row1, text="对齐点块:").pack(side="left")
        self.align_block_var = tk.StringVar(value=self.current_config.get("align_block_name", "Floorbase"))
        align_entry = ttk.Entry(align_row1, textvariable=self.align_block_var)
        align_entry.pack(side="left", padx=(5, 0), fill="x", expand=True)
        align_entry.bind("<FocusOut>",
                         lambda e: self.on_config_change("align_block_name", self.align_block_var.get()))
        align_row2 = ttk.Frame(align_col)
        align_row2.pack(anchor="w", pady=(0, 2), fill="x")
        ttk.Label(align_row2, text="属性字段:").pack(side="left")
        self.align_attr_var = tk.StringVar(value=self.current_config.get("align_attribute_name", "Elevation"))
        align_attr_entry = ttk.Entry(align_row2, textvariable=self.align_attr_var)
        align_attr_entry.pack(side="left", padx=(5, 0), fill="x", expand=True)
        align_attr_entry.bind("<FocusOut>",
                              lambda e: self.on_config_change("align_attribute_name", self.align_attr_var.get()))

        # 喷头图块列
        sprinkler_col = ttk.Frame(block_row)
        sprinkler_col.grid(row=0, column=2, padx=5, sticky="nsew")
        s_row1 = ttk.Frame(sprinkler_col)
        s_row1.pack(anchor="w", pady=(0, 2), fill="x")
        ttk.Label(s_row1, text="喷头块名:").pack(side="left")
        self.sprinkler_block_var = tk.StringVar(value=self.current_config.get("sprinkler_block_name", ""))
        sprinkler_entry = ttk.Entry(s_row1, textvariable=self.sprinkler_block_var)
        sprinkler_entry.pack(side="left", padx=(5, 0), fill="x", expand=True)
        sprinkler_entry.bind("<FocusOut>",
                             lambda e: self.on_config_change("sprinkler_block_name", self.sprinkler_block_var.get()))


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
        self.min_velocity_var = tk.StringVar(value=str(self.current_config.get("min_velocity", 1.0)))
        
        # 喷头K输入框改为Combobox，可输入可选择
        k_combo = ttk.Combobox(param_frame, textvariable=self.k_var, values=[80, 115, 161, 200, 202, 242, 320, 363], width=8, state='normal')
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
                         (self.hak_var, "hydrant_Hak")]:
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
        
    def bind_events(self):
        """绑定事件"""
        self.scheme_combo.bind("<<ComboboxSelected>>", self.on_scheme_changed)
    
    def on_config_change(self, key: str, value):
        """配置发生变化时更新内存配置"""
        self.current_config[key] = value
        # 同步到config_manager的live_config
        self.config_manager.set_live_config(self.current_config)
        # 如果更改的是单位，通知所有页面
        if key in ['flow_unit', 'pressure_unit']:
            root = self.winfo_toplevel()
            if hasattr(root, 'main_app'):
                root.main_app.notify_units_changed()
    
    def on_material_changed(self):
        """管材类型变化处理"""
        material = self.material_var.get()
        old_material = self.current_config.get("pipe_material")
        self.on_config_change("pipe_material", material)
        self.color_table.set_material(material)
        self.update_all_material_combos()
        # 如果管材改变了，并且已有CAD数据加载，则更新所有管道的材料
        if material != old_material and self.cad_data_manager.is_loaded:
            self.cad_data_manager.update_all_pipes_material(material)
            # 刷新各页面
            root = self.winfo_toplevel()
            if hasattr(root, 'main_app'):
                root.main_app.refresh_all_pages()
    
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
            filetypes=[("CAD Files", "*.dwg"), ("All files", "*.*")]
        )
        if file_path:
            self.cad_file_var.set(file_path)
            # 只保存路径，不立即加载
            self.config_manager.update_global_setting("last_cad_file", file_path)
            self.loading_status_var.set("已选择文件，点击'读取CAD数据'按钮开始读取")
    
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
        
        # 禁用按钮，防止重复点击
        self.is_loading_cad = True
        self.load_button.config(state=tk.DISABLED)
        self.loading_status_var.set("正在读取CAD文件...")
        self.update_idletasks()  # 强制更新UI
        
        # 在新线程中读取
        import threading
        
        def load_cad_thread():
            try:
                # 定义进度回调，通过 after 更新UI
                def progress_callback(message):
                    self.after(0, lambda: self.loading_status_var.set(message))
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
                    
                    # 在主线程中更新UI
                    self.after(0, lambda: self.show_load_result(
                        True, 
                        f"成功读取 {pipes_count} 条管道，{nodes_count} 个节点"
                    ))
                else:
                    self.after(0, lambda: self.show_load_result(False, "CAD文件读取失败"))
                
            except Exception as e:
                error_msg = str(e)
                self.after(0, lambda: self.show_load_result(False, f"读取出错: {error_msg}"))
        
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
            root.main_app.reset_calculation_and_preview()
            if '供水点和用水点' in root.main_app.pages:
                root.main_app.pages['供水点和用水点'].refresh_data()
            if '管网预览' in root.main_app.pages:
                root.main_app.pages['管网预览'].refresh_data()
        else:
            self.loading_status_var.set(f"✗ {message}")
            self.load_status_label.config(foreground="red")
     


    def on_scheme_changed(self, event=None):
        """方案选择变化"""
        scheme_name = self.scheme_combo.get()
        if scheme_name in self.config_manager.get_visible_schemes():
            # 重要：这里不再保存到临时方案！
            # 直接切换方案
            self.config_manager.set_current_scheme(scheme_name)
            
            # 重新加载配置
            self.load_current_config()
            
            # 更新所有控件
            self.update_all_widgets()
            
            # 更新方案下拉框
            self.scheme_combo.set(scheme_name)
    
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
        self.valve_block_var.set(self.current_config.get("valve_block_name", "valve"))
        self.align_block_var.set(self.current_config.get("align_block_name", "Floorbase"))
        self.align_attr_var.set(self.current_config.get("align_attribute_name", "Elevation"))
        self.sprinkler_block_var.set(self.current_config.get("sprinkler_block_name", ""))

        
        # 更新计算设置
        self.tolerance_var.set(str(self.current_config.get("tolerance", 10.0)))
        self.local_loss_ratio_var.set(str(self.current_config.get("local_loss_ratio", 0.3)))
        
        # 更新颜色管径对照表
        self.color_table.set_material(material)
        self.preprocess_var.set(self.current_config.get("preprocess_cad", False))
        
        # 更新新增的配置
        self.hydrant_block_var.set(self.current_config.get("hydrant_block_name", "hydrant"))
        self.max_velocity_var.set(str(self.current_config.get("max_velocity", 5.0)))
        self.min_velocity_var.set(str(self.current_config.get("min_velocity", 1.0)))
        self.system_type_var.set(self.current_config.get("system_type", "outdoor_hydrant"))
        

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

    def update_current_scheme(self):
        """更新当前方案"""
        # 获取当前输入框中的图层
        current_layers = self.layer_manager.get_current_layers()
        if current_layers:
            self.on_config_change("pipe_layers", current_layers)
        
        # 获取方案名称
        scheme_name = self.scheme_combo.get()
        
        try:
            # 保存到当前方案（使用深拷贝）
            self.config_manager.update_current_config(copy.deepcopy(self.current_config))
            # 可选：显示成功消息
            # messagebox.showinfo("成功", f"方案 '{scheme_name}' 已更新")
        except Exception as e:
            messagebox.showerror("错误", str(e))
    
    def save_as_new_scheme(self):
        """保存为新方案"""
        # 获取当前输入框中的图层
        current_layers = self.layer_manager.get_current_layers()
        if current_layers:
            self.on_config_change("pipe_layers", current_layers)
        
        # 获取新方案名称
        scheme_name = simpledialog.askstring("新方案", "请输入新方案名称:")
        
        if scheme_name and scheme_name.strip():
            scheme_name = scheme_name.strip()
            
            try:
                # 添加新方案（使用深拷贝）
                self.config_manager.add_scheme(scheme_name, copy.deepcopy(self.current_config))
                
                # 更新方案下拉框
                self.scheme_combo['values'] = self.config_manager.get_visible_schemes()
                self.scheme_combo.set(scheme_name)
                
                # 可选：显示成功消息
                # messagebox.showinfo("成功", f"方案 '{scheme_name}' 已保存")
            except ValueError as e:
                messagebox.showerror("错误", str(e))
    
    def delete_current_scheme(self):
        """删除当前方案"""
        scheme_name = self.scheme_combo.get()
        
        if scheme_name == "默认方案":
            messagebox.showwarning("警告", "不能删除默认方案")
            return
        
        if messagebox.askyesno("确认删除", f"确定要删除方案 '{scheme_name}' 吗？"):
            self.config_manager.delete_scheme(scheme_name)
            
            # 更新方案下拉框
            self.scheme_combo['values'] = self.config_manager.get_visible_schemes()
            
            # 切换到默认方案
            self.scheme_combo.set("默认方案")
            self.on_scheme_changed()
    
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
                self.min_velocity_var.set(str(self.current_config.get("min_velocity", 1.0)))
                return
            self.on_config_change("max_velocity", max_v)
            self.on_config_change("min_velocity", min_v)
        except ValueError:
            messagebox.showerror("输入错误", "流速必须为数字")
            self.max_velocity_var.set(str(self.current_config.get("max_velocity", 5.0)))
            self.min_velocity_var.set(str(self.current_config.get("min_velocity", 1.0)))
    
    def on_system_type_changed(self):
        """系统类型变化时保存配置"""
        self.on_config_change("system_type", self.system_type_var.get())