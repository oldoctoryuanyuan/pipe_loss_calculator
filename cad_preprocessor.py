"""
CAD数据预处理模块
负责拆分多段线、处理跨线分割，返回模拟的直线段列表
"""
import math
import logging
from typing import List, Dict, Any
CAD_AVAILABLE = True

logger = logging.getLogger(__name__)

# 判断线段是否退化为点（长度接近零）的阈值。
# 注意：不能用 tolerance（容差），否则长度小于容差的合法短管会被误丢弃
# （曾导致 41.5mm 短线丢失、阀门 V_0012 匹配失败，2026-08-05 修复）。
MIN_LINE_LENGTH = 1e-9

class SimpleLine:
    """模拟的直线实体，用于替换原始的多段线"""
    def __init__(self, start, end, color, layer, handle, valve_pos=None):
        self.ObjectName = "AcDbLine"
        self.StartPoint = start
        self.EndPoint = end
        self.Color = color
        self.Layer = layer
        self.Handle = handle
        self.valve_pos = valve_pos
        self.Length = math.sqrt((end[0]-start[0])**2 + (end[1]-start[1])**2 + (end[2]-start[2])**2)

def merge_collinear_segments(segments, tolerance):
    """
    合并共线且重叠（或端点相接）的线段，仅考虑 XY 坐标。
    算法：
    1. 将所有线段按方向角（模π）分组，容差 1e-4 弧度。
    2. 在每个角度组内，循环合并：
       - 取第一条线段作为参考直线。
       - 找出与之共线（两端点到参考直线距离<=tol）的线段，提取这些线段的所有投影区间，合并后生成新线段。
       - 将未参与合并的线段保留，继续循环直至没有变化。
    3. 返回所有合并后的线段。
    """
    if not segments:
        return segments

    import math
    from collections import defaultdict

    # 辅助函数：点到直线距离（二维）
    def point_line_distance(px, py, x1, y1, x2, y2):
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) < MIN_LINE_LENGTH and abs(dy) < MIN_LINE_LENGTH:
            return math.hypot(px - x1, py - y1)
        return abs(dy * px - dx * py + x2 * y1 - y2 * x1) / math.hypot(dx, dy)

    # 计算线段的方向角（模π）
    def direction_angle(seg):
        x1, y1, _ = seg['start']
        x2, y2, _ = seg['end']
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) < MIN_LINE_LENGTH and abs(dy) < MIN_LINE_LENGTH:
            return None
        ang = math.atan2(dy, dx)
        if ang < 0:
            ang += math.pi
        if ang >= math.pi - 1e-6:
            ang = 0.0
        return ang

    # 按角度分组
    angle_tol = 1e-4
    groups = defaultdict(list)
    for seg in segments:
        ang = direction_angle(seg)
        if ang is None:
            continue
        found = False
        for key in list(groups.keys()):
            if abs(ang - key) < angle_tol:
                groups[key].append(seg)
                found = True
                break
        if not found:
            groups[ang].append(seg)

    result = []

    for ang, segs in groups.items():
        work = list(segs)
        while True:
            merged = False
            if len(work) <= 1:
                break
            ref = work[0]
            x1, y1, _ = ref['start']
            x2, y2, _ = ref['end']
            dx = x2 - x1
            dy = y2 - y1
            length = math.hypot(dx, dy)
            if length < tolerance:
                # 退化为点，直接保留
                result.append(ref)
                work.pop(0)
                continue
            ux = dx / length
            uy = dy / length

            collinear = []
            rest = []
            for seg in work:
                sx, sy, _ = seg['start']
                ex, ey, _ = seg['end']
                # 检查两个端点是否都在参考线上（距离容差内）
                d1 = point_line_distance(sx, sy, x1, y1, x2, y2)
                d2 = point_line_distance(ex, ey, x1, y1, x2, y2)
                if d1 > tolerance or d2 > tolerance:
                    rest.append(seg)
                    continue
                # 计算线段在参考线上的投影区间
                t1 = (sx - x1) * ux + (sy - y1) * uy
                t2 = (ex - x1) * ux + (ey - y1) * uy
                seg_min = min(t1, t2)
                seg_max = max(t1, t2)
                # 参考线自身区间 [0, length]
                ref_min = 0.0
                ref_max = length
                # 计算交集长度
                overlap = max(0.0, min(seg_max, ref_max) - max(seg_min, ref_min))
                # 只有存在正重叠（大于一个极小容差）的线段才参与合并
                if overlap > tolerance * 0.1:
                    collinear.append(seg)
                else:
                    rest.append(seg)

            if len(collinear) == 1:
                # 只有参考自身，无法合并
                result.append(collinear[0])
                work = rest
                continue

            # 合并 collinear 中的线段
            intervals = []
            for seg in collinear:
                sx, sy, _ = seg['start']
                ex, ey, _ = seg['end']
                t1 = (sx - x1) * ux + (sy - y1) * uy
                t2 = (ex - x1) * ux + (ey - y1) * uy
                if t1 < t2:
                    intervals.append((t1, t2))
                else:
                    intervals.append((t2, t1))
            intervals.sort(key=lambda x: x[0])
            merged_intervals = []
            for tmin, tmax in intervals:
                if not merged_intervals:
                    merged_intervals.append([tmin, tmax])
                else:
                    last = merged_intervals[-1]
                    if tmin <= last[1] - tolerance:
                        last[1] = max(last[1], tmax)
                    else:
                        merged_intervals.append([tmin, tmax])
            for tmin, tmax in merged_intervals:
                start_x = x1 + ux * tmin
                start_y = y1 + uy * tmin
                end_x = x1 + ux * tmax
                end_y = y1 + uy * tmax
                new_seg = {
                    'start': (start_x, start_y, 0.0),
                    'end': (end_x, end_y, 0.0),
                    'color': collinear[0]['color'],
                    'layer': collinear[0]['layer'],
                    'handle': '|'.join([s['handle'] for s in collinear])
                }
                result.append(new_seg)
            work = rest
            merged = True
        result.extend(work)

    return result


