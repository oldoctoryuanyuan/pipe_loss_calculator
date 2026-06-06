# core/pressure_driven_solver.py

import os
import numpy as np
import logging
from typing import Dict, Tuple, Optional, Callable
from datetime import datetime
import shutil
import json

logger = logging.getLogger(__name__)

class PressureDrivenSolver:
    """
    压力驱动求解器（模式B/C）
    用于室内消火栓和喷淋计算，用水点作为独立节点，需求由压力驱动公式决定。
    """
    def __init__(self,
                 cad_data_manager,
                 config_manager,
                 calc_type: str,          # 'hydrant' 或 'sprinkler'
                 mode: str,                # 'B' 或 'C'
                 sprinkler_K: float,
                 hydrant_Ad: float,
                 hydrant_Ld: float,
                 hydrant_B: float,
                 hydrant_Hak: float,
                 progress_callback: Optional[Callable] = None):
        self.cad = cad_data_manager
        self.config = config_manager
        self.calc_type = calc_type
        self.mode = mode
        # 强制转换为浮点数（防止字符串传入）
        self.sprinkler_K = float(sprinkler_K)
        self.Ad = float(hydrant_Ad)
        self.Ld = float(hydrant_Ld)
        self.B = float(hydrant_B)
        self.Hak = float(hydrant_Hak)
        self.progress_callback = progress_callback

        self._total_invocation_count = 0
        
        # 计算常量
        if calc_type == 'sprinkler':
            # q = C * sqrt(P)  (P单位 m)
            self.C = self.sprinkler_K / 60.0 * np.sqrt(0.1)
        else:  # hydrant
            # q = C * sqrt(P - Hak)
            denominator = self.B * self.Ad * self.Ld + 1
            if denominator <= 0:   # 防止除零
                logger.warning("消火栓参数导致分母<=0，使用默认值1")
                denominator = 1.0
            self.C = np.sqrt(self.B / denominator)

        # 导入必要模块（延迟导入避免循环）
        from core.inp_generator import INPGenerator
        from core.epanet_calculator import EpanetCalculator
        from core.result_parser import ResultParser
        self.inp_gen = INPGenerator(config_manager, cad_data_manager.material_manager)
        self.calculator = EpanetCalculator()
        self.parser = ResultParser(cad_data_manager)

        # 临时项目目录
        self.project_dir = self._create_temp_project_dir()
        # 缓存当前迭代的需求值 - 修复：初始化这个字典
        self.demand_cache = {}   # node_id -> demand (L/s)
        
        # 调试输出目录
        self.debug_dir = os.path.join(self.project_dir, "debug")
        os.makedirs(self.debug_dir, exist_ok=True)
        if calc_type == 'sprinkler':
            logger.info(f"喷头K={self.sprinkler_K}, C={self.C}")
        else:
            logger.info(f"消火栓参数: Ad={self.Ad}, Ld={self.Ld}, B={self.B}, Hak={self.Hak}, C={self.C}")

    def _create_temp_project_dir(self) -> str:
        """创建临时项目目录（基于当前时间）"""
        base_dir = os.path.join(os.getcwd(), "projects_temp")
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dir_path = os.path.join(base_dir, f"temp_{timestamp}")
        os.makedirs(dir_path, exist_ok=True)
        return dir_path

    def solve(self) -> Tuple[bool, Optional[Dict], str]:
        """主求解入口"""
        if self.mode == 'B':
            return self._solve_mode_B()
        else:  # 'C'
            return self._solve_mode_C()

    # ---------- 模式B ----------
    def _solve_mode_B(self) -> Tuple[bool, Optional[Dict], str]:
        """模式B：供水点压力已知，迭代求解需求（直接复用 _solve_mode_B_fixed_supply）"""
        # 获取供水点压力
        if not self.cad.supply_nodes:
            return False, None, "没有供水点数据"
        supply_pressure = self.cad.supply_nodes[0].pressure
        if supply_pressure <= 0:
            return False, None, "供水点压力未设置或为0"

        # 收集被勾选的用水点组的节点ID
        selected_demand_node_ids = set()
        for group in self.cad.demand_groups.values():
            if group.is_selected:
                for demand_node in group.demand_nodes:
                    node = self.cad.node_by_id.get(demand_node.node_id)
                    if node and node.is_active:
                        selected_demand_node_ids.add(demand_node.node_id)
                    else:
                        logger.warning(f"节点 {demand_node.node_id} 无效或不存在，已跳过")

        if not selected_demand_node_ids:
            return False, None, "没有勾选的用水点组"

        logger.info(f"模式B：勾选的用水点节点数: {len(selected_demand_node_ids)}")

        # 直接调用 _solve_mode_B_fixed_supply，使用相同的压力
        return self._solve_mode_B_fixed_supply(supply_pressure, selected_demand_node_ids)


    # ---------- 模式C ----------
    def _solve_mode_C(self) -> Tuple[bool, Optional[Dict], str]:
        # 1. 收集勾选组及目标压力
        selected_groups = [g for g in self.cad.demand_groups.values() if g.is_selected and g.min_pressure > 0]
        if not selected_groups:
            return False, None, "没有勾选的用水点组或未设置最低水压"
        target_min_pressure = max(g.min_pressure for g in selected_groups)
        
        # 2. 获取供水点节点高程
        if not self.cad.supply_nodes:
            return False, None, "没有供水点数据"
        original_supply_pressure = self.cad.supply_nodes[0].pressure
        
        # 临时将供水点压力设为0，以消除之前遗留的压力值
        self.cad.supply_nodes[0].pressure = 0.0
        
        supply_node_id = self.cad.supply_nodes[0].node_ids[0]
        supply_node = self.cad.node_by_id.get(supply_node_id)
        if not supply_node:
            return False, None, "供水点节点不存在"
        supply_z = supply_node.z / 1000.0
    
        # 3. 收集所有勾选组中用水点节点的最高高程
        demand_z_max = 0.0
        selected_demand_node_ids = set()
        for group in selected_groups:
            for demand_node in group.demand_nodes:
                node = self.cad.node_by_id.get(demand_node.node_id)
                if node and node.is_active:
                    selected_demand_node_ids.add(demand_node.node_id)
                    demand_z_max = max(demand_z_max, node.z / 1000.0)
                else:
                    logger.warning(f"节点 {demand_node.node_id} 无效或不存在，已跳过")
    
        # 4. 确定初始二分区间
        # 理论最低压力 = (最不利用水点高程 - 供水点高程) + 目标压力
        theoretical_min = (demand_z_max - supply_z) + target_min_pressure
        low = theoretical_min   # 肯定不满足的下界（因为还没有考虑水损）
        # 上界初始设为理论最低 + 一个较大的值，例如 40m（根据管网复杂程度调整）
        high = low + 40.0
    
        # 5. 二分搜索（最多 30 次）
        best_pressure = None
        best_results = None
        candidate_pressures = []  # 存储所有满足条件的压力
    
        consecutive_failures = 0
        logger.info(f"模式C开始：目标压力={target_min_pressure}m, 供水点高程={supply_z}m, 最高用水点高程={demand_z_max}m")
        logger.info(f"初始区间: low={low:.2f}, high={high:.2f}")
        for iteration in range(30):
            mid = (low + high) / 2
            logger.info(f"二分法尝试 {iteration+1}: low={low:.2f}, high={high:.2f}, mid={mid:.2f}")

            # 设置供水点压力
            self.cad.supply_nodes[0].pressure = mid
            logger.info(f"设置供水点压力为 {mid:.2f}")
            success, results, msg = self._solve_mode_B_fixed_supply(mid, selected_demand_node_ids)

            if not success:
                consecutive_failures += 1
                # 如果连续失败次数过多，且区间很小，则扩大上界
                if consecutive_failures >= 3 and (high - low) < 5.0:
                    high = high + 20.0
                    logger.info(f"连续失败，扩大上界至 {high:.2f}")
                if consecutive_failures >= 10:
                    logger.warning(f"连续失败 {consecutive_failures} 次，停止搜索")
                    break
                # 计算失败 → 压力不足，提高下界
                logger.warning(f"  计算失败: {msg}，提高下界")
                low = mid
                if low >= high:
                    high = low + 20.0
                    logger.info(f"  扩大上界至 {high:.2f}")
                continue
            else:
                consecutive_failures = 0   # 成功时重置失败计数

            # 计算成功，获取最不利用水点压力
            min_actual = min(self._get_node_pressure(results, node_id) for node_id in selected_demand_node_ids)
            logger.info(f"  最不利用水点压力={min_actual:.2f}, 目标={target_min_pressure:.2f}")

            if min_actual >= target_min_pressure:
                # 满足要求，记录候选，并尝试更小的压力
                candidate_pressures.append((mid, results))
                high = mid
            else:
                # 压力不足，提高下界
                low = mid

            # 区间足够小，提前终止
            if high - low < 0.001:
                break
    
        # 6. 从候选结果中选择最小压力
        if candidate_pressures:
            candidate_pressures.sort(key=lambda x: x[0])
            best_pressure, best_results = candidate_pressures[0]
            self.cad.supply_nodes[0].pressure = best_pressure
            # 更新最终结果到用水点组
            self._update_demand_groups(best_results, selected_demand_node_ids)
            return True, best_results, f"供水点压力 = {best_pressure:.2f}m"
        else:
            # 未找到任何满足要求的结果，恢复原始压力
            self.cad.supply_nodes[0].pressure = original_supply_pressure
            return False, None, "二分法未找到满足要求的供水点压力"

    def _solve_mode_B_fixed_supply(self, supply_pressure: float, selected_node_ids: set = None) -> Tuple[bool, Optional[Dict], str]:
        """给定供水点压力，进行模式B迭代求解（内部使用）"""
        logger.info(f"_solve_mode_B_fixed_supply 收到供水压力: {supply_pressure}")
        self._total_invocation_count += 1
        # 过滤无效节点
        valid_node_ids = set()
        for node_id in selected_node_ids:
            node = self.cad.node_by_id.get(node_id)
            if node and node.is_active:
                valid_node_ids.add(node_id)
            else:
                logger.warning(f"节点 {node_id} 无效或不存在，已从勾选列表中移除")
        selected_node_ids = valid_node_ids
        if not selected_node_ids:
            return False, None, "没有有效的用水点节点"
        if self._total_invocation_count > 200:  # 限制总调用次数
            logger.error("压力驱动求解器调用次数过多，强制终止")
            return False, None, "求解器调用次数超限，可能陷入死循环"

        # 清除所有节点上的 demand 属性，防止上一次迭代残留
        for node in self.cad.nodes:
            if hasattr(node, 'demand'):
                delattr(node, 'demand')

        if selected_node_ids is None:
            # 如果未提供，则从cad中收集所有勾选的节点（用于模式B）
            selected_node_ids = set()
            for group in self.cad.demand_groups.values():
                if group.is_selected:
                    for demand_node in group.demand_nodes:
                        selected_node_ids.add(demand_node.node_id)

        if not selected_node_ids:
            return False, None, "没有勾选的用水点组"

        # 重置需求缓存（只重置勾选的节点）
        self.demand_cache.clear()
        for node_id in selected_node_ids:
            self.demand_cache[node_id] = 0.0

        max_iter = 30
        tol = 0.1  # L/s 收敛容差
        relax = 0.3  # 松弛因子（0.5 表示新需求 = 0.5 * 计算值 + 0.5 * 旧值）
        prev_demands = self.demand_cache.copy()

        # 添加迭代计数器（用于调试文件名）
        self._iter_counter = 0

        for iteration in range(max_iter):
            # 递增迭代计数器
            self._iter_counter += 1
            iter_num = self._iter_counter

            success, inp_path, _ = self._generate_inp_no_virtual()
            if not success:
                return False, None, "生成INP失败"

            ok, msg, _ = self.calculator.run_analysis(inp_path)
            if not ok:
                return False, None, f"计算失败: {msg}"

            parse_ok, parse_msg, results = self.parser.parse_report_file(
                None, results_obj=self.calculator.last_results, wn=self.calculator.last_wn
            )
            if not parse_ok:
                return False, None, f"解析失败: {parse_msg}"

            # 计算新需求（使用松弛因子）
            new_demands = {}
            for node_id in selected_node_ids:
                pressure = self._get_node_pressure(results, node_id)
                q_computed = self._compute_flow(pressure)
                # 松弛：新需求 = 松弛因子 * 计算值 + (1-松弛因子) * 旧值
                # 为避免振荡，采用0.5的松弛
                prev_q = prev_demands.get(node_id, 0.0)
                q_smoothed = relax * q_computed + (1 - relax) * prev_q
                new_demands[node_id] = q_smoothed
                self.demand_cache[node_id] = q_smoothed

            # 调试：输出本次迭代的节点压力、计算需求
            debug_file = os.path.join(self.debug_dir, f"iter_{iter_num:03d}_results.json")
            debug_data = {
                "iteration": iter_num,
                "supply_pressure": float(supply_pressure),
                "node_pressures": {},
                "computed_flows": {},
                "demand_cache_before": {k: float(v) for k, v in prev_demands.items()},
                "demand_cache_after": {k: float(v) for k, v in new_demands.items()}
            }
            for node_id in selected_node_ids:
                pressure = self._get_node_pressure(results, node_id)
                debug_data["node_pressures"][node_id] = float(pressure)
                debug_data["computed_flows"][node_id] = float(self._compute_flow(pressure))
            with open(debug_file, 'w') as f:
                json.dump(debug_data, f, indent=2)
            logger.info(f"迭代 {iter_num} 调试数据已保存: {debug_file}")

            # 检查是否所有需求为零（压力过低）
            if iteration == 0:
                if all(abs(q) < 1e-6 for q in new_demands.values()):
                    return False, None, "供水压力过低，无法产生任何流量"

            # 检查收敛
            max_change = 0.0
            for node_id, q in new_demands.items():
                prev_q = prev_demands.get(node_id, 0.0)
                max_change = max(max_change, abs(q - prev_q))
            if max_change < tol:
                # 收敛，更新结果（只更新勾选节点）
                self._update_demand_groups(results, selected_node_ids)
                return True, results, f"迭代{iteration+1}收敛"

            prev_demands = new_demands.copy()

        return False, None, f"迭代{max_iter}次未收敛"

    # ---------- 辅助方法 ----------
    def _reset_demand_cache(self, selected_node_ids=None):
        """将所有用水点需求置0（如果指定selected_node_ids，只重置这些节点）"""
        self.demand_cache.clear()
        if selected_node_ids is None:
            for node in self.cad.nodes:
                if self._is_demand_node(node):
                    self.demand_cache[node.node_id] = 0.0
                    logger.debug(f"重置节点 {node.node_id} 需求为0")
        else:
            for node_id in selected_node_ids:
                self.demand_cache[node_id] = 0.0
                logger.debug(f"重置节点 {node_id} 需求为0")

    def _is_demand_node(self, node) -> bool:
        """判断是否为用水点节点"""
        return node.node_type and node.node_type.startswith("用水点")

    def _get_node_pressure(self, results: Dict, node_id: str) -> float:
        """从结果中获取节点压力（m）"""
        for nr in results.get("node_results", []):
            if nr["node_id"] == node_id:
                return nr["pressure_m"]
        return 0.0

    def _compute_flow(self, pressure: float) -> float:
        """根据压力和类型计算流量 (L/s)"""
        pressure = float(pressure)   # 确保为浮点数
        if self.calc_type == 'sprinkler':
            if pressure <= 0:
                return 0.0
            return self.C * np.sqrt(pressure)
        else:  # hydrant
            effective_pressure = pressure - self.Hak
            if effective_pressure <= 0:
                return 0.0
            return self.C * np.sqrt(effective_pressure)

    def _generate_inp_no_virtual(self) -> Tuple[bool, str, Dict]:
        """生成无虚拟节点的INP文件"""
        # 第一步：清除所有节点上可能残留的 demand 属性
        for node in self.cad.nodes:
            if hasattr(node, 'demand'):
                delattr(node, 'demand')
    
        # 第二步：将当前迭代的需求值设置到节点对象的临时属性中（只设置被勾选的节点）
        for node in self.cad.nodes:
            if self._is_demand_node(node) and node.is_active:
                # 只设置那些在 demand_cache 中的节点（即被勾选的）
                demand_val = self.demand_cache.get(node.node_id, 0.0)
                node.demand = demand_val
                logger.debug(f"设置节点 {node.node_id} 的需求为 {demand_val}")  # 新增日志
            else:
                # 非用水点节点确保 demand 属性不存在（或为0，但 INP 中写入 0）
                pass
    
        # 第三步：调用 INPGenerator
        success, inp_path, demand_models = self.inp_gen.generate_inp_file(
            self.cad,
            self.project_dir,
            demand_groups={},       # 无虚拟节点，因此传空字典
            no_virtual=True,
            calc_type=self.calc_type
        )

        # 保存一份带时间戳的副本（调试用）
        if success:
            import time
            iter_num = getattr(self, '_iter_counter', 0)
            backup_path = inp_path.replace('.inp', f'_iter_{iter_num:03d}_{int(time.time())}.inp')
            shutil.copy(inp_path, backup_path)
            logger.debug(f"已保存迭代INP备份: {backup_path}")

            # 同时保存一份到调试目录
            debug_inp = os.path.join(self.debug_dir, f"inp_iter_{iter_num:03d}.inp")
            shutil.copy(inp_path, debug_inp)
            logger.debug(f"调试INP已保存: {debug_inp}")

        # 第四步：清理临时属性（可选，但建议清理）
        for node in self.cad.nodes:
            if hasattr(node, 'demand'):
                delattr(node, 'demand')
    
        return success, inp_path, demand_models

    def _update_demand_groups(self, results, selected_node_ids=None):
        """将最终结果写回到cad_data_manager的demand_groups中"""
        node_results = {nr["node_id"]: nr for nr in results.get("node_results", [])}
        for group in self.cad.demand_groups.values():
            for demand_node in group.demand_nodes:
                node_id = demand_node.node_id
                # 如果指定了selected_node_ids，只更新在集合中的节点
                if selected_node_ids is not None and node_id not in selected_node_ids:
                    continue
                nr = node_results.get(node_id)
                if nr:
                    demand_node.flow = nr.get("demand_lps", 0.0)
                    demand_node.pressure = nr.get("pressure_m", 0.0)
                