"""
INP文件生成器
负责将CAD数据转换为EPANET的INP文件格式
"""
import os
import json
from typing import Dict, List, Tuple
from dataclasses import dataclass
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class DemandGroupModel:
    """用水点组EPANET模型"""
    group_id: str
    total_flow: float  # 总流量 (L/s)
    demand_node_id: str  # 虚拟需求节点ID
    actual_node_ids: List[str]  # 实际用水节点ID列表

class INPGenerator:
    """EPANET INP文件生成器"""
    
    def __init__(self, config_manager, material_manager):
        self.config_manager = config_manager
        self.material_manager = material_manager
        self.config = config_manager.get_live_config()
        
    def _get_unit_conversion(self):
        """单位转换映射（每次调用时获取最新配置）"""
        config = self.config_manager.get_live_config()
        flow_unit = config.get("flow_unit", "L/s")
        pressure_unit = config.get("pressure_unit", "m")
        
        if flow_unit == "m³/h":
            flow_factor = 1000.0 / 3600.0  # m³/h -> L/s
        else:
            flow_factor = 1.0
            
        if pressure_unit == "MPa":
            pressure_factor = 101.9716  # MPa -> m水柱
        else:
            pressure_factor = 1.0
            
        return flow_factor, pressure_factor

    # ========== 已注释：未被调用的方法 ==========
    # def _convert_epanet_headloss(self, formula: str) -> str:
    #     """转换水头损失公式到EPANET格式"""
    #     formula_map = {
    #         "H-W (海澄威廉公式)": "H-W",
    #         "D-W": "D-W",
    #         "C-M": "C-M"
    #     }
    #     return formula_map.get(formula, "H-W")
    # 注释原因：此方法在代码中从未被调用，水头损失公式在[OPTIONS]中直接硬编码为H-W
    
    def generate_inp_file(self, cad_data_manager, project_dir, demand_groups,
                          no_virtual=False, calc_type='fire_fighting') -> Tuple[bool, str, Dict]:
        """
        生成EPANET INP文件
        :param no_virtual: 是否不使用虚拟用水节点（模式B/C时True）
        :param calc_type: 计算类型，用于可能的水头损失公式（暂未使用）
        """
        try:
            inp_path = os.path.join(project_dir, "network.inp")
            flow_factor, pressure_factor = self._get_unit_conversion()

            # 准备用水点组模型（仅当 no_virtual=False 时有效）
            if no_virtual:
                demand_group_models = {}   # 不生成虚拟节点
            else:
                demand_group_models = self._prepare_demand_groups(demand_groups)

            # 生成INP内容
            content = self._generate_inp_content(
                cad_data_manager,
                demand_group_models,
                flow_factor,
                pressure_factor,
                no_virtual=no_virtual
            )

            with open(inp_path, 'w', encoding='utf-8') as f:
                f.write(content)

            logger.info(f"INP文件生成成功: {inp_path}")
            return True, inp_path, demand_group_models

        except Exception as e:
            logger.error(f"生成INP文件失败: {e}")
            return False, str(e), {}
    
    def _prepare_demand_groups(self, demand_groups: Dict) -> Dict[str, DemandGroupModel]:
        """准备用水点组的EPANET模型"""
        models = {}
        
        for group_id, group_data in demand_groups.items():
            if not group_data.get("is_selected", False):
                continue
                
            # 创建虚拟需求节点ID
            demand_node_id = f"D_{group_id}"
            actual_nodes = [node.node_id for node in group_data.get("demand_nodes", [])]
            
            total_flow_lps = group_data.get("total_flow", 0.0)
            
            models[group_id] = DemandGroupModel(
                group_id=group_id,
                total_flow=total_flow_lps,
                demand_node_id=demand_node_id,
                actual_node_ids=actual_nodes
            )
            
        return models
    
    def _generate_inp_content(self, cad_data_manager, demand_group_models,
                            flow_factor, pressure_factor, no_virtual=False) -> str:
        """生成完整的INP文件内容 - 修正节点重复定义问题"""
        lines = []
        
        # 1. 标题和选项
        lines.append("[TITLE]")
        lines.append(f"Network Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        
        lines.append("[OPTIONS]")
        lines.append("UNITS LPS")  # EPANET国际单位：L/s, m, mm
        lines.append("HEADLOSS H-W")
        lines.append("SPECIFIC GRAVITY 1.0")
        lines.append("VISCOSITY 1.0")
        lines.append("TRIALS 100")
        lines.append("ACCURACY 0.001")
        lines.append("UNBALANCED CONTINUE 20")
        lines.append("")
        
        # ===== 收集所有需要关闭的管道 =====
        pipes_to_close = set()
        for valve in cad_data_manager.valves:
            if valve.status == "CLOSED":
                pipes_to_close.add(valve.pipe_id)
        
        # ===== 节点段 - 移除重复的水源节点 =====
        lines.append("[JUNCTIONS]")
        lines.append(";ID               Elev         Demand      Pattern")
        
        # 收集所有需要写入的节点ID（避免重复写入同一个节点）
        written_nodes = set()
        
        # 1. 写入所有实际节点（包括供水点节点和普通节点）
        for node in cad_data_manager.nodes:
            if not node.is_active:
                continue   # 跳过无效节点
            node_id = node.node_id
            if node_id not in written_nodes:
                # 高程转换为米
                elev_m = node.z / 1000.0
                # 需求值：如果是用水点节点且 no_virtual=True，则使用节点临时属性 demand（由求解器设置），否则为0
                if no_virtual and node.node_type and node.node_type.startswith("用水点"):
                    demand_val = getattr(node, 'demand', 0.0)
                    logger.debug(f"INP生成: 节点 {node_id} 需求 = {demand_val}")
                    lines.append(f"{node_id:15} {elev_m:<10.3f} {demand_val:<10.3f} Pattern1")
                else:
                    demand_val = 0.0
                lines.append(f"{node_id:15} {elev_m:<10.3f} {demand_val:<10.3f} Pattern1")
                written_nodes.add(node_id)
        
        # 2. 写入虚拟用水点节点（每个激活的用水点组）
        if not no_virtual:
            for group_model in demand_group_models.values():
                virtual_node_id = group_model.demand_node_id  # 格式如 "D_1#"
                if virtual_node_id not in written_nodes:
                    # 设置组总流量作为需求
                    demand_lps = group_model.total_flow  # 已转换单位
                    lines.append(f"{virtual_node_id:15} 0.0         {demand_lps:<8.3f} Pattern1")
                    written_nodes.add(virtual_node_id)
        
        lines.append("")
        
        # ===== 水库段（虚拟供水点） =====
        lines.append("[RESERVOIRS]")
        lines.append(";ID               Head         Pattern")
        
        virtual_supply_id = "RESERVOIR"

        if cad_data_manager.supply_nodes:
            supply = cad_data_manager.supply_nodes[0]
            # 用户压力转换为米水柱（pressure_factor 已处理单位）
            user_pressure_m = supply.pressure * pressure_factor
            
            # 获取供水点关联的第一个节点的高程（米）
            node_elev_m = 0.0
            if supply.node_ids:
                node = cad_data_manager.node_by_id.get(supply.node_ids[0])
                if node:
                    node_elev_m = node.z / 1000.0  # 毫米 -> 米
            
            # 水库水头 = 节点高程 + 用户期望的节点表压
            reservoir_head = node_elev_m + user_pressure_m
        else:
            reservoir_head = 30.0
            
        lines.append(f"{virtual_supply_id:15} {reservoir_head:<8.1f}    Pattern1")
        lines.append("")
        
        # ===== 管道段 =====
        lines.append("[PIPES]")
        lines.append(";ID               Node1            Node2            Length      Diameter    Roughness  Status")
        
        # 获取局部水损比例
        config = self.config_manager.get_live_config()
        local_loss_ratio = config.get("local_loss_ratio", 0.3)
        length_factor = 1.0 + local_loss_ratio   # 放大系数

        # 写入所有实际管道
        for pipe in cad_data_manager.pipes:
            if not pipe.is_active:
                continue   # 跳过无效管道
            # 检查端点节点是否存在且有效
            start_node = cad_data_manager.node_by_id.get(pipe.start_node_id)
            end_node = cad_data_manager.node_by_id.get(pipe.end_node_id)
            if not start_node or not end_node or not start_node.is_active or not end_node.is_active:
                logger.warning(f"管道 {pipe.pipe_id} 的端点节点无效或不存在，跳过写入")
                continue    
            
            # 如果管道上有阀门关闭，则管道状态为Closed
            if pipe.pipe_id in pipes_to_close:
                status = "Closed"
            else:
                status = "Open" if pipe.status == "开" else "Closed"
            
            diameter_mm = pipe.inner_diameter
            roughness = self.material_manager.get_roughness(pipe.material)
            adjusted_length = pipe.length * length_factor # 修改长度
            lines.append(f"{pipe.pipe_id:15} {pipe.start_node_id:15} {pipe.end_node_id:15} "
                        f"{adjusted_length:<8.2f}    {diameter_mm:<8.3f}  {roughness:<8.1f} 0.0      {status}")
        
        # ===== 虚拟连接管道 =====
        virtual_pipe_id = 10000
        # 收集所有实际供水点节点ID
        supply_node_ids = set()
        for supply in cad_data_manager.supply_nodes:
            supply_node_ids.update(supply.node_ids)
        
        virtual_diameter_mm = 10000
        virtual_length_m = 0.01
        virtual_roughness = 150.0
        
        # 1. 虚拟供水点 -> 实际供水点
        for supply_node_id in supply_node_ids:
            virtual_pipe_id += 1
            lines.append(f"VP_S{virtual_pipe_id:04d}   {virtual_supply_id:15} {supply_node_id:15} "
                        f"{virtual_length_m:<8.3f}    {virtual_diameter_mm:<8.3f}  {virtual_roughness:<8.1f} 0.0      Open")
        
        # 2. 虚拟用水点 -> 实际用水点
        if not no_virtual:
            for group_model in demand_group_models.values():
                virtual_node_id = group_model.demand_node_id
                for actual_node_id in group_model.actual_node_ids:
                    virtual_pipe_id += 1
                    lines.append(f"VP_D{virtual_pipe_id:04d}   {virtual_node_id:15} {actual_node_id:15} "
                                f"{virtual_length_m:<8.3f}    {virtual_diameter_mm:<8.3f}  {virtual_roughness:<8.1f} 0.0      Open")
        lines.append("")
        
        # ===== 时间参数段 =====
        lines.append("[TIMES]")
        lines.append(" Duration           0:00")  # 稳态分析
        lines.append(" Hydraulic Timestep 0:00")
        lines.append(" Quality Timestep   0:00")
        lines.append(" Pattern Timestep   0:00")
        lines.append(" Pattern Start      0:00")
        lines.append(" Report Timestep    0:00")
        lines.append(" Report Start       0:00")
        lines.append("")
        
        # ===== 报告段 =====
        lines.append("[REPORT]")
        lines.append(" Status             Yes")
        lines.append(" Summary            Yes")
        lines.append(" Page               0")
        lines.append(" Nodes              All")
        lines.append(" Links              All")
        lines.append("")
        
        # ===== 坐标段 - 只包括JUNCTIONS中的节点 =====
        lines.append("[COORDINATES]")
        lines.append(";Node             X-Coord            Y-Coord")
        
        # 写入普通节点坐标（不包括虚拟水源）
        for node in cad_data_manager.nodes:
            if not node.is_active:
                continue
                
            # 坐标单位：米
            x_m = node.x / 1000.0  # 毫米转米
            y_m = node.y / 1000.0
            lines.append(f"{node.node_id:15} {x_m:<18.3f} {y_m:<18.3f}")
        
        # 添加虚拟供水点坐标（放在合适位置）
        if supply_node_ids:
            # 找一个供水点作为参考位置
            first_supply_node_id = list(supply_node_ids)[0]
            node = cad_data_manager.node_by_id.get(first_supply_node_id)
            if node:
                x_m = node.x / 1000.0 + 2.0  # 偏移一点
                y_m = node.y / 1000.0 + 2.0
                lines.append(f"{virtual_supply_id:15} {x_m:<18.3f} {y_m:<18.3f}")
        
        lines.append("")
        
        # ===== 其他必要段落 =====
        lines.append("[VERTICES]")
        lines.append(";Link             X-Coord            Y-Coord")
        lines.append("")
        
        lines.append("[QUALITY]")
        lines.append(";ID               InitQual")
        # 写入所有节点（包括虚拟水源）
        for node in cad_data_manager.nodes:
            if not node.is_active:
                continue
            lines.append(f"{node.node_id:15} 0.0")
        lines.append(f"{virtual_supply_id:15} 0.0")
        lines.append("")
        
        lines.append("[PATTERNS]")
        lines.append(";ID               Multipliers")
        lines.append("Pattern1          1.0")
        lines.append("")
        
        lines.append("[CURVES]")
        lines.append(";ID               X-Value   Y-Value")
        lines.append("")
        
        lines.append("[CONTROLS]")
        lines.append("")
        
        lines.append("[STATUS]")
        lines.append("")
        
        lines.append("[ENERGY]")
        lines.append("Global Efficiency    75")
        lines.append("Global Price         0.0")
        
        # ========== 已注释：重复的pipes_to_close定义 ==========
        # 注释原因：pipes_to_close已在函数开头（约141行）定义并用于管道状态判断，
        # 此处重复定义无实际用途，仅用于日志输出。
        # pipes_to_close = set()
        # for valve in cad_data_manager.valves:
        #     if valve.status == "CLOSED" and valve.pipe_id:
        #         pipes_to_close.add(valve.pipe_id)
        # logger.info(f"阀门关闭影响的管道: {pipes_to_close}")
        
        return "\n".join(lines)
    


