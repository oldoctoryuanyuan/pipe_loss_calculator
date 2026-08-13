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
                 progress_callback: Optional[Callable] = None,
                 pipe_lengths: Optional[Dict[str, float]] = None,
                 warm_low: Optional[float] = None,
                 pressure_tolerance: float = 0.1,
                 inner_diameter_offset: float = 0.0):
        self.cad = cad_data_manager
        self.config = config_manager
        self.calc_type = calc_type
        self.mode = mode
        self.pipe_lengths = pipe_lengths  # 当量长度法：管道计算长度覆盖表，None=局部水损系数法
        self.warm_low = warm_low          # 模式C热启动下界：上一轮平差供水点压力（当量长度法跨轮复用）
        self.pressure_tolerance = float(pressure_tolerance)  # 模式C主判据：最不利用水点超压≤该值即终止（m）
        self.inner_diameter_offset = float(inner_diameter_offset)  # 内径修正量（mm，如 -1.0）
        # 强制转换为浮点数（防止字符串传入）
        self.sprinkler_K = float(sprinkler_K)
        self.k_value_map: Dict[str, float] = {}  # node_id→K，per-node覆盖
        self.Ad = float(hydrant_Ad)
        self.Ld = float(hydrant_Ld)
        self.B = float(hydrant_B)
        self.Hak = float(hydrant_Hak)
        self.progress_callback = progress_callback

        # P3 内存模式：模型只加载一次，迭代间改内存需求直接重算（跳过 INP 重建与 WNTR 重新加载）。
        # 若怀疑内存模式与文件模式结果不一致，可将此开关置 False 立即回退到老路径。
        self.use_memory_solver = True
        # P1 二分热启动：模式C相邻候选压力差极小，保留上一候选收敛需求作初值可大幅减少迭代次数。
        # 收敛解为松弛迭代的唯一不动点，与初值无关；若出现异常可置 False 回退到冷启动。
        self.use_warm_start = True
        # P2 调试写盘开关：默认关闭（不再生成迭代 INP 副本与 JSON）；排查问题时置 True 打开
        self.debug_write = False
        self._mem_model_loaded = False    # 内存模型是否已加载
        self._mem_reservoir_head = None   # 模式C当前候选对应的水库水头（米）
        self._current_round = 1           # 当前二分候选轮次（模式B恒为1），用于进度文字显示

        self._total_invocation_count = 0
        # 模式C求解出的供水点压力（m）：仅记录供当量长度法跨轮热启动读取，
        # 不写回 supply_nodes[0].pressure（保持页面输入值为0，便于下次C模式直接计算）
        self.last_supply_pressure = 0.0
        
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
        """主求解入口（成功时在消息中附带总耗时，便于对比优化效果）"""
        import time as _time
        start_time = _time.perf_counter()
        if self.mode == 'B':
            success, results, message = self._solve_mode_B()
        else:  # 'C'
            success, results, message = self._solve_mode_C()
        if success:
            elapsed = _time.perf_counter() - start_time
            message = f"{message}，总耗时 {elapsed:.1f}s"
        return success, results, message

    # ---------- 模式B ----------
    def _solve_mode_B(self) -> Tuple[bool, Optional[Dict], str]:
        """模式B：供水点压力已知，迭代求解需求（直接复用 _solve_mode_B_fixed_supply）"""
        # 获取供水点压力
        if not self.cad.supply_nodes:
            return False, None, "没有供水点数据"
        supply_pressure = self.cad.supply_nodes[0].pressure
        if supply_pressure <= 0:
            return False, None, "供水点压力未设置或为0"

        # 收集被勾选的用水点组的节点ID（跳过状态为"关"的用水点，如位于检修管道上的用水点）
        selected_demand_node_ids = set()
        for group in self.cad.demand_groups.values():
            if group.is_selected:
                for demand_node in group.demand_nodes:
                    if demand_node.status == "关":
                        logger.info(f"用水点 {demand_node.node_id} 状态为关，跳过（不参与计算）")
                        continue
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
        if self.use_memory_solver:
            # 内存模式下水库水头由这里维护（与 INP 生成逻辑一致：节点高程 + 表压）
            self._mem_reservoir_head = None
    
        # 3. 收集所有勾选组中用水点节点的最高高程（跳过状态为"关"的用水点）
        demand_z_max = 0.0
        selected_demand_node_ids = set()
        for group in selected_groups:
            for demand_node in group.demand_nodes:
                if demand_node.status == "关":
                    logger.info(f"用水点 {demand_node.node_id} 状态为关，跳过（不参与计算）")
                    continue
                node = self.cad.node_by_id.get(demand_node.node_id)
                if node and node.is_active:
                    selected_demand_node_ids.add(demand_node.node_id)
                    demand_z_max = max(demand_z_max, node.z / 1000.0)
                else:
                    logger.warning(f"节点 {demand_node.node_id} 无效或不存在，已跳过")
    
        # 4. 确定初始二分区间
        # 理论最低压力 = (最不利用水点高程 - 供水点高程) + 目标压力
        theoretical_min = (demand_z_max - supply_z) + target_min_pressure
        if self.warm_low and self.warm_low > 0:
            # 热启动（当量长度法第1轮起）：上一轮平差供水点压力 -5m 兜底，
            # 上界只比下界高15m（约等于上一轮结果+10m）；三通/四通当量水损远小于40m
            low = max(theoretical_min, self.warm_low - 5.0)
            high = low + 15.0
            logger.info(f"热启动区间(上一轮供水压力={self.warm_low:.2f}): "
                        f"low={low:.2f}, high={high:.2f}")
        else:
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
            self._current_round = iteration + 1   # 进度文字显示当前二分轮次
            logger.info(f"二分法尝试 {iteration+1}: low={low:.2f}, high={high:.2f}, mid={mid:.2f}")

            # 设置供水点压力
            self.cad.supply_nodes[0].pressure = mid
            logger.info(f"设置供水点压力为 {mid:.2f}")
            if self.use_memory_solver:
                # 内存模式：同步更新水库水头（高程 + 表压 × 单位系数），与 INP 生成公式一致
                _, pressure_factor = self.inp_gen._get_unit_conversion()
                self._mem_reservoir_head = supply_z + mid * pressure_factor
            success, results, msg = self._solve_mode_B_fixed_supply(mid, selected_demand_node_ids, warm_start=self.use_warm_start)

            if not success:
                consecutive_failures += 1
                # 如果连续失败次数过多，且区间很小，则扩大上界（每次只扩5m）
                if consecutive_failures >= 3 and (high - low) < 5.0:
                    high = high + 5.0
                    logger.info(f"连续失败，扩大上界至 {high:.2f}")
                if consecutive_failures >= 10:
                    logger.warning(f"连续失败 {consecutive_failures} 次，停止搜索")
                    break
                # 计算失败 → 压力不足，提高下界
                logger.warning(f"  计算失败: {msg}，提高下界")
                low = mid
                if low >= high:
                    high = low + 5.0
                    logger.info(f"  扩大上界至 {high:.2f}")
                continue
            else:
                consecutive_failures = 0   # 成功时重置失败计数

            # 计算成功，获取最不利用水点压力
            min_actual = min(self._get_node_pressure(results, node_id) for node_id in selected_demand_node_ids)
            logger.info(f"  最不利用水点压力={min_actual:.2f}, 目标={target_min_pressure:.2f}")

            if min_actual >= target_min_pressure:
                # 满足要求，记录候选
                candidate_pressures.append((mid, results))
                # 主判据：超压已落在允许误差内（用户可配置，缺省0.1m）→ 立即终止本轮
                if min_actual - target_min_pressure <= self.pressure_tolerance:
                    logger.info(f"  最不利用水点超压 {min_actual - target_min_pressure:.3f}m "
                                f"≤ 允许误差 {self.pressure_tolerance:.2f}m，提前终止")
                    break
                # 尝试更小的压力
                high = mid
            else:
                # 压力不足，提高下界
                low = mid
                # 当区间过小时扩大上界，避免死锁
                if low >= high:
                    high = low + 5.0
                    logger.info(f"  low >= high，扩大上界至 {high:.2f}")
                elif high - low < 1.0 and not candidate_pressures:
                    high = low + 5.0
                    logger.info(f"  区间过小({high - low:.2f}<1.0)且无满足候选，扩大上界至 {high:.2f}")

            # 兜底终止：区间足够小（5cm 工程精度）
            if high - low < 0.05:
                break
    
        # 6. 从候选结果中选择最小压力
        if candidate_pressures:
            candidate_pressures.sort(key=lambda x: x[0])
            best_pressure, best_results = candidate_pressures[0]
            # 记录求解出的供水点压力（供当量长度法跨轮热启动读取）
            self.last_supply_pressure = best_pressure
            # 恢复供水点压力为进入计算时的值（C模式要求为0），不把求解结果写回输入框：
            # 供水点压力在计算页面（节点结果表）有显示，保持0便于下次C模式直接计算
            self.cad.supply_nodes[0].pressure = original_supply_pressure
            # 更新最终结果到用水点组
            self._update_demand_groups(best_results, selected_demand_node_ids)
            return True, best_results, f"供水点压力 = {best_pressure:.2f}m"
        else:
            # 未找到任何满足要求的结果，恢复原始压力
            self.cad.supply_nodes[0].pressure = original_supply_pressure
            return False, None, "二分法未找到满足要求的供水点压力"

    def _solve_mode_B_fixed_supply(self, supply_pressure: float, selected_node_ids: set = None, warm_start: bool = False) -> Tuple[bool, Optional[Dict], str]:
        """给定供水点压力，进行模式B迭代求解（内部使用）

        warm_start=True 时保留上一候选收敛的 demand_cache 作为迭代初值
        （模式C相邻候选压力差极小，可省去大部分重新收敛迭代）。
        """
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
            # 如果未提供，则从cad中收集所有勾选的节点（用于模式B），跳过状态为"关"的用水点
            selected_node_ids = set()
            for group in self.cad.demand_groups.values():
                if group.is_selected:
                    for demand_node in group.demand_nodes:
                        if demand_node.status == "关":
                            logger.info(f"用水点 {demand_node.node_id} 状态为关，跳过（不参与计算）")
                            continue
                        selected_node_ids.add(demand_node.node_id)

        if not selected_node_ids:
            return False, None, "没有勾选的用水点组"

        # 重置需求缓存（只重置勾选的节点）；warm start 时保留上一候选的收敛值作初值
        if not warm_start:
            self.demand_cache.clear()
            for node_id in selected_node_ids:
                self.demand_cache[node_id] = 0.0

        max_iter = 30
        tol = 0.02  # L/s 收敛容差（真实误差：公式流量 vs 实际写入需求）
        relax = 0.3  # 松弛因子（0.5 表示新需求 = 0.5 * 计算值 + 0.5 * 旧值）
        prev_demands = self.demand_cache.copy()

        # 添加迭代计数器（用于调试文件名）
        self._iter_counter = 0

        for iteration in range(max_iter):
            # 递增迭代计数器
            self._iter_counter += 1
            iter_num = self._iter_counter

            if self.progress_callback:
                self.progress_callback(
                    min(90, int(iter_num / max_iter * 90)),
                    f"第 {self._current_round} 轮：迭代 {iter_num}/{max_iter}：生成INP并水力计算")

            ok, msg, results = self._run_epanet_once()
            if not ok:
                return False, None, msg

            # 计算新需求（使用松弛因子）
            new_demands = {}
            for node_id in selected_node_ids:
                pressure = self._get_node_pressure(results, node_id)
                q_computed = self._compute_flow(pressure, node_id)
                # 松弛：新需求 = 松弛因子 * 计算值 + (1-松弛因子) * 旧值
                # 为避免振荡，采用0.5的松弛
                prev_q = prev_demands.get(node_id, 0.0)
                q_smoothed = relax * q_computed + (1 - relax) * prev_q
                new_demands[node_id] = q_smoothed
                self.demand_cache[node_id] = q_smoothed

            # 调试：输出本次迭代的节点压力、计算需求（仅在 debug_write 开启时）
            if self.debug_write:
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
                    debug_data["computed_flows"][node_id] = float(self._compute_flow(pressure, node_id))
                with open(debug_file, 'w') as f:
                    json.dump(debug_data, f, indent=2)
                logger.info(f"迭代 {iter_num} 调试数据已保存: {debug_file}")

            # 检查是否所有需求为零（压力过低）
            if iteration == 0:
                if all(abs(q) < 1e-6 for q in new_demands.values()):
                    return False, None, "供水压力过低，无法产生任何流量"

            # 检查收敛：真实误差 = 当前压力下公式流量 与 本轮 INP 写入需求之差
            # （原先用平滑值变化量判定，收敛时需求仍滞后公式值最多 0.33 L/s，
            #   导致最终流量与喷头公式不符；改用真实误差后收敛即自洽）
            max_change = 0.0
            for node_id in selected_node_ids:
                pressure = self._get_node_pressure(results, node_id)
                q_computed = self._compute_flow(pressure, node_id)
                prev_q = prev_demands.get(node_id, 0.0)
                max_change = max(max_change, abs(q_computed - prev_q))
            if max_change < tol:
                # 收敛：用最终需求（demand_cache 已更新）重新生成 INP 并再跑一次
                # EPANET，得到压力/管道流量/水损/需求全自洽的完整结果
                if self.progress_callback:
                    self.progress_callback(95, f"第 {self._current_round} 轮：迭代收敛，按最终需求重算")
                final_ok, final_msg, final_results = self._final_run()
                if not final_ok:
                    return False, None, final_msg
                self._update_demand_groups(final_results, selected_node_ids)
                return True, final_results, f"迭代{iteration+1}收敛"

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

    def _compute_flow(self, pressure: float, node_id: str = None) -> float:
        """根据压力和类型计算流量 (L/s)，node_id 用于取 per-node K 值"""
        pressure = float(pressure)
        if self.calc_type == 'sprinkler':
            if pressure <= 0:
                return 0.0
            if node_id and node_id in self.k_value_map:
                k = self.k_value_map[node_id]
                C = k / 60.0 * np.sqrt(0.1)
                return C * np.sqrt(pressure)
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
            calc_type=self.calc_type,
            pipe_lengths=self.pipe_lengths,
            inner_diameter_offset=self.inner_diameter_offset
        )

        # 保存一份带时间戳的副本（调试用，默认关闭）
        if success and self.debug_write:
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

    def _run_epanet_once(self) -> Tuple[bool, str, Dict]:
        """执行一次水力计算并解析结果（迭代与最终重算共用）。

        - 文件路径（use_memory_solver=False）：与老逻辑逐句等价——每次生成 INP 并 run_analysis；
        - 内存路径（use_memory_solver=True）：首次生成 INP 并加载模型，之后只改内存需求直接重算，
          跳过 INP 重建与 WNTR 模型重新加载，是 P3 提速的核心。
        """
        if self.use_memory_solver:
            if not self._mem_model_loaded:
                success, inp_path, _ = self._generate_inp_no_virtual()
                if not success:
                    return False, "生成INP失败", None
                ok, msg = self.calculator.load_model(inp_path)
                if not ok:
                    return False, f"加载模型失败: {msg}", None
                self._mem_model_loaded = True
            self.calculator.set_demands(self.demand_cache)
            if self._mem_reservoir_head is not None:
                self.calculator.set_reservoir_head("RESERVOIR", self._mem_reservoir_head)
            ok, msg = self.calculator.run_loaded_model()
            if not ok:
                return False, f"计算失败: {msg}", None
        else:
            success, inp_path, _ = self._generate_inp_no_virtual()
            if not success:
                return False, "生成INP失败", None
            ok, msg, _ = self.calculator.run_analysis(inp_path)
            if not ok:
                return False, f"计算失败: {msg}", None

        parse_ok, parse_msg, results = self.parser.parse_report_file(
            None, results_obj=self.calculator.last_results, wn=self.calculator.last_wn
        )
        if not parse_ok:
            return False, f"解析失败: {parse_msg}", None
        return True, "", results

    def _final_run(self) -> Tuple[bool, str, Optional[Dict]]:
        """收敛后，用最终需求（demand_cache）再跑一次 EPANET，返回完整自洽的结果。

        迭代循环中 EPANET 反馈的 demand 是上一轮写入的缓存值，若直接作为最终结果，
        流量会滞后于喷头公式值；这里用收敛后的最终需求重新求解一次，
        使节点压力、管道流量、水损与需求全部来自同一次求解，互洽一致。
        """
        ok, msg, results = self._run_epanet_once()
        if not ok:
            return False, f"最终计算失败: {msg}", None
        return True, "", results

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
                