def preprocess_cad_data(acad, pipe_layers: List[str], tolerance_mm: float) -> List[SimpleLine]:
    """
    主入口函数：从 AutoCAD 模型空间提取实体，进行预处理，返回模拟的直线段列表
    """
    tolerance = tolerance_mm
    model_space = acad.doc.ModelSpace

    # 第一步：拆分多段线为直线段，同时收集直线
    segments = []  # 每个元素为 dict: {'start': (x,y,z), 'end': (x,y,z), 'color': int, 'layer': str, 'handle': str}
    for entity in model_space:
        try:
            if entity.ObjectName not in ["AcDbPolyline", "AcDb2dPolyline", "AcDbLine"]:
                continue
            if entity.Layer not in pipe_layers:
                continue

            color = entity.Color
            layer = entity.Layer
            handle = entity.Handle

            if entity.ObjectName in ["AcDbPolyline", "AcDb2dPolyline"]:
                # 处理多段线：获取所有顶点
                coords = entity.Coordinates
                # 判断坐标维度
                if len(coords) % 2 == 0:
                    points = []
                    for i in range(0, len(coords), 2):
                        points.append((coords[i], coords[i+1], 0.0))
                else:
                    points = []
                    for i in range(0, len(coords), 3):
                        points.append((coords[i], coords[i+1], 0.0))
                # 生成相邻点之间的线段
                for i in range(len(points)-1):
                    seg = {
                        'start': points[i],
                        'end': points[i+1],
                        'color': color,
                        'layer': layer,
                        'handle': handle
                    }
                    segments.append(seg)
            elif entity.ObjectName == "AcDbLine":
                # 直线直接作为一段
                start = (entity.StartPoint[0], entity.StartPoint[1], 0.0)
                end = (entity.EndPoint[0], entity.EndPoint[1], 0.0)
                seg = {
                    'start': start,
                    'end': end,
                    'color': color,
                    'layer': layer,
                    'handle': handle
                }
                segments.append(seg)
        except Exception as e:
            logger.debug(f"预处理收集实体时忽略错误: {e}")
            continue

    logger.info(f"提取CAD实体完成: {len(segments)} 个线段")

    # 合并共线重合线段（仅 XY 平面）
    if segments:
        segments = merge_collinear_segments(segments, tolerance)
    logger.info(f"合并共线完成: {len(segments)} 个线段")

    # 第二步：收集所有端点（去重）
    points = []
    for seg in segments:
        points.append(seg['start'])
        points.append(seg['end'])
    # 去重
    unique_points = []
    for p in points:
        if not any(_point_equals(p, up, tolerance) for up in unique_points):
            unique_points.append(p)
    logger.info(f"点去重完成: {len(unique_points)} 个唯一端点")

    # 第三步：跨线分割
    new_segments = []
    for seg in segments:
        a = seg['start']
        b = seg['end']
        # 找出落在此线段内部的点（不包括端点）
        interior_points = []
        for p in unique_points:
            if _point_on_segment(p, a, b, tolerance) and not _point_equals(p, a, tolerance) and not _point_equals(p, b, tolerance):
                interior_points.append(p)
        if not interior_points:
            new_segments.append(seg)
        else:
            # 按沿线距离排序
            interior_points.sort(key=lambda p: _point_distance_along(p, a, b))
            prev = a
            for p in interior_points:
                new_segments.append({
                    'start': prev,
                    'end': p,
                    'color': seg['color'],
                    'layer': seg['layer'],
                    'handle': seg['handle']
                })
                prev = p
            new_segments.append({
                'start': prev,
                'end': b,
                'color': seg['color'],
                'layer': seg['layer'],
                'handle': seg['handle']
            })

    logger.info(f"内部点分割完成: {len(new_segments)} 个线段")

    # ========== 处理线段交叉（非端点） ==========
    # 辅助函数：计算二维线段交点（排除共线和端点）
    def segment_intersection(p1, p2, p3, p4, tol):
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = p3
        x4, y4 = p4
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-12:
            return None
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
        if 0 <= t <= 1 and 0 <= u <= 1:
            ix = x1 + t * (x2 - x1)
            iy = y1 + t * (y2 - y1)
            # 检查交点是否在线段内部（非端点）
            if (math.hypot(ix - x1, iy - y1) > tol and
                math.hypot(ix - x2, iy - y2) > tol and
                math.hypot(ix - x3, iy - y3) > tol and
                math.hypot(ix - x4, iy - y4) > tol):
                return (ix, iy)
        return None

    # 辅助函数：在交叉点处迭代分割线段
    def split_at_crossings(segments, tol):
        changed = True
        max_iter = 100
        iter_count = 0
        while changed and iter_count < max_iter:
            changed = False
            new_segs = []
            n = len(segments)
            for i in range(n):
                seg1 = segments[i]
                a = seg1['start'][:2]   # 取XY
                b = seg1['end'][:2]
                split_pts = []
                for j in range(n):
                    if i == j:
                        continue
                    seg2 = segments[j]
                    c = seg2['start'][:2]
                    d = seg2['end'][:2]
                    inter = segment_intersection(a, b, c, d, tol)
                    if inter is not None:
                        split_pts.append(inter)
                if split_pts:
                    # 去重
                    unique = []
                    for pt in split_pts:
                        if not any(_point_equals((pt[0], pt[1], 0), (up[0], up[1], 0), tol) for up in unique):
                            unique.append(pt)
                    if unique:
                        # 沿线段方向排序
                        dx = b[0] - a[0]
                        dy = b[1] - a[1]
                        def proj(p):
                            if abs(dx) > abs(dy):
                                return (p[0] - a[0]) / dx if abs(dx) > tol else 0
                            else:
                                return (p[1] - a[1]) / dy if abs(dy) > tol else 0
                        unique.sort(key=proj)
                        cur = a
                        cur_z = seg1['start'][2]
                        for pt in unique:
                            new_segs.append({
                                'start': (cur[0], cur[1], cur_z),
                                'end': (pt[0], pt[1], seg1['end'][2]),
                                'color': seg1['color'],
                                'layer': seg1['layer'],
                                'handle': seg1['handle']
                            })
                            cur = pt
                        # 最后一段
                        new_segs.append({
                            'start': (cur[0], cur[1], cur_z),
                            'end': (b[0], b[1], seg1['end'][2]),
                            'color': seg1['color'],
                            'layer': seg1['layer'],
                            'handle': seg1['handle']
                        })
                        changed = True
                    else:
                        new_segs.append(seg1)
                else:
                    new_segs.append(seg1)
            segments = new_segs
            iter_count += 1
        return segments

    # 执行交叉分割
    new_segments = split_at_crossings(new_segments, tolerance)
    logger.info(f"交叉分割完成: {len(new_segments)} 个线段")

    # ========== 交叉分割结束 ==========

    # 转换为 SimpleLine 对象
    result = [SimpleLine(seg['start'], seg['end'], seg['color'], seg['layer'], seg['handle']) for seg in new_segments]
    logger.info(f"转换SimpleLine完成: {len(result)} 个对象")
    return result

