# core/equiv_length_engine.py
"""
当量长度法计算引擎（模式B/C）
多轮平差流程：第0轮（静态当量）→ 第1轮（按第0轮流向赋非松弛当量）→
第n轮（flow_changed松弛/weight_changed重加权）→ 终止/上限 → 最终轮（非松弛重写）。
每轮平差新建 PressureDrivenSolver 实例，通过 pipe_lengths 覆盖管道计算长度。
"""
import logging
from typing import Dict, List, Optional, Tuple, Callable

logger = logging.getLogger(__name__)

ALPHA = 0.6                     # 松弛因子
ZERO_FLOW_EPS = 0.001           # 零流量判断阈值（L/s），与现有代码一致


class EquivLengthEngine:
    """当量长度法计算引擎"""

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
                 k_value_map: Optional[Dict[str, float]] = None,
                 progress_callback: Optional[Callable] = None,
                 pressure_tolerance: float = 0.1,
                 inner_diameter_offset: float = 0.0):
        self.cad = cad_data_manager
        self.config = config_manager
        self.calc_type = calc_type
        self.mode = mode
        self.sprinkler_K = float(sprinkler_K)
        self.hydrant_Ad = float(hydrant_Ad)
        self.hydrant_Ld = float(hydrant_Ld)
        self.hydrant_B = float(hydrant_B)
        self.hydrant_Hak = float(hydrant_Hak)
        self.inner_diameter_offset = float(inner_diameter_offset)  # 内径修正量（mm）
        self.k_value_map = k_value_map or {}
        self.progress_callback = progress_callback
        self.pressure_tolerance = float(pressure_tolerance)  # 模式C主判据允许误差（m）

        # 当量长度法局部水损系数（A2：消火栓；B2：喷淋）
        cfg = config_manager.get_live_config()
        if calc_type == "sprinkler":
            self.coeff = cfg.get("equiv_len_ratio_sprinkler", 0.05)
        else:
            self.coeff = cfg.get("equiv_len_ratio_hydrant", 0.1)

        self.analysis = None                     # FittingAnalysisResult
        self.fitting_nodes: List[str] = []       # 三通/四通节点ID列表
        self.l_current: Dict[Tuple[str, str], float] = {}   # (node, pipe) -> 当前当量长度
        self.kinds: Dict[Tuple[str, str], str] = {}         # (node, pipe) -> 直通/侧通/混合
        self.recalc: Dict[str, str] = {}         # node_id -> 'flow_changed'/'weight_changed'
        self.roles: Dict[Tuple[str, str], bool] = {}        # (node, pipe) -> 上轮是否支流
        self._prev_supply_pressure: Optional[float] = None  # 上一轮平差的供水点压力（模式C热启动）

    # ---------- 主流程 ----------
    def solve(self, standardize_errors: bool = False,
              analysis: Optional["FittingAnalysisResult"] = None) -> Tuple[bool, Optional[Dict], str]:
        from core.fitting_analyzer import analyze_fittings
        if analysis is not None:
            # 复用已有分析结果（如"转为标准管件计算"时用第一次检测的结果，避免重复分析）
            self.analysis = analysis
        else:
            self.analysis = analyze_fittings(self.cad)
        if self.analysis.error_nodes and standardize_errors:
            # 用户选择"转为标准管件计算"：将可转换节点（2/3/4管）转为标准管件
            from core.fitting_analyzer import convert_error_nodes_to_standard
            self.analysis = convert_error_nodes_to_standard(self.cad, self.analysis)
        if self.analysis.error_nodes:
            detail = "\n".join(f"节点{node_id}：{reason}" for node_id, reason in self.analysis.error_nodes)
            return False, None, "管网存在画图错误或不严谨，请在CAD中修正后重新读取：\n" + detail
        if self.analysis.missing_data:
            detail = "\n".join(self.analysis.missing_data)
            return False, None, "当量长度数据缺失，无法进行当量长度法计算：\n" + detail

        self.fitting_nodes = [nid for nid, rec in self.analysis.fittings.items()
                              if rec.fitting_type in ("三通", "四通")]
        if not self.fitting_nodes:
            # 无三通/四通：第0轮即为最终结果
            base = self._build_base_lengths()
            results = self._run_round(base)
            if results is None:
                return False, None, "水力计算失败"
            self._attach_calc_length(results, base)
            return True, results, "当量长度法计算完成（无三通/四通管件）"

        # 第0轮：仅静态当量
        base = self._build_base_lengths()
        self._notify("第0轮平差：计算静态当量后的管网")
        results = self._run_round(base)
        if results is None:
            return False, None, "第0轮平差失败"
        flows_prev = self._extract_flows(results)

        # 第1轮：按第0轮流向直接赋予非松弛当量长度
        self._assign_initial(flows_prev)
        lengths = self._build_lengths(base)
        self._notify("第1轮平差：按第0轮流向赋予管件当量长度")
        results = self._run_round(lengths)
        if results is None:
            return False, None, "第1轮平差失败"
        flows_cur = self._extract_flows(results)
        if self._flows_equal(flows_prev, flows_cur):
            self._attach_calc_length(results, lengths)
            return True, results, "当量长度法计算完成（第1轮流向即稳定）"

        # 第2~5轮
        final_flows = flows_cur
        prev_pressure = self._prev_supply_pressure   # 第1轮供水点压力（_run_round 已记录）
        for round_no in range(2, 6):
            self._update_recalc(flows_prev, flows_cur)
            self._apply_recalc(flows_cur)
            lengths = self._build_lengths(base)
            self._notify(f"第{round_no}轮平差：松弛调整管件当量长度")
            results = self._run_round(lengths)
            if results is None:
                return False, None, f"第{round_no}轮平差失败"
            flows_new = self._extract_flows(results)
            flows_prev = flows_cur
            flows_cur = flows_new
            final_flows = flows_cur
            # 提前终止判据（OR）：流向完全相等，或供水压力已收敛（与上轮差≤允许误差）
            cur_pressure = self._prev_supply_pressure
            pressure_converged = (prev_pressure is not None and cur_pressure is not None
                                  and abs(cur_pressure - prev_pressure) <= self.pressure_tolerance)
            flows_stable = self._flows_equal(flows_prev, flows_cur)
            if flows_stable or pressure_converged:
                if pressure_converged and not flows_stable:
                    logger.info(f"供水压力收敛（第{round_no}轮 {cur_pressure:.2f}m vs "
                                f"上轮 {prev_pressure:.2f}m，差 "
                                f"{abs(cur_pressure - prev_pressure):.3f}m ≤ 允许误差 "
                                f"{self.pressure_tolerance:.2f}m），提前结束循环轮")
                break
            prev_pressure = cur_pressure

        # 最终轮：按最终流向赋予非松弛当量长度（流向曾改变的管件 + 二进二出四通）
        self._assign_final(final_flows)
        lengths = self._build_lengths(base)
        self._notify("最终轮平差：按最终流向赋予非松弛当量长度")
        results = self._run_round(lengths)
        if results is None:
            return False, None, "最终轮平差失败"
        self._attach_calc_length(results, lengths)
        return True, results, "当量长度法计算完成"

    # ---------- 管道长度 ----------
    def _build_base_lengths(self) -> Dict[str, float]:
        """基础计算长度 = 几何×(1+当量法系数) + 静态当量（弯头/阀门/异径）"""
        base: Dict[str, float] = {}
        for pipe in self.cad.pipes:
            if not pipe.is_active:
                continue
            base[pipe.pipe_id] = pipe.length * (1.0 + self.coeff) \
                + self.analysis.static_lengths.get(pipe.pipe_id, 0.0)
        return base

    def _build_lengths(self, base: Dict[str, float]) -> Dict[str, float]:
        """基础长度 + 动态管件当量"""
        lengths = dict(base)
        for (node_id, pipe_id), value in self.l_current.items():
            if value:
                lengths[pipe_id] = lengths.get(pipe_id, 0.0) + value
        return lengths

    def _attach_calc_length(self, results: Dict, lengths: Dict[str, float]) -> None:
        """将本轮计算长度附加到结果管道项上，供展示层使用"""
        for pr in results.get("pipe_results", []):
            pid = pr.get("pipe_id")
            if pid in lengths:
                pr["calc_length"] = lengths[pid]

    # ---------- 单轮求解 ----------
    def _run_round(self, lengths: Dict[str, float]) -> Optional[Dict]:
        from core.pressure_driven_solver import PressureDrivenSolver
        solver = PressureDrivenSolver(
            cad_data_manager=self.cad,
            config_manager=self.config,
            calc_type=self.calc_type,
            mode=self.mode,
            sprinkler_K=self.sprinkler_K,
            hydrant_Ad=self.hydrant_Ad,
            hydrant_Ld=self.hydrant_Ld,
            hydrant_B=self.hydrant_B,
            hydrant_Hak=self.hydrant_Hak,
            progress_callback=self.progress_callback,
            pipe_lengths=lengths,
            warm_low=self._prev_supply_pressure,
            pressure_tolerance=self.pressure_tolerance,
            inner_diameter_offset=self.inner_diameter_offset,
        )
        solver.k_value_map = self.k_value_map
        success, results, message = solver.solve()
        if not success:
            logger.error(f"当量长度法平差轮失败: {message}")
            return None
        # 记录本轮供水点压力，供下一轮模式C二分区间热启动。
        # solver 不再写回 supply_nodes[0].pressure（保持页面输入值不变），
        # 改从 solver 求解结果属性读取，数值与原来完全一致。
        try:
            p = getattr(solver, 'last_supply_pressure', 0.0)
            if p > 0:
                self._prev_supply_pressure = float(p)
        except Exception:
            pass
        return results

    def _notify(self, message: str) -> None:
        if self.progress_callback:
            try:
                self.progress_callback(None, message)
            except Exception:
                pass

    # ---------- 流向提取与对比 ----------
    def _extract_flows(self, results: Dict) -> Dict[Tuple[str, str], int]:
        """提取各管件节点连接管段的流向: (node, pipe) -> -1流入/+1流出/0零流量"""
        flows: Dict[Tuple[str, str], int] = {}
        pipe_map = {}
        for pr in results.get("pipe_results", []):
            pipe_map[pr.get("pipe_id")] = pr
        for node_id in self.fitting_nodes:
            rec = self.analysis.fittings[node_id]
            for pid in rec.pipes:
                pr = pipe_map.get(pid)
                if not pr:
                    flows[(node_id, pid)] = 0
                    continue
                flow = pr.get("flow_lps", 0.0)
                if abs(flow) <= ZERO_FLOW_EPS:
                    flows[(node_id, pid)] = 0
                elif pr.get("node1") == node_id:
                    flows[(node_id, pid)] = 1 if flow > 0 else -1
                elif pr.get("node2") == node_id:
                    flows[(node_id, pid)] = -1 if flow > 0 else 1
                else:
                    flows[(node_id, pid)] = 0
        return flows

    def _flows_equal(self, f1: Dict[Tuple[str, str], int],
                     f2: Dict[Tuple[str, str], int]) -> bool:
        for node_id in self.fitting_nodes:
            rec = self.analysis.fittings[node_id]
            for pid in rec.pipes:
                if f1.get((node_id, pid), 0) != f2.get((node_id, pid), 0):
                    return False
        return True

    def _node_zero_flow(self, rec, flows: Dict[Tuple[str, str], int]) -> bool:
        return all(flows.get((rec.node_id, p), 0) == 0 for p in rec.pipes)

    def _in_out_pipes(self, rec, flows: Dict[Tuple[str, str], int]) -> Tuple[List[str], List[str]]:
        node = rec.node_id
        in_pipes = [p for p in rec.pipes if flows.get((node, p), 0) < 0]
        out_pipes = [p for p in rec.pipes if flows.get((node, p), 0) > 0]
        return in_pipes, out_pipes

    def _is_two_in_two_out(self, rec, flows: Dict[Tuple[str, str], int]) -> bool:
        in_pipes, out_pipes = self._in_out_pipes(rec, flows)
        return rec.fitting_type == "四通" and len(in_pipes) == 2 and len(out_pipes) == 2

    def _is_straight_pair(self, rec, p1: str, p2: str) -> bool:
        return any(p1 in pair and p2 in pair for pair in rec.straight_pairs)

    def _lookup_side(self, rec) -> float:
        """侧通当量长度 L_s（数据缺失已在分析阶段拦截，此处双保险）"""
        tables = self.analysis.tables
        return tables.get("三通或四通(侧向)", {}).get(str(rec.diameter_mm), 0.0)

    # ---------- 当量长度目标值计算 ----------
    def _compute_targets(self, rec, flows: Dict[Tuple[str, str], int]) -> Dict[str, float]:
        """按工况1~5计算各连接管段的目标当量长度 L_target，并同步记录直通/侧通种类"""
        node = rec.node_id
        in_pipes, out_pipes = self._in_out_pipes(rec, flows)
        n_in, n_out = len(in_pipes), len(out_pipes)
        targets: Dict[str, float] = {p: 0.0 for p in rec.pipes}

        def set(p, v, kind):
            targets[p] = v
            self.kinds[(node, p)] = kind if v > 0 else ''

        if n_in == 0 or n_out == 0:
            return targets
        if n_in == 1 and n_out == 1:
            # 单入单出（第三口零流量）：按几何直通对区分直通/侧通，
            # 当量均加在出口（支流）管段——与一进二出等工况"当量加支流"原则一致
            ls = self._lookup_side(rec)
            straight = self._is_straight_pair(rec, in_pipes[0], out_pipes[0])
            set(out_pipes[0], 0.2 * ls if straight else ls,
                "直通" if straight else "侧通")
            return targets

        ls = self._lookup_side(rec)
        ld = 0.2 * ls

        if rec.fitting_type == "三通":
            if n_in == 1:     # 工况1：一进二出，支流=出口
                main = in_pipes[0]
                for p in out_pipes:
                    straight = self._is_straight_pair(rec, main, p)
                    set(p, ld if straight else ls, "直通" if straight else "侧通")
            elif n_out == 1:  # 工况2：二进一出，支流=入口
                main = out_pipes[0]
                for p in in_pipes:
                    straight = self._is_straight_pair(rec, main, p)
                    set(p, ld if straight else ls, "直通" if straight else "侧通")
            return targets

        if rec.fitting_type == "四通":
            if n_in == 1:     # 工况3：一进三出
                main = in_pipes[0]
                for p in out_pipes:
                    straight = self._is_straight_pair(rec, main, p)
                    set(p, ld if straight else ls, "直通" if straight else "侧通")
            elif n_out == 1:  # 工况4：三进一出
                main = out_pipes[0]
                for p in in_pipes:
                    straight = self._is_straight_pair(rec, main, p)
                    set(p, ld if straight else ls, "直通" if straight else "侧通")
            elif n_in == 2 and n_out == 2:   # 工况5：二进二出，流量加权
                a, b = in_pipes[0], in_pipes[1]
                c, d = out_pipes[0], out_pipes[1]
                # 直通配对：A-C 直通、B-D 直通（几何直通对固定）
                if self._is_straight_pair(rec, a, c):
                    pass
                elif self._is_straight_pair(rec, a, d):
                    c, d = d, c
                else:
                    # 对撞结构（入口互为直通对）：出口均按侧通处理
                    qa = abs(flows.get((node, a), 0.0))
                    qb = abs(flows.get((node, b), 0.0))
                    denom = qa + qb
                    if denom > 1e-9:
                        set(c, ls, "侧通")
                        set(d, ls, "侧通")
                    return targets
                qa = abs(flows.get((node, a), 0.0))
                qb = abs(flows.get((node, b), 0.0))
                denom = qa + qb
                if denom <= 1e-9:
                    return targets
                set(c, (qa * ld + qb * ls) / denom, "混合")
                set(d, (qa * ls + qb * ld) / denom, "混合")
            return targets
        return targets

    # ---------- 第1轮与最终轮赋值 ----------
    def _assign_initial(self, flows: Dict[Tuple[str, str], int]) -> None:
        """第1轮：按第0轮流向，所有三通/四通直接赋予非松弛 L_target"""
        for node_id in self.fitting_nodes:
            rec = self.analysis.fittings[node_id]
            if self._node_zero_flow(rec, flows):
                continue
            targets = self._compute_targets(rec, flows)
            for pid in rec.pipes:
                value = targets.get(pid, 0.0)
                self.l_current[(node_id, pid)] = value
                self.roles[(node_id, pid)] = value > 0

    def _assign_final(self, flows: Dict[Tuple[str, str], int]) -> None:
        """最终轮：流向曾改变的管件 + 二进二出四通，赋予非松弛 L_target"""
        for node_id in self.fitting_nodes:
            rec = self.analysis.fittings[node_id]
            if self._node_zero_flow(rec, flows):
                continue
            if self.recalc.get(node_id) == "flow_changed" or self._is_two_in_two_out(rec, flows):
                targets = self._compute_targets(rec, flows)
                for pid in rec.pipes:
                    self.l_current[(node_id, pid)] = targets.get(pid, 0.0)

    # ---------- recalc 表更新与应用 ----------
    def _update_recalc(self, flows_prev: Dict[Tuple[str, str], int],
                       flows_cur: Dict[Tuple[str, str], int]) -> None:
        """每轮平差结束后更新需要重新计算的管件列表"""
        for node_id in self.fitting_nodes:
            rec = self.analysis.fittings[node_id]
            if self._node_zero_flow(rec, flows_cur):
                # 上轮平差中流量为零的管件移出此表
                self.recalc.pop(node_id, None)
                continue
            changed = any(flows_prev.get((node_id, p), 0) != flows_cur.get((node_id, p), 0)
                          for p in rec.pipes)
            if changed:
                # 流向曾改变的管件：flow_changed 标记，永久保留（不得降级为 weight_changed）
                self.recalc[node_id] = "flow_changed"
            elif self._is_two_in_two_out(rec, flows_cur):
                # 流向未变的二进二出四通：weight_changed（流量变化需重新加权）
                if self.recalc.get(node_id) != "flow_changed":
                    self.recalc[node_id] = "weight_changed"
            # 其余：不在此表的管件不做处理（直接继承第1轮当量长度）

    def _apply_recalc(self, flows: Dict[Tuple[str, str], int]) -> None:
        """按 recalc 表计算本轮各管件的当量长度"""
        for node_id, flag in list(self.recalc.items()):
            rec = self.analysis.fittings[node_id]
            if flag == "flow_changed":
                targets = self._compute_targets(rec, flows)
                for pid in rec.pipes:
                    cur_role = targets.get(pid, 0.0) > 0
                    if not cur_role:
                        # 支流→非支流（或一直非支流）：直接归零
                        self.l_current[(node_id, pid)] = 0.0
                        self.roles[(node_id, pid)] = False
                        continue
                    # 非支流→支流：L_previous=0；支流→支流：按第二层路径松弛
                    prev = self.l_current.get((node_id, pid), 0.0)
                    self.l_current[(node_id, pid)] = ALPHA * targets[pid] + (1.0 - ALPHA) * prev
                    self.roles[(node_id, pid)] = True
            else:  # weight_changed：二进二出四通，按上一轮流量直接重加权（不松弛）
                targets = self._compute_targets(rec, flows)
                for pid in rec.pipes:
                    value = targets.get(pid, 0.0)
                    self.l_current[(node_id, pid)] = value
                    self.roles[(node_id, pid)] = value > 0


