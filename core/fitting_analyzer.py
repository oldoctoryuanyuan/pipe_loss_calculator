# core/fitting_analyzer.py
"""
管件分类分析器（当量长度法）
将CAD管网中的节点按连接管道数及3D夹角分类为弯头/三通/四通/直通/错误，
并计算静态当量长度（弯头/阀门/异径），供当量长度法引擎使用。
"""
import math
import json
import os
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)

# 公称直径等级序列（异径提高等级计算用）
NOMINAL_SERIES = [25, 32, 40, 50, 65, 80, 100, 125, 150, 200, 250, 300, 350, 400]

# 角度分类阈值（度）
ANGLE_STRAIGHT = 170.0   # 直通
ANGLE_45_MIN, ANGLE_45_MAX = 125.0, 145.0
ANGLE_90_MIN, ANGLE_90_MAX = 80.0, 100.0
ANGLE_TOL = 0.5          # 浮点容差


def angle_between_degrees(v1_start, v1_end, v2_start, v2_end) -> float:
    """两空间线段方向向量的夹角（0~180°）"""
    d1 = (v1_end[0] - v1_start[0], v1_end[1] - v1_start[1], v1_end[2] - v1_start[2])
    d2 = (v2_end[0] - v2_start[0], v2_end[1] - v2_start[1], v2_end[2] - v2_start[2])
    return _vectors_angle_degrees(d1, d2)


def _vectors_angle_degrees(d1: Tuple[float, float, float], d2: Tuple[float, float, float]) -> float:
    """两方向向量的夹角（0~180°）"""
    n1 = math.sqrt(d1[0] ** 2 + d1[1] ** 2 + d1[2] ** 2)
    n2 = math.sqrt(d2[0] ** 2 + d2[1] ** 2 + d2[2] ** 2)
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    cos = (d1[0] * d2[0] + d1[1] * d2[1] + d1[2] * d2[2]) / (n1 * n2)
    cos = max(-1.0, min(1.0, cos))
    return math.degrees(math.acos(cos))


def _node_outward_dir(node_id: str, pipe) -> Tuple[float, float, float]:
    """管件节点处管道向外的方向向量（节点→另一端），与管道拓扑方向无关"""
    if pipe.start_node_id == node_id:
        return (pipe.end_point[0] - pipe.start_point[0],
                pipe.end_point[1] - pipe.start_point[1],
                pipe.end_point[2] - pipe.start_point[2])
    return (pipe.start_point[0] - pipe.end_point[0],
            pipe.start_point[1] - pipe.end_point[1],
            pipe.start_point[2] - pipe.end_point[2])


def _parse_dn(nominal_diameter) -> Optional[int]:
    """从公称直径字符串（如 'DN100'）提取数字；失败返回None"""
    if not nominal_diameter:
        return None
    digits = ''.join(ch for ch in str(nominal_diameter) if ch.isdigit())
    if not digits:
        return None
    return int(digits)


def _nearest_series_dn(dn: int) -> int:
    """将管径就近匹配到公称等级序列"""
    return min(NOMINAL_SERIES, key=lambda s: abs(s - dn))


def _pipe_dn(pipe) -> int:
    """取管道公称直径（数字）；nominal缺失时用内径就近匹配"""
    dn = _parse_dn(pipe.nominal_diameter)
    if dn is not None and dn > 0:
        return dn
    if getattr(pipe, 'inner_diameter', 0) and pipe.inner_diameter > 0:
        return _nearest_series_dn(round(pipe.inner_diameter))
    return 0


def _is_straight(angle: float) -> bool:
    return angle >= ANGLE_STRAIGHT - ANGLE_TOL


def _is_45_bend(angle: float) -> bool:
    return ANGLE_45_MIN + ANGLE_TOL <= angle <= ANGLE_45_MAX - ANGLE_TOL


def _is_90_bend(angle: float) -> bool:
    return ANGLE_90_MIN + ANGLE_TOL <= angle <= ANGLE_90_MAX - ANGLE_TOL