# 辅助几何函数
def _point_equals(p1, p2, tol):
    return math.hypot(p1[0]-p2[0], p1[1]-p2[1]) < tol and abs(p1[2]-p2[2]) < tol

def _point_on_segment(p, a, b, tol):
    ab = (b[0]-a[0], b[1]-a[1], b[2]-a[2])
    ap = (p[0]-a[0], p[1]-a[1], p[2]-a[2])
    ab_len_sq = ab[0]**2 + ab[1]**2 + ab[2]**2
    if ab_len_sq < 1e-12:
        return False
    t = (ap[0]*ab[0] + ap[1]*ab[1] + ap[2]*ab[2]) / ab_len_sq
    if t < 0 or t > 1:
        return False
    proj = (a[0] + t*ab[0], a[1] + t*ab[1], a[2] + t*ab[2])
    dist = math.sqrt((p[0]-proj[0])**2 + (p[1]-proj[1])**2 + (p[2]-proj[2])**2)
    return dist < tol

def _point_distance_along(p, a, b):
    ab = (b[0]-a[0], b[1]-a[1], b[2]-a[2])
    ap = (p[0]-a[0], p[1]-a[1], p[2]-a[2])
    ab_len_sq = ab[0]**2 + ab[1]**2 + ab[2]**2
    if ab_len_sq < 1e-12:
        return 0
    return (ap[0]*ab[0] + ap[1]*ab[1] + ap[2]*ab[2]) / ab_len_sq

