"""
CAD数据管理器模块
负责读取和处理CAD文件中的管网数据
"""
import os
import tempfile
import uuid
import json
import math
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import tkinter as tk
from tkinter import messagebox
import logging
from cad_preprocessor import preprocess_cad_data, SimpleLine, merge_pipes_at_valves, preprocess_from_segments, merge_pipes_at_valves_from_points
import pythoncom  # 新增：用于COM初始化


# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 动态导入pyautocad，避免启动失败
CAD_AVAILABLE = False
APoint = None
Autocad = None

try:
    from pyautocad import Autocad, APoint
    CAD_AVAILABLE = True
    logger.info("pyautocad加载成功")
except ImportError:
    logger.warning("pyautocad未安装，CAD相关功能不可用")
except Exception as e:
    logger.error(f"加载pyautocad时出错: {e}")



@dataclass
class PipeData:
    """管道数据类"""
    pipe_id: str = ""
    start_node_id: str = ""
    end_node_id: str = ""
    color_code: int = 0
    nominal_diameter: str = ""
    inner_diameter: float = 0.0
    length: float = 0.0
    raw_length: float = 0.0
    status: str = "开"
    material: str = ""
    roughness: float = 0.0
    start_point: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    end_point: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    layer: str = ""
    entity_handle: str = ""
    direction_angle: float = 0.0  # 管道方向角度
    pipe_type: str = "未知"   # NEW: "干管" / "支管" / "未知"
    riser_number: str = ""   # 立管编号（仅对竖向管道有效）
    is_active: bool = True   # 新增：管道有效性，默认为有效

    def __post_init__(self):
        # 计算管道方向角度
        if len(self.start_point) >= 2 and len(self.end_point) >= 2:
            dx = self.end_point[0] - self.start_point[0]
            dy = self.end_point[1] - self.start_point[1]
            self.direction_angle = math.degrees(
                math.atan2(dy, dx)) if dx != 0 or dy != 0 else 0


@dataclass
class NodeData:
    """节点数据类"""
    node_id: str = ""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    status: str = "开"
    node_type: str = "普通"
    connected_pipes: List[str] = field(default_factory=list)
    pressure: float = 0.0
    flow: float = 0.0
    cad_key: str = ""  # 用于节点去重的键
    hydrants: List[str] = field(default_factory=list)  # 该节点上的消火栓ID列表
    is_active: bool = True   # 新增：节点有效性，默认为有效

    def __eq__(self, other):
        if not isinstance(other, NodeData):
            return False
        return self.cad_key == other.cad_key

    def __hash__(self):
        return hash(self.cad_key)


@dataclass
class SupplyNodeData:
    """供水点数据类"""
    group_id: str = ""
    node_ids: List[str] = field(default_factory=list)
    pressure: float = 0.0
    total_flow: float = 0.0
    block_name: str = "supply_node"
    attribute_name: str = "GroupID"
    attribute_value: str = ""
    cad_handle: str = ""


@dataclass
class DemandNodeData:
    """用水点数据类"""
    node_id: str = ""
    status: str = "关"
    flow: float = 0.0
    pressure: float = 0.0
    block_name: str = "demand_node"
    attribute_name: str = "GroupID"
    attribute_value: str = ""
    cad_handle: str = ""


@dataclass
class DemandGroupData:
    """用水点组数据类"""
    group_id: str = ""
    group_name: str = ""
    is_selected: bool = False
    total_flow: float = 0.0
    min_pressure: float = 0.0
    demand_nodes: List[DemandNodeData] = field(default_factory=list)


@dataclass
class ValveData:
    """阀门数据类"""
    valve_id: str = ""
    pipe_id: str = ""
    status: str = "OPEN"
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    block_name: str = "valve"
    attribute_name: str = "Status"
    attribute_value: str = ""
    entity_handle: str = ""
    distance_on_pipe: float = 0.0
    floor_name: str = ""   # 所属楼层名
    
@dataclass
class HydrantData:
    """消火栓数据类"""
    hydrant_id: str = ""
    node_id: str = ""          # 关联的节点ID
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    block_name: str = "hydrant"   # 图块名，从配置读取
    entity_handle: str = ""       # CAD图块句柄
    floor_name: str = ""   # 所属楼层名
        
@dataclass
class RiserData:
    """立管数据类"""
    riser_id: str = ""
    x: float = 0.0          # 圆心的X坐标（毫米）
    y: float = 0.0          # 圆心的Y坐标（毫米）
    z: float = 0.0          # 圆心的Z坐标（毫米）
    radius: float = 0.0     # 半径（毫米）
    layer: str = ""         # 立管图层
    entity_handle: str = "" # CAD实体句柄
    note: str = ""          # 引出标注文字（如 "PL-1 DN100"）
    note_number: str = ""
    note_diameter: str = ""
    nominal_diameter: str = ""  # 从标注中解析的管径（如 "DN100"）
    note_x: float = 0.0     # 标注文字的位置X
    note_y: float = 0.0     # 标注文字的位置Y
    note_z: float = 0.0
    connected_node_id: str = ""  # 关联的节点ID（匹配后赋值）
    floor_name: str = ""   # 所属楼层名
    top_node_id: str = ""      # 新增：立管上端节点ID（与本层横管相连，若无则为新建节点ID）
    bottom_node_id: str = ""   # 新增：立管下端节点ID（本层楼面标高处）
        
@dataclass
class FloorData:
    """楼层数据类"""
    name: str                     # 楼层名（对齐点属性中的楼层部分）
    elevation: float              # 楼面标高（米）
    align_point: Tuple[float, float, float]   # 对齐点插入点坐标（毫米）
    rect_min: Tuple[float, float]             # 矩形框最小角点 (x_min, y_min) 毫米
    rect_max: Tuple[float, float]             # 矩形框最大角点 (x_max, y_max) 毫米
    layer: str                    # 对齐点所在图层
    pipes: List['PipeData'] = field(default_factory=list)   # 本层管道
    nodes: List['NodeData'] = field(default_factory=list)   # 本层节点
    pipe_z_offset: float = 0.0    # 本层管网标高（米），计算后赋值
    hydrants: List['HydrantData'] = field(default_factory=list)  # 本层消火栓数据列表