def _is_angle_error(angle: float) -> bool:
    """非直通、非45°/90°弯头的夹角视为画图错误/不严谨"""
    if angle < ANGLE_90_MIN - ANGLE_TOL:
        return True
    if ANGLE_90_MAX + ANGLE_TOL < angle < ANGLE_45_MIN - ANGLE_TOL:
        return True
    if ANGLE_45_MAX + ANGLE_TOL < angle < ANGLE_STRAIGHT - ANGLE_TOL:
        return True
    return False


def _find_straight_pairs(pipes: List[str], angles: Dict[Tuple[str, str], float]) -> Tuple[List[Tuple[str, str]], List[str]]:
    """从连接管道中贪心配对直通对（夹角≥170°），返回(直通对列表, 侧通管道列表)"""
    pairs: List[Tuple[str, str]] = []
    remaining = set(pipes)
    while remaining:
        p = sorted(remaining)[0]
        partner = None
        for q in sorted(remaining - {p}):
            key = tuple(sorted((p, q)))
            if _is_straight(angles.get(key, 0.0)):
                partner = q
                break
        if partner is not None:
            pairs.append((p, partner))
            remaining.discard(p)
            remaining.discard(partner)
        else:
            remaining.discard(p)
    side_pipes = [p for p in pipes if not any(p in pair for pair in pairs)]
    return pairs, side_pipes


def load_fitting_tables(path: Optional[str] = None) -> Dict[str, Dict[str, float]]:
    """读取当量长度数据表（EquivLength_Fittings.json），返回 {名称: {管径键: 值}}"""
    if path is None:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "EquivLength_Fittings.json")
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    tables: Dict[str, Dict[str, float]] = {}
    for item in data.get("管件和阀门", []):
        name = item.get("名称", "")
        table: Dict[str, float] = {}
        for k, v in item.get("当量长度(m)", {}).items():
            key = str(k).strip()
            try:
                if "x" in key:
                    table[key] = float(v)      # 异径接头复合键（如 "125x100"）
                else:
                    table[str(int(key))] = float(v)
            except (ValueError, TypeError):
                continue
        tables[name] = table
    return tables


@dataclass
class FittingRecord:
    """单个节点的管件分类结果"""
    node_id: str = ""
    degree: int = 0
    fitting_type: str = "未知"          # 直通/45弯头/90弯头/三通/四通/错误
    pipes: List[str] = field(default_factory=list)      # 连接管道ID
    straight_pairs: List[Tuple[str, str]] = field(default_factory=list)  # 直通对（管道ID对）
    side_pipes: List[str] = field(default_factory=list)  # 侧通管道
    diameter_mm: int = 0               # 管件管径（所连最大公称管径）
    errors: List[str] = field(default_factory=list)


@dataclass
class FittingAnalysisResult:
    """管网管件分析结果"""
    fittings: Dict[str, FittingRecord] = field(default_factory=dict)  # node_id -> 记录
    static_lengths: Dict[str, float] = field(default_factory=dict)    # pipe_id -> 静态当量(m)
    error_nodes: List[Tuple[str, str]] = field(default_factory=list)  # [(node_id, 原因)] 画图错误
    missing_data: List[str] = field(default_factory=list)             # 数据缺失描述（含节点/管道编号）
    self_loop_pipes: List[str] = field(default_factory=list)          # 自环管道ID（起点=终点，不参与计算但需提醒用户）
    tables: Dict[str, Dict[str, float]] = field(default_factory=dict) # 原始当量表


def _lookup_table(tables: Dict, name: str, dn: int, location: str, result: FittingAnalysisResult) -> Optional[float]:
    """查当量表；缺失时记录 missing_data 并返回 None"""
    table = tables.get(name, {})
    value = table.get(str(dn))
    if value is None:
        result.missing_data.append(f"{location}：{name}DN{dn}无当量长度数据")
        return None
    return value