def merge_pipes_at_valves(simple_lines: List[SimpleLine], acad, valve_block_names: list, tolerance_mm: float) -> List[SimpleLine]:
    """
    将被阀门图块打断的两条线段合并为一条
    """
    if acad is None:
        return simple_lines

    tolerance = tolerance_mm
    model_space = acad.doc.ModelSpace

    # 收集阀门插入点
    valves = []
    for entity in model_space:
        try:
            if entity.ObjectName != "AcDbBlockReference":
                continue
            if entity.Name not in valve_block_names:
                continue
            ins = entity.InsertionPoint
            valves.append((ins[0], ins[1], 0.0))
        except Exception as e:
            logger.debug(f"读取阀门图块时出错: {e}")
            continue

    logger.info(f"收集阀门完成: {len(valves)} 个")
    if not valves:
        return simple_lines

    used_indices = set()
    new_lines = []
    lines = list(simple_lines)

    def point_line_distance(px, py, x1, y1, x2, y2):
        if (x2 - x1) == 0 and (y2 - y1) == 0:
            return math.hypot(px - x1, py - y1)
        return abs((y2 - y1)*px - (x2 - x1)*py + x2*y1 - y2*x1) / math.hypot(y2 - y1, x2 - x1)

    def is_collinear(px, py, line):
        x1, y1 = line.StartPoint[0], line.StartPoint[1]
        x2, y2 = line.EndPoint[0], line.EndPoint[1]
        dist = point_line_distance(px, py, x1, y1, x2, y2)
        return dist < tolerance

    def min_endpoint_distance(px, py, line):
        x1, y1 = line.StartPoint[0], line.StartPoint[1]
        x2, y2 = line.EndPoint[0], line.EndPoint[1]
        d1 = math.hypot(px - x1, py - y1)
        d2 = math.hypot(px - x2, py - y2)
        return min(d1, d2)

    def far_endpoint(px, py, line):
        x1, y1 = line.StartPoint[0], line.StartPoint[1]
        x2, y2 = line.EndPoint[0], line.EndPoint[1]
        d1 = math.hypot(px - x1, py - y1)
        d2 = math.hypot(px - x2, py - y2)
        if d1 > d2:
            return (x1, y1, 0.0)
        else:
            return (x2, y2, 0.0)

    for vx, vy, vz in valves:
        candidates = []
        for idx, line in enumerate(lines):
            if idx in used_indices:
                continue
            if is_collinear(vx, vy, line):
                dist = min_endpoint_distance(vx, vy, line)
                candidates.append((idx, dist, line))
        if len(candidates) < 2:
            continue
        candidates.sort(key=lambda x: x[1])
        idx1, _, line1 = candidates[0]
        idx2, _, line2 = candidates[1]

        end1 = far_endpoint(vx, vy, line1)
        end2 = far_endpoint(vx, vy, line2)

        new_line = SimpleLine(
            start=end1,
            end=end2,
            color=line1.Color,
            layer=line1.Layer,
            handle=f"{line1.Handle}|{line2.Handle}",
            valve_pos=(vx, vy, vz)
        )
        new_lines.append(new_line)
        used_indices.add(idx1)
        used_indices.add(idx2)

    for idx, line in enumerate(lines):
        if idx not in used_indices:
            new_lines.append(line)

    logger.info(f"阀门合并完成: {len(lines)}→{len(new_lines)} 条")
    return new_lines


