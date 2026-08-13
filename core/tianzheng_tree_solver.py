# core/tianzheng_tree_solver.py
"""
支状喷淋倒推法求解器（天正式，独立逐段计算，不使用 WNTR/EPANET）

原理（《自动喷水灭火系统设计规范》GB50084-2017 特性系数法 / 逐段逆推）：
1. 以供水点为根 BFS 建树；发现环（非支状）直接拒绝。
2. 支状管网流向唯一（供水点 → 喷头），三通/四通的支流在计算前即可确定：
   与进水管不成直通对的出水管 = 支流，按「三通或四通(侧向)」表加当量长度；
   因此管道计算长度可一次性预分配：
       L_calc = 几何长度 × (1 + 支状喷淋倒推法局部水损系数)
              + 本管作为支流的三通/四通当量长度
              + 其它分配给本管的管件阀门当量长度（弯头/异径/蝶阀静态当量）
3. 单调压力需求迭代（每轮）：
   a. 自叶向根：每根管流量 = 下游所有喷头流量之和（喷头流量按当前实际压力 q = K·√(10P)）；
   b. 自叶向根：节点需求压力 = max(自身喷头需求 P0, 各子支路(需求压力 + 水损 + 高程差))——
      分支点取所有子支路需求的**最大值**，保证全部喷头同时满足最低工作压力；
   c. 自根向叶：用供水点需求压力正推，得各喷头实际压力；
   d. 以实际压力更新喷头流量 → 下一轮（流量/压力单调不减，必收敛，通常 2~5 轮）。
4. 供水点所需压力 = 根节点需求压力，总流量 = 根节点流量。
"""
import math
import logging
from typing import Dict, List, Set, Tuple, Optional, Callable
from collections import defaultdict

logger = logging.getLogger(__name__)