def _lookup_reducer(tables: Dict, big_dn: int, small_dn: int, node_id: str,
                    result: FittingAnalysisResult) -> Optional[float]:
    """异径接头当量长度：以大头为入口、小头为出口。

    规则：优先查表键 "大头x小头"（相邻级）；否则以"小头的上一级x小头"为基准，
    入口（大头）自身提高1级时×1.5，提高2级或以上时×2.0。
    """
    table = tables.get("异径接头", {})
    key = f"{big_dn}x{small_dn}"
    if key in table:
        return table[key]
    if small_dn not in NOMINAL_SERIES or big_dn not in NOMINAL_SERIES:
        result.missing_data.append(f"节点{node_id}：异径DN{big_dn}xDN{small_dn}无当量长度数据")
        return None
    idx_small = NOMINAL_SERIES.index(small_dn)
    if idx_small >= len(NOMINAL_SERIES) - 1:
        result.missing_data.append(f"节点{node_id}：异径DN{big_dn}xDN{small_dn}无当量长度数据")
        return None
    entry_small = NOMINAL_SERIES[idx_small + 1]   # 小头的上一级（更大相邻等级，基准键入口）
    base_key = f"{entry_small}x{small_dn}"
    if base_key not in table:
        result.missing_data.append(f"节点{node_id}：异径DN{big_dn}xDN{small_dn}无当量长度数据")
        return None
    base = table[base_key]
    levels = NOMINAL_SERIES.index(big_dn) - NOMINAL_SERIES.index(entry_small)
    if levels <= 1:
        return base * 1.5
    return base * 2.0