# ========== 多楼层合一辅助函数 ==========
def chinese_to_int(ch_str: str) -> int:
    """中文数字转整数（支持一~九千九百九十九）"""
    if not ch_str:
        raise ValueError("空字符串")
    if ch_str.isdigit():
        return int(ch_str)
    digit_map = {'零':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
    unit_map = {'十':10,'百':100,'千':1000,'万':10000}
    if ch_str.startswith('十'):
        ch_str = '一' + ch_str
    def parse(s):
        if '万' in s:
            parts = s.split('万')
            left = parts[0]
            right = parts[1] if len(parts)>1 else ''
            left_val = parse(left) if left else 1
            right_val = parse(right) if right else 0
            return left_val*10000 + right_val
        if '千' in s:
            parts = s.split('千')
            left = parts[0]
            right = parts[1] if len(parts)>1 else ''
            left_val = parse(left) if left else 1
            right_val = parse(right) if right else 0
            return left_val*1000 + right_val
        if '百' in s:
            parts = s.split('百')
            left = parts[0]
            right = parts[1] if len(parts)>1 else ''
            left_val = parse(left) if left else 1
            right_val = parse(right) if right else 0
            return left_val*100 + right_val
        if '十' in s:
            parts = s.split('十')
            left = parts[0]
            right = parts[1] if len(parts)>1 else ''
            left_val = parse(left) if left else 1
            right_val = parse(right) if right else 0
            return left_val*10 + right_val
        if s in digit_map:
            return digit_map[s]
        if s == '零':
            return 0
        raise ValueError(f"无法解析: {s}")
    try:
        return parse(ch_str)
    except:
        return int(ch_str) if ch_str.isdigit() else 0

def int_to_chinese(n: int) -> str:
    """整数1~99转中文数字"""
    if n<1 or n>99:
        return str(n)
    digits = ["","一","二","三","四","五","六","七","八","九"]
    if n<=10:
        return "十" if n==10 else digits[n]
    if n<20:
        return "十"+digits[n-10]
    tens = n//10
    units = n%10
    if units==0:
        return digits[tens]+"十"
    else:
        return digits[tens]+"十"+digits[units]

def parse_floor_range(range_str: str) -> List[int]:
    """解析 "一至四层" 或 "10至12层" 返回楼层数字列表"""
    import re
    match = re.search(r'(.+?)至(.+?)层', range_str)
    if not match:
        raise ValueError(f"无法解析楼层范围: {range_str}")
    start_str = match.group(1).strip()
    end_str = match.group(2).strip()
    try:
        start = chinese_to_int(start_str)
        end = chinese_to_int(end_str)
    except:
        start = int(start_str) if start_str.isdigit() else 0
        end = int(end_str) if end_str.isdigit() else 0
    if start>end:
        raise ValueError("起始楼层大于结束楼层")
    return list(range(start, end+1))


class CADDataManager:
    """CAD数据管理器"""

    def __init__(self, config_manager, material_manager, cache_file="cad_cache.json"):
        """
        初始化CAD数据管理器

        Args:
            config_manager: 配置管理器实例
            material_manager: 管材管理器实例
            cache_file: 缓存文件路径
        """
        self.config_manager = config_manager
        self.material_manager = material_manager
        self.cache_file = cache_file

        # CAD连接
        self.acad = None
        self.cad_file_path = None

        # 数据存储
        self.pipes: List[PipeData] = []
        self.nodes: List[NodeData] = []
        self.supply_nodes: List[SupplyNodeData] = []
        self.demand_groups: Dict[str, DemandGroupData] = {}
        self.valves: List[ValveData] = []
        
        # 消火栓数据
        self.hydrants: List[HydrantData] = []
        self.hydrant_by_id: Dict[str, HydrantData] = {}

        # 喷头短立管_S节点ID
        self.sprinkler_s_node_ids: List[str] = []

        # K值/DN手动修改追踪
        self.sprinkler_k_map: Dict[str, float] = {}
        self.sprinkler_k_overrides: Set[str] = set()
        self.manual_dn_pipes: Set[str] = set()

        # 立管数据
        self.risers: List[RiserData] = []
        self.riser_by_id: Dict[str, RiserData] = {}
        self.duplicate_risers_by_floor = {}  # 存储每层重复立管编号的立管列表，格式: {楼层名: [RiserData, ...]}
        self.duplicate_pipe_ids_by_floor = {}  # {楼层名: Set[管道ID]} 存储重复立管编号的管道ID集合

        # 楼层数据
        self.floors: List[FloorData] = []
        self.floor_by_name: Dict[str, FloorData] = {}
        self.grouped_floors_map: Dict[str, List[str]] = {}
        
        # 索引
        self.pipe_by_id: Dict[str, PipeData] = {}
        self.node_by_id: Dict[str, NodeData] = {}
        self.valve_by_id: Dict[str, ValveData] = {}

        # 状态
        self.is_loaded = False
        self.current_project_dir = None   # 当前项目目录，用于保存楼层配置
        self.default_color256_diameter = None  # 存储用户指定的随层管道管径
        self.progress_callback = None  # 用于接收进度消息的回调函数
        
        # 单位转换因子 (CAD单位到米)
        self.unit_factors = {
            "毫米": 0.001,
            "厘米": 0.01,
            "米": 1.0
        }
        
        # 加载缓存
        self.load_cache()

    def connect_to_cad(self):
        """连接到AutoCAD（修正COM初始化问题）"""
        if not CAD_AVAILABLE:
            messagebox.showerror("CAD错误", "pyautocad未安装，无法连接AutoCAD")
            return False

        try:
            # 初始化COM环境
            pythoncom.CoInitialize()

            # 创建AutoCAD连接
            self.acad = Autocad(create_if_not_exists=True)

            if self.acad:
                logger.info("成功连接到AutoCAD")
                return True
            else:
                logger.error("连接AutoCAD失败")
                return False
        except Exception as e:
            logger.error(f"连接AutoCAD失败: {e}")
            messagebox.showerror("CAD连接错误", f"无法连接到AutoCAD: {str(e)}")
            return False

    def check_current_document(self, file_path: str) -> bool:
        """检查当前CAD活动文档是否为指定文件"""
        try:
            if not self.acad:
                return False
            # 获取当前活动文档的完整路径
            current_doc = self.acad.doc
            current_path = current_doc.FullName
            # 统一路径格式（小写，正斜杠）进行比对
            import os
            current_norm = os.path.normcase(os.path.normpath(current_path))
            target_norm = os.path.normcase(os.path.normpath(file_path))
            if current_norm == target_norm:
                logger.info(f"CAD当前文档匹配: {current_path}")
                return True
            else:
                logger.error(f"CAD当前文档: {current_path}，所选文件: {file_path}")
                return False
        except Exception as e:
            logger.error(f"检查CAD文档失败: {e}")
            return False

    def load_cad_file(self, file_path: str, force_reload=False, progress_callback=None) -> bool:
        """
        加载CAD文件
        progress_callback: 可选回调函数，接收字符串消息，用于更新UI进度
        """
        self.progress_callback = progress_callback
        
        if not os.path.exists(file_path):
            logger.error(f"文件不存在: {file_path}")
            return False

        # 检查文件是否已加载
        if not force_reload and self.cad_file_path == file_path and self.is_loaded:
            logger.info(f"CAD文件已加载: {file_path}")
            return True

        # 连接到CAD
        if not self.connect_to_cad():
            return False
        
        # 检查当前活动文档是否为所选文件
        if not self.check_current_document(file_path):
            messagebox.showerror("CAD文件不匹配", 
                f"当前CAD活动文档与所选文件不一致！\n\n"
                f"请在AutoCAD中将当前文档切换到:\n{os.path.basename(file_path)}\n\n"
                f"然后重新点击「读取文件」按钮。")
            return False
               
        try:
            self.cad_file_path = file_path
            logger.info(f"开始加载CAD文件: {file_path}")

            # 清空旧数据
            self.clear_data()
            # 重置随层管径询问缓存，确保每次读取都询问
            self.default_color256_diameter = None
            
            # 获取配置
            config = self.config_manager.get_live_config()
            self.preprocess_enabled = config.get("preprocess_cad", False)

            # 调用 extract_all_data 并传入配置
            if self.progress_callback:
                self.progress_callback("正在提取管网数据...")
            if not self.extract_all_data(config):
                logger.error("提取管网数据失败")
                return False

            logger.info(f"CAD文件加载成功: {file_path}")
            # 确保项目目录存在，用于保存楼层配置
            self._ensure_project_dir()
            self.is_loaded = True
            return True

        except Exception as e:
            logger.error(f"加载CAD文件失败: {e}", exc_info=True)
            return False

    def _ensure_project_dir(self):
        """根据当前CAD文件路径创建或获取项目目录"""
        if not self.cad_file_path:
            return
        cad_name = os.path.splitext(os.path.basename(self.cad_file_path))[0]
        base_dir = "projects"
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
        project_index = 1
        while True:
            project_dir_name = f"{cad_name}_{project_index:03d}"
            project_dir = os.path.join(base_dir, project_dir_name)
            if not os.path.exists(project_dir):
                os.makedirs(project_dir)
                self.current_project_dir = project_dir
                break
            meta_file = os.path.join(project_dir, "project_meta.json")
            if os.path.exists(meta_file):
                try:
                    with open(meta_file, 'r') as f:
                        meta = json.load(f)
                    if meta.get("cad_file") == self.cad_file_path:
                        self.current_project_dir = project_dir
                        break
                except:
                    pass
            project_index += 1
        # 保存项目元数据
        meta = {
            "cad_file": self.cad_file_path,
            "created_at": pd.Timestamp.now().isoformat(),
        }
        meta_file = os.path.join(self.current_project_dir, "project_meta.json")
        with open(meta_file, 'w') as f:
            json.dump(meta, f, indent=2)

    def _collect_all_entities(self, config: dict) -> dict:
        """单次遍历 model_space，按类型分类收集所有实体数据，返回轻量字典"""
        model_space = self.acad.doc.ModelSpace

        pipe_layers = config.get("pipe_layers", [])
        valve_block_name = config.get("valve_block_name", "")
        hydrant_block_name = config.get("hydrant_block_name", "")
        sprinkler_block_name = config.get("sprinkler_block_name", "")
        riser_layers = config.get("riser_layers", [])
        riser_note_layers = config.get("riser_note_layers", [])
        align_block_name = config.get("align_block_name", "")

        result = {
            'pipe_segments': [],
            'valve_points': [],
            'valve_raw': [],
            'hydrant_raw': [],
            'sprinkler_raw': [],
            'riser_circles': [],
            'riser_lines': [],
            'riser_texts': [],
            'floor_align_blocks': [],
            'floor_rect_polylines': [],
        }

        for entity in model_space:
            try:
                _ = entity.ObjectName
            except:
                continue
            try:
                obj_name = entity.ObjectName
                layer = entity.Layer
                is_pipe_layer = layer in pipe_layers
                is_riser_layer = layer in riser_layers
                is_riser_note_layer = layer in riser_note_layers

                # 1. Pipe entities
                if obj_name in ("AcDbLine", "AcDbPolyline", "AcDb2dPolyline") and is_pipe_layer:
                    color = entity.Color
                    handle = entity.Handle
                    if obj_name in ("AcDbPolyline", "AcDb2dPolyline"):
                        coords = entity.Coordinates
                        elevation = getattr(entity, 'Elevation', 0.0)
                        if len(coords) % 2 == 0:
                            points = [(coords[i], coords[i+1], elevation) for i in range(0, len(coords), 2)]
                        else:
                            points = [(coords[i], coords[i+1], coords[i+2]) for i in range(0, len(coords), 3)]
                        for i in range(len(points) - 1):
                            result['pipe_segments'].append({
                                'start': points[i],
                                'end': points[i+1],
                                'color': color,
                                'layer': layer,
                                'handle': handle
                            })
                    else:
                        start = (entity.StartPoint[0], entity.StartPoint[1], entity.StartPoint[2])
                        end = (entity.EndPoint[0], entity.EndPoint[1], entity.EndPoint[2])
                        result['pipe_segments'].append({
                            'start': start,
                            'end': end,
                            'color': color,
                            'layer': layer,
                            'handle': handle
                        })
                    continue

                # 2. Block references
                if obj_name == "AcDbBlockReference":
                    name = entity.Name
                    ins = entity.InsertionPoint
                    handle = entity.Handle
                    xyz = (ins[0], ins[1], ins[2])

                    if name == valve_block_name:
                        result['valve_points'].append(xyz)
                        result['valve_raw'].append((ins[0], ins[1], ins[2], handle))
                    elif name == hydrant_block_name:
                        result['hydrant_raw'].append((ins[0], ins[1], ins[2], handle))
                    elif name == sprinkler_block_name:
                        result['sprinkler_raw'].append((ins[0], ins[1], ins[2], handle))
                    elif name == align_block_name:
                        result['floor_align_blocks'].append({
                            'point': (ins[0], ins[1], ins[2]),
                            'layer': layer,
                            'handle': handle
                        })
                    continue

                # 3. Riser circles/arcs
                if obj_name in ("AcDbCircle", "AcDbArc") and is_riser_layer:
                    center = entity.Center
                    result['riser_circles'].append({
                        'center': (center[0], center[1], center[2]),
                        'radius': entity.Radius,
                        'layer': layer,
                        'handle': entity.Handle
                    })
                    continue

                # 4. Riser note lines
                if obj_name == "AcDbLine" and is_riser_note_layer:
                    start = (entity.StartPoint[0], entity.StartPoint[1], entity.StartPoint[2])
                    end = (entity.EndPoint[0], entity.EndPoint[1], entity.EndPoint[2])
                    result['riser_lines'].append((start, end, entity.Handle))
                    continue

                # 5. Text entities
                if obj_name == "AcDbText":
                    ins = entity.InsertionPoint
                    result['riser_texts'].append({
                        'text': entity.TextString,
                        'pos': (ins[0], ins[1], ins[2])
                    })
                    continue

                # 6. Floor rect polylines (4-vertex axis-aligned)
                if obj_name in ("AcDbPolyline", "AcDb2dPolyline"):
                    coords = entity.Coordinates
                    if len(coords) == 8:
                        points = [(coords[i], coords[i+1]) for i in range(0, 8, 2)]
                    elif len(coords) == 12:
                        points = [(coords[i], coords[i+1]) for i in range(0, 12, 3)]
                    else:
                        continue
                    if len(points) == 4:
                        xs = sorted(set(p[0] for p in points))
                        ys = sorted(set(p[1] for p in points))
                        if len(xs) == 2 and len(ys) == 2:
                            result['floor_rect_polylines'].append({
                                'coords': coords,
                                'layer': layer,
                                'handle': entity.Handle
                            })

            except Exception:
                continue

        logger.info(f"单次遍历收集完成: {len(result['pipe_segments'])}管道段, "
                     f"{len(result['valve_raw'])}阀门, {len(result['hydrant_raw'])}消火栓, "
                     f"{len(result['sprinkler_raw'])}喷头块, "
                     f"{len(result['riser_circles'])}立管圆, {len(result['riser_texts'])}标注文本, "
                     f"{len(result['floor_align_blocks'])}对齐点, {len(result['floor_rect_polylines'])}楼层矩形")
        return result

    def _collect_entities_from_dxf(self, config: dict) -> dict:
        """通过 ezdxf 读取 DXF 临时文件收集实体，替代 COM 逐属性遍历"""
        try:
            import ezdxf
            logging.getLogger("ezdxf").setLevel(logging.ERROR)
        except ImportError:
            logger.warning("ezdxf 未安装，无法使用 DXF 加速")
            return None

        if not self.cad_file_path:
            logger.warning("无 CAD 文件路径，无法导出 DXF")
            return None

        doc = self.acad.doc

        pipe_layers = config.get("pipe_layers", [])
        valve_block_name = config.get("valve_block_name", "")
        hydrant_block_name = config.get("hydrant_block_name", "")
        sprinkler_block_name = config.get("sprinkler_block_name", "")
        riser_layers = config.get("riser_layers", [])
        riser_note_layers = config.get("riser_note_layers", [])
        align_block_name = config.get("align_block_name", "")

        result = {
            'pipe_segments': [],
            'valve_points': [],
            'valve_raw': [],
            'hydrant_raw': [],
            'sprinkler_raw': [],
            'riser_circles': [],
            'riser_lines': [],
            'riser_texts': [],
            'floor_align_blocks': [],
            'floor_rect_polylines': [],
        }

        tmp_path = None
        try:
            # 使用 Export 导出 DXF（不改变当前活动文档）
            tmp_stem = os.path.join(tempfile.gettempdir(), f"ocad_{uuid.uuid4().hex}")
            if self.progress_callback:
                self.progress_callback("正在导出 DXF...")
            ss = doc.SelectionSets.Add(f"ocad_ss_{uuid.uuid4().hex}")
            ss.Select(5)  # acSelectionSetAll = 5
            doc.Export(tmp_stem, "DXF", ss)
            ss.Delete()
            tmp_path = tmp_stem + ".dxf"
            import time
            time.sleep(0.5)
            if not os.path.exists(tmp_path):
                logger.error(f"DXF 导出后文件未创建: {tmp_path}")
                return None

            if self.progress_callback:
                self.progress_callback("正在解析 DXF...")
            dxf = ezdxf.readfile(tmp_path)
            msp = dxf.modelspace()

            if self.progress_callback:
                self.progress_callback("正在读取实体数据...")
            for entity in msp:
                try:
                    dxftype = entity.dxftype()
                except Exception:
                    continue
                try:
                    layer = entity.dxf.layer
                    is_pipe_layer = layer in pipe_layers
                    is_riser_layer = layer in riser_layers
                    is_riser_note_layer = layer in riser_note_layers
                    handle = entity.dxf.handle

                    if dxftype in ("LINE", "LWPOLYLINE", "POLYLINE") and is_pipe_layer:
                        color = entity.dxf.color
                        if dxftype == "LINE":
                            start = entity.dxf.start
                            end = entity.dxf.end
                            result['pipe_segments'].append({
                                'start': (start[0], start[1], start[2]),
                                'end': (end[0], end[1], end[2]),
                                'color': color,
                                'layer': layer,
                                'handle': handle,
                            })
                        else:
                            if dxftype == "LWPOLYLINE":
                                pts = entity.get_points()
                                elev = entity.dxf.elevation if entity.dxf.hasattr('elevation') else 0.0
                                points = [(p[0], p[1], elev) for p in pts]
                            else:
                                points = [(v.dxf.location[0], v.dxf.location[1], v.dxf.location[2])
                                          for v in entity.vertices]
                            for i in range(len(points) - 1):
                                result['pipe_segments'].append({
                                    'start': points[i],
                                    'end': points[i + 1],
                                    'color': color,
                                    'layer': layer,
                                    'handle': handle,
                                })
                        continue

                    if dxftype == "INSERT":
                        name = entity.dxf.name
                        ins = entity.dxf.insert
                        xyz = (ins[0], ins[1], ins[2])
                        if name == valve_block_name:
                            result['valve_points'].append(xyz)
                            result['valve_raw'].append((ins[0], ins[1], ins[2], handle))
                        elif name == hydrant_block_name:
                            result['hydrant_raw'].append((ins[0], ins[1], ins[2], handle))
                        elif name == sprinkler_block_name:
                            result['sprinkler_raw'].append((ins[0], ins[1], ins[2], handle))
                        elif name == align_block_name:
                            result['floor_align_blocks'].append({
                                'point': (ins[0], ins[1], ins[2]),
                                'layer': layer,
                                'handle': handle,
                            })
                        continue

                    if dxftype in ("CIRCLE", "ARC") and is_riser_layer:
                        center = entity.dxf.center
                        result['riser_circles'].append({
                            'center': (center[0], center[1], center[2]),
                            'radius': entity.dxf.radius,
                            'layer': layer,
                            'handle': handle,
                        })
                        continue

                    if dxftype == "LINE" and is_riser_note_layer:
                        start = entity.dxf.start
                        end = entity.dxf.end
                        result['riser_lines'].append(
                            ((start[0], start[1], start[2]),
                             (end[0], end[1], end[2]),
                             handle)
                        )
                        continue

                    if dxftype == "TEXT":
                        ins = entity.dxf.insert
                        result['riser_texts'].append({
                            'text': entity.dxf.text,
                            'pos': (ins[0], ins[1], ins[2]),
                        })
                        continue

                    if dxftype in ("LWPOLYLINE", "POLYLINE") and not is_pipe_layer:
                        if dxftype == "LWPOLYLINE":
                            pts = entity.get_points()
                            if len(pts) != 4:
                                continue
                            points_2d = [(p[0], p[1]) for p in pts]
                            flat_coords = []
                            for p in pts:
                                flat_coords.extend([p[0], p[1]])
                            coords = tuple(flat_coords)
                        else:
                            verts = list(entity.vertices)
                            if len(verts) != 4:
                                continue
                            points_2d = [(v.dxf.location[0], v.dxf.location[1]) for v in verts]
                            flat_coords = []
                            for v in verts:
                                flat_coords.extend([v.dxf.location[0], v.dxf.location[1]])
                            coords = tuple(flat_coords)
                        xs = sorted(set(p[0] for p in points_2d))
                        ys = sorted(set(p[1] for p in points_2d))
                        if len(xs) == 2 and len(ys) == 2:
                            result['floor_rect_polylines'].append({
                                'coords': coords,
                                'layer': layer,
                                'handle': handle,
                            })

                except Exception:
                    continue

            logger.info(f"DXF 解析完成: {len(result['pipe_segments'])}管道段, "
                         f"{len(result['valve_raw'])}阀门, {len(result['hydrant_raw'])}消火栓, "
                         f"{len(result['sprinkler_raw'])}喷头块, "
                         f"{len(result['riser_circles'])}立管圆, {len(result['riser_texts'])}标注文本, "
                         f"{len(result['floor_align_blocks'])}对齐点, {len(result['floor_rect_polylines'])}楼层矩形")
            return result

        except Exception as e:
            logger.warning(f"DXF 读取失败: {e}，将回退到 COM 模式")
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def extract_all_data(self, config: dict) -> bool:
        """提取所有管网数据"""
        collected = None
        try:
            if self.progress_callback:
                self.progress_callback("清空旧数据...")
            self.clear_data()

            if self.acad and hasattr(self.acad, 'doc'):
                use_dxf = config.get("use_dxf_read", False)
                if use_dxf:
                    if self.progress_callback:
                        self.progress_callback("正在扫描CAD实体（DXF模式）...")
                    collected = self._collect_entities_from_dxf(config)
                else:
                    if self.progress_callback:
                        self.progress_callback("正在扫描CAD实体（COM模式）...")
                    collected = self._collect_all_entities(config)
                if collected is None and use_dxf:
                    logger.info("DXF 模式失败，回退到 COM 模式")
                    if self.progress_callback:
                        self.progress_callback("正在扫描CAD实体（COM回退模式）...")
                    collected = self._collect_all_entities(config)
            else:
                logger.warning("CAD未连接，无法使用单次遍历优化")
                collected = None

            if self.progress_callback:
                self.progress_callback("正在提取管道...")
            logger.info("正在提取管道...")
            if not self.extract_pipes(config, collected=collected):
                logger.error("提取管道数据失败")
                return False

            if self.progress_callback:
                self.progress_callback("正在提取节点...")
            logger.info("正在提取节点...")
            if not self.extract_nodes(config):
                logger.error("提取节点数据失败")
                return False

            if self.progress_callback:
                self.progress_callback("正在匹配节点与管道...")
            logger.info("正在匹配节点与管道...")
            if not self.match_nodes_with_pipes(config.get("tolerance", 10.0)):
                logger.error("匹配节点与管道失败")
                return False

            if self.progress_callback:
                self.progress_callback("正在提取阀门...")
            logger.info("正在提取阀门...")
            if not self.extract_valves(config, collected=collected):
                logger.warning("提取阀门数据失败或未找到")

            if self.progress_callback:
                self.progress_callback("正在匹配阀门...")
            logger.info("正在匹配阀门...")
            self.match_valves_with_pipes(config.get("tolerance", 10.0))

            if self.progress_callback:
                self.progress_callback("正在提取消火栓...")
            logger.info("正在提取消火栓...")
            if not self.extract_hydrants(config, collected=collected):
                logger.warning("提取消火栓数据失败或未找到")

            if self.progress_callback:
                self.progress_callback("正在提取立管...")
            logger.info("正在提取立管...")
            self.extract_risers(config, collected=collected)

            if self.progress_callback:
                self.progress_callback("正在匹配立管与横管...")
            logger.info("正在匹配立管与横管...")
            self.match_risers_with_nodes(config.get("tolerance", 10.0), config)

            if self.progress_callback:
                self.progress_callback("正在提取楼层信息...")
            logger.info("正在提取楼层信息...")
            has_floors = self.extract_floors(config, collected=collected)
            
            if has_floors:
                if self.progress_callback:
                    self.progress_callback("正在分配管道到楼层...")
                logger.info("正在分配管道到楼层...")
                self.assign_pipes_to_floors()
                
                if self.progress_callback:
                    self.progress_callback("正在展开多楼层合一...")
                logger.info("正在展开多楼层合一...")
                drawing_unit = config.get("drawing_unit", "毫米")
                unit_factor = self.unit_factors.get(drawing_unit, 0.001)
                self._expand_multi_floors(unit_factor)

                if self.progress_callback:
                    self.progress_callback("正在检查管道间距...")
                logger.info("正在检查管道间距...")
                if not self.check_clearance(config):
                    return False

                if self.progress_callback:
                    self.progress_callback("正在对齐各楼层坐标...")
                logger.info("正在对齐各楼层坐标...")
                self.align_floors_to_baseline()

                if self.progress_callback:
                    self.progress_callback("正在计算管网标高...")
                logger.info("正在计算管网标高...")
                self.assign_node_z_coordinates(config)
                
                if self.progress_callback:
                    self.progress_callback("正在生成立管管道及连接...")
                logger.info("正在生成立管管道及连接...")
                self.create_riser_pipes_and_connections(config)
                
                if self.progress_callback:
                    self.progress_callback("正在配对消火栓与立管，生成支管...")
                logger.info("正在配对消火栓与立管，生成支管...")
                self.connect_hydrants_to_risers(config)

                self.check_duplicate_risers_in_floor()
            
            if self.progress_callback:
                self.progress_callback("正在更新管道类型...")
            logger.info("正在更新管道类型...")
            self.update_pipe_types(config)
            
            if config.get("system_type", "indoor_hydrant") == "sprinkler":
                if self.progress_callback:
                    self.progress_callback("正在处理喷淋短管...")
                logger.info("正在处理喷淋短管...")
                sprinkler_raw = collected.get('sprinkler_raw', []) if collected else []
                self._sprinkler_raw = sprinkler_raw
                self.add_short_pipes_for_sprinklers(config, sprinkler_raw)
            
            logger.info(f"数据提取完成: {len(self.pipes)}管道, {len(self.nodes)}节点")
            return True

        except Exception as e:
            logger.error(f"提取管网数据失败: {e}")
            return False
        finally:
            if collected is not None:
                del collected

    def add_short_pipes_for_sprinklers(self, config: dict, sprinkler_raw: list = None) -> bool:
        """为每个喷头块位置添加向上短立管。

        参数:
            config: 配置字典
            sprinkler_raw: 喷头块位置列表 [(x,y,z,handle), ...]
        """
        if sprinkler_raw is None:
            sprinkler_raw = getattr(self, '_sprinkler_raw', [])
        return self._add_short_pipes_from_sprinkler_raw(config, sprinkler_raw)


    def _add_short_pipes_from_sprinkler_raw(self, config: dict, sprinkler_raw: list) -> bool:
        """根据喷头块位置列表创建向上短立管。"""
        try:
            if not sprinkler_raw:
                logger.info("无喷头块数据，跳过短管添加")
                return True

            material = config.get("pipe_material", "镀锌钢管")
            short_len_m = 0.1
            K = config.get("sprinkler_K", 80)
            short_dn = self.material_manager.get_sprinkler_dn(K)
            diameter_info = self.material_manager.get_diameter_info(material, short_dn)
            if diameter_info.get("inner", 0) == 0:
                logger.warning(f"无法为喷淋短管找到内径（{short_dn}），使用默认值27.3mm")
                inner_diameter_mm = 27.3
            else:
                inner_diameter_mm = diameter_info["inner"]

            drawing_unit = config.get("drawing_unit", "毫米")
            unit_factor = self.unit_factors.get(drawing_unit, 0.001)
            height_increment = short_len_m / unit_factor if unit_factor > 0 else short_len_m * 1000
            tolerance = config.get("tolerance", 10.0) * 0.001

            new_pipes = []
            new_nodes = []

            for (x, y, z_raw, handle) in sprinkler_raw:
                nearest_node = self._find_nearest_node((x, y, z_raw), tolerance)
                if not nearest_node:
                    logger.debug(f"喷头块({x},{y},{z_raw})附近无管道节点，跳过")
                    continue

                node_id = nearest_node.node_id
                short_node_id = f"{node_id}_S"

                if short_node_id in self.node_by_id:
                    continue
                if any(n.node_id == short_node_id for n in self.nodes):
                    continue

                new_node = NodeData(
                    node_id=short_node_id,
                    x=nearest_node.x,
                    y=nearest_node.y,
                    z=nearest_node.z + height_increment,
                    cad_key=f"{nearest_node.x:.6f},{nearest_node.y:.6f},{nearest_node.z+height_increment:.6f}",
                    connected_pipes=[]
                )
                self.nodes.append(new_node)
                self.node_by_id[new_node.node_id] = new_node
                new_nodes.append(new_node)

                pipe_id = f"SP_{node_id}"
                new_pipe = PipeData(
                    pipe_id=pipe_id,
                    start_node_id=node_id,
                    end_node_id=short_node_id,
                    start_point=(nearest_node.x, nearest_node.y, nearest_node.z),
                    end_point=(new_node.x, new_node.y, new_node.z),
                    length=short_len_m,
                    inner_diameter=inner_diameter_mm,
                    nominal_diameter=short_dn,
                    material=material,
                    status="开",
                    pipe_type="-"
                )
                new_pipes.append(new_pipe)

                if pipe_id not in nearest_node.connected_pipes:
                    nearest_node.connected_pipes.append(pipe_id)
                new_node.connected_pipes.append(pipe_id)

                self.sprinkler_s_node_ids.append(short_node_id)
                self.sprinkler_k_map[node_id] = float(K)

            self.pipes.extend(new_pipes)
            for pipe in new_pipes:
                self.pipe_by_id[pipe.pipe_id] = pipe

            logger.info(f"为 {len(new_nodes)} 个喷头块添加了喷淋短管")
            return True

        except Exception as e:
            logger.error(f"添加喷淋短管失败: {e}", exc_info=True)
            return False

    def extract_pipes(self, config: dict, collected: dict = None) -> bool:
        try:
            pipe_layers = config.get("pipe_layers", [])
            drawing_unit = config.get("drawing_unit", "毫米")
            pipe_material = config.get("pipe_material", "镀锌钢管")
            if not pipe_layers:
                logger.warning("未设置管道图层")
                return False
            color_table = self.material_manager.get_color_diameter_table(pipe_material)
            if not color_table:
                logger.error(f"未找到管材'{pipe_material}'的颜色管径对照表")
                return False
            roughness = self.material_manager.get_roughness(pipe_material)
            unit_factor = self.unit_factors.get(drawing_unit, 0.001)
            self.pipes.clear()
            self.pipe_by_id.clear()
            success = self._extract_pipes_from_cad(config, pipe_layers, pipe_material, color_table,
                                                roughness, unit_factor, collected=collected)
            # 预处理已经处理了重合和交叉，不再需要额外合并
            # self._merge_duplicate_pipes()
            return success
        except Exception as e:
            logger.error(f"提取管道数据失败: {e}")
            return False

    def _merge_duplicate_pipes(self):
        """
        合并共线且部分或完全重叠的管道（排除仅端点相接的情况）
        """
        tolerance = self.config_manager.get_live_config().get("tolerance", 10.0) * 0.001  # 米
        unique_pipes = []
        duplicate_count = 0

        # 辅助函数：判断点是否在线段上（包括端点）
        def point_on_segment(px, py, x1, y1, x2, y2, tol):
            if min(x1, x2) - tol > px or px > max(x1, x2) + tol:
                return False
            if min(y1, y2) - tol > py or py > max(y1, y2) + tol:
                return False
            dx = x2 - x1
            dy = y2 - y1
            if dx == 0 and dy == 0:
                return math.hypot(px - x1, py - y1) < tol
            t = ((px - x1) * dx + (py - y1) * dy) / (dx*dx + dy*dy)
            if t < 0 or t > 1:
                return False
            proj_x = x1 + t * dx
            proj_y = y1 + t * dy
            return math.hypot(px - proj_x, py - proj_y) < tol

        # 辅助函数：判断两条线段是否共线（方向平行且在同一直线上）
        def is_collinear(pipe1, pipe2, tol):
            x1, y1 = pipe1.start_point[0], pipe1.start_point[1]
            x2, y2 = pipe1.end_point[0], pipe1.end_point[1]
            x3, y3 = pipe2.start_point[0], pipe2.start_point[1]
            x4, y4 = pipe2.end_point[0], pipe2.end_point[1]
            dx1 = x2 - x1
            dy1 = y2 - y1
            dx2 = x4 - x3
            dy2 = y4 - y3
            if dx1 == 0 and dy1 == 0:
                return False
            if dx2 == 0 and dy2 == 0:
                return False
            # 平行检查（叉积）
            cross = dx1 * dy2 - dy1 * dx2
            if abs(cross) > tol:
                return False
            # 检查共线：pipe1 的起点到 pipe2 所在直线的距离
            if dx2 != 0 or dy2 != 0:
                d = abs((x4 - x3) * (y1 - y3) - (y4 - y3) * (x1 - x3)) / math.hypot(dx2, dy2)
                if d > tol:
                    return False
            else:
                if dx1 != 0 or dy1 != 0:
                    d = abs((x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)) / math.hypot(dx1, dy1)
                    if d > tol:
                        return False
                else:
                    return math.hypot(x1 - x3, y1 - y3) < tol
            return True

        for pipe in self.pipes:
            is_duplicate = False
            for existing in unique_pipes:
                if not is_collinear(pipe, existing, tolerance):
                    continue

                p1 = (pipe.start_point[0], pipe.start_point[1])
                p2 = (pipe.end_point[0], pipe.end_point[1])
                e1 = (existing.start_point[0], existing.start_point[1])
                e2 = (existing.end_point[0], existing.end_point[1])

                # 检查 pipe 的端点是否在 existing 上
                p1_on_existing = point_on_segment(p1[0], p1[1], e1[0], e1[1], e2[0], e2[1], tolerance)
                p2_on_existing = point_on_segment(p2[0], p2[1], e1[0], e1[1], e2[0], e2[1], tolerance)
                # 检查 existing 的端点是否在 pipe 上
                e1_on_pipe = point_on_segment(e1[0], e1[1], p1[0], p1[1], p2[0], p2[1], tolerance)
                e2_on_pipe = point_on_segment(e2[0], e2[1], p1[0], p1[1], p2[0], p2[1], tolerance)

                # 判断是否为仅仅端点相连（只有一端重合，且无其他重叠）
                only_endpoint = False
                if (p1_on_existing and not p2_on_existing and not e1_on_pipe and not e2_on_pipe) or \
                (p2_on_existing and not p1_on_existing and not e1_on_pipe and not e2_on_pipe) or \
                (e1_on_pipe and not e2_on_pipe and not p1_on_existing and not p2_on_existing) or \
                (e2_on_pipe and not e1_on_pipe and not p1_on_existing and not p2_on_existing):
                    only_endpoint = True

                # 如果有内部重叠（两个端点都在对方上，或一个端点在对方上且另一个也在对方上等），视为重合
                if (p1_on_existing and p2_on_existing) or \
                (e1_on_pipe and e2_on_pipe) or \
                (p1_on_existing and e1_on_pipe) or \
                (p1_on_existing and e2_on_pipe) or \
                (p2_on_existing and e1_on_pipe) or \
                (p2_on_existing and e2_on_pipe):
                    is_duplicate = True
                    duplicate_count += 1
                    logger.warning(f"发现重叠管道: {pipe.pipe_id} 与 {existing.pipe_id} 共线重叠，将忽略 {pipe.pipe_id}")
                    break
                elif not only_endpoint:
                    # 既不是仅端点相连，也不是部分重叠，可能是分离但共线，不处理
                    pass
            if not is_duplicate:
                unique_pipes.append(pipe)

        if duplicate_count > 0:
            logger.info(f"合并了 {duplicate_count} 条重叠管道，剩余 {len(unique_pipes)} 条")
            self.pipes = unique_pipes
            # 重新建立 pipe_by_id 索引
            self.pipe_by_id.clear()
            for pipe in self.pipes:
                self.pipe_by_id[pipe.pipe_id] = pipe


    def _extract_pipes_from_cad(self, config, pipe_layers, material, color_table, roughness, unit_factor, collected=None):
        """从实际CAD中提取管道（支持多段线拆分）- 优化版"""
        try:
            if not CAD_AVAILABLE:
                logger.error("pyautocad不可用，无法提取CAD数据")
                return False

            if not self.acad or not hasattr(self.acad, 'doc'):
                logger.error("CAD连接未建立")
                return False

            # 预收集路径或预处理路径
            if collected is not None or getattr(self, 'preprocess_enabled', False):
                if self.progress_callback:
                    self.progress_callback("预处理：拆分多段线...")
                tolerance = self.config_manager.get_live_config().get("tolerance", 10.0)

                if collected is not None:
                    segments = collected['pipe_segments']
                    if not segments:
                        logger.warning("预收集无管道段")
                        return False
                    simple_lines = preprocess_from_segments(segments, tolerance)
                    valve_points = collected['valve_points']
                    simple_lines = merge_pipes_at_valves_from_points(simple_lines, valve_points, tolerance)
                else:
                    simple_lines = preprocess_cad_data(self.acad, pipe_layers, tolerance)
                    if not simple_lines:
                        logger.warning("预处理未生成任何线段")
                        return False
                    valve_block_name = config.get("valve_block_name", "valve")
                    simple_lines = merge_pipes_at_valves(simple_lines, self.acad, valve_block_name, tolerance)

                if self.progress_callback:
                    self.progress_callback("预处理：创建管道对象...")

                pipe_count = 0
                warned_colors = set()
                for line in simple_lines:
                    pipes_data = self._create_pipe_from_entity(
                        line, material, color_table, roughness, unit_factor,
                        line.Layer, warned_colors
                    )
                    if pipes_data:
                        for pipe_data in pipes_data:
                            pipe_count += 1
                            id_digits = 4 if pipe_count < 10000 else 5
                            pipe_data.pipe_id = f"P_{pipe_count:0{id_digits}d}"
                            self.pipes.append(pipe_data)
                            self.pipe_by_id[pipe_data.pipe_id] = pipe_data
                logger.info(f"{'预收集' if collected else '预处理'}模式：从 {len(simple_lines)} 个直线段创建了 {len(self.pipes)} 条管道")
                return len(self.pipes) > 0

            model_space = self.acad.doc.ModelSpace
            pipe_count = 0
            warned_colors = set()

            for entity in model_space:
                try:
                    _ = entity.ObjectName
                except:
                    continue
                try:
                    entity_type = entity.ObjectName

                    if entity_type not in ["AcDbPolyline", "AcDb2dPolyline", "AcDbLine"]:
                        continue

                    entity_layer = entity.Layer
                    if entity_layer not in pipe_layers:
                        continue

                    pipes_data = self._create_pipe_from_entity(
                        entity, material, color_table, roughness, unit_factor,
                        entity_layer, warned_colors
                    )

                    if pipes_data:
                        for pipe_data in pipes_data:
                            pipe_count += 1
                            id_digits = 4
                            if pipe_count >= 10000:
                                id_digits = 5

                            pipe_data.pipe_id = f"P_{pipe_count:0{id_digits}d}"
                            self.pipes.append(pipe_data)
                            self.pipe_by_id[pipe_data.pipe_id] = pipe_data

                except Exception as e:
                    continue

            return len(self.pipes) > 0

        except Exception as e:
            logger.error(f"从CAD提取管道失败: {e}")
            return False

    def _create_pipe_from_entity(self, entity, material, color_table, roughness,
                                 unit_factor, layer, warned_colors, by_layer_list=None):
        """从CAD实体创建管道数据（支持多段线拆分）"""
        try:
            pipes_data = []  # 存储多个管道数据

            # 获取颜色代码
            color_code = entity.Color
            color_str = str(color_code)

            # 处理颜色代码256（随层）的情况
            if color_code == 256:
                # 询问用户随层管道的默认管径
                if self.default_color256_diameter is None:
                    user_dn = self._ask_user_for_color256_diameter_sync()
                    self.default_color256_diameter = user_dn
                target_dn = self.default_color256_diameter
                # 从颜色表中查找该公称管径对应的内径
                inner_diam = 0.0
                for c, info in color_table.items():
                    if info.get("nominal") == target_dn:
                        inner_diam = info.get("inner", 0.0)
                        break
                if inner_diam == 0.0:
                    logger.warning(f"未找到公称管径 {target_dn} 对应的内径，使用默认内径100mm")
                    inner_diam = 100.0
                diameter_info = {"nominal": target_dn, "inner": inner_diam}
                # 注意：随层管道没有固定的颜色代码，不需要记录警告
            else:
                # 根据颜色获取管径
                diameter_info = color_table.get(color_str)
                if not diameter_info:
                    # 颜色不在对照表中，记录警告（只记录一次）
                    if color_str not in warned_colors:
                        logger.warning(f"颜色代码 {color_code} 未在管径对照表中定义，跳过此管道")
                        warned_colors.add(color_str)
                    return None

            if entity.ObjectName in ["AcDbPolyline", "AcDb2dPolyline"]:
                # 多段线可能有多个顶点
                coords = entity.Coordinates
                vertex_count = len(coords)

                # 确定每个顶点的坐标维度（2D或3D）
                if vertex_count % 3 == 0:
                    # 3D坐标，每3个值一个点
                    points = []
                    for i in range(0, vertex_count, 3):
                        points.append((coords[i], coords[i+1], coords[i+2]))
                else:
                    # 2D坐标，每2个值一个点，Z坐标为0
                    points = []
                    for i in range(0, vertex_count, 2):
                        points.append((coords[i], coords[i+1], 0.0))

                # 将多段线拆分为多个直线段
                if len(points) >= 2:
                    total_length = entity.Length

                    # 计算每段的近似长度（平均分配）
                    segment_count = len(points) - 1
                    avg_length = total_length / segment_count if segment_count > 0 else 0

                    for i in range(len(points) - 1):
                        start_point = points[i]
                        end_point = points[i + 1]

                        # 创建管道数据对象
                        pipe_data = PipeData(
                            start_point=start_point,
                            end_point=end_point,
                            color_code=color_code,
                            nominal_diameter=diameter_info.get("nominal", ""),
                            inner_diameter=diameter_info.get("inner", 0.0),
                            length=avg_length * unit_factor,  # 使用平均长度
                            raw_length=avg_length,
                            material=material,
                            roughness=roughness,
                            layer=layer,
                            entity_handle=entity.Handle
                        )
                        pipes_data.append(pipe_data)

            elif entity.ObjectName == "AcDbLine":
                # 直线，直接创建
                start_point = (
                    entity.StartPoint[0], entity.StartPoint[1], entity.StartPoint[2])
                end_point = (
                    entity.EndPoint[0], entity.EndPoint[1], entity.EndPoint[2])
                dx = end_point[0] - start_point[0]
                dy = end_point[1] - start_point[1]
                raw_length = math.hypot(dx, dy)

                # 创建管道数据对象
                pipe_data = PipeData(
                    start_point=start_point,
                    end_point=end_point,
                    color_code=color_code,
                    nominal_diameter=diameter_info.get("nominal", ""),
                    inner_diameter=diameter_info.get("inner", 0.0),
                    length=raw_length * unit_factor,
                    raw_length=raw_length,
                    material=material,
                    roughness=roughness,
                    layer=layer,
                    entity_handle=entity.Handle
                )
                pipes_data.append(pipe_data)

            else:
                return None

            return pipes_data  # 返回管道列表

        except Exception as e:
            logger.error(f"从实体创建管道数据失败: {e}")
            return None

    def extract_nodes(self, config: dict) -> bool:
        """
        提取节点数据（简化版本）
        注意：这个函数在match_nodes_with_pipes中已经实现了节点创建，
        这里只做简单的初始化
        """
        try:
            # 清空现有节点数据
            self.nodes.clear()
            self.node_by_id.clear()
            logger.info("节点数据结构已初始化")
            return True

        except Exception as e:
            logger.error(f"初始化节点数据失败: {e}")
            return False

    def match_nodes_with_pipes(self, tolerance_mm: float = 10.0) -> bool:
        """
        建立节点与管道的连接关系，合并容差范围内的相同坐标节点
        Args:
            tolerance_mm: 容差（毫米），用于合并节点
        """
        try:
            tolerance = tolerance_mm * 0.001  # 转换为米
            nodes = []          # 存储已创建的节点对象
            node_counter = 1

            # 清空现有节点数据
            self.nodes.clear()
            self.node_by_id.clear()

            # 辅助函数：查找距离最近的节点
            def find_existing_node(point):
                for node in nodes:
                    dx = point[0] - node.x
                    dy = point[1] - node.y
                    dz = point[2] - node.z
                    if math.sqrt(dx*dx + dy*dy + dz*dz) < tolerance:
                        return node
                return None

            # 第一遍：创建节点（合并相近点）
            for pipe in self.pipes:
                # 处理起点
                start_point = pipe.start_point
                existing = find_existing_node(start_point)
                if existing is None:
                    node = NodeData(
                        node_id=f"N_{node_counter:04d}",
                        x=start_point[0],
                        y=start_point[1],
                        z=start_point[2],
                        cad_key=f"{start_point[0]:.6f},{start_point[1]:.6f},{start_point[2]:.6f}"
                    )
                    nodes.append(node)
                    self.nodes.append(node)
                    self.node_by_id[node.node_id] = node
                    node_counter += 1
                else:
                    # 使用已有节点
                    pass

                # 处理终点
                end_point = pipe.end_point
                existing = find_existing_node(end_point)
                if existing is None:
                    node = NodeData(
                        node_id=f"N_{node_counter:04d}",
                        x=end_point[0],
                        y=end_point[1],
                        z=end_point[2],
                        cad_key=f"{end_point[0]:.6f},{end_point[1]:.6f},{end_point[2]:.6f}"
                    )
                    nodes.append(node)
                    self.nodes.append(node)
                    self.node_by_id[node.node_id] = node
                    node_counter += 1
                else:
                    pass

            # 第二遍：建立连接关系（根据实际节点对象）
            # 构建一个从点坐标到节点对象的快速查找表（使用四舍五入后的坐标，容差内视为相同）
            # 注意：这里为了效率，我们仍使用坐标键，但为了容差，可以用四舍五入后的坐标作为键
            # 简便方法：直接用节点对象列表查找
            for pipe in self.pipes:
                start_point = pipe.start_point
                end_point = pipe.end_point
                # 查找起点节点
                start_node = None
                for node in nodes:
                    dx = start_point[0] - node.x
                    dy = start_point[1] - node.y
                    dz = start_point[2] - node.z
                    if math.sqrt(dx*dx + dy*dy + dz*dz) < tolerance:
                        start_node = node
                        break
                if start_node:
                    pipe.start_node_id = start_node.node_id
                    if pipe.pipe_id not in start_node.connected_pipes:
                        start_node.connected_pipes.append(pipe.pipe_id)

                # 查找终点节点
                end_node = None
                for node in nodes:
                    dx = end_point[0] - node.x
                    dy = end_point[1] - node.y
                    dz = end_point[2] - node.z
                    if math.sqrt(dx*dx + dy*dy + dz*dz) < tolerance:
                        end_node = node
                        break
                if end_node:
                    pipe.end_node_id = end_node.node_id
                    if pipe.pipe_id not in end_node.connected_pipes:
                        end_node.connected_pipes.append(pipe.pipe_id)

            logger.info(f"节点匹配完成：{len(self.nodes)} 个节点，{len(self.pipes)} 条管道")
            return True

        except Exception as e:
            logger.error(f"匹配节点与管道失败: {e}")
            return False

    def _find_closest_node(self, x, y, z, max_distance=0.01):
        """查找最近的节点（容差匹配）"""
        closest_node = None
        min_distance = float('inf')

        for node in self.nodes:
            dx = x - node.x
            dy = y - node.y
            dz = z - node.z
            distance = math.sqrt(dx*dx + dy*dy + dz*dz)

            if distance < min_distance and distance < max_distance:
                min_distance = distance
                closest_node = node

        return closest_node

    def extract_supply_demand_nodes(self, config: dict, collected: dict = None) -> bool:
        """已废弃：供/用水点不再从 CAD 读取。保留空壳避免外部调用报错。"""
        self.supply_nodes.clear()
        self.demand_groups.clear()
        return True

    def get_block_attributes_direct(self, entity_or_handle, attribute_name):
        """直接使用COM接口获取图块属性，接受 entity 或 handle 字符串"""
        try:
            import win32com.client

            acad_app = win32com.client.Dispatch("AutoCAD.Application")

            doc = acad_app.ActiveDocument

            if isinstance(entity_or_handle, str):
                handle = entity_or_handle
            else:
                handle = entity_or_handle.Handle
            block_ref = doc.HandleToObject(handle)

            if not block_ref:
                logger.error(f"无法通过句柄找到图块: {handle}")
                return None

            # 获取属性
            if hasattr(block_ref, 'GetAttributes'):
                attrs = block_ref.GetAttributes()

                for attr in attrs:
                    tag = str(attr.TagString).strip() if hasattr(
                        attr, 'TagString') else ""
                    text = str(attr.TextString).strip() if hasattr(
                        attr, 'TextString') else ""

                    if tag.upper() == attribute_name.upper():
                        logger.info(f"找到属性: {tag} = {text}")
                        return text

            return None

        except Exception as e:
            logger.error(f"直接获取图块属性失败: {e}")
            return None

    def _find_nearest_node(self, point, max_distance=0.01):
        """查找距离最近的节点"""
        nearest_node = None
        min_distance = float('inf')

        for node in self.nodes:
            dx = point[0] - node.x
            dy = point[1] - node.y
            dz = point[2] - node.z
            distance = math.sqrt(dx*dx + dy*dy + dz*dz)

            if distance < min_distance and distance < max_distance:
                min_distance = distance
                nearest_node = node

        return nearest_node

    def update_pipe_types(self, config: dict):
        """根据系统类型和管径更新所有管道的类型"""
        system_type = config.get("system_type", "indoor_hydrant")
        for pipe in self.pipes:
            dn_str = pipe.nominal_diameter
            # 提取数字部分
            if dn_str.startswith("DN"):
                try:
                    num = int(dn_str[2:])
                except:
                    num = 0
            else:
                num = 0
            if system_type in ("indoor_hydrant", "outdoor_hydrant"):
                if num >= 100:
                    pipe.pipe_type = "干管"
                elif num == 65:
                    pipe.pipe_type = "支管"
                else:
                    pipe.pipe_type = "错误管径"
            elif system_type == "sprinkler":
                pipe.pipe_type = "-"
            else:
                pipe.pipe_type = "未知"

    def update_all_pipes_material(self, new_material: str):
        """更新所有管道的管材，并根据新管材重新获取内径"""
        # 获取新管材的颜色-管径对照表
        color_table = self.material_manager.get_color_diameter_table(new_material)
        if not color_table:
            logger.warning(f"新管材 {new_material} 的颜色表为空，无法更新内径")
            # 只更新材料名称，内径可能不变
            for pipe in self.pipes:
                pipe.material = new_material
            return
        # 根据颜色代码更新内径
        for pipe in self.pipes:
            pipe.material = new_material
            # 获取内径
            info = color_table.get(str(pipe.color_code))
            if info:
                pipe.inner_diameter = info.get("inner", 0.0)
            else:
                logger.debug(f"管道 {pipe.pipe_id} 颜色 {pipe.color_code} 在新管材中无对应，内径保留原值")
        # 同时更新管材管理器中的粗糙系数（如果需要）
        self.roughness = self.material_manager.get_roughness(new_material)

    def extract_valves(self, config: dict, collected: dict = None) -> bool:
        """
        提取阀门数据（不再读取属性，所有阀门初始状态为OPEN）
        """
        try:
            self.valves.clear()
            self.valve_by_id.clear()

            if collected is not None:
                valve_count = 0
                for (x, y, z, handle) in collected['valve_raw']:
                    valve_count += 1
                    valve = ValveData(
                        valve_id=f"V_{valve_count:04d}",
                        status="OPEN",
                        x=x, y=y, z=z,
                        attribute_value="",
                        entity_handle=handle
                    )
                    self.valves.append(valve)
                    self.valve_by_id[valve.valve_id] = valve
                logger.info(f"阀门提取完成(预收集): 共 {len(self.valves)} 个阀门")
                return True

            valve_block_name = config.get("valve_block_name", "valve")
            tolerance = config.get("tolerance", 10.0) * 0.001  # 转换为米

            if not CAD_AVAILABLE or not self.acad:
                logger.warning("CAD未连接，无法提取阀门")
                return True

            model_space = self.acad.doc.ModelSpace
            valve_count = 0

            logger.info(f"开始提取阀门图块: {valve_block_name}")

            for entity in model_space:
                try:
                    _ = entity.ObjectName
                except:
                    continue
                try:
                    if entity.ObjectName != "AcDbBlockReference":
                        continue
                    if entity.Name != valve_block_name:
                        continue

                    valve_point = (
                        entity.InsertionPoint[0],
                        entity.InsertionPoint[1],
                        entity.InsertionPoint[2]
                    )

                    valve_count += 1
                    valve = ValveData(
                        valve_id=f"V_{valve_count:04d}",
                        status="OPEN",
                        x=valve_point[0],
                        y=valve_point[1],
                        z=valve_point[2],
                        attribute_value="",
                        entity_handle=entity.Handle if hasattr(entity, 'Handle') else ""
                    )

                    self.valves.append(valve)
                    self.valve_by_id[valve.valve_id] = valve

                    logger.debug(f"阀门 {valve.valve_id} 已提取: 位置({valve.x:.2f}, {valve.y:.2f}, {valve.z:.2f}), 状态=OPEN")

                except Exception as e:
                    if "空对象 ID" in str(e):
                        logger.debug(f"忽略空对象阀门图块: {e}")
                    else:
                        logger.warning(f"处理阀门图块时出错: {e}", exc_info=True)
                    continue

            logger.info(f"阀门提取完成: 共 {len(self.valves)} 个阀门")
            return True

        except Exception as e:
            logger.error(f"提取阀门数据失败: {e}", exc_info=True)
            return False

    def extract_hydrants(self, config: dict, collected: dict = None) -> bool:
        """提取消火栓图块数据"""
        try:
            self.hydrants.clear()
            self.hydrant_by_id.clear()

            if collected is not None:
                hydrant_block_name = config.get("hydrant_block_name", "hydrant")
                hydrant_count = 0
                for (x, y, z, handle) in collected['hydrant_raw']:
                    hydrant_count += 1
                    hydrant = HydrantData(
                        hydrant_id=f"H_{hydrant_count:04d}",
                        x=x, y=y, z=z,
                        block_name=hydrant_block_name,
                        entity_handle=handle
                    )
                    self.hydrants.append(hydrant)
                    self.hydrant_by_id[hydrant.hydrant_id] = hydrant
                logger.info(f"消火栓提取完成(预收集): 共 {len(self.hydrants)} 个")
                return True

            hydrant_block_name = config.get("hydrant_block_name", "hydrant")
            tolerance = config.get("tolerance", 10.0) * 0.001

            if not CAD_AVAILABLE or not self.acad:
                logger.warning("CAD未连接，无法提取消火栓")
                return True

            model_space = self.acad.doc.ModelSpace
            hydrant_count = 0

            logger.info(f"开始提取消火栓图块: {hydrant_block_name}")

            for entity in model_space:
                try:
                    _ = entity.ObjectName
                except:
                    continue
                try:
                    if entity.ObjectName != "AcDbBlockReference":
                        continue
                    if entity.Name != hydrant_block_name:
                        continue

                    point = (entity.InsertionPoint[0],
                             entity.InsertionPoint[1],
                             entity.InsertionPoint[2])

                    hydrant_count += 1
                    hydrant = HydrantData(
                        hydrant_id=f"H_{hydrant_count:04d}",
                        x=point[0],
                        y=point[1],
                        z=point[2],
                        block_name=hydrant_block_name,
                        entity_handle=entity.Handle if hasattr(entity, 'Handle') else ""
                    )
                    self.hydrants.append(hydrant)
                    self.hydrant_by_id[hydrant.hydrant_id] = hydrant

                    logger.debug(f"消火栓 {hydrant.hydrant_id} 已提取: ({point[0]:.2f}, {point[1]:.2f}, {point[2]:.2f})")

                except Exception as e:
                    if "空对象 ID" in str(e):
                        logger.debug(f"忽略空对象消火栓图块: {e}")
                    else:
                        logger.warning(f"处理消火栓图块时出错: {e}", exc_info=True)
                    continue

            logger.info(f"消火栓提取完成: 共 {len(self.hydrants)} 个")
            return True

        except Exception as e:
            logger.error(f"提取消火栓数据失败: {e}", exc_info=True)
            return False

    def extract_floors(self, config: dict, collected: dict = None) -> bool:
        """提取楼层对齐点及对应的矩形框"""
        try:
            align_block_name = config.get("align_block_name", "Floorbase")
            align_attr_name = config.get("align_attribute_name", "Elevation")
            tolerance_mm = config.get("tolerance", 10.0)
            tolerance = tolerance_mm * 0.001   # 米

            # 从预收集数据加载
            if collected is not None:
                align_blocks = collected.get('floor_align_blocks', [])
                rect_polylines = collected.get('floor_rect_polylines', [])
            else:
                if not CAD_AVAILABLE or not self.acad:
                    logger.warning("CAD未连接，无法提取楼层信息")
                    return True
                model_space = self.acad.doc.ModelSpace

                align_blocks = []
                for entity in model_space:
                    try:
                        _ = entity.ObjectName
                    except:
                        continue
                    try:
                        if entity.ObjectName != "AcDbBlockReference":
                            continue
                        if entity.Name != align_block_name:
                            continue
                        ins = entity.InsertionPoint
                        point = (ins[0], ins[1], ins[2])
                        layer = entity.Layer
                        handle = entity.Handle
                        align_blocks.append({'point': point, 'layer': layer, 'handle': handle})
                    except Exception as e:
                        logger.debug(f"处理对齐点出错: {e}")

                rect_polylines = []
                for entity in model_space:
                    try:
                        _ = entity.ObjectName
                    except:
                        continue
                    try:
                        if entity.ObjectName not in ("AcDbPolyline", "AcDb2dPolyline"):
                            continue
                        coords = entity.Coordinates
                        if len(coords) == 8:
                            points = [(coords[i], coords[i+1]) for i in range(0, 8, 2)]
                        elif len(coords) == 12:
                            points = [(coords[i], coords[i+1]) for i in range(0, 12, 3)]
                        else:
                            continue
                        if len(points) != 4:
                            continue
                        xs = sorted(set(p[0] for p in points))
                        ys = sorted(set(p[1] for p in points))
                        if len(xs) == 2 and len(ys) == 2:
                            rect_polylines.append({
                                'coords': coords, 'layer': entity.Layer, 'handle': entity.Handle
                            })
                    except Exception as e:
                        logger.debug(f"处理矩形框出错: {e}")

            # 1. 从 align_blocks 收集对齐点（需要读取属性）
            align_points = []
            for blk in align_blocks:
                point = blk['point']
                layer = blk['layer']
                handle = blk['handle']
                attr_value = self.get_block_attributes_direct(handle, align_attr_name)
                if not attr_value:
                    logger.warning(f"对齐点 {handle} 未读取到属性 {align_attr_name}，跳过")
                    continue
                align_points.append((point, layer, attr_value, handle))

            if not align_points:
                logger.warning("未找到任何对齐点图块")
                return False

            # 2. 按图层分组，找出每个图层中的矩形框
            rects_by_layer = {}
            for poly in rect_polylines:
                coords = poly['coords']
                layer = poly['layer']
                if len(coords) == 8:
                    points = [(coords[i], coords[i+1]) for i in range(0, 8, 2)]
                elif len(coords) == 12:
                    points = [(coords[i], coords[i+1]) for i in range(0, 12, 3)]
                else:
                    continue
                if len(points) != 4:
                    continue
                xs = sorted(set(p[0] for p in points))
                ys = sorted(set(p[1] for p in points))
                if len(xs) == 2 and len(ys) == 2:
                    rect_min = (xs[0], ys[0])
                    rect_max = (xs[1], ys[1])
                    if layer not in rects_by_layer:
                        rects_by_layer[layer] = []
                    rects_by_layer[layer].append((rect_min, rect_max, poly['handle']))

            # 3. 匹配对齐点与矩形框（相同图层，且插入点在矩形框角点容差内）
            floors = []
            for (point, layer, attr_value, handle) in align_points:
                rects = rects_by_layer.get(layer, [])
                matched_rect = None
                for rect_min, rect_max, rect_handle in rects:
                    # 检查插入点是否与矩形某个角点重合（容差内）
                    corners = [rect_min, (rect_min[0], rect_max[1]), rect_max, (rect_max[0], rect_min[1])]
                    for corner in corners:
                        dx = point[0] - corner[0]
                        dy = point[1] - corner[1]
                        if math.hypot(dx, dy) < tolerance:
                            matched_rect = (rect_min, rect_max)
                            break
                    if matched_rect:
                        break
                if not matched_rect:
                    logger.warning(f"对齐点 {handle} 所在图层 {layer} 未找到匹配矩形框，跳过")
                    continue

                # 解析属性值：支持两种格式
                attr_str = attr_value.strip()
                if '_' not in attr_str:
                    logger.warning(f"对齐点属性值格式错误（缺少下划线）: {attr_str}，跳过")
                    continue
                
                # 判断是否为多楼层合一（包含'&'）
                if '&' in attr_str:
                    # 多楼层合一格式
                    parts = attr_str.rsplit('_', 1)
                    if len(parts) != 2:
                        logger.warning(f"多楼层属性格式错误: {attr_str}")
                        continue
                    range_name = parts[0]        # 如 "一至四层"
                    elevs_str = parts[1]         # 如 "0.00&4.50&8.50&12.50"
                    try:
                        elev_list = [float(e) for e in elevs_str.split('&')]
                    except ValueError:
                        logger.warning(f"标高值解析失败: {elevs_str}")
                        continue
                    # 解析范围名称得到楼层数字列表
                    try:
                        floor_numbers = parse_floor_range(range_name)
                    except Exception as e:
                        logger.warning(f"解析楼层范围失败 {range_name}: {e}")
                        continue
                    if len(floor_numbers) != len(elev_list):
                        logger.warning(f"楼层数量({len(floor_numbers)})与标高数量({len(elev_list)})不匹配: {range_name}")
                        continue
                    # 生成实际楼层名称列表（中文或数字）
                    actual_names = []
                    # 判断原范围名第一个字符是否为数字（决定输出数字还是中文）
                    if range_name[0].isdigit():
                        for n in floor_numbers:
                            actual_names.append(f"{n}层")
                    else:
                        for n in floor_numbers:
                            actual_names.append(f"{int_to_chinese(n)}层")
                    # 创建临时楼层，存储多楼层信息
                    floor = FloorData(
                        name=range_name,           # 临时名称
                        elevation=elev_list[0],    # 临时用首层标高
                        align_point=point,
                        rect_min=matched_rect[0],
                        rect_max=matched_rect[1],
                        layer=layer
                    )
                    floor._multi_floor_info = {
                        "type": "group",
                        "actual_names": actual_names,
                        "elevations": elev_list,
                        "range_name": range_name
                    }
                    floors.append(floor)
                else:
                    # 原有单楼层逻辑
                    last_underscore = attr_str.rfind('_')
                    name_part = attr_str[:last_underscore]
                    elev_part = attr_str[last_underscore+1:]
                    try:
                        elevation = float(elev_part)
                    except ValueError:
                        logger.warning(f"对齐点标高解析失败: {elev_part}，跳过")
                        continue
                    floor = FloorData(
                        name=name_part,
                        elevation=elevation,
                        align_point=point,
                        rect_min=matched_rect[0],
                        rect_max=matched_rect[1],
                        layer=layer
                    )
                    floors.append(floor)

            if not floors:
                logger.warning("未成功匹配到任何楼层")
                return False

            # 4. 检查重复标高和标高差过小
            elev_map = {}
            for f in floors:
                if f.elevation in elev_map:
                    logger.error(f"发现重复标高 {f.elevation}m: 楼层 {f.name} 与 {elev_map[f.elevation]}")
                    messagebox.showerror("楼层错误", f"多个楼层具有相同标高 {f.elevation}m，程序终止。")
                    return False
                elev_map[f.elevation] = f.name

            # 检查标高差小于1m的相邻楼层（按标高排序）
            sorted_floors = sorted(floors, key=lambda x: x.elevation)
            for i in range(len(sorted_floors)-1):
                diff = sorted_floors[i+1].elevation - sorted_floors[i].elevation
                if diff < 1.0 and diff > 0:
                    msg = f"楼层 '{sorted_floors[i].name}' (标高{sorted_floors[i].elevation}m) 与 " \
                          f"'{sorted_floors[i+1].name}' (标高{sorted_floors[i+1].elevation}m) 标高差仅 {diff:.2f}m，可能异常。\n是否继续？"
                    if not messagebox.askyesno("警告", msg):
                        return False
                    break   # 只询问一次

            self.floors = sorted_floors
            self.floor_by_name = {f.name: f for f in self.floors}
            logger.info(f"成功提取 {len(self.floors)} 个楼层")
            return True

        except Exception as e:
            logger.error(f"提取楼层信息失败: {e}", exc_info=True)
            return False

    def assign_pipes_to_floors(self):
        """将管道分配到各楼层矩形框内（基于节点xy坐标）"""
        if not self.floors:
            return

        # 清空楼层中的旧数据
        for floor in self.floors:
            floor.pipes.clear()
            floor.nodes.clear()
            floor.hydrants.clear()

        # 辅助函数：判断点是否在矩形内
        def point_in_rect(x, y, rect_min, rect_max):
            return rect_min[0] <= x <= rect_max[0] and rect_min[1] <= y <= rect_max[1]

        # 为每个管道分配楼层：管道两个端点都在同一楼层矩形内才归属该楼层
        # 如果只有一个端点在矩形内，仍然归属（用户承担风险）
        for pipe in self.pipes:
            start = pipe.start_point
            end = pipe.end_point
            assigned_floor = None
            for floor in self.floors:
                start_in = point_in_rect(start[0], start[1], floor.rect_min, floor.rect_max)
                end_in = point_in_rect(end[0], end[1], floor.rect_min, floor.rect_max)
                if start_in or end_in:
                    assigned_floor = floor
                    break
            if assigned_floor:
                assigned_floor.pipes.append(pipe)
            else:
                logger.debug(f"管道 {pipe.pipe_id} 未落入任何楼层矩形，将忽略")

        # 收集每个楼层的节点（从分配到该楼层的管道端点中收集）
        for floor in self.floors:
            node_ids = set()
            for pipe in floor.pipes:
                node_ids.add(pipe.start_node_id)
                node_ids.add(pipe.end_node_id)
            for nid in node_ids:
                node = self.node_by_id.get(nid)
                if node:
                    floor.nodes.append(node)
            logger.info(f"楼层 {floor.name}: {len(floor.pipes)} 条管道, {len(floor.nodes)} 个节点")

        # 分配立管到楼层（基于圆心坐标是否在楼层矩形内）
        for riser in self.risers:
            riser.floor_name = ""
            for floor in self.floors:
                if (floor.rect_min[0] <= riser.x <= floor.rect_max[0] and
                    floor.rect_min[1] <= riser.y <= floor.rect_max[1]):
                    riser.floor_name = floor.name
                    break

        # 分配阀门到楼层（通过管道关联）
        for valve in self.valves:
            valve.floor_name = ""
            if valve.pipe_id and valve.pipe_id in self.pipe_by_id:
                pipe = self.pipe_by_id[valve.pipe_id]
                for floor in self.floors:
                    if pipe in floor.pipes:
                        valve.floor_name = floor.name
                        break

        # 分配消火栓到楼层（基于坐标矩形，不依赖节点）
        for hydrant in self.hydrants:
            hydrant.floor_name = ""
            for floor in self.floors:
                if (floor.rect_min[0] <= hydrant.x <= floor.rect_max[0] and
                    floor.rect_min[1] <= hydrant.y <= floor.rect_max[1]):
                    hydrant.floor_name = floor.name
                    floor.hydrants.append(hydrant)
                    break
            if not hydrant.floor_name:
                logger.warning(f"消火栓 {hydrant.hydrant_id} 坐标 ({hydrant.x:.1f},{hydrant.y:.1f}) 不在任何楼层矩形内")

    def align_floors_to_baseline(self):
        """将所有楼层对齐到基准楼层（一层或最低标高楼层）的xy坐标"""
        if not self.floors:
            return

        # 寻找基准楼层：名称包含"一层"或标高为0.00，否则取最低标高
        baseline = None
        for f in self.floors:
            if f.name == "一层" or abs(f.elevation) < 0.01:
                baseline = f
                break
        if baseline is None:
            baseline = min(self.floors, key=lambda x: x.elevation)
        logger.info(f"基准楼层: {baseline.name}, 标高 {baseline.elevation}m")

        base_x, base_y = baseline.align_point[0], baseline.align_point[1]

        # 对每个非基准楼层，计算偏移量，平移该楼层所有节点的坐标
        for floor in self.floors:
            if floor is baseline:
                continue
            dx = base_x - floor.align_point[0]
            dy = base_y - floor.align_point[1]
            if abs(dx) < 0.001 and abs(dy) < 0.001:
                continue
            logger.info(f"平移楼层 {floor.name}: 偏移 ({dx:.2f}, {dy:.2f}) 毫米")
            for node in floor.nodes:
                node.x += dx
                node.y += dy
            # 同时更新管道端点坐标（因为节点已变，管道端点坐标应同步）
            for pipe in floor.pipes:
                start_node = self.node_by_id.get(pipe.start_node_id)
                end_node = self.node_by_id.get(pipe.end_node_id)
                if start_node:
                    pipe.start_point = (start_node.x, start_node.y, pipe.start_point[2])
                if end_node:
                    pipe.end_point = (end_node.x, end_node.y, pipe.end_point[2])
            # 平移该楼层内的立管
            for riser in self.risers:
                if riser.floor_name == floor.name:
                    riser.x += dx
                    riser.y += dy
            # 平移该楼层内的阀门
            for valve in self.valves:
                if valve.floor_name == floor.name:
                    valve.x += dx
                    valve.y += dy
            # 平移该楼层内的消火栓
            for hydrant in self.hydrants:
                if hydrant.floor_name == floor.name:
                    hydrant.x += dx
                    hydrant.y += dy

            # 更新对齐点坐标（保持记录）
            floor.align_point = (floor.align_point[0] + dx, floor.align_point[1] + dy, floor.align_point[2])
            floor.rect_min = (floor.rect_min[0] + dx, floor.rect_min[1] + dy)
            floor.rect_max = (floor.rect_max[0] + dx, floor.rect_max[1] + dy)

        # 注意：所有节点坐标已修改，需要重新建立 node_by_id 索引（如果必要）
        self.node_by_id = {node.node_id: node for node in self.nodes}

    def assign_node_z_coordinates(self, config: dict, default_offset: float = 0.8, top_offset: float = 3.0):
        """
        根据楼层标高和管道与上层楼面标高差计算每个节点的Z坐标（毫米）
        default_offset: 管道与上层楼面标高差（米），默认0.8
        top_offset: 最高层无上层时，楼面标高加上此值（米），默认3.0
        """
        if not self.floors:
            return

        drawing_unit = config.get("drawing_unit", "毫米")
        unit_factor = self.unit_factors.get(drawing_unit, 0.001)  # 米到毫米的转换因子
        # 实际上我们需要将标高（米）转换为毫米：乘以 1000/unit_factor ？
        # 更简单：如果画图单位是毫米，标高乘1000；厘米乘100；米乘1。
        to_mm = 1.0
        if drawing_unit == "毫米":
            to_mm = 1000.0
        elif drawing_unit == "厘米":
            to_mm = 10.0
        else:  # 米
            to_mm = 1.0

        # 按标高从低到高排序
        sorted_floors = sorted(self.floors, key=lambda x: x.elevation)
        # 构建上层标高映射
        for idx, floor in enumerate(sorted_floors):
            if idx == len(sorted_floors) - 1:
                # 最高层：没有上层
                pipe_z_m = floor.elevation + top_offset
            else:
                upper_floor = sorted_floors[idx + 1]
                pipe_z_m = upper_floor.elevation - default_offset
            floor.pipe_z_offset = pipe_z_m   # 存储本层管网标高（米）
            # 为楼层内所有节点设置Z坐标
            z_mm = pipe_z_m * to_mm
            for node in floor.nodes:
                node.z = z_mm
            logger.info(f"楼层 {floor.name}: 楼面标高 {floor.elevation}m -> 管网标高 {pipe_z_m:.3f}m")


        # 重新计算管道的长度（因为节点Z可能改变）
        for pipe in self.pipes:
            start_node = self.node_by_id.get(pipe.start_node_id)
            end_node = self.node_by_id.get(pipe.end_node_id)
            if start_node and end_node:
                pipe.start_point = (pipe.start_point[0], pipe.start_point[1], start_node.z)
                pipe.end_point = (pipe.end_point[0], pipe.end_point[1], end_node.z)
                dx = pipe.end_point[0] - pipe.start_point[0]
                dy = pipe.end_point[1] - pipe.start_point[1]
                dz = pipe.end_point[2] - pipe.start_point[2]
                pipe.raw_length = math.hypot(dx, dy, dz)
                pipe.length = pipe.raw_length * unit_factor

        # 重新建立节点索引，确保坐标更新
        self.node_by_id = {node.node_id: node for node in self.nodes}
        
        # 同步阀门的 Z 坐标（根据所在管道的端点 Z 和 distance_on_pipe）
        for valve in self.valves:
            if valve.pipe_id and valve.pipe_id in self.pipe_by_id:
                pipe = self.pipe_by_id[valve.pipe_id]
                start_node = self.node_by_id.get(pipe.start_node_id)
                end_node = self.node_by_id.get(pipe.end_node_id)
                if start_node and end_node:
                    t = valve.distance_on_pipe
                    new_z = start_node.z + t * (end_node.z - start_node.z)
                    valve.z = new_z

    def _expand_multi_floors(self, unit_factor: float):
        """将多楼层合一的临时楼层展开为多个实际楼层，复制所有相关数据"""
        import copy
        new_floors = []
        self.grouped_floors_map = {}   # 供预览模块使用
        
        # 辅助函数：获取下一个可用ID
        def get_next_id(prefix, existing_dict):
            max_num = 0
            for key in existing_dict.keys():
                if key.startswith(prefix):
                    try:
                        num = int(key.split('_')[1])
                        if num > max_num:
                            max_num = num
                    except:
                        pass
            return f"{prefix}_{max_num+1:04d}"
        
        for floor in self.floors:
            if not hasattr(floor, '_multi_floor_info'):
                # 普通楼层直接保留
                new_floors.append(floor)
                continue
            
            info = floor._multi_floor_info
            actual_names = info["actual_names"]
            elevations = info["elevations"]
            range_name = info["range_name"]
            
            # 获取该临时楼层下的原始对象（这些对象是在 assign_pipes_to_floors 中分配进来的）
            source_pipes = floor.pipes[:]
            source_nodes = floor.nodes[:]
            source_valves = [v for v in self.valves if v.floor_name == floor.name]
            source_hydrants = [h for h in self.hydrants if h.floor_name == floor.name]
            source_risers = [r for r in self.risers if r.floor_name == floor.name]
            
            # 记录映射关系
            node_id_map = {}
            pipe_id_map = {}
            valve_id_map = {}
            hydrant_id_map = {}
            riser_id_map = {}
            
            # 第一层：保留临时楼层作为第一层，只修改其名称和标高
            first_name = actual_names[0]
            first_elev = elevations[0]
            floor.name = first_name
            floor.elevation = first_elev
            # 更新已有对象的楼层名
            for node in floor.nodes:
                node_id_map[node.node_id] = node.node_id  # 自身映射
            for pipe in floor.pipes:
                pipe_id_map[pipe.pipe_id] = pipe.pipe_id
            for v in source_valves:
                v.floor_name = first_name
                valve_id_map[v.valve_id] = v.valve_id
            for h in source_hydrants:
                h.floor_name = first_name
                hydrant_id_map[h.hydrant_id] = h.hydrant_id
            for r in source_risers:
                r.floor_name = first_name
                riser_id_map[r.riser_id] = r.riser_id
            new_floors.append(floor)
            
            # 后续楼层：复制
            for idx in range(1, len(actual_names)):
                act_name = actual_names[idx]
                elev = elevations[idx]
                
                # 复制节点（立即添加）
                new_nodes = []
                for n in source_nodes:
                    new_id = get_next_id("N", self.node_by_id)
                    node_id_map[n.node_id] = new_id
                    new_node = copy.copy(n)
                    new_node.node_id = new_id
                    new_node.connected_pipes = []
                    new_node.x = n.x
                    new_node.y = n.y
                    new_node.z = n.z   # 临时，稍后 assign_node_z_coordinates 会重新设置
                    new_node.cad_key = f"{new_node.x:.6f},{new_node.y:.6f},{new_node.z:.6f}"
                    new_nodes.append(new_node)
                    # 立即添加到全局
                    self.nodes.append(new_node)
                    self.node_by_id[new_node.node_id] = new_node
                
                # 复制管道（立即添加）
                new_pipes = []
                for p in source_pipes:
                    new_id = get_next_id("P", self.pipe_by_id)
                    pipe_id_map[p.pipe_id] = new_id
                    new_pipe = copy.copy(p)
                    new_pipe.pipe_id = new_id
                    new_pipe.start_node_id = node_id_map[p.start_node_id]
                    new_pipe.end_node_id = node_id_map[p.end_node_id]
                    new_pipe.start_point = (p.start_point[0], p.start_point[1], p.start_point[2])
                    new_pipe.end_point = (p.end_point[0], p.end_point[1], p.end_point[2])
                    new_pipes.append(new_pipe)
                    # 立即添加到全局
                    self.pipes.append(new_pipe)
                    self.pipe_by_id[new_pipe.pipe_id] = new_pipe
                
                # 更新节点的 connected_pipes
                for new_node in new_nodes:
                    new_node.connected_pipes = []
                for new_pipe in new_pipes:
                    for new_node in new_nodes:
                        if new_node.node_id == new_pipe.start_node_id:
                            new_node.connected_pipes.append(new_pipe.pipe_id)
                        if new_node.node_id == new_pipe.end_node_id:
                            new_node.connected_pipes.append(new_pipe.pipe_id)
                
                # 复制阀门（立即添加）
                new_valves = []
                for v in source_valves:
                    new_id = get_next_id("V", self.valve_by_id)
                    valve_id_map[v.valve_id] = new_id
                    new_valve = copy.copy(v)
                    new_valve.valve_id = new_id
                    new_valve.pipe_id = pipe_id_map.get(v.pipe_id, v.pipe_id)
                    new_valve.floor_name = act_name
                    new_valves.append(new_valve)
                    # 立即添加到全局
                    self.valves.append(new_valve)
                    self.valve_by_id[new_valve.valve_id] = new_valve
                
                # 复制消火栓（立即添加）
                new_hydrants = []
                for h in source_hydrants:
                    new_id = get_next_id("H", self.hydrant_by_id)
                    hydrant_id_map[h.hydrant_id] = new_id
                    new_hyd = copy.copy(h)
                    new_hyd.hydrant_id = new_id
                    new_hyd.node_id = node_id_map.get(h.node_id, h.node_id)
                    new_hyd.floor_name = act_name
                    new_hydrants.append(new_hyd)
                    # 立即添加到全局
                    self.hydrants.append(new_hyd)
                    self.hydrant_by_id[new_hyd.hydrant_id] = new_hyd
                    # 更新新节点的 hydrants 列表（需要确保目标节点已在全局中）
                    target_node = self.node_by_id.get(new_hyd.node_id)
                    if target_node and new_hyd.hydrant_id not in target_node.hydrants:
                        target_node.hydrants.append(new_hyd.hydrant_id)
                
                # 复制立管（立即添加）
                new_risers = []
                for r in source_risers:
                    new_id = get_next_id("R", self.riser_by_id)
                    riser_id_map[r.riser_id] = new_id
                    new_riser = copy.copy(r)
                    new_riser.riser_id = new_id
                    new_riser.floor_name = act_name
                    if r.connected_node_id:
                        new_riser.connected_node_id = node_id_map.get(r.connected_node_id, "")
                    if r.top_node_id:
                        new_riser.top_node_id = node_id_map.get(r.top_node_id, "")
                    if r.bottom_node_id:
                        new_riser.bottom_node_id = node_id_map.get(r.bottom_node_id, "")
                    new_risers.append(new_riser)
                    # 立即添加到全局
                    self.risers.append(new_riser)
                    self.riser_by_id[new_riser.riser_id] = new_riser
                
                # 创建新楼层对象
                new_floor = FloorData(
                    name=act_name,
                    elevation=elev,
                    align_point=floor.align_point,
                    rect_min=floor.rect_min,
                    rect_max=floor.rect_max,
                    layer=floor.layer
                )
                new_floor.pipes = new_pipes
                new_floor.nodes = new_nodes
                new_floors.append(new_floor)
                
            # 记录分组映射
            self.grouped_floors_map[range_name] = actual_names
        
        # 替换楼层列表
        self.floors = new_floors
        self.floor_by_name = {f.name: f for f in self.floors}
        
        # 清理临时属性
        for f in self.floors:
            if hasattr(f, '_multi_floor_info'):
                delattr(f, '_multi_floor_info')
        
        logger.info(f"多楼层展开完成，现有楼层数: {len(self.floors)}")

    def check_clearance(self, config: dict) -> bool:
        """
        检测立管中心距和平行横管间距是否小于150mm。
        如果发现冲突，弹出对话框让用户选择终止或继续。
        返回 True 表示可以继续，False 表示终止读取。
        """
        import math
        from tkinter import messagebox
        
        tolerance_mm = 150.0  # 150mm
        conflicts = []
        
        # 1. 检查立管中心距
        if self.floors:
            for floor in self.floors:
                risers_in_floor = [r for r in self.risers if r.floor_name == floor.name]
                n = len(risers_in_floor)
                for i in range(n):
                    for j in range(i+1, n):
                        r1 = risers_in_floor[i]
                        r2 = risers_in_floor[j]
                        dist = math.hypot(r1.x - r2.x, r1.y - r2.y)
                        if dist < tolerance_mm:
                            conflicts.append(f"楼层 '{floor.name}' 立管 {r1.riser_id} 与 {r2.riser_id} 中心距 {dist:.1f}mm < 150mm")
        
        # 2. 检查平行横管间距
        def min_distance_between_segments(p1, p2, q1, q2):
            # 线段间最短距离（保留原实现）
            def seg_pt_dist(a, b, pt):
                abx = b[0] - a[0]
                aby = b[1] - a[1]
                t = ((pt[0]-a[0])*abx + (pt[1]-a[1])*aby) / (abx*abx + aby*aby) if (abx*abx+aby*aby) > 0 else 0
                t = max(0, min(1, t))
                proj_x = a[0] + t*abx
                proj_y = a[1] + t*aby
                return math.hypot(pt[0]-proj_x, pt[1]-proj_y)
            
            d1 = seg_pt_dist(p1, p2, q1)
            d2 = seg_pt_dist(p1, p2, q2)
            d3 = seg_pt_dist(q1, q2, p1)
            d4 = seg_pt_dist(q1, q2, p2)
            return min(d1, d2, d3, d4)

        if self.floors:
            for floor in self.floors:
                pipes_in_floor = floor.pipes
                n = len(pipes_in_floor)
                for i in range(n):
                    for j in range(i+1, n):
                        pipe1 = pipes_in_floor[i]
                        pipe2 = pipes_in_floor[j]
                        
                        # 新增：排除共用节点的情况（避免相邻管道误判）
                        # 检查是否共享端点（容差内）
                        def points_equal(p1, p2):
                            return math.hypot(p1[0]-p2[0], p1[1]-p2[1]) < tolerance_mm
                        # 获取端点坐标（毫米）
                        p1_start = (pipe1.start_point[0], pipe1.start_point[1])
                        p1_end   = (pipe1.end_point[0], pipe1.end_point[1])
                        p2_start = (pipe2.start_point[0], pipe2.start_point[1])
                        p2_end   = (pipe2.end_point[0], pipe2.end_point[1])
                        if (points_equal(p1_start, p2_start) or points_equal(p1_start, p2_end) or
                            points_equal(p1_end, p2_start) or points_equal(p1_end, p2_end)):
                            continue  # 共用节点，跳过间距检测
                        
                        # 判断是否平行（方向夹角小于5度）
                        dx1 = pipe1.end_point[0] - pipe1.start_point[0]
                        dy1 = pipe1.end_point[1] - pipe1.start_point[1]
                        dx2 = pipe2.end_point[0] - pipe2.start_point[0]
                        dy2 = pipe2.end_point[1] - pipe2.start_point[1]
                        len1 = math.hypot(dx1, dy1)
                        len2 = math.hypot(dx2, dy2)
                        if len1 < 1e-6 or len2 < 1e-6:
                            continue
                        dot = dx1*dx2 + dy1*dy2
                        cos_angle = dot / (len1 * len2)
                        angle = math.degrees(math.acos(max(-1, min(1, cos_angle))))
                        if angle > 5.0 and angle < 175.0:
                            continue
                        # 平行，计算间距
                        p1 = (pipe1.start_point[0], pipe1.start_point[1])
                        p2 = (pipe1.end_point[0], pipe1.end_point[1])
                        q1 = (pipe2.start_point[0], pipe2.start_point[1])
                        q2 = (pipe2.end_point[0], pipe2.end_point[1])
                        dist = min_distance_between_segments(p1, p2, q1, q2)
                        if dist < 150.0:
                            conflicts.append(f"楼层 '{floor.name}' 管道 {pipe1.pipe_id} 与 {pipe2.pipe_id} 平行间距 {dist:.1f}mm < 150mm")

        if not conflicts:
            return True
        
        # 构建冲突信息
        conflict_msg = "检测到以下间距小于150mm的冲突：\n" + "\n".join(conflicts[:10])
        if len(conflicts) > 10:
            conflict_msg += f"\n... 还有 {len(conflicts)-10} 处冲突"
        conflict_msg += "\n\n是否继续读取？（终止将取消加载）"
        
        result = messagebox.askyesno("间距冲突警告", conflict_msg)
        if result:
            # 用户选择“是” -> 继续
            logger.warning(f"用户选择继续读取，忽略 {len(conflicts)} 处间距冲突")
            return True
        else:
            # 用户选择“否” -> 终止
            logger.error(f"用户终止读取，共发现 {len(conflicts)} 处间距冲突")
            return False

    def check_duplicate_risers_in_floor(self):
        """检查同一楼层内是否有相同编号的立管，收集重复立管但不终止程序"""
        if not self.floors:
            return True
        # 重置存储
        self.duplicate_risers_by_floor = {}
        # 按楼层分组
        risers_by_floor = {}
        for riser in self.risers:
            if riser.floor_name:
                if riser.floor_name not in risers_by_floor:
                    risers_by_floor[riser.floor_name] = []
                risers_by_floor[riser.floor_name].append(riser)
        
        # 检查每个楼层内的重复编号
        for floor_name, riser_list in risers_by_floor.items():
            # 按编号分组
            number_to_risers = {}
            for riser in riser_list:
                num = riser.note_number
                if not num:
                    continue
                if num not in number_to_risers:
                    number_to_risers[num] = []
                number_to_risers[num].append(riser)
            
            # 收集重复编号的立管（出现次数 > 1）
            duplicate_in_floor = []
            for num, risers in number_to_risers.items():
                if len(risers) > 1:
                    logger.warning(f"楼层 {floor_name} 中发现重复立管编号 {num}: 共 {len(risers)} 个")
                    duplicate_in_floor.extend(risers)
            
            if duplicate_in_floor:
                self.duplicate_risers_by_floor[floor_name] = duplicate_in_floor
        
        return True

    def match_hydrants_with_nodes(self, tolerance_mm: float):
        """将消火栓匹配到最近的节点"""
        tolerance = tolerance_mm * 0.001  # 转换为米
        matched_count = 0
        for hydrant in self.hydrants:
            point = (hydrant.x, hydrant.y, hydrant.z)
            node = self._find_nearest_node(point, tolerance)
            if node:
                hydrant.node_id = node.node_id
                if hydrant.hydrant_id not in node.hydrants:
                    node.hydrants.append(hydrant.hydrant_id)
                matched_count += 1
                logger.debug(f"消火栓 {hydrant.hydrant_id} 匹配到节点 {node.node_id}")
            else:
                logger.debug(f"消火栓 {hydrant.hydrant_id} 未能匹配到节点")
        logger.info(f"消火栓匹配完成: {matched_count}/{len(self.hydrants)} 匹配成功")

    def match_valves_with_pipes(self, tolerance_mm: float):
        """
        将阀门匹配到对应的管道
        """
        try:
            tolerance = tolerance_mm * 0.001  # 转换为米

            logger.info(f"开始匹配阀门与管道，容差: {tolerance_mm}mm")

            matched_count = 0

            for valve in self.valves:
                valve_point = (valve.x, valve.y, valve.z)
                min_distance = float('inf')
                matched_pipe = None
                best_t = 0.0

                # 遍历所有管道
                for pipe in self.pipes:
                    # 计算点到线段的距离（3D）
                    distance, t = self._point_to_line_distance_3d(
                        valve_point,
                        pipe.start_point,
                        pipe.end_point
                    )

                    # 检查是否是最近的管道
                    if distance < min_distance:
                        min_distance = distance
                        matched_pipe = pipe
                        best_t = t

                # 如果找到匹配的管道
                if matched_pipe and min_distance < tolerance:
                    valve.pipe_id = matched_pipe.pipe_id
                    valve.distance_on_pipe = best_t
                    matched_count += 1

                    logger.debug(
                        f"阀门 {valve.valve_id} 匹配到管道 {matched_pipe.pipe_id}, "
                        f"距离: {min_distance*1000:.2f}mm"
                    )
                else:
                    logger.debug(
                        f"阀门 {valve.valve_id} 未能匹配到任何管道 "
                        f"(最近距离: {min_distance*1000:.2f}mm)"
                    )

            logger.info(f"阀门匹配完成: {matched_count}/{len(self.valves)} 匹配成功")

        except Exception as e:
            logger.error(f"匹配阀门与管道失败: {e}")

    def _point_to_line_distance_3d(self, point, line_start, line_end):
        """
        计算点到3D线段的距离和相对位置
        """
        try:
            # 线段方向向量
            dx = line_end[0] - line_start[0]
            dy = line_end[1] - line_start[1]
            dz = line_end[2] - line_start[2]

            # 线段长度平方
            line_length_sq = dx*dx + dy*dy + dz*dz

            if line_length_sq == 0:
                # 线段退化为点
                distance = math.sqrt(
                    (point[0] - line_start[0])**2 +
                    (point[1] - line_start[1])**2 +
                    (point[2] - line_start[2])**2
                )
                return distance, 0.0

            # 计算投影参数 t
            t = (
                (point[0] - line_start[0]) * dx +
                (point[1] - line_start[1]) * dy +
                (point[2] - line_start[2]) * dz
            ) / line_length_sq

            # 限制 t 在 [0, 1] 范围内
            t = max(0.0, min(1.0, t))

            # 计算投影点
            proj_x = line_start[0] + t * dx
            proj_y = line_start[1] + t * dy
            proj_z = line_start[2] + t * dz

            # 计算距离（3D）
            distance = math.sqrt(
                (point[0] - proj_x)**2 +
                (point[1] - proj_y)**2 +
                (point[2] - proj_z)**2
            )

            return distance, t

        except Exception as e:
            logger.error(f"计算3D距离失败: {e}")
            return float('inf'), 0.0

    def write_back_to_cad(self, element_type: str, elements=None) -> tuple:
        """
        将数据写回CAD

        Returns:
            tuple: (成功数, 失败数, 错误信息, 是否需要重新加载)
        """
        try:
            # ✅ 强制检查和重建连接
            if not self.acad:
                return (0, 0, "CAD未初始化", False)

            # 尝试访问文档，如果失败则重新连接
            try:
                _ = self.acad.doc.Name
            except:
                logger.warning("CAD连接已失效，尝试重新连接...")
                try:
                    # 清空旧连接
                    self.acad = None
                    pythoncom.CoUninitialize()

                    # 重新初始化
                    import time
                    time.sleep(0.5)
                    pythoncom.CoInitialize()
                    self.acad = Autocad()

                    # 验证连接
                    _ = self.acad.doc.Name
                    logger.info("CAD连接已恢复")
                except Exception as reconnect_error:
                    logger.error(f"无法重新连接CAD: {reconnect_error}")
                    return (0, 0, "无法连接到AutoCAD，请确保已打开对应的CAD文件", False)

            success_count = 0
            fail_count = 0
            error_list = []

            model_space = self.acad.doc.ModelSpace

            if element_type == "pipes":
                elements = elements or self.pipes
                for pipe in elements:
                    try:
                        self._write_pipe_to_cad_safe(model_space, pipe)
                        success_count += 1
                    except Exception as e:
                        fail_count += 1
                        error_list.append(f"{pipe.pipe_id}")
                        logger.debug(f"管道 {pipe.pipe_id} 反写失败: {e}")

            elif element_type == "nodes":
                elements = elements or self.nodes
                for node in elements:
                    try:
                        self._write_node_to_cad_safe(model_space, node)
                        success_count += 1
                    except Exception as e:
                        fail_count += 1
                        error_list.append(f"{node.node_id}")
                        logger.debug(f"节点 {node.node_id} 反写失败: {e}")

            elif element_type == "valves":
                elements = elements or self.valves
                for valve in elements:
                    try:
                        self._write_valve_to_cad_safe(model_space, valve)
                        success_count += 1
                    except Exception as e:
                        fail_count += 1
                        error_list.append(f"{valve.valve_id}")
                        logger.debug(f"阀门 {valve.valve_id} 反写失败: {e}")

            # 生成消息
            if success_count > 0:
                message = f"成功反写 {success_count} 个{element_type}"
                logger.info(message)
                return (success_count, fail_count, message, False)
            else:
                message = f"反写失败，请检查CAD文件是否已打开"
                logger.error(message)
                return (0, fail_count, message, False)

        except Exception as e:
            logger.error(f"反写异常: {e}", exc_info=True)
            return (0, 0, f"反写异常: {str(e)}", False)

    def _write_pipe_to_cad_safe(self, model_space, pipe: PipeData):
        """安全的写回管道 - 修正箭头逻辑"""
        try:
            # 判断是否来自计算页面
            is_from_calculation = hasattr(pipe, 'display_text')
            
            if is_from_calculation:
                # 计算页面反写：两行文字
                data_line = pipe.display_text
                flow_value = getattr(pipe, 'flow_value', 0.0)
                show_arrow = getattr(pipe, 'show_arrow', False)
                
                # 计算管道方向
                dx = pipe.end_point[0] - pipe.start_point[0]
                dy = pipe.end_point[1] - pipe.start_point[1]
                
                # 计算管道方向角度（从起点指向终点）
                pipe_angle = math.degrees(math.atan2(dy, dx)) if dx != 0 or dy != 0 else 0.0
                
                # 将角度归一化到0-360度
                if pipe_angle < 0:
                    pipe_angle += 360
                
                # 计算管道中点
                mid_x = (pipe.start_point[0] + pipe.end_point[0]) / 2
                mid_y = (pipe.start_point[1] + pipe.end_point[1]) / 2
                mid_z = (pipe.start_point[2] + pipe.end_point[2]) / 2
                
                # 获取文字高度
                text_height = self._get_cad_text_height()
                
                # 计算管道长度和方向向量
                length = math.sqrt(dx*dx + dy*dy) if dx != 0 or dy != 0 else 1.0
                if length > 0:
                    ux = dx / length
                    uy = dy / length
                else:
                    ux, uy = 1.0, 0.0
                
                # 计算管道法向量（垂直于管道方向）
                nx = -uy
                ny = ux
                
                # 计算文字位置偏移（垂直于管道方向，距离等于字高）
                offset_x = nx * text_height
                offset_y = ny * text_height
                
                # 第一行文字位置（数据行）
                data_x = mid_x + offset_x
                data_y = mid_y + offset_y
                data_pos = APoint(data_x, data_y, mid_z)
                
                # 数据行角度：使用管道角度，但需要避免文字倒置
                data_angle = pipe_angle
                if data_angle >= 180:
                    data_angle -= 180  # 避免文字倒置
                
                # 添加数据行文字
                text_obj1 = model_space.AddText(data_line, data_pos, text_height)
                text_obj1.Rotation = math.radians(data_angle)
                text_obj1.Alignment = 10
                text_obj1.TextAlignmentPoint = data_pos
                
                # 添加箭头行（仅当流量不为0且show_arrow为True时）
                if show_arrow and flow_value != 0:
                    # 第二行文字位置（箭头行，在数据行下方一个行高）
                    arrow_x = data_x + nx * text_height
                    arrow_y = data_y + ny * text_height
                    arrow_pos = APoint(arrow_x, arrow_y, mid_z)
                    
                    # 确定箭头方向
                    # 流量为正：箭头方向与管道方向一致
                    # 流量为负：箭头方向与管道方向相反（旋转180度）
                    if flow_value >= 0:
                        arrow_angle = pipe_angle
                    else:
                        arrow_angle = pipe_angle + 180
                        # 归一化到0-360度
                        if arrow_angle >= 360:
                            arrow_angle -= 360
                    
                    # 使用右箭头字符
                    arrow_text = "→"
                    text_obj2 = model_space.AddText(arrow_text, arrow_pos, text_height)
                    text_obj2.Rotation = math.radians(arrow_angle)
                    text_obj2.Alignment = 10
                    text_obj2.TextAlignmentPoint = arrow_pos
                    
                    logger.debug(f"管道 {pipe.pipe_id} 反写箭头: 流量={flow_value}, "
                                f"管道角度={pipe_angle:.1f}°, 箭头角度={arrow_angle:.1f}°")
                
                logger.debug(f"管道反写数据行: {pipe.pipe_id} -> {data_line}")
                
            else:
                # 管道页面反写：一行文字（保持原有逻辑）
                text_content = f"{pipe.pipe_id}_{pipe.nominal_diameter}"
                
                # 计算管道中点
                mid_x = (pipe.start_point[0] + pipe.end_point[0]) / 2
                mid_y = (pipe.start_point[1] + pipe.end_point[1]) / 2
                mid_z = (pipe.start_point[2] + pipe.end_point[2]) / 2
                
                # 计算管道方向
                dx = pipe.end_point[0] - pipe.start_point[0]
                dy = pipe.end_point[1] - pipe.start_point[1]
                
                # 计算管道方向角度
                pipe_angle = math.degrees(math.atan2(dy, dx)) if dx != 0 or dy != 0 else 0.0
                if pipe_angle < 0:
                    pipe_angle += 360
                
                # 避免文字倒置
                text_angle = pipe_angle
                if text_angle >= 180:
                    text_angle -= 180
                
                # 获取文字高度
                text_height = self._get_cad_text_height()
                
                # 计算文字位置（简单偏移）
                if abs(dx) > abs(dy):
                    offset_x = 0
                    offset_y = 50
                else:
                    offset_x = 50
                    offset_y = 0
                
                text_x = mid_x + offset_x
                text_y = mid_y + offset_y
                text_pos = APoint(text_x, text_y, mid_z)
                
                # 添加文字到CAD
                text_obj = model_space.AddText(text_content, text_pos, text_height)
                text_obj.Rotation = math.radians(text_angle)
                text_obj.Alignment = 10
                text_obj.TextAlignmentPoint = text_pos
                
                logger.debug(f"管道反写单行: {pipe.pipe_id} -> {text_content}")
                
            return True
            
        except Exception as e:
            logger.error(f"管道反写失败 {pipe.pipe_id}: {e}")
            return False


    def _write_node_to_cad_safe(self, model_space, node: NodeData):
        """安全的写回节点"""
        text_x = node.x + 50
        text_y = node.y + 50
        text_z = node.z

        text_position = APoint(text_x, text_y, text_z)
        text_height = self._get_cad_text_height()

        model_space.AddText(node.node_id, text_position, text_height)

    def _write_valve_to_cad_safe(self, model_space, valve: ValveData):
        """安全的写回阀门"""
        text_x = valve.x + 30
        text_y = valve.y + 30
        text_z = valve.z

        text_position = APoint(text_x, text_y, text_z)
        text_height = self._get_cad_text_height()

        text_obj = model_space.AddText(
            valve.valve_id, text_position, text_height)

        if valve.pipe_id and valve.pipe_id in self.pipe_by_id:
            pipe = self.pipe_by_id[valve.pipe_id]
            if pipe.direction_angle is not None:
                # 获取原始角度
                angle = pipe.direction_angle

                # 将角度归一化到0-360度范围
                angle = angle % 360

                # 如果角度大于等于180度，减去180度，避免字体倒置
                if angle >= 180:
                    angle -= 180

                # 应用旋转角度
                text_obj.Rotation = math.radians(angle)

    def _get_cad_text_height(self) -> float:
        """获取CAD当前文字高度"""
        try:
            if self.acad and self.acad.doc:
                text_style = self.acad.doc.ActiveTextStyle
                if hasattr(text_style, 'Height') and text_style.Height > 0:
                    return text_style.Height
        except:
            pass

        return 2.5  # 默认高度

    def export_to_dataframe(self, element_type: str) -> pd.DataFrame:
        """
        导出数据为DataFrame
        """
        try:
            if element_type == "pipes":
                data = [{
                    "管段ID": pipe.pipe_id,
                    "起点节点": pipe.start_node_id,
                    "终点节点": pipe.end_node_id,
                    "公称管径": pipe.nominal_diameter,
                    "内径(mm)": pipe.inner_diameter,
                    "管长(m)": pipe.length,
                    "状态": pipe.status,
                    "管材": pipe.material
                } for pipe in self.pipes]

            elif element_type == "nodes":
                data = [{
                    "节点ID": node.node_id,
                    "状态": node.status,
                    "X坐标": node.x,
                    "Y坐标": node.y,
                    "Z坐标": node.z,
                    "节点类型": node.node_type,
                    "连接管道": ",".join(node.connected_pipes) if node.connected_pipes else ""
                } for node in self.nodes]

            elif element_type == "valves":
                data = [{
                    "阀门ID": valve.valve_id,
                    "所在管道ID": valve.pipe_id,
                    "状态": valve.status,
                    "X坐标": valve.x,
                    "Y坐标": valve.y,
                    "Z坐标": valve.z
                } for valve in self.valves]

            elif element_type == "supply":
                data = [{
                    "供水点组ID": group.group_id,
                    "节点ID列表": ",".join(group.node_ids),
                    "供水压力": group.pressure,
                    "总流量": group.total_flow
                } for group in self.supply_nodes]

            elif element_type == "demand":
                data = []
                for group_id, group in self.demand_groups.items():
                    for node in group.demand_nodes:
                        data.append({
                            "用水点组ID": group_id,
                            "节点ID": node.node_id,
                            "状态": node.status,
                            "流量": node.flow,
                            "压力": node.pressure
                        })
            else:
                logger.error(f"未知的元素类型: {element_type}")
                return pd.DataFrame()

            return pd.DataFrame(data) if data else pd.DataFrame()

        except Exception as e:
            logger.error(f"导出{element_type}数据失败: {e}")
            return pd.DataFrame()

    def load_cache(self):
        """加载缓存数据"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.cache_data = json.load(f)
                logger.info(f"缓存文件已加载: {self.cache_file}")
            else:
                self.cache_data = {}
                logger.info("未找到缓存文件，创建新缓存")
        except Exception as e:
            logger.error(f"加载缓存失败: {e}")
            self.cache_data = {}

    def get_cached_data(self, cache_key: str):
        """获取缓存数据"""
        return self.cache_data.get(cache_key)

    def save_to_cache(self, cache_key: str):
        """保存数据到缓存"""
        try:
            # 构建缓存数据
            cache_entry = {
                "cad_file": self.cad_file_path,
                "timestamp": pd.Timestamp.now().isoformat(),
                "pipes_count": len(self.pipes),
                "nodes_count": len(self.nodes)
            }

            self.cache_data[cache_key] = cache_entry

            # 保存到文件
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache_data, f, ensure_ascii=False, indent=2)

            logger.info(f"数据已保存到缓存: {self.cache_file}")

        except Exception as e:
            logger.error(f"保存缓存失败: {e}")

    def load_from_cache(self, cache_data: dict):
        """从缓存加载数据（实际应该加载完整数据，这里简化）"""
        logger.info(f"从缓存加载数据: {cache_data.get('cad_file')}")
        # 注意：实际应该加载完整的管道、节点等数据
        # 这里只是示例

    def clear_data(self):
        """清空所有数据"""
        self.pipes.clear()
        self.nodes.clear()
        self.supply_nodes.clear()
        self.demand_groups.clear()
        self.valves.clear()
        self.hydrants.clear()
        self.risers.clear()
        self.floors.clear()

        self.pipe_by_id.clear()
        self.node_by_id.clear()
        self.valve_by_id.clear()
        self.hydrant_by_id.clear()
        self.riser_by_id.clear()
        self.floor_by_name.clear()
        self.grouped_floors_map.clear()
        self.duplicate_risers_by_floor.clear()
        self.duplicate_pipe_ids_by_floor.clear()

        self.is_loaded = False
        logger.info("所有数据已清空")

    def clear_all_data(self):
        """清空所有数据（含立管、楼层等，用于导入前完全重置）。"""
        self.pipes.clear()
        self.nodes.clear()
        self.supply_nodes.clear()
        self.demand_groups.clear()
        self.valves.clear()
        self.hydrants.clear()
        self.risers.clear()
        self.floors.clear()

        self.pipe_by_id.clear()
        self.node_by_id.clear()
        self.valve_by_id.clear()
        self.hydrant_by_id.clear()
        self.riser_by_id.clear()
        self.floor_by_name.clear()
        self.grouped_floors_map.clear()
        self.duplicate_risers_by_floor.clear()
        self.duplicate_pipe_ids_by_floor.clear()

        self.is_loaded = False
        self.cad_file_path = None
        self.current_project_dir = None
        self.default_color256_diameter = None
        self.sprinkler_s_node_ids.clear()
        self.sprinkler_k_map.clear()
        self.sprinkler_k_overrides.clear()
        self.manual_dn_pipes.clear()
        logger.info("所有数据已完全清空（含立管、楼层）")

    def get_summary(self) -> dict:
        """获取数据摘要"""
        return {
            "管道数量": len(self.pipes),
            "节点数量": len(self.nodes),
            "供水点组数": len(self.supply_nodes),
            "用水点组数": len(self.demand_groups),
            "阀门数量": len(self.valves),
            "CAD文件": self.cad_file_path,
            "加载状态": self.is_loaded
        }

    def close(self):
        """关闭CAD连接"""
        try:
            # 保存缓存
            if self.cache_data:
                with open(self.cache_file, 'w', encoding='utf-8') as f:
                    json.dump(self.cache_data, f, ensure_ascii=False, indent=2)

            logger.info("CAD数据管理器已关闭")
        except Exception as e:
            logger.error(f"关闭CAD数据管理器时出错: {e}")

    def _ask_user_for_color256_diameter_sync(self):
        """同步弹窗询问用户随层管道的默认管径，返回管径字符串（如 'DN100'）"""
        import threading
        import tkinter as tk
        from tkinter import simpledialog

        result = [None]
        event = threading.Event()

        def ask():
            root = tk._default_root
            if root is None:
                root = tk.Tk()
                root.withdraw()
            dlg = simpledialog.askstring(
                "随层管道管径",
                "检测到颜色为随层（颜色256）的管道，请指定其公称管径（例如 DN100）：",
                initialvalue="DN100",
                parent=root
            )
            result[0] = dlg if dlg else "DN100"
            event.set()

        root = tk._default_root
        if root:
            root.after(0, ask)
        else:
            ask()
        event.wait()
        return result[0]

    def validate_problem_pipes(self) -> set:
        """验证并返回问题管道ID集合
        问题定义：
        1. 管道两端节点都有消火栓（两端均连接消火栓）
        2. 节点有消火栓且连接管道数 > 1（即该节点同时连接多根管道）
        3. 孤立管道：两端节点都只连接了该管道（即两端节点的 connected_pipes 长度均为 1）
        """
        problem_pipes = set()
        # 情况1：两端都有消火栓的管道
        for pipe in self.pipes:
            start_node = self.node_by_id.get(pipe.start_node_id)
            end_node = self.node_by_id.get(pipe.end_node_id)
            if start_node and end_node:
                if start_node.hydrants and end_node.hydrants:
                    problem_pipes.add(pipe.pipe_id)
        # 情况2：节点有消火栓且连接管道数 > 1，则与该节点相连的所有管道都标记为问题
        for node in self.nodes:
            if node.hydrants and len(node.connected_pipes) > 1:
                for pid in node.connected_pipes:
                    problem_pipes.add(pid)
        # 情况3：孤立管道
        for pipe in self.pipes:
            start_node = self.node_by_id.get(pipe.start_node_id)
            end_node = self.node_by_id.get(pipe.end_node_id)
            if start_node and end_node:
                if len(start_node.connected_pipes) == 1 and len(end_node.connected_pipes) == 1:
                    problem_pipes.add(pipe.pipe_id)
        return problem_pipes

    # ==================== 立管提取与匹配 ====================
    def extract_risers(self, config: dict, collected: dict = None) -> bool:
        """提取立管（圆或圆弧）及引出标注 - 基于最近距离匹配"""
        try:
            riser_layers = config.get("riser_layers", [])
            tolerance = config.get("tolerance", 10.0) * 0.001  # 米

            if not riser_layers:
                logger.warning("未设置立管图层，跳过立管提取")
                return True

            # 预收集路径或回退路径
            if collected is not None:
                riser_entities = collected.get('riser_circles', [])
                text_entities = collected.get('riser_texts', [])
                line_raw = collected.get('riser_lines', [])
                line_entities = [{'start': s, 'end': e, 'handle': h} for (s, e, h) in line_raw]
            else:
                if not CAD_AVAILABLE or not self.acad:
                    logger.warning("CAD未连接，无法提取立管")
                    return True

                model_space = self.acad.doc.ModelSpace

                riser_entities = []
                line_entities = []
                text_entities = []

                for entity in model_space:
                    try:
                        _ = entity.ObjectName
                    except:
                        continue
                    try:
                        obj_name = entity.ObjectName
                        layer = entity.Layer
                        riser_note_layers = config.get("riser_note_layers", [])
                        if layer in riser_layers and obj_name in ("AcDbCircle", "AcDbArc"):
                            center = entity.Center
                            riser_entities.append({
                                'center': (center[0], center[1], center[2]),
                                'radius': entity.Radius,
                                'layer': layer,
                                'handle': entity.Handle
                            })
                        elif layer in riser_note_layers and obj_name == "AcDbLine":
                            start = (entity.StartPoint[0], entity.StartPoint[1], entity.StartPoint[2])
                            end = (entity.EndPoint[0], entity.EndPoint[1], entity.EndPoint[2])
                            line_entities.append({'start': start, 'end': end, 'handle': entity.Handle})
                        elif obj_name == "AcDbText":
                            ins = entity.InsertionPoint
                            text_entities.append({
                                'text': entity.TextString,
                                'pos': (ins[0], ins[1], ins[2])
                            })
                    except Exception:
                        continue

            # 创建立管对象
            self.risers.clear()
            self.riser_by_id.clear()
            for idx, ent in enumerate(riser_entities, 1):
                cx, cy, cz = ent['center']
                riser = RiserData(
                    riser_id=f"R_{idx:04d}",
                    x=cx, y=cy, z=cz,
                    radius=ent['radius'],
                    layer=ent['layer'],
                    entity_handle=ent['handle']
                )
                self.risers.append(riser)
                self.riser_by_id[riser.riser_id] = riser

            # 构建立管圆心字典（用于快速匹配）
            riser_centers = {(r.x, r.y, r.z): r for r in self.risers}

            # 处理每条引出线组
            for line1 in line_entities:
                start, end = line1['start'], line1['end']
                matched_riser = None
                free_end = None
                for center, riser in riser_centers.items():
                    if math.hypot(start[0]-center[0], start[1]-center[1]) < tolerance:
                        matched_riser = riser
                        free_end = end
                        break
                    elif math.hypot(end[0]-center[0], end[1]-center[1]) < tolerance:
                        matched_riser = riser
                        free_end = start
                        break
                if not matched_riser:
                    continue

                search_handle = line1['handle']
                second_line = None
                second_free_end = None
                for line2 in line_entities:
                    if line2['handle'] == search_handle:
                        continue
                    s2, e2 = line2['start'], line2['end']
                    if math.hypot(s2[0]-free_end[0], s2[1]-free_end[1]) < tolerance:
                        second_line = line2
                        second_free_end = e2
                        break
                    elif math.hypot(e2[0]-free_end[0], e2[1]-free_end[1]) < tolerance:
                        second_line = line2
                        second_free_end = s2
                        break
                if not second_line:
                    continue

                # 第二根引线的两个端点：pt1 是与第一根引线的连接点（即 free_end），pt2 是远端（second_free_end）
                pt1 = free_end
                pt2 = second_free_end

                # ===== 修改开始：基于引线长度限制搜索半径，并分别从 pt1 和 pt2 各取两个文字（管径+编号） =====
                # 计算第二根引线的长度（pt1 到 pt2 的距离）
                line_len = math.hypot(pt2[0] - pt1[0], pt2[1] - pt1[1])
                # 搜索半径 = 引线长度 * 1.5（至少 50mm，避免线太短时半径过小）
                search_radius = max(line_len * 1.5, 50.0)   # 单位：毫米（坐标是毫米）
                
                # 分别收集 pt1 和 pt2 周围 search_radius 内的文字
                texts_near_pt1 = []
                texts_near_pt2 = []
                for txt in text_entities:
                    pos = txt['pos']
                    dist1 = math.hypot(pos[0] - pt1[0], pos[1] - pt1[1])
                    dist2 = math.hypot(pos[0] - pt2[0], pos[1] - pt2[1])
                    if dist1 <= search_radius:
                        texts_near_pt1.append((dist1, txt))
                    if dist2 <= search_radius:
                        texts_near_pt2.append((dist2, txt))
                
                # 辅助函数：从文字列表中找出一个管径文本和一个编号文本（距离最近的两个）
                def find_pair(texts):
                    # 按距离排序
                    texts.sort(key=lambda x: x[0])
                    dn_text = None
                    num_text = None
                    for dist, txt in texts:
                        if dn_text and num_text:
                            break
                        content = txt['text'].strip()
                        if content.upper().startswith("DN"):
                            if dn_text is None:
                                dn_text = (dist, txt, content)
                        else:
                            if num_text is None and content != "":
                                num_text = (dist, txt, content)
                    return dn_text, num_text
                
                dn1, num1 = find_pair(texts_near_pt1)   # 从 pt1 附近找到的（管径，编号）
                dn2, num2 = find_pair(texts_near_pt2)   # 从 pt2 附近找到的（管径，编号）
                
                note_number = ""
                note_diameter = ""
                
                # 初始化两个变量，供后续偏移量计算使用（默认为 None）
                closest_to_pt1 = None
                closest_to_pt2 = None
                
                # 决策逻辑：选择更可信的那一组（距离 pt1 或 pt2 更近）
                # 情况1：两组都完整（都有管径和编号）
                if dn1 and num1 and dn2 and num2:
                    # 比较 (num1 的距离 + dn1 的距离) 与 (num2 的距离 + dn2 的距离)，取小者
                    score1 = num1[0] + dn1[0]
                    score2 = num2[0] + dn2[0]
                    if score1 <= score2:
                        note_diameter = dn1[2]
                        note_number = num1[2]
                        closest_to_pt2 = dn1[1] if dn1[1] else num1[1]   # 取其中一个文字对象
                    else:
                        note_diameter = dn2[2]
                        note_number = num2[2]
                        closest_to_pt2 = dn2[1] if dn2[1] else num2[1]
                # 情况2：只有 pt1 组完整
                elif dn1 and num1:
                    note_diameter = dn1[2]
                    note_number = num1[2]
                    closest_to_pt2 = dn1[1] if dn1[1] else num1[1]
                # 情况3：只有 pt2 组完整
                elif dn2 and num2:
                    note_diameter = dn2[2]
                    note_number = num2[2]
                    closest_to_pt2 = dn2[1] if dn2[1] else num2[1]
                # 情况4：都不完整，但有单个管径或编号（回退）
                else:
                    # 收集所有候选文字（半径内），按距离排序
                    all_candidates = texts_near_pt1 + texts_near_pt2
                    all_candidates.sort(key=lambda x: x[0])
                    # 取前五个尝试提取
                    for dist, txt in all_candidates[:5]:
                        text = txt['text'].strip()
                        if text.upper().startswith("DN") and not note_diameter:
                            note_diameter = text
                            closest_to_pt2 = txt
                        elif not note_number and text:
                            note_number = text
                            if closest_to_pt2 is None:
                                closest_to_pt2 = txt
                        if note_number and note_diameter:
                            break
                    # 如果仍然缺失，则尝试全局最近的两个文字（不限制半径，但仅作为最后手段）
                    if not note_number or not note_diameter:
                        texts_with_dist = []
                        for txt in text_entities:
                            pos = txt['pos']
                            dist = math.hypot(pos[0] - pt2[0], pos[1] - pt2[1])
                            texts_with_dist.append((dist, txt))
                        texts_with_dist.sort(key=lambda x: x[0])
                        for dist, txt in texts_with_dist[:3]:
                            text = txt['text'].strip()
                            if text.upper().startswith("DN") and not note_diameter:
                                note_diameter = text
                                closest_to_pt2 = txt
                            elif not note_number and text:
                                note_number = text
                                if closest_to_pt2 is None:
                                    closest_to_pt2 = txt
                            if note_number and note_diameter:
                                break
                
                # 如果没有找到任何文字作为 closest_to_pt2，至少用 pt1 或 pt2 附近的第一个文字（避免 None）
                if closest_to_pt2 is None and texts_near_pt2:
                    closest_to_pt2 = texts_near_pt2[0][1]
                elif closest_to_pt2 is None and texts_near_pt1:
                    closest_to_pt2 = texts_near_pt1[0][1]
                # 最后：如果 still None，设置一个虚拟对象，避免后续出错
                if closest_to_pt2 is None:
                    # 创建一个虚拟文字对象，位置为 pt2 本身
                    class DummyText:
                        def __init__(self, pos):
                            self.pos = pos
                    closest_to_pt2 = DummyText(pt2)
                # ===== 修改结束 =====

                # 构建 full_note 并赋值（原样保留）
                if note_diameter and note_number:
                    full_note = f"{note_number}\n{note_diameter}"
                elif note_diameter:
                    full_note = note_diameter
                else:
                    full_note = note_number
                matched_riser.note = full_note
                matched_riser.note_number = note_number
                matched_riser.note_diameter = note_diameter
                matched_riser.nominal_diameter = note_diameter

                # 存储相对于立管圆心的偏移量（使用离 pt2 最近的那个文字的位置作为 note_pos）
                # 优先使用 closest_to_pt2；若没有则用 closest_to_pt1
                note_text = closest_to_pt2 if closest_to_pt2 else closest_to_pt1
                if note_text:
                    note_pos = note_text['pos']
                    matched_riser.note_x = note_pos[0] - matched_riser.x
                    matched_riser.note_y = note_pos[1] - matched_riser.y
                    matched_riser.note_z = note_pos[2] - matched_riser.z
                else:
                    matched_riser.note_x, matched_riser.note_y, matched_riser.note_z = 0, 0, 0

                # logger.info(f"立管 {matched_riser.riser_id} 获得标注: {full_note}")

            logger.info(f"提取立管完成: {len(self.risers)} 个")

            # ------------------ 合并重合的立管（圆心距离小于容差） ------------------
            if not self.risers:
                return True

            # 获取容差（毫米）
            tolerance_mm = config.get("tolerance", 10.0)
            tolerance = tolerance_mm * 0.001  # 转换为米

            # 分组
            groups = []
            used = [False] * len(self.risers)

            for i, riser_i in enumerate(self.risers):
                if used[i]:
                    continue
                group = [riser_i]
                used[i] = True
                for j in range(i+1, len(self.risers)):
                    if used[j]:
                        continue
                    riser_j = self.risers[j]
                    dx = riser_i.x - riser_j.x
                    dy = riser_i.y - riser_j.y
                    if math.hypot(dx, dy) < tolerance:
                        group.append(riser_j)
                        used[j] = True
                groups.append(group)

            # 合并每组立管
            merged_risers = []
            for group in groups:
                if len(group) == 1:
                    merged_risers.append(group[0])
                    continue
                
                # 合并多个重合立管
                base = group[0]
                # 收集标注和管径
                notes = []
                diameters = []
                for r in group:
                    if r.note:
                        notes.append(r.note)
                    if r.nominal_diameter:
                        diameters.append(r.nominal_diameter)
                # 合并标注：优先取第一个有标注的，如果多个不同则拼接
                if notes:
                    # 去重并拼接
                    unique_notes = []
                    for n in notes:
                        if n not in unique_notes:
                            unique_notes.append(n)
                    base.note = " | ".join(unique_notes) if len(unique_notes) > 1 else unique_notes[0]
                # 合并管径：优先取第一个有管径的，如果多个不同则警告并取第一个
                if diameters:
                    unique_diameters = list(set(diameters))
                    if len(unique_diameters) > 1:
                        logger.warning(f"立管 {base.riser_id} 位置({base.x:.2f},{base.y:.2f}) 有多个不同管径 {unique_diameters}，将使用第一个 {unique_diameters[0]}")
                    base.nominal_diameter = unique_diameters[0]
                    # 同步 note_diameter 和 note 中的管径部分（可选）
                    if base.note and "DN" in base.note:
                        # 简单替换 note 中的管径字符串，保持格式
                        base.note = base.note.replace(base.note_diameter, base.nominal_diameter) if base.note_diameter else base.note
                    base.note_diameter = base.nominal_diameter
                # 记录日志
                logger.info(f"合并 {len(group)} 个重合立管为 {base.riser_id}，位置({base.x:.2f},{base.y:.2f})")
                merged_risers.append(base)

            # 替换立管列表和索引
            self.risers = merged_risers
            self.riser_by_id.clear()
            for riser in self.risers:
                self.riser_by_id[riser.riser_id] = riser
            logger.info(f"去重后立管数量: {len(self.risers)}")
            # ------------------ 合并结束 ------------------
            
            return True
        except Exception as e:
            logger.error(f"提取立管失败: {e}", exc_info=True)
            return False

    def match_risers_with_nodes(self, tolerance_mm: float, config: dict):
        """
        将横管端点延伸至立管圆心（不移动立管）
        对于每个立管：
        1. 找出所有与该立管相连的横管端点（直接重合或圆周截断且共线）
        2. 将这些端点的坐标改为立管圆心的坐标，同步更新节点坐标，重新计算管道长度
        3. 对于圆心位于横管中间的情况（垂足在线段内部，且圆心到两端点距离 > 半径+容差），
           在垂足处打断管道，创建新节点，将立管圆心移至垂足
        """
        # 容差（毫米），所有距离计算均使用毫米，避免单位混淆
        tolerance = tolerance_mm  # 毫米
        
        # 获取单位转换因子（用于将CAD单位（毫米/厘米/米）转换为米）
        drawing_unit = config.get("drawing_unit", "毫米")
        unit_factors = {"毫米": 0.001, "厘米": 0.01, "米": 1.0}
        unit_factor = unit_factors.get(drawing_unit, 0.001)

        # 建立节点字典，方便通过节点ID快速获取节点对象
        node_by_id = {node.node_id: node for node in self.nodes}
        # 建立管道列表，包含管道对象、起点坐标、终点坐标、起点节点ID、终点节点ID
        pipe_list = [(pipe, pipe.start_point, pipe.end_point, pipe.start_node_id, pipe.end_node_id) for pipe in self.pipes]

        # 记录成功匹配的管道端点数量（每个端点算一次）
        matched_count = 0

        # 用于存储需要新增的节点和管道（打断操作）
        new_nodes = []
        new_pipes = []
        # 记录需要删除的管道ID
        pipes_to_delete = []

        for riser in self.risers:
            rx, ry, rz = riser.x, riser.y, riser.z          # 立管圆心坐标（毫米）
            radius_mm = riser.radius                        # 立管半径（毫米）

            # 用于存储当前立管需要修改的管道端点信息
            # 每个元素为 (管道对象, 端点类型('start'或'end'), 节点ID)
            modifications = []
            # 用于存储需要打断的管道信息（圆心在管道中间的情况）
            middle_hits = []  # 每个元素为 (管道对象, 垂足坐标, 垂足对应的参数t)

            # 遍历所有管道，找出所有与当前立管相关的管道
            for pipe, start, end, start_nid, end_nid in pipe_list:
                # 先检查端点直接重合或圆周截断
                d_start = math.hypot(start[0] - rx, start[1] - ry)
                d_end = math.hypot(end[0] - rx, end[1] - ry)
                
                # 标记是否已作为端点处理
                endpoint_handled = False
                
                # 检查起点
                if d_start < tolerance:
                    modifications.append((pipe, 'start', start_nid))
                    endpoint_handled = True
                elif d_start <= radius_mm + tolerance:
                    # 圆周截断，检查共线性
                    x1, y1 = pipe.start_point[0], pipe.start_point[1]
                    x2, y2 = pipe.end_point[0], pipe.end_point[1]
                    if not ((x2 - x1) == 0 and (y2 - y1) == 0):
                        A = y2 - y1
                        B = x1 - x2
                        C = x2 * y1 - y2 * x1
                        dist_line = abs(A * rx + B * ry + C) / math.hypot(A, B)
                        if dist_line < tolerance:
                            modifications.append((pipe, 'start', start_nid))
                            endpoint_handled = True
                
                # 检查终点
                if d_end < tolerance:
                    modifications.append((pipe, 'end', end_nid))
                    endpoint_handled = True
                elif d_end <= radius_mm + tolerance:
                    x1, y1 = pipe.start_point[0], pipe.start_point[1]
                    x2, y2 = pipe.end_point[0], pipe.end_point[1]
                    if not ((x2 - x1) == 0 and (y2 - y1) == 0):
                        A = y2 - y1
                        B = x1 - x2
                        C = x2 * y1 - y2 * x1
                        dist_line = abs(A * rx + B * ry + C) / math.hypot(A, B)
                        if dist_line < tolerance:
                            modifications.append((pipe, 'end', end_nid))
                            endpoint_handled = True
                
                # 如果圆心不在端点附近，但圆心到管道的垂直距离小于容差，且垂足在线段内部
                if not endpoint_handled:
                    # 计算圆心到管道的投影参数 t
                    x1, y1 = pipe.start_point[0], pipe.start_point[1]
                    x2, y2 = pipe.end_point[0], pipe.end_point[1]
                    dx = x2 - x1
                    dy = y2 - y1
                    if dx == 0 and dy == 0:
                        continue
                    # 计算 t（0-1范围）
                    t = ((rx - x1) * dx + (ry - y1) * dy) / (dx*dx + dy*dy)
                    if 0 < t < 1:  # 垂足在线段内部，不是端点
                        # 计算垂足坐标
                        foot_x = x1 + t * dx
                        foot_y = y1 + t * dy
                        # 计算圆心到垂足的距离
                        dist_to_foot = math.hypot(rx - foot_x, ry - foot_y)
                        if dist_to_foot < tolerance:
                            # 圆心在管道中间附近，需要打断
                            middle_hits.append((pipe, (foot_x, foot_y), t))
                        elif dist_to_foot <= radius_mm + tolerance:
                            # 再检查共线性（其实垂直距离已经很小，但为了保险）
                            A = y2 - y1
                            B = x1 - x2
                            C = x2 * y1 - y2 * x1
                            dist_line = abs(A * rx + B * ry + C) / math.hypot(A, B)
                            if dist_line < tolerance:
                                middle_hits.append((pipe, (foot_x, foot_y), t))

            # ========== 处理端点修改（直接移动） ==========
            # 手动去重：使用字典，键为 (pipe.pipe_id, endpoint_type) 确保唯一
            unique_mods = {}
            for pipe, endpoint_type, nid in modifications:
                key = (pipe.pipe_id, endpoint_type)
                if key not in unique_mods:
                    unique_mods[key] = (pipe, endpoint_type, nid)
            
            for pipe, endpoint_type, nid in unique_mods.values():
                target_node = node_by_id.get(nid)
                if target_node is None:
                    logger.warning(f"立管 {riser.riser_id} 找不到节点 {nid}")
                    continue
                if endpoint_type == 'start':
                    pipe.start_point = (rx, ry, pipe.start_point[2])
                else:
                    pipe.end_point = (rx, ry, pipe.end_point[2])
                target_node.x = rx
                target_node.y = ry
                # 重新计算管道长度
                dx = pipe.end_point[0] - pipe.start_point[0]
                dy = pipe.end_point[1] - pipe.start_point[1]
                dz = pipe.end_point[2] - pipe.start_point[2]
                pipe.raw_length = math.hypot(dx, dy, dz)
                pipe.length = pipe.raw_length * unit_factor
                riser.connected_node_id = nid
                matched_count += 1
                logger.debug(f"立管 {riser.riser_id} 匹配到管道 {pipe.pipe_id} 的 {endpoint_type} 端点")

            # ========== 处理中间点打断 ==========
            # 去重：同一管道只打断一次
            unique_middle = {}
            for pipe, foot_point, t in middle_hits:
                if pipe.pipe_id not in unique_middle:
                    unique_middle[pipe.pipe_id] = (pipe, foot_point, t)
            
            for pipe, foot_point, t in unique_middle.values():
                foot_x, foot_y = foot_point
                foot_z = pipe.start_point[2]  # 使用管道Z坐标（假设管道水平）
                
                # 创建新节点
                new_node_id = f"N_{len(self.nodes) + len(new_nodes) + 1:04d}"
                new_node = NodeData(
                    node_id=new_node_id,
                    x=foot_x,
                    y=foot_y,
                    z=foot_z,
                    cad_key=f"{foot_x:.6f},{foot_y:.6f},{foot_z:.6f}",
                    connected_pipes=[]
                )
                new_nodes.append(new_node)
                # 临时加入 node_by_id 以便后续使用（在循环结束后会统一更新 self.nodes）
                node_by_id[new_node_id] = new_node
                
                # 创建两段新管道
                # 第一段：从原起点到新节点
                pipe1_id = f"P_{len(self.pipes) + len(new_pipes) + 1:04d}"
                pipe1 = PipeData(
                    pipe_id=pipe1_id,
                    start_node_id=pipe.start_node_id,
                    end_node_id=new_node_id,
                    start_point=pipe.start_point,
                    end_point=(foot_x, foot_y, foot_z),
                    color_code=pipe.color_code,
                    nominal_diameter=pipe.nominal_diameter,
                    inner_diameter=pipe.inner_diameter,
                    material=pipe.material,
                    roughness=pipe.roughness,
                    layer=pipe.layer,
                    entity_handle=pipe.entity_handle
                )
                # 第二段：从新节点到原终点
                pipe2_id = f"P_{len(self.pipes) + len(new_pipes) + 2:04d}"
                pipe2 = PipeData(
                    pipe_id=pipe2_id,
                    start_node_id=new_node_id,
                    end_node_id=pipe.end_node_id,
                    start_point=(foot_x, foot_y, foot_z),
                    end_point=pipe.end_point,
                    color_code=pipe.color_code,
                    nominal_diameter=pipe.nominal_diameter,
                    inner_diameter=pipe.inner_diameter,
                    material=pipe.material,
                    roughness=pipe.roughness,
                    layer=pipe.layer,
                    entity_handle=pipe.entity_handle
                )
                # 重新计算长度
                dx1 = pipe1.end_point[0] - pipe1.start_point[0]
                dy1 = pipe1.end_point[1] - pipe1.start_point[1]
                dz1 = pipe1.end_point[2] - pipe1.start_point[2]
                pipe1.raw_length = math.hypot(dx1, dy1, dz1)
                pipe1.length = pipe1.raw_length * unit_factor
                
                dx2 = pipe2.end_point[0] - pipe2.start_point[0]
                dy2 = pipe2.end_point[1] - pipe2.start_point[1]
                dz2 = pipe2.end_point[2] - pipe2.start_point[2]
                pipe2.raw_length = math.hypot(dx2, dy2, dz2)
                pipe2.length = pipe2.raw_length * unit_factor
                
                new_pipes.append(pipe1)
                new_pipes.append(pipe2)
                
                # 更新原管道两端的节点连接信息
                start_node = node_by_id.get(pipe.start_node_id)
                if start_node:
                    if pipe.pipe_id in start_node.connected_pipes:
                        start_node.connected_pipes.remove(pipe.pipe_id)
                    start_node.connected_pipes.append(pipe1_id)
                end_node = node_by_id.get(pipe.end_node_id)
                if end_node:
                    if pipe.pipe_id in end_node.connected_pipes:
                        end_node.connected_pipes.remove(pipe.pipe_id)
                    end_node.connected_pipes.append(pipe2_id)
                
                # 新节点的连接管道
                new_node.connected_pipes.append(pipe1_id)
                new_node.connected_pipes.append(pipe2_id)
                
                # 标记原管道为待删除
                pipes_to_delete.append(pipe.pipe_id)
                
                # 将立管圆心移动到垂足坐标
                riser.x = foot_x
                riser.y = foot_y
                # 立管关联到新节点
                riser.connected_node_id = new_node_id
                matched_count += 1
                logger.debug(f"立管 {riser.riser_id} 在管道 {pipe.pipe_id} 中间打断，创建新节点 {new_node_id}")

        # ========== 清理被标记的管道，添加新管道和新节点 ==========
        # 删除被标记的管道
        self.pipes = [pipe for pipe in self.pipes if pipe.pipe_id not in pipes_to_delete]
        # 更新 pipe_by_id 索引
        self.pipe_by_id.clear()
        for pipe in self.pipes:
            self.pipe_by_id[pipe.pipe_id] = pipe
        # 添加新管道
        self.pipes.extend(new_pipes)
        for pipe in new_pipes:
            self.pipe_by_id[pipe.pipe_id] = pipe
        # 添加新节点
        self.nodes.extend(new_nodes)
        self.node_by_id.clear()
        for node in self.nodes:
            self.node_by_id[node.node_id] = node

        logger.info(f"立管匹配完成: 共处理 {matched_count} 个管道端点匹配，新增 {len(new_nodes)} 个节点，{len(new_pipes)} 条管道")

    def create_riser_pipes_and_connections(self, config: dict):
        """
        立管处理第一步：将每个立管圆转换为竖向管道（R_开头）
        立管处理第二步：相邻楼层相同编号立管用连接管（L_开头）连接

        注意：下端节点（楼面标高）绝不能加入楼层节点列表，
            否则后续 assign_node_z_coordinates 会将其 Z 覆盖为管网标高，导致竖向管道长度为零。
        """
        if not self.floors or not self.risers:
            return

        # ----- 单位与材质准备 -----
        drawing_unit = config.get("drawing_unit", "毫米")
        to_mm = {"毫米": 1000.0, "厘米": 10.0, "米": 1.0}.get(drawing_unit, 1000.0)
        unit_factor = self.unit_factors.get(drawing_unit, 0.001)
        pipe_material = config.get("pipe_material", "镀锌钢管")
        roughness = self.material_manager.get_roughness(pipe_material)

        # ----- 分离的 ID 计数器 -----
        max_riser_id = max((int(pid.split('_')[1]) for pid in self.pipe_by_id if pid.startswith('R_')), default=0)
        max_link_id  = max((int(pid.split('_')[1]) for pid in self.pipe_by_id if pid.startswith('L_')), default=0)
        max_node_id  = max((int(nid.split('_')[1]) for nid in self.node_by_id), default=0)

        def next_riser_pipe_id():
            nonlocal max_riser_id
            max_riser_id += 1
            return f"R_{max_riser_id:04d}"

        def next_link_pipe_id():
            nonlocal max_link_id
            max_link_id += 1
            return f"L_{max_link_id:04d}"

        def next_node_id():
            nonlocal max_node_id
            max_node_id += 1
            return f"N_{max_node_id:04d}"

        new_pipes = []
        new_nodes = []

        # ----- 第一步：为每个立管创建竖向管道（R_开头） -----
        for riser in self.risers:
            floor = self.floor_by_name.get(riser.floor_name)
            if not floor:
                continue
            # 确保 riser.note_number 有值
            if not riser.note_number and riser.note:
                lines = riser.note.split('\n')
                if lines:
                    riser.note_number = lines[0].strip()
                    if len(lines) > 1:
                        riser.note_diameter = lines[1].strip()
                        riser.nominal_diameter = riser.note_diameter
                        
            z_top    = floor.pipe_z_offset * to_mm      # 管网标高（毫米）
            z_bottom = floor.elevation * to_mm           # 楼面标高（毫米）

            # ---------- 上端节点 ----------
            # 若该立管已通过 match_risers_with_nodes 与横管相连，则复用横管节点
            if riser.connected_node_id and riser.connected_node_id in self.node_by_id:
                top_node = self.node_by_id[riser.connected_node_id]
                # 该节点坐标已在 match 中移至立管圆心，Z 已在 assign 中设为管网标高
            else:
                # 无横管连接，新建上端节点（管网标高）
                top_id = next_node_id()
                top_node = NodeData(
                    node_id=top_id,
                    x=riser.x, y=riser.y, z=z_top,
                    cad_key=f"{riser.x:.6f},{riser.y:.6f},{z_top:.6f}",
                    connected_pipes=[]
                )
                new_nodes.append(top_node)
                self.node_by_id[top_id] = top_node
                # 上端节点属于本层管网，可加入楼层节点（不做要求，此处不加入也不影响）
            riser.top_node_id = top_node.node_id

            # ---------- 下端节点（楼面标高）----------
            bottom_id = next_node_id()
            bottom_node = NodeData(
                node_id=bottom_id,
                x=riser.x, y=riser.y, z=z_bottom,
                cad_key=f"{riser.x:.6f},{riser.y:.6f},{z_bottom:.6f}",
                connected_pipes=[]
            )
            new_nodes.append(bottom_node)
            self.node_by_id[bottom_id] = bottom_node
            riser.bottom_node_id = bottom_id
            # ★ 关键：下端节点绝不能加入 floor.nodes，否则后续 assign_node_z_coordinates 会将其 Z 覆盖为管网标高

            # ---------- 管径 ----------
            dn = riser.nominal_diameter if riser.nominal_diameter else (self.default_color256_diameter or "DN100")
            info = self.material_manager.get_diameter_info(pipe_material, dn)
            inner_d = info.get("inner", 100.0) if info else 100.0
            if not info:
                # 回退到 DN100
                info = self.material_manager.get_diameter_info(pipe_material, "DN100")
                inner_d = info.get("inner", 100.0) if info else 100.0
                dn = "DN100"

            # ---------- 竖向管道（R_开头）----------
            raw_len = abs(z_top - z_bottom)
            pipe_riser = PipeData(
                pipe_id=riser.riser_id,   # 直接使用立管的原ID，确保与 riser_id 一致
                start_node_id=top_node.node_id,
                end_node_id=bottom_node.node_id,
                start_point=(riser.x, riser.y, z_top),
                end_point=(riser.x, riser.y, z_bottom),
                nominal_diameter=dn,
                inner_diameter=inner_d,
                length=raw_len * unit_factor,
                raw_length=raw_len,
                material=pipe_material,
                roughness=roughness,
                layer=riser.layer,
                riser_number=riser.note_number
            )
            new_pipes.append(pipe_riser)
            self.pipe_by_id[pipe_riser.pipe_id] = pipe_riser

            # 更新节点连接关系
            top_node.connected_pipes.append(pipe_riser.pipe_id)
            bottom_node.connected_pipes.append(pipe_riser.pipe_id)

            # 竖向管道加入楼层管道，便于单层预览
            floor.pipes.append(pipe_riser)
            # 上端节点如果是新建且希望出现在楼层节点列表中，可加入（但这不是必须）
            if riser.connected_node_id is None or riser.connected_node_id not in self.node_by_id:
                floor.nodes.append(top_node)

        # 将新节点加入总列表（注意：bottom_node 已包含在 new_nodes 中，但未加入任何楼层）
        self.nodes.extend(new_nodes)

        # ----- 第二步：相邻楼层同编号立管连接（L_开头） -----
        sorted_floors = sorted(self.floors, key=lambda f: f.elevation)
        # 按楼层收集有编号的立管
        risers_by_floor = {}
        for riser in self.risers:
            if riser.note_number:
                risers_by_floor.setdefault(riser.floor_name, []).append(riser)

        for i in range(len(sorted_floors) - 1):
            lower = sorted_floors[i]
            upper = sorted_floors[i + 1]
            lowers = risers_by_floor.get(lower.name, [])
            uppers = risers_by_floor.get(upper.name, [])

            from collections import defaultdict
            lower_by_num = defaultdict(list)
            for r in lowers:
                lower_by_num[r.note_number].append(r)
            upper_by_num = defaultdict(list)
            for r in uppers:
                upper_by_num[r.note_number].append(r)

            common_nums = set(lower_by_num.keys()) & set(upper_by_num.keys())
            for num in common_nums:
                lower_list = lower_by_num[num]
                upper_list = upper_by_num[num]

                # 找出一对 XY 距离最近的立管（仅配一对，其余不连）
                best_pair = None
                min_dist = float('inf')
                for rl in lower_list:
                    for ru in upper_list:
                        d = math.hypot(ru.x - rl.x, ru.y - rl.y)
                        if d < min_dist:
                            min_dist = d
                            best_pair = (ru, rl)

                if not best_pair:
                    continue
                ru, rl = best_pair

                # 上层立管下端节点（楼面标高），下层立管上端节点（管网标高）
                top_node_id = ru.bottom_node_id        # 上层下端
                bottom_node_id = rl.top_node_id        # 下层上端
                if top_node_id not in self.node_by_id or bottom_node_id not in self.node_by_id:
                    continue
                top_node = self.node_by_id[top_node_id]
                bottom_node = self.node_by_id[bottom_node_id]

                # 连接管管径：上层立管管径，无则 DN100
                dn_conn = ru.nominal_diameter if ru.nominal_diameter else (self.default_color256_diameter or "DN100")
                info_conn = self.material_manager.get_diameter_info(pipe_material, dn_conn)
                inner_conn = info_conn.get("inner", 100.0) if info_conn else 100.0

                dx = bottom_node.x - top_node.x
                dy = bottom_node.y - top_node.y
                dz = bottom_node.z - top_node.z
                raw_len = math.hypot(dx, dy, dz)
                pipe_conn = PipeData(
                    pipe_id=next_link_pipe_id(),        # L_开头
                    start_node_id=top_node_id,
                    end_node_id=bottom_node_id,
                    start_point=(top_node.x, top_node.y, top_node.z),
                    end_point=(bottom_node.x, bottom_node.y, bottom_node.z),
                    nominal_diameter=dn_conn,
                    inner_diameter=inner_conn,
                    length=raw_len * unit_factor,
                    raw_length=raw_len,
                    material=pipe_material,
                    roughness=roughness,
                    layer=""                           # 无特定图层
                )
                new_pipes.append(pipe_conn)
                self.pipe_by_id[pipe_conn.pipe_id] = pipe_conn
                top_node.connected_pipes.append(pipe_conn.pipe_id)
                bottom_node.connected_pipes.append(pipe_conn.pipe_id)

        # 将所有新管道加入总列表
        self.pipes.extend(new_pipes)
        logger.info(f"立管管道创建完成：竖向 {max_riser_id} 根，连接 {max_link_id} 根，新增节点 {len(new_nodes)} 个")

    def connect_hydrants_to_risers(self, config: dict):
        """
        将每个消火栓与同层最近的立管配对，在立管上1.1m高度处创建一个新节点，
        删除原立管管道，创建两段新立管（顶部到1.1m节点，1.1m节点到底部），
        并生成DN65横管连接到消火栓末端节点。
        新立管管道ID在原ID后加 _A 和 _B，继承原立管编号。
        """
        logger.info("=== 开始消火栓-立管配对 ===")
        if not self.floors:
            logger.warning("没有楼层数据，跳过配对")
            return
        if not self.risers:
            logger.warning("没有立管数据，跳过配对")
            return
        if not self.hydrants:
            logger.warning("没有消火栓数据，跳过配对")
            return
    
        logger.info(f"楼层数: {len(self.floors)}, 立管数: {len(self.risers)}, 消火栓数: {len(self.hydrants)}")
    
        # 获取配置参数
        drawing_unit = config.get("drawing_unit", "毫米")
        unit_factors = self.unit_factors
        tolerance_mm = config.get("tolerance", 10.0)
        material = config.get("pipe_material", "镀锌钢管")
        roughness = self.material_manager.get_roughness(material)
    
        # 配对最大距离（毫米）
        MAX_PAIR_DISTANCE_MM = 5000.0   # 5米
    
        # 获取DN65管径信息
        dn_info = self.material_manager.get_diameter_info(material, "DN65")
        if not dn_info or dn_info.get("inner", 0) == 0:
            logger.warning("未找到DN65管径信息，无法生成消火栓支管")
            return
        dn65_inner_mm = dn_info["inner"]
        logger.info(f"DN65内径: {dn65_inner_mm} mm")
    
        # 按楼层分组立管
        risers_by_floor = {}
        for r in self.risers:
            if r.floor_name:
                risers_by_floor.setdefault(r.floor_name, []).append(r)
            else:
                logger.warning(f"立管 {r.riser_id} 没有楼层名")
    
        # 按楼层分组消火栓
        hydrants_by_floor = {}
        for h in self.hydrants:
            if h.floor_name:
                hydrants_by_floor.setdefault(h.floor_name, []).append(h)
            else:
                logger.warning(f"消火栓 {h.hydrant_id} 没有楼层名，跳过")
    
        processed_hydrants = set()
        split_risers = set()
    
        for floor in self.floors:
            floor_name = floor.name
            risers = risers_by_floor.get(floor_name, [])
            hydrants = hydrants_by_floor.get(floor_name, [])
            logger.info(f"楼层 {floor_name}: 立管 {len(risers)} 个, 消火栓 {len(hydrants)} 个")
    
            if not risers or not hydrants:
                continue
    
            # 为每个消火栓找最近的立管
            hydrant_pairs = []
            for hydrant in hydrants:
                if hydrant.hydrant_id in processed_hydrants:
                    continue
                best_dist = float('inf')
                best_riser = None
                for riser in risers:
                    dx = hydrant.x - riser.x
                    dy = hydrant.y - riser.y
                    dist = math.hypot(dx, dy)
                    if dist < best_dist - 1e-6:
                        best_dist = dist
                        best_riser = riser
                    elif abs(dist - best_dist) < 1e-6 and best_riser is not None:
                        if riser.nominal_diameter == "DN65" and best_riser.nominal_diameter != "DN65":
                            best_riser = riser
                if best_riser is None:
                    continue
                if best_dist > MAX_PAIR_DISTANCE_MM:
                    logger.warning(f"消火栓 {hydrant.hydrant_id} 距立管 {best_riser.riser_id} 距离 {best_dist:.1f}mm 超过 {MAX_PAIR_DISTANCE_MM}mm，跳过")
                    continue
                hydrant_pairs.append((hydrant, best_riser, best_dist))
                processed_hydrants.add(hydrant.hydrant_id)
    
            # 按立管ID分组
            riser_to_hydrants = {}
            for hydrant, riser, dist in hydrant_pairs:
                riser_to_hydrants.setdefault(riser.riser_id, []).append((hydrant, riser, dist))
    
            for riser_id, hydrant_list in riser_to_hydrants.items():
                riser = self.riser_by_id.get(riser_id)
                if not riser:
                    continue
    
                if riser_id in split_risers:
                    # 已拆分过，直接复用已有的中间节点和两段立管
                    pipe_a = self.pipe_by_id.get(f"{riser_id}_A")
                    pipe_b = self.pipe_by_id.get(f"{riser_id}_B")
                    if pipe_a and pipe_b:
                        mid_node = self.node_by_id.get(pipe_a.end_node_id)
                        if not mid_node:
                            mid_node = self.node_by_id.get(pipe_b.start_node_id)
                        if mid_node:
                            for hydrant, _, dist in hydrant_list:
                                self._create_hydrant_branch(hydrant, mid_node, floor, material, dn65_inner_mm, roughness, unit_factors, drawing_unit, tolerance_mm)
                        else:
                            logger.error(f"立管 {riser_id} 拆分后找不到中间节点")
                    else:
                        logger.error(f"立管 {riser_id} 已拆分但找不到新管道")
                    continue
    
                # 第一次拆分该立管
                split_risers.add(riser_id)
    
                # 获取原立管管道
                old_vertical_pipe = self.pipe_by_id.get(riser_id)
                if not old_vertical_pipe or not old_vertical_pipe.pipe_id.startswith("R_"):
                    logger.warning(f"立管 {riser_id} 未找到对应的竖向管道，跳过拆分")
                    continue
    
                # 获取原立管的上下端节点
                top_node = self.node_by_id.get(old_vertical_pipe.start_node_id)
                bottom_node = self.node_by_id.get(old_vertical_pipe.end_node_id)
                if not top_node or not bottom_node:
                    logger.warning(f"立管 {riser_id} 的节点不完整")
                    continue
                if top_node.z < bottom_node.z:
                    top_node, bottom_node = bottom_node, top_node
    
                # 计算1.1m高度处的节点坐标（毫米）
                floor_elev_mm = floor.elevation * 1000.0
                new_z_mm = floor_elev_mm + 1100.0
    
                # 强制创建新节点，不复用任何现有节点
                mid_node_id = f"N_{len(self.nodes) + 1:04d}"
                mid_node = NodeData(
                    node_id=mid_node_id,
                    x=riser.x,
                    y=riser.y,
                    z=new_z_mm,
                    cad_key=f"{riser.x:.6f},{riser.y:.6f},{new_z_mm:.6f}",
                    connected_pipes=[]
                )
                self.nodes.append(mid_node)
                self.node_by_id[mid_node_id] = mid_node
                # logger.info(f"在立管 {riser_id} 上创建1.1m节点 {mid_node_id} (Z={new_z_mm}mm)")
    
                # 删除原立管管道
                if old_vertical_pipe.pipe_id in top_node.connected_pipes:
                    top_node.connected_pipes.remove(old_vertical_pipe.pipe_id)
                if old_vertical_pipe.pipe_id in bottom_node.connected_pipes:
                    bottom_node.connected_pipes.remove(old_vertical_pipe.pipe_id)
                if old_vertical_pipe in floor.pipes:
                    floor.pipes.remove(old_vertical_pipe)
                self.pipes.remove(old_vertical_pipe)
                del self.pipe_by_id[old_vertical_pipe.pipe_id]
    
                # 创建立管上半段（顶部到中间节点）
                pipe_a_id = f"{riser_id}_A"
                pipe_a = PipeData(
                    pipe_id=pipe_a_id,
                    start_node_id=top_node.node_id,
                    end_node_id=mid_node.node_id,
                    start_point=(top_node.x, top_node.y, top_node.z),
                    end_point=(mid_node.x, mid_node.y, mid_node.z),
                    nominal_diameter=old_vertical_pipe.nominal_diameter,
                    inner_diameter=old_vertical_pipe.inner_diameter,
                    material=old_vertical_pipe.material,
                    roughness=old_vertical_pipe.roughness,
                    layer=old_vertical_pipe.layer,
                    riser_number=riser.note_number
                )
                dx = pipe_a.end_point[0] - pipe_a.start_point[0]
                dy = pipe_a.end_point[1] - pipe_a.start_point[1]
                dz = pipe_a.end_point[2] - pipe_a.start_point[2]
                pipe_a.raw_length = math.hypot(dx, dy, dz)
                pipe_a.length = pipe_a.raw_length * unit_factors.get(drawing_unit, 0.001)
    
                # 创建立管下半段（中间节点到底部）
                pipe_b_id = f"{riser_id}_B"
                pipe_b = PipeData(
                    pipe_id=pipe_b_id,
                    start_node_id=mid_node.node_id,
                    end_node_id=bottom_node.node_id,
                    start_point=(mid_node.x, mid_node.y, mid_node.z),
                    end_point=(bottom_node.x, bottom_node.y, bottom_node.z),
                    nominal_diameter=old_vertical_pipe.nominal_diameter,
                    inner_diameter=old_vertical_pipe.inner_diameter,
                    material=old_vertical_pipe.material,
                    roughness=old_vertical_pipe.roughness,
                    layer=old_vertical_pipe.layer,
                    riser_number=riser.note_number
                )
                dx = pipe_b.end_point[0] - pipe_b.start_point[0]
                dy = pipe_b.end_point[1] - pipe_b.start_point[1]
                dz = pipe_b.end_point[2] - pipe_b.start_point[2]
                pipe_b.raw_length = math.hypot(dx, dy, dz)
                pipe_b.length = pipe_b.raw_length * unit_factors.get(drawing_unit, 0.001)
    
                # 添加新管道
                self.pipes.append(pipe_a)
                self.pipe_by_id[pipe_a_id] = pipe_a
                pipe_a.original_riser_id = riser_id
                self.pipes.append(pipe_b)
                self.pipe_by_id[pipe_b_id] = pipe_b
                pipe_b.original_riser_id = riser_id
    
                # 更新节点连接关系
                top_node.connected_pipes.append(pipe_a_id)
                mid_node.connected_pipes.append(pipe_a_id)
                mid_node.connected_pipes.append(pipe_b_id)
                bottom_node.connected_pipes.append(pipe_b_id)
    
                floor.pipes.append(pipe_a)
                floor.pipes.append(pipe_b)
    
                # logger.info(f"立管 {riser_id} 已拆分为 {pipe_a_id} (长度 {pipe_a.length:.3f}m) 和 {pipe_b_id} (长度 {pipe_b.length:.3f}m)")
    
                # 为每个关联的消火栓创建支管
                for hydrant, _, dist in hydrant_list:
                    self._create_hydrant_branch(hydrant, mid_node, floor, material, dn65_inner_mm, roughness, unit_factors, drawing_unit, tolerance_mm)
    
        logger.info(f"配对完成，共处理消火栓 {len(processed_hydrants)} 个，已拆分立管 {len(split_risers)} 个")
        self.update_pipe_types(config)
        logger.info("=== 消火栓-立管配对及支管生成完成 ===")
    
    def _create_hydrant_branch(self, hydrant, mid_node, floor, material, dn65_inner_mm, roughness, unit_factors, drawing_unit, tolerance_mm):
        """为消火栓创建末端节点和横管（内部辅助方法）"""
        # 创建消火栓末端节点
        end_node_id = f"N_{len(self.nodes) + 1:04d}"
        end_node = NodeData(
            node_id=end_node_id,
            x=hydrant.x,
            y=hydrant.y,
            z=mid_node.z,
            cad_key=f"{hydrant.x:.6f},{hydrant.y:.6f},{mid_node.z:.6f}",
            connected_pipes=[]
        )
        self.nodes.append(end_node)
        self.node_by_id[end_node_id] = end_node
        # logger.info(f"创建消火栓末端节点 {end_node_id} 位于 ({hydrant.x:.2f}, {hydrant.y:.2f}, Z={mid_node.z}mm)")
    
        # 创建横管（DN65）
        branch_pipe_id = f"B_{len(self.pipes) + 1:04d}"
        branch_pipe = PipeData(
            pipe_id=branch_pipe_id,
            start_node_id=mid_node.node_id,
            end_node_id=end_node_id,
            start_point=(mid_node.x, mid_node.y, mid_node.z),
            end_point=(end_node.x, end_node.y, end_node.z),
            nominal_diameter="DN65",
            inner_diameter=dn65_inner_mm,
            material=material,
            roughness=roughness,
            pipe_type="支管"
        )
        dx = branch_pipe.end_point[0] - branch_pipe.start_point[0]
        dy = branch_pipe.end_point[1] - branch_pipe.start_point[1]
        dz = branch_pipe.end_point[2] - branch_pipe.start_point[2]
        length_mm = math.hypot(dx, dy, dz)
        branch_pipe.raw_length = length_mm
        branch_pipe.length = length_mm * unit_factors.get(drawing_unit, 0.001)
        branch_pipe.is_hydrant_branch = True
    
        self.pipes.append(branch_pipe)
        self.pipe_by_id[branch_pipe_id] = branch_pipe
        floor.pipes.append(branch_pipe)

        # 更新节点连接关系
        mid_node.connected_pipes.append(branch_pipe_id)
        end_node.connected_pipes.append(branch_pipe_id)
    
        # 更新消火栓关联节点
        old_node_id = hydrant.node_id
        hydrant.node_id = end_node_id
        if old_node_id:
            old_node = self.node_by_id.get(old_node_id)
            if old_node and hydrant.hydrant_id in old_node.hydrants:
                old_node.hydrants.remove(hydrant.hydrant_id)
        if hydrant.hydrant_id not in end_node.hydrants:
            end_node.hydrants.append(hydrant.hydrant_id)
    
        # 如果横管太短，直接合并
        if branch_pipe.raw_length < tolerance_mm:
            logger.info(f"横管长度 {branch_pipe.raw_length:.2f}mm 小于容差，直接合并到 mid_node")
            hydrant.node_id = mid_node.node_id
            if hydrant.hydrant_id not in mid_node.hydrants:
                mid_node.hydrants.append(hydrant.hydrant_id)
            # 清理临时节点和管道
            end_node.connected_pipes.remove(branch_pipe_id)
            self.pipes.remove(branch_pipe)
            del self.pipe_by_id[branch_pipe_id]
            self.nodes.remove(end_node)
            del self.node_by_id[end_node_id]
            floor.nodes.remove(end_node)
            if branch_pipe_id in mid_node.connected_pipes:
                mid_node.connected_pipes.remove(branch_pipe_id)