class TianzhengTreeSolver:
    """支状喷淋倒推法求解器（模式无关、独立于 WNTR）"""

    def __init__(self,
                 cad_data_manager,
                 sprinkler_K: float,
                 target_min_pressure: float,
                 selected_node_ids: Optional[Set[str]] = None,
                 k_value_map: Optional[Dict[str, float]] = None,
                 tz_ratio: float = 0.015,
                 tables: Optional[Dict] = None,
                 progress_callback: Optional[Callable] = None,
                 inner_diameter_offset: float = 0.0):
        self.cad = cad_data_manager
        self.default_K = float(sprinkler_K)
        self.target_pressure = float(target_min_pressure)   # m 水柱
        self.selected_node_ids = set(selected_node_ids or [])
        self.k_value_map = dict(k_value_map or {})
        self.tz_ratio = float(tz_ratio)                     # 支状喷淋倒推法局部水损系数
        self.tables = tables                                # 可选注入当量表（测试用）
        self.progress_callback = progress_callback
        self.inner_diameter_offset = float(inner_diameter_offset)  # 内径修正量（mm，如 -1.0）

        self.analysis = None          # FittingAnalysisResult（static_lengths/tables/fittings）
        self.l_current: Dict[Tuple[str, str], float] = {}   # (node, pipe) -> 支流当量长度
        self.kinds: Dict[Tuple[str, str], str] = {}         # (node, pipe) -> "侧通"
        self.l_calc: Dict[str, float] = {}                  # pipe_id -> 管道计算长度(m)

        self.parent: Dict[str, Optional[str]] = {}
        self.parent_pipe: Dict[str, Optional[str]] = {}
        self.children: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        self.root: Optional[str] = None
        self.supply_pressure = 0.0                          # 供水点所需表压 (m)
        self.total_flow = 0.0                               # 供水点总流量 (L/s)
        self.sprinkler_self_flow: Dict[str, float] = {}     # 喷头节点自身流量（非喷头 0）

    # ---------- 进度 ----------
    def _notify(self, message: str) -> None:
        if self.progress_callback:
            try:
                self.progress_callback(None, message)
            except Exception:
                pass

    # ---------- 主流程 ----------
    def solve(self) -> Tuple[bool, Optional[Dict], str]:
        try:
            # 0. 前置检查
            if not self.cad.supply_nodes or not self.cad.supply_nodes[0].node_ids:
                return False, None, "没有供水点数据"
            self.root = self.cad.supply_nodes[0].node_ids[0]
            if not self.selected_node_ids:
                return False, None, "没有勾选的喷头节点"

            # 1. 管件分析（静态当量 + 当量数据表）
            from core.fitting_analyzer import analyze_fittings
            self.analysis = analyze_fittings(self.cad, self.tables)
            if self.analysis.error_nodes:
                detail = "\n".join(f"节点{nid}：{reason}" for nid, reason in self.analysis.error_nodes)
                return False, None, "管网存在画图错误或不严谨，请在CAD中修正后重新读取：\n" + detail
            if self.analysis.missing_data:
                detail = "\n".join(self.analysis.missing_data)
                return False, None, "当量长度数据缺失，无法进行支状喷淋倒推法计算：\n" + detail

            # 2. 环检测 + 建树
            ok, err = self._build_tree()
            if not ok:
                return False, None, err

            # 3. 喷头可达性检查
            unreachable = [n for n in self.selected_node_ids if n not in self.parent and n != self.root]
            if unreachable:
                return False, None, "以下喷头未连接到供水点，无法计算：\n" + ", ".join(sorted(unreachable))

            # 4. 当量预分配（支状流向唯一，一次算好）
            self._assign_equiv_lengths()

            # 5. 迭代倒推（单调压力需求迭代）
            self._notify("支状喷淋倒推法：开始计算")
            ok, converged = self._iterate_to_convergence()
            if not ok:
                return False, None, "支状喷淋倒推法迭代超过20轮未收敛，请检查管网结构"

            # 6. 供水点结果
            self.supply_pressure = self.node_pressure.get(self.root, 0.0)
            self.total_flow = self.node_flow.get(self.root, 0.0)
            self._notify("支状喷淋倒推法：计算完成")
            results = self._build_results()
            return True, results, self._summary_message()

        except Exception as e:
            logger.error(f"支状喷淋倒推法计算异常: {e}", exc_info=True)
            return False, None, f"支状喷淋倒推法计算异常: {str(e)}"

    # ---------- 迭代倒推（核心） ----------
    def _iterate_to_convergence(self) -> Tuple[bool, bool]:
        """单调压力需求迭代（保证收敛，规避「换末端」在多最不利分支下的振荡）：

        每轮：
        a. 自叶向根：每根管流量 = 下游喷头流量之和（喷头流量按当前实际压力计算）；
        b. 自叶向根：节点需求压力 = max(自身喷头需求 P0, 各子支路(需求压力+水损+高程差))——
           分支点取所有子支路需求的**最大值**，保证全部喷头同时满足最低工作压力；
        c. 自根向叶：用供水点需求压力正推，得各喷头实际压力；
        d. 以实际压力更新喷头流量 → 下一轮（流量/压力单调不减，必收敛）。

        收敛判据：全部喷头实际压力 ≥ P0，且两轮间喷头压力最大变化 < 0.001m。
        """
        # 树的后序（自叶向根）与先序（自根向叶）遍历顺序
        order: List[str] = []
        stack = [self.root]
        while stack:
            n = stack.pop()
            order.append(n)
            for child, _ in self.children.get(n, []):
                stack.append(child)
        post = list(reversed(order))          # 叶 → 根
        pre = order                           # 根 → 叶

        # 喷头当前实际压力（初值 = 目标压力，之后单调上升）
        spr_p: Dict[str, float] = {n: self.target_pressure for n in self.selected_node_ids}

        prev_pressure = {n: -1.0 for n in self.selected_node_ids}
        for rnd in range(20):
            self._notify(f"支状喷淋倒推法：第{rnd + 1}轮迭代")
            # a. 自叶向根累加流量
            node_q: Dict[str, float] = {}
            pipe_q: Dict[str, float] = {}
            for n in post:
                q = self._sprinkler_flow(n, spr_p.get(n, 0.0)) if n in spr_p else 0.0
                for child, pid in self.children.get(n, []):
                    child_q = node_q.get(child, 0.0)
                    q += child_q
                    # 带符号：水流方向 = 父 → 子；与管道 start→end 同向为正，反向为负
                    pipe = self.cad.pipe_by_id.get(pid)
                    if pipe and pipe.start_node_id != n:
                        child_q = -child_q
                    pipe_q[pid] = child_q
                node_q[n] = q
            # b. 自叶向根计算节点需求压力（分支点取 max）
            need: Dict[str, float] = {}
            for n in post:
                base = self.target_pressure if n in spr_p else 0.0
                for child, pid in self.children.get(n, []):
                    h = self._headloss(node_q.get(child, 0.0), pid)
                    z_n = self._node_z(n)
                    z_c = self._node_z(child)
                    base = max(base, need.get(child, 0.0) + h + (z_c - z_n))
                need[n] = base
            supply_need = need.get(self.root, 0.0)
            # c. 自根向叶正推实际压力
            actual: Dict[str, float] = {self.root: supply_need}
            for n in pre:
                for child, pid in self.children.get(n, []):
                    h = self._headloss(node_q.get(child, 0.0), pid)
                    z_n = self._node_z(n)
                    z_c = self._node_z(child)
                    actual[child] = actual[n] - h - (z_c - z_n)
            # d. 更新喷头实际压力（单调不减），检查收敛
            max_dp = 0.0
            for n in spr_p:
                new_p = actual.get(n, self.target_pressure)
                max_dp = max(max_dp, abs(new_p - prev_pressure.get(n, new_p)))
                prev_pressure[n] = new_p
                if new_p > spr_p[n]:
                    spr_p[n] = new_p
            # 全部喷头满足最低压力且两轮稳定 → 收敛
            all_ok = all(actual.get(n, 0.0) >= self.target_pressure - 1e-6 for n in spr_p)
            if all_ok and max_dp < 0.001:
                # 记录最终结果
                self.node_flow = node_q
                self.pipe_flow = pipe_q
                self.node_pressure = actual
                self.pipe_headloss = {pid: self._headloss(q, pid) for pid, q in pipe_q.items()}
                self.pipe_velocity = {pid: self._velocity(q, pid) for pid, q in pipe_q.items()}
                self.sprinkler_self_flow = {
                    n: self._sprinkler_flow(n, spr_p.get(n, 0.0)) for n in spr_p}
                return True, True
        return False, False

    # ---------- 环检测与建树 ----------
    def _build_tree(self) -> Tuple[bool, str]:
        adj: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        for pipe in self.cad.pipes:
            if not pipe.is_active:
                continue
            sn = self.cad.node_by_id.get(pipe.start_node_id)
            en = self.cad.node_by_id.get(pipe.end_node_id)
            if not sn or not en or not sn.is_active or not en.is_active:
                continue
            adj[pipe.start_node_id].append((pipe.pipe_id, pipe.end_node_id))
            adj[pipe.end_node_id].append((pipe.pipe_id, pipe.start_node_id))

        if self.root not in adj:
            return False, f"供水点节点 {self.root} 未连接任何管道"

        self.parent = {self.root: None}
        self.parent_pipe = {self.root: None}
        self.children = defaultdict(list)
        loop_pipes: List[str] = []
        stack = [self.root]
        while stack:
            n = stack.pop()
            for pid, nb in adj.get(n, []):
                if nb == self.parent.get(n):
                    continue
                if nb in self.parent:
                    loop_pipes.append(pid)          # 非树边 = 成环
                    continue
                self.parent[nb] = n
                self.parent_pipe[nb] = pid
                self.children[n].append((nb, pid))
                stack.append(nb)

        if loop_pipes:
            return False, ("该管网存在环路（非支状），不适用于支状喷淋倒推法。\n"
                           "成环管段：" + ", ".join(sorted(set(loop_pipes))) +
                           "\n请改用「当量长度法」或「局部水损系数法」。")
        return True, ""

    # ---------- 当量预分配 ----------
    def _assign_equiv_lengths(self) -> None:
        """一次性分配管道计算长度：几何×(1+系数) + 三通/四通当量 + 静态当量。

        支状管网流向唯一（供水点→喷头），三通/四通节点处：
        - 与进水管构成直通对的出水管 = 直通，加直通当量（0.2×侧向表值，与当量长度法一致）；
        - 与进水管不成直通对的出水管 = 支流，加侧向当量 Ls。
        """
        tables = self.analysis.tables
        side_table = tables.get("三通或四通(侧向)", {})

        for node_id, rec in self.analysis.fittings.items():
            if rec.fitting_type not in ("三通", "四通"):
                continue
            in_pipe = self.parent_pipe.get(node_id)
            if not in_pipe:
                continue
            dn = rec.diameter_mm
            side_value = side_table.get(str(dn), 0.0)
            ld = 0.2 * side_value                       # 直通当量
            # 出水管中与进水管构成直通对者 = 直通；否则 = 支流
            pair_pipes = set()
            for p1, p2 in rec.straight_pairs:
                pair_pipes.add(p1)
                pair_pipes.add(p2)
            for child, pid in self.children.get(node_id, []):
                if pid == in_pipe:
                    continue
                if in_pipe in pair_pipes and pid in pair_pipes:
                    self.l_current[(node_id, pid)] = ld
                    self.kinds[(node_id, pid)] = "直通"
                else:
                    self.l_current[(node_id, pid)] = side_value
                    self.kinds[(node_id, pid)] = "侧通"

        for pipe in self.cad.pipes:
            if not pipe.is_active:
                continue
            static = self.analysis.static_lengths.get(pipe.pipe_id, 0.0)
            branch = 0.0
            for (node_id, pid), v in self.l_current.items():
                if pid == pipe.pipe_id:
                    branch += v
            self.l_calc[pipe.pipe_id] = (pipe.length * (1.0 + self.tz_ratio)
                                         + static + branch)

    # ---------- 初始末端喷头：ΣL_calc 加权路径最大 ----------
    def _initial_end_sprinkler(self) -> str:
        path_len: Dict[str, float] = {self.root: 0.0}
        order = [self.root]
        for n in order:
            for child, pid in self.children.get(n, []):
                path_len[child] = path_len[n] + self.l_calc.get(pid, 0.0)
                order.append(child)
        return max(self.selected_node_ids, key=lambda n: path_len.get(n, -1.0))

    # ---------- 水损 / 流速 / 喷头流量 ----------
    def _headloss(self, q_lps: float, pipe_id: str) -> float:
        """海澄-威廉姆斯沿程水头损失（m）。

        i = 10.667 × Q^1.852 / (C^1.852 × d^4.871)   （Q: m³/s, d: m）
        C 值取管材 roughness（与 EPANET H-W 一致，便于结果对照）。
        流量带符号（沿管道 start→end 为正），水损取绝对值。
        内径按 inner_diameter_offset 修正（如减1mm计算）。
        """
        if not q_lps or not pipe_id:
            return 0.0
        pipe = self.cad.pipe_by_id.get(pipe_id)
        if not pipe:
            return 0.0
        d_m = (pipe.inner_diameter + self.inner_diameter_offset) / 1000.0
        if d_m <= 0:
            return 0.0
        c = pipe.roughness if pipe.roughness and pipe.roughness > 0 else 120.0
        q_m3s = abs(q_lps) / 1000.0
        i = 10.667 * (q_m3s ** 1.852) / (c ** 1.852 * d_m ** 4.871)
        return i * self.l_calc.get(pipe_id, pipe.length)

    def _velocity(self, q_lps: float, pipe_id: str) -> float:
        if not q_lps or not pipe_id:
            return 0.0
        pipe = self.cad.pipe_by_id.get(pipe_id)
        if not pipe:
            return 0.0
        d_m = (pipe.inner_diameter + self.inner_diameter_offset) / 1000.0
        if d_m <= 0:
            return 0.0
        q_m3s = abs(q_lps) / 1000.0
        return q_m3s / (math.pi * d_m * d_m / 4.0)

    def _sprinkler_flow(self, node_id: str, pressure_m: float) -> float:
        """喷头流量（L/s）：q = C·√P，C = K/60·√0.1（与压力驱动求解器一致）"""
        if pressure_m <= 0:
            return 0.0
        k = self.k_value_map.get(node_id, self.default_K)
        c = k / 60.0 * math.sqrt(0.1)
        return c * math.sqrt(pressure_m)

    # ---------- 辅助 ----------
    def _node_z(self, node_id: str) -> float:
        node = self.cad.node_by_id.get(node_id)
        return (node.z / 1000.0) if node else 0.0

    # ---------- 结果组装 ----------
    def _build_results(self) -> Dict:
        node_results = []
        for node in self.cad.nodes:
            if not node.is_active:
                continue
            nid = node.node_id
            p = self.node_pressure.get(nid, 0.0)
            node_results.append({
                "node_id": nid,
                "demand_lps": self.sprinkler_self_flow.get(nid, 0.0),
                "head_m": node.z / 1000.0 + p,
                "pressure_m": p,
            })

        pipe_results = []
        for pipe in self.cad.pipes:
            if not pipe.is_active:
                continue
            pid = pipe.pipe_id
            flow = self.pipe_flow.get(pid, 0.0)
            hl = self.pipe_headloss.get(pid, 0.0)          # 整管水损 (m)
            lcalc = self.l_calc.get(pid, pipe.length)
            # headloss_m 字段语义 = 单位水损 (m/m)（与 EPANET/ResultParser 一致），
            # GUI 层水损 = headloss_m × calc_length；整管水损 = hl / lcalc × calc_length
            unit_hl = hl / lcalc if lcalc > 0 else 0.0
            pipe_results.append({
                "pipe_id": pid,
                "node1": pipe.start_node_id,
                "node2": pipe.end_node_id,
                "flow_lps": flow,
                "velocity_mps": self.pipe_velocity.get(pid, 0.0),
                "headloss_per_km": unit_hl * 1000.0,
                "headloss_m": unit_hl,
                "diameter": pipe.inner_diameter,
                "nominal_diameter": pipe.nominal_diameter,
                "length": pipe.length,
                "material": pipe.material,
                "roughness": pipe.roughness,
                "status": "Open" if pipe.status == "开" else "Closed",
                "calc_length": lcalc,
            })

        pressures = [r["pressure_m"] for r in node_results]
        summary = {
            "total_demand": sum(r["demand_lps"] for r in node_results),
            "average_pressure": sum(pressures) / len(pressures) if pressures else 0,
            "maximum_pressure": max(pressures, default=0),
            "minimum_pressure": min(pressures, default=0),
            "number_of_nodes": len(node_results),
            "number_of_pipes": len(pipe_results),
        }
        return {
            "node_results": node_results,
            "pipe_results": pipe_results,
            "demand_results": {},
            "summary": summary,
            "status": "完成",
        }

    def _summary_message(self) -> str:
        return (f"支状喷淋倒推法计算完成：供水点所需压力 = {self.supply_pressure:.2f}m，"
                f"总流量 = {self.total_flow:.3f}L/s")