def preprocess_from_segments(segments, tolerance_mm):
    """
    从预提取的线段列表开始预处理（跳过 model_space 遍历），
    与 preprocess_cad_data 后续步骤完全一致。
    """
    tolerance = tolerance_mm

    # 合并共线重合线段
    if segments:
        segments = merge_collinear_segments(segments, tolerance)
    logger.info(f"合并共线完成: {len(segments)} 个线段")

    # 收集所有端点（去重）
    points = []
    for seg in segments:
        points.append(seg['start'])
        points.append(seg['end'])
    unique_points = []
    for p in points:
        if not any(_point_equals(p, up, tolerance) for up in unique_points):
            unique_points.append(p)
    logger.info(f"点去重完成: {len(unique_points)} 个唯一端点")

    # 内部点分割
    new_segments = []
    for seg in segments:
        a = seg['start']
        b = seg['end']
        interior_points = []
        for p in unique_points:
            if _point_on_segment(p, a, b, tolerance) and not _point_equals(p, a, tolerance) and not _point_equals(p, b, tolerance):
                interior_points.append(p)
        if not interior_points:
            new_segments.append(seg)
        else:
            interior_points.sort(key=lambda p: _point_distance_along(p, a, b))
            prev = a
            for p in interior_points:
                new_segments.append({
                    'start': prev,
                    'end': p,
                    'color': seg['color'],
                    'layer': seg['layer'],
                    'handle': seg['handle']
                })
                prev = p
            new_segments.append({
                'start': prev,
                'end': b,
                'color': seg['color'],
                'layer': seg['layer'],
                'handle': seg['handle']
            })
    logger.info(f"内部点分割完成: {len(new_segments)} 个线段")

    # 交叉分割
    def segment_intersection(p1, p2, p3, p4, tol):
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = p3
        x4, y4 = p4
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-12:
            return None
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
        if 0 <= t <= 1 and 0 <= u <= 1:
            ix = x1 + t * (x2 - x1)
            iy = y1 + t * (y2 - y1)
            if (math.hypot(ix - x1, iy - y1) > tol and
                math.hypot(ix - x2, iy - y2) > tol and
                math.hypot(ix - x3, iy - y3) > tol and
                math.hypot(ix - x4, iy - y4) > tol):
                return (ix, iy)
        return None

    def split_at_crossings(segs, tol):
        changed = True
        max_iter = 100
        iter_count = 0
        while changed and iter_count < max_iter:
            changed = False
            new_segs = []
            n = len(segs)
            for i in range(n):
                seg1 = segs[i]
                a = seg1['start'][:2]
                b = seg1['end'][:2]
                split_pts = []
                for j in range(n):
                    if i == j:
                        continue
                    seg2 = segs[j]
                    c = seg2['start'][:2]
                    d = seg2['end'][:2]
                    inter = segment_intersection(a, b, c, d, tol)
                    if inter is not None:
                        split_pts.append(inter)
                if split_pts:
                    unique = []
                    for pt in split_pts:
                        if not any(_point_equals((pt[0], pt[1], 0), (up[0], up[1], 0), tol) for up in unique):
                            unique.append(pt)
                    if unique:
                        dx = b[0] - a[0]
                        dy = b[1] - a[1]
                        def proj(p):
                            if abs(dx) > abs(dy):
                                return (p[0] - a[0]) / dx if abs(dx) > tol else 0
                            else:
                                return (p[1] - a[1]) / dy if abs(dy) > tol else 0
                        unique.sort(key=proj)
                        cur = a
                        cur_z = seg1['start'][2]
                        for pt in unique:
                            new_segs.append({
                                'start': (cur[0], cur[1], cur_z),
                                'end': (pt[0], pt[1], seg1['end'][2]),
                                'color': seg1['color'],
                                'layer': seg1['layer'],
                                'handle': seg1['handle']
                            })
                            cur = pt
                        new_segs.append({
                            'start': (cur[0], cur[1], cur_z),
                            'end': (b[0], b[1], seg1['end'][2]),
                            'color': seg1['color'],
                            'layer': seg1['layer'],
                            'handle': seg1['handle']
                        })
                        changed = True
                    else:
                        new_segs.append(seg1)
                else:
                    new_segs.append(seg1)
            segs = new_segs
            iter_count += 1
        return segs

    new_segments = split_at_crossings(new_segments, tolerance)
    logger.info(f"交叉分割完成: {len(new_segments)} 个线段")

    # 转 SimpleLine
    result = [SimpleLine(seg['start'], seg['end'], seg['color'], seg['layer'], seg['handle']) for seg in new_segments]
    logger.info(f"转换SimpleLine完成: {len(result)} 个对象")
    return result