# ---------------------------------------------------------------------------
# 当量长度分配明细收集（供展示层表格 / Excel 导出 / 预览着色使用）
# ---------------------------------------------------------------------------

def _table_val(tables: Dict[str, Dict[str, float]], name: str, dn: int) -> Optional[float]:
    """字典式当量表键值查询；无数据返回 None"""
    return tables.get(name, {}).get(str(dn))


def collect_equiv_detail_rows(analysis, l_current: Dict[Tuple[str, str], float],
                              cad=None, kinds: Dict[Tuple[str, str], str] = None) -> List[Dict]:
    """收集当量长度分配的明细行（每行 = 一个管件对一条管道的分配）。

    静态部分（弯头均摊一半 / 异径放小管 / 阀门在所在管）由 analysis 展开；
    动态部分（三通/四通直通、侧通、混合当量）来自 l_current（引擎第1/2~5/最终轮的结果），
    类别按 kinds 细分为「三通直通/三通侧通/四通直通/四通侧通/四通混合」。
    """
    from core.fitting_analyzer import _pipe_dn, _lookup_reducer

    rows: List[Dict] = []
    tables = analysis.tables
    kinds = kinds or {}

    class _Sink:
        def __init__(self):
            self.missing_data = []
    sink = _Sink()

    def add(node, ftype, dn, pid, value, cat, note):
        rows.append({
            "节点": node,
            "管件类型": ftype,
            "管径": f"DN{dn}" if dn else "",
            "分配管道": pid if pid else "",
            "当量长度(m)": round(float(value), 6),
            "类别": cat,
            "说明": note,
        })

    # 1. 弯头静态当量（均摊一半给所连两管）
    for node_id, rec in analysis.fittings.items():
        dn = rec.diameter_mm
        if rec.fitting_type == "45弯头" and dn > 0:
            value = _table_val(tables, "45°弯头", dn)
            if value is not None:
                half = value / 2.0
                for pid in rec.pipes:
                    add(node_id, "45弯头", dn, pid, half, "静态弯头", "45°弯头当量均摊一半")
        elif rec.fitting_type == "90弯头" and dn > 0:
            value = _table_val(tables, "90°弯头", dn)
            if value is not None:
                half = value / 2.0
                for pid in rec.pipes:
                    add(node_id, "90弯头", dn, pid, half, "静态弯头", "90°弯头当量均摊一半")

    # 2. 异径静态当量（放在较小管径的管道上）
    if cad is not None:
        for node_id, rec in analysis.fittings.items():
            dns_map: Dict[str, int] = {}
            for pid in rec.pipes:
                p = cad.pipe_by_id.get(pid)
                dn = _pipe_dn(p) if p else 0
                if dn > 0:
                    dns_map[pid] = dn
            if len(dns_map) < 2:
                continue
            big = max(dns_map.values())
            for pid, dn in dns_map.items():
                if dn < big:
                    value = _lookup_reducer(tables, big, dn, node_id, sink)
                    if value is not None:
                        add(node_id, "异径", dn, pid, value, "静态异径",
                            f"异径 DN{big}xDN{dn}（放在小管上）")

    # 3. 阀门静态当量（蝶阀，加在所在管道上）
    if cad is not None:
        for valve in cad.valves:
            pipe_id = valve.pipe_id
            if not pipe_id:
                continue
            pipe = cad.pipe_by_id.get(pipe_id)
            dn = _pipe_dn(pipe) if pipe else 0
            if dn <= 0:
                continue
            value = _table_val(tables, "蝶阀", dn)
            if value is not None:
                add(getattr(valve, 'valve_id', '') or '', "蝶阀", dn, pipe_id, value,
                    "静态阀门", "蝶阀当量（加在所在管道上）")

    # 4. 动态当量（三通/四通直通、侧通、混合）
    for (node_id, pipe_id), value in l_current.items():
        if value and value > 0:
            rec = analysis.fittings.get(node_id)
            ftype = rec.fitting_type if rec else "管件"
            dn = rec.diameter_mm if rec else 0
            kind = kinds.get((node_id, pipe_id), "直通")
            cat = f"{ftype}{kind}"   # 三通直通/三通侧通/四通直通/四通侧通/四通混合
            add(node_id, ftype, dn, pipe_id, value, cat, f"{cat}当量")

    return rows


