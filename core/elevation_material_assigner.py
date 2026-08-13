# core/elevation_material_assigner.py
"""
标高管材分段分配器（纯函数，零依赖）

加压管网中水泵向上供水需克服重力：底部管道压力最大、顶部压力最小。
因此用户按标高分段指定管材时，低标高层应使用承压能力更高的管材。

安全规则：每层管道覆盖的标高区间为 [本层楼面标高, 上层楼面标高)，
区间内最低点（本层楼面标高）处压力最大 —— 取"本层楼面标高所在分段"的管材，
即把用户的分段边界自动"吸附"到楼面标高，避免楼层管道跨越分界线导致承压不足爆管。

例：≤15m 无缝、15<H≤40m 加厚、>40m 镀锌；
    4 层楼面 13m、5 层楼面 17m → 4 层 [13,17) 跨 15m 线 → 取无缝（等效加厚下限吸附到 17m）；
    10 层管道部分超过 40m → 10 层楼面落在加厚段 → 取加厚（等效加厚上限吸附到 11 层楼面）。

匹配规则：lower < H ≤ upper（与工程习惯一致，如 15<H≤40）。
标高端留空（None）视为 ±∞；管材留空的分段跳过（不生效）。
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _make_floor_key(building_id: str, floor_name: str) -> str:
    return f"{building_id}|{floor_name}" if building_id else floor_name


def _match_segment(segments: List[Dict], elevation_m: float) -> Optional[Dict]:
    """楼面标高所在分段（lower < H ≤ upper）。无命中返回 None"""
    for seg in segments:
        material = (seg.get("material") or "").strip()
        if not material:
            continue
        lower = seg.get("lower")
        upper = seg.get("upper")
        if lower is not None and elevation_m <= lower:
            continue
        if upper is not None and elevation_m > upper:
            continue
        return seg
    return None


def assign_elevation_materials(cdm, segments: List[Dict],
                               outdoor_material: str = "") -> Dict[str, str]:
    """按标高管材分段计算各管道应使用的管材。

    Args:
        cdm: CADDataManager（需有 floors / floor_by_name / pipes / pipe_by_id）
        segments: [{material, lower, upper}]，承压低→高行序（行序仅展示，匹配按标高区间）；
                  管材空 = 该分段不生效；lower/upper None = ±∞。
        outdoor_material: 室外管网楼层（building_id == "ZT"）使用的管材；空字符串表示保持原管材。

    Returns:
        {pipe_id: material} —— 仅包含需要改变管材的管道；
        未命中分段的楼层管道、无楼层归属管道不返回（保持原管材）。
    """
    if not cdm or not getattr(cdm, "floors", None):
        return {}
    if not segments and not outdoor_material:
        return {}

    # 楼面标高所在分段的管材：{楼层key: material}
    floor_material: Dict[str, str] = {}
    for floor in cdm.floors:
        fkey = _make_floor_key(floor.building_id or "", floor.name)
        # 室外管网楼层：单独管材（无标高分段）
        if (floor.building_id or "") == "ZT" or floor.name == "室外管网":
            if outdoor_material and outdoor_material.strip():
                floor_material[fkey] = outdoor_material.strip()
            continue
        seg = _match_segment(segments, floor.elevation)
        if seg:
            floor_material[fkey] = seg["material"].strip()

    # 管道 → 楼层归属（floor.pipes 已含立管段）
    result: Dict[str, str] = {}
    for floor in cdm.floors:
        fkey = _make_floor_key(floor.building_id or "", floor.name)
        mat = floor_material.get(fkey)
        if not mat:
            continue
        for pipe in getattr(floor, "pipes", []):
            if not pipe or not pipe.is_active:
                continue
            if pipe.pipe_id in result:
                continue
            if pipe.material != mat:
                result[pipe.pipe_id] = mat

    logger.info(f"标高管材分配完成: 共 {len(result)} 条管道需要更换管材")
    return result