def merge_pipes_at_valves_from_points(simple_lines, valve_points, tolerance_mm):
    """
    从预提取的阀门点列表开始合并（跳过 model_space 遍历），
    与 merge_pipes_at_valves 后续处理完全一致。
    valve_points: [(x, y, z), ...] 列表
    """
    tolerance = tolerance_mm

    if not valve_points:
        return simple_lines

    used_indices = set()
    new_lines = []
    lines = list(simple_lines)

    def point_line_distance(px, py, x1, y1, x2, y2):
        if (x2 - x1) == 0 and (y2 - y1) == 0:
            return math.hypot(px - x1, py - y1)
        return abs((y2 - y1)*px - (x2 - x1)*py + x2*y1 - y2*x1) / math.hypot(y2 - y1, x2 - x1)

    def is_collinear(px, py, line):
        x1, y1 = line.StartPoint[0], line.StartPoint[1]
        x2, y2 = line.EndPoint[0], line.EndPoint[1]
        dist = point_line_distance(px, py, x1, y1, x2, y2)
        return dist < tolerance

    def min_endpoint_distance(px, py, line):
        x1, y1 = line.StartPoint[0], line.StartPoint[1]
        x2, y2 = line.EndPoint[0], line.EndPoint[1]
        d1 = math.hypot(px - x1, py - y1)
        d2 = math.hypot(px - x2, py - y2)
        return min(d1, d2)

    def far_endpoint(px, py, line):
        x1, y1 = line.StartPoint[0], line.StartPoint[1]
        x2, y2 = line.EndPoint[0], line.EndPoint[1]
        d1 = math.hypot(px - x1, py - y1)
        d2 = math.hypot(px - x2, py - y2)
        if d1 > d2:
            return (x1, y1, 0.0)
        else:
            return (x2, y2, 0.0)

    for vx, vy, vz in valve_points:
        candidates = []
        for idx, line in enumerate(lines):
            if idx in used_indices:
                continue
            if is_collinear(vx, vy, line):
                dist = min_endpoint_distance(vx, vy, line)
                candidates.append((idx, dist, line))
        if len(candidates) < 2:
            continue
        candidates.sort(key=lambda x: x[1])
        idx1, _, line1 = candidates[0]
        idx2, _, line2 = candidates[1]

        end1 = far_endpoint(vx, vy, line1)
        end2 = far_endpoint(vx, vy, line2)

        new_line = SimpleLine(
            start=end1,
            end=end2,
            color=line1.Color,
            layer=line1.Layer,
            handle=f"{line1.Handle}|{line2.Handle}",
            valve_pos=(vx, vy, vz)
        )
        new_lines.append(new_line)
        used_indices.add(idx1)
        used_indices.add(idx2)

    for idx, line in enumerate(lines):
        if idx not in used_indices:
            new_lines.append(line)

    logger.info(f"阀门合并完成: {len(lines)}->{len(new_lines)} 条")
    return new_lines