def collect_equiv_summary_rows(cad, analysis, l_current: Dict[Tuple[str, str], float],
                               coeff: float) -> List[Dict]:
    """按管道汇总：几何长度 / 系数附加(几何×coeff) / 静态当量 / 动态当量 / 总计算长度"""
    dynamic: Dict[str, float] = {}
    for (node_id, pipe_id), value in l_current.items():
        if value:
            dynamic[pipe_id] = dynamic.get(pipe_id, 0.0) + value

    rows: List[Dict] = []
    for pipe in cad.pipes:
        if not pipe.is_active:
            continue
        pid = pipe.pipe_id
        length = pipe.length
        static = analysis.static_lengths.get(pid, 0.0)
        dyn = dynamic.get(pid, 0.0)
        rows.append({
            "管道ID": pid,
            "几何长度(m)": round(length, 4),
            "系数附加(m)": round(length * coeff, 4),
            "静态当量(m)": round(static, 4),
            "动态当量(m)": round(dyn, 4),
            "总计算长度(m)": round(length * (1.0 + coeff) + static + dyn, 4),
        })
    return rows


def gather_pipe_equiv(analysis, l_current: Dict[Tuple[str, str], float]
                      ) -> Tuple[Dict[str, float], Dict[str, float]]:
    """汇总静态/动态当量到 {pipe_id: value}，供管道属性挂载与表格列展示使用"""
    static = dict(analysis.static_lengths)
    dynamic: Dict[str, float] = {}
    for (node_id, pipe_id), value in l_current.items():
        if value:
            dynamic[pipe_id] = dynamic.get(pipe_id, 0.0) + value
    return static, dynamic