def analyze_fittings(cad, tables: Optional[Dict] = None,
                     pipe_ids: Optional[set] = None) -> FittingAnalysisResult:
    """分析管网：管件分类 + 静态当量长度（弯头/阀门/异径）。

    Args:
        cad: CADDataManager
        tables: 可选注入当量表（测试用）
        pipe_ids: 可选管道ID集合——仅分析这些管道及其端点节点（区域模式逐单体
                  读取时传入当前单体管道ID，避免重复提示其它单体的画图错误）；
                  为 None 时分析整个管网（默认行为不变）。
    """
    if tables is None:
        tables = load_fitting_tables()
    result = FittingAnalysisResult(tables=tables)
    if not cad or not cad.pipes:
        return result

    # 1. 构建节点邻接表
    adj: Dict[str, List[Tuple[str, object]]] = {}   # node_id -> [(pipe_id, pipe)]
    for pipe in cad.pipes:
        if not pipe.is_active:
            continue
        if pipe_ids is not None and pipe.pipe_id not in pipe_ids:
            continue
        # 自环管道（起点==终点）：物理上无意义，跳过参与管件分类（避免同管自比、
        # 夹角0°误报、节点度数虚高）。记录到 self_loop_pipes 供读取CAD时提醒用户，
        # 但不加入 error_nodes（不阻塞计算，INP生成时也会跳过该管道）
        if pipe.start_node_id == pipe.end_node_id:
            result.self_loop_pipes.append(pipe.pipe_id)
            continue
        sn = cad.node_by_id.get(pipe.start_node_id)
        en = cad.node_by_id.get(pipe.end_node_id)
        if not sn or not en or not sn.is_active or not en.is_active:
            continue
        adj.setdefault(pipe.start_node_id, []).append((pipe.pipe_id, pipe))
        adj.setdefault(pipe.end_node_id, []).append((pipe.pipe_id, pipe))
    if not adj:
        return result

    # 2. 节点分类
    for node_id, items in adj.items():
        degree = len(items)
        if degree <= 1:
            continue   # 端头/孤立节点，无管件
        pipes = [pid for pid, _ in items]
        pipe_objs = {pid: p for pid, p in items}

        # 两两夹角（以节点为原点，取"节点→另一端"的方向向量，方向与管道拓扑无关）
        angles: Dict[Tuple[str, str], float] = {}
        dirs: Dict[str, Tuple[float, float, float]] = {
            pid: _node_outward_dir(node_id, p) for pid, p in items
        }
        for i in range(degree):
            for j in range(i + 1, degree):
                angles[tuple(sorted((pipes[i], pipes[j])))] = _vectors_angle_degrees(
                    dirs[pipes[i]], dirs[pipes[j]])

        # 错误夹角检查
        errors: List[str] = []
        for (p1, p2), theta in angles.items():
            if _is_angle_error(theta):
                errors.append(f"管道{p1}与管道{p2}夹角{theta:.1f}°（画图错误）")
        if degree >= 5:
            errors.insert(0, f"连接{degree}根管道（画图错误）")

        # 直通对配对
        straight_pairs, side_pipes = _find_straight_pairs(pipes, angles)

        # 分类
        if degree == 2:
            theta = angles[tuple(sorted((pipes[0], pipes[1])))]
            if _is_straight(theta):
                fitting_type = "直通"
            elif _is_45_bend(theta):
                fitting_type = "45弯头"
            elif _is_90_bend(theta):
                fitting_type = "90弯头"
            else:
                fitting_type = "错误"
                if not errors:
                    errors.append(f"两管夹角{theta:.1f}°（画图错误）")
        elif degree == 3:
            if len(straight_pairs) == 1 and len(side_pipes) == 1:
                fitting_type = "三通"
            else:
                fitting_type = "错误"
                if not errors:
                    errors.append("未找到直通对（画图错误）")
        elif degree == 4:
            if len(straight_pairs) == 2 and len(side_pipes) == 0:
                fitting_type = "四通"
            else:
                fitting_type = "错误"
                if not errors:
                    errors.append("未找到两对直通对（画图错误）")
        else:
            fitting_type = "错误"
            if not errors:
                errors.append(f"连接{degree}根管道（画图错误）")

        if fitting_type == "错误":
            for reason in errors:
                result.error_nodes.append((node_id, reason))

        # 管件管径 = 所连最大管径
        max_dn = max(_pipe_dn(p) for p in pipe_objs.values())

        record = FittingRecord(
            node_id=node_id,
            degree=degree,
            fitting_type=fitting_type,
            pipes=pipes,
            straight_pairs=straight_pairs,
            side_pipes=side_pipes,
            diameter_mm=max_dn,
            errors=errors,
        )
        result.fittings[node_id] = record

        # 3a. 弯头静态当量（均摊给所连两管）
        if fitting_type in ("45弯头", "90弯头") and max_dn > 0:
            table_name = "45°弯头" if fitting_type == "45弯头" else "90°弯头"
            value = _lookup_table(tables, table_name, max_dn, f"节点{node_id}", result)
            if value is not None:
                half = value / 2.0
                for pid in pipes:
                    result.static_lengths[pid] = result.static_lengths.get(pid, 0.0) + half

        # 3b. 异径静态当量（放在较小管段上）
        dns = {_pipe_dn(p) for p in pipe_objs.values() if _pipe_dn(p) > 0}
        if len(dns) > 1:
            big_dn = max(dns)
            for pid, p in items:
                dn = _pipe_dn(p)
                if 0 < dn < big_dn:
                    value = _lookup_reducer(tables, big_dn, dn, node_id, result)
                    if value is not None:
                        result.static_lengths[pid] = result.static_lengths.get(pid, 0.0) + value

        # 3c. 三通/四通侧向当量数据存在性检查（供引擎动态使用）
        if fitting_type in ("三通", "四通") and max_dn > 0:
            if str(max_dn) not in tables.get("三通或四通(侧向)", {}):
                result.missing_data.append(f"节点{node_id}：{fitting_type}DN{max_dn}无当量长度数据")

    # 4. 阀门静态当量（默认蝶阀，加在阀门所在管道上）
    for valve in cad.valves:
        pipe_id = valve.pipe_id
        if not pipe_id:
            continue
        if pipe_ids is not None and pipe_id not in pipe_ids:
            continue
        pipe = cad.pipe_by_id.get(pipe_id)
        if not pipe or not pipe.is_active:
            continue
        dn = _pipe_dn(pipe)
        if dn <= 0:
            continue
        value = _lookup_table(tables, "蝶阀", dn, f"管道{pipe_id}", result)
        if value is not None:
            result.static_lengths[pipe_id] = result.static_lengths.get(pipe_id, 0.0) + value

    logger.info(f"管件分析完成: 节点{len(result.fittings)}个, 画图错误{len(result.error_nodes)}个, 数据缺失{len(result.missing_data)}条")
    return result


