"""
管网预览页面（完全实现 - 修正版）
"""
import tkinter as tk
import json
import os
import sys
import shutil
from tkinter import ttk, simpledialog, messagebox
import math
import logging
from typing import List, Dict, Tuple, Optional, Set
from collections import defaultdict, deque
from cad_data_manager import HydrantData, ValveData, DemandGroupData, DemandNodeData, PipeData, NodeData, SupplyNodeData
# from tkinter import messagebox

logger = logging.getLogger(__name__)

def _get_exe_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(__file__))

class MaintenanceZone:
    """检修区数据类"""
    def __init__(self, zone_id, pipe_ids, valve_ids, node_ids):
        self.zone_id = zone_id
        self.pipe_ids = pipe_ids
        self.valve_ids = valve_ids
        self.node_ids = node_ids

class LayerColorDialog:
    """分层颜色编辑对话框"""
    def __init__(self, parent, preview_page):
        self.parent = parent
        self.preview = preview_page
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("分层颜色表")
        self.dialog.geometry("500x500")
        self.dialog.transient(parent)
        # self.dialog.grab_set()

        # 将对话框居中于主窗口
        self.dialog.update_idletasks()
        parent = self.parent
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        w = self.dialog.winfo_width()
        h = self.dialog.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self.dialog.geometry(f"+{x}+{y}")

        # 启用复选框
        self.enable_var = self.preview.layer_colors_enabled  # 直接引用，实时同步
        enable_frame = ttk.Frame(self.dialog)
        enable_frame.pack(fill="x", padx=10, pady=5)
        self.enable_cb = ttk.Checkbutton(enable_frame, text="启用", variable=self.enable_var,
                                         command=self.on_enable_changed)
        self.enable_cb.pack(side="left")
        
        # 颜色表格
        self.create_table()
        
        # 绑定事件，确保实时保存
        self.dialog.protocol("WM_DELETE_WINDOW", self.on_close)
        
    def create_table(self):
        """创建颜色表格"""
        columns = ("颜色名称", "R", "G", "B", "楼层名")
        self.tree = ttk.Treeview(self.dialog, columns=columns, show="headings", height=15)
        self.tree.heading("颜色名称", text="颜色名称")
        self.tree.heading("R", text="R")
        self.tree.heading("G", text="G")
        self.tree.heading("B", text="B")
        self.tree.heading("楼层名", text="楼层名")
        self.tree.column("颜色名称", width=60)
        self.tree.column("R", width=30)
        self.tree.column("G", width=30)
        self.tree.column("B", width=30)
        self.tree.column("楼层名", width=150)
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 右键菜单
        self.context_menu = tk.Menu(self.tree, tearoff=0)
        self.context_menu.add_command(label="新增行", command=self.append_new_row)
        self.context_menu.add_command(label="删除行", command=self.delete_row)
        self.tree.bind("<Button-3>", self.show_context_menu)
        
        # 双击编辑
        self.tree.bind("<Double-1>", self.on_double_click)

        # 拖拽排序
        self.drag_item = None
        self.last_target = None
        self.tree.bind("<Button-1>", self.on_drag_start)
        self.tree.bind("<B1-Motion>", self.on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self.on_drag_end)
        self.tree.bind("<Leave>", self.on_drag_leave)

        # 加载数据
        self.refresh_table()

    # 整个拖拽相关的方法
    def on_drag_start(self, event):
        self.drag_item = self.tree.identify_row(event.y)
    
    def on_drag_motion(self, event):
        if not self.drag_item:
            return
        # 恢复上一个目标行的颜色（保留背景色标签）
        if hasattr(self, 'last_target') and self.last_target:
            self.tree.tag_configure("drag_target", foreground="")
            tags = self.tree.item(self.last_target, "tags") or ()
            cleaned = tuple(t for t in tags if t != "drag_target")
            self.tree.item(self.last_target, tags=cleaned)
        # 获取当前目标行
        target = self.tree.identify_row(event.y)
        if target and target != self.drag_item:
            self.last_target = target
            self.tree.tag_configure("drag_target", foreground="red")
            tags = self.tree.item(target, "tags") or ()
            new_tags = tuple(t for t in tags if t != "drag_target") + ("drag_target",)
            self.tree.item(target, tags=new_tags)
        else:
            self.last_target = None
    
    def on_drag_end(self, event):
        if not self.drag_item or not hasattr(self, 'last_target') or not self.last_target:
            self.drag_item = None
            self.last_target = None
            return
        drag_idx = self.tree.index(self.drag_item)
        target_idx = self.tree.index(self.last_target)
        # 先清除高亮（保留背景色标签）
        if self.last_target:
            self.tree.tag_configure("drag_target", foreground="")
            tags = self.tree.item(self.last_target, "tags") or ()
            cleaned = tuple(t for t in tags if t != "drag_target")
            self.tree.item(self.last_target, tags=cleaned)
        if drag_idx != target_idx:
            color_list = self.preview.layer_color_list
            color_list[drag_idx], color_list[target_idx] = color_list[target_idx], color_list[drag_idx]
            self.preview.save_floor_colors()
            self.preview.update_floor_color_map()
            self.preview.redraw()
            self.refresh_table()
        self.drag_item = None
        self.last_target = None

    def on_drag_leave(self, event):
        if hasattr(self, 'last_target') and self.last_target:
            self.tree.tag_configure("drag_target", foreground="")
            tags = self.tree.item(self.last_target, "tags") or ()
            cleaned = tuple(t for t in tags if t != "drag_target")
            self.tree.item(self.last_target, tags=cleaned)
            self.last_target = None

    def refresh_table(self):
        """刷新表格数据，并更新背景色"""
        self.tree.delete(*self.tree.get_children())
        # 获取楼层分配信息（按标高升序排列）
        sorted_floors = sorted(self.preview.cad_data_manager.floors, key=lambda f: f.elevation)
        num_floors = len(sorted_floors)
        num_colors = len(self.preview.layer_color_list)
        # 构建楼层到颜色索引的映射
        floor_to_color_idx = {}
        for idx, floor in enumerate(sorted_floors):
            if num_colors > 0:
                color_idx = idx % num_colors
                floor_to_color_idx[floor.name] = color_idx
        
        # 显示每个颜色行，并在楼层名列显示使用了该颜色的楼层列表
        for color_idx, color in enumerate(self.preview.layer_color_list):
            # 找出使用了该颜色的楼层
            used_floors = [floor.name for floor in sorted_floors if floor_to_color_idx.get(floor.name) == color_idx]
            floor_str = "、".join(used_floors)
            item = self.tree.insert("", "end", values=(
                color["name"],
                color["r"],
                color["g"],
                color["b"],
                floor_str
            ))
            # 设置行背景色
            bg_hex = color["hex"]
            self.tree.tag_configure(f"bg_{color_idx}", background=bg_hex)
            self.tree.item(item, tags=(f"bg_{color_idx}",))
            
    def on_double_click(self, event):
        """双击单元格编辑"""
        item = self.tree.selection()[0]
        column = self.tree.identify_column(event.x)
        col_index = int(column.replace('#', '')) - 1
        if col_index == 4:  # 楼层名列不可编辑
            return
        x, y, width, height = self.tree.bbox(item, column)
        value = self.tree.item(item, "values")[col_index]
        entry = ttk.Entry(self.tree)
        entry.place(x=x, y=y, width=width, height=height)
        entry.insert(0, value)
        entry.focus()
        
        def save_edit(e=None):
            new_value = entry.get().strip()
            # 获取当前行的颜色对象索引
            item_values = self.tree.item(item, "values")
            color_idx = self._get_color_index_by_values(item_values)
            if color_idx is None:
                entry.destroy()
                return
            if col_index == 0:  # 颜色名称
                # 检查重名
                if any(c["name"] == new_value for idx, c in enumerate(self.preview.layer_color_list) if idx != color_idx):
                    messagebox.showerror("错误", "颜色名称已存在", parent=self.dialog)
                    entry.destroy()
                    return
                self.preview.layer_color_list[color_idx]["name"] = new_value
            elif col_index in (1, 2, 3):  # RGB
                try:
                    val = int(new_value)
                    if val < 0 or val > 255:
                        raise ValueError
                except:
                    messagebox.showerror("错误", "RGB值必须为0-255的整数", parent=self.dialog)
                    entry.destroy()
                    return
                if col_index == 1:
                    self.preview.layer_color_list[color_idx]["r"] = val
                elif col_index == 2:
                    self.preview.layer_color_list[color_idx]["g"] = val
                elif col_index == 3:
                    self.preview.layer_color_list[color_idx]["b"] = val
                # 更新十六进制
                c = self.preview.layer_color_list[color_idx]
                hex_val = f"#{c['r']:02x}{c['g']:02x}{c['b']:02x}".upper()
                self.preview.layer_color_list[color_idx]["hex"] = hex_val
            # 保存到文件
            self.preview.save_floor_colors()
            # 更新楼层颜色映射并重绘预览
            self.preview.update_floor_color_map()
            self.preview.redraw()
            # 刷新表格
            self.refresh_table()
            entry.destroy()
            
        entry.bind("<Return>", save_edit)
        entry.bind("<FocusOut>", save_edit)
        
    def _get_color_index_by_values(self, values):
        """根据表格行的值查找颜色索引"""
        name = values[0]
        r = int(values[1])
        g = int(values[2])
        b = int(values[3])
        for idx, c in enumerate(self.preview.layer_color_list):
            if c["name"] == name and c["r"] == r and c["g"] == g and c["b"] == b:
                return idx
        return None
        
    def show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()
            
    def append_new_row(self):
        """在末尾添加新行"""
        self._insert_row_at(len(self.preview.layer_color_list))

    def _insert_row_at(self, position):
        """在指定位置插入新行（position 为颜色列表中的索引）"""
        # 限制 position 范围
        if position < 0:
            position = 0
        if position > len(self.preview.layer_color_list):
            position = len(self.preview.layer_color_list)
    
        new_name = "新颜色1"
        base = new_name
        counter = 1
        while any(c["name"] == new_name for c in self.preview.layer_color_list):
            new_name = f"{base}{counter}"
            counter += 1
        new_color = {
            "name": new_name,
            "r": 255, "g": 255, "b": 255,
            "hex": "#FFFFFF"
        }
        self.preview.layer_color_list.insert(position, new_color)
        self.preview.save_floor_colors()
        self.preview.update_floor_color_map()
        self.preview.redraw()
        self.refresh_table()
        # 尝试选中新插入的行（新行在位置 position）
        for child in self.tree.get_children():
            if self.tree.index(child) == position:
                self.tree.selection_set(child)
                self.tree.see(child)
                break

    def delete_row(self):
        selected = self.tree.selection()
        if not selected:
            return
        item = selected[0]
        values = self.tree.item(item, "values")
        idx = self._get_color_index_by_values(values)
        if idx is not None:
            if len(self.preview.layer_color_list) == 1:
                messagebox.showwarning("警告", "至少需要保留一种颜色", parent=self.dialog)
                return
            del self.preview.layer_color_list[idx]
            self.preview.save_floor_colors()
            self.preview.update_floor_color_map()
            self.preview.redraw()
            self.refresh_table()
            
    def on_enable_changed(self):
        """启用复选框变化时，更新预览画布"""
        self.preview.redraw()
        
    def on_close(self):
        self.dialog.destroy()
        self.preview.color_dialog = None


