"""
EPANET结果解析器（WNTR增强版）
支持从 WNTR 结果对象直接解析
"""
import os
import re
from typing import Dict, List, Tuple, Any, Optional
import logging
import pandas as pd

logger = logging.getLogger(__name__)

class ResultParser:
    """EPANET结果解析器（支持WNTR）"""
    
    def __init__(self, cad_data_manager=None):
        self.results = {}
        self.cad_data_manager = cad_data_manager
        
    def parse_report_file(self, rpt_file: str, results_obj=None, wn=None) -> Tuple[bool, str, Dict]:
        """
        解析EPANET报告文件或 WNTR 结果对象
        
        Args:
            rpt_file: 报告文件路径（如果提供了 results_obj 和 wn，此参数可忽略）
            results_obj: WNTR 模拟结果对象（SimulationResults）
            wn: WNTR 管网模型对象（WaterNetworkModel）
            
        Returns:
            (success, message, results_dict)
        """
        if results_obj is not None and wn is not None:
            return self._parse_from_wntr(results_obj, wn)
        else:
            # 回退到原文件解析（保留向后兼容）
            return self._parse_from_file(rpt_file)

    def _parse_from_wntr(self, results, wn) -> Tuple[bool, str, Dict]:
        """从 WNTR 结果对象解析"""
        try:
            node_results = []
            pipe_results = []

            # 获取最后时间步的数据（假设稳态分析只有一个时间步）
            node_pressure = results.node['pressure'].iloc[-1]   # 单位：米水头
            node_demand = results.node['demand'].iloc[-1]       # 单位：立方米/秒
            node_head = results.node['head'].iloc[-1]           # 单位：米

            # 获取管道数据
            link_flow = results.link['flowrate'].iloc[-1]       # 单位：立方米/秒
            # 注意：WNTR 结果中可能没有直接给出 headloss_per_km，我们需要通过模型计算或从结果获取
            # 如果结果中有 'headloss'，则使用，否则手动计算
            if 'headloss' in results.link:
                link_headloss = results.link['headloss'].iloc[-1]   # 总水损，米
            else:
                link_headloss = None

            # 构建节点结果
            for node_id in wn.node_name_list:
                pressure_val = node_pressure.get(node_id, 0)
                # 调试：打印前几个节点的压力
                if len(node_results) < 5:
                    logger.debug(f"节点 {node_id} 压力 = {pressure_val}")
                node_results.append({
                    "node_id": node_id,
                    "demand_lps": node_demand.get(node_id, 0) * 1000,  # 转换为 L/s
                    "head_m": node_head.get(node_id, 0),
                    "pressure_m": pressure_val
                })

            # 构建管道结果
            for link_id in wn.link_name_list:
                link = wn.get_link(link_id)
                # 只处理实际管道（类型为 Pipe）
                if link.link_type != 'Pipe':
                    continue

                # 从结果中获取流量
                flow_m3s = link_flow.get(link_id, 0)
                flow_lps = flow_m3s * 1000

                # 获取流速（如果结果中有）
                velocity = 0.0
                if 'velocity' in results.link:
                    velocity = results.link['velocity'].iloc[-1].get(link_id, 0)

                # 获取总水损（米）
                headloss_m = 0.0
                if link_headloss is not None:
                    headloss_m = link_headloss.get(link_id, 0)   # 单位水损 (m/m)
                else:
                    # 如果结果中没有 headloss，可以尝试从模型计算（如 length * unit_headloss）
                    # 这里先设为 0，后续可通过其他方式计算
                    pass

                # 获取管道长度（米）
                length = link.length if hasattr(link, 'length') else 0.0
                # 计算每千米水损
                headloss_per_km = headloss_m * 1000

                # 从 CAD 数据管理器获取详细信息（可选）
                node1 = link.start_node_name
                node2 = link.end_node_name
                inner_diameter = link.diameter if hasattr(link, 'diameter') else 0.0  # 注意单位：米
                inner_diameter_mm = inner_diameter * 1000
                nominal_diameter = ""  # WNTR 模型中没有公称管径，可能需要从 CAD 数据补充
                material = link.material if hasattr(link, 'material') else ""
                roughness = link.roughness if hasattr(link, 'roughness') else 0.0

                # 如果提供了 CAD 数据管理器，尝试获取更详细的信息
                if self.cad_data_manager:
                    pipe_data = self.cad_data_manager.pipe_by_id.get(link_id)
                    if pipe_data:
                        nominal_diameter = pipe_data.nominal_diameter
                        inner_diameter_mm = pipe_data.inner_diameter
                        material = pipe_data.material
                        roughness = pipe_data.roughness

                pipe_results.append({
                    "pipe_id": link_id,
                    "node1": node1,
                    "node2": node2,
                    "flow_lps": flow_lps,
                    "velocity_mps": velocity,
                    "headloss_per_km": headloss_per_km,
                    "headloss_m": headloss_m,
                    "diameter": inner_diameter_mm,
                    "nominal_diameter": nominal_diameter,
                    "length": length,
                    "material": material,
                    "roughness": roughness,
                    "status": "Open"  # 状态默认为开，可根据阀门调整
                })

            # 构建摘要
            summary = {
                "total_demand": sum(r["demand_lps"] for r in node_results),
                "average_pressure": sum(r["pressure_m"] for r in node_results) / len(node_results) if node_results else 0,
                "maximum_pressure": max((r["pressure_m"] for r in node_results), default=0),
                "minimum_pressure": min((r["pressure_m"] for r in node_results), default=0),
                "number_of_nodes": len(node_results),
                "number_of_pipes": len(pipe_results)
            }

            self.results = {
                "node_results": node_results,
                "pipe_results": pipe_results,
                "demand_results": {},  # 可根据需要填充
                "summary": summary,
                "status": "完成"
            }

            logger.info("从 WNTR 结果解析成功")
            return True, "解析成功", self.results

        except Exception as e:
            logger.error(f"从 WNTR 解析结果失败: {e}", exc_info=True)
            return False, f"解析失败: {str(e)}", {}

    def _parse_from_file(self, rpt_file: str) -> Tuple[bool, str, Dict]:
        """原有的文件解析方法（保持不变）"""
        # 此处保留您原来的文件解析代码，用于向后兼容
        # 如果不需要，可以直接删除此方法，但为了完整性，建议保留
        # 以下为原代码占位符，请用您原有的 _parse_node_results 等逻辑替换
        try:
            # 原有解析逻辑...
            # 这里省略具体代码，请保留您原来的实现
            pass
        except Exception as e:
            logger.error(f"解析报告文件失败: {e}")
            return False, f"解析失败: {str(e)}", {}