def convert_error_nodes_to_standard(cad, analysis: FittingAnalysisResult) -> FittingAnalysisResult:
    """将画图错误节点转为标准管件分类（供"转为标准管件计算"使用）。

    规则：
      - 连接2根管道：按最接近的角度转为 45弯头 或 90弯头（45/90取更近者）
      - 连接3根管道：转为三通，夹角最接近180°的两管按直通处理（直通对），另一管为侧通
      - 连接4根管道：转为四通，对向的两管两两算作直通（贪心配对两对直通对）
      - 连接5根及以上管道：仍保留为错误（无法转换）

    转换后重新计算被转换节点的静态当量（弯头均摊）并更新 fittings 记录。
    返回处理后的 analysis（error_nodes 仅剩无法转换的 ≥5 管节点）。
    """
    if not cad or not analysis.fittings:
        return analysis

    remaining_errors: List[Tuple[str, str]] = []
    converted: List[Tuple[str, str]] = []

    for node_id, reason in analysis.error_nodes:
        rec = analysis.fittings.get(node_id)
        if rec is None or rec.degree < 2 or rec.degree > 4:
            remaining_errors.append((node_id, reason))
            continue

        pipes = rec.pipes
        pipe_objs = {pid: cad.pipe_by_id.get(pid) for pid in pipes}
        if any(p is None for p in pipe_objs.values()):
            remaining_errors.append((node_id, reason))
            continue

        # 节点→另一端方向向量
        dirs = {pid: _node_outward_dir(node_id, p) for pid, p in pipe_objs.items()}

        # 两两夹角
        angles: Dict[Tuple[str, str], float] = {}
        for i in range(len(pipes)):
            for j in range(i + 1, len(pipes)):
                angles[tuple(sorted((pipes[i], pipes[j])))] = _vectors_angle_degrees(
                    dirs[pipes[i]], dirs[pipes[j]])

        # ---- 分类转换 ----
        if rec.degree == 2:
            theta = angles[tuple(sorted((pipes[0], pipes[1])))]
            if abs(theta - 90.0) <= abs(theta - 45.0):
                rec.fitting_type = "90弯头"
            else:
                rec.fitting_type = "45弯头"
            rec.straight_pairs = []
            rec.side_pipes = []
        elif rec.degree == 3:
            # 找最接近180°的一对作为直通对，另一管为侧通
            best_pair = max(
                ((pipes[i], pipes[j]) for i in range(3) for j in range(i + 1, 3)),
                key=lambda pr: angles[tuple(sorted(pr))])
            bp = tuple(sorted(best_pair))
            rec.fitting_type = "三通"
            rec.straight_pairs = [bp]
            rec.side_pipes = [p for p in pipes if p not in bp]
        else:  # degree == 4
            # 贪心配对两对直通对：每次取夹角最大的一对，剩余两管再配一对
            pairs: List[Tuple[str, str]] = []
            remaining = list(pipes)
            while len(remaining) >= 2:
                best_pair = max(
                    ((remaining[i], remaining[j])
                     for i in range(len(remaining)) for j in range(i + 1, len(remaining))),
                    key=lambda pr: angles[tuple(sorted(pr))])
                bp = tuple(sorted(best_pair))
                pairs.append(bp)
                remaining = [p for p in remaining if p not in bp]
            rec.fitting_type = "四通"
            rec.straight_pairs = pairs
            rec.side_pipes = []

        rec.errors = []
        converted.append(node_id)

        # ---- 重新计算静态当量 ----
        # 先移除该节点相关的旧静态当量（原分析中错误节点无弯头当量，但可能已有异径/阀门当量）
        # 弯头当量：均摊给所连两管
        max_dn = rec.diameter_mm
        if rec.fitting_type in ("45弯头", "90弯头") and max_dn > 0:
            table_name = "45°弯头" if rec.fitting_type == "45弯头" else "90°弯头"
            value = _lookup_table(analysis.tables, table_name, max_dn, f"节点{node_id}", analysis)
            if value is not None:
                half = value / 2.0
                for pid in pipes:
                    analysis.static_lengths[pid] = analysis.static_lengths.get(pid, 0.0) + half
        # 三通/四通侧向当量数据存在性检查（供引擎动态使用）
        if rec.fitting_type in ("三通", "四通") and max_dn > 0:
            if str(max_dn) not in analysis.tables.get("三通或四通(侧向)", {}):
                analysis.missing_data.append(f"节点{node_id}：{rec.fitting_type}DN{max_dn}无当量长度数据")
        # 异径当量（原分析已对所有节点处理，无需重复）

        analysis.fittings[node_id] = rec

    analysis.error_nodes = remaining_errors
    if converted:
        logger.info(f"已转换画图错误节点 {len(converted)} 个为标准管件: {converted}")
    return analysis
