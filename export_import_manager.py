"""
管网项目导出/导入管理器

支持将完整的管网模型（含计算结果、用户设置、显示状态）导出为自包含的JSON文件目录，
也可从导出的目录完整恢复程序状态，无需依赖原始CAD文件。
"""
import os
import json
import copy
import logging
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime
import dataclasses
import numpy as np
import zipfile
import tempfile
import shutil

from gui.preview_module import MaintenanceZone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 每种数据类中的 tuple 字段（JSON不支持tuple，需转换）
# ---------------------------------------------------------------------------
_TUPLE_FIELDS_MAP: Dict[str, set] = {
    "PipeData": {"start_point", "end_point"},
    "FloorData": {"align_point", "rect_min", "rect_max"},
}

# PipeData 上运行时动态添加的非dataclass属性
_PIPE_EXTRA_ATTRS = [
    "display_text", "flow_value", "show_arrow",
    "original_riser_id", "is_hydrant_branch",
]


# ---------------------------------------------------------------------------
# 序列化/反序列化工具函数
# ---------------------------------------------------------------------------

def _tuples_to_lists(d: dict, cls_name: str) -> dict:
    """将字典中的tuple值转为list（原地修改）。"""
    tuple_fields = _TUPLE_FIELDS_MAP.get(cls_name, set())
    for k in tuple_fields:
        if k in d and isinstance(d[k], tuple):
            d[k] = list(d[k])
    return d


def _lists_to_tuples(d: dict, cls_name: str) -> dict:
    """将字典中的list值转为tuple（原地修改）。"""
    tuple_fields = _TUPLE_FIELDS_MAP.get(cls_name, set())
    for k in tuple_fields:
        if k in d and isinstance(d[k], list):
            d[k] = tuple(d[k])
    return d


def _dataclass_to_dict(obj, cls_name: str) -> dict:
    """dataclass → dict，处理tuple→list转换。"""
    d = dataclasses.asdict(obj)
    _tuples_to_lists(d, cls_name)
    return d


def _dict_to_dataclass(cls, data: dict, cls_name: str):
    """dict → dataclass，处理list→tuple转换。"""
    d = copy.deepcopy(data)
    _lists_to_tuples(d, cls_name)
    # 移除 _extra_attrs（如果存在），它不是dataclass字段
    d.pop("_extra_attrs", None)
    return cls(**d)


def _collect_pipe_extra_attrs(pipe) -> Optional[dict]:
    """收集PipeData上不在dataclass定义中的动态属性。"""
    extra = {}
    for attr in _PIPE_EXTRA_ATTRS:
        if hasattr(pipe, attr):
            val = getattr(pipe, attr)
            if val is not None:
                extra[attr] = val
    return extra if extra else None


def _restore_pipe_extra_attrs(pipe, extra: Optional[dict]):
    """恢复PipeData的动态属性。"""
    if extra:
        for k, v in extra.items():
            setattr(pipe, k, v)


# ---------------------------------------------------------------------------
# ProjectExporter —— 导出
# ---------------------------------------------------------------------------

class NumpyEncoder(json.JSONEncoder):
    """自定义JSON编码器，处理numpy数值类型"""
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