def build_pipe_equiv_detail(analysis, l_current: Dict[Tuple[str, str], float],
                            cad=None, kinds: Dict[Tuple[str, str], str] = None
                            ) -> Dict[str, List[Tuple[str, float]]]:
    """按管道聚合当量来源：{pipe_id: [(显示名, 长度m)...]}，供预览 Alt+悬停明细展示。

    显示名只含管件/阀门类型（90弯头/异径/蝶阀/三通直通/三通侧通/四通直通/四通侧通/四通混合），
    不含节点编号；同类多管件按值合并、按长度降序。
    """
    out: Dict[str, Dict[str, float]] = {}
    for r in collect_equiv_detail_rows(analysis, l_current, cad, kinds):
        pid = r.get("分配管道")
        if not pid:
            continue
        cat = r.get("类别", "")
        ftype = r.get("管件类型", "")
        if cat == "静态弯头":
            name = ftype               # 90弯头 / 45弯头
        elif cat in ("静态异径", "静态阀门"):
            name = ftype               # 异径 / 蝶阀
        else:
            name = cat                 # 三通直通 / 三通侧通 / 四通直通 / 四通侧通 / 四通混合
        d = out.setdefault(pid, {})
        d[name] = d.get(name, 0.0) + r.get("当量长度(m)", 0.0)
    return {pid: sorted(((n, round(v, 4)) for n, v in d.items()), key=lambda x: -x[1])
            for pid, d in out.items()}