class PreviewPage(ttk.Frame):
    """管网预览页面 - 实现2D/3D渲染、交互、实时更新"""

    VIEWS = {
        "俯视":     {"type": "ortho", "up": (0,1,0), "eye": (0,0,1), "target": (0,0,0)},
        "东南等轴测": {"type": "isometric", "angle": (45, 35.264)},
        "东北等轴测": {"type": "isometric", "angle": (135, 35.264)},
        "西南等轴测": {"type": "isometric", "angle": (225, 35.264)},
        "西北等轴测": {"type": "isometric", "angle": (315, 35.264)},
    }

    # 颜色定义
    COLOR_PIPE_ACTIVE = "#00BFFF"
    COLOR_PIPE_INACTIVE = "#808080"
    COLOR_PIPE_HIGHLIGHT = "#FF0000"
    COLOR_PIPE_VELOCITY_NORMAL = "#ADD8E6"   # 校正/优化模式下，流速正常管道淡蓝色
    COLOR_PIPE_ZERO_FLOW = "#808080"          # 校正/优化模式下，零流量管道深灰色
    COLOR_NODE = "#FFFFFF"
    COLOR_NODE_HIGHLIGHT = "#FF0000"
    COLOR_VALVE = "#00FF00"
    COLOR_VALVE_CLOSED = "#FF0000"       # 关闭阀门红色
    COLOR_VALVE_SELECTED = "#FFFF00"
    COLOR_SELECTED_PIPE = "#FFFF00"
    COLOR_SUPPLY = "#0000FF"             # 供水点蓝色方块
    COLOR_DEMAND_OFF = "#888888"         # 关闭用水点灰色
    COLOR_DEMAND_ON = "#00FF00"          # 开启用水点绿色

    TEXT_MIN_SIZE = 10
    TEXT_MAX_SIZE = 100

    def __init__(self, parent, config_manager, material_manager, cad_data_manager):
        super().__init__(parent)
        self.config_manager = config_manager
        self.material_manager = material_manager
        self.cad_data_manager = cad_data_manager

        # 图形状态
        self.scale = 1.0
        self.translate_x = 0
        self.translate_y = 0
        self.drag_start = None
        self.current_view = "俯视"

        # ===== 新增：整体管网相关属性 =====
        self.current_view_mode = "floor"          # "floor" 或 "global"
        self.global_view_angle = 45.0             # 等轴测方位角（度），初始东南
        # 内部表示：视线与垂直方向夹角（0=俯视，90=水平）
        self.global_view_elevation = 54.736       # 对应用户高度角 35.264°
        # UI显示：用户高度角（与水平面夹角）
        self.global_view_elevation_var = tk.StringVar(value="35.264")
        self.compass_radius = 40                  # 罗盘半径（像素）
        self.compass_center_x = 60                # 罗盘圆心 X（画布坐标）
        self.compass_center_y = 60                # 罗盘圆心 Y

        # 显示选项
        self.show_nominal = tk.BooleanVar(value=True)
        self.show_length = tk.BooleanVar(value=False)
        self.show_flow = tk.BooleanVar(value=False)
        self.show_velocity = tk.BooleanVar(value=False)
        self.show_loss = tk.BooleanVar(value=False)
        self.show_arrow = tk.BooleanVar(value=False)
        self.show_node_ids = tk.BooleanVar(value=False)
        self.real_time = tk.BooleanVar(value=True)
        self._skip_z_recalc = False   # 用户手动修改标高时跳过自动计算
        self.show_pipe_id = tk.BooleanVar(value=False)
        self.show_elevation = tk.BooleanVar(value=False)  # 横管标高，缺省不勾选
        
        # 显示前后遮挡（新增）
        self.show_occlusion_var = tk.BooleanVar(value=True)  # 缺省打开
        self.occlusion_cache_valid = False                   # 遮挡缓存是否有效
        self.occlusion_breaks = {}                           # 遮挡断点缓存 {pipe_id: List[t]}
        self.projected_depth = {}                            # 节点深度缓存 {node_id: float}
        
        self.duplicate_risers_by_floor = {}        # 从 CADDataManager 获取的重复立管字典（仅用于标记）
        self.show_riser_warning = tk.BooleanVar(value=True)   # 是否显示立管重复警告标记，默认勾选
        
        # 计算结果缓存
        self.pipe_results: Dict[str, Dict] = {}
        self.calculation_available = False
        self.velocity_check_var = tk.BooleanVar(value=False)   # 校正或优化管径模式
        self.velocity_max = 5.0                                 # 最高流速阈值
        self.velocity_min = 1.0                                 # 最低流速阈值
        
        # 节点压力缓存
        self.node_pressures: Dict[str, float] = {}
        self.show_node_pressure = tk.BooleanVar(value=False)  # 节点压力显示开关
        
        # 消火栓支管向左展开（仅整体管网）
        self.hydrant_branch_flat_var = tk.BooleanVar(value=False)

        # 节点流量缓存（从 calculation_module 传入）
        self.node_flows: Dict[str, float] = {}

        # Alt 悬停信息框
        self.alt_pressed = False
        self._hover_tooltip_id = None
        self._hover_tooltip_win = None
        self._hover_info = None          # (info_type, lines)
        self._hover_canvas_pos = None    # (canvasx, canvasy)
        self._hover_screen_pos = None    # (root_x, root_y)        
        self._pending_jump = None         # 待执行的跳转缩放 (type, entity_id, extra)
        
        # 高亮数据
        self.highlight_path_pipes: Set[str] = set()
        self.highlight_path_nodes: Set[str] = set()

        # 选择状态
        self.selected_pipe_id: Optional[str] = None
        self.selected_valve_id: Optional[str] = None

        # 投影坐标缓存（世界坐标，单位毫米）
        self.projected_coords: Dict[str, Tuple[float, float]] = {}

        # 连通性缓存
        self.reachable_pipes: Set[str] = set()

        # Alt 悬停信息框的全局键绑定
        self.bind("<KeyPress-Alt_L>", self._on_alt_press)
        self.bind("<KeyPress-Alt_R>", self._on_alt_press)
        self.bind("<KeyRelease-Alt_L>", self._on_alt_release)
        self.bind("<KeyRelease-Alt_R>", self._on_alt_release)

        # 创建界面
        self.create_widgets()
        self.update_projection()
        self.compute_reachability()
        self.auto_center()
        self.redraw()
        
        # ===== 分层颜色相关属性 =====
        self.layer_colors_enabled = tk.BooleanVar(value=False)  # 是否启用分层颜色，缺省不勾选
        self.layer_color_list = []      # 颜色列表，每个元素: {"name": str, "r": int, "g": int, "b": int, "hex": str}
        self.floor_color_map = {}       # 楼层名 -> 颜色十六进制字符串 (如 "#FFB3B3")
        self.pipe_floor_map = {}        # 管道ID -> 楼层名（用于快速获取管道所属楼层）
        self.color_dialog = None        # 分层颜色对话框实例
        self.load_floor_colors()        # 加载颜色配置文件
        self.update_floor_color_map()   # 初始化楼层颜色映射

        # 选择集相关
        self.selected_pipes: Set[str] = set()
        self.selection_rect = None          # 框选矩形ID
        self.selection_start = None         # 框选起点（画布坐标）
        self.selection_mode = False         # 是否处于框选模式
        self.problem_pipes: Set[str] = set()  # 问题管道ID集合（由CADDataManager验证得到）

        # 楼层相关
        self.floor_notebook = None          # 楼层标签页控件
        self.floor_canvases = {}            # 每个楼层的画布
        self.current_floor_name = None      # 当前显示的楼层名
        self._current_canvas = None         # 当前活动的画布对象

        # 每个楼层的独立视图状态（用于切换时恢复）
        self.floor_view_state: Dict[str, Tuple[float, float, float]] = {}
        
        # 缓存分组映射，用于判断是否需要重建标签页
        self._cached_grouped_floors_map = {}        

        # 消火栓数据引用
        self.hydrants = self.cad_data_manager.hydrants

        # 添加撤销栈
        self.undo_stack = []
        self.redo_stack = []
        self.max_undo = 40

        # 检修区管理
        self.maintenance_zones: List[MaintenanceZone] = []
        self._next_zone_id: int = 0

        # 楼层分离相关（仅内存，需求95）
        self.separation_values: Dict[str, float] = {}   # 楼层名 -> 分离值(米)
        self._separation_applied = False                  # 是否已应用分离显示

        # 绑定全局ESC键
        # self.bind("<KeyPress-Escape>", self.on_escape)

        self.canvas.bind("<KeyPress-Escape>", self.on_escape)
        self.canvas.focus_set()  # 确保画布获得焦点

    def load_floor_colors(self):
        """从 floor_pipes_colors.json 加载颜色配置，文件不存在则使用默认颜色"""
        default_colors = [
            {"name": "淡红", "r": 255, "g": 179, "b": 179, "hex": "#FFB3B3"},
            {"name": "淡橙", "r": 255, "g": 214, "b": 153, "hex": "#FFD699"},
            {"name": "淡黄", "r": 255, "g": 255, "b": 153, "hex": "#FFFF99"},
            {"name": "淡绿", "r": 179, "g": 255, "b": 179, "hex": "#B3FFB3"},
            {"name": "淡青", "r": 179, "g": 255, "b": 255, "hex": "#B3FFFF"},
            {"name": "淡蓝", "r": 179, "g": 217, "b": 255, "hex": "#B3D9FF"},
            {"name": "淡紫", "r": 230, "g": 179, "b": 255, "hex": "#E6B3FF"},
            {"name": "淡粉", "r": 255, "g": 179, "b": 230, "hex": "#FFB3E6"},
            {"name": "淡茶", "r": 217, "g": 194, "b": 163, "hex": "#D9C2A3"},
            {"name": "淡灰绿", "r": 194, "g": 217, "b": 179, "hex": "#C2D9B3"},
            {"name": "淡玫瑰", "r": 255, "g": 204, "b": 204, "hex": "#FFCCCC"},
            {"name": "淡靛蓝", "r": 179, "g": 179, "b": 255, "hex": "#B3B3FF"}
        ]
        config_path = os.path.join(_get_exe_dir(), "floor_pipes_colors.json")
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                colors = data.get("colors", [])
                if colors:
                    self.layer_color_list = []
                    for c in colors:
                        hex_val = c.get("hex", "#FFFFFF")
                        # 十六进制转 RGB
                        hex_val = hex_val.lstrip('#')
                        r = int(hex_val[0:2], 16)
                        g = int(hex_val[2:4], 16)
                        b = int(hex_val[4:6], 16)
                        self.layer_color_list.append({
                            "name": c.get("name", "未命名"),
                            "r": r, "g": g, "b": b,
                            "hex": f"#{hex_val}"
                        })
                else:
                    self.layer_color_list = default_colors
        except Exception as e:
            logger.warning(f"加载 floor_pipes_colors.json 失败: {e}，使用默认颜色")
            self.layer_color_list = default_colors
        # 确保列表不为空
        if not self.layer_color_list:
            self.layer_color_list = default_colors
    
    def save_floor_colors(self):
        """保存当前颜色配置到 floor_pipes_colors.json"""
        colors = []
        for c in self.layer_color_list:
            colors.append({
                "name": c["name"],
                "hex": c["hex"]
            })
        config_path = os.path.join(_get_exe_dir(), "floor_pipes_colors.json")
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump({"colors": colors, "cycle": True, "description": "用于整体管网分层着色的颜色表，按楼层标高升序循环使用。"}, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"保存 floor_pipes_colors.json 失败: {e}")

    def update_floor_color_map(self):
        """根据当前颜色列表和楼层列表，按标高从低到高分配颜色（循环使用）"""
        if not self.cad_data_manager.floors:
            self.floor_color_map.clear()
            return
        # 按标高从低到高排序楼层
        sorted_floors = sorted(self.cad_data_manager.floors, key=lambda f: f.elevation)
        num_floors = len(sorted_floors)
        num_colors = len(self.layer_color_list)
        for idx, floor in enumerate(sorted_floors):
            if num_colors == 0:
                # 没有颜色，直接清空映射（后续会走原有颜色逻辑）
                color_hex = None
            else:
                color_idx = idx % num_colors
                color_hex = self.layer_color_list[color_idx]["hex"]
            self.floor_color_map[floor.name] = color_hex
        # 重新构建管道->楼层映射（因为楼层可能变化）
        self._build_pipe_floor_map()

    def show_layer_color_dialog(self):
        """打开分层颜色编辑对话框"""
        if self.color_dialog is None or not tk.Toplevel.winfo_exists(self.color_dialog.dialog):
            self.color_dialog = LayerColorDialog(self.winfo_toplevel(), self)
            self.color_dialog_open = True
            # 当对话框关闭时重置标志
            self.color_dialog.dialog.protocol("WM_DELETE_WINDOW", self._on_color_dialog_close)
        else:
            self.color_dialog.dialog.lift()
            self.color_dialog_open = True
    
    def _on_color_dialog_close(self):
        if self.color_dialog:
            self.color_dialog.dialog.destroy()
            self.color_dialog = None
        self.color_dialog_open = False

    def draw_color_legend(self):
        """在整体管网模式下，如果启用分层颜色，在画布左下角绘制颜色图例表"""
        self._draw_legend()

    def _draw_legend(self):
        """在整体管网画布左下角直接绘制图例（透明背景，文字+下方线条）"""
        # 清除旧图例
        if hasattr(self, 'legend_items'):
            for item in self.legend_items:
                try:
                    self.canvas.delete(item)
                except:
                    pass
            self.legend_items = []
        else:
            self.legend_items = []
    
        if not self.layer_colors_enabled.get() or self.current_view_mode != "global":
            return
        if not self.cad_data_manager.floors:
            return
    
        # 获取画布尺寸
        self.canvas.update_idletasks()
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        if canvas_width <= 10 or canvas_height <= 10:
            self.after(100, self._draw_legend)
            return
    
        # 楼层按标高从低到高排序（最低楼层在底部）
        sorted_floors = sorted(self.cad_data_manager.floors, key=lambda f: f.elevation)
    
        # 紧凑行高
        line_height = 14
        font = ("Arial", 9)
        # 从底部向上绘制
        start_y = canvas_height - 10
    
        for idx, floor in enumerate(sorted_floors):
            color_hex = self.floor_color_map.get(floor.name, "#FFFFFF")
            text = f"{floor.name}  FL {floor.elevation:.2f}"
    
            # 绘制文字（左下角对齐，背景透明）
            text_id = self.canvas.create_text(
                10, start_y - idx * line_height,
                text=text, anchor="sw",
                fill=color_hex, font=font,
                tags="legend"
            )
            self.legend_items.append(text_id)
    
            # 获取文字边界，确定线条的垂直中心位置
            bbox = self.canvas.bbox(text_id)
            if bbox:
                text_width = bbox[2] - bbox[0]
                text_center_y = (bbox[1] + bbox[3]) / 2   # 文字垂直中心
                line_y = text_center_y
                line_start_x = bbox[2] + 5                 # 文字右侧偏移5像素
            else:
                text_width = len(text) * 6
                line_y = start_y - idx * line_height + 3
                line_start_x = 10 + text_width + 5
            
            # 线条长度固定为30像素，线宽加倍（原宽度的2倍）
            line_length = 30
            line_width = max(4, int(6 * self.scale))       # 是之前 line_width 的2倍（原来 max(2,3*scale)）
            line_id = self.canvas.create_line(
                line_start_x, line_y, line_start_x + line_length, line_y,
                fill=color_hex, width=line_width,
                tags="legend"
            )
            self.legend_items.append(line_id)

    def _build_pipe_floor_map(self):
        """为所有管道建立管道ID到楼层名的映射"""
        self.pipe_floor_map.clear()
        for floor in self.cad_data_manager.floors:
            for pipe in floor.pipes:
                self.pipe_floor_map[pipe.pipe_id] = floor.name
        # 对于没有被分配到楼层的管道（理论上不应该发生），不加入映射

    def show_floor_height_dialog(self):
        """显示楼层与管网标高表对话框"""
        import json
        import os

        # 即使没有楼层数据也允许手动添加
        if not self.cad_data_manager.floors:
            if not messagebox.askyesno("提示", "当前没有楼层数据，是否继续手动创建楼层？"):
                return

        dialog = tk.Toplevel(self)
        dialog.title("楼层与管网标高表")
        dialog.geometry("720x500")
        dialog.transient(self)
        # 不调用 grab_set()，保持画布可拖拽和缩放（需求98）
        self.center_dialog(dialog)
        
        # 顶部输入框
        top_frame = ttk.Frame(dialog)
        top_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(top_frame, text="管道与上层楼面标高差 (m):").pack(side="left", padx=(0, 5))
        # 从全局设置读取上次保存的偏移量，如果没有则使用默认值0.8
        saved_offset = self.config_manager.get_global_setting("pipe_z_offset_default", "0.8")
        offset_var = tk.StringVar(value=saved_offset)
        offset_entry = ttk.Entry(top_frame, textvariable=offset_var, width=8)
        offset_entry.pack(side="left")

        # 表格
        columns = ("楼层名", "楼面标高(m)", "管网标高(m)", "楼层分离值(m)")
        tree = ttk.Treeview(dialog, columns=columns, show="headings", height=15)
        tree.heading("楼层名", text="楼层名")
        tree.heading("楼面标高(m)", text="楼面标高(m)")
        tree.heading("管网标高(m)", text="管网标高(m)")
        tree.heading("楼层分离值(m)", text="楼层分离值(m)")
        tree.column("楼层名", width=120)
        tree.column("楼面标高(m)", width=100)
        tree.column("管网标高(m)", width=100)
        tree.column("楼层分离值(m)", width=110)
        tree.pack(fill="both", expand=True, padx=10, pady=5)
        # 记录用户手动修改过的行（管网标高被直接编辑）
        manual_overrides = set()
        
        # 先定义插入和删除函数
        def insert_row(above=True):
            selected = tree.selection()
            if not selected:
                tree.insert("", "end", values=("新楼层", "0.00", "0.00"))
                return
            item = selected[0]
            if above:
                tree.insert(tree.parent(item), tree.index(item), values=("新楼层", "0.00", "0.00"))
            else:
                tree.insert(tree.parent(item), tree.index(item) + 1, values=("新楼层", "0.00", "0.00"))
            recalc_pipe_z()
            
        def delete_row():
            selected = tree.selection()
            if not selected:
                return
            item = selected[0]
            values = tree.item(item, "values")
            name = values[0]
            floor_obj = self.cad_data_manager.floor_by_name.get(name)
            if floor_obj and len(floor_obj.pipes) > 0:
                messagebox.showerror("无法删除", f"楼层 {name} 包含横管，不能删除")
                return
            # 从手动覆盖集合中移除
            if item in manual_overrides:
                manual_overrides.remove(item)            
            tree.delete(item)
            recalc_pipe_z()

        # 右键菜单
        tree_menu = tk.Menu(tree, tearoff=0)
        tree_menu.add_command(label="在上方插入行", command=lambda: insert_row(above=True))
        tree_menu.add_command(label="在下方插入行", command=lambda: insert_row(above=False))
        tree_menu.add_separator()
        tree_menu.add_command(label="删除选中行", command=delete_row)

        def show_tree_menu(event):
            try:
                tree_menu.tk_popup(event.x_root, event.y_root)
            finally:
                tree_menu.grab_release()

        tree.bind("<Button-3>", show_tree_menu)

        # 双击编辑
        def on_tree_double_click(event):
            item = tree.selection()[0]
            column = tree.identify_column(event.x)
            col_index = int(column.replace('#', '')) - 1
            # 禁止编辑楼层名列
            if col_index == 0:
                return
            if col_index < 0 or col_index > 3:
                return
            x, y, width, height = tree.bbox(item, column)
            value = tree.item(item, "values")[col_index]
            entry = ttk.Entry(tree)
            entry.place(x=x, y=y, width=width, height=height)
            entry.insert(0, value)
            entry.focus()

            def save_edit(e=None):
                new_value = entry.get()
                values = list(tree.item(item, "values"))
                values[col_index] = new_value
                tree.item(item, values=values)
                entry.destroy()
                # 如果编辑的是管网标高列（col_index == 2），标记为手动覆盖
                if col_index == 2:
                    manual_overrides.add(item)
                # 第4列（索引3）：楼层分离值，仅允许正整数（需求104）
                if col_index == 3:
                    # 最低楼层强制为0（需求111）
                    row_name = tree.item(item, "values")[0]
                    is_lowest = self.cad_data_manager.floors and \
                        row_name == min(self.cad_data_manager.floors, key=lambda f: f.elevation).name
                    if is_lowest:
                        new_value = "0"
                        values[3] = "0"
                        tree.item(item, values=values)
                    else:
                        try:
                            v = float(new_value)
                            if v < 0:
                                raise ValueError
                            new_value = str(int(v))  # 截断小数
                            values[3] = new_value
                            tree.item(item, values=values)
                        except (ValueError, OverflowError):
                            old_vals = tree.item(item, "values")
                            new_value = str(old_vals[3]) if len(old_vals) > 3 else "0"
                            values[3] = new_value
                            tree.item(item, values=values)
                recalc_pipe_z()                
                recalc_pipe_z()

            entry.bind("<Return>", save_edit)
            entry.bind("<FocusOut>", save_edit)

        tree.bind("<Double-1>", on_tree_double_click)

        # 加载数据（直接使用内存中的 pipe_z_offset）
        for floor in self.cad_data_manager.floors:
            sep_val = int(self.separation_values.get(floor.name, 0))
            tree.insert("", "end", values=(
                floor.name,
                f"{floor.elevation:.2f}",
                f"{floor.pipe_z_offset:.2f}",
                str(sep_val)
            ))

        # 底部按钮区域
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", padx=10, pady=10)

        # ---- 应用分离按钮回调（需求97） ----
        def apply_separation():
            """收集表格第4列数据到 self.separation_values 并触发重绘"""
            # 找出最低楼层（其分离值强制为0，需求111）
            lowest_name = min(
                (f.name for f in self.cad_data_manager.floors),
                key=lambda n: next(f.elevation for f in self.cad_data_manager.floors if f.name == n),
                default=None
            )
            new_sep = {}
            for item in tree.get_children():
                values = tree.item(item, "values")
                if len(values) < 4:
                    continue
                name = values[0]
                try:
                    v = int(float(values[3]))
                except (ValueError, OverflowError):
                    v = 0
                if name == lowest_name:
                    v = 0  # 最低楼层强制为0
                    # 同步表格显示
                    vals = list(values)
                    vals[3] = "0"
                    tree.item(item, values=vals)
                if v > 0:
                    new_sep[name] = float(v)
            self.separation_values = new_sep
            self._separation_applied = bool(new_sep)
            self._sep_cache_key = None
            self.redraw()

        def clear_separation():
            """清空所有分离值"""
            for item in tree.get_children():
                values = list(tree.item(item, "values"))
                if len(values) >= 4:
                    values[3] = "0"
                    tree.item(item, values=values)
            self.separation_values.clear()
            self._separation_applied = False
            self._sep_cache_key = None
            self.update_projection()
            if self.show_occlusion_var.get():
                self.build_occlusion_cache()
            self.redraw()

        def recalc_pipe_z():
            try:
                default_offset = float(offset_var.get())
            except ValueError:
                default_offset = 0.8
        
            # 保存用户修改的偏移量到全局设置
            self.config_manager.update_global_setting("pipe_z_offset_default", str(default_offset))
            
            # 获取当前所有行的楼层名和楼面标高
            rows = []
            for item in tree.get_children():
                values = tree.item(item, "values")
                if len(values) != 3:
                    continue
                name = values[0]
                try:
                    elev = float(values[1])
                except:
                    continue
                rows.append({"item_id": item, "name": name, "elevation": elev})
            
            if not rows:
                return
            
            # 按楼面标高从低到高排序
            rows.sort(key=lambda x: x["elevation"])
            
            # 重新计算每个楼层的管网标高
            for idx, row in enumerate(rows):
                if idx == len(rows) - 1:
                    # 顶层：管网标高 = 楼面标高 + 3.0（用户可后续手动修改）
                    pipe_z = row["elevation"] + 3.0
                else:
                    # 非顶层：管网标高 = 下一层楼面标高 - 默认偏移量
                    next_elev = rows[idx + 1]["elevation"]
                    pipe_z = next_elev - default_offset
                row["pipe_z"] = pipe_z
            
            # 更新表格显示（直接修改现有行的值，而不是删除重建，避免丢失焦点）
            for row in rows:
                # 如果该行的管网标高已被用户手动修改，则跳过自动计算的值
                if row["item_id"] in manual_overrides:
                    continue
                tree.set(row["item_id"], column="管网标高(m)", value=f"{row['pipe_z']:.2f}")

        offset_var.trace('w', lambda *args: recalc_pipe_z())

        def cancel():
            dialog.destroy()

        def assign():
            # 设置标志，阻止 refresh_data 中的自动重新计算
            self._skip_z_recalc = True

            # 收集新数据
            new_data = []
            for item in tree.get_children():
                values = tree.item(item, "values")
                if len(values) != 3:
                    continue
                name = values[0]
                try:
                    elev = float(values[1])
                    pipe_z = float(values[2])
                except:
                    continue
                new_data.append({"name": name, "elevation": elev, "pipe_z": pipe_z})

            drawing_unit = self.config_manager.get_live_config().get("drawing_unit", "毫米")
            if drawing_unit == "毫米":
                to_mm = 1000.0
            elif drawing_unit == "厘米":
                to_mm = 10.0
            else:  # 米
                to_mm = 1.0
            unit_factor = self.cad_data_manager.unit_factors.get(drawing_unit, 0.001)

            # 1. 更新楼层对象的标高和管网标高
            for floor in self.cad_data_manager.floors:
                for nd in new_data:
                    if nd["name"] == floor.name:
                        floor.elevation = nd["elevation"]
                        floor.pipe_z_offset = nd["pipe_z"]
                        break

            # 2. 更新所有节点的 Z 坐标
            for node in self.cad_data_manager.nodes:
                for floor in self.cad_data_manager.floors:
                    if node in floor.nodes:
                        new_z_m = floor.pipe_z_offset
                        node.z = new_z_m * to_mm
                        node.cad_key = f"{node.x:.6f},{node.y:.6f},{node.z:.6f}"
                        break

            # 3. 重新计算所有管道的长度
            for pipe in self.cad_data_manager.pipes:
                start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
                end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
                if start_node and end_node:
                    pipe.start_point = (pipe.start_point[0], pipe.start_point[1], start_node.z)
                    pipe.end_point = (pipe.end_point[0], pipe.end_point[1], end_node.z)
                    dx = pipe.end_point[0] - pipe.start_point[0]
                    dy = pipe.end_point[1] - pipe.start_point[1]
                    dz = pipe.end_point[2] - pipe.start_point[2]
                    pipe.raw_length = math.hypot(dx, dy, dz)
                    pipe.length = pipe.raw_length * unit_factor

            # 4. 更新阀门Z坐标（根据所在管道的新端点Z）
            for valve in self.cad_data_manager.valves:
                if valve.pipe_id and valve.pipe_id in self.cad_data_manager.pipe_by_id:
                    pipe = self.cad_data_manager.pipe_by_id[valve.pipe_id]
                    start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
                    end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
                    if start_node and end_node:
                        t = valve.distance_on_pipe
                        new_z = start_node.z + t * (end_node.z - start_node.z)
                        valve.z = new_z

            # 5. 重建节点索引
            self.cad_data_manager.node_by_id = {node.node_id: node for node in self.cad_data_manager.nodes}

            # 6. 刷新预览画布和左下角文字
            self.update_projection()
            self.redraw()
            self._draw_floor_info_text()

            # 7. 只刷新节点页面，避免触发 refresh_all_pages 导致重新计算
            root = self.winfo_toplevel()
            if hasattr(root, 'main_app') and '节点' in root.main_app.pages:
                root.main_app.pages['节点'].refresh_data()
            # 赋值后清除手动覆盖标记，因为模型已更新
            manual_overrides.clear()
            
            dialog.destroy()

        ttk.Button(btn_frame, text="取消", command=cancel).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="赋值", command=assign).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="清除分离", command=clear_separation).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="应用分离", command=apply_separation).pack(side="right", padx=5)

    def show_sprinkler_table_dialog(self):
        """打开喷淋管径表编辑对话框"""
        root_dir = _get_exe_dir()
        file_path = os.path.join(root_dir, "sprinkler_k_factor_pipe_capacity.json")
        default_path = os.path.join(root_dir, "sprinkler_k_factor_pipe_capacity_default.json")
        SprinklerCapacityDialog(self.winfo_toplevel(), file_path, default_path)

    def assign_diameter_to_pipes(self):
        """根据喷淋管径表对喷淋管网赋予管径"""
        if getattr(self, '_sprinkler_assign_dialog_active', False):
            return
        self._sprinkler_assign_dialog_active = True
        try:
            self._do_assign_diameter()
        finally:
            self._sprinkler_assign_dialog_active = False

    def _do_assign_diameter(self):
        cad = self.cad_data_manager
        config = self.config_manager.get_live_config()

        system_type = config.get("system_type", "outdoor_hydrant")
        if system_type != "sprinkler":
            messagebox.showwarning("不支持", "赋予管径功能仅在喷淋模式下可用。")
            return

        root_dir = _get_exe_dir()
        file_path = os.path.join(root_dir, "sprinkler_k_factor_pipe_capacity.json")

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                capacity = json.load(f)
        except Exception:
            messagebox.showerror("错误", "无法读取喷淋管径表文件。")
            return

        supply_nodes = cad.supply_nodes
        if not supply_nodes:
            messagebox.showwarning("缺少供水点", "请先在管网预览页设置供水点。")
            return

        supply_node = supply_nodes[0]
        if len(supply_node.node_ids) > 1:
            selected = self._select_supply_point(supply_node.node_ids)
            if selected is None:
                return
            supply_node_id = selected
        else:
            supply_node_id = supply_node.node_ids[0]

        if not supply_node_id or supply_node_id not in cad.node_by_id:
            messagebox.showerror("错误", "供水点节点ID无效。")
            return

        adjacency = defaultdict(list)
        edge_to_pipe = {}

        for pipe in cad.pipes:
            if not pipe.is_active:
                continue
            if pipe.pipe_id.startswith("SP_"):
                continue
            a, b = pipe.start_node_id, pipe.end_node_id
            adjacency[a].append(b)
            adjacency[b].append(a)
            edge_to_pipe[tuple(sorted((a, b)))] = pipe

        if supply_node_id not in adjacency:
            messagebox.showwarning("供水点未连接",
                "供水点节点没有连接到任何管道，无法进行遍历。")
            return

        try:
            tree_edges = _bfs_tree_and_detect_loops(adjacency, supply_node_id, edge_to_pipe)
        except ValueError as e:
            self._show_loop_warning(e.args[0])
            return

        if not tree_edges:
            messagebox.showwarning("无管道", "未找到可以赋予管径的管道。")
            return

        visited_nodes = {supply_node_id}
        for parent, child in tree_edges:
            visited_nodes.add(parent)
            visited_nodes.add(child)

        # 统计全树喷头 K 值
        k_counter = defaultdict(int)
        for nid in visited_nodes:
            k = cad.sprinkler_k_map.get(nid)
            if k:
                k_counter[int(k)] += 1

        if not k_counter:
            messagebox.showwarning("无喷头", "管网中未检测到任何喷头，无法赋予管径。")
            return

        max_count = max(k_counter.values())
        global_K = max(k for k, v in k_counter.items() if v == max_count)
        global_K_str = str(global_K)

        if global_K_str not in capacity:
            messagebox.showwarning("K值未找到",
                f"喷淋管径表中未找到 K={global_K} 对应的数据。\n"
                f"请检查设置页面的K值或编辑喷淋管径表。")
            return

        has_multi_k = len(k_counter) > 1

        material = config.get("pipe_material", "镀锌钢管")

        children = defaultdict(list)
        parent_of = {}
        for parent, child in tree_edges:
            children[parent].append(child)
            parent_of[child] = parent

        # ---------- 辅助函数 ----------
        def _lookup_dn(cap_dict, dn_list, downstream_count):
            for dn in dn_list:
                if cap_dict[dn] > 0 and cap_dict[dn] >= downstream_count:
                    return dn
            for dn in reversed(dn_list):
                if cap_dict[dn] > 0:
                    return dn
            return "DN25"

        def _record_and_set(pipe, assigned_dn, modified_list, mat):
            if pipe and pipe.nominal_diameter != assigned_dn:
                modified_list.append((pipe, pipe.nominal_diameter, pipe.inner_diameter))
                pipe.nominal_diameter = assigned_dn
                info = self.material_manager.get_diameter_info(mat, assigned_dn)
                if info.get("inner", 0) > 0:
                    pipe.inner_diameter = info["inner"]
                cad.manual_dn_pipes.add(pipe.pipe_id)

        def _post_order_accum(root, ch_map, spr_map):
            acc = {}
            stk = [(root, 0)]
            while stk:
                nd, state = stk.pop()
                if state == 0:
                    stk.append((nd, 1))
                    for cc in reversed(ch_map.get(nd, [])):
                        stk.append((cc, 0))
                else:
                    total = spr_map.get(nd, 0)
                    for cc in ch_map.get(nd, []):
                        total += acc.get(cc, 0)
                    acc[nd] = total
            return acc

        # ============ 第一遍：全局 K 赋值 ============
        node_sprinklers = {}
        for nid in visited_nodes:
            node_sprinklers[nid] = 1 if nid in cad.sprinkler_k_map else 0

        accumulated = _post_order_accum(supply_node_id, children, node_sprinklers)

        cap = capacity[global_K_str]
        dns = sorted(cap.keys(), key=lambda x: int(x[2:]) if x.startswith('DN') else 0)

        modified_pipes = []

        for parent, child in tree_edges:
            downstream = accumulated.get(child, 0)
            assigned_dn = _lookup_dn(cap, dns, downstream)
            pipe = edge_to_pipe.get(tuple(sorted((parent, child))))
            _record_and_set(pipe, assigned_dn, modified_pipes, material)

        # ============ 第二遍和修正（仅多 K 值管网） ============
        if has_multi_k:
            # ---- 收集用水点（有 K 值的 demand node） ----
            water_use_ids = set()
            for g in cad.demand_groups.values():
                for dn in g.demand_nodes:
                    if dn.node_id in cad.sprinkler_k_map:
                        water_use_ids.add(dn.node_id)

            if water_use_ids:
                # ---- 后序标记：节点下游是否有用水点 ----
                has_water_use = {}
                stk = [(supply_node_id, 0)]
                while stk:
                    nd, state = stk.pop()
                    if state == 0:
                        stk.append((nd, 1))
                        for cc in reversed(children.get(nd, [])):
                            stk.append((cc, 0))
                    else:
                        marked = nd in water_use_ids
                        for cc in children.get(nd, []):
                            marked = marked or has_water_use.get(cc, False)
                        has_water_use[nd] = marked

                reduced_edges = [(p, c) for p, c in tree_edges
                                 if has_water_use.get(c, False)]

                if reduced_edges:
                    # ---- 统计用水点 K 值 ----
                    wu_k_counter = defaultdict(int)
                    for nid in water_use_ids:
                        k_val = int(cad.sprinkler_k_map[nid])
                        wu_k_counter[k_val] += 1

                    max_wu_count = max(wu_k_counter.values())
                    water_use_K = max(k for k, v in wu_k_counter.items()
                                      if v == max_wu_count)
                    water_use_K_str = str(water_use_K)

                    # ---- 第二遍赋值（仅当 K 不同时） ----
                    if water_use_K_str != global_K_str and water_use_K_str in capacity:
                        reduced_children = defaultdict(list)
                        for p, c in reduced_edges:
                            reduced_children[p].append(c)

                        reduced_sprinklers = {}
                        for nid in has_water_use:
                            reduced_sprinklers[nid] = 1 if nid in water_use_ids else 0

                        reduced_accum = _post_order_accum(
                            supply_node_id, reduced_children, reduced_sprinklers)

                        wu_cap = capacity[water_use_K_str]
                        wu_dns = sorted(wu_cap.keys(),
                                        key=lambda x: int(x[2:]) if x.startswith('DN') else 0)

                        for parent, child in reduced_edges:
                            downstream = reduced_accum.get(child, 0)
                            assigned_dn = _lookup_dn(wu_cap, wu_dns, downstream)
                            pipe = edge_to_pipe.get(tuple(sorted((parent, child))))
                            _record_and_set(pipe, assigned_dn, modified_pipes, material)

            # ============ 上游 ≥ 下游修正 ============
            depth = {supply_node_id: 0}
            for p, c in tree_edges:
                depth[c] = depth.get(p, 0) + 1
            sorted_edges = sorted(tree_edges,
                                  key=lambda x: depth[x[1]], reverse=True)

            sp_pipes = [p for p in cad.pipes
                        if p.pipe_id.startswith("SP_") and p.is_active]

            changed = True
            while changed:
                changed = False
                # a) BFS 树边上下游检查
                for p, c in sorted_edges:
                    pipe = edge_to_pipe.get(tuple(sorted((p, c))))
                    if not pipe or not pipe.nominal_diameter:
                        continue
                    try:
                        p_dn_int = int(pipe.nominal_diameter[2:])
                    except ValueError:
                        continue
                    for gc in children.get(c, []):
                        c_pipe = edge_to_pipe.get(tuple(sorted((c, gc))))
                        if c_pipe and c_pipe.nominal_diameter:
                            try:
                                c_dn_int = int(c_pipe.nominal_diameter[2:])
                            except ValueError:
                                continue
                            if c_dn_int > p_dn_int:
                                _record_and_set(pipe, c_pipe.nominal_diameter,
                                                modified_pipes, material)
                                changed = True
                                break
                # b) SP_ 管道与其上游管道的比较
                for sp_pipe in sp_pipes:
                    if not sp_pipe.nominal_diameter:
                        continue
                    base_node = sp_pipe.start_node_id
                    parent_node = parent_of.get(base_node)
                    if parent_node is None:
                        continue
                    feed_pipe = edge_to_pipe.get(
                        tuple(sorted((parent_node, base_node))))
                    if not feed_pipe or not feed_pipe.nominal_diameter:
                        continue
                    try:
                        sp_dn_int = int(sp_pipe.nominal_diameter[2:])
                        feed_dn_int = int(feed_pipe.nominal_diameter[2:])
                    except ValueError:
                        continue
                    if sp_dn_int > feed_dn_int:
                        _record_and_set(feed_pipe, sp_pipe.nominal_diameter,
                                        modified_pipes, material)
                        changed = True

        # ============ 汇总 undo（保留每根管道首次修改记录） ============
        first_mod = {}
        for p, old_dn, old_in in modified_pipes:
            pid = p.pipe_id
            if pid not in first_mod:
                first_mod[pid] = (p, old_dn, old_in)
        unique_modified = list(first_mod.values())

        if unique_modified:
            self.undo_stack.append({
                'type': 'batch_attr',
                'changes': [{'pipe': p, 'old_dn': old_dn, 'old_inner': old_in}
                            for p, old_dn, old_in in unique_modified]
            })
            self.redo_stack.clear()
            if len(self.undo_stack) > self.max_undo:
                self.undo_stack.pop(0)

        if unique_modified:
            cad.update_pipe_types(config)
        self.refresh_data(keep_view=True)
        self._refresh_other_pages()

        if unique_modified:
            self.show_temp_message(
                f"已为 {len(unique_modified)} 根管道赋予管径（按 Ctrl+Z 可撤销）", 3000)
        else:
            self.show_temp_message(
                "所有管道管径已符合喷淋管径表，无需修改。", 2000)

    def _select_supply_point(self, node_ids):
        """多供水节点时弹出选择对话框，返回选中的 node_id 或 None"""
        parent = self.winfo_toplevel()
        dialog = tk.Toplevel(parent)
        dialog.title("选择供水点")
        dialog.transient(parent)
        dialog.resizable(False, False)
        ttk.Label(dialog, text="检测到多个供水节点，请选择其中一个作为遍历起点：").pack(padx=15, pady=(10, 5))
        listbox = tk.Listbox(dialog, height=min(len(node_ids), 8), width=40)
        listbox.pack(padx=15, pady=5)
        for nid in node_ids:
            listbox.insert(tk.END, f"节点 {nid}")
        listbox.selection_set(0)
        result = [None]
        def on_ok():
            sel = listbox.curselection()
            if sel:
                result[0] = node_ids[sel[0]]
            dialog.destroy()
        def on_cancel():
            dialog.destroy()
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=(0, 10))
        ttk.Button(btn_frame, text="确定", command=on_ok).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="取消", command=on_cancel).pack(side="left", padx=5)
        self.center_dialog(dialog)
        dialog.bind("<Escape>", lambda e: on_cancel())
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)
        dialog.lift()
        dialog.focus_set()
        self.wait_window(dialog)
        return result[0]

    def _show_loop_warning(self, cycle_pipe_ids):
        """显示环路警告并高亮环路管道"""
        if hasattr(self, 'loop_highlight_pipe_ids'):
            self.loop_highlight_pipe_ids.clear()
        self.loop_highlight_pipe_ids = set(cycle_pipe_ids)
        self._zoom_to_pipes(cycle_pipe_ids)

        parent = self.winfo_toplevel()
        dialog = tk.Toplevel(parent)
        dialog.title("检测到环路")
        dialog.transient(parent)
        dialog.resizable(False, False)
        msg = f"管网中存在环路，无法进行树状遍历。\n环路包含以下 {len(cycle_pipe_ids)} 根管道：\n"
        msg += ", ".join(cycle_pipe_ids)
        ttk.Label(dialog, text=msg, wraplength=400).pack(padx=20, pady=10)
        ttk.Label(dialog, text="请在关闭本窗口后，手动修复环路结构。", foreground="gray").pack(pady=(0, 10))
        def on_close():
            dialog.destroy()
        ttk.Button(dialog, text="确定", command=on_close).pack(pady=(0, 10))
        dialog.bind("<Escape>", lambda e: on_close())
        dialog.protocol("WM_DELETE_WINDOW", on_close)
        self.center_dialog(dialog)
        dialog.lift()
        dialog.focus_set()
        self.wait_window(dialog)

        self.loop_highlight_pipe_ids.clear()
        self.redraw()

    def _zoom_to_pipes(self, pipe_ids):
        """定位画布到指定管道集，使其占据画布中央一半区域"""
        nodes_x, nodes_y = [], []
        cad = self.cad_data_manager
        for pid in pipe_ids:
            pipe = cad.pipe_by_id.get(pid)
            if pipe:
                for nid in (pipe.start_node_id, pipe.end_node_id):
                    pt = self.projected_coords.get(nid)
                    if pt:
                        nodes_x.append(pt[0])
                        nodes_y.append(pt[1])
        if not nodes_x:
            return
        cx, cy = (min(nodes_x) + max(nodes_x)) / 2, (min(nodes_y) + max(nodes_y)) / 2
        cw = max(self.canvas.winfo_width(), 800)
        ch = max(self.canvas.winfo_height(), 600)
        pw = max(max(nodes_x) - min(nodes_x), 1)
        ph = max(max(nodes_y) - min(nodes_y), 1)
        new_scale = min((cw * 0.5) / pw, (ch * 0.5) / ph)
        self.scale = new_scale
        self.translate_x = (cw / 2) - cx * new_scale
        self.translate_y = (ch / 2) - cy * new_scale
        self.redraw()

    def _switch_to_floor_tab(self, tab_text):
        current_idx = self.floor_notebook.index(self.floor_notebook.select())
        for i, tab_id in enumerate(self.floor_notebook.tabs()):
            if self.floor_notebook.tab(tab_id, "text") == tab_text:
                self.floor_notebook.select(tab_id)
                return i != current_idx
        return False

    def jump_to_pipe(self, pipe_id, to_global=False):
        self._pending_jump = ('pipe', pipe_id, None)
        if to_global:
            switched = self._switch_to_floor_tab("整体管网")
        else:
            floor_name = self.pipe_floor_map.get(pipe_id)
            switched = self._switch_to_floor_tab(floor_name) if floor_name else False
        if not switched:
            self._execute_jump_zoom()

    def jump_to_node(self, node_id, to_global=False):
        cad = self.cad_data_manager
        longest_pipe_id = None
        longest_len = -1
        for pipe in cad.pipes:
            if not pipe.is_active or pipe.pipe_id.startswith("SP_"):
                continue
            if pipe.start_node_id == node_id or pipe.end_node_id == node_id:
                if pipe.length > longest_len:
                    longest_len = pipe.length
                    longest_pipe_id = pipe.pipe_id
        self._pending_jump = ('node', node_id, longest_pipe_id)
        if to_global:
            switched = self._switch_to_floor_tab("整体管网")
        else:
            switched = False
            for pipe in cad.pipes:
                if not pipe.is_active or pipe.pipe_id.startswith("SP_"):
                    continue
                if pipe.start_node_id == node_id or pipe.end_node_id == node_id:
                    floor_name = self.pipe_floor_map.get(pipe.pipe_id)
                    if floor_name:
                        switched = self._switch_to_floor_tab(floor_name)
                        break
        if not switched:
            self._execute_jump_zoom()

    def jump_to_valve(self, valve_id, to_global=False):
        cad = self.cad_data_manager
        valve = cad.valve_by_id.get(valve_id)
        if not valve or not valve.pipe_id:
            return
        self._pending_jump = ('valve', valve_id, None)
        if to_global:
            switched = self._switch_to_floor_tab("整体管网")
        else:
            floor_name = valve.floor_name or self.pipe_floor_map.get(valve.pipe_id)
            switched = self._switch_to_floor_tab(floor_name) if floor_name else False
        if not switched:
            self._execute_jump_zoom()

    def _jump_zoom_pipe(self, pipe_id):
        self.update_projection()
        if self.current_view_mode == "floor":
            self._filter_projected_to_current_floor()
        self._zoom_to_pipes([pipe_id])

    def _jump_zoom_node(self, node_id, longest_pipe_id):
        self.update_projection()
        if self.current_view_mode == "floor":
            self._filter_projected_to_current_floor()
        if longest_pipe_id:
            self._zoom_to_pipes([longest_pipe_id])
        self.scale *= 2.0
        pt = self.projected_coords.get(node_id)
        if pt:
            cw = max(self.canvas.winfo_width(), 800)
            ch = max(self.canvas.winfo_height(), 600)
            self.translate_x = (cw / 2) - pt[0] * self.scale
            self.translate_y = (ch / 2) - pt[1] * self.scale
            self.redraw()

    def _jump_zoom_valve(self, valve_id):
        cad = self.cad_data_manager
        valve = cad.valve_by_id.get(valve_id)
        if not valve or not valve.pipe_id:
            return
        self.update_projection()
        if self.current_view_mode == "floor":
            self._filter_projected_to_current_floor()
        self._zoom_to_pipes([valve.pipe_id])
        pipe = cad.pipe_by_id.get(valve.pipe_id)
        if pipe:
            s = self.projected_coords.get(pipe.start_node_id)
            e = self.projected_coords.get(pipe.end_node_id)
            if s and e:
                t = valve.distance_on_pipe
                vx = s[0] + t * (e[0] - s[0])
                vy = s[1] + t * (e[1] - s[1])
                cw = max(self.canvas.winfo_width(), 800)
                ch = max(self.canvas.winfo_height(), 600)
                self.translate_x = (cw / 2) - vx * self.scale
                self.translate_y = (ch / 2) - vy * self.scale
                self.redraw()

    def _execute_jump_zoom(self):
        """执行待处理的跳转缩放，并更新 floor_view_state"""
        info = self._pending_jump
        self._pending_jump = None
        if not info:
            return
        etype = info[0]
        if etype == 'pipe':
            self._jump_zoom_pipe(info[1])
        elif etype == 'node':
            node_id = info[1]
            longest_pipe_id = info[2]
            if longest_pipe_id is None:
                cad = self.cad_data_manager
                longest_len = -1
                for pipe in cad.pipes:
                    if not pipe.is_active or pipe.pipe_id.startswith("SP_"):
                        continue
                    if pipe.start_node_id == node_id or pipe.end_node_id == node_id:
                        if pipe.length > longest_len:
                            longest_len = pipe.length
                            longest_pipe_id = pipe.pipe_id
            self._jump_zoom_node(node_id, longest_pipe_id)
        elif etype == 'valve':
            self._jump_zoom_valve(info[1])
        self.floor_view_state[self.current_floor_name] = (
            self.scale, self.translate_x, self.translate_y
        )

    def center_dialog(self, dialog):
        """将对话框居中于父窗口"""
        dialog.update_idletasks()
        w = dialog.winfo_width()
        h = dialog.winfo_height()
        parent = self.winfo_toplevel()
        px = parent.winfo_x()
        py = parent.winfo_y()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        dialog.geometry(f"{w}x{h}+{x}+{y}")

    # ----------------------------------------------------------------------
    # 界面构建
    # ----------------------------------------------------------------------
    def create_widgets(self):
        # 防止重复创建控件（标志放在最后设置，避免中途异常导致状态不一致）
        if hasattr(self, '_widgets_created') and self._widgets_created:
            return
        
        # 如果已存在 paned，先销毁旧控件
        if hasattr(self, 'paned') and self.paned:
            self.paned.destroy()
        
        self.paned = ttk.PanedWindow(self, orient="horizontal")
        self.paned.pack(fill="both", expand=True)

        left_frame = ttk.Frame(self.paned)
        self.paned.add(left_frame, weight=4)

        # 创建楼层标签页控件
        self.floor_notebook = ttk.Notebook(left_frame)
        logger.info(f"floor_notebook created: {self.floor_notebook}")
        self.floor_notebook.pack(fill="both", expand=True)
        
        # 创建一个临时画布（用于兼容老代码）
        self.canvas = tk.Canvas(left_frame, bg="black", highlightthickness=0)
        self.canvas.pack_forget()
        self._current_canvas = None

        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<Button-2>", self.on_mouse_middle_down)
        self.canvas.bind("<B2-Motion>", self.on_mouse_middle_drag)
        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<KeyPress-Escape>", self.on_escape)
        self.canvas.bind("<Control-z>", self.undo)
        self.canvas.bind("<Control-Z>", self.undo)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Configure>", self._on_canvas_configure, add="+")
        self.canvas.focus_set()

        right_frame = ttk.Frame(self.paned, width=100)
        self.paned.add(right_frame, weight=0)
        self.create_control_panel(right_frame)
        
        # 标记创建完成（放在最后，确保所有控件都成功创建）
        self._widgets_created = True
        logger.info("create_widgets completed successfully")

    def rebuild_floor_tabs(self):
        """根据 CADDataManager 中的楼层数据重建标签页，并保持当前选中项和视图状态"""
        if self.floor_notebook is None:
            logger.error("floor_notebook is None, cannot rebuild tabs")
            return
    
        # 保存当前选中的标签页名称和视图状态
        selected_name = None
        if self.floor_notebook.tabs():
            sel_tab = self.floor_notebook.select()
            if sel_tab:
                selected_name = self.floor_notebook.tab(sel_tab, "text")
        # if selected_name and self.current_floor_name and selected_name != self.current_floor_name:
        #     selected_name = self.current_floor_name
    
        # 保存所有楼层的视图状态（已由 _on_floor_changed 保存，这里不做重复）
    
        # 清空当前画布引用
        if self._current_canvas is not None:
            self._current_canvas = None
        if self.canvas is not None:
            self.canvas = None
    
        # 解绑事件防止中间状态被错误保存
        self.floor_notebook.unbind("<<NotebookTabChanged>>")

        # 清空现有标签页（使用 forget 确保 tab 记录也被移除）
        for tab_id in self.floor_notebook.tabs():
            self.floor_notebook.forget(tab_id)
        for child in self.floor_notebook.winfo_children():
            child.destroy()
        self.floor_canvases.clear()
    
        if not self.cad_data_manager.floors:
            frame = ttk.Frame(self.floor_notebook)
            canvas = tk.Canvas(frame, bg="black", highlightthickness=0)
            canvas.pack(fill="both", expand=True)
            canvas.bind("<Configure>", lambda e: self.redraw())
            self.floor_notebook.add(frame, text="单层")
            self.floor_canvases["单层"] = canvas
            self._current_canvas = canvas
            self.canvas = canvas
            self.current_floor_name = "单层"
            self._bind_canvas_events(canvas)
    
        # 获取分组映射
        grouped = getattr(self.cad_data_manager, 'grouped_floors_map', {})
        grouped_floors = set()
        for group_name, actuals in grouped.items():
            grouped_floors.update(actuals)

        # 构建显示项目列表：(显示名称, 实际楼层名列表, 排序标高)
        display_items = []
        # 普通楼层（不在任何分组中）
        for floor in self.cad_data_manager.floors:
            if floor.name not in grouped_floors:
                display_items.append((floor.name, [floor.name], floor.elevation))
        # 分组
        for group_name, actual_names in grouped.items():
            first_floor = self.cad_data_manager.floor_by_name.get(actual_names[0])
            sort_elev = first_floor.elevation if first_floor else 0
            display_items.append((group_name, actual_names, sort_elev))

        # 按标高排序
        display_items.sort(key=lambda x: x[2])

        # 创建标签页
        for disp_name, actual_names, _ in display_items:
            frame = ttk.Frame(self.floor_notebook)
            canvas = tk.Canvas(frame, bg="black", highlightthickness=0)
            canvas.pack(fill="both", expand=True)
            self.floor_notebook.add(frame, text=disp_name)
            self.floor_canvases[disp_name] = canvas
            # 存储该标签页对应的实际楼层列表
            canvas.actual_floors = actual_names
            canvas.current_display_floor = actual_names[0]  # 默认显示第一个

        # 创建整体管网标签页（最后面）
        self._create_global_tab()
    
        # 恢复选中的标签页
        target_name = selected_name
        if target_name and target_name in self.floor_canvases:
            for tab_id in self.floor_notebook.tabs():
                if self.floor_notebook.tab(tab_id, "text") == target_name:
                    self.floor_notebook.select(tab_id)
                    break
        else:
            if self.floor_notebook.tabs():
                self.floor_notebook.select(0)
    
        self._on_floor_changed()  # 手动调用一次以设置当前画布
        self.floor_notebook.bind("<<NotebookTabChanged>>", self._on_floor_changed)
        """
        if self.floor_notebook.tabs():
            first_tab_text = self.floor_notebook.tab(0, "text")
            self.current_floor_name = first_tab_text
            logger.info(f"强制设置当前楼层为: {self.current_floor_name}")
        """
        
    def _create_global_tab(self):
        """创建整体管网标签页"""
        frame = ttk.Frame(self.floor_notebook)
        canvas = tk.Canvas(frame, bg="black", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        self.floor_notebook.add(frame, text="整体管网")
        self.floor_canvases["整体管网"] = canvas
        self._bind_canvas_events(canvas)

    def _on_floor_changed(self, event=None):
        """楼层切换时更新当前画布引用并重绘，恢复该楼层视图状态"""
        tab_id = self.floor_notebook.select()
        if not tab_id:
            return
        tab_text = self.floor_notebook.tab(tab_id, "text")

        # 仅当切换到不同标签页时才保存上一个楼层的视图状态
        if (self._current_canvas is not None and self.current_floor_name is not None
            and self.current_floor_name != tab_text):
            self.floor_view_state[self.current_floor_name] = (
                self.scale, self.translate_x, self.translate_y
            )

        frame = self.floor_notebook.nametowidget(tab_id)
        new_canvas = None
        for child in frame.winfo_children():
            if isinstance(child, tk.Canvas):
                new_canvas = child
                break
        if new_canvas is None:
            return
    
        # 解绑旧画布事件
        if self._current_canvas is not None and self._current_canvas != new_canvas:
            try:
                self._unbind_canvas_events(self._current_canvas)
            except Exception as e:
                logger.debug(f"解绑旧画布事件时出错（可忽略）: {e}")
        if self._current_canvas != new_canvas:
            self._bind_canvas_events(new_canvas)
    
        self._current_canvas = new_canvas
        self.canvas = new_canvas
        self.current_floor_name = tab_text

        # 对于分组标签页，设置实际显示的第一个楼层
        if hasattr(self._current_canvas, 'actual_floors'):
            self._current_canvas.current_display_floor = self._current_canvas.actual_floors[0]
                
        # 设置视图模式
        if tab_text == "整体管网":
            self.current_view_mode = "global"
        else:
            self.current_view_mode = "floor"
    
        # 控制罗盘显隐和消火栓支管展开复选框状态
        if self.current_view_mode == "global":
            self.compass_frame.pack(fill="x", padx=5, pady=5)
        else:
            self.compass_frame.pack_forget()
        self._update_hydrant_flat_state()
    
        logger.info(f"切换到楼层: {self.current_floor_name}")
    
        # 恢复该楼层的视图状态（若从未访问过，则自动居中，仅此一次）
        if tab_text in self.floor_view_state:
            self.scale, self.translate_x, self.translate_y = self.floor_view_state[tab_text]
        else:
            self.update_projection()
            if self.current_view_mode == "floor":
                self._filter_projected_to_current_floor()
            self.auto_center()
            self.floor_view_state[self.current_floor_name] = (self.scale, self.translate_x, self.translate_y)
    
        # 更新投影并重绘（不重置视图）
        self.update_projection()
        if self.current_view_mode == "floor":
            self._filter_projected_to_current_floor()
        self.redraw()
        
        # 执行待处理的跳转缩放
        if self._pending_jump:
            self._execute_jump_zoom()

    def _filter_projected_to_current_floor(self):
        """过滤 projected_coords 只保留当前楼层节点，使 auto_center 以该楼层范围居中。"""
        canvas = self._current_canvas
        display_floor = self.current_floor_name
        if canvas and hasattr(canvas, 'actual_floors'):
            display_floor = canvas.current_display_floor
        if display_floor == "单层":
            return
        floor = self.cad_data_manager.floor_by_name.get(display_floor)
        if not floor:
            return
        keep_ids = set()
        for pipe in floor.pipes:
            keep_ids.add(pipe.start_node_id)
            keep_ids.add(pipe.end_node_id)
        for node in floor.nodes:
            keep_ids.add(node.node_id)
        for nid in list(self.projected_coords.keys()):
            if nid not in keep_ids:
                del self.projected_coords[nid]

    def _bind_canvas_events(self, canvas):
        """为指定画布绑定所有交互事件"""
        canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        canvas.bind("<Button-2>", self.on_mouse_middle_down)
        canvas.bind("<B2-Motion>", self.on_mouse_middle_drag)
        canvas.bind("<Button-1>", self.on_left_click)
        canvas.bind("<Button-3>", self.on_right_click)
        canvas.bind("<B1-Motion>", self.on_left_drag)
        canvas.bind("<ButtonRelease-1>", self.on_left_release)
        canvas.bind("<KeyPress-Escape>", self.on_escape)
        canvas.bind("<Control-z>", self.undo)
        canvas.bind("<Control-Z>", self.undo)
        canvas.bind("<Motion>", self.on_mouse_move)
        canvas.bind("<Leave>", self.on_mouse_leave)
        canvas.bind("<Configure>", self._on_canvas_configure)
        canvas.bind("<KeyPress-Alt_L>", self._on_alt_press)
        canvas.bind("<KeyPress-Alt_R>", self._on_alt_press)
        canvas.bind("<KeyRelease-Alt_L>", self._on_alt_release)
        canvas.bind("<KeyRelease-Alt_R>", self._on_alt_release)
        canvas.focus_set()

    def _unbind_canvas_events(self, canvas):
        """解绑画布事件（避免重复绑定），忽略窗口已销毁的异常"""
        if not canvas or not canvas.winfo_exists():
            return
        try:
            canvas.unbind("<MouseWheel>")
            canvas.unbind("<Button-2>")
            canvas.unbind("<B2-Motion>")
            canvas.unbind("<Button-1>")
            canvas.unbind("<Button-3>")
            canvas.unbind("<B1-Motion>")
            canvas.unbind("<ButtonRelease-1>")
            canvas.unbind("<KeyPress-Escape>")
            canvas.unbind("<Control-z>")
            canvas.unbind("<Control-Z>")
            canvas.unbind("<Motion>")
            canvas.unbind("<Leave>")
        except tk.TclError:
            # 窗口已销毁，忽略
            pass

    def create_control_panel(self, parent):
        # 显示选项
        display_frame = ttk.LabelFrame(parent, text="显示选项", padding=5)
        display_frame.pack(fill="x", padx=5, pady=5)

        # 创建两列容器
        left_col = ttk.Frame(display_frame)
        right_col = ttk.Frame(display_frame)
        left_col.pack(side="left", fill="both", expand=True)
        right_col.pack(side="left", fill="both", expand=True)

        # 左侧列
        ttk.Checkbutton(left_col, text="公称管径",
                        variable=self.show_nominal,
                        command=self.redraw).pack(anchor="w")
        ttk.Checkbutton(left_col, text="管段长度",
                        variable=self.show_length,
                        command=self.redraw).pack(anchor="w")
        ttk.Checkbutton(left_col, text="管道编号",
                        variable=self.show_pipe_id,
                        command=self.redraw).pack(anchor="w")
        ttk.Checkbutton(left_col, text="节点编号",
                        variable=self.show_node_ids,
                        command=self.redraw).pack(anchor="w")
        self.show_riser_id = tk.BooleanVar(value=False)
        ttk.Checkbutton(left_col, text="立管编号",
                        variable=self.show_riser_id,
                        command=self.redraw).pack(anchor="w")
        self.show_valve_id = tk.BooleanVar(value=False)
        ttk.Checkbutton(left_col, text="阀门编号",
                        variable=self.show_valve_id,
                        command=self.redraw).pack(anchor="w")
        ttk.Checkbutton(left_col, text="横管标高",
                        variable=self.show_elevation,
                        command=self.redraw).pack(anchor="w")        
        
        # 右侧列
        self.flow_check = ttk.Checkbutton(right_col, text="管道流量",
                                           variable=self.show_flow,
                                           command=self.redraw,
                                           state="disabled")
        self.flow_check.pack(anchor="w")
        self.velocity_check = ttk.Checkbutton(right_col, text="管道流速",
                                               variable=self.show_velocity,
                                               command=self.redraw,
                                               state="disabled")
        self.velocity_check.pack(anchor="w")
        self.loss_check = ttk.Checkbutton(right_col, text="管道水损",
                                           variable=self.show_loss,
                                           command=self.redraw,
                                           state="disabled")
        self.loss_check.pack(anchor="w")
        self.arrow_check = ttk.Checkbutton(right_col, text="水流方向",
                                           variable=self.show_arrow,
                                           command=self.redraw,
                                           state="disabled")
        self.arrow_check.pack(anchor="w")
        self.node_pressure_check = ttk.Checkbutton(right_col, text="节点压力",
                                                   variable=self.show_node_pressure,
                                                   command=self.redraw,
                                                   state="disabled")
        self.node_pressure_check.pack(anchor="w")        

        self.update_btn = ttk.Button(display_frame, text="更新管网连通",
                                      command=self.on_update_network)
        self.update_btn.pack(fill="x", pady=5)

        ttk.Checkbutton(display_frame, text="实时更新管网连通",
                        variable=self.real_time,
                        command=self.on_real_time_toggle).pack(anchor="w")

        # 管网标高按钮
        self.height_btn = ttk.Button(display_frame, text="楼层与管网标高", command=self.show_floor_height_dialog)
        self.height_btn.pack(fill="x", pady=5)

        # 喷淋管径相关按钮（喷淋模式下显示）
        self.sprinkler_table_btn = ttk.Button(display_frame, text="喷淋管径表",
            command=self.show_sprinkler_table_dialog)
        self.sprinkler_table_btn.pack(fill="x", pady=2)
        self.assign_diameter_btn = ttk.Button(display_frame, text="赋予管径",
            command=self.assign_diameter_to_pipes)
        self.assign_diameter_btn.pack(fill="x", pady=2)

        # 创建一行用于放置两个复选框的框架
        self.check_frame = ttk.Frame(display_frame)
        self.check_frame.pack(anchor="w", fill="x")

        # 立管重复标记复选框（默认勾选）
        self.show_riser_warning = tk.BooleanVar(value=True)
        ttk.Checkbutton(display_frame, text="标记同层同编号立管",
                        variable=self.show_riser_warning,
                        command=self.redraw).pack(anchor="w", pady=(5,0))

        # 显示无流量管道标注
        self.show_zero_flow_label_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(display_frame, text="显示无流量管道标注",
                        variable=self.show_zero_flow_label_var,
                        command=self.redraw).pack(anchor="w")

        # 管道操作栏
        pipe_op_frame = ttk.LabelFrame(parent, text="管道操作", padding=5)
        pipe_op_frame.pack(fill="x", padx=5, pady=5)
        
        # 使用 Frame 让两个按钮在一行
        button_row = ttk.Frame(pipe_op_frame)
        button_row.pack(fill="x", pady=2)
        
        self.mark_invalid_btn = ttk.Button(button_row, text="标注无效管并校正管径", command=self.mark_invalid_and_correct_diameters)
        self.mark_invalid_btn.pack(side="left", expand=True, fill="x", padx=2)
        
        self.delete_invalid_btn = ttk.Button(button_row, text="删除无效管", command=self.delete_invalid_pipes)
        self.delete_invalid_btn.pack(side="left", expand=True, fill="x", padx=2)
        
        # 隐藏无效管和显示前后遮挡复选框（第一行）
        check_row = ttk.Frame(pipe_op_frame)
        check_row.pack(fill="x", pady=2)
        self.hide_invalid_var = tk.BooleanVar(value=False)
        self.hide_invalid_cb = ttk.Checkbutton(check_row, text="隐藏无效管", variable=self.hide_invalid_var, command=self._on_hide_invalid_toggle)
        self.hide_invalid_cb.pack(side="left", padx=2)
        self.show_occlusion_cb = ttk.Checkbutton(check_row, text="显示前后遮挡", variable=self.show_occlusion_var, command=self.redraw)
        self.show_occlusion_cb.pack(side="left", padx=2)

        # 校正或优化管径和消火栓支管向左展开（第二行）
        check_row2 = ttk.Frame(pipe_op_frame)
        check_row2.pack(fill="x", pady=2)
        self.velocity_check_cb = ttk.Checkbutton(check_row2, text="校正或优化管径",
                                                  variable=self.velocity_check_var,
                                                  command=self.redraw,
                                                  state="disabled")
        self.velocity_check_cb.pack(side="left", padx=2)
        self.hydrant_flat_cb = ttk.Checkbutton(check_row2, text="消火栓支管向左展开",
                                                variable=self.hydrant_branch_flat_var,
                                                command=self.redraw)
        self.hydrant_flat_cb.pack(side="left", padx=2)

        # 路径高亮   
        path_frame = ttk.LabelFrame(parent, text="路径高亮", padding=5)
        path_frame.pack(fill="x", padx=5, pady=5)

        self.path_var = tk.StringVar()
        self.path_combo = ttk.Combobox(path_frame, textvariable=self.path_var,
                                        values=[], state="readonly")
        self.path_combo.pack(fill="x")
        self.path_combo.bind("<<ComboboxSelected>>", self.on_path_selected)

        # 罗盘（仅整体管网模式下可见）
        self.compass_frame = ttk.LabelFrame(parent, text="视角方向", padding=5)
        try:
            bg_color = self.winfo_toplevel().cget("background")
        except:
            bg_color = "SystemButtonFace"
        self.compass_canvas = tk.Canvas(self.compass_frame, width=120, height=120,
                                        bg=bg_color, highlightthickness=0)
        self.compass_canvas.pack()
        self.compass_canvas.bind("<Button-1>", self.on_compass_click)
        
        # 高度角控制行
        elevation_frame = ttk.Frame(self.compass_frame)
        elevation_frame.pack(fill="x", pady=5)
        ttk.Label(elevation_frame, text="高度角:").pack(side="left", padx=(5,2))
        self.elevation_entry = ttk.Entry(elevation_frame, textvariable=self.global_view_elevation_var, width=8)
        self.elevation_entry.pack(side="left", padx=2)
        ttk.Button(elevation_frame, text="复原", command=self.reset_elevation, width=6).pack(side="left", padx=2)
        # 新增：分层颜色按钮
        ttk.Button(elevation_frame, text="分层颜色", command=self.show_layer_color_dialog, width=8).pack(side="left", padx=5)

        # 绑定焦点离开事件，实时更新
        self.elevation_entry.bind("<FocusOut>", self.on_elevation_changed)
        self.elevation_entry.bind("<Return>", self.on_elevation_changed)
        
        # 初始隐藏，切到整体管网时才显示
        self.compass_frame.pack_forget()

        note = ttk.Label(parent, text="左键点击管道/阀门选择\n右键弹出菜单",
                         justify="left", foreground="gray")
        note.pack(side="bottom", pady=10)
        # 初始化无效管相关控件和消火栓支管展开复选框的状态
        self.update_invalid_controls_state()
        self._update_hydrant_flat_state()

    def update_invalid_controls_state(self):
        """根据当前系统类型更新无效管/喷淋相关控件的启用/禁用状态"""
        config = self.config_manager.get_live_config()
        system_type = config.get("system_type", "outdoor_hydrant")
        is_indoor = (system_type == "indoor_hydrant")
        state = "normal" if is_indoor else "disabled"
        self.mark_invalid_btn.config(state=state)
        self.delete_invalid_btn.config(state=state)
        self.hide_invalid_cb.config(state=state)

        # 喷淋按钮可见性
        if system_type == "sprinkler":
            self.sprinkler_table_btn.pack(fill="x", pady=2, before=self.check_frame)
            self.assign_diameter_btn.pack(fill="x", pady=2, before=self.check_frame)
        else:
            self.sprinkler_table_btn.pack_forget()
            self.assign_diameter_btn.pack_forget()

    def _update_hydrant_flat_state(self):
        """根据当前视图模式更新消火栓支管向左展开复选框状态（仅整体管网可用）"""
        if self.current_view_mode == "global":
            self.hydrant_flat_cb.config(state="normal")
        else:
            self.hydrant_flat_cb.config(state="disabled")

    def _on_hide_invalid_toggle(self):
        """隐藏无效管复选框的回调：自动清除当前选中集中已变为无效的管道"""
        if self.hide_invalid_var.get():
            # 从选中集中移除无效管道
            self.selected_pipes = {pid for pid in self.selected_pipes
                                if pid in self.cad_data_manager.pipe_by_id
                                and self.cad_data_manager.pipe_by_id[pid].is_active}
        self.redraw()


    # ----------------------------------------------------------------------
    # 坐标转换（单位毫米，不转换单位）
    # ----------------------------------------------------------------------
    def project_point(self, x_mm: float, y_mm: float, z_mm: float) -> Tuple[float, float]:
        if self.current_view_mode == "global":
            cx, cy, cz = self.compute_network_centroid()
            tx = x_mm - cx
            ty = y_mm - cy
            tz = z_mm - cz

            azimuth = math.radians(self.global_view_angle)      # 摄像机方位角（正北0°）
            elevation = math.radians(self.global_view_elevation)  # 仰角

            # 旋转矩阵：使摄像机位于 azimuth 方向，指向原点
            # 方法：先绕Z轴旋转 -azimuth，使摄像机位于 -Y 方向，再绕X轴旋转 elevation
            cos_a = math.cos(azimuth)
            sin_a = math.sin(azimuth)
            cos_e = math.cos(elevation)
            sin_e = math.sin(elevation)

            # 第一步：绕Z旋转 -azimuth
            x1 = tx * cos_a + ty * sin_a
            y1 = -tx * sin_a + ty * cos_a
            z1 = tz

            # 第二步：绕X旋转 elevation (俯仰)
            x2 = x1
            y2 = y1 * cos_e + z1 * sin_e

            # 屏幕坐标系：x2 为水平，y2 为垂直（但tkinter Y轴向下，取反）
            return x2, -y2

        # 以下原有楼层视图代码不变
        view = self.VIEWS[self.current_view]
        if view["type"] == "ortho":
            if self.current_view == "俯视":
                return x_mm, -y_mm
            else:
                return x_mm, -y_mm
        else:
            angle_h, angle_v = view["angle"]
            rad_h = math.radians(angle_h)
            rad_v = math.radians(angle_v)
            x1 = x_mm * math.cos(rad_h) - y_mm * math.sin(rad_h)
            y1 = x_mm * math.sin(rad_h) * math.sin(rad_v) + \
                y_mm * math.cos(rad_h) * math.sin(rad_v) + \
                z_mm * math.cos(rad_v)
            return x1, y1

    def compute_depth(self, x_mm: float, y_mm: float, z_mm: float) -> float:
        """计算节点在当前视角下的深度（用于前后遮挡判断）"""
        if self.current_view_mode != "global":
            return 0.0  # 楼层视图不需要深度
        
        azimuth = math.radians(self.global_view_angle)
        elevation = math.radians(self.global_view_elevation)
        sin_a = math.sin(azimuth)
        cos_a = math.cos(azimuth)
        sin_e = math.sin(elevation)
        cos_e = math.cos(elevation)
        
        # 深度公式：z2 = (tx * sin_a - ty * cos_a) * sin_e + tz * cos_e
        # 这里使用绝对坐标即可，质心偏移在比较时会被抵消
        depth = (x_mm * sin_a - y_mm * cos_a) * sin_e + z_mm * cos_e
        return depth

    def update_projection(self):
        """为所有节点计算投影坐标和深度（世界坐标，毫米）"""
        self.projected_coords.clear()
        self.projected_depth.clear()
        for node in self.cad_data_manager.nodes:
            px, py = self.project_point(node.x, node.y, node.z)
            depth = self.compute_depth(node.x, node.y, node.z)
            self.projected_coords[node.node_id] = (px, py)
            self.projected_depth[node.node_id] = depth
        # 投影更新后，遮挡缓存失效
        self.occlusion_cache_valid = False

    def build_occlusion_cache(self):
        """构建遮挡关系缓存：检测二维相交，比较三维深度，记录后方管线的断开参数"""
        if self.current_view_mode != "global":
            self.occlusion_breaks.clear()
            self.occlusion_cache_valid = True
            return
        
        self.occlusion_breaks.clear()
        pipes = self.cad_data_manager.pipes
        n = len(pipes)
        if n < 2:
            self.occlusion_cache_valid = True
            return
        
        # 预先提取所有管线的投影坐标和端点深度
        pipe_proj = {}
        pipe_depth = {}
        for pipe in pipes:
            start_w = self.projected_coords.get(pipe.start_node_id)
            end_w = self.projected_coords.get(pipe.end_node_id)
            d_s = self.projected_depth.get(pipe.start_node_id)
            d_e = self.projected_depth.get(pipe.end_node_id)
            if start_w and end_w and d_s is not None and d_e is not None:
                pipe_proj[pipe.pipe_id] = (start_w, end_w)
                pipe_depth[pipe.pipe_id] = (d_s, d_e)
        
        # 遍历所有管线对，检测相交与遮挡
        for i in range(n):
            pipe1 = pipes[i]
            proj1 = pipe_proj.get(pipe1.pipe_id)
            depth1 = pipe_depth.get(pipe1.pipe_id)
            if not proj1 or not depth1:
                continue
            p1_start, p1_end = proj1
            d1_s, d1_e = depth1
            
            for j in range(i + 1, n):
                pipe2 = pipes[j]
                proj2 = pipe_proj.get(pipe2.pipe_id)
                depth2 = pipe_depth.get(pipe2.pipe_id)
                if not proj2 or not depth2:
                    continue
                
                # 新增：检查是否共享节点（3D中相连），如果相连则不处理断开
                # 因为拓扑相连的管道在视觉上连通是正确的，不应断开
                if pipe1.start_node_id == pipe2.start_node_id or \
                   pipe1.start_node_id == pipe2.end_node_id or \
                   pipe1.end_node_id == pipe2.start_node_id or \
                   pipe1.end_node_id == pipe2.end_node_id:
                    continue
                                
                p2_start, p2_end = proj2
                d2_s, d2_e = depth2
                
                # 检查2D投影是否相交
                intersection = self.segment_intersection(p1_start, p1_end, p2_start, p2_end)
                if intersection:
                    t1, t2 = intersection
                    # 计算交点处的三维深度
                    d1 = d1_s + t1 * (d1_e - d1_s)
                    d2 = d2_s + t2 * (d2_e - d2_s)
                    
                    # 比较深度，深度值越大表示越靠近观察者（在前面）
                    if d1 > d2:  # pipe1 在前面，遮挡 pipe2
                        self.occlusion_breaks.setdefault(pipe2.pipe_id, []).append((t2, pipe1.pipe_id))
                    elif d2 > d1:  # pipe2 在前面，遮挡 pipe1
                        self.occlusion_breaks.setdefault(pipe1.pipe_id, []).append((t1, pipe2.pipe_id))
        
        self.occlusion_cache_valid = True

    def segment_intersection(self, p1, p2, p3, p4):
        """计算两条2D线段的相交参数 (t1, t2)，包含端点相交，若不相交返回 None"""
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = p3
        x4, y4 = p4
        
        dx1 = x2 - x1
        dy1 = y2 - y1
        dx2 = x4 - x3
        dy2 = y4 - y3
        
        denom = dx1 * dy2 - dy1 * dx2
        if abs(denom) < 1e-10:
            return None  # 平行或共线
        
        t1 = ((x3 - x1) * dy2 - (y3 - y1) * dx2) / denom
        t2 = ((x3 - x1) * dy1 - (y3 - y1) * dx1) / denom
        
        # 放宽条件，包含端点相交（0 <= t <= 1），以处理端点重合的遮挡
        if 0 <= t1 <= 1 and 0 <= t2 <= 1:
            return (t1, t2)
        return None

    def merge_intervals(self, intervals):
        """合并重叠或相邻的断开区间"""
        if not intervals:
            return []
        intervals.sort(key=lambda x: x[0])
        merged = [list(intervals[0])]
        for current in intervals[1:]:
            last = merged[-1]
            if current[0] <= last[1]:
                last[1] = max(last[1], current[1])
            else:
                merged.append(list(current))
        return merged

    def get_draw_segments(self, start, end, merged_breaks):
        """根据合并后的断开区间，生成需要绘制的连续片段"""
        segments = []
        current = start
        for brk in merged_breaks:
            if brk[0] > current:
                segments.append((current, brk[0]))
            current = max(current, brk[1])
        if current < end:
            segments.append((current, end))
        return segments

    def _is_pipe_active(self, pipe_id):
        """检查管道是否有效（未被标记为无效，即隐藏无效管时该管道仍然可见）"""
        pipe = self.cad_data_manager.pipe_by_id.get(pipe_id)
        return pipe is not None and pipe.is_active

    def world_to_canvas(self, wx: float, wy: float) -> Tuple[float, float]:
        return wx * self.scale + self.translate_x, wy * self.scale + self.translate_y

    def auto_center(self):
        """根据所有节点投影自动设置缩放和平移，使管网适应画布"""
        if not self.projected_coords:
            return
        xs = [wx for wx, wy in self.projected_coords.values()]
        ys = [wy for wx, wy in self.projected_coords.values()]
        if not xs:
            return
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        if max_x - min_x < 1e-6:
            return
        self.update_idletasks()
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        if canvas_width <= 1:
            canvas_width = 800
            canvas_height = 600
        margin = 0.1
        range_x = max_x - min_x
        range_y = max_y - min_y
        if range_x == 0:
            range_x = 1
        if range_y == 0:
            range_y = 1
        scale_x = (canvas_width * (1 - 2*margin)) / range_x
        scale_y = (canvas_height * (1 - 2*margin)) / range_y
        self.scale = min(scale_x, scale_y)
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        self.translate_x = canvas_width/2 - center_x * self.scale
        self.translate_y = canvas_height/2 - center_y * self.scale

    def compute_network_centroid(self):
        """
        计算所有节点的三维质心（毫米），作为等轴测旋转中心。
        若无节点，返回原点 (0,0,0)。
        """
        nodes = self.cad_data_manager.nodes
        if not nodes:
            return 0.0, 0.0, 0.0
        total = len(nodes)
        sum_x = sum(n.x for n in nodes)
        sum_y = sum(n.y for n in nodes)
        sum_z = sum(n.z for n in nodes)
        return sum_x / total, sum_y / total, sum_z / total

    # ----------------------------------------------------------------------
    # 连通性计算（基于阀门状态）
    # ----------------------------------------------------------------------
    def compute_reachability(self):
        """从所有供水点出发，BFS遍历开启的管道，标记可到达的管道"""
        closed_pipes = set()
        for valve in self.cad_data_manager.valves:
            if valve.status == "CLOSED":
                closed_pipes.add(valve.pipe_id)

        adj = {}
        for pipe in self.cad_data_manager.pipes:
            if pipe.status == "关":
                closed_pipes.add(pipe.pipe_id)
                continue
            n1, n2 = pipe.start_node_id, pipe.end_node_id
            if n1 not in adj:
                adj[n1] = []
            if n2 not in adj:
                adj[n2] = []
            adj[n1].append((n2, pipe.pipe_id))
            adj[n2].append((n1, pipe.pipe_id))

        start_nodes = set()
        for supply in self.cad_data_manager.supply_nodes:
            start_nodes.update(supply.node_ids)

        from collections import deque
        reachable_nodes = set(start_nodes)
        reachable_pipes = set()
        q = deque(start_nodes)
        while q:
            node = q.popleft()
            for nbr, pid in adj.get(node, []):
                if pid in closed_pipes:
                    continue
                if nbr not in reachable_nodes:
                    reachable_nodes.add(nbr)
                    q.append(nbr)
                if pid not in reachable_pipes:
                    reachable_pipes.add(pid)

        self.reachable_pipes = reachable_pipes

    # ----------------------------------------------------------------------
    # 接收计算结果
    # ----------------------------------------------------------------------
    def set_calculation_results(self, pipe_results: Dict[str, Dict]):
        logger.info(f"预览页面 set_calculation_results 被调用，收到 {len(pipe_results)} 条管道结果")
        self.pipe_results = pipe_results
        self.calculation_available = True
        self.flow_check.config(state="normal")
        self.loss_check.config(state="normal")
        self.arrow_check.config(state="normal")
        self.velocity_check.config(state="normal")
        self.node_pressure_check.config(state="normal")
        config = self.config_manager.get_live_config()
        self.velocity_max = config.get("max_velocity", 5.0)
        self.velocity_min = config.get("min_velocity", 1.0)
        self.velocity_check_cb.config(state="normal")
        self.redraw()

    def set_node_pressures(self, node_pressures: Dict[str, float]):
        """接收计算页面传递的节点压力结果"""
        self.node_pressures = node_pressures
        self.redraw()

    def set_node_flows(self, node_flows: Dict[str, float]):
        """接收计算页面传递的节点流量结果"""
        self.node_flows = node_flows

    # ----------------------------------------------------------------------
    # 绘制
    # ----------------------------------------------------------------------
    def redraw(self):
        if not self.cad_data_manager.is_loaded:
            if self.canvas is not None and self.canvas.winfo_exists():
                self.canvas.delete("all")
                self.canvas.create_text(400, 300, text="请先在设置页面加载CAD数据",
                                         fill="white", font=("Arial", 20))
            return
        if self.canvas is None or not self.canvas.winfo_exists():
            return
        self.canvas.delete("all")
        
        # ----- 获取当前楼层名称 -----
        current_tab_name = None
        if self.floor_notebook and self.floor_notebook.tabs():
            current_tab = self.floor_notebook.select()
            if current_tab:
                current_tab_name = self.floor_notebook.tab(current_tab, "text")
        if not current_tab_name:
            current_tab_name = self.current_floor_name
        if not current_tab_name:
            current_tab_name = "单层"
        
        # 整体管网模式：绘制全部元素 + 罗盘
        if self.current_view_mode == "global":
            self._draw_global_network()
            # 更新罗盘绘制
            self.draw_compass()
            return
        
        # 普通楼层视图：隐藏罗盘
        if self.compass_frame.winfo_manager() != "":
            self.compass_frame.pack_forget()
                
        # ----- 获取当前楼层的管道和节点 -----
        pipes_to_draw = []
        nodes_to_draw = []
        # 确定实际要显示的楼层名
        display_floor_name = current_tab_name
        canvas = self._current_canvas
        if canvas and hasattr(canvas, 'actual_floors'):
            display_floor_name = canvas.current_display_floor
                    
        if display_floor_name != "单层":
            floor = self.cad_data_manager.floor_by_name.get(display_floor_name)
            if floor:
                pipes_to_draw = floor.pipes
                nodes_to_draw = floor.nodes
            else:
                # 降级：绘制全部
                pipes_to_draw = self.cad_data_manager.pipes
                nodes_to_draw = self.cad_data_manager.nodes
                logger.warning(f"未找到楼层 {current_tab_name}，使用全部管道")
        else:
            pipes_to_draw = self.cad_data_manager.pipes
            nodes_to_draw = self.cad_data_manager.nodes
        
        # ----- 必须投影该楼层所有管道端点，否则阀门、消火栓等可能绘制失败 -----
        need_proj_ids = set()
        for pipe in pipes_to_draw:
            need_proj_ids.add(pipe.start_node_id)
            need_proj_ids.add(pipe.end_node_id)
        # 同时保留原有节点（显示用），但投影仅需管道端点
        for node in nodes_to_draw:
            need_proj_ids.add(node.node_id)
        self.projected_coords.clear()
        for nid in need_proj_ids:
            node = self.cad_data_manager.node_by_id.get(nid)
            if node:
                px, py = self.project_point(node.x, node.y, node.z)
                self.projected_coords[nid] = (px, py)
        
        # 绘制管道
        for pipe in pipes_to_draw:
            if self.hide_invalid_var.get() and not pipe.is_active:
                continue   # 隐藏无效管道
            self.draw_pipe(pipe)
        
        # 绘制阀门（只绘制当前楼层的）
        for valve in self.cad_data_manager.valves:
            if valve.floor_name == display_floor_name or (display_floor_name == "单层" and not valve.floor_name):
                self.draw_valve(valve)
        
        # 绘制供水点和用水点（现在 self.projected_coords 只包含当前楼层节点，draw_supply_demand 中的过滤会自动生效）
        self.draw_supply_demand()
        self.draw_sprinklers()
        
        # 绘制节点（可选，节点编号或节点压力勾选时显示）
        if self.show_node_ids.get() or self.show_node_pressure.get():
            for node in nodes_to_draw:
                self.draw_node(node)
        
        # 绘制消火栓（只绘制当前楼层的，基于坐标，不依赖节点）
        if display_floor_name != "整体管网":
            floor = self.cad_data_manager.floor_by_name.get(display_floor_name) if display_floor_name != "单层" else None
            if floor:
                for hydrant in floor.hydrants:
                    self.draw_hydrant_by_coords(hydrant)   # 使用新函数
            elif display_floor_name == "单层":
                for hydrant in self.cad_data_manager.hydrants:
                    if not hasattr(hydrant, 'hydrant_id'):   # 或 isinstance(hydrant, HydrantData)
                        # logger.warning(f"跳过非消火栓对象: {type(hydrant)}")
                        continue
                    self.draw_hydrant(hydrant)
        # 整体管网模式已在 _draw_global_network 中绘制所有消火栓（调用 draw_hydrant，依赖节点）
        
        # 绘制立管（只绘制当前楼层的）
        for riser in self.cad_data_manager.risers:
            if riser.floor_name == display_floor_name or (display_floor_name == "单层" and not riser.floor_name):
                self.draw_riser(riser)

        # 绘制左下角固定文字（通过独立方法处理）
        self._draw_floor_info_text()

    def _draw_global_network(self):
        """绘制整体管网（所有楼层元素 + 罗盘）"""
        if self._separation_applied:
            self._draw_global_network_separated()
            return
        canvas = self._current_canvas
        if not canvas or not canvas.winfo_exists():
            return
        canvas.delete("all")

        # ----- 投影缓存：视角变化时重算，缩放/平移零计算开销 -----
        cache_key = (round(self.global_view_angle, 2), round(self.global_view_elevation, 2))
        cache_miss = getattr(self, '_global_cache_key', None) != cache_key

        if cache_miss:
            _cx, _cy, _cz = self.compute_network_centroid()
            _az = math.radians(self.global_view_angle)
            _el = math.radians(self.global_view_elevation)
            _ca, _sa = math.cos(_az), math.sin(_az)
            _ce, _se = math.cos(_el), math.sin(_el)

            def _fast_proj(x, y, z):
                tx, ty, tz = x-_cx, y-_cy, z-_cz
                x1 = tx*_ca + ty*_sa
                y1 = -tx*_sa + ty*_ca
                return x1, -(y1*_ce + tz*_se)

            def _fast_depth(x, y, z):
                return (x*_sa - y*_ca)*_se + z*_ce

            _proj = {}
            _depth = {}
            for node in self.cad_data_manager.nodes:
                _proj[node.node_id] = _fast_proj(node.x, node.y, node.z)
                _depth[node.node_id] = _fast_depth(node.x, node.y, node.z)

            self._global_projected_coords = _proj
            self._global_projected_depth = _depth
            self._global_cache_key = cache_key
            self.occlusion_cache_valid = False

        self.projected_coords = self._global_projected_coords
        self.projected_depth = self._global_projected_depth

        # 消火栓支管向左展开（复选框控制）
        if self.hydrant_branch_flat_var.get():
            self._build_hydrant_visual_offsets()
        else:
            self._hydrant_visual_offsets = None

        # 遮挡处理
        if self.show_occlusion_var.get():
            if not self.occlusion_cache_valid:
                self.build_occlusion_cache()
        else:
            self.occlusion_breaks.clear()
            self.occlusion_cache_valid = True

        # 构建从 R_ 管道ID到立管对象的映射（用于重复立管高亮）
        self.riser_by_pipe_id = {}
        for riser in self.cad_data_manager.risers:
            self.riser_by_pipe_id[riser.riser_id] = riser  

        # 绘制管道
        for pipe in self.cad_data_manager.pipes:
            if self.hide_invalid_var.get() and not pipe.is_active:
                continue
            self.draw_pipe(pipe)

        # 绘制阀门
        for valve in self.cad_data_manager.valves:
            self.draw_valve(valve)

        # 绘制供水点和用水点
        self.draw_supply_demand()
        self.draw_sprinklers()

        # 节点编号（可选）
        if self.show_node_ids.get() or self.show_node_pressure.get():
            for node in self.cad_data_manager.nodes:
                self.draw_node(node)

        # 消火栓
        for hydrant in self.cad_data_manager.hydrants:
            if not hasattr(hydrant, 'hydrant_id'):
                continue
            self.draw_hydrant(hydrant)

        # 绘制颜色图例表（如果启用分层颜色）
        self.draw_color_legend()    
        # 清理消火栓支管视觉偏移
        self._hydrant_visual_offsets = None

    def _build_hydrant_visual_offsets(self):
        """构建 B_ 消火栓支管末端节点的视觉偏移映射 {end_node_id: start_node_id}"""
        self._hydrant_visual_offsets = {}
        for pipe in self.cad_data_manager.pipes:
            if pipe.pipe_id.startswith('B_') and getattr(pipe, 'is_hydrant_branch', False):
                self._hydrant_visual_offsets[pipe.end_node_id] = pipe.start_node_id

    # ======================================================================
    # 以下三个方法实现楼层分离显示（需求94-111）
    # 均为新增，不修改任何已有绘图函数
    # ======================================================================

    def _build_separation_transforms(self):
        """构建分离显示所需映射。XY-based pipe_floor_map 为主（含 R_xxx_A/B 和 B_xxxx），Z值匹配为兜底。
        返回: (pipe_to_floor, node_to_floors, cumulative_offsets_mm, floor_elev_order)
        """
        # 0. 单位换算因子
        drawing_unit = self.config_manager.get_live_config().get("drawing_unit", "毫米")
        to_mm = {"毫米": 1000.0, "厘米": 10.0}.get(drawing_unit, 1.0)

        # 1. XY-based pipe→floor 映射为主（cad_data_manager 已确保所有管道被包含）
        self._build_pipe_floor_map()
        pipe_to_floor = dict(self.pipe_floor_map)

        # 2. Z-based node→floor（用于 primary_sep_coords 和兜底）
        node_to_floors = {}
        for node in self.cad_data_manager.nodes:
            for floor in self.cad_data_manager.floors:
                if abs(node.z - floor.pipe_z_offset * to_mm) < 0.1:
                    if node.node_id not in node_to_floors:
                        node_to_floors[node.node_id] = set()
                    node_to_floors[node.node_id].add(floor.name)
        # 2b. 未匹配节点取最近楼层（3m容差）
        for node in self.cad_data_manager.nodes:
            if node.node_id in node_to_floors:
                continue
            best_f, best_d = None, float('inf')
            for f_obj in self.cad_data_manager.floors:
                d = abs(node.z - f_obj.pipe_z_offset * to_mm)
                if d < best_d:
                    best_d, best_f = d, f_obj.name
            if best_d < 3000.0:
                node_to_floors[node.node_id] = {best_f}

        # 3. Z-based兜底：仅对 XY 映射中缺失的管道
        floor_elev = {f.name: f.elevation for f in self.cad_data_manager.floors}
        for pipe in self.cad_data_manager.pipes:
            if pipe.pipe_id in pipe_to_floor:
                continue
            s_floors = node_to_floors.get(pipe.start_node_id, set())
            e_floors = node_to_floors.get(pipe.end_node_id, set())
            all_floors = s_floors | e_floors
            if not all_floors:
                continue
            if len(all_floors) == 1:
                pipe_to_floor[pipe.pipe_id] = next(iter(all_floors))
            else:
                sorted_f = sorted(all_floors, key=lambda fn: floor_elev.get(fn, 0))
                if pipe.pipe_id.startswith('L_'):
                    pipe_to_floor[pipe.pipe_id] = sorted_f[0]
                elif pipe.pipe_id.startswith('R_'):
                    pipe_to_floor[pipe.pipe_id] = sorted_f[-1]
                else:
                    pipe_to_floor[pipe.pipe_id] = sorted_f[0]

        # 4. 楼层标高升序
        sorted_pairs = sorted(
            [(f.name, f.elevation) for f in self.cad_data_manager.floors],
            key=lambda x: x[1]
        )
        floor_elev_order = [name for name, _ in sorted_pairs]

        # 5. 累计分离偏移（排除最低楼层，需求111）
        cumulative_offsets_mm = {}
        running_sum = 0.0
        for idx, floor_name in enumerate(floor_elev_order):
            if idx > 0:
                running_sum += self.separation_values.get(floor_name, 0.0)
            cumulative_offsets_mm[floor_name] = running_sum * to_mm

        return pipe_to_floor, node_to_floors, cumulative_offsets_mm, floor_elev_order

    def _draw_global_network_separated(self):
        """绘制带楼层分离效果的整体管网（需求96-110）"""
        canvas = self._current_canvas
        if not canvas or not canvas.winfo_exists():
            return
        canvas.delete("all")

        pipe_to_floor, node_to_floors, cumulative_offsets_mm, floor_elev_order = \
            self._build_separation_transforms()
        node_by_id = self.cad_data_manager.node_by_id
        pipe_by_id = self.cad_data_manager.pipe_by_id

        self.riser_by_pipe_id = {}
        for riser in self.cad_data_manager.risers:
            self.riser_by_pipe_id[riser.riser_id] = riser

        # --- 缓存：分离值或视角改变才重算世界坐标 ---
        sep_fp = tuple(sorted(self.separation_values.items()))
        cache_key = (sep_fp,
                     round(self.global_view_angle, 2),
                     round(self.global_view_elevation, 2))
        cache_miss = getattr(self, '_sep_cache_key', None) != cache_key

        _orig_proj = self.project_point
        _orig_depth = self.compute_depth
        try:
            _cx, _cy, _cz = self.compute_network_centroid()
            _az = math.radians(self.global_view_angle)
            _el = math.radians(self.global_view_elevation)
            _ca, _sa = math.cos(_az), math.sin(_az)
            _ce, _se = math.cos(_el), math.sin(_el)

            def fast_proj(x, y, z):
                tx, ty, tz = x-_cx, y-_cy, z-_cz
                x1 = tx*_ca + ty*_sa
                y1 = -tx*_sa + ty*_ca
                return x1, -(y1*_ce + tz*_se)

            self.project_point = fast_proj

            def fast_depth(x, y, z):
                return (x*_sa - y*_ca)*_se + z*_ce

            self.compute_depth = fast_depth

            proj_cache = {}
            def cached_proj(node, z_off):
                key = (node.node_id, z_off)
                if key not in proj_cache:
                    proj_cache[key] = fast_proj(node.x, node.y, node.z + z_off)
                return proj_cache[key]

            if cache_miss:
                self._sep_cache_key = cache_key

                pipe_endpoints = {}
                pipe_depth_data = {}
                for pipe in self.cad_data_manager.pipes:
                    if self.hide_invalid_var.get() and not pipe.is_active:
                        continue
                    pipe_floor = pipe_to_floor.get(pipe.pipe_id)
                    offset = cumulative_offsets_mm.get(pipe_floor, 0.0) if pipe_floor else 0.0
                    sn = node_by_id.get(pipe.start_node_id)
                    en = node_by_id.get(pipe.end_node_id)
                    if not sn or not en:
                        continue
                    sp = cached_proj(sn, offset)
                    ep = cached_proj(en, offset)
                    sd = fast_depth(sn.x, sn.y, sn.z + offset)
                    ed = fast_depth(en.x, en.y, en.z + offset)
                    pipe_endpoints[pipe.pipe_id] = (sp, ep)
                    pipe_depth_data[pipe.pipe_id] = (sd, ed)

                primary_sep_coords = {}
                for node in self.cad_data_manager.nodes:
                    floors = node_to_floors.get(node.node_id, set())
                    best_off = max((cumulative_offsets_mm.get(fn, 0.0) for fn in floors), default=0.0)
                    primary_sep_coords[node.node_id] = cached_proj(node, best_off)

                self._sep_pipe_endpoints = pipe_endpoints
                self._sep_pipe_depth_data = pipe_depth_data
                self._sep_primary_sep_coords = primary_sep_coords
                self.occlusion_cache_valid = False
            else:
                pipe_endpoints = self._sep_pipe_endpoints
                pipe_depth_data = self._sep_pipe_depth_data
                primary_sep_coords = self._sep_primary_sep_coords

            if self.show_occlusion_var.get():
                if not self.occlusion_cache_valid:
                    self._build_pipe_occlusion_cache(pipe_endpoints, pipe_depth_data)
            else:
                self.occlusion_breaks.clear()
                self.occlusion_cache_valid = True

            self.projected_coords = primary_sep_coords.copy()

            # 消火栓支管向左展开（复选框控制）
            if self.hydrant_branch_flat_var.get():
                self._build_hydrant_visual_offsets()
            else:
                self._hydrant_visual_offsets = None

            for pipe in self.cad_data_manager.pipes:
                if self.hide_invalid_var.get() and not pipe.is_active:
                    continue
                pe = pipe_endpoints.get(pipe.pipe_id)
                if not pe:
                    continue
                sp, ep = pe
                old_s = self.projected_coords.get(pipe.start_node_id)
                old_e = self.projected_coords.get(pipe.end_node_id)
                self.projected_coords[pipe.start_node_id] = sp
                self.projected_coords[pipe.end_node_id] = ep
                try:
                    self.draw_pipe(pipe)
                finally:
                    if old_s is not None:
                        self.projected_coords[pipe.start_node_id] = old_s
                    if old_e is not None:
                        self.projected_coords[pipe.end_node_id] = old_e

            for valve in self.cad_data_manager.valves:
                floor_name = valve.floor_name
                offset = cumulative_offsets_mm.get(floor_name, 0.0) if floor_name else 0.0
                saved_coords = {}
                if valve.pipe_id and valve.pipe_id in pipe_by_id:
                    pipe_v = pipe_by_id[valve.pipe_id]
                    s_node = node_by_id.get(pipe_v.start_node_id)
                    e_node = node_by_id.get(pipe_v.end_node_id)
                    if s_node and e_node:
                        p_floor = pipe_to_floor.get(pipe_v.pipe_id, floor_name)
                        p_off = cumulative_offsets_mm.get(p_floor, offset) if p_floor else offset
                        spx, spy = cached_proj(s_node, p_off)
                        epx, epy = cached_proj(e_node, p_off)
                        saved_coords[pipe_v.start_node_id] = self.projected_coords.get(pipe_v.start_node_id)
                        saved_coords[pipe_v.end_node_id] = self.projected_coords.get(pipe_v.end_node_id)
                        self.projected_coords[pipe_v.start_node_id] = (spx, spy)
                        self.projected_coords[pipe_v.end_node_id] = (epx, epy)
                orig_z = valve.z
                valve.z = valve.z + offset
                try:
                    self.draw_valve(valve)
                finally:
                    valve.z = orig_z
                    for nid, old_val in saved_coords.items():
                        if old_val is not None:
                            self.projected_coords[nid] = old_val

            self.draw_supply_demand()
            self.draw_sprinklers()

            node_connected_floors = {}
            for node in self.cad_data_manager.nodes:
                cps = getattr(node, 'connected_pipes', []) or []
                fl_set = set()
                for pid in cps:
                    fn = pipe_to_floor.get(pid)
                    if fn:
                        fl_set.add(fn)
                if fl_set:
                    node_connected_floors[node.node_id] = fl_set

            if self.show_node_ids.get() or self.show_node_pressure.get():
                drawn = set()
                for node in self.cad_data_manager.nodes:
                    floors = node_connected_floors.get(node.node_id, set())
                    if not floors:
                        self.draw_node(node)
                        continue
                    for fn in floors:
                        off = cumulative_offsets_mm.get(fn, 0.0)
                        key = (node.node_id, round(off, 1))
                        if key in drawn:
                            continue
                        drawn.add(key)
                        lx, ly = cached_proj(node, off)
                        old_val = self.projected_coords.get(node.node_id)
                        self.projected_coords[node.node_id] = (lx, ly)
                        try:
                            self.draw_node(node)
                        finally:
                            if old_val is not None:
                                self.projected_coords[node.node_id] = old_val

            for hydrant in self.cad_data_manager.hydrants:
                if not hasattr(hydrant, 'hydrant_id'):
                    continue
                floor_name = hydrant.floor_name
                offset = cumulative_offsets_mm.get(floor_name, 0.0) if floor_name else 0.0
                an = node_by_id.get(hydrant.node_id)
                if not an:
                    continue
                hx, hy = cached_proj(an, offset)
                old_val = self.projected_coords.get(hydrant.node_id)
                self.projected_coords[hydrant.node_id] = (hx, hy)
                try:
                    self.draw_hydrant(hydrant)
                finally:
                    if old_val is not None:
                        self.projected_coords[hydrant.node_id] = old_val

            self.draw_color_legend()

            self._draw_separation_dashed_lines(cumulative_offsets_mm, floor_elev_order,
                                               pipe_to_floor, node_connected_floors,
                                               pipe_endpoints, pipe_by_id)

        finally:
            self.project_point = _orig_proj
            self.compute_depth = _orig_depth
            self._hydrant_visual_offsets = None

    def _draw_separation_dashed_lines(self, cumulative_offsets_mm, floor_elev_order,
                                       pipe_to_floor, node_connected_floors,
                                       pipe_endpoints, pipe_by_id):
        """分离虚线：用 Phase1 已算好的管道端点坐标直接画线，零重算"""
        sorted_floors = sorted(self.cad_data_manager.floors, key=lambda f: f.elevation)
        # 建 (pipe_id, node_id) → (px, py) 查表
        pipe_node_proj = {}
        for pid, ((sx, sy), (ex, ey)) in pipe_endpoints.items():
            pipe = pipe_by_id.get(pid)
            if pipe:
                pipe_node_proj[(pid, pipe.start_node_id)] = (sx, sy)
                pipe_node_proj[(pid, pipe.end_node_id)] = (ex, ey)

        for i in range(len(sorted_floors) - 1):
            lo, hi = sorted_floors[i], sorted_floors[i + 1]
            off_lo = cumulative_offsets_mm.get(lo.name, 0.0)
            off_hi = cumulative_offsets_mm.get(hi.name, 0.0)
            if abs(off_hi - off_lo) < 0.001:
                continue

            for node in self.cad_data_manager.nodes:
                floors = node_connected_floors.get(node.node_id, set())
                if lo.name not in floors or hi.name not in floors:
                    continue
                cps = getattr(node, 'connected_pipes', []) or []
                l_pid = r_pid = None
                for pid in cps:
                    fn = pipe_to_floor.get(pid)
                    if fn == lo.name and pid.startswith('L_'):
                        l_pid = pid
                    if fn == hi.name and pid.startswith('R_'):
                        r_pid = pid
                if not (l_pid and r_pid):
                    continue
                lp = pipe_node_proj.get((l_pid, node.node_id))
                rp = pipe_node_proj.get((r_pid, node.node_id))
                if not lp or not rp:
                    continue
                lcx, lcy = self.world_to_canvas(*lp)
                ucx, ucy = self.world_to_canvas(*rp)
                self.canvas.create_line(lcx, lcy, ucx, ucy,
                                        fill="gray", dash=(4, 4), width=1,
                                        tags="separation_line")

    def _build_pipe_occlusion_cache(self, pipe_endpoints, pipe_depth_data):
        """基于每管端点的分离后坐标构建遮挡缓存（替代 build_occlusion_cache 的节点单坐标方案）
        pipe_endpoints: {pipe_id: ((sx,sy), (ex,ey))}  管道端点在画布上的2D坐标
        pipe_depth_data: {pipe_id: (d_s, d_e)}         管道端点3D深度
        """
        self.occlusion_breaks.clear()
        if self.hide_invalid_var.get():
            pipes = [p for p in self.cad_data_manager.pipes if p.is_active]
        else:
            pipes = list(self.cad_data_manager.pipes)
        n = len(pipes)
        if n < 2:
            self.occlusion_cache_valid = True
            return

        for i in range(n):
            pipe1 = pipes[i]
            proj1 = pipe_endpoints.get(pipe1.pipe_id)
            depth1 = pipe_depth_data.get(pipe1.pipe_id)
            if not proj1 or not depth1:
                continue
            p1_start, p1_end = proj1
            d1_s, d1_e = depth1

            for j in range(i + 1, n):
                pipe2 = pipes[j]
                proj2 = pipe_endpoints.get(pipe2.pipe_id)
                depth2 = pipe_depth_data.get(pipe2.pipe_id)
                if not proj2 or not depth2:
                    continue
                if pipe1.start_node_id == pipe2.start_node_id or \
                   pipe1.start_node_id == pipe2.end_node_id or \
                   pipe1.end_node_id == pipe2.start_node_id or \
                   pipe1.end_node_id == pipe2.end_node_id:
                    continue

                p2_start, p2_end = proj2
                d2_s, d2_e = depth2

                intersection = self.segment_intersection(p1_start, p1_end, p2_start, p2_end)
                if intersection:
                    t1, t2 = intersection
                    d1 = d1_s + t1 * (d1_e - d1_s)
                    d2 = d2_s + t2 * (d2_e - d2_s)
                    if d1 > d2:
                        self.occlusion_breaks.setdefault(pipe2.pipe_id, []).append((t2, pipe1.pipe_id))
                    elif d2 > d1:
                        self.occlusion_breaks.setdefault(pipe1.pipe_id, []).append((t1, pipe2.pipe_id))

        self.occlusion_cache_valid = True

    def on_compass_click(self, event):
        if self.current_view_mode != "global":
            return
        canvas = event.widget
        x, y = event.x, event.y
        cx, cy, r = 60, 60, 40
        dx = x - cx
        dy = y - cy
        if math.hypot(dx, dy) > r + 5:
            return

        # 计算鼠标方向角（数学标准角：0°=东，逆时针为正）
        angle_rad = math.atan2(dy, dx)
        angle_deg = math.degrees(angle_rad)
        if angle_deg < 0:
            angle_deg += 360

        # 转换为导航角（0°=北，顺时针为正）
        nav = (90 - angle_deg) % 360

        # 取扇区中心（每扇区30°）
        sector = round(nav / 15) % 24
        nav_center = sector * 15.0

        # 存储导航角用于高亮
        self.nav_angle = nav_center
        # 投影需要的角度 = 导航角（根据您的投影矩阵特性）
        self.global_view_angle = nav_center

        # 调试输出（明确打印角度基准）
        print(f"\n=== 罗盘点击调试 ===")
        print(f"鼠标偏移: dx={dx:.1f}, dy={dy:.1f}")
        print(f"数学角 (0°=东,逆时针): {angle_deg:.1f}°")
        print(f"导航角 (0°=北,顺时针): {nav:.1f}°")
        print(f"扇区: {sector}, 中心导航角: {nav_center:.1f}°")
        print(f"高亮使用导航角: {nav_center:.1f}°")
        print(f"投影使用角度: {self.global_view_angle:.1f}°")

        self.update_projection()
        self.build_occlusion_cache()
        self.redraw()

    def on_elevation_changed(self, event=None):
        """高度角输入框失去焦点或回车时调用（用户输入为与水平面夹角）"""
        try:
            user_angle = float(self.global_view_elevation_var.get())
        except ValueError:
            # 输入无效，恢复上次有效值
            current_user = 90 - self.global_view_elevation
            self.global_view_elevation_var.set(f"{current_user:.3f}")
            return
        # 限制范围 0~90 度
        if user_angle < 0:
            user_angle = 0
        elif user_angle > 90:
            user_angle = 90
        # 转换为内部角度（与垂直方向夹角）
        internal_angle = 90 - user_angle
        if abs(internal_angle - self.global_view_elevation) > 0.001:
            self.global_view_elevation = internal_angle
            # UI框保持显示用户输入的值
            self.global_view_elevation_var.set(f"{user_angle:.3f}")
            # 重新投影并重绘
            self.update_projection()
            self.build_occlusion_cache()
            self.redraw()

    def reset_elevation(self):
        """将高度角恢复为默认值（用户角度35.264°）"""
        self.global_view_elevation = 54.736   # 内部角度
        self.global_view_elevation_var.set("35.264")
        self.update_projection()
        self.build_occlusion_cache()
        self.redraw()

    def draw_compass(self):
        canvas = self.compass_canvas
        if not canvas or not canvas.winfo_exists():
            return
        canvas.delete("all")
        cx, cy, r = 60, 60, 40

        canvas.create_oval(cx - r - 5, cy - r - 5, cx + r + 5, cy + r + 5,
                        outline="white", width=1, tags="compass")

        # 高亮使用存储的导航角
        nav = getattr(self, 'nav_angle', self.global_view_angle)
        active_block = round(nav / 15) % 24
        # print(f"罗盘绘制: 导航角={nav:.1f}°, 高亮扇区={active_block}")

        for i in range(24):
            # 扇区i在罗盘上的起始角度（tkinter角度: 0°=东,顺时针增加）
            # 扇区0（正北）的tkinter起始角 = 270-15 = 255°, 为了通用: i*30 - 105
            start_angle = (i * 15 - 97.5) % 360
            fill = "red" if i == active_block else "gray"
            canvas.create_arc(cx - r, cy - r, cx + r, cy + r,
                            start=start_angle, extent=15,
                            fill=fill, outline="white", tags="compass")

        canvas.create_text(cx, cy - r - 12, text="N", fill="black",
                        font=("Arial", 8, "bold"), tags="compass")

    def draw_pipe(self, pipe):
        start_w = self.projected_coords.get(pipe.start_node_id)
        end_w = self.projected_coords.get(pipe.end_node_id)
        if not start_w or not end_w:
            return

        # B_消火栓支管视觉覆盖：从中间节点向左 0.3m（300mm）
        if getattr(self, '_hydrant_visual_offsets', None) and pipe.pipe_id.startswith('B_'):
            mid_id = self._hydrant_visual_offsets.get(pipe.end_node_id)
            if mid_id:
                mid_pos = self.projected_coords.get(mid_id)
                if mid_pos:
                    end_w = (mid_pos[0] - 300.0, mid_pos[1])

        sx, sy = self.world_to_canvas(*start_w)
        ex, ey = self.world_to_canvas(*end_w)

        # 确定颜色
        if self.velocity_check_var.get() and self.calculation_available:
            pipe_flow = self.pipe_results.get(pipe.pipe_id, {}).get('flow_lps', 0.0)
            if abs(pipe_flow) < 0.001:
                color = self.COLOR_PIPE_ZERO_FLOW
            else:
                pipe_velocity = self.pipe_results.get(pipe.pipe_id, {}).get('velocity_mps', 0.0)
                if pipe_velocity > self.velocity_max:
                    color = "red"
                elif pipe_velocity > 0 and pipe_velocity < self.velocity_min:
                    color = "blue"
                else:
                    color = self.COLOR_PIPE_VELOCITY_NORMAL
        else:
            if not pipe.is_active:
                color = "purple"   # 紫色
            elif pipe.pipe_id in self.problem_pipes:
                color = "red"
            elif pipe.pipe_id in self.highlight_path_pipes:
                color = self.COLOR_PIPE_HIGHLIGHT
            elif pipe.pipe_id in self.reachable_pipes:
                color = self.COLOR_PIPE_ACTIVE
            else:
                color = self.COLOR_PIPE_INACTIVE

        line_width = max(3, int(5 * self.scale))  # 固定像素宽度

        # 整体管网模式下，对 R_ 开头的竖向管道进行重复立管高亮（基于 CAD 立管编号）
        if not (self.velocity_check_var.get() and self.calculation_available) and self.current_view_mode == "global" and self.show_riser_warning.get() and not self.hide_invalid_var.get() and pipe.pipe_id.startswith("R_"):
            # 获取映射字典（已在 _draw_global_network 中构建）
            if hasattr(self, 'riser_by_pipe_id'):
                # 尝试用当前 pipe_id 查找，如果找不到且管道有 original_riser_id 属性，则用 original_riser_id 查找
                riser = self.riser_by_pipe_id.get(pipe.pipe_id)
                if not riser and hasattr(pipe, 'original_riser_id'):
                    riser = self.riser_by_pipe_id.get(pipe.original_riser_id)
                if riser and riser.note_number:
                    # 检查该立管是否属于重复立管（在 cad_data_manager.duplicate_risers_by_floor 中）
                    dup_dict = self.cad_data_manager.duplicate_risers_by_floor
                    floor_name = riser.floor_name
                    if floor_name in dup_dict:
                        # 判断当前 riser 对象是否在重复列表中（通过 riser_id）
                        if any(hasattr(r, 'riser_id') and r.riser_id == riser.riser_id for r in dup_dict[floor_name]):
                            color = "yellow"
                            line_width = max(3, int(5 * self.scale)) * 1.5  # 加粗为1.5倍

        # 分层颜色覆盖（优先级低于立管重复、问题管道、无效管道、高亮路径）
        if not (self.velocity_check_var.get() and self.calculation_available) and self.layer_colors_enabled.get() and not pipe.pipe_id.startswith('B_'):
            floor_name = self.pipe_floor_map.get(pipe.pipe_id)
            if floor_name and floor_name in self.floor_color_map:
                layer_color = self.floor_color_map[floor_name]
                # 仅当当前颜色不是更高优先级颜色时才覆盖
                # 更高优先级颜色: 高亮路径红色、问题管道红色、无效管道紫色、立管重复黄色
                high_priority = (color == self.COLOR_PIPE_HIGHLIGHT or color == "red" or color == "purple" or color == "yellow")
                if not high_priority:
                    color = layer_color

        # 虚线样式：选中的管道使用虚线；环路高亮覆盖（最高优先级）
        if hasattr(self, 'loop_highlight_pipe_ids') and pipe.pipe_id in self.loop_highlight_pipe_ids:
            color = "red"
            dash = (6, 3)
        else:
            dash = (4, 4) if pipe.pipe_id in self.selected_pipes else None

        # 检查是否需要断开绘制（整体管网模式且开启遮挡显示，B_管豁免）
        breaks_data = self.occlusion_breaks.get(pipe.pipe_id, [])
        if breaks_data and self.current_view_mode == "global" and self.show_occlusion_var.get() \
           and not (getattr(self, '_hydrant_visual_offsets', None) and pipe.pipe_id.startswith('B_')):
            # 如果隐藏了无效管，则过滤掉遮挡源是无效管的断点
            if self.hide_invalid_var.get():
                breaks_t = [t for t, occluder_id in breaks_data if self._is_pipe_active(occluder_id)]
            else:
                breaks_t = [t for t, _ in breaks_data]
            
            if breaks_t:
                # 计算断开宽度（管线宽度的3.5倍）
                gap_width = line_width * 3.5
                L_canvas = math.hypot(ex - sx, ey - sy)
                if L_canvas > 0:
                    delta_t = (gap_width / 2) / L_canvas
                    # 生成断开区间并限制在 [0, 1] 范围内
                    intervals = [(max(0, t - delta_t), min(1, t + delta_t)) for t in breaks_t]
                    # 合并重叠区间（支持多根前方管线遮挡导致的宽断开）
                    merged = self.merge_intervals(intervals)
                    # 生成需要绘制的连续片段
                    draw_segs = self.get_draw_segments(0, 1, merged)
                    
                    # 分段绘制管线（保持颜色、虚线等属性一致）
                    for seg_start, seg_end in draw_segs:
                        seg_sx = sx + seg_start * (ex - sx)
                        seg_sy = sy + seg_start * (ey - sy)
                        seg_ex = sx + seg_end * (ex - sx)
                        seg_ey = sy + seg_end * (ey - sy)
                        self.canvas.create_line(seg_sx, seg_sy, seg_ex, seg_ey, fill=color, width=line_width,
                                                 dash=dash, tags=("pipe", f"pipe:{pipe.pipe_id}"))
                else:
                    # 管线太短无法断开，正常绘制
                    self.canvas.create_line(sx, sy, ex, ey, fill=color, width=line_width,
                                             dash=dash, tags=("pipe", f"pipe:{pipe.pipe_id}"))
            else:
                # 所有断点均被过滤（遮挡源均为隐藏的无效管），恢复为正常绘制
                self.canvas.create_line(sx, sy, ex, ey, fill=color, width=line_width,
                                         dash=dash, tags=("pipe", f"pipe:{pipe.pipe_id}"))
        else:
            # 无断开或非整体管网模式，正常绘制
            self.canvas.create_line(sx, sy, ex, ey, fill=color, width=line_width,
                                     dash=dash, tags=("pipe", f"pipe:{pipe.pipe_id}"))

        # 提前获取流量值
        flow = 0.0
        if self.calculation_available:
            flow = self.pipe_results.get(pipe.pipe_id, {}).get('flow_lps', 0)        

        # 获取立管编号（仅对竖向管道且勾选了立管编号）
        riser_display_id = None
        if self.show_riser_id.get() and pipe.pipe_id.startswith("R_"):
            # 直接从管道对象获取立管编号（已在 CADDataManager 中赋值）
            if hasattr(pipe, 'riser_number') and pipe.riser_number:
                riser_display_id = pipe.riser_number
            else:
                # 兼容旧数据：如果 pipe 中没有 riser_number，回退到匹配查找
                for riser in self.cad_data_manager.risers:
                    if riser.riser_id == pipe.pipe_id and riser.note_number:
                        riser_display_id = riser.note_number
                        break

        if pipe.pipe_id.startswith("R_") and self.show_riser_id.get() and riser_display_id is None:
            print(f"未匹配到立管编号: pipe_id={pipe.pipe_id}")

        # 管道文字
        text_parts = []
        if self.show_pipe_id.get():
            text_parts.append(pipe.pipe_id)
            if riser_display_id and riser_display_id != pipe.pipe_id:
                text_parts.append(riser_display_id)
        elif riser_display_id:
            text_parts.append(riser_display_id)

        # B_ 开头的消火栓支管不显示公称管径和管长
        if not pipe.pipe_id.startswith('B_'):
            if self.show_nominal.get() and not pipe.pipe_id.startswith('L_'):
                text_parts.append(pipe.nominal_diameter)
            if self.show_length.get():
                length_m = pipe.length
                text_parts.append(f"{length_m:.2f}m")
            
        if self.show_elevation.get():
            # 只对横管显示标高（R_、L_、B_开头的立管/连接管/支管不显示）
            if not pipe.pipe_id.startswith(('R_', 'L_', 'B_')):
                if pipe.length > 2.0:
                    pipe_elev = None
                    if self.cad_data_manager.floors:
                        for floor in self.cad_data_manager.floors:
                            if pipe in floor.pipes:
                                pipe_elev = floor.pipe_z_offset
                                break
                    if pipe_elev is not None:
                        text_parts.append(f"FL{pipe_elev:.2f}")            
            
        if self.calculation_available and self.show_flow.get() and not pipe.pipe_id.startswith('L_'):
            flow = self.pipe_results.get(pipe.pipe_id, {}).get('flow_lps', 0)
            flow_abs = abs(flow)
            if flow_abs > 0.001 or self.show_zero_flow_label_var.get():
                flow_unit = self.config_manager.get_live_config().get('flow_unit', 'L/s')
                if flow_unit == 'm³/h':
                    flow_abs = flow_abs * 3.6
                text_parts.append(f"{flow_abs:.2f}{flow_unit}")
        if self.calculation_available and self.show_velocity.get() and not pipe.pipe_id.startswith('L_'):
            vel = self.pipe_results.get(pipe.pipe_id, {}).get('velocity_mps', 0.0)
            if abs(vel) > 0.001 or self.show_zero_flow_label_var.get():
                text_parts.append(f"{vel:.2f}m/s")
        if self.calculation_available and self.show_loss.get() and not pipe.pipe_id.startswith('L_'):
            loss = self.pipe_results.get(pipe.pipe_id, {}).get('total_loss', 0)
            if abs(flow) > 0.001 or self.show_zero_flow_label_var.get():
                pressure_unit = self.config_manager.get_live_config().get('pressure_unit', 'm')
                if pressure_unit == 'MPa':
                    loss = loss * 0.00980665
                text_parts.append(f"{loss:.2f}{pressure_unit}")

        if text_parts:
            display = "_".join(text_parts)
            self.draw_pipe_text(pipe, sx, sy, ex, ey, display)

        # 流向箭头
        if self.show_arrow.get() and self.calculation_available and not pipe.pipe_id.startswith('L_'):
            flow = self.pipe_results.get(pipe.pipe_id, {}).get('flow_lps', 0)
            if abs(flow) > 0.001:
                self.draw_arrow(pipe, sx, sy, ex, ey, flow)

    def draw_pipe_text(self, pipe, sx, sy, ex, ey, text):
        mx = (sx + ex) / 2
        my = (sy + ey) / 2
        dx = ex - sx
        dy = ey - sy
        length = math.hypot(dx, dy)
        if length == 0:
            return
    
        text_size = max(self.TEXT_MIN_SIZE, min(self.TEXT_MAX_SIZE, int(10 * self.scale)))
        offset = text_size * 1.0  # 偏移距离（像素）
    
        # 法线向量（垂直于线段）
        nx = -dy / length
        ny = dx / length
    
        # 计算角度：Tkinter的angle参数遵循数学坐标系（逆时针，Y轴向上），
        # 而屏幕坐标系Y轴向下，因此需要将dy取反以正确转换坐标系。
        angle = math.degrees(math.atan2(-dy, dx))

        # 判断是否需要旋转180度避免文字倒置
        # 当角度超过90度或小于-90度时，文字字符本身会倒立，
        # 此时翻转180度可使字符正立，文字基线方向变为反向平行（仍在同一直线上）。
        flip = (angle > 90 or angle < -90)
        if flip:
            angle += 180
            # 偏移方向反向（使文字始终在管道同一侧，保持阅读方向一致）
            tx = mx - nx * offset
            ty = my - ny * offset
        else:
            tx = mx + nx * offset
            ty = my + ny * offset
        
        # 确保角度在 [0,360) 范围内
        angle = angle % 360
    
        self.canvas.create_text(tx, ty, text=text, fill="white",
                                angle=angle, font=("Arial", text_size),
                                tags="pipe_text")

    def draw_arrow(self, pipe, sx, sy, ex, ey, flow):
        if flow > 0:
            # 起点->终点
            ax = (sx * 0.7 + ex * 0.3)
            ay = (sy * 0.7 + ey * 0.3)
            bx = (sx * 0.3 + ex * 0.7)
            by = (sy * 0.3 + ey * 0.7)
        else:
            # 终点->起点
            ax = (sx * 0.3 + ex * 0.7)
            ay = (sy * 0.3 + ey * 0.7)
            bx = (sx * 0.7 + ex * 0.3)
            by = (sy * 0.7 + ey * 0.3)

        arrow_size = max(5, int(8 * self.scale))*2
        self.canvas.create_line(ax, ay, bx, by,
                                 fill="white", width=2, arrow=tk.LAST,
                                 arrowshape=(arrow_size, arrow_size, arrow_size//2),
                                 tags="arrow")

    def draw_node(self, node):
        # 隐藏无效管模式下，跳过无有效管道连接的节点
        if self.hide_invalid_var.get():
            connected = getattr(node, 'connected_pipes', []) or []
            has_valid = any(
                p is not None and p.is_active
                for p in (self.cad_data_manager.pipe_by_id.get(pid) for pid in connected)
            )
            if not has_valid:
                return
        wpos = self.projected_coords.get(node.node_id)
        if not wpos:
            return

        # B_消火栓支管末端节点视觉覆盖：跟随中间节点向左 0.3m
        if getattr(self, '_hydrant_visual_offsets', None):
            mid_id = self._hydrant_visual_offsets.get(node.node_id)
            if mid_id:
                mid_pos = self.projected_coords.get(mid_id)
                if mid_pos:
                    wpos = (mid_pos[0] - 300.0, mid_pos[1])

        cx, cy = self.world_to_canvas(*wpos)
        radius = max(3, int(3 * self.scale))
        if node.node_id in self.highlight_path_nodes:
            fill = self.COLOR_NODE_HIGHLIGHT
        else:
            fill = self.COLOR_NODE
        self.canvas.create_oval(cx - radius, cy - radius,
                                 cx + radius, cy + radius,
                                 fill=fill, outline="", tags="node")
        
        # 构建显示文本（独立控制节点编号和节点压力）
        text_parts = []
        if self.show_node_ids.get():
            text_parts.append(node.node_id)
        if self.show_node_pressure.get():
            pressure = self.node_pressures.get(node.node_id, 0.0)
            if pressure > 0:
                config = self.config_manager.get_live_config()
                pressure_unit = config.get("pressure_unit", "m")
                if pressure_unit == "MPa":
                    pressure = pressure / 101.9716
                text_parts.append(f"{pressure:.2f}")
        if text_parts:
            display_text = "_".join(text_parts)
            self.canvas.create_text(cx + radius + 2, cy - radius - 2,
                                     text=display_text, fill="white",
                                     font=("Arial", max(10, int(10 * self.scale))),
                                     tags="node_text")

    def on_units_changed(self):
        """单位改变时刷新显示，并重新计算节点Z坐标"""
        if self.cad_data_manager.floors:
            # 重新获取配置，重新计算节点Z坐标
            config = self.config_manager.get_live_config()
            self.cad_data_manager.assign_node_z_coordinates(config)
        self.redraw()

    def draw_valve(self, valve):
        pipe = self.cad_data_manager.pipe_by_id.get(valve.pipe_id)
        if not pipe:
            # 降级绘制简单菱形
            px, py = self.project_point(valve.x, valve.y, valve.z)
            cx, cy = self.world_to_canvas(px, py)
            size = max(5, int(6 * self.scale))
            color = self.COLOR_VALVE if valve.status == "OPEN" else self.COLOR_VALVE_CLOSED
            if valve.valve_id == self.selected_valve_id:
                color = self.COLOR_VALVE_SELECTED
            points = [cx, cy - size, cx + size, cy, cx, cy + size, cx - size, cy]
            self.canvas.create_polygon(points, fill=color, outline="white", width=1,
                                       tags=("valve", valve.valve_id))
            return
    
        # 获取管道方向
        start_w = self.projected_coords.get(pipe.start_node_id)
        end_w = self.projected_coords.get(pipe.end_node_id)
        if not start_w or not end_w:
            return
        sx, sy = self.world_to_canvas(*start_w)
        ex, ey = self.world_to_canvas(*end_w)
        dx = ex - sx
        dy = ey - sy
        length = math.hypot(dx, dy)
        if length == 0:
            return
        ux = dx / length   # 管道方向单位向量
        uy = dy / length
        perp_x = -uy       # 垂直向量（用于底边宽度）
        perp_y = ux
    
        # 阀门插入点画布坐标
        vx_w, vy_w = self.project_point(valve.x, valve.y, valve.z)
        vx, vy = self.world_to_canvas(vx_w, vy_w)
    
        # 阀门尺寸（已放大1.5倍）
        base_height = 12 * self.scale
        base_width = 10 * self.scale
        tri_height = max(8, int(base_height * 1.5))   # 三角形沿管道方向的长度
        tri_base = max(6, int(base_width * 1.5))      # 三角形底边宽度的一半
    
        # 计算两个三角形的底边中点（沿管道方向偏移 tri_height）
        mid1 = (vx + ux * tri_height, vy + uy * tri_height)   # 正向底边中点
        mid2 = (vx - ux * tri_height, vy - uy * tri_height)   # 反向底边中点
    
        # 计算两个三角形的底边端点（沿法向偏移 tri_base）
        left1 = (mid1[0] - perp_x * tri_base, mid1[1] - perp_y * tri_base)
        right1 = (mid1[0] + perp_x * tri_base, mid1[1] + perp_y * tri_base)
        left2 = (mid2[0] - perp_x * tri_base, mid2[1] - perp_y * tri_base)
        right2 = (mid2[0] + perp_x * tri_base, mid2[1] + perp_y * tri_base)
    
        # 根据阀门状态确定填充
        if valve.status == "OPEN":
            fill = ""
            outline = self.COLOR_VALVE
        else:
            fill = self.COLOR_VALVE_CLOSED
            outline = self.COLOR_VALVE_CLOSED
        if valve.valve_id == self.selected_valve_id:
            outline = self.COLOR_VALVE_SELECTED
            if valve.status == "OPEN":
                fill = ""
    
        # 绘制两个三角形（顶点都在插入点 (vx,vy)）
        # 三角形1（指向正方向）：顶点 (vx,vy)，底边 left1-right1
        self.canvas.create_polygon(vx, vy, left1[0], left1[1], right1[0], right1[1],
                                   fill=fill, outline=outline, width=2, tags=("valve", valve.valve_id))
        # 三角形2（指向反方向）：顶点 (vx,vy)，底边 left2-right2
        self.canvas.create_polygon(vx, vy, left2[0], left2[1], right2[0], right2[1],
                                   fill=fill, outline=outline, width=2, tags=("valve", valve.valve_id))
        # 显示阀门编号（如果勾选）
        if self.show_valve_id.get():
            # 阀门编号文字放置于阀门符号右侧偏移位置
            text_x = vx + 12 * self.scale
            text_y = vy
            # 根据缩放调整字体大小
            font_size = max(10, int(10 * self.scale))
            self.canvas.create_text(text_x, text_y, text=valve.valve_id, fill="white",
                                    font=("Arial", font_size), anchor="w", tags="valve_text")
            
    def draw_supply_demand(self):
        """绘制供水点和用水点（只绘制当前楼层的）"""
        # 获取当前楼层的节点ID集合
        current_floor_node_ids = set(self.projected_coords.keys())
        
        # 供水点：实心方块
        for supply in self.cad_data_manager.supply_nodes:
            for node_id in supply.node_ids:
                # 只绘制在当前楼层的供水点
                if node_id not in current_floor_node_ids:
                    continue
                node = self.cad_data_manager.node_by_id.get(node_id)
                if node:
                    wpos = self.projected_coords.get(node_id)
                    if getattr(self, '_hydrant_visual_offsets', None):
                        mid_id = self._hydrant_visual_offsets.get(node_id)
                        if mid_id:
                            mid_pos = self.projected_coords.get(mid_id)
                            if mid_pos:
                                wpos = (mid_pos[0] - 300.0, mid_pos[1])
                    if wpos:
                        cx, cy = self.world_to_canvas(*wpos)
                        size = max(4, int(5 * self.scale))
                        self.canvas.create_rectangle(cx - size, cy - size,
                                                       cx + size, cy + size,
                                                       fill=self.COLOR_SUPPLY,
                                                       outline="white", width=1,
                                                       tags="supply")

        # 用水点：根据状态绘制圆
        for group in self.cad_data_manager.demand_groups.values():
            for demand_node in group.demand_nodes:
                node_id = demand_node.node_id
                # 只绘制在当前楼层的用水点
                if node_id not in current_floor_node_ids:
                    continue
                node = self.cad_data_manager.node_by_id.get(node_id)
                if node:
                    wpos = self.projected_coords.get(node_id)
                    if getattr(self, '_hydrant_visual_offsets', None):
                        mid_id = self._hydrant_visual_offsets.get(node_id)
                        if mid_id:
                            mid_pos = self.projected_coords.get(mid_id)
                            if mid_pos:
                                wpos = (mid_pos[0] - 300.0, mid_pos[1])
                    if wpos:
                        cx, cy = self.world_to_canvas(*wpos)
                        radius = max(4, int(5 * self.scale))
                        if demand_node.status == "开":
                            fill = self.COLOR_DEMAND_ON
                            outline = "white"
                        else:
                            fill = self.COLOR_DEMAND_OFF
                            outline = "white"
                        self.canvas.create_oval(cx - radius, cy - radius,
                                                 cx + radius, cy + radius,
                                                 fill=fill, outline=outline,
                                                 width=1, tags="demand")

    def draw_sprinklers(self):
        s_ids = getattr(self.cad_data_manager, 'sprinkler_s_node_ids', [])
        if not s_ids:
            return
        current_nodes = set(self.projected_coords.keys())
        for nid in s_ids:
            if nid not in current_nodes:
                continue
            wpos = self.projected_coords.get(nid)
            if not wpos:
                continue
            cx, cy = self.world_to_canvas(*wpos)
            r = max(6, int(6 * self.scale))
            self.canvas.create_oval(cx-r, cy-r, cx+r, cy+r,
                                    outline="white", width=1, tags="sprinkler")

    def modify_sprinkler(self, sp_pipes=None):
        """打开喷头修改对话框"""
        if sp_pipes is None:
            sp_pipes = [self.cad_data_manager.pipe_by_id[pid]
                        for pid in self.selected_pipes
                        if pid.startswith("SP_") and pid in self.cad_data_manager.pipe_by_id]
        if not sp_pipes:
            self.show_temp_message("未选中任何喷头短管", 2000)
            return
        root = self.winfo_toplevel()
        self.SprinklerModifyDialog(root, self, sp_pipes)

    # ==================== 喷头修改对话框 ====================
    class SprinklerModifyDialog:
        def __init__(self, parent, preview, sp_pipes):
            self.preview = preview
            self.cad = preview.cad_data_manager
            self.config = preview.config_manager
            self.mm = preview.material_manager
            self.sp_pipes = sp_pipes
            self._dn_manual = False

            first_pipe = sp_pipes[0]
            first_node_id = first_pipe.start_node_id
            self.default_K = self.cad.sprinkler_k_map.get(
                first_node_id, self.config.get_live_config().get("sprinkler_K", 80))
            self.default_dn = first_pipe.nominal_diameter
            self.default_len = first_pipe.length
            self.default_up = (first_pipe.end_point[2] > first_pipe.start_point[2])

            params_differ = False
            for pipe in sp_pipes[1:]:
                if pipe.nominal_diameter != self.default_dn or abs(pipe.length - self.default_len) > 0.001:
                    params_differ = True
                    break

            self.dialog = tk.Toplevel(parent)
            self.dialog.title("修改喷头和短管")
            self.dialog.resizable(False, False)
            self.dialog.transient(parent)

            kf = ttk.Frame(self.dialog)
            kf.pack(fill="x", padx=10, pady=(10, 5))
            ttk.Label(kf, text="K值:").pack(side="left")
            k_values = [80, 115, 161, 200, 202, 242, 320, 363]
            k_strs = [str(v) for v in k_values]
            self.k_var = tk.StringVar(value=str(self.default_K))
            self.k_combo = ttk.Combobox(kf, textvariable=self.k_var, values=k_strs, width=10, state='normal')
            self.k_combo.pack(side="left", padx=(5, 0))
            self.k_var.trace('w', lambda *a: self._on_k_changed())

            df = ttk.Frame(self.dialog)
            df.pack(fill="x", padx=10, pady=(0, 5))
            ttk.Label(df, text="短立管管径:").pack(side="left")
            dn_values = self._get_sprinkler_dn_list()
            self.dn_var = tk.StringVar(value=self.default_dn)
            self.dn_combo = ttk.Combobox(df, textvariable=self.dn_var, values=dn_values, width=8, state='readonly')
            self.dn_combo.pack(side="left", padx=(5, 0))
            self.dn_combo.bind("<<ComboboxSelected>>", lambda e: setattr(self, '_dn_manual', True))

            lf = ttk.Frame(self.dialog)
            lf.pack(fill="x", padx=10, pady=(0, 5))
            ttk.Label(lf, text="短立管长度(m):").pack(side="left")
            self.len_var = tk.StringVar(value=str(self.default_len))
            self.len_entry = ttk.Entry(lf, textvariable=self.len_var, width=8)
            self.len_entry.pack(side="left", padx=(5, 0))

            dirf = ttk.Frame(self.dialog)
            dirf.pack(fill="x", padx=10, pady=(0, 5))
            ttk.Label(dirf, text="方向:").pack(side="left")
            self.dir_var = tk.IntVar(value=1 if self.default_up else 0)
            ttk.Radiobutton(dirf, text="上喷", variable=self.dir_var, value=1).pack(side="left", padx=(10, 0))
            ttk.Radiobutton(dirf, text="下喷", variable=self.dir_var, value=0).pack(side="left", padx=(10, 0))

            if params_differ:
                warn = ttk.Label(self.dialog, text="⚠ 选中的喷头参数不一致，将以第一根喷头参数显示",
                                 foreground="red")
                warn.pack(pady=(0, 5))

            bf = ttk.Frame(self.dialog)
            bf.pack(fill="x", padx=10, pady=(5, 10))
            ttk.Button(bf, text="确定", command=self._on_confirm).pack(side="left", padx=(30, 10))
            ttk.Button(bf, text="复原", command=self._on_reset).pack(side="left", padx=(0, 10))
            ttk.Button(bf, text="取消", command=self.dialog.destroy).pack(side="left")

            self.dialog.update_idletasks()
            w = self.dialog.winfo_width()
            h = self.dialog.winfo_height()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
            self.dialog.geometry(f"+{x}+{y}")

        def _get_sprinkler_dn_list(self):
            material = self.config.get_live_config().get("pipe_material", "镀锌钢管")
            all_dn = self.mm.get_sorted_diameters(material, "sprinkler")
            result = []
            for dn in all_dn:
                if dn.startswith("DN"):
                    try:
                        if int(dn[2:]) <= 150:
                            result.append(dn)
                    except:
                        pass
            return result

        def _on_k_changed(self):
            if self._dn_manual:
                return
            try:
                K = float(self.k_var.get())
                new_dn = self.mm.get_sprinkler_dn(K)
                dn_values = self._get_sprinkler_dn_list()
                if new_dn in dn_values:
                    self.dn_var.set(new_dn)
                self._dn_manual = False
            except:
                pass

        def _on_reset(self):
            config = self.config.get_live_config()
            default_K = config.get("sprinkler_K", 80)
            self.k_var.set(str(default_K))
            self.len_var.set("0.1")
            self.dir_var.set(1)
            self._dn_manual = False
            self._on_k_changed()

        def _on_confirm(self):
            try:
                K = float(self.k_var.get())
                new_len = float(self.len_var.get())
            except ValueError:
                self.preview.show_temp_message("输入值非法", 2000)
                return
            new_dn = self.dn_var.get()
            is_up = self.dir_var.get() == 1
            config = self.config.get_live_config()
            drawing_unit = config.get("drawing_unit", "毫米")
            unit_factor = self.cad.unit_factors.get(drawing_unit, 0.001)

            for pipe in self.sp_pipes:
                material = pipe.material
                pipe.nominal_diameter = new_dn
                pipe.length = new_len
                info = self.mm.get_diameter_info(material, new_dn)
                pipe.inner_diameter = info.get("inner", pipe.inner_diameter)

                self.cad.manual_dn_pipes.add(pipe.pipe_id)

                base_node = self.cad.node_by_id.get(pipe.start_node_id)
                s_node = self.cad.node_by_id.get(pipe.end_node_id)
                if base_node and s_node:
                    height = new_len / unit_factor if unit_factor > 0 else new_len * 1000
                    if is_up:
                        s_node.z = base_node.z + height
                    else:
                        s_node.z = base_node.z - height
                    pipe.end_point = (s_node.x, s_node.y, s_node.z)
                    pipe.start_point = (base_node.x, base_node.y, base_node.z)

                self.cad.sprinkler_k_map[pipe.start_node_id] = K
                self.cad.sprinkler_k_overrides.add(pipe.start_node_id)

            self.preview.redraw()
            self.preview.show_temp_message(f"已修改 {len(self.sp_pipes)} 根喷头短管", 2000)
            self.dialog.destroy()

    # ----------------------------------------------------------------------
    # 交互事件
    # ----------------------------------------------------------------------
    def on_mouse_wheel(self, event):
        self._destroy_hover_tooltip()
        scale_factor = 1.1 if event.delta > 0 else 0.9
        self.scale *= scale_factor
        mouse_x = self.canvas.canvasx(event.x)
        mouse_y = self.canvas.canvasy(event.y)
        self.translate_x = mouse_x - (mouse_x - self.translate_x) * scale_factor
        self.translate_y = mouse_y - (mouse_y - self.translate_y) * scale_factor
        self.redraw()

    def on_mouse_middle_down(self, event):
        self._destroy_hover_tooltip()
        self.drag_start = (event.x, event.y)
    
    def on_mouse_middle_drag(self, event):
        if self.drag_start:
            dx = event.x - self.drag_start[0]
            dy = event.y - self.drag_start[1]
            self.translate_x += dx
            self.translate_y += dy
            self.drag_start = (event.x, event.y)
            self.redraw()

    def on_left_click(self, event):
        self._destroy_hover_tooltip()
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        # 使用画布像素坐标进行最近对象查找，阈值统一为50像素
        threshold = 10
        ctrl_pressed = (event.state & 0x0004) != 0

        # 查找最近的管道
        pipe_dist, clicked_pipe = self._find_nearest_pipe((canvas_x, canvas_y))

        if pipe_dist < threshold and clicked_pipe:
            # 点击管道
            if ctrl_pressed:
                if clicked_pipe.pipe_id in self.selected_pipes:
                    self.selected_pipes.remove(clicked_pipe.pipe_id)
            else:
                self.selected_pipes.add(clicked_pipe.pipe_id)
            self.selected_valve_id = None
            self.redraw()
            return

        # 查找最近的阀门
        valve_dist, clicked_valve = self._find_nearest_valve((canvas_x, canvas_y))
        if valve_dist < threshold and clicked_valve:
            self.selected_pipes.clear()
            self.selected_valve_id = clicked_valve.valve_id
            self.redraw()
            return

        # 点击空白处：不清空选择集，只清除阀门高亮，开始框选模式
        self.selected_valve_id = None
        self.selection_start = (event.x, event.y)
        self.selection_mode = True
        self.canvas.focus_set()

    def on_left_drag(self, event):
        if not self.selection_mode or not self.selection_start:
            return
        # 删除旧的矩形
        if self.selection_rect:
            self.canvas.delete(self.selection_rect)
        # 画新矩形
        x1, y1 = self.selection_start
        x2, y2 = event.x, event.y
        self.selection_rect = self.canvas.create_rectangle(
            x1, y1, x2, y2, outline="white", dash=(4, 2), tags="selection_rect"
        )

    def on_left_release(self, event):
        if not self.selection_mode or not self.selection_start:
            return
        # 删除矩形
        if self.selection_rect:
            self.canvas.delete(self.selection_rect)
            self.selection_rect = None

        # 获取矩形区域的画布像素坐标
        x1, y1 = self.selection_start
        x2, y2 = event.x, event.y
        # 计算矩形宽度和高度（像素）
        width = abs(x2 - x1)
        height = abs(y2 - y1)
        # 如果矩形太小（例如小于5像素），视为无效点击，不清空选择集也不更新
        if width < 5 and height < 5:
            # 无效框选，直接退出，不清除选择集
            self.selection_mode = False
            self.selection_start = None
            return

        min_cx, max_cx = min(x1, x2), max(x1, x2)
        min_cy, max_cy = min(y1, y2), max(y1, y2)

        # 查找矩形内的管道
        ctrl_pressed = (event.state & 0x0004) != 0
        pipes_in_rect = self._get_pipes_in_rect(min_cx, min_cy, max_cx, max_cy)
        if ctrl_pressed:
            self.selected_pipes -= pipes_in_rect
        else:
            self.selected_pipes.update(pipes_in_rect)

        self.selection_mode = False
        self.selection_start = None
        self.redraw()

    def on_escape(self, event):
        self.selected_pipes.clear()
        self.selected_valve_id = None
        self.redraw()

    def _get_pipes_in_rect(self, canvas_min_x, canvas_min_y, canvas_max_x, canvas_max_y) -> Set[str]:
        """返回与矩形（画布坐标）相交的管道ID集合（精确线段相交）"""
        result = set()
        # 预先计算矩形的边界
        left = canvas_min_x
        right = canvas_max_x
        top = canvas_min_y
        bottom = canvas_max_y
        
        for pipe in self.cad_data_manager.pipes:
            # 仅当“隐藏无效管”勾选时，才跳过无效管道
            if self.hide_invalid_var.get() and not pipe.is_active:
                continue
            start_w = self.projected_coords.get(pipe.start_node_id)
            end_w = self.projected_coords.get(pipe.end_node_id)
            if not start_w or not end_w:
                continue
            start_c = self.world_to_canvas(*start_w)
            end_c = self.world_to_canvas(*end_w)
            
            # 快速包围盒剔除（可选，提高性能）
            pipe_min_x = min(start_c[0], end_c[0])
            pipe_max_x = max(start_c[0], end_c[0])
            pipe_min_y = min(start_c[1], end_c[1])
            pipe_max_y = max(start_c[1], end_c[1])
            if (pipe_max_x < left or pipe_min_x > right or
                pipe_max_y < top or pipe_min_y > bottom):
                continue
            
            # 精确检测：线段与矩形是否相交（包括线段完全在矩形内部、线段穿过矩形、线段端点落在矩形内）
            if self._segment_intersects_rect(start_c, end_c, left, right, top, bottom):
                result.add(pipe.pipe_id)
        return result
    
    def _segment_intersects_rect(self, p1, p2, left, right, top, bottom):
        """判断线段 p1-p2 是否与轴对齐矩形相交（包括线段在矩形内部或端点落在矩形上）"""
        # 快速检查：线段端点是否在矩形内
        if (left <= p1[0] <= right and top <= p1[1] <= bottom) or \
           (left <= p2[0] <= right and top <= p2[1] <= bottom):
            return True
        
        # 检查线段是否与矩形的四条边相交
        # 矩形四条边：左、右、上、下
        # 与左边（x=left）相交，y 在 [top, bottom] 内
        if p1[0] != p2[0]:
            t = (left - p1[0]) / (p2[0] - p1[0])
            if 0 <= t <= 1:
                y = p1[1] + t * (p2[1] - p1[1])
                if top <= y <= bottom:
                    return True
            # 右边
            t = (right - p1[0]) / (p2[0] - p1[0])
            if 0 <= t <= 1:
                y = p1[1] + t * (p2[1] - p1[1])
                if top <= y <= bottom:
                    return True
        
        # 与上边（y=top）相交
        if p1[1] != p2[1]:
            t = (top - p1[1]) / (p2[1] - p1[1])
            if 0 <= t <= 1:
                x = p1[0] + t * (p2[0] - p1[0])
                if left <= x <= right:
                    return True
            # 下边
            t = (bottom - p1[1]) / (p2[1] - p1[1])
            if 0 <= t <= 1:
                x = p1[0] + t * (p2[0] - p1[0])
                if left <= x <= right:
                    return True
        
        return False

    def on_right_click(self, event):
        self._destroy_hover_tooltip()
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        threshold = 10  # 像素阈值

        # 查找最近的管道和阀门
        pipe_dist, clicked_pipe = self._find_nearest_pipe((canvas_x, canvas_y))
        valve_dist, clicked_valve = self._find_nearest_valve((canvas_x, canvas_y))

        menu = tk.Menu(self, tearoff=0)

        if pipe_dist < threshold and clicked_pipe:
            self._build_pipe_menu(menu, clicked_pipe)
        elif valve_dist < threshold and clicked_valve:
            self._build_valve_menu(menu, clicked_valve)
        else:
            # 无管道/阀门，尝试查找最近的节点
            node_dist, clicked_node = self._find_nearest_node((canvas_x, canvas_y))
            if node_dist < threshold and clicked_node:
                self._build_node_menu(menu, clicked_node)
            if self.selected_pipes:
                self._build_selection_menu(menu)

        if menu.index("end") is not None:
            menu.tk_popup(event.x_root, event.y_root)

        self.canvas.focus_set()

    def _find_nearest_pipe(self, canvas_pt):
        min_dist = float('inf')
        nearest_pipe = None
        for pipe in self.cad_data_manager.pipes:
            if self.hide_invalid_var.get() and not pipe.is_active:   # 仅当“隐藏无效管”勾选时，才跳过无效管道
                continue
            start_w = self.projected_coords.get(pipe.start_node_id)
            end_w = self.projected_coords.get(pipe.end_node_id)
            if not start_w or not end_w:
                continue
            # 转换为画布像素坐标
            start_c = self.world_to_canvas(*start_w)
            end_c = self.world_to_canvas(*end_w)
            dist = self.point_to_line_distance(canvas_pt, start_c, end_c)
            if dist < min_dist:
                min_dist = dist
                nearest_pipe = pipe
        return min_dist, nearest_pipe
    
    def _find_nearest_valve(self, canvas_pt):
        min_dist = float('inf')
        nearest_valve = None
        for valve in self.cad_data_manager.valves:
            vw = self.project_point(valve.x, valve.y, valve.z)
            vc = self.world_to_canvas(*vw)
            dist = math.hypot(canvas_pt[0] - vc[0], canvas_pt[1] - vc[1])
            if dist < min_dist:
                min_dist = dist
                nearest_valve = valve
        return min_dist, nearest_valve

    def _find_nearest_node(self, canvas_pt):
        min_dist = float('inf')
        nearest_node = None
        for node in self.cad_data_manager.nodes:
            wpos = self.projected_coords.get(node.node_id)
            if not wpos:
                continue
            cpos = self.world_to_canvas(*wpos)
            dist = math.hypot(canvas_pt[0] - cpos[0], canvas_pt[1] - cpos[1])
            if dist < min_dist:
                min_dist = dist
                nearest_node = node
        return min_dist, nearest_node

    # ----------------------------------------------------------------------
    # Alt 悬停信息框
    # ----------------------------------------------------------------------
    def _on_alt_press(self, event):
        self.alt_pressed = True

    def _on_alt_release(self, event):
        self.alt_pressed = False
        self._destroy_hover_tooltip()

    def on_mouse_move(self, event):
        self._destroy_hover_tooltip()
        if not self.alt_pressed:
            return
        if self._hover_tooltip_id:
            self.after_cancel(self._hover_tooltip_id)
        self._hover_canvas_pos = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        self._hover_screen_pos = (event.x_root, event.y_root)
        self._hover_tooltip_id = self.after(500, self._show_hover_tooltip)

    def on_mouse_leave(self, event):
        self._destroy_hover_tooltip()

    def _destroy_hover_tooltip(self):
        if self._hover_tooltip_id:
            self.after_cancel(self._hover_tooltip_id)
            self._hover_tooltip_id = None
        if self._hover_tooltip_win:
            try:
                self._hover_tooltip_win.destroy()
            except tk.TclError:
                pass
            self._hover_tooltip_win = None
        self._hover_canvas_pos = None
        self._hover_screen_pos = None
        self._hover_info = None

    def _show_hover_tooltip(self):
        self._hover_tooltip_id = None
        if not self.alt_pressed or not self._hover_canvas_pos:
            return
        if not self.canvas or not self.canvas.winfo_exists():
            return
        info_type, lines = self._get_hover_info(self._hover_canvas_pos)
        if not lines:
            return
        self._hover_info = (info_type, lines)
        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.attributes('-alpha', 0.9)
        win.attributes('-topmost', True)
        label = tk.Label(win, text="\n".join(lines),
                         justify=tk.LEFT,
                         background="#FFFFE8",
                         relief=tk.SOLID, borderwidth=1,
                         font=("Microsoft YaHei", 9),
                         padx=6, pady=4)
        label.pack()
        win.update_idletasks()
        rx, ry = self._hover_screen_pos
        win_w = win.winfo_width()
        win_h = win.winfo_height()
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        pos_x = rx + 15
        pos_y = ry + 15
        if pos_x + win_w > screen_w:
            pos_x = rx - win_w - 10
        if pos_y + win_h > screen_h:
            pos_y = ry - win_h - 10
        pos_x = max(pos_x, 0)
        pos_y = max(pos_y, 0)
        win.geometry(f"+{pos_x}+{pos_y}")
        self._hover_tooltip_win = win

    def _get_hover_info(self, canvas_pt):
        threshold = 10
        # 优先级：节点 > 阀门 > 管道
        dist, node = self._find_nearest_node(canvas_pt)
        if node and dist < threshold:
            node_id = node.node_id
            pressure_val = self.node_pressures.get(node_id, 0.0)
            # 节点流量：取所有连接管道中流量的最大绝对值
            node_obj = self.cad_data_manager.node_by_id.get(node_id)
            if node_obj and node_obj.connected_pipes:
                flow_val = max(
                    (abs(self.pipe_results.get(pid, {}).get('flow_lps', 0.0))
                     for pid in node_obj.connected_pipes),
                    default=0.0
                )
            else:
                flow_val = 0.0
            node_lines = [
                f"节点编号: {node_id}",
                f"节点流量: {flow_val:.2f}L/s",
                f"节点压力: {pressure_val:.2f}m"
            ]
            # 消火栓（优先于喷头）
            if node.hydrants:
                hyd_id = node.hydrants[0]
                hyd = self.cad_data_manager.hydrant_by_id.get(hyd_id)
                hyd_label = hyd.hydrant_id if hyd else hyd_id
                lines = [f"消火栓编号: {hyd_label}"] + node_lines
                return ("hydrant", lines)
            # 喷头：sprinkler_s_node_ids 存的是 {base_id}_S，
            # 而 sprinkler_k_map 的键是 base_id（不带 _S）
            s_ids = getattr(self.cad_data_manager, 'sprinkler_s_node_ids', [])
            if node_id in s_ids:
                base_id = node_id[:-2] if node_id.endswith('_S') else node_id
                k_val = self.cad_data_manager.sprinkler_k_map.get(base_id, 0)
                lines = [f"喷头K值: {k_val}"] + node_lines
                return ("sprinkler", lines)
            # 普通节点
            return ("node", node_lines)
        dist, valve = self._find_nearest_valve(canvas_pt)
        if valve and dist < threshold:
            lines = [f"阀门编号: {valve.valve_id}"]
            return ("valve", lines)
        dist, pipe = self._find_nearest_pipe(canvas_pt)
        if pipe and dist < threshold:
            lines = [f"管道编号: {pipe.pipe_id}"]
            if pipe.riser_number:
                lines.append(f"立管编号: {pipe.riser_number}")
            lines.append(f"公称管径: {pipe.nominal_diameter or '0'}")
            lines.append(f"管长: {pipe.length:.2f}m")
            pres = self.pipe_results.get(pipe.pipe_id, {})
            flow = pres.get('flow_lps', 0.0)
            vel = pres.get('velocity_mps', 0.0)
            loss = pres.get('total_loss', 0.0)
            lines.append(f"流量: {abs(flow):.2f}L/s")
            lines.append(f"流速: {vel:.2f}m/s")
            lines.append(f"水损: {loss:.2f}m")
            return ("pipe", lines)
        return (None, None)

    def _build_pipe_menu(self, menu, pipe):
        # 添加阀门（如果无阀门）
        has_valve = any(v.pipe_id == pipe.pipe_id for v in self.cad_data_manager.valves)
        if not has_valve:
            menu.add_command(label="添加阀门", command=lambda: self.add_valve_on_pipe(pipe.pipe_id))
    
        # 阀门操作（如果有阀门）
        valve = next((v for v in self.cad_data_manager.valves if v.pipe_id == pipe.pipe_id), None)
        if valve:
            if valve.status == "OPEN":
                menu.add_command(label="关闭阀门", command=lambda: self.set_valve_status(valve.valve_id, "CLOSED"))
            else:
                menu.add_command(label="打开阀门", command=lambda: self.set_valve_status(valve.valve_id, "OPEN"))
            menu.add_command(label="删除阀门", command=lambda: self.delete_valve(valve.valve_id))
    
        # 添加消火栓（检查两端节点）
        start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
        end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
        for node in (start_node, end_node):
            if node and len(node.connected_pipes) == 1 and not node.hydrants:
                # 允许用水点添加消火栓，但禁止供水点
                if "供水点" not in node.node_type:
                    menu.add_command(label="添加消火栓", command=lambda n=node: self.add_hydrant_on_node(n))
                    break  # 只需添加一个选项
    
        # 删除消火栓（检查两端节点是否有消火栓）
        for node in (start_node, end_node):
            if node and node.hydrants:
                hydrant_id = node.hydrants[0]  # 取第一个
                menu.add_command(label="删除消火栓", command=lambda hid=hydrant_id: self.delete_hydrant(hid))
                break
    
        menu.add_separator()
        # 新增有效性操作
        if pipe.is_active:
            menu.add_command(label="使无效", command=lambda: self.set_pipe_active(pipe.pipe_id, False))
        else:
            menu.add_command(label="使有效", command=lambda: self.set_pipe_active(pipe.pipe_id, True))
        menu.add_command(label="删除管道", command=lambda: self.delete_pipe(pipe.pipe_id))
        menu.add_command(label="放大管径", command=lambda: self.change_pipe_diameter(pipe.pipe_id, "up"))
        menu.add_command(label="缩小管径", command=lambda: self.change_pipe_diameter(pipe.pipe_id, "down"))
        if self.velocity_check_var.get() and self.calculation_available:
            menu.add_command(label="校正管径",
                             command=lambda pid=pipe.pipe_id: self.correct_single_pipe_diameter(pid, "up"))
            menu.add_command(label="优化管径",
                             command=lambda pid=pipe.pipe_id: self.correct_single_pipe_diameter(pid, "down"))
        
        # 支管链缩小管径（仅消火栓模式，且管道为支管链的一部分）
        config = self.config_manager.get_live_config()
        if config.get("system_type") == "indoor_hydrant":
            # 检查管道是否属于可缩小的支管链
            if self._is_part_of_branch_chain(pipe):
                menu.add_command(label="缩小支管链到DN65", command=lambda: self.shrink_branch_chain(pipe.pipe_id))
        
        # 改为消火栓支管（需满足条件，否则禁用或隐藏）
        if self._can_be_hydrant_branch(pipe):
            menu.add_command(label="改为消火栓支管", command=lambda: self.change_pipe_to_hydrant_branch(pipe.pipe_id))

        menu.add_separator()
        # ===== 新增：供水点/用水点操作 =====
        # 获取自由端节点
        free_nodes = self._get_free_end_nodes_from_pipes([pipe])
        has_free = len(free_nodes) > 0
        # 检查自由端上的点类型
        has_supply = False
        has_demand = False
        for node in free_nodes:
            if self._get_supply_point_on_node(node):
                has_supply = True
            if self._get_demand_point_on_node(node):
                has_demand = True
        # 添加供水点/用水点（仅当所有自由端节点都没有任何类型的点时显示）
        if has_free:
            # 检查是否有任何一个自由端节点已经有点（供水或用水）
            any_point_exists = any(self._get_supply_point_on_node(n) or self._get_demand_point_on_node(n) for n in free_nodes)
            if not any_point_exists:
                menu.add_command(label="添加供水点", command=lambda: self.add_supply_point(pipe))
                menu.add_command(label="添加用水点", command=lambda: self.add_demand_point(pipe))
        # 删除供水点/用水点（自由端上有对应点）
        if has_supply:
            menu.add_command(label="删除供水点", command=lambda: self.delete_supply_point(pipe))
        if has_demand:
            menu.add_command(label="删除用水点", command=lambda: self.delete_demand_point(pipe))
        # 编组/移出组（需要点存在）
        if has_demand:
            menu.add_command(label="用水点编组", command=lambda: self.group_demand_point(pipe))
            menu.add_command(label="用水点移出组", command=lambda: self.ungroup_demand_point(pipe))

        # 检查管道是否关联消火栓
        start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
        end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
        hydrant_id_on_pipe = None
        associated_node = None
        for node in (start_node, end_node):
            if node and node.hydrants:
                hydrant_id_on_pipe = node.hydrants[0]
                associated_node = node
                break
        
        if hydrant_id_on_pipe and associated_node:
            menu.add_separator()
            # 检查该节点当前是否属于某个用水点组
            current_group = None
            for gid, group in self.cad_data_manager.demand_groups.items():
                for dn in group.demand_nodes:
                    if dn.node_id == associated_node.node_id:
                        current_group = gid
                        break
                if current_group:
                    break
            if current_group:
                menu.add_command(label="移出用水点组", 
                                 command=lambda nid=associated_node.node_id, g=current_group: self.remove_node_from_demand_group(nid, g))
            else:
                groups = list(self.cad_data_manager.demand_groups.keys())
                if groups:
                    submenu = tk.Menu(menu, tearoff=0)
                    for gid in groups:
                        submenu.add_command(label=gid, 
                                            command=lambda nid=associated_node.node_id, g=gid: self.add_node_to_demand_group(nid, g))
                    menu.add_cascade(label="加入用水点组", menu=submenu)

        # 喷头短管右键菜单
        if pipe.pipe_id.startswith("SP_"):
            menu.add_separator()
            menu.add_command(label="修改喷头和短管",
                             command=lambda p=pipe: self.modify_sprinkler([p]))

        # ===== 检修区操作 =====
        menu.add_separator()
        zone = self._find_maintenance_zone_for_pipe(pipe.pipe_id)
        if zone:
            menu.add_command(label="不再检修",
                             command=lambda z=zone: self.undo_maintenance(z))
        else:
            menu.add_command(label="此管检修",
                             command=lambda pid=pipe.pipe_id: self.execute_maintenance(pid))

    def _build_valve_menu(self, menu, valve):
        if valve.status == "OPEN":
            menu.add_command(label="关闭阀门", command=lambda: self.set_valve_status(valve.valve_id, "CLOSED"))
        else:
            menu.add_command(label="打开阀门", command=lambda: self.set_valve_status(valve.valve_id, "OPEN"))
        menu.add_command(label="删除阀门", command=lambda: self.delete_valve(valve.valve_id))


    def _build_selection_menu(self, menu):
        menu.add_command(label="放大管径（选择集）", command=lambda: self.change_selected_pipes_diameter("up"))
        menu.add_command(label="缩小管径（选择集）", command=lambda: self.change_selected_pipes_diameter("down"))
        menu.add_command(label="改为消火栓支管（选择集）", command=self.change_selected_to_hydrant_branch)
        menu.add_separator()
        menu.add_command(label="使无效（选择集）", command=lambda: self.set_selected_pipes_active(False))
        menu.add_command(label="使有效（选择集）", command=lambda: self.set_selected_pipes_active(True))
        menu.add_command(label="删除（选择集）", command=self.delete_selected_pipes)
        menu.add_command(label="消火栓编成用水点组", command=self.group_selected_hydrants)
        if self.velocity_check_var.get() and self.calculation_available:
            menu.add_command(label="校正管径（选择集）",
                             command=lambda: self.correct_selected_pipes_diameter("up"))
            menu.add_command(label="优化管径（选择集）",
                             command=lambda: self.correct_selected_pipes_diameter("down"))
        menu.add_separator()
        # ===== 新增：供水点/用水点操作（选择集） =====
        # 获取所有选中管道对应的自由端节点
        selected_pipes_objs = [self.cad_data_manager.pipe_by_id[pid] for pid in self.selected_pipes if pid in self.cad_data_manager.pipe_by_id]
        free_nodes = self._get_free_end_nodes_from_pipes(selected_pipes_objs)
        has_free = len(free_nodes) > 0
        has_supply = False
        has_demand = False
        for node in free_nodes:
            if self._get_supply_point_on_node(node):
                has_supply = True
            if self._get_demand_point_on_node(node):
                has_demand = True
        if has_free:
            # 检查是否有任何一个自由端节点已经有点（供水或用水）
            any_point_exists = any(self._get_supply_point_on_node(n) or self._get_demand_point_on_node(n) for n in free_nodes)
            if not any_point_exists:
                menu.add_command(label="添加供水点（选择集）", command=self.add_supply_points_selected)
                menu.add_command(label="添加用水点（选择集）", command=self.add_demand_points_selected)
        if has_supply:
            menu.add_command(label="删除供水点（选择集）", command=self.delete_supply_points_selected)
        if has_demand:
            menu.add_command(label="删除用水点（选择集）", command=self.delete_demand_points_selected)
            menu.add_command(label="用水点编组（选择集）", command=self.group_demand_points_selected)
            menu.add_command(label="用水点移出组（选择集）", command=self.ungroup_demand_points_selected)

        # 喷头短管选择集菜单
        if any(pid.startswith("SP_") for pid in self.selected_pipes
               if pid in self.cad_data_manager.pipe_by_id):
            menu.add_separator()
            menu.add_command(label="修改喷头和短管", command=self.modify_sprinkler)

    def group_selected_hydrants(self):
        """将选择集中与消火栓关联的节点编成一个新的用水点组"""
        if not self.selected_pipes:
            self.show_temp_message("请先选择至少一个消火栓或关联管道", 2000)
            return
        target_nodes = set()
        for pid in self.selected_pipes:
            pipe = self.cad_data_manager.pipe_by_id.get(pid)
            if not pipe:
                continue
            for node_id in (pipe.start_node_id, pipe.end_node_id):
                node = self.cad_data_manager.node_by_id.get(node_id)
                if node and node.hydrants:
                    target_nodes.add(node)
        if not target_nodes:
            self.show_temp_message("选择集中没有找到消火栓", 2000)
            return
    
        from tkinter import simpledialog
        group_name = simpledialog.askstring("新建用水点组", "请输入用水点组名称:", initialvalue="消火栓组", parent=self)
        if not group_name:
            return
    
        new_group = DemandGroupData(
            group_id=group_name,
            group_name=group_name,
            is_selected=False,
            total_flow=0.0,
            min_pressure=0.0,
            demand_nodes=[]
        )
        for node in target_nodes:
            demand_node = DemandNodeData(
                node_id=node.node_id,
                status="关",
                flow=0.0,
                pressure=0.0,
                attribute_value=group_name,
                cad_handle=""
            )
            new_group.demand_nodes.append(demand_node)
            node.node_type = f"用水点-{group_name}"
        self.cad_data_manager.demand_groups[group_name] = new_group
    
        self._refresh_other_pages()
        self.show_temp_message(f"已创建用水点组 {group_name}，包含 {len(target_nodes)} 个消火栓", 2000)

    # ==================== 检修区管理 ====================
    def _get_valve_on_pipe(self, pipe_id):
        """查找指定管道上的阀门，返回 ValveData 或 None"""
        for v in self.cad_data_manager.valves:
            if v.pipe_id == pipe_id:
                return v
        return None

    def _is_stop_node_condition(self, node):
        """判断节点是否为遍历停止条件（自由端/消火栓/供用水点）"""
        if node is None:
            return True
        if len(node.connected_pipes) <= 1:
            return True
        if node.hydrants:
            return True
        if "供水点" in node.node_type:
            return True
        if "用水点" in node.node_type:
            return True
        return False

    def _find_maintenance_zone_for_pipe(self, pipe_id):
        """查找某管道所属的检修区，若不在任何检修区中则返回 None"""
        for zone in self.maintenance_zones:
            if pipe_id in zone.pipe_ids:
                return zone
        return None

    def _traverse_maintenance_zone(self, start_pipe_id):
        """
        从起始管道出发，BFS 遍历检修区。
        返回 (zone_pipes, zone_valves, zone_nodes) 三个 set。
        """
        from collections import deque
        pipe = self.cad_data_manager.pipe_by_id.get(start_pipe_id)
        if not pipe:
            return set(), set(), set()

        zone_pipes = {start_pipe_id}
        zone_valves = set()
        zone_nodes = set()
        visited_nodes = set()

        # 起始管道上的阀门也关闭
        start_valve = self._get_valve_on_pipe(start_pipe_id)
        if start_valve:
            zone_valves.add(start_valve.valve_id)

        # 从两端节点开始 BFS
        queue = deque()
        for nid in (pipe.start_node_id, pipe.end_node_id):
            node = self.cad_data_manager.node_by_id.get(nid)
            if node:
                zone_nodes.add(nid)
                visited_nodes.add(nid)
                queue.append(node)

        while queue:
            current_node = queue.popleft()
            for connected_pipe_id in list(current_node.connected_pipes):
                if connected_pipe_id in zone_pipes:
                    continue

                cp = self.cad_data_manager.pipe_by_id.get(connected_pipe_id)
                if not cp:
                    continue

                # 检查管道上是否有阀门
                valve = self._get_valve_on_pipe(connected_pipe_id)
                if valve:
                    zone_pipes.add(connected_pipe_id)
                    zone_valves.add(valve.valve_id)
                    continue

                # 获取另一端节点
                other_node_id = (cp.start_node_id if cp.end_node_id == current_node.node_id
                                 else cp.end_node_id)
                other_node = self.cad_data_manager.node_by_id.get(other_node_id)
                if not other_node:
                    continue

                # 检查另一端节点是否为停止条件
                if self._is_stop_node_condition(other_node):
                    zone_pipes.add(connected_pipe_id)
                    zone_nodes.add(other_node_id)
                    continue

                # 继续遍历
                zone_pipes.add(connected_pipe_id)
                if other_node_id not in visited_nodes:
                    visited_nodes.add(other_node_id)
                    zone_nodes.add(other_node_id)
                    queue.append(other_node)

        return zone_pipes, zone_valves, zone_nodes

    def execute_maintenance(self, pipe_id):
        """执行管道检修：遍历并隔离检修区。"""
        pipe = self.cad_data_manager.pipe_by_id.get(pipe_id)
        if not pipe:
            return

        # 检查是否已在检修区
        existing = self._find_maintenance_zone_for_pipe(pipe_id)
        if existing:
            messagebox.showinfo("提示", "该管道已在检修区中")
            return

        # BFS 遍历
        zone_pipes, zone_valves, zone_nodes = self._traverse_maintenance_zone(pipe_id)

        if not zone_pipes:
            return

        # 检查是否与已有检修区重叠
        for existing_zone in self.maintenance_zones:
            if zone_pipes & existing_zone.pipe_ids:
                messagebox.showwarning("重叠检修区",
                    "遍历结果与已有检修区重叠，请先取消已有检修区")
                return

        # 应用状态变更
        for pid in zone_pipes:
            p = self.cad_data_manager.pipe_by_id.get(pid)
            if p:
                p.status = "关"

        for vid in zone_valves:
            v = self.cad_data_manager.valve_by_id.get(vid)
            if v:
                v.status = "CLOSED"

        for nid in zone_nodes:
            n = self.cad_data_manager.node_by_id.get(nid)
            if n:
                n.status = "关"

        # 记录检修区
        zone_id = f"maintenance_zone_{self._next_zone_id}"
        self._next_zone_id += 1
        zone = MaintenanceZone(
            zone_id=zone_id,
            pipe_ids=zone_pipes,
            valve_ids=zone_valves,
            node_ids=zone_nodes,
        )
        self.maintenance_zones.append(zone)

        # 刷新
        self.compute_reachability()
        self.redraw()

    def undo_maintenance(self, zone):
        """取消检修：恢复检修区内所有管道、阀门、节点。"""
        for pid in zone.pipe_ids:
            p = self.cad_data_manager.pipe_by_id.get(pid)
            if p:
                p.status = "开"

        for vid in zone.valve_ids:
            v = self.cad_data_manager.valve_by_id.get(vid)
            if v:
                v.status = "OPEN"

        for nid in zone.node_ids:
            n = self.cad_data_manager.node_by_id.get(nid)
            if n:
                n.status = "开"

        if zone in self.maintenance_zones:
            self.maintenance_zones.remove(zone)

        self.compute_reachability()
        self.redraw()

    def _refresh_other_pages(self):
        root = self.winfo_toplevel()
        if hasattr(root, 'main_app'):
            for name, page in root.main_app.pages.items():
                if name != "管网预览" and hasattr(page, 'refresh_data'):
                    try:
                        page.refresh_data()
                    except Exception as e:
                        logger.error(f"刷新页面 {name} 失败: {e}")

    # ==================== 供水点/用水点辅助函数 ====================
    def _get_free_end_nodes_from_pipes(self, pipes: List[PipeData]) -> Set[NodeData]:
        """从管道列表中获取所有自由端节点（连接管道数==1）"""
        free_nodes = set()
        for pipe in pipes:
            start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
            end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
            if start_node and len(start_node.connected_pipes) == 1:
                free_nodes.add(start_node)
            if end_node and len(end_node.connected_pipes) == 1:
                free_nodes.add(end_node)
        return free_nodes
    
    def _get_supply_point_on_node(self, node: NodeData) -> Optional[SupplyNodeData]:
        """查找节点上的供水点（返回所属的 SupplyNodeData）"""
        for supply in self.cad_data_manager.supply_nodes:
            if node.node_id in supply.node_ids:
                return supply
        return None
    
    def _get_demand_point_on_node(self, node: NodeData) -> Optional[Tuple[str, DemandNodeData]]:
        """查找节点上的用水点，返回 (group_id, DemandNodeData)"""
        for group_id, group in self.cad_data_manager.demand_groups.items():
            for dn in group.demand_nodes:
                if dn.node_id == node.node_id:
                    return (group_id, dn)
        return None
    
    def _get_next_group_number(self, point_type: str) -> int:
        """获取下一个可用的组序号（供水或用水）"""
        if point_type == "supply":
            prefix = "供水"
            groups = self.cad_data_manager.supply_nodes
        else:  # demand
            prefix = "用水"
            groups = self.cad_data_manager.demand_groups.values()
        max_num = 0
        for g in groups:
            name = g.group_id if point_type == "supply" else g.group_name
            if name.startswith(prefix):
                try:
                    num = int(name[len(prefix):])
                    if num > max_num:
                        max_num = num
                except:
                    pass
        return max_num + 1
    
    def _create_supply_group_for_node(self, node: NodeData) -> SupplyNodeData:
        """将节点添加到公共供水点组（不存在则创建）"""
        # 查找公共供水点组（组名固定为"供水点组"）
        common_group = None
        for supply in self.cad_data_manager.supply_nodes:
            if supply.group_id == "供水点组":
                common_group = supply
                break
        
        if common_group is None:
            # 创建公共组
            common_group = SupplyNodeData(
                group_id="供水点组",
                node_ids=[],
                pressure=0.0,
                total_flow=0.0,
                block_name="",
                attribute_name="",
                attribute_value="",
                cad_handle=""
            )
            self.cad_data_manager.supply_nodes.append(common_group)
        
        # 将节点加入公共组（避免重复）
        if node.node_id not in common_group.node_ids:
            common_group.node_ids.append(node.node_id)
        
        node.node_type = f"供水点-{common_group.group_id}"
        return common_group
    
    def _create_demand_group_for_node(self, node: NodeData) -> DemandGroupData:
        """为节点创建新的单点用水组"""
        group_name = f"用水{self._get_next_group_number('demand')}"
        demand_node = DemandNodeData(
            node_id=node.node_id,
            status="关",
            flow=0.0,
            pressure=0.0,
            attribute_value=group_name,
            cad_handle=""
        )
        group = DemandGroupData(
            group_id=group_name,
            group_name=group_name,
            is_selected=False,
            total_flow=0.0,
            min_pressure=0.0,
            demand_nodes=[demand_node]
        )
        self.cad_data_manager.demand_groups[group_name] = group
        node.node_type = f"用水点-{group_name}"
        return group
    
    def _refresh_supply_demand_page(self):
        """刷新供水点和用水点页面"""
        root = self.winfo_toplevel()
        if hasattr(root, 'main_app') and '供水点和用水点' in root.main_app.pages:
            root.main_app.pages['供水点和用水点'].refresh_data()

    # ==================== 添加/删除供水点/用水点 ====================
    def _add_points_to_pipes(self, pipes: List[PipeData], point_type: str):
        """为管道列表的自由端添加供水点或用水点（内部通用）"""
        free_nodes = self._get_free_end_nodes_from_pipes(pipes)
        if not free_nodes:
            self.show_temp_message("所选管道没有自由端节点", 2000)
            return
        added = 0
        skipped = 0
        for node in free_nodes:
            # 检查节点是否已有任何类型的点（供水点或用水点）
            has_supply = self._get_supply_point_on_node(node) is not None
            has_demand = self._get_demand_point_on_node(node) is not None
            if has_supply or has_demand:
                skipped += 1
                continue
            if point_type == "supply":
                self._create_supply_group_for_node(node)
            else:
                self._create_demand_group_for_node(node)
            added += 1
        if added > 0:
            self._refresh_supply_demand_page()
            self.redraw()
            self.show_temp_message(f"已添加 {added} 个{('供水点' if point_type=='supply' else '用水点')}", 2000)
        if skipped > 0:
            self.show_temp_message(f"跳过 {skipped} 个已有点的节点", 2000)
    
    def add_supply_point(self, pipe: PipeData):
        """单根管道添加供水点"""
        self._add_points_to_pipes([pipe], "supply")
    
    def add_demand_point(self, pipe: PipeData):
        """单根管道添加用水点"""
        self._add_points_to_pipes([pipe], "demand")
    
    def add_supply_points_selected(self):
        """选择集添加供水点"""
        if not self.selected_pipes:
            return
        pipes = [self.cad_data_manager.pipe_by_id[pid] for pid in self.selected_pipes if pid in self.cad_data_manager.pipe_by_id]
        self._add_points_to_pipes(pipes, "supply")
    
    def add_demand_points_selected(self):
        """选择集添加用水点"""
        if not self.selected_pipes:
            return
        pipes = [self.cad_data_manager.pipe_by_id[pid] for pid in self.selected_pipes if pid in self.cad_data_manager.pipe_by_id]
        self._add_points_to_pipes(pipes, "demand")
    
    # ---------- 删除 ----------
    def _delete_points_from_pipes(self, pipes: List[PipeData], point_type: str):
        """从管道自由端删除供水点或用水点"""
        free_nodes = self._get_free_end_nodes_from_pipes(pipes)
        if not free_nodes:
            self.show_temp_message("所选管道没有自由端节点", 2000)
            return
        deleted = 0
        for node in free_nodes:
            if point_type == "supply":
                supply = self._get_supply_point_on_node(node)
                if not supply:
                    continue
                # 从组中移除该节点
                if node.node_id in supply.node_ids:
                    supply.node_ids.remove(node.node_id)
                # 如果组变空，删除组（可选，但为了保持单行，删除后可让下次添加时重建）
                if not supply.node_ids:
                    self.cad_data_manager.supply_nodes.remove(supply)
                node.node_type = "普通"
                deleted += 1
            else:  # demand
                result = self._get_demand_point_on_node(node)
                if not result:
                    continue
                group_id, dn = result
                group = self.cad_data_manager.demand_groups[group_id]
                group.demand_nodes.remove(dn)
                if not group.demand_nodes:
                    del self.cad_data_manager.demand_groups[group_id]
                node.node_type = "普通"
                deleted += 1
        if deleted > 0:
            self._refresh_supply_demand_page()
            self.redraw()
            self.show_temp_message(f"已删除 {deleted} 个{('供水点' if point_type=='supply' else '用水点')}", 2000)
        else:
            self.show_temp_message("没有找到要删除的点", 2000)
    
    def delete_supply_point(self, pipe: PipeData):
        self._delete_points_from_pipes([pipe], "supply")
    
    def delete_demand_point(self, pipe: PipeData):
        self._delete_points_from_pipes([pipe], "demand")
    
    def delete_supply_points_selected(self):
        if not self.selected_pipes:
            return
        pipes = [self.cad_data_manager.pipe_by_id[pid] for pid in self.selected_pipes if pid in self.cad_data_manager.pipe_by_id]
        self._delete_points_from_pipes(pipes, "supply")
    
    def delete_demand_points_selected(self):
        if not self.selected_pipes:
            return
        pipes = [self.cad_data_manager.pipe_by_id[pid] for pid in self.selected_pipes if pid in self.cad_data_manager.pipe_by_id]
        self._delete_points_from_pipes(pipes, "demand")
    
    # ==================== 编组与移出组 ====================
    def _group_points(self, pipes: List[PipeData], point_type: str):
        """将管道自由端上的用水点编入同一组"""
        if point_type != "demand":
            # 供水点不支持编组（菜单已删除，理论上不会触发）
            self.show_temp_message("仅用水点支持编组", 2000)
            return
        
        free_nodes = self._get_free_end_nodes_from_pipes(pipes)
        if not free_nodes:
            self.show_temp_message("所选管道没有自由端节点", 2000)
            return
    
        # 收集节点上的用水点
        points = []
        for node in free_nodes:
            res = self._get_demand_point_on_node(node)
            if res:
                group_id, dn = res
                points.append((node, group_id, dn))
        
        if not points:
            self.show_temp_message("没有找到要编组的用水点", 2000)
            return
    
        # 弹出对话框选择组
        from tkinter import Toplevel, ttk
        dialog = Toplevel(self)
        dialog.title("选择或输入组名")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("300x100")
    
        ttk.Label(dialog, text="组名:").pack(pady=5)
        combo = ttk.Combobox(dialog, values=self._get_existing_group_names("demand"))
        combo.pack(pady=5, padx=10, fill='x')
        combo.focus_set()
    
        def confirm():
            new_name = combo.get().strip()
            if not new_name:
                messagebox.showwarning("警告", "组名不能为空")
                return
            # 处理重名（视为选择现有组）
            if new_name in self.cad_data_manager.demand_groups:
                target_group = self.cad_data_manager.demand_groups[new_name]
            else:
                target_group = DemandGroupData(
                    group_id=new_name,
                    group_name=new_name,
                    is_selected=False,
                    total_flow=0.0,
                    min_pressure=0.0,
                    demand_nodes=[]
                )
                self.cad_data_manager.demand_groups[new_name] = target_group
    
            moved = 0
            for node, old_group_id, dn in points:
                if old_group_id != new_name:
                    # 从原组移除
                    old_group = self.cad_data_manager.demand_groups[old_group_id]
                    old_group.demand_nodes.remove(dn)
                    if not old_group.demand_nodes:
                        del self.cad_data_manager.demand_groups[old_group_id]
                    # 加入目标组
                    new_dn = DemandNodeData(
                        node_id=dn.node_id,
                        status=dn.status,
                        flow=dn.flow,
                        pressure=dn.pressure,
                        attribute_value=new_name,
                        cad_handle=""
                    )
                    target_group.demand_nodes.append(new_dn)
                    node.node_type = f"用水点-{new_name}"
                    moved += 1
            if moved > 0:
                self._refresh_supply_demand_page()
                self.redraw()
                self.show_temp_message(f"已将 {moved} 个点编入组 {new_name}", 2000)
            else:
                self.show_temp_message("没有点被移动", 2000)
            dialog.destroy()
    
        ttk.Button(dialog, text="确认", command=confirm).pack(pady=5)
        ttk.Button(dialog, text="取消", command=dialog.destroy).pack(pady=5)
        self.center_dialog(dialog)

    def _get_existing_group_names(self, point_type: str) -> List[str]:
        """获取现有组名列表（供水或用水）"""
        if point_type == "supply":
            return [sp.group_id for sp in self.cad_data_manager.supply_nodes]
        else:
            return list(self.cad_data_manager.demand_groups.keys())
    
    def group_demand_points_selected(self):
        """选择集编组用水点"""
        if not self.selected_pipes:
            return
        pipes = [self.cad_data_manager.pipe_by_id[pid] for pid in self.selected_pipes if pid in self.cad_data_manager.pipe_by_id]
        self._group_points(pipes, "demand")
    
    def _ungroup_points(self, pipes: List[PipeData], point_type: str):
        """将管道自由端上的用水点移出当前组，变成单点组"""
        if point_type != "demand":
            self.show_temp_message("仅用水点支持移出组", 2000)
            return
        
        free_nodes = self._get_free_end_nodes_from_pipes(pipes)
        if not free_nodes:
            self.show_temp_message("所选管道没有自由端节点", 2000)
            return
        
        moved = 0
        for node in free_nodes:
            res = self._get_demand_point_on_node(node)
            if not res:
                continue
            group_id, dn = res
            group = self.cad_data_manager.demand_groups[group_id]
            if len(group.demand_nodes) <= 1:
                continue  # 单点组不移出
            # 从原组移除
            group.demand_nodes.remove(dn)
            if not group.demand_nodes:
                del self.cad_data_manager.demand_groups[group_id]
            # 创建新单点组
            self._create_demand_group_for_node(node)
            moved += 1
        
        if moved > 0:
            self._refresh_supply_demand_page()
            self.redraw()
            self.show_temp_message(f"已将 {moved} 个点移出组", 2000)
        else:
            self.show_temp_message("没有可移出的点（可能是单点组或无点）", 2000)

    def ungroup_demand_points_selected(self):
        if not self.selected_pipes:
            return
        pipes = [self.cad_data_manager.pipe_by_id[pid] for pid in self.selected_pipes if pid in self.cad_data_manager.pipe_by_id]
        self._ungroup_points(pipes, "demand")
    
    # 单根管道的编组/移出组（临时构造选择集）
    def group_demand_point(self, pipe: PipeData):
        self.selected_pipes = {pipe.pipe_id}
        self.group_demand_points_selected()
        self.selected_pipes.clear()
    
    def ungroup_demand_point(self, pipe: PipeData):
        self.selected_pipes = {pipe.pipe_id}
        self.ungroup_demand_points_selected()
        self.selected_pipes.clear()

    def _build_node_menu(self, menu, node):
        # 如果节点有消火栓，则提供用水点组菜单
        if node.hydrants:
            hydrant_id = node.hydrants[0]
            current_group = None
            for gid, group in self.cad_data_manager.demand_groups.items():
                for dn in group.demand_nodes:
                    if dn.node_id == node.node_id:
                        current_group = gid
                        break
                if current_group:
                    break
            if current_group:
                menu.add_command(label="移出用水点组", 
                                 command=lambda nid=node.node_id, g=current_group: self.remove_node_from_demand_group(nid, g))
            else:
                groups = list(self.cad_data_manager.demand_groups.keys())
                if groups:
                    submenu = tk.Menu(menu, tearoff=0)
                    for gid in groups:
                        submenu.add_command(label=gid, 
                                            command=lambda nid=node.node_id, g=gid: self.add_node_to_demand_group(nid, g))
                    menu.add_cascade(label="加入用水点组", menu=submenu)
            menu.add_separator()
        menu.add_command(label="取消", command=lambda: None)

    def _can_be_hydrant_branch(self, pipe):
        """检查管道是否满足改为消火栓支管的条件（消火栓系统，且一端自由，且自由端节点不是供水点）"""
        config = self.config_manager.get_live_config()
        if config.get("system_type") != "indoor_hydrant":
            return False
        start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
        end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
        # 检查两端是否有供水点（禁止）
        for node in (start_node, end_node):
            if node and "供水点" in node.node_type:
                return False
        # 检查是否有自由端（仅连接此管道且无消火栓）
        for node in (start_node, end_node):
            if node and len(node.connected_pipes) == 1 and not node.hydrants:
                return True
        return False

    def _is_part_of_branch_chain(self, pipe):
        """判断管道是否属于可缩小的支管链（消火栓模式，且位于从末端自由端向上到分支点的单管链上）"""
        config = self.config_manager.get_live_config()
        if config.get("system_type") != "indoor_hydrant":
            return False
        # 尝试找到自由端
        free_node = self._find_free_end_from_pipe(pipe)
        if not free_node:
            return False
        chain_pipes = self._get_branch_chain_pipes(free_node)
        return pipe.pipe_id in chain_pipes

    def _get_branch_chain_pipes(self, free_node):
        """从自由端节点开始向上游收集支管链上的所有管道，直到分支点（连接数>=3）或供水点"""
        chain_pipes = set()
        from collections import deque
        queue = deque()
        queue.append((free_node, None))  # (节点, 来的管道ID)
        visited_nodes = {free_node.node_id}
        
        while queue:
            node, from_pipe_id = queue.popleft()
            # 如果是供水点，停止
            if "供水点" in node.node_type:
                continue
            for pid in node.connected_pipes:
                if pid == from_pipe_id:
                    continue
                pipe = self.cad_data_manager.pipe_by_id.get(pid)
                if not pipe:
                    continue
                chain_pipes.add(pid)
                # 找到另一端节点
                other_id = pipe.start_node_id if pipe.end_node_id == node.node_id else pipe.end_node_id
                other_node = self.cad_data_manager.node_by_id.get(other_id)
                if not other_node:
                    continue
                # 如果另一端节点度数 >= 3 或者是供水点，则停止扩展
                if len(other_node.connected_pipes) >= 3 or "供水点" in other_node.node_type:
                    continue
                if other_node.node_id not in visited_nodes:
                    visited_nodes.add(other_node.node_id)
                    queue.append((other_node, pid))
        return chain_pipes

    def shrink_branch_chain(self, pipe_id):
        """将包含指定管道的支管链上的所有管道缩小到DN65"""
        pipe = self.cad_data_manager.pipe_by_id.get(pipe_id)
        if not pipe:
            return
        config = self.config_manager.get_live_config()
        if config.get("system_type") != "indoor_hydrant":
            self.show_temp_message("仅室内消火栓模式支持此功能", 2000)
            return
        
        # 找到自由端节点
        start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
        end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
        free_node = None
        if start_node and len(start_node.connected_pipes) == 1:
            free_node = start_node
        elif end_node and len(end_node.connected_pipes) == 1:
            free_node = end_node
        
        if not free_node:
            # 没有直接的自由端，尝试从两端查找自由端
            free_node = self._find_free_end_from_pipe(pipe)
            if not free_node:
                self.show_temp_message("未找到支管链的自由端", 2000)
                return
        
        # 获取整条链上的管道
        chain_pipes = self._get_branch_chain_pipes(free_node)
        if not chain_pipes:
            self.show_temp_message("未找到可缩小的支管链", 2000)
            return
        
        material = config.get("pipe_material", "镀锌钢管")
        modified = False
        for pid in chain_pipes:
            p = self.cad_data_manager.pipe_by_id.get(pid)
            if not p:
                continue
            current_dn = p.nominal_diameter
            # 只缩小大于DN65的管道
            if current_dn == "DN65":
                continue
            # 获取缩小一级的管径，但最终目标为DN65，可多次缩小
            new_dn = current_dn
            while new_dn != "DN65":
                next_dn = self.material_manager.get_next_diameter(
                    new_dn, "down", material, "indoor_hydrant"
                )
                if next_dn == new_dn:
                    break
                new_dn = next_dn
                if new_dn == "DN65":
                    break
            if new_dn == current_dn:
                continue
            # 检查缩小到DN65时的自由端条件（支管链末端必须满足）
            if new_dn == "DN65":
                # 检查该管道是否在自由端位置（仅当管道连接自由端时才需检查）
                # 实际上支管链中所有管道都允许缩小到DN65，但为了安全，只检查最末端的管道
                # 这里简化：只要链条中有自由端且管道在链条上，就允许
                pass
            new_info = self.material_manager.get_diameter_info(material, new_dn)
            if not new_info.get("inner", 0):
                continue
            self._record_change('attr', p, 'nominal_diameter', current_dn, new_dn)
            p.nominal_diameter = new_dn
            p.inner_diameter = new_info["inner"]
            modified = True
        
        if modified:
            self.cad_data_manager.update_pipe_types(config)
            self._refresh_after_modification(keep_view=True)
            self.show_temp_message(f"已将支管链上的 {len(chain_pipes)} 条管道缩小到DN65", 2000)
        else:
            self.show_temp_message("支管链上所有管道已是DN65或更小", 2000)

    def _find_free_end_from_pipe(self, pipe):
        """从管道出发，查找任意一端的自由端节点（度数==1且不是供水点）"""
        start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
        end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
        
        def dfs_find_free(node, visited):
            if node.node_id in visited:
                return None
            visited.add(node.node_id)
            # 自由端：连接数==1且不是供水点
            if len(node.connected_pipes) == 1 and "供水点" not in node.node_type:
                return node
            # 如果节点度数==2，继续向另一个节点走
            if len(node.connected_pipes) == 2:
                for pid in node.connected_pipes:
                    p = self.cad_data_manager.pipe_by_id.get(pid)
                    if not p:
                        continue
                    next_id = p.start_node_id if p.end_node_id == node.node_id else p.end_node_id
                    next_node = self.cad_data_manager.node_by_id.get(next_id)
                    if next_node and next_node.node_id not in visited:
                        res = dfs_find_free(next_node, visited)
                        if res:
                            return res
            return None
        
        visited = set()
        free = dfs_find_free(start_node, visited) if start_node else None
        if not free:
            visited = set()
            free = dfs_find_free(end_node, visited) if end_node else None
        return free
  
    def _is_on_single_chain(self, pipe):
        """检查管道是否位于某个自由端支链上（两端节点度数都不超过2）"""
        start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
        end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
        if not start_node or not end_node:
            return False
        # 从两个方向向外寻找自由端
        def find_free_end(node, visited=None):
            if visited is None:
                visited = set()
            if node.node_id in visited:
                return None
            visited.add(node.node_id)
            if len(node.connected_pipes) == 1:
                return node
            if len(node.connected_pipes) == 2:
                # 继续向另一个节点走
                for pid in node.connected_pipes:
                    pipe_obj = self.cad_data_manager.pipe_by_id.get(pid)
                    if not pipe_obj:
                        continue
                    next_id = pipe_obj.start_node_id if pipe_obj.end_node_id == node.node_id else pipe_obj.end_node_id
                    if next_id in visited:
                        continue
                    next_node = self.cad_data_manager.node_by_id.get(next_id)
                    if next_node:
                        return find_free_end(next_node, visited)
            return None
        
        free1 = find_free_end(start_node)
        free2 = find_free_end(end_node)
        return free1 is not None or free2 is not None

    def change_pipe_diameter(self, pipe_id, direction):
        # 保存当前选择集
        old_selection = set(self.selected_pipes)
        # 临时设置为只包含当前管道
        self.selected_pipes = {pipe_id}
        # 执行操作
        self.change_selected_pipes_diameter(direction)
        # 恢复选择集，并确保当前管道包含在内
        self.selected_pipes = old_selection | {pipe_id}
        # 重绘以更新选择集高亮（change_selected_pipes_diameter 已包含刷新，但可能选择集未更新）
        self.redraw()

    def change_pipe_to_hydrant_branch(self, pipe_id):
        self.selected_pipes = {pipe_id}
        self.change_selected_to_hydrant_branch()

    def change_selected_pipes_diameter(self, direction: str):
        """放大或缩小选中的管道管径"""
        if not self.selected_pipes:
            return
        config = self.config_manager.get_live_config()
        system_type = config.get("system_type", "indoor_hydrant")
        material = config.get("pipe_material", "镀锌钢管")
        modified = False
        for pipe_id in list(self.selected_pipes):
            pipe = self.cad_data_manager.pipe_by_id.get(pipe_id)
            if not pipe:
                continue
            current_dn = pipe.nominal_diameter
            # 获取放大/缩小一级的管径
            new_dn = self.material_manager.get_next_diameter(
                current_dn, direction, material, system_type
            )
            if new_dn == current_dn:
                continue
    
            # 消火栓模式下，缩小到DN65需检查自由端
            if direction == "down" and system_type == "indoor_hydrant":
                new_num = int(new_dn[2:]) if new_dn.startswith("DN") else 0
                if new_num == 65:
                    start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
                    end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
                    free_node = None
                    for node in (start_node, end_node):
                        if node and len(node.connected_pipes) == 1:
                            if "供水点" not in node.node_type and "用水点" not in node.node_type:
                                free_node = node
                                break
                    if not free_node:
                        continue  # 不符合条件，跳过
    
            # 获取新管径信息
            new_info = self.material_manager.get_diameter_info(material, new_dn)
            if not new_info.get("inner", 0):
                continue
    
            # 记录旧值
            self._record_change('attr', pipe, 'nominal_diameter', current_dn, new_dn)
            pipe.nominal_diameter = new_dn
            pipe.inner_diameter = new_info["inner"]
            modified = True
    
        if modified:
            config = self.config_manager.get_live_config()
            self.cad_data_manager.update_pipe_types(config)
            self._refresh_after_modification(keep_view=True)
        else:
            self.show_temp_message("没有可调整的管道", 2000)

    def correct_single_pipe_diameter(self, pipe_id, direction):
        """校正(up放大)或优化(down缩小)单个管道管径，按流速条件和消火栓豁免规则过滤"""
        pipe = self.cad_data_manager.pipe_by_id.get(pipe_id)
        if not pipe or not self.calculation_available:
            return
        config = self.config_manager.get_live_config()
        system_type = config.get("system_type", "outdoor_hydrant")

        velocity = self.pipe_results.get(pipe_id, {}).get('velocity_mps', 0.0)

        if direction == "up" and velocity <= self.velocity_max:
            return
        if direction == "down" and velocity >= self.velocity_min:
            return

        if system_type in ("indoor_hydrant", "outdoor_hydrant"):
            current_dn = pipe.nominal_diameter
            dn_num = int(current_dn[2:]) if current_dn.startswith("DN") else 0
            if dn_num == 65:
                return
            if direction == "down" and dn_num == 100:
                return
            if direction == "down" and dn_num > 100:
                material = config.get("pipe_material", "镀锌钢管")
                new_dn = self.material_manager.get_next_diameter(
                    current_dn, direction, material, system_type
                )
                new_num = int(new_dn[2:]) if new_dn.startswith("DN") else 0
                if new_num < 100:
                    return

        self.change_pipe_diameter(pipe_id, direction)

    def correct_selected_pipes_diameter(self, direction):
        """校正(up)或优化(down)选择集中的管道管径，按流速条件和消火栓豁免规则过滤"""
        if not self.selected_pipes or not self.calculation_available:
            return
        config = self.config_manager.get_live_config()
        system_type = config.get("system_type", "outdoor_hydrant")
        material = config.get("pipe_material", "镀锌钢管")
        modified = False

        for pipe_id in list(self.selected_pipes):
            pipe = self.cad_data_manager.pipe_by_id.get(pipe_id)
            if not pipe:
                continue

            velocity = self.pipe_results.get(pipe_id, {}).get('velocity_mps', 0.0)

            if direction == "up" and velocity <= self.velocity_max:
                continue
            if direction == "down" and velocity >= self.velocity_min:
                continue

            current_dn = pipe.nominal_diameter

            if system_type in ("indoor_hydrant", "outdoor_hydrant"):
                dn_num = int(current_dn[2:]) if current_dn.startswith("DN") else 0
                if dn_num == 65:
                    continue
                if direction == "down" and dn_num == 100:
                    continue
                if direction == "down" and dn_num > 100:
                    new_dn = self.material_manager.get_next_diameter(
                        current_dn, direction, material, system_type
                    )
                    new_num = int(new_dn[2:]) if new_dn.startswith("DN") else 0
                    if new_num < 100:
                        continue

            new_dn = self.material_manager.get_next_diameter(
                current_dn, direction, material, system_type
            )
            if new_dn == current_dn:
                continue

            new_info = self.material_manager.get_diameter_info(material, new_dn)
            if not new_info.get("inner", 0):
                continue

            self._record_change('attr', pipe, 'nominal_diameter', current_dn, new_dn)
            pipe.nominal_diameter = new_dn
            pipe.inner_diameter = new_info["inner"]
            modified = True

        if modified:
            self.cad_data_manager.update_pipe_types(config)
            self._refresh_after_modification(keep_view=True)
        else:
            self.show_temp_message("选择集中没有可调整的管道", 2000)

    def change_selected_to_hydrant_branch(self):
        """将选中的管道改为消火栓支管（管径设为DN65，并尝试在端点创建消火栓）"""
        if not self.selected_pipes:
            return
        config = self.config_manager.get_live_config()
        material = config.get("pipe_material", "镀锌钢管")
        modified = False
        for pipe_id in list(self.selected_pipes):
            pipe = self.cad_data_manager.pipe_by_id.get(pipe_id)
            if not pipe:
                continue
            # 检查是否符合改为支管的条件
            if not self._can_be_hydrant_branch(pipe):
                continue  # 跳过不满足的管道
    
            start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
            end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
            # 选择一个自由端节点
            target_node = None
            if start_node and len(start_node.connected_pipes) == 1 and not start_node.hydrants:
                target_node = start_node
            elif end_node and len(end_node.connected_pipes) == 1 and not end_node.hydrants:
                target_node = end_node
            if not target_node:
                continue  # 理论上不会发生，但防御性编程
    
            # 将管道管径设为DN65，类型改为支管
            new_dn = "DN65"
            new_info = self.material_manager.get_diameter_info(material, new_dn)
            if new_info.get("inner", 0) == 0:
                continue  # 颜色表中无DN65
    
            # 记录旧值
            self._record_change('attr', pipe, 'nominal_diameter', pipe.nominal_diameter, new_dn)
            self._record_change('attr', pipe, 'inner_diameter', pipe.inner_diameter, new_info["inner"])
            pipe.nominal_diameter = new_dn
            pipe.inner_diameter = new_info["inner"]
            pipe.pipe_type = "支管"
            modified = True
    
            # 在目标节点上创建消火栓（如果还没有）
            if not target_node.hydrants:
                new_id = f"H_{len(self.cad_data_manager.hydrants)+1:04d}"
                hydrant = HydrantData(
                    hydrant_id=new_id,
                    node_id=target_node.node_id,
                    x=target_node.x,
                    y=target_node.y,
                    z=target_node.z,
                    block_name=config.get("hydrant_block_name", "hydrant"),
                    entity_handle=""
                )
                # 为消火栓分配所属楼层（基于节点所在的楼层）
                target_floor = None
                for floor in self.cad_data_manager.floors:
                    if target_node in floor.nodes:
                        target_floor = floor
                        break
                if target_floor:
                    hydrant.floor_name = target_floor.name
                    if hydrant not in target_floor.hydrants:
                        target_floor.hydrants.append(hydrant)
                else:
                    hydrant.floor_name = ""

                self.cad_data_manager.hydrants.append(hydrant)
                self.cad_data_manager.hydrant_by_id[new_id] = hydrant
                target_node.hydrants.append(new_id)
                self._record_change('add', hydrant)

                # 新增：将消火栓添加到对应楼层的 hydrants 列表
                if hydrant.floor_name:
                    floor = self.cad_data_manager.floor_by_name.get(hydrant.floor_name)
                    if floor and hydrant not in floor.hydrants:
                        floor.hydrants.append(hydrant)
            # 节点已有消火栓，无需重复创建
    
        if modified:
            config = self.config_manager.get_live_config()
            self.cad_data_manager.update_pipe_types(config)
            self._refresh_after_modification(keep_view=True)
        else:
            self.show_temp_message("没有符合条件的管道", 2000)

    def add_node_to_demand_group(self, node_id, group_id):
        """将指定节点加入用水点组（如果该节点有消火栓）"""
        node = self.cad_data_manager.node_by_id.get(node_id)
        if not node or not node.hydrants:
            self.show_temp_message("该节点没有消火栓，无法加入用水点组", 2000)
            return
        # 检查是否已在某个组中
        for gid, group in self.cad_data_manager.demand_groups.items():
            for dn in group.demand_nodes:
                if dn.node_id == node_id:
                    if gid == group_id:
                        self.show_temp_message(f"节点已在组 {group_id} 中", 2000)
                    else:
                        self.show_temp_message(f"节点已在其他组 {gid} 中，请先移出", 2000)
                    return
        target_group = self.cad_data_manager.demand_groups.get(group_id)
        if not target_group:
            self.show_temp_message(f"用水点组 {group_id} 不存在", 2000)
            return
        demand_node = DemandNodeData(
            node_id=node_id,
            status="关",
            flow=0.0,
            pressure=0.0,
            attribute_value=group_id,
            cad_handle=""
        )
        target_group.demand_nodes.append(demand_node)
        node.node_type = f"用水点-{group_id}"
        self._refresh_other_pages()
        self.show_temp_message(f"节点 {node_id} 已加入组 {group_id}", 2000)
    
    def remove_node_from_demand_group(self, node_id, group_id):
        """将指定节点从用水点组中移除"""
        node = self.cad_data_manager.node_by_id.get(node_id)
        if not node:
            return
        group = self.cad_data_manager.demand_groups.get(group_id)
        if not group:
            return
        group.demand_nodes = [dn for dn in group.demand_nodes if dn.node_id != node_id]
        if node.node_type.startswith("用水点-"):
            node.node_type = "普通"
        self._refresh_other_pages()
        self.show_temp_message(f"节点 {node_id} 已从组 {group_id} 移除", 2000)

    def _refresh_after_modification(self, keep_view=True):
        self.refresh_data(keep_view=keep_view)
        self._refresh_other_pages()
        self.show_temp_message("管径已修改", 2000)

    def _is_valid_branch_candidate(self, pipe):
        """检查管道是否满足改为消火栓支管的条件：
        1. 管网类型为消火栓
        2. 管道一端自由（连接数=1），且该节点不是供水点/用水点，无消火栓
        3. 另一端连接数至少为2（干管）
        """
        config = self.config_manager.get_live_config()
        if config.get("system_type") != "indoor_hydrant":
            return False
        start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
        end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
        if not start_node or not end_node:
            return False
    
        # 找出自由端（连接数=1的节点）
        free_node = None
        other_node = None
        if len(start_node.connected_pipes) == 1:
            free_node = start_node
            other_node = end_node
        elif len(end_node.connected_pipes) == 1:
            free_node = end_node
            other_node = start_node
    
        if not free_node:
            return False  # 没有自由端
    
        # 自由端不能是供水点/用水点，不能已有消火栓
        if "供水点" in free_node.node_type or "用水点" in free_node.node_type:
            return False
        if free_node.hydrants:
            return False
    
        # 另一端必须连接至少2根管道（干管）
        if len(other_node.connected_pipes) < 2:
            return False
    
        return True

    def add_hydrant_on_node(self, node):
        """在指定节点上添加消火栓（不改变管道）"""
        if node.hydrants:
            self.show_temp_message("该节点已有消火栓", 2000)
            return
        if "供水点" in node.node_type:
            self.show_temp_message("不能在供水点添加消火栓", 2000)
            return
        if len(node.connected_pipes) != 1:
            self.show_temp_message("只能向仅连接一根管道的节点添加消火栓", 2000)
            return
        config = self.config_manager.get_live_config()
        new_id = f"H_{len(self.cad_data_manager.hydrants)+1:04d}"
        hydrant = HydrantData(
            hydrant_id=new_id,
            node_id=node.node_id,
            x=node.x, y=node.y, z=node.z,
            block_name=config.get("hydrant_block_name", "hydrant"),
            entity_handle=""
        )
        # ★ 为新消火栓分配楼层名（基于所属节点所在的楼层）
        if self.cad_data_manager.floors:
            for floor in self.cad_data_manager.floors:
                if node in floor.nodes:
                    hydrant.floor_name = floor.name
                    break
        self.cad_data_manager.hydrants.append(hydrant)
        self.cad_data_manager.hydrant_by_id[new_id] = hydrant
        node.hydrants.append(new_id)
        self._record_change('add', hydrant)

        # 新增：将消火栓添加到对应楼层的 hydrants 列表（用于楼层预览）
        if hydrant.floor_name:
            floor = self.cad_data_manager.floor_by_name.get(hydrant.floor_name)
            if floor and hydrant not in floor.hydrants:
                floor.hydrants.append(hydrant)

        self.redraw()
        self.show_temp_message(f"已添加消火栓 {new_id}", 2000)
        

    def _get_hydrant_on_node(self, node):
        """返回节点上的第一个消火栓ID，如果没有则返回None"""
        if node and node.hydrants:
            return node.hydrants[0]
        return None

    def delete_hydrant(self, hydrant_id):
        hydrant = self.cad_data_manager.hydrant_by_id.get(hydrant_id)
        if not hydrant:
            return
        node = self.cad_data_manager.node_by_id.get(hydrant.node_id)
        if node:
            node.hydrants.remove(hydrant_id)
        
        # 从楼层 hydrants 列表中移除
        if hydrant.floor_name:
            floor = self.cad_data_manager.floor_by_name.get(hydrant.floor_name)
            if floor and hydrant in floor.hydrants:
                floor.hydrants.remove(hydrant)
        
        self._record_change('delete', hydrant)
        self.cad_data_manager.hydrants.remove(hydrant)
        del self.cad_data_manager.hydrant_by_id[hydrant_id]
        self.redraw()
        self.show_temp_message(f"已删除消火栓 {hydrant_id}", 2000)

    def draw_hydrant(self, hydrant):
        # 添加诊断日志
        logger.debug(f"draw_hydrant 被调用: hydrant_id={hydrant.hydrant_id}, node_id={hydrant.node_id}, floor_name={hydrant.floor_name}")
        node = self.cad_data_manager.node_by_id.get(hydrant.node_id)
        if not node:
            return
        wpos = self.projected_coords.get(node.node_id)
        if not wpos:
            return

        # B_消火栓支管末端消火栓视觉覆盖：跟随中间节点向左 0.3m
        if getattr(self, '_hydrant_visual_offsets', None):
            mid_id = self._hydrant_visual_offsets.get(hydrant.node_id)
            if mid_id:
                mid_pos = self.projected_coords.get(mid_id)
                if mid_pos:
                    wpos = (mid_pos[0] - 300.0, mid_pos[1])

        cx, cy = self.world_to_canvas(*wpos)
        r = max(8, int(8 * self.scale))   # 半径
        # 画圆（白色轮廓）
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                outline="white", fill="", tags="hydrant")
        # 画右下填充半圆（45°到225°）
        self.canvas.create_arc(cx - r, cy - r, cx + r, cy + r,
                               start=225, extent=180,
                               fill="#FFD700", outline="", tags="hydrant")  # 金色填充

    def draw_hydrant_by_coords(self, hydrant):
        """直接使用消火栓坐标绘制（用于楼层预览，不依赖节点）"""
        wpos = self.project_point(hydrant.x, hydrant.y, hydrant.z)
        if not wpos:
            return
        cx, cy = self.world_to_canvas(*wpos)
        r = max(8, int(8 * self.scale))
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                outline="white", fill="", tags="hydrant")
        self.canvas.create_arc(cx - r, cy - r, cx + r, cy + r,
                               start=225, extent=180,
                               fill="#FFD700", outline="", tags="hydrant")

    def draw_riser(self, riser):
        # 计算立管圆心在画布上的位置
        wpos = self.project_point(riser.x, riser.y, riser.z)
        cx, cy = self.world_to_canvas(*wpos)
        # 绘制圆（默认青色轮廓）
        r = max(6, int(riser.radius * self.scale * 0.1))
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                outline="cyan", width=2, fill="", tags="riser")

        if riser.note:
            lines = riser.note.split('\n')
            # 文字放在立管圆心右下方固定偏移（画布坐标偏移30像素）
            offset_x = 30
            offset_y = 30
            text_x = cx + offset_x
            text_y = cy + offset_y
            # 绘制引线（从圆心到文字位置）
            self.canvas.create_line(cx, cy, text_x, text_y,
                                    fill="white", width=1, dash=(2, 2), tags="riser_note")
            if len(lines) == 2:
                self.canvas.create_text(text_x, text_y - 12, text=lines[0], fill="white",
                                        font=("Arial", 10), tags="riser_note", anchor="w")
                self.canvas.create_text(text_x, text_y + 12, text=lines[1], fill="white",
                                        font=("Arial", 10), tags="riser_note", anchor="w")
            else:
                self.canvas.create_text(text_x, text_y, text=riser.note, fill="white",
                                        font=("Arial", 10), tags="riser_note", anchor="w")

        # 绘制重复立管的红色箭头标记（根据复选框状态）
        if self.show_riser_warning.get() and self.duplicate_risers_by_floor:
            current_floor_name = self.current_floor_name
            if current_floor_name in self.duplicate_risers_by_floor:
                duplicate_list = self.duplicate_risers_by_floor[current_floor_name]
                if any(dr.riser_id == riser.riser_id for dr in duplicate_list):
                    # 绘制一个加长的红色箭头，箭头指向立管圆心
                    arrow_len = max(20, int(20 * self.scale))
                    # 箭头宽度为长度的十分之一
                    arrow_width = max(2, arrow_len // 10)
                    # 计算箭头起点（45度方向的反方向，即从外部指向圆心）
                    angle_rad = math.radians(45)
                    # 起点在外部（从圆心向外偏移 arrow_len）
                    start_x = cx + arrow_len * math.cos(angle_rad)
                    start_y = cy - arrow_len * math.sin(angle_rad)
                    # 终点是圆心
                    end_x = cx
                    end_y = cy
                    # 绘制箭头（注意线的方向是从 start 到 end，箭头在 end 处，指向圆心）
                    self.canvas.create_line(start_x, start_y, end_x, end_y,
                                            fill="red", width=arrow_width,
                                            arrow=tk.LAST,
                                            arrowshape=(arrow_len//2, arrow_len//2, arrow_len//4),
                                            tags="riser_warning")
                    
    def mark_invalid_risers(self):
        """标注无效立管：立管上下节点都没有连接其他有效管道时，将立管和对应节点标记为无效"""
        import logging
        logger = logging.getLogger(__name__)
        
        for pipe in self.cad_data_manager.pipes:
            if not pipe.pipe_id.startswith("R_"):
                continue
            
            start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
            end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
            if not start_node or not end_node:
                continue
            
            def has_other_active_pipe(node, current_pipe_id):
                for pid in node.connected_pipes:
                    if pid == current_pipe_id:
                        continue
                    other_pipe = self.cad_data_manager.pipe_by_id.get(pid)
                    # 注意：这里必须要 other_pipe 存在且 is_active == True
                    if other_pipe and other_pipe.is_active:
                        logger.debug(f"节点 {node.node_id} 有其它有效管道: {pid} (active={other_pipe.is_active})")
                        return True
                return False
            
            start_has_other = has_other_active_pipe(start_node, pipe.pipe_id)
            end_has_other = has_other_active_pipe(end_node, pipe.pipe_id)
            
            logger.info(f"立管 {pipe.pipe_id}: 起点节点 {start_node.node_id} 有其它有效管道? {start_has_other}, 终点节点 {end_node.node_id} 有其它有效管道? {end_has_other}")
            
            if start_has_other and end_has_other:
                continue
            else:
                # 立管无效，标记立管和对应的节点（但不标记共享节点）
                if not start_has_other:
                    # 只标记那些只连接了此立管的节点（自由端）
                    if len(start_node.connected_pipes) == 1:
                        start_node.is_active = False
                        logger.info(f"节点 {start_node.node_id} 被标记为无效（自由端）")
                if not end_has_other:
                    if len(end_node.connected_pipes) == 1:
                        end_node.is_active = False
                        logger.info(f"节点 {end_node.node_id} 被标记为无效（自由端）")
                pipe.is_active = False
                self.show_temp_message(f"立管 {pipe.pipe_id} 已标记为无效", 2000)
        
        self.redraw()
        self._refresh_other_pages()

    def mark_invalid_and_correct_diameters(self):
        """先标注无效立管，再校正管径（仅室内消火栓系统）"""
        self.mark_invalid_risers()
        config = self.config_manager.get_live_config()
        if config.get("system_type") == "indoor_hydrant":
            self.correct_hydrant_branch_diameters()
        else:
            self.show_temp_message("仅室内消火栓系统支持管径校正", 2000)

    def correct_hydrant_branch_diameters(self):
        """
        室内消火栓系统自动调整：从每个消火栓支管的 mid_node 出发，
        沿所有方向（忽略 B_ 支管）遍历管道（包括 P_、R_、L_），
        收集每个方向路径上的所有管道（含第一根管道），
        根据两端终止节点类型决定是否将**两个方向**的所有管道改为 DN65。
        注意：无效管也参与遍历（但遇到第一根无效管时，该方向直接终止），终止节点判断基于有效度数。
        """
        config = self.config_manager.get_live_config()
        if config.get("system_type") != "indoor_hydrant":
            return

        cad = self.cad_data_manager
        material = config.get("pipe_material", "镀锌钢管")
        target_dn = "DN65"
        target_info = self.material_manager.get_diameter_info(material, target_dn)
        if not target_info or target_info.get("inner", 0) == 0:
            self.show_temp_message(f"未找到管径 {target_dn} 信息，无法校正", 2000)
            return
        target_inner = target_info["inner"]

        # 1. 收集所有 B_ 支管对应的 mid_node（与立管相连的那个节点）
        mid_nodes = set()
        for pipe in cad.pipes:
            if pipe.pipe_id.startswith("B_"):
                start_node = cad.node_by_id.get(pipe.start_node_id)
                end_node = cad.node_by_id.get(pipe.end_node_id)
                for node in (start_node, end_node):
                    if node and any(pid.startswith("R_") for pid in node.connected_pipes):
                        mid_nodes.add(node.node_id)
                        break

        if not mid_nodes:
            self.show_temp_message("没有找到需要遍历的消火栓支管连接点", 2000)
            return

        # 辅助函数：获取节点的有效度数（只统计 is_active 的管道）
        def effective_degree(node):
            if not node:
                return 0
            count = 0
            for pid in node.connected_pipes:
                p = cad.pipe_by_id.get(pid)
                if p and p.is_active:
                    count += 1
            return count

        # 2. 方向遍历函数（处理无效管特殊规则）
        def traverse_one_direction(mid_node_id, start_pipe_id):
            # 第一根管道
            pipe = cad.pipe_by_id.get(start_pipe_id)
            if not pipe:
                return None, []
            # 特殊处理：第一根管道是无效管
            if not pipe.is_active:
                # 直接记录该管道，终止节点视为自由节点（因为其另一端节点必然是自由节点）
                return "FREE_NODE", [start_pipe_id]
            # 管道有效，开始遍历
            if pipe.start_node_id == mid_node_id:
                current_node_id = pipe.end_node_id
            else:
                current_node_id = pipe.start_node_id
            path_pipes = [start_pipe_id]
            visited_nodes = {mid_node_id}
            while True:
                if current_node_id in visited_nodes:
                    return None, []  # 回路
                visited_nodes.add(current_node_id)
                node = cad.node_by_id.get(current_node_id)
                if not node:
                    return None, []
                deg = effective_degree(node)
                if deg == 1:
                    return current_node_id, path_pipes
                if deg >= 3:
                    return current_node_id, path_pipes
                # deg == 2，继续向另一根有效管道前进
                incoming_pipe = path_pipes[-1]
                next_pipe_id = None
                for pid in node.connected_pipes:
                    if pid == incoming_pipe:
                        continue
                    p = cad.pipe_by_id.get(pid)
                    if p and p.is_active:
                        next_pipe_id = pid
                        break
                if not next_pipe_id:
                    return None, []
                next_pipe = cad.pipe_by_id.get(next_pipe_id)
                if not next_pipe or not next_pipe.is_active:
                    return None, []
                path_pipes.append(next_pipe_id)
                if next_pipe.start_node_id == current_node_id:
                    current_node_id = next_pipe.end_node_id
                else:
                    current_node_id = next_pipe.start_node_id

        warnings = []
        modified = False

        # 3. 对每个 mid_node 处理
        for mid_node_id in mid_nodes:
            mid_node = cad.node_by_id.get(mid_node_id)
            if not mid_node:
                continue

            # 获取所有非 B_ 的连接管道（需要遍历的方向）
            directions = [pid for pid in mid_node.connected_pipes if not pid.startswith("B_")]
            if len(directions) < 2:
                warnings.append(f"节点 {mid_node_id} 连接管道不足2个方向，跳过")
                continue

            dir_results = []  # 每个元素为 (终止节点ID或"FREE_NODE", 路径管道列表)
            loop_error = False
            for dir_pipe_id in directions:
                term_node, path_pipes = traverse_one_direction(mid_node_id, dir_pipe_id)
                if term_node is None:
                    loop_error = True
                    break
                dir_results.append((term_node, path_pipes))

            if loop_error:
                warnings.append(f"节点 {mid_node_id} 出发的路径中存在回路，跳过")
                continue

            # 判断终止节点是否为自由节点（有效度数 == 1）
            def is_free(term):
                if term == "FREE_NODE":
                    return True
                node = cad.node_by_id.get(term)
                if not node:
                    return False
                return effective_degree(node) == 1

            free_flags = [is_free(term) for term, _ in dir_results]

            if all(free_flags):
                warnings.append(f"节点 {mid_node_id} 所有方向都终止于自由节点，绘图错误")
                continue
            if not any(free_flags):
                continue

            # 至少有一个自由节点 -> 将所有方向路径上的所有管道改为 DN65
            pipes_to_change = set()
            for _, path_pipes in dir_results:
                pipes_to_change.update(path_pipes)
            for pid in pipes_to_change:
                pipe = cad.pipe_by_id.get(pid)
                if pipe and pipe.nominal_diameter != target_dn:
                    pipe.nominal_diameter = target_dn
                    pipe.inner_diameter = target_inner
                    modified = True
                    logger.info(f"自动调整管道 {pid} 为 {target_dn}")

        if modified:
            cad.update_pipe_types(config)
            self.redraw()
            self._refresh_other_pages()
            self.show_temp_message("管径校正完成", 2000)
        else:
            self.show_temp_message("没有需要调整的管道", 2000)

        if warnings:
            full_msg = "校正警告：\n" + "\n".join(warnings)
            if len(warnings) > 5:
                full_msg = "校正警告：\n" + "\n".join(warnings[:5]) + f"\n... 共 {len(warnings)} 条"
            self._show_auto_dismiss_popup(full_msg, 5000)

    def _show_auto_dismiss_popup(self, message, duration=5000):
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

    def delete_invalid_pipes(self):
        """删除所有标记为无效的管道和节点（弹出确认对话框），记录撤销信息。"""
        invalid_pipes = [p for p in self.cad_data_manager.pipes if not p.is_active]
        invalid_nodes = [n for n in self.cad_data_manager.nodes if not n.is_active and len(n.connected_pipes) == 0]

        if not invalid_pipes and not invalid_nodes:
            self.show_temp_message("没有需要删除的无效管道或孤立无效节点", 2000)
            return

        msg = f"即将删除 {len(invalid_pipes)} 条管道和 {len(invalid_nodes)} 个孤立节点，是否确认？"
        if not messagebox.askyesno("确认删除", msg):
            return

        # ---- 收集撤销数据（删除前） ----
        undo_pipes = list(invalid_pipes)
        undo_nodes = list(invalid_nodes)
        undo_hydrants = []
        for node in invalid_nodes:
            for hid in list(node.hydrants):
                hydrant = self.cad_data_manager.hydrant_by_id.get(hid)
                if hydrant:
                    undo_hydrants.append(hydrant)
        undo_risers = []
        for pipe in invalid_pipes:
            if pipe.pipe_id.startswith('R_'):
                riser = self.cad_data_manager.riser_by_id.get(pipe.pipe_id)
                if riser:
                    undo_risers.append(riser)

        # 记录撤销命令
        cmd = {
            'type': 'delete_invalid_batch',
            'pipes': undo_pipes,
            'nodes': undo_nodes,
            'hydrants': undo_hydrants,
            'risers': undo_risers,
        }
        self.undo_stack.append(cmd)
        self.redo_stack.clear()
        if len(self.undo_stack) > self.max_undo:
            self.undo_stack.pop(0)

        # ---- 执行删除 ----
        deleted_riser_ids = []
        for pipe in invalid_pipes:
            start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
            end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
            if start_node and pipe.pipe_id in start_node.connected_pipes:
                start_node.connected_pipes.remove(pipe.pipe_id)
            if end_node and pipe.pipe_id in end_node.connected_pipes:
                end_node.connected_pipes.remove(pipe.pipe_id)
            for floor in self.cad_data_manager.floors:
                if pipe in floor.pipes:
                    floor.pipes.remove(pipe)
            self.cad_data_manager.pipes.remove(pipe)
            del self.cad_data_manager.pipe_by_id[pipe.pipe_id]
            if pipe.pipe_id.startswith('R_'):
                deleted_riser_ids.append(pipe.pipe_id)

        for riser_id in deleted_riser_ids:
            riser = self.cad_data_manager.riser_by_id.get(riser_id)
            if riser:
                for floor in self.cad_data_manager.floors:
                    if hasattr(floor, 'risers') and riser in floor.risers:
                        floor.risers.remove(riser)
                if riser in self.cad_data_manager.risers:
                    self.cad_data_manager.risers.remove(riser)
                del self.cad_data_manager.riser_by_id[riser_id]

        self.cad_data_manager.check_duplicate_risers_in_floor()
        self.duplicate_risers_by_floor = self.cad_data_manager.duplicate_risers_by_floor

        for node in invalid_nodes:
            for hid in list(node.hydrants):
                hydrant = self.cad_data_manager.hydrant_by_id.get(hid)
                if hydrant:
                    self.cad_data_manager.hydrants.remove(hydrant)
                    del self.cad_data_manager.hydrant_by_id[hid]
            for floor in self.cad_data_manager.floors:
                if node in floor.nodes:
                    floor.nodes.remove(node)
            self.cad_data_manager.nodes.remove(node)
            del self.cad_data_manager.node_by_id[node.node_id]

        config = self.config_manager.get_live_config()
        self.cad_data_manager.update_pipe_types(config)

        self.occlusion_cache_valid = False
        self.redraw()
        self._refresh_other_pages()
        self.show_temp_message(f"已删除 {len(invalid_pipes)} 条管道和 {len(invalid_nodes)} 个孤立节点", 2000)

    def point_to_line_distance(self, p, a, b):
        ax, ay = a
        bx, by = b
        px, py = p
        abx = bx - ax
        aby = by - ay
        apx = px - ax
        apy = py - ay
        t = (apx * abx + apy * aby) / (abx * abx + aby * aby) if (abx*abx + aby*aby) > 0 else 0
        if t < 0:
            t = 0
        elif t > 1:
            t = 1
        projx = ax + t * abx
        projy = ay + t * aby
        return math.hypot(px - projx, py - projy)

    def clear_selection(self):
        self.selected_pipe_id = None
        self.selected_valve_id = None
        self.redraw()

    # ----------------------------------------------------------------------
    # 阀门操作
    # ----------------------------------------------------------------------
    def add_valve_on_pipe(self, pipe_id):
        for valve in self.cad_data_manager.valves:
            if valve.pipe_id == pipe_id:
                self.show_temp_message("该管道已存在阀门", 2000)
                return
        pipe = self.cad_data_manager.pipe_by_id.get(pipe_id)
        if not pipe:
            return
        mid_x = (pipe.start_point[0] + pipe.end_point[0]) / 2
        mid_y = (pipe.start_point[1] + pipe.end_point[1]) / 2
        mid_z = (pipe.start_point[2] + pipe.end_point[2]) / 2

        max_id = 0
        for v in self.cad_data_manager.valves:
            if v.valve_id.startswith("V_"):
                try:
                    num = int(v.valve_id[2:])
                    if num > max_id:
                        max_id = num
                except:
                    pass
        new_id = f"V_{max_id+1:04d}"

        from cad_data_manager import ValveData
        new_valve = ValveData(
            valve_id=new_id,
            pipe_id=pipe_id,
            status="OPEN",
            x=mid_x, y=mid_y, z=mid_z,
            block_name=self.config_manager.get_live_config().get("valve_block_name", "valve"),
            attribute_name=self.config_manager.get_live_config().get("valve_attribute_name", "Status"),
            attribute_value="OPEN",
            entity_handle="",
            distance_on_pipe=0.5
        )

        # ★ 先为阀门分配楼层（必须在 redraw 前面，否则首次不显示）
        if self.cad_data_manager.floors:
            for floor in self.cad_data_manager.floors:
                if pipe in floor.pipes:
                    new_valve.floor_name = floor.name
                    break

        self.cad_data_manager.valves.append(new_valve)
        self.cad_data_manager.valve_by_id[new_id] = new_valve
        self._record_change('add', new_valve)

        root = self.winfo_toplevel()
        if hasattr(root, 'pages') and "阀门" in root.pages:
            root.pages["阀门"].refresh_data()

        if self.real_time.get():
            self.compute_reachability()

        self.redraw()
        self.show_temp_message(f"已添加阀门 {new_id}", 2000)

    def set_valve_status(self, valve_id, new_status):
        valve = self.cad_data_manager.valve_by_id.get(valve_id)
        if valve:
            old_status = valve.status
            if old_status == new_status:
                return
            self._record_change('attr', valve, 'status', old_status, new_status)
            valve.status = new_status
            root = self.winfo_toplevel()
            if hasattr(root, 'pages') and "阀门" in root.pages:
                root.pages["阀门"].refresh_data()
            if self.real_time.get():
                self.compute_reachability()
                self.redraw()
            else:
                self.redraw()

    def delete_valve(self, valve_id):
        valve = self.cad_data_manager.valve_by_id.get(valve_id)
        if valve:
            self._record_change('delete', valve)
            self.cad_data_manager.valves.remove(valve)
            del self.cad_data_manager.valve_by_id[valve_id]
            self.selected_valve_id = None
            root = self.winfo_toplevel()
            if hasattr(root, 'pages') and "阀门" in root.pages:
                root.pages["阀门"].refresh_data()
            if self.real_time.get():
                self.compute_reachability()
            self.redraw()
            self.show_temp_message(f"已删除阀门 {valve_id}", 2000)

    # ----------------------------------------------------------------------
    # 视图切换、更新按钮、实时更新、路径高亮
    # ----------------------------------------------------------------------
    def on_view_changed(self):
        self.current_view = self.view_var.get()
        self.update_projection()
        self.redraw()

    def on_update_network(self):
        self.compute_reachability()
        self.redraw()

    def on_real_time_toggle(self):
        if self.real_time.get():
            self.update_btn.config(state="disabled")
            self.compute_reachability()
            self.redraw()
        else:
            self.update_btn.config(state="normal")

    def set_path_list(self, paths: List[Dict]):
        logger.info(f"预览页面 set_path_list 被调用，收到 {len(paths)} 条路径")
        self.path_list = paths
        display_items = []
        for p in paths:
            text = f"{p['id']}: [{p['start']}] → [{p['end_group']}] (水损: {p['loss']:.2f}m, 长度: {p['length']:.1f}m)"
            display_items.append(text)
        self.path_combo['values'] = display_items
        if display_items:
            self.path_combo.current(0)
            self.on_path_selected()

    def on_path_selected(self, event=None):
        idx = self.path_combo.current()
        if idx >= 0 and hasattr(self, 'path_list') and idx < len(self.path_list):
            path = self.path_list[idx]
            self.highlight_path_pipes = set(path.get('pipes', []))
            self.highlight_path_nodes = set(path.get('nodes', []))
        else:
            self.highlight_path_pipes.clear()
            self.highlight_path_nodes.clear()
        self.redraw()

    # ----------------------------------------------------------------------
    # 工具方法
    # ----------------------------------------------------------------------
    def show_temp_message(self, msg: str, duration=2000):
        root = self.winfo_toplevel()
        if hasattr(root, 'show_temp_message'):
            root.show_temp_message(msg, duration)

    def refresh_data(self, keep_view=False):
        if not self.cad_data_manager.is_loaded:
            return
        # 重新计算坐标和连通性
        if self.cad_data_manager.floors:
            config = self.config_manager.get_live_config()
            self.cad_data_manager.align_floors_to_baseline()
            if not self._skip_z_recalc:
                self.cad_data_manager.assign_node_z_coordinates(config)

            unit_factor = self.cad_data_manager.unit_factors.get(config.get("drawing_unit", "毫米"), 0.001)
            for pipe in self.cad_data_manager.pipes:
                s = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
                e = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
                if s and e:
                    pipe.start_point = (pipe.start_point[0], pipe.start_point[1], s.z)
                    pipe.end_point = (pipe.end_point[0], pipe.end_point[1], e.z)
                    dx = pipe.end_point[0] - pipe.start_point[0]
                    dy = pipe.end_point[1] - pipe.start_point[1]
                    dz = pipe.end_point[2] - pipe.start_point[2]
                    pipe.raw_length = math.hypot(dx, dy, dz)
                    pipe.length = pipe.raw_length * unit_factor

        self.update_projection()
        self.compute_reachability()
        # 更新楼层颜色映射（因为楼层标高可能已改变）
        self.update_floor_color_map()    
    
        # 检查分组映射是否变化，若变化则需要重建标签页
        current_grouped_map = getattr(self.cad_data_manager, 'grouped_floors_map', {})
        need_rebuild = (self.floor_notebook is None) or (not self.floor_notebook.tabs()) or (current_grouped_map != self._cached_grouped_floors_map)
        
        if self.floor_notebook is None:
            if hasattr(self, '_widgets_created'):
                delattr(self, '_widgets_created')
            self.create_widgets()
            self.update_projection()
            self.compute_reachability()
        
        if need_rebuild:
            self.rebuild_floor_tabs()
            self._cached_grouped_floors_map = current_grouped_map.copy()
        else:
            # 仅更新画布内容
            self.update_projection()
            
        self.update_projection()
    
        if self.current_floor_name is None and self.cad_data_manager.floors:
            self.current_floor_name = self.cad_data_manager.floors[0].name
    
        # 加载新数据时强制居中（仅该楼层从未访问过才居中）
        if not keep_view and self.current_view_mode != "global":
            if self.current_floor_name not in self.floor_view_state:
                self.auto_center()
                if self.current_floor_name:
                    self.floor_view_state[self.current_floor_name] = (self.scale, self.translate_x, self.translate_y)
        self.problem_pipes = self.cad_data_manager.validate_problem_pipes()
        # 更新计算结果相关控件状态
        if self.calculation_available:
            self.flow_check.config(state="normal")
            self.loss_check.config(state="normal")
            self.arrow_check.config(state="normal")
            self.velocity_check.config(state="normal")
            self.node_pressure_check.config(state="normal")
        else:
            self.flow_check.config(state="disabled")
            self.velocity_check.config(state="disabled")
            self.loss_check.config(state="disabled")
            self.arrow_check.config(state="disabled")
            self.node_pressure_check.config(state="disabled")

        # 同步重复立管信息（用于整体管网高亮）
        self.duplicate_risers_by_floor = self.cad_data_manager.duplicate_risers_by_floor
        self.update_invalid_controls_state()
        self.redraw()

    def _record_change(self, action, target, attr=None, old=None, new=None, obj_type=None):
        if action == 'attr':
            cmd = {'type': 'attr', 'obj': target, 'attr': attr, 'old': old, 'new': new}
        elif action == 'add':
            if obj_type is None:
                if isinstance(target, ValveData):
                    obj_type = 'valve'
                elif isinstance(target, HydrantData):
                    obj_type = 'hydrant'
                elif isinstance(target, PipeData):
                    obj_type = 'pipe'
                elif isinstance(target, NodeData):
                    obj_type = 'node'
                else:
                    obj_type = 'unknown'
            cmd = {'type': 'add', 'obj': target, 'obj_type': obj_type}
        elif action == 'delete':
            if obj_type is None:
                if isinstance(target, ValveData):
                    obj_type = 'valve'
                elif isinstance(target, HydrantData):
                    obj_type = 'hydrant'
                elif isinstance(target, PipeData):
                    obj_type = 'pipe'
                elif isinstance(target, NodeData):
                    obj_type = 'node'
                else:
                    obj_type = 'unknown'
            cmd = {'type': 'delete', 'obj': target, 'obj_type': obj_type}
        elif action == 'delete_batch':
            cmd = {'type': 'delete_batch', 'obj': target}
        else:
            return
        self.undo_stack.append(cmd)
        self.redo_stack.clear()
        if len(self.undo_stack) > self.max_undo:
            self.undo_stack.pop(0)

    def undo(self, event=None):
        if not self.undo_stack:
            return
        cmd = self.undo_stack.pop()
        if cmd['type'] == 'attr':
            obj = cmd['obj']
            setattr(obj, cmd['attr'], cmd['old'])
            self.redo_stack.append(cmd)
        elif cmd['type'] == 'add':
            obj = cmd['obj']
            obj_type = cmd['obj_type']
            if obj_type == 'valve':
                if obj in self.cad_data_manager.valves:
                    self.cad_data_manager.valves.remove(obj)
                if obj.valve_id in self.cad_data_manager.valve_by_id:
                    del self.cad_data_manager.valve_by_id[obj.valve_id]
            elif obj_type == 'hydrant':
                if obj in self.cad_data_manager.hydrants:
                    self.cad_data_manager.hydrants.remove(obj)
                if obj.hydrant_id in self.cad_data_manager.hydrant_by_id:
                    del self.cad_data_manager.hydrant_by_id[obj.hydrant_id]
                node = self.cad_data_manager.node_by_id.get(obj.node_id)
                if node and obj.hydrant_id in node.hydrants:
                    node.hydrants.remove(obj.hydrant_id)
                if obj.floor_name:
                    floor = self.cad_data_manager.floor_by_name.get(obj.floor_name)
                    if floor and obj in floor.hydrants:
                        floor.hydrants.remove(obj)
            elif obj_type == 'pipe':
                if obj in self.cad_data_manager.pipes:
                    self.cad_data_manager.pipes.remove(obj)
                if obj.pipe_id in self.cad_data_manager.pipe_by_id:
                    del self.cad_data_manager.pipe_by_id[obj.pipe_id]
                start_node = self.cad_data_manager.node_by_id.get(obj.start_node_id)
                end_node = self.cad_data_manager.node_by_id.get(obj.end_node_id)
                if start_node and obj.pipe_id in start_node.connected_pipes:
                    start_node.connected_pipes.remove(obj.pipe_id)
                if end_node and obj.pipe_id in end_node.connected_pipes:
                    end_node.connected_pipes.remove(obj.pipe_id)
                for floor in self.cad_data_manager.floors:
                    if obj in floor.pipes:
                        floor.pipes.remove(obj)
            self.redo_stack.append(cmd)
        elif cmd['type'] == 'delete':
            obj = cmd['obj']
            obj_type = cmd['obj_type']
            if obj_type == 'valve':
                if obj not in self.cad_data_manager.valves:
                    self.cad_data_manager.valves.append(obj)
                if obj.valve_id not in self.cad_data_manager.valve_by_id:
                    self.cad_data_manager.valve_by_id[obj.valve_id] = obj
            elif obj_type == 'hydrant':
                if obj not in self.cad_data_manager.hydrants:
                    self.cad_data_manager.hydrants.append(obj)
                if obj.hydrant_id not in self.cad_data_manager.hydrant_by_id:
                    self.cad_data_manager.hydrant_by_id[obj.hydrant_id] = obj
                node = self.cad_data_manager.node_by_id.get(obj.node_id)
                if node and obj.hydrant_id not in node.hydrants:
                    node.hydrants.append(obj.hydrant_id)
                if obj.floor_name:
                    floor = self.cad_data_manager.floor_by_name.get(obj.floor_name)
                    if floor and obj not in floor.hydrants:
                        floor.hydrants.append(obj)
            elif obj_type == 'pipe':
                # 完整恢复被删除的管道及其拓扑连接
                if obj not in self.cad_data_manager.pipes:
                    self.cad_data_manager.pipes.append(obj)
                if obj.pipe_id not in self.cad_data_manager.pipe_by_id:
                    self.cad_data_manager.pipe_by_id[obj.pipe_id] = obj
                start_node = self.cad_data_manager.node_by_id.get(obj.start_node_id)
                end_node = self.cad_data_manager.node_by_id.get(obj.end_node_id)
                if start_node and obj.pipe_id not in start_node.connected_pipes:
                    start_node.connected_pipes.append(obj.pipe_id)
                if end_node and obj.pipe_id not in end_node.connected_pipes:
                    end_node.connected_pipes.append(obj.pipe_id)
                # 恢复楼层归属（只要端点节点在楼层中，管道就属于该楼层）
                for floor in self.cad_data_manager.floors:
                    if obj not in floor.pipes:
                        if (start_node and start_node in floor.nodes) or (end_node and end_node in floor.nodes):
                            floor.pipes.append(obj)
            elif obj_type == 'node':
                if obj not in self.cad_data_manager.nodes:
                    self.cad_data_manager.nodes.append(obj)
                if obj.node_id not in self.cad_data_manager.node_by_id:
                    self.cad_data_manager.node_by_id[obj.node_id] = obj
                for floor in self.cad_data_manager.floors:
                    if obj not in floor.nodes:
                        floor.nodes.append(obj)
            self.redo_stack.append(cmd)
        elif cmd['type'] == 'delete_batch':
            pipes_list = cmd['obj']
            for pipe in pipes_list:
                if pipe not in self.cad_data_manager.pipes:
                    self.cad_data_manager.pipes.append(pipe)
                if pipe.pipe_id not in self.cad_data_manager.pipe_by_id:
                    self.cad_data_manager.pipe_by_id[pipe.pipe_id] = pipe
                start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
                end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
                if start_node and pipe.pipe_id not in start_node.connected_pipes:
                    start_node.connected_pipes.append(pipe.pipe_id)
                if end_node and pipe.pipe_id not in end_node.connected_pipes:
                    end_node.connected_pipes.append(pipe.pipe_id)
                for floor in self.cad_data_manager.floors:
                    if pipe not in floor.pipes:
                        if (start_node and start_node in floor.nodes) or (end_node and end_node in floor.nodes):
                            floor.pipes.append(pipe)
            self.redo_stack.append(cmd)
        elif cmd['type'] == 'delete_invalid_batch':
            # 撤销批量删除无效管：按逆序恢复消火栓 → 节点 → 立管 → 管道
            pipes = cmd['pipes']
            nodes = cmd['nodes']
            hydrants = cmd['hydrants']
            risers = cmd['risers']

            for hydrant in hydrants:
                if hydrant not in self.cad_data_manager.hydrants:
                    self.cad_data_manager.hydrants.append(hydrant)
                if hydrant.hydrant_id not in self.cad_data_manager.hydrant_by_id:
                    self.cad_data_manager.hydrant_by_id[hydrant.hydrant_id] = hydrant
                node = self.cad_data_manager.node_by_id.get(hydrant.node_id)
                if node and hydrant.hydrant_id not in node.hydrants:
                    node.hydrants.append(hydrant.hydrant_id)
                if hydrant.floor_name:
                    floor = self.cad_data_manager.floor_by_name.get(hydrant.floor_name)
                    if floor and hydrant not in floor.hydrants:
                        floor.hydrants.append(hydrant)

            for node in nodes:
                if node not in self.cad_data_manager.nodes:
                    self.cad_data_manager.nodes.append(node)
                if node.node_id not in self.cad_data_manager.node_by_id:
                    self.cad_data_manager.node_by_id[node.node_id] = node
                for floor in self.cad_data_manager.floors:
                    if node not in floor.nodes:
                        floor.nodes.append(node)

            for riser in risers:
                if riser not in self.cad_data_manager.risers:
                    self.cad_data_manager.risers.append(riser)
                if riser.riser_id not in self.cad_data_manager.riser_by_id:
                    self.cad_data_manager.riser_by_id[riser.riser_id] = riser
                for floor in self.cad_data_manager.floors:
                    if hasattr(floor, 'risers') and riser not in floor.risers:
                        floor.risers.append(riser)

            for pipe in pipes:
                if pipe not in self.cad_data_manager.pipes:
                    self.cad_data_manager.pipes.append(pipe)
                if pipe.pipe_id not in self.cad_data_manager.pipe_by_id:
                    self.cad_data_manager.pipe_by_id[pipe.pipe_id] = pipe
                start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
                end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
                if start_node and pipe.pipe_id not in start_node.connected_pipes:
                    start_node.connected_pipes.append(pipe.pipe_id)
                if end_node and pipe.pipe_id not in end_node.connected_pipes:
                    end_node.connected_pipes.append(pipe.pipe_id)
                for floor in self.cad_data_manager.floors:
                    if pipe not in floor.pipes:
                        if (start_node and start_node in floor.nodes) or (end_node and end_node in floor.nodes):
                            floor.pipes.append(pipe)

            self.cad_data_manager.check_duplicate_risers_in_floor()
            self.duplicate_risers_by_floor = self.cad_data_manager.duplicate_risers_by_floor

            self.redo_stack.append(cmd)
        elif cmd['type'] == 'batch_attr':
            changes = cmd['changes']
            for item in changes:
                pipe = item['pipe']
                pipe.nominal_diameter = item['old_dn']
                pipe.inner_diameter = item['old_inner']
            self.redo_stack.append(cmd)
        else:
            return
    
        # 撤销操作后，拓扑结构可能变化，遮挡缓存必须失效
        self.occlusion_cache_valid = False
        
        # 刷新视图和其他页面
        self.redraw()
        root = self.winfo_toplevel()
        if hasattr(root, 'main_app'):
            for name, page in root.main_app.pages.items():
                if name != "管网预览" and hasattr(page, 'refresh_data'):
                    try:
                        page.refresh_data()
                    except Exception as e:
                        logger.error(f"刷新页面 {name} 失败: {e}")

    def _on_canvas_configure(self, event):
        """画布大小改变时重绘左下角文字"""
        self._draw_floor_info_text()
        self.draw_color_legend()

    def _draw_floor_info_text(self):
        """在画布左下角固定像素位置绘制楼层信息"""
        if not self.canvas or not self.canvas.winfo_exists():
            return
        self.canvas.delete("floor_info")
        if not self.cad_data_manager.floors or not self.current_floor_name or self.current_floor_name == "单层":
            return
        floor = self.cad_data_manager.floor_by_name.get(self.current_floor_name)
        if not floor:
            return
        info_text = f"楼面标高: {floor.elevation:.2f}m  管网标高: {floor.pipe_z_offset:.2f}m"
        
        # 强制更新画布布局，确保获取的宽高是最新的
        self.canvas.update_idletasks()
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w > 10 and h > 10:
            self.canvas.create_text(20, h - 20, text=info_text, fill="white",
                                    anchor="sw", font=("Arial", 10), tags="floor_info")      

    def set_pipe_active(self, pipe_id, active):
        pipe = self.cad_data_manager.pipe_by_id.get(pipe_id)
        if not pipe:
            return
        if pipe.is_active == active:
            return
        self._record_change('attr', pipe, 'is_active', pipe.is_active, active)
        pipe.is_active = active
        
        # 处理自由节点：对于管道两端的节点，如果节点只连接了此管道，则同步其有效性
        start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
        end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
        for node in (start_node, end_node):
            if node and len(node.connected_pipes) == 1:
                node.is_active = active
        self.redraw()
        self._refresh_other_pages()
    
    def set_selected_pipes_active(self, active):
        for pid in self.selected_pipes:
            self.set_pipe_active(pid, active)
        self.redraw()
    
    def delete_pipe(self, pipe_id, record=True):
        pipe = self.cad_data_manager.pipe_by_id.get(pipe_id)
        if not pipe:
            return
        if record:
            self._record_change('delete', pipe, obj_type='pipe')
        
        # 从节点连接列表中移除
        start_node = self.cad_data_manager.node_by_id.get(pipe.start_node_id)
        end_node = self.cad_data_manager.node_by_id.get(pipe.end_node_id)
        if start_node and pipe_id in start_node.connected_pipes:
            start_node.connected_pipes.remove(pipe_id)
        if end_node and pipe_id in end_node.connected_pipes:
            end_node.connected_pipes.remove(pipe_id)
        
        # 从楼层管道列表中移除
        for floor in self.cad_data_manager.floors:
            if pipe in floor.pipes:
                floor.pipes.remove(pipe)
        
        self.cad_data_manager.pipes.remove(pipe)
        del self.cad_data_manager.pipe_by_id[pipe_id]
        
        # 如果是立管管道，同步删除对应的立管对象
        if pipe_id.startswith('R_'):
            riser = self.cad_data_manager.riser_by_id.get(pipe_id)
            if riser:
                # 从楼层立管列表中移除（如果有 floor.risers 属性）
                for floor in self.cad_data_manager.floors:
                    if hasattr(floor, 'risers') and riser in floor.risers:
                        floor.risers.remove(riser)
                # 从全局立管列表中移除
                if riser in self.cad_data_manager.risers:
                    self.cad_data_manager.risers.remove(riser)
                # 从索引字典中删除
                del self.cad_data_manager.riser_by_id[pipe_id]
            # 重新计算重复立管信息
            self.cad_data_manager.check_duplicate_risers_in_floor()
            self.duplicate_risers_by_floor = self.cad_data_manager.duplicate_risers_by_floor
            
        self.occlusion_cache_valid = False
        self.redraw()
        self._refresh_other_pages()

    def delete_selected_pipes(self):
        if not self.selected_pipes:
            return
        # 收集要删除的管道对象
        to_delete_pipes = []
        for pid in list(self.selected_pipes):
            pipe = self.cad_data_manager.pipe_by_id.get(pid)
            if pipe:
                to_delete_pipes.append(pipe)
        if not to_delete_pipes:
            return
        # 记录批量删除命令
        self._record_change('delete_batch', to_delete_pipes)
        # 执行删除（不单独记录）
        for pipe in to_delete_pipes:
            self.delete_pipe(pipe.pipe_id, record=False)
        self.selected_pipes.clear()
        self.occlusion_cache_valid = False
        self.redraw()
    
    def _delete_node(self, node_id):
        node = self.cad_data_manager.node_by_id.get(node_id)
        if not node:
            return
        # 删除节点上的消火栓
        for hid in node.hydrants[:]:
            hydrant = self.cad_data_manager.hydrant_by_id.get(hid)
            if hydrant:
                self.cad_data_manager.hydrants.remove(hydrant)
                del self.cad_data_manager.hydrant_by_id[hid]
        # 从楼层节点列表中移除
        for floor in self.cad_data_manager.floors:
            if node in floor.nodes:
                floor.nodes.remove(node)
        # 从全局列表中移除
        self.cad_data_manager.nodes.remove(node)
        del self.cad_data_manager.node_by_id[node_id]

    def reset_state(self):
        """重置预览页面状态（清除计算结果、高亮、选择集等）"""
        self.pipe_results = {}
        self.calculation_available = False
        self.show_flow.set(False)
        self.show_velocity.set(False)
        self.show_loss.set(False)
        self.show_arrow.set(False)
        self.show_node_pressure.set(False)
        self.flow_check.config(state="disabled")
        self.velocity_check.config(state="disabled")
        self.loss_check.config(state="disabled")
        self.arrow_check.config(state="disabled")
        self.node_pressure_check.config(state="disabled")
        self.velocity_check_var.set(False)
        self.velocity_check_cb.config(state="disabled")
        self._update_hydrant_flat_state()
        self.highlight_path_pipes = set()
        self.highlight_path_nodes = set()
        self.selected_pipes.clear()
        self.selected_valve_id = None
        self.path_list = []
        self.path_combo['values'] = []
        self.separation_values.clear()
        self._separation_applied = False
        self._sep_cache_key = None
        self.maintenance_zones.clear()
        self._next_zone_id = 0
        self._cached_grouped_floors_map = None
        self.floor_view_state.clear()
        self.current_floor_name = None
        self.node_pressures = {}
        self.node_flows = {}
        self._destroy_hover_tooltip()
        self.alt_pressed = False
        self.redraw()

    def get_state_for_export(self) -> dict:
        """返回预览页面完整状态，供导出使用。"""
        return {
            "layer_colors_enabled": self.layer_colors_enabled.get(),
            "color_list": self.layer_color_list,
            "floor_color_map": self.floor_color_map,
            "pipe_floor_map": self.pipe_floor_map,
            "separation_values": self.separation_values,
            "_separation_applied": self._separation_applied,
            "show_nominal": self.show_nominal.get(),
            "show_length": self.show_length.get(),
            "show_flow": self.show_flow.get(),
            "show_loss": self.show_loss.get(),
            "show_arrow": self.show_arrow.get(),
            "show_node_ids": self.show_node_ids.get(),
            "show_pipe_id": self.show_pipe_id.get(),
            "show_elevation": self.show_elevation.get(),
            "show_node_pressure": self.show_node_pressure.get(),
            "show_occlusion_var": self.show_occlusion_var.get(),
            "show_riser_warning": self.show_riser_warning.get(),
            "show_zero_flow_label_var": self.show_zero_flow_label_var.get(),
            "hide_invalid_var": self.hide_invalid_var.get(),
            "real_time": self.real_time.get(),
            "current_view_mode": self.current_view_mode,
            "global_view_angle": self.global_view_angle,
            "global_view_elevation": self.global_view_elevation,
            "global_view_elevation_var": self.global_view_elevation_var.get(),
            "current_floor_name": self.current_floor_name,
            "floor_view_state": {
                k: list(v) if isinstance(v, tuple) else v
                for k, v in self.floor_view_state.items()
            },
            "selected_pipes": list(self.selected_pipes),
            "selected_valve_id": self.selected_valve_id,
            "problem_pipes": list(self.problem_pipes),
            "reachable_pipes": list(self.reachable_pipes),
            "undo_count": len(self.undo_stack),
            "redo_count": len(self.redo_stack),
            "maintenance_zones": [
                {
                    "zone_id": z.zone_id,
                    "pipe_ids": list(z.pipe_ids),
                    "valve_ids": list(z.valve_ids),
                    "node_ids": list(z.node_ids),
                }
                for z in self.maintenance_zones
            ],
            "_next_zone_id": self._next_zone_id,
        }

    def restore_imported_state(self, data: dict):
        """从导入数据恢复预览页面完整状态。"""
        if data is None:
            return

        # 分层颜色
        if "color_list" in data:
            self.layer_color_list = data["color_list"]
        if "floor_color_map" in data:
            self.floor_color_map = data["floor_color_map"]
        if "pipe_floor_map" in data:
            self.pipe_floor_map = data["pipe_floor_map"]
        if "layer_colors_enabled" in data:
            self.layer_colors_enabled.set(data["layer_colors_enabled"])

        # 分离值
        if "separation_values" in data:
            self.separation_values = data["separation_values"]
        self._separation_applied = data.get("_separation_applied", False)
        self._sep_cache_key = None

        # BooleanVar 恢复
        bool_vars = {
            "show_nominal": self.show_nominal,
            "show_length": self.show_length,
            "show_flow": self.show_flow,
            "show_loss": self.show_loss,
            "show_arrow": self.show_arrow,
            "show_node_ids": self.show_node_ids,
            "show_pipe_id": self.show_pipe_id,
            "show_elevation": self.show_elevation,
            "show_node_pressure": self.show_node_pressure,
            "show_occlusion_var": self.show_occlusion_var,
            "show_riser_warning": self.show_riser_warning,
            "show_zero_flow_label_var": self.show_zero_flow_label_var,
            "hide_invalid_var": self.hide_invalid_var,
            "real_time": self.real_time,
        }
        for key, var in bool_vars.items():
            if key in data:
                var.set(data[key])

        # 视角
        if "current_view_mode" in data:
            self.current_view_mode = data["current_view_mode"]
        if "global_view_angle" in data:
            self.global_view_angle = data["global_view_angle"]
        if "global_view_elevation" in data:
            self.global_view_elevation = data["global_view_elevation"]
        if "global_view_elevation_var" in data:
            self.global_view_elevation_var.set(data["global_view_elevation_var"])
        if "current_floor_name" in data:
            self.current_floor_name = data["current_floor_name"]
        if "floor_view_state" in data:
            self.floor_view_state = {
                k: tuple(v) if isinstance(v, list) else v
                for k, v in data["floor_view_state"].items()
            }

        # 选择集
        self.selected_pipes = set(data.get("selected_pipes", []))
        self.selected_valve_id = data.get("selected_valve_id")
        self.problem_pipes = set(data.get("problem_pipes", []))
        self.reachable_pipes = set(data.get("reachable_pipes", []))

        # 撤销栈清空（不可序列化）
        self.undo_stack.clear()
        self.redo_stack.clear()

        # 检修区恢复
        if "maintenance_zones" in data:
            self.maintenance_zones = [
                MaintenanceZone(
                    zone_id=z["zone_id"],
                    pipe_ids=set(z["pipe_ids"]),
                    valve_ids=set(z["valve_ids"]),
                    node_ids=set(z["node_ids"]),
                )
                for z in data["maintenance_zones"]
            ]
        if "_next_zone_id" in data:
            self._next_zone_id = data["_next_zone_id"]

        # 重新绘制
        self.redraw()


def _bfs_tree_and_detect_loops(adjacency, start_node, edge_to_pipe):
    """BFS 遍历，返回树边列表 (parent, child)；检测到环路时抛出 ValueError(pipe_ids)"""
    visited = {start_node: None}
    queue = deque([start_node])
    tree_edges = []
    while queue:
        u = queue.popleft()
        for v in adjacency.get(u, []):
            if v not in visited:
                visited[v] = u
                queue.append(v)
                tree_edges.append((u, v))
            elif v != visited.get(u):
                cycle_pipes = _find_cycle_pipe_ids(visited, u, v, edge_to_pipe)
                raise ValueError(cycle_pipes)
    return tree_edges


def _find_cycle_pipe_ids(visited, u, v, edge_to_pipe):
    """从 BFS parent 表与检测到的跨边 (u,v) 重建环路管道 ID 列表"""
    u_ancestors = {u: 0}
    curr = visited.get(u)
    depth = 1
    while curr is not None:
        u_ancestors[curr] = depth
        curr = visited.get(curr)
        depth += 1
    curr = v
    lca = None
    while curr is not None:
        if curr in u_ancestors:
            lca = curr
            break
        curr = visited.get(curr)
    if lca is None:
        return []
    u_path = [u]
    curr = visited.get(u)
    while curr is not None and curr != lca:
        u_path.append(curr)
        curr = visited.get(curr)
    u_path.append(lca)
    v_path = [v]
    curr = visited.get(v)
    while curr is not None and curr != lca:
        v_path.append(curr)
        curr = visited.get(curr)
    v_path.append(lca)
    cycle_nodes = u_path + list(reversed(v_path[:-1]))
    cycle_nodes.append(u)
    pipe_ids = []
    for i in range(len(cycle_nodes) - 1):
        a, b = cycle_nodes[i], cycle_nodes[i + 1]
        pipe = edge_to_pipe.get(tuple(sorted((a, b))))
        if pipe:
            pipe_ids.append(pipe.pipe_id)
    return pipe_ids


class SprinklerCapacityDialog(tk.Toplevel):
    """喷淋管径表编辑对话框"""

    def __init__(self, parent, file_path, default_path):
        super().__init__(parent)
        self.parent = parent
        self.file_path = file_path
        self.default_path = default_path

        self.title("喷淋管径表")
        self.transient(parent)
        self.resizable(False, False)

        self.data = self._load_data()
        self._build_ui()
        self._center_on_parent()

        self.grab_set()
        self.focus_set()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", lambda e: self._on_cancel())
        self.wait_window()

    def _load_data(self):
        with open(self.file_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        k_vals = sorted(raw.keys(), key=int)
        dns = sorted(raw[k_vals[0]].keys(),
                     key=lambda x: int(x[2:]) if x.startswith('DN') else 0)
        return {k: {d: raw[k][d] for d in dns} for k in k_vals}

    def _build_ui(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill="both", expand=True)

        table_frame = ttk.Frame(main_frame)
        table_frame.pack()

        cw = 7
        k_vals = list(self.data.keys())
        dns = list(self.data[k_vals[0]].keys())

        # A1: "K="
        ttk.Label(table_frame, text="K=", width=cw, anchor="center",
                  relief="solid", borderwidth=1).grid(row=0, column=0, sticky="nsew")

        # B1-J1: K值 只读
        for j, k in enumerate(k_vals):
            ttk.Label(table_frame, text=k, width=cw, anchor="center",
                      relief="solid", borderwidth=1).grid(row=0, column=j+1, sticky="nsew")

        self.entry_vars = {}
        self.entries = {}

        for i, dn in enumerate(dns):
            # A2-A12: 管径 只读
            ttk.Label(table_frame, text=dn, width=cw, anchor="center",
                      relief="solid", borderwidth=1).grid(row=i+1, column=0, sticky="nsew")

            for j, k in enumerate(k_vals):
                var = tk.StringVar(value=str(self.data[k][dn]))
                entry = ttk.Entry(table_frame, textvariable=var, width=cw, justify="center")
                entry.grid(row=i+1, column=j+1, sticky="nsew")

                entry._valid_value = str(self.data[k][dn])
                entry._k = k
                entry._dn = dn
                entry.bind("<FocusOut>", self._on_cell_focusout, add="+")

                self.entry_vars[(dn, k)] = var
                self.entries[(dn, k)] = entry

        # 按钮行
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill="x", pady=(10, 0))

        ttk.Button(btn_frame, text="恢复默认", command=self._on_restore_default).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="保存", command=self._on_save).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="取消", command=self._on_cancel).pack(side="left", padx=5)

    def _on_cell_focusout(self, event):
        entry = event.widget
        val = entry.get().strip()
        k = entry._k
        dn = entry._dn

        if val == "":
            entry.delete(0, tk.END)
            entry.insert(0, entry._valid_value)
            return

        try:
            num_str = val.lstrip('-')
            if not num_str.isdigit():
                raise ValueError
            num = int(val)
            if num < 0:
                raise ValueError
        except ValueError:
            entry.delete(0, tk.END)
            entry.insert(0, entry._valid_value)
            return

        self.data[k][dn] = num
        entry._valid_value = str(num)

    def _on_restore_default(self):
        if not messagebox.askyesno("确认",
                "确定要从默认文件恢复喷淋管径表吗？\n当前修改将被丢弃。"):
            return
        try:
            shutil.copy2(self.default_path, self.file_path)
        except Exception as e:
            messagebox.showerror("错误", f"恢复默认失败：{e}")
            return
        self.data = self._load_data()
        for (dn, k), entry in self.entries.items():
            val = str(self.data[k][dn])
            entry._valid_value = val
            self.entry_vars[(dn, k)].set(val)

    def _on_save(self):
        # 校验并同步所有单元格到 data
        for (dn, k), entry in self.entries.items():
            val = entry.get().strip()
            try:
                if val == "" or not val.lstrip('-').isdigit():
                    raise ValueError
                num = int(val)
                if num < 0:
                    raise ValueError
            except ValueError:
                entry.delete(0, tk.END)
                entry.insert(0, entry._valid_value)
                entry.focus_set()
                messagebox.showerror("输入错误",
                    f"K={k}, {dn} 的数值无效，请输入非负整数。")
                return
            self.data[k][dn] = int(val)
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("错误", f"保存失败：{e}")
            return
        self.destroy()

    def _on_cancel(self):
        self.destroy()

    def _center_on_parent(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        pw = self.parent.winfo_width()
        ph = self.parent.winfo_height()
        px = self.parent.winfo_rootx()
        py = self.parent.winfo_rooty()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self.geometry(f"+{x}+{y}")