class ProjectExporter:
    """将程序当前完整状态导出到目录。"""

    def __init__(self, cad_data_manager,
                 config_manager,
                 material_manager,
                 settings_page=None,
                 preview_page=None,
                 calculation_page=None):
        self.cdm = cad_data_manager
        self.cfg = config_manager
        self.mat = material_manager
        self.settings_page = settings_page
        self.preview_page = preview_page
        self.calc_page = calculation_page

    # ---- 主入口 ----

    def _write_json(self, filename: str, data: Any):
        path = os.path.join(self._current_target, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)

    def export_project(self, target_dir: str) -> str:
        """执行完整导出，返回导出目录路径。"""
        os.makedirs(target_dir, exist_ok=True)
        self._current_target = target_dir

        self._write_json("manifest.json", self._export_manifest())
        self._write_json("cad_data.json", self._export_cad_data())
        self._write_json("config.json", self._export_config())
        self._write_json("materials.json", self._export_materials())

        if self.preview_page:
            self._write_json("floor_colors.json", self._export_floor_colors())
            self._write_json("preview_state.json", self._export_preview_state())
            self._write_json("selection_state.json", self._export_selection_state())

        if self.calc_page:
            results = self._export_calc_results()
            if results is not None:
                self._write_json("calc_results.json", results)

        logger.info(f"项目已导出到: {target_dir}")
        return target_dir

    def export_to_zip(self, zip_path: str, model_name: str = None) -> str:
        """导出到ZIP文件"""
        import tempfile
        import zipfile
        import shutil
        
        tmp_dir = tempfile.mkdtemp(prefix="pipe_loss_export_")
        try:
            target_dir = os.path.join(tmp_dir, model_name or "project")
            self.export_project(target_dir)
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(target_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, os.path.dirname(target_dir))
                        zf.write(file_path, arcname)
            logger.info(f"项目已导出到ZIP: {zip_path}")
            return zip_path
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ---- 各导出方法 ----

    def _export_manifest(self) -> dict:
        cdm = self.cdm
        has_calc = (
            self.calc_page is not None
            and hasattr(self.calc_page, "original_results")
            and self.calc_page.original_results is not None
        )
        return {
            "version": "1.0",
            "export_timestamp": datetime.now().isoformat(),
            "cad_file_path": cdm.cad_file_path or "",
            "cad_file_name": os.path.basename(cdm.cad_file_path) if cdm.cad_file_path else "",
            "scheme_name": self.cfg.current_scheme,
            "has_calculation": has_calc,
            "pipes_count": len(cdm.pipes),
            "nodes_count": len(cdm.nodes),
            "valves_count": len(cdm.valves),
            "hydrants_count": len(cdm.hydrants),
            "risers_count": len(cdm.risers),
            "floors_count": len(cdm.floors),
        }

    def _export_cad_data(self) -> dict:
        cdm = self.cdm

        # 辅助：序列化dataclass列表
        def _serialize_list(items, cls_name):
            result = []
            for obj in items:
                d = _dataclass_to_dict(obj, cls_name)
                # 收集PipeData动态属性
                if cls_name == "PipeData":
                    extra = _collect_pipe_extra_attrs(obj)
                    if extra:
                        d["_extra_attrs"] = extra
                result.append(d)
            return result

        # 楼层存ID列表而非对象引用
        floor_pipe_ids = {}
        floor_node_ids = {}
        floor_hydrant_ids = {}
        for floor in cdm.floors:
            floor_pipe_ids[floor.name] = [p.pipe_id for p in floor.pipes]
            floor_node_ids[floor.name] = [n.node_id for n in floor.nodes]
            floor_hydrant_ids[floor.name] = [h.hydrant_id for h in floor.hydrants]

        floors_data = []
        for floor in cdm.floors:
            fd = _dataclass_to_dict(floor, "FloorData")
            # 移除引用列表（已转为ID）
            fd.pop("pipes", None)
            fd.pop("nodes", None)
            fd.pop("hydrants", None)
            floors_data.append(fd)

        # 将duplicate_risers_by_floor中的RiserData转为ID
        dup_risers = {}
        for fname, risers in cdm.duplicate_risers_by_floor.items():
            dup_risers[fname] = [r.riser_id for r in risers]

        # duplicate_pipe_ids_by_floor中set不能直接序列化
        dup_pipes = {}
        for fname, pids in cdm.duplicate_pipe_ids_by_floor.items():
            dup_pipes[fname] = list(pids)

        return {
            "pipes": _serialize_list(cdm.pipes, "PipeData"),
            "nodes": _serialize_list(cdm.nodes, "NodeData"),
            "supply_nodes": _serialize_list(cdm.supply_nodes, "SupplyNodeData"),
            "demand_groups": {
                gid: _dataclass_to_dict(grp, "DemandGroupData")
                for gid, grp in cdm.demand_groups.items()
            },
            "valves": _serialize_list(cdm.valves, "ValveData"),
            "hydrants": _serialize_list(cdm.hydrants, "HydrantData"),
            "risers": _serialize_list(cdm.risers, "RiserData"),
            "floors": floors_data,
            "floor_pipe_ids": floor_pipe_ids,
            "floor_node_ids": floor_node_ids,
            "floor_hydrant_ids": floor_hydrant_ids,
            "grouped_floors_map": copy.deepcopy(cdm.grouped_floors_map),
            "duplicate_risers_by_floor": dup_risers,
            "duplicate_pipe_ids_by_floor": dup_pipes,
            "cad_file_path": cdm.cad_file_path or "",
            "is_loaded": cdm.is_loaded,
            "preprocess_enabled": getattr(cdm, "preprocess_enabled", False),
            "default_color256_diameter": cdm.default_color256_diameter,
        }

    def _export_config(self) -> dict:
        """获取当前设置页面的内存配置。"""
        if self.settings_page and hasattr(self.settings_page, "current_config"):
            return copy.deepcopy(self.settings_page.current_config)
        return copy.deepcopy(self.cfg.get_current_config())

    def _export_materials(self) -> dict:
        return {"materials": copy.deepcopy(self.mat.materials)}

    def _export_floor_colors(self) -> dict:
        pp = self.preview_page
        if hasattr(pp, "get_state_for_export"):
            state = pp.get_state_for_export()
            return {
                "layer_colors_enabled": state.get("layer_colors_enabled", False),
                "color_list": state.get("color_list", []),
                "floor_color_map": state.get("floor_color_map", {}),
                "pipe_floor_map": state.get("pipe_floor_map", {}),
            }
        # 后备：直接访问
        return {
            "layer_colors_enabled": pp.layer_colors_enabled.get(),
            "color_list": copy.deepcopy(pp.layer_color_list),
            "floor_color_map": copy.deepcopy(pp.floor_color_map),
            "pipe_floor_map": copy.deepcopy(pp.pipe_floor_map),
        }

    def _export_preview_state(self) -> dict:
        pp = self.preview_page
        if hasattr(pp, "get_state_for_export"):
            state = pp.get_state_for_export()
            # 提取除颜色和选择集外的显示状态
            return {k: v for k, v in state.items()
                    if k not in ("color_list", "floor_color_map", "pipe_floor_map",
                                 "layer_colors_enabled", "selected_pipes",
                                 "selected_valve_id", "problem_pipes",
                                 "reachable_pipes", "undo_count", "redo_count")}
        # 后备：直接访问
        return {
            "separation_values": copy.deepcopy(pp.separation_values),
            "_separation_applied": pp._separation_applied,
            "show_nominal": pp.show_nominal.get(),
            "show_length": pp.show_length.get(),
            "show_flow": pp.show_flow.get(),
            "show_loss": pp.show_loss.get(),
            "show_arrow": pp.show_arrow.get(),
            "show_node_ids": pp.show_node_ids.get(),
            "show_pipe_id": pp.show_pipe_id.get(),
            "show_elevation": pp.show_elevation.get(),
            "show_node_pressure": pp.show_node_pressure.get(),
            "show_occlusion_var": pp.show_occlusion_var.get(),
            "show_riser_warning": pp.show_riser_warning.get(),
            "show_zero_flow_label_var": pp.show_zero_flow_label_var.get(),
            "hide_invalid_var": pp.hide_invalid_var.get(),
            "real_time": pp.real_time.get(),
            "current_view_mode": pp.current_view_mode,
            "global_view_angle": pp.global_view_angle,
            "global_view_elevation": pp.global_view_elevation,
            "global_view_elevation_var": pp.global_view_elevation_var.get(),
            "current_floor_name": pp.current_floor_name,
            "current_scale": pp.scale,
            "current_translate_x": pp.translate_x,
            "current_translate_y": pp.translate_y,            
            "floor_view_state": {
                k: list(v) if isinstance(v, tuple) else v
                for k, v in pp.floor_view_state.items()
            },
        }

    def _export_calc_results(self) -> Optional[dict]:
        cp = self.calc_page
        if hasattr(cp, "get_state_for_export"):
            return cp.get_state_for_export()
        # 后备：直接访问
        if not hasattr(cp, "original_results") or cp.original_results is None:
            return None

        def _clean(obj):
            if isinstance(obj, dict):
                return {k: _clean(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_clean(v) for v in obj]
            if hasattr(obj, "item"):
                return obj.item()
            return obj

        return {
            "original_results": _clean(cp.original_results),
            "pipe_display_data": _clean(getattr(cp, "pipe_display_data", [])),
            "all_paths_for_preview": _clean(getattr(cp, "all_paths_for_preview", [])),
            "node_total_loss": _clean(getattr(cp, "node_total_loss", {})),
            "show_flow_in_m3h": cp.show_flow_in_m3h,
            "show_pressure_in_mpa": cp.show_pressure_in_mpa,
            "show_zero_flow_var": cp.show_zero_flow_var.get(),
        }

    def _export_selection_state(self) -> dict:
        pp = self.preview_page
        if hasattr(pp, "get_state_for_export"):
            state = pp.get_state_for_export()
            return {
                "selected_pipes": state.get("selected_pipes", []),
                "selected_valve_id": state.get("selected_valve_id"),
                "problem_pipes": state.get("problem_pipes", []),
                "reachable_pipes": state.get("reachable_pipes", []),
                "undo_count": state.get("undo_count", 0),
                "redo_count": state.get("redo_count", 0),
            }
        # 后备
        return {
            "selected_pipes": list(pp.selected_pipes),
            "selected_valve_id": pp.selected_valve_id,
            "problem_pipes": list(pp.problem_pipes),
            "reachable_pipes": list(pp.reachable_pipes),
            "undo_count": len(pp.undo_stack),
            "redo_count": len(pp.redo_stack),
        }


# ---------------------------------------------------------------------------
# ProjectImporter —— 导入
# ---------------------------------------------------------------------------

class ProjectImporter:
    """从导出目录恢复程序完整状态。"""

    def __init__(self, cad_data_manager,
                 config_manager,
                 material_manager,
                 app_instance=None):
        self.cdm = cad_data_manager
        self.cfg = config_manager
        self.mat = material_manager
        self.app = app_instance

    # ---- 主入口 ----

    def import_project(self, export_dir: str) -> bool:
        """从导出目录完整恢复状态。"""
        # 1. 验证
        manifest = self._read_json(export_dir, "manifest.json")
        if manifest is None:
            logger.error("导入失败：manifest.json 不存在或损坏")
            return False

        if manifest.get("version", "") != "1.0":
            logger.warning(f"导出版本 {manifest.get('version')} 与当前版本 1.0 不一致，尝试导入")

        # 2. 按顺序加载
        cad_data = self._read_json(export_dir, "cad_data.json")
        if cad_data is None:
            logger.error("导入失败：cad_data.json 不存在或损坏")
            return False

        self._load_cad_data(cad_data)

        config_data = self._read_json(export_dir, "config.json")
        if config_data:
            self._load_config(config_data)

        materials_data = self._read_json(export_dir, "materials.json")
        if materials_data:
            self._load_materials(materials_data)

        floor_colors = self._read_json(export_dir, "floor_colors.json")
        if floor_colors:
            self._load_floor_colors(floor_colors)

        preview_state = self._read_json(export_dir, "preview_state.json")
        if preview_state:
            self._load_preview_state(preview_state)

        calc_data = self._read_json(export_dir, "calc_results.json")
        if calc_data:
            self._load_calc_results(calc_data)

        selection_state = self._read_json(export_dir, "selection_state.json")
        if selection_state:
            self._load_selection_state(selection_state)

        # 3. 标记导入模式
        self.cdm.is_loaded = True
        self.cdm.acad = None  # 导入模式无CAD连接

        logger.info(f"项目已从 {export_dir} 导入成功")
        return True

    def import_from_zip(self, zip_path: str) -> bool:
        """从ZIP文件导入项目"""
        import tempfile
        import zipfile
        import shutil
        
        tmp_dir = tempfile.mkdtemp(prefix="pipe_loss_import_")
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(tmp_dir)
            
            export_dir = tmp_dir
            manifest_path = os.path.join(tmp_dir, "manifest.json")
            if not os.path.exists(manifest_path):
                items = [d for d in os.listdir(tmp_dir)
                        if os.path.isdir(os.path.join(tmp_dir, d))]
                if items:
                    export_dir = os.path.join(tmp_dir, items[0])
            
            return self.import_project(export_dir)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _read_json(self, export_dir: str, filename: str) -> Optional[dict]:
        path = os.path.join(export_dir, filename)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取 {filename} 失败: {e}")
            return None

    # ---- 数据加载方法 ----

    def _load_cad_data(self, data: dict):
        """从cad_data.json重建所有数据对象和索引。"""
        cdm = self.cdm

        # 1. 清空所有
        cdm.clear_all_data()

        # 延迟导入避免循环依赖
        from cad_data_manager import (
            PipeData, NodeData, SupplyNodeData,
            DemandNodeData, DemandGroupData,
            ValveData, HydrantData, RiserData, FloorData,
        )

        # 2. 重建主列表
        for item in data.get("pipes", []):
            extra = item.pop("_extra_attrs", None)
            pipe = _dict_to_dataclass(PipeData, item, "PipeData")
            _restore_pipe_extra_attrs(pipe, extra)
            cdm.pipes.append(pipe)
            cdm.pipe_by_id[pipe.pipe_id] = pipe

        for item in data.get("nodes", []):
            node = _dict_to_dataclass(NodeData, item, "NodeData")
            cdm.nodes.append(node)
            cdm.node_by_id[node.node_id] = node

        for item in data.get("supply_nodes", []):
            sn = _dict_to_dataclass(SupplyNodeData, item, "SupplyNodeData")
            cdm.supply_nodes.append(sn)

        # 用水点组（含嵌套DemandNodeData）
        for gid, gdata in data.get("demand_groups", {}).items():
            nodes_data = gdata.pop("demand_nodes", [])
            demand_nodes = []
            for nd in nodes_data:
                dn = _dict_to_dataclass(DemandNodeData, nd, "DemandNodeData")
                demand_nodes.append(dn)
            gdata["demand_nodes"] = demand_nodes
            grp = _dict_to_dataclass(DemandGroupData, gdata, "DemandGroupData")
            grp.demand_nodes = demand_nodes  # 确保引用正确
            cdm.demand_groups[gid] = grp

        for item in data.get("valves", []):
            v = _dict_to_dataclass(ValveData, item, "ValveData")
            cdm.valves.append(v)
            cdm.valve_by_id[v.valve_id] = v

        for item in data.get("hydrants", []):
            h = _dict_to_dataclass(HydrantData, item, "HydrantData")
            cdm.hydrants.append(h)
            cdm.hydrant_by_id[h.hydrant_id] = h

        for item in data.get("risers", []):
            r = _dict_to_dataclass(RiserData, item, "RiserData")
            cdm.risers.append(r)
            cdm.riser_by_id[r.riser_id] = r

        # 3. 重建楼层（先建空楼层，再填充引用）
        floor_pipe_ids = data.get("floor_pipe_ids", {})
        floor_node_ids = data.get("floor_node_ids", {})
        floor_hydrant_ids = data.get("floor_hydrant_ids", {})

        for fdata in data.get("floors", []):
            fname = fdata["name"]
            # 移除自动生成的 fields（dataclass 的 field 默认值）
            fdata.pop("pipes", None)
            fdata.pop("nodes", None)
            fdata.pop("hydrants", None)
            floor = _dict_to_dataclass(FloorData, fdata, "FloorData")

            # 按ID恢复引用
            floor.pipes = [
                cdm.pipe_by_id[pid]
                for pid in floor_pipe_ids.get(fname, [])
                if pid in cdm.pipe_by_id
            ]
            floor.nodes = [
                cdm.node_by_id[nid]
                for nid in floor_node_ids.get(fname, [])
                if nid in cdm.node_by_id
            ]
            floor.hydrants = [
                cdm.hydrant_by_id[hid]
                for hid in floor_hydrant_ids.get(fname, [])
                if hid in cdm.hydrant_by_id
            ]
            cdm.floors.append(floor)
            cdm.floor_by_name[fname] = floor

        # 4. 恢复其他状态
        cdm.grouped_floors_map = data.get("grouped_floors_map", {})
        cdm.duplicate_risers_by_floor = data.get("duplicate_risers_by_floor", {})
        cdm.duplicate_pipe_ids_by_floor = {}
        for fname, pids in data.get("duplicate_pipe_ids_by_floor", {}).items():
            cdm.duplicate_pipe_ids_by_floor[fname] = set(pids)

        cdm.cad_file_path = data.get("cad_file_path", "")
        cdm.preprocess_enabled = data.get("preprocess_enabled", False)
        cdm.default_color256_diameter = data.get("default_color256_diameter")

    def _load_config(self, data: dict):
        """恢复配置到ConfigManager。"""
        # 用导入的配置覆盖"临时方案"，确保下次启动可见
        self.cfg.save_temp_scheme(copy.deepcopy(data))
        # 同时设为live_config
        self.cfg.set_live_config(copy.deepcopy(data))

    def _load_materials(self, data: dict):
        """恢复管材数据。"""
        materials = data.get("materials", {})
        if materials:
            self.mat.materials = copy.deepcopy(materials)
            self.mat.save_materials()

    def _load_floor_colors(self, data: dict):
        """恢复分层颜色到PreviewPage。"""
        pp = self.app.pages.get("管网预览") if self.app else None
        if pp is None:
            return
        if "color_list" in data:
            pp.layer_color_list = copy.deepcopy(data["color_list"])
        if "floor_color_map" in data:
            pp.floor_color_map = copy.deepcopy(data["floor_color_map"])
        if "pipe_floor_map" in data:
            pp.pipe_floor_map = copy.deepcopy(data["pipe_floor_map"])
        if "layer_colors_enabled" in data:
            pp.layer_colors_enabled.set(data["layer_colors_enabled"])

    def _load_preview_state(self, data: dict):
        """恢复管网预览显示状态。"""
        pp = self.app.pages.get("管网预览") if self.app else None
        if pp is None:
            return

        if "separation_values" in data:
            pp.separation_values = data["separation_values"]
        pp._separation_applied = data.get("_separation_applied", False)

        # BooleanVar 恢复
        bool_vars = {
            "show_nominal": pp.show_nominal,
            "show_length": pp.show_length,
            "show_flow": pp.show_flow,
            "show_loss": pp.show_loss,
            "show_arrow": pp.show_arrow,
            "show_node_ids": pp.show_node_ids,
            "show_pipe_id": pp.show_pipe_id,
            "show_elevation": pp.show_elevation,
            "show_node_pressure": pp.show_node_pressure,
            "show_occlusion_var": pp.show_occlusion_var,
            "show_riser_warning": pp.show_riser_warning,
            "show_zero_flow_label_var": pp.show_zero_flow_label_var,
            "hide_invalid_var": pp.hide_invalid_var,
            "real_time": pp.real_time,
        }
        for key, var in bool_vars.items():
            if key in data:
                var.set(data[key])

        # if "current_view_mode" in data:
        #     pp.current_view_mode = data["current_view_mode"]
        if "global_view_angle" in data:
            pp.global_view_angle = data["global_view_angle"]
        if "global_view_elevation" in data:
            pp.global_view_elevation = data["global_view_elevation"]
        if "global_view_elevation_var" in data:
            pp.global_view_elevation_var.set(data["global_view_elevation_var"])
        if "current_floor_name" in data:
            pp.current_floor_name = data["current_floor_name"]
        if "current_scale" in data:
            pp.scale = data["current_scale"]
            pp.translate_x = data["current_translate_x"]
            pp.translate_y = data["current_translate_y"]
            pp.floor_view_state[data["current_floor_name"]] = (
                data["current_scale"],
                data["current_translate_x"],
                data["current_translate_y"]
            )        
        if "floor_view_state" in data:
            pp.floor_view_state = {
                k: tuple(v) if isinstance(v, list) else v
                for k, v in data["floor_view_state"].items()
            }

        pp._sep_cache_key = None
        pp._cached_grouped_floors_map = {}

        # 检修区恢复
        if "maintenance_zones" in data:
            pp.maintenance_zones = [
                MaintenanceZone(
                    zone_id=z["zone_id"],
                    pipe_ids=set(z["pipe_ids"]),
                    valve_ids=set(z["valve_ids"]),
                    node_ids=set(z["node_ids"]),
                )
                for z in data["maintenance_zones"]
            ]
        if "_next_zone_id" in data:
            pp._next_zone_id = data["_next_zone_id"]

    def _load_calc_results(self, data: dict):
        """恢复计算结果到CalculationPage。"""
        cp = self.app.pages.get("计算") if self.app else None
        if cp is None:
            return

        if "original_results" in data:
            cp.original_results = data["original_results"]
            cp.pipe_display_data = data.get("pipe_display_data", [])
            cp.all_paths_for_preview = data.get("all_paths_for_preview", [])
            cp.node_total_loss = data.get("node_total_loss", {})
            cp.show_flow_in_m3h = data.get("show_flow_in_m3h", False)
            cp.show_pressure_in_mpa = data.get("show_pressure_in_mpa", False)
            cp.show_zero_flow_var.set(data.get("show_zero_flow_var", False))
            cp.flow_unit_var.set(cp.show_flow_in_m3h)
            cp.pressure_unit_var.set(cp.show_pressure_in_mpa)

            # 触发UI刷新
            if hasattr(cp, "display_results") and cp.original_results:
                cp.display_results(cp.original_results)
                cp.calculate_btn.config(state="normal")
                cp.export_btn.config(state="normal")

    def _load_selection_state(self, data: dict):
        """恢复选择集和编辑状态。"""
        pp = self.app.pages.get("管网预览") if self.app else None
        if pp is None:
            return
        pp.selected_pipes = set(data.get("selected_pipes", []))
        pp.selected_valve_id = data.get("selected_valve_id")
        pp.problem_pipes = set(data.get("problem_pipes", []))
        pp.reachable_pipes = set(data.get("reachable_pipes", []))
        # 撤销栈无法恢复，清空
        pp.undo_stack.clear()
        pp.redo_stack.clear()
