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
# ============================================================================
# 模块说明：
# 天正式支状喷淋倒推求解器——针对"支状（树状）管网"的喷淋系统，
# 按《自动喷水灭火系统设计规范》特性系数法思想做逐段逆推计算，
# 完全不依赖 WNTR/EPANET（与 pressure_driven_solver 的迭代思路不同，
# 本模块利用支状管网流向唯一的性质做确定性计算）。
#
# 使用场景与触发条件：计算页选择"支状喷淋倒推法"时由 GUI 调用；
# 管网必须为严格树状（存在环即拒绝，返回错误提示建议改用其他算法）。
#
# 核心数据结构（内存布局）：
#   l_current: {(node_id, pipe_id): 支流当量长度}   —— 三通/四通节点处
#              每条出水管对应的当量长度（直通 ld 或侧向 Ls）
#   kinds:     {(node_id, pipe_id): "直通"/"侧通"} —— 与 l_current 同步
#   l_calc:    {pipe_id: 计算长度 m} = 几何长度×(1+tz_ratio) + 静态当量 + 支流当量
#   parent / parent_pipe / children: BFS 建树结果（parent 为 None 表示根）
#   node_flow / pipe_flow / node_pressure / pipe_headloss / pipe_velocity:
#               迭代收敛后的最终结果字典（键为节点/管道 ID）
#   sprinkler_self_flow: {node_id: 喷头自身流量 L/s}（非喷头节点为 0）
#
# 关键数值约定：
#   tz_ratio 默认 0.015（支状喷淋倒推法局部水损系数，与当量长度法区分）；
#   内径修正 inner_diameter_offset（mm，如 -1.0）在 _headloss/_velocity 中
#   统一叠加到 CAD 内径上再换算为米；
#   C 值取管材 roughness（海曾-威廉姆斯系数，与 EPANET 一致便于对照），
#   缺失或非正时兜底 120。
#
# 调用关系：GUI 计算页 → solve()；内部调用 core.fitting_analyzer.analyze_fittings
# 做管件当量分析；结果结构（node_results/pipe_results/summary）与
# ResultParser 输出同构，供页面表格与导出统一消费。
# ============================================================================
import math
# 数学库：平方根（喷头流量公式 q=C·√P）与圆周率（流速截面积计算）
import logging
# 日志系统：solve 异常路径输出完整堆栈
from typing import Dict, List, Set, Tuple, Optional, Callable
# 类型标注：字段与方法签名的类型声明（Optional 用于可能为 None 的父节点等）
from collections import defaultdict
# 默认字典：children 邻接表自动初始化为空列表，免去显式判空

logger = logging.getLogger(__name__)


class TianzhengTreeSolver:
    """支状喷淋倒推法求解器（模式无关、独立于 WNTR）"""
    # 求解器主体：一次性注入全部输入参数（管件/水力/节点选择），
    # 调用 solve() 后从字段读取结果。生命周期：单次计算会话内创建与丢弃。

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
        # 构造器：固化全部计算输入，避免求解过程中参数被外部修改。
        # 参数语义：
        #   cad_data_manager：CAD 数据管理器（节点/管道/管件数据源）
        #   sprinkler_K：默认喷头流量系数 K（无 per-node 覆盖时使用）
        #   target_min_pressure：最低工作压力 P0（m 水柱），迭代目标值
        #   selected_node_ids：勾选的喷头节点集合（参与计算与收敛判据）
        #   k_value_map：按节点覆盖的 K 值表（per-node 喷头差异）
        #   tz_ratio：支状喷淋倒推法局部水损系数（默认 0.015）
        #   tables：可选注入的当量数据表（测试用；None 时由 fitting_analyzer 内置）
        #   progress_callback：进度回调 fn(None, message)，GUI 显示进度
        #   inner_diameter_offset：内径修正量（mm，如 -1.0）
        self.cad = cad_data_manager
        # 保存 CAD 数据管理器引用（全类数据源）
        self.default_K = float(sprinkler_K)
        # 默认喷头 K 值（强制浮点，防止传入字符串/整数）
        self.target_pressure = float(target_min_pressure)   # m 水柱
        # 最低工作压力目标 P0（m 水柱），既是迭代目标也是喷头初值
        self.selected_node_ids = set(selected_node_ids or [])
        # 勾选喷头集合：转 set 去重；None 时为空集（solve 前置检查会拒绝）
        self.k_value_map = dict(k_value_map or {})
        # per-node K 覆盖表：复制为独立字典，防止外部后续修改污染
        self.tz_ratio = float(tz_ratio)                     # 支状喷淋倒推法局部水损系数
        # 局部水损系数：乘到几何长度上，一次性计入全部管道
        self.tables = tables                                # 可选注入当量表（测试用）
        # 当量数据表（三通/四通侧向值等）；None 时用 fitting_analyzer 默认
        self.progress_callback = progress_callback
        # 进度回调引用（可为 None；GUI 场景注入后 _notify 才会真正输出）
        self.inner_diameter_offset = float(inner_diameter_offset)  # 内径修正量（mm，如 -1.0）
        # 内径修正量（mm）：叠加到 CAD 内径再换算为米（如镀锌管按减 1mm 计算）

        self.analysis = None          # FittingAnalysisResult（static_lengths/tables/fittings）
        # 管件分析结果：由 solve() 第 1 步调用 analyze_fittings 填充；
        # 含静态当量 static_lengths、当量数据表 tables、管件明细 fittings
        self.l_current: Dict[Tuple[str, str], float] = {}   # (node, pipe) -> 支流当量长度
        # 三通/四通节点的支流当量长度表：键 (节点, 出水管)
        self.kinds: Dict[Tuple[str, str], str] = {}         # (node, pipe) -> "侧通"
        # 三通/四通分类表：同键记录 "直通"/"侧通"（供 GUI 展示与调试）
        self.l_calc: Dict[str, float] = {}                  # pipe_id -> 管道计算长度(m)
        # 管道计算长度表：几何×(1+系数)+静态当量+支流当量，水损计算直接用

        self.parent: Dict[str, Optional[str]] = {}
        # 树结构：节点 -> 父节点（根为 None）
        self.parent_pipe: Dict[str, Optional[str]] = {}
        # 树结构：节点 -> 连接父节点的管道 ID（根为 None）
        self.children: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        # 树结构：节点 -> [(子节点, 管道 ID)] 列表（建树时填充）
        self.root: Optional[str] = None
        # 供水点节点 ID：取 supply_nodes[0].node_ids[0]（solve 第 0 步）
        self.supply_pressure = 0.0                          # 供水点所需表压 (m)
        # 供水点所需压力（m 水柱）：solve 完成后 = 根节点需求压力
        self.total_flow = 0.0                               # 供水点总流量 (L/s)
        # 供水点总流量（L/s）：solve 完成后 = 根节点流量
        self.sprinkler_self_flow: Dict[str, float] = {}     # 喷头节点自身流量（非喷头 0）
        # 喷头自身流量表：键为节点 ID；非喷头节点不存在于表（读取时 get 兜底 0）

    # ---------- 进度 ----------
    def _notify(self, message: str) -> None:
        # 进度通知：转发给注入的 progress_callback（GUI 场景刷新进度条/状态栏）。
        # 回调异常被静默吞掉（try/except pass）：进度显示失败不影响计算正确性，
        # 也防止第三方回调抛错中断整个求解。
        if self.progress_callback:
            try:
                self.progress_callback(None, message)
            except Exception:
                pass

    # ---------- 主流程 ----------
    def solve(self) -> Tuple[bool, Optional[Dict], str]:
        # 主入口：前置检查 → 管件分析 → 建树 → 当量预分配 → 迭代 → 结果组装。
        # 返回 (成功标志, 结果字典或 None, 消息)；结果字典结构与
        # ResultParser 输出同构（node_results/pipe_results/summary/status）。
        try:
            # 0. 前置检查
            if not self.cad.supply_nodes or not self.cad.supply_nodes[0].node_ids:
                # 无供水点数据：supply_nodes 为空或首个供水点无节点 → 直接拒绝
                return False, None, "没有供水点数据"
            self.root = self.cad.supply_nodes[0].node_ids[0]
            # 取第一个供水点的第一个节点为根（本算法只支持单一供水点）
            if not self.selected_node_ids:
                # 未勾选任何喷头：无计算对象 → 直接拒绝
                return False, None, "没有勾选的喷头节点"

            # 1. 管件分析（静态当量 + 当量数据表）
            from core.fitting_analyzer import analyze_fittings
            # 延迟导入：避免模块加载时就依赖 fitting_analyzer（减少循环依赖风险）
            self.analysis = analyze_fittings(self.cad, self.tables)
            # 执行管件当量分析：产出静态当量/当量表/管件明细，供当量预分配使用
            if self.analysis.error_nodes:
                # 存在画图错误节点（如管件连接不严谨）：无法可靠计算，逐条列出
                detail = "\n".join(f"节点{nid}：{reason}" for nid, reason in self.analysis.error_nodes)
                return False, None, "管网存在画图错误或不严谨，请在CAD中修正后重新读取：\n" + detail
            if self.analysis.missing_data:
                # 当量数据缺失（如未知管径没有对应表值）：无法给当量长度，拒绝计算
                detail = "\n".join(self.analysis.missing_data)
                return False, None, "当量长度数据缺失，无法进行支状喷淋倒推法计算：\n" + detail

            # 2. 环检测 + 建树
            ok, err = self._build_tree()
            # BFS 建树并顺带检测环路；非支状（有环）返回错误信息
            if not ok:
                return False, None, err

            # 3. 喷头可达性检查
            unreachable = [n for n in self.selected_node_ids if n not in self.parent and n != self.root]
            # 勾选喷头不在树中（未连通到供水点）→ 无法计算，列出全部不可达节点
            if unreachable:
                return False, None, "以下喷头未连接到供水点，无法计算：\n" + ", ".join(sorted(unreachable))

            # 4. 当量预分配（支状流向唯一，一次算好）
            self._assign_equiv_lengths()
            # 支状管网流向唯一（供水点→喷头），三通/四通当量可一次性分配，
            # 无需像当量长度法那样迭代修正

            # 5. 迭代倒推（单调压力需求迭代）
            self._notify("支状喷淋倒推法：开始计算")
            ok, converged = self._iterate_to_convergence()
            # 核心迭代：自叶向根累流量/算需求，自根向叶正推压力，循环至收敛
            if not ok:
                # 20 轮未收敛：通常意味着管网结构异常（如极端管径组合），
                # 直接报告失败而非无限循环
                return False, None, "支状喷淋倒推法迭代超过20轮未收敛，请检查管网结构"

            # 6. 供水点结果
            self.supply_pressure = self.node_pressure.get(self.root, 0.0)
            # 供水点所需表压 = 根节点需求压力（迭代 b 步算出的 need[root]）
            self.total_flow = self.node_flow.get(self.root, 0.0)
            # 供水点总流量 = 根节点累计流量（迭代 a 步累加的 node_q[root]）
            self._notify("支状喷淋倒推法：计算完成")
            results = self._build_results()
            # 组装统一结果字典（节点/管道/摘要），供页面与导出消费
            return True, results, self._summary_message()
            # 成功返回：结果字典 + 一句话摘要（供水点压力/总流量）

        except Exception as e:
            logger.error(f"支状喷淋倒推法计算异常: {e}", exc_info=True)
            # 兜底异常处理：任何未预期错误在此捕获并转为失败返回（含完整堆栈）
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
        # 先序遍历结果：根 → 叶（子节点入栈顺序影响遍历序，但不影响正确性）
        stack = [self.root]
        while stack:
            n = stack.pop()
            order.append(n)
            for child, _ in self.children.get(n, []):
                stack.append(child)
        post = list(reversed(order))          # 叶 → 根
        # 后序遍历：反转先序即得"子节点先于父节点"的访问序，用于累加流量与需求
        pre = order                           # 根 → 叶
        # 先序遍历：父节点先于子节点，用于正推实际压力

        # 喷头当前实际压力（初值 = 目标压力，之后单调上升）
        spr_p: Dict[str, float] = {n: self.target_pressure for n in self.selected_node_ids}
        # 迭代状态：当前实际压力表。初值 = P0（目标压力），
        # d 步只增不减（new_p > spr_p[n] 才更新），保证单调上升 → 必收敛

        prev_pressure = {n: -1.0 for n in self.selected_node_ids}
        # 上一轮实际压力表：初值 -1.0（保证第一轮 max_dp 必然很大，不会误判收敛）
        for rnd in range(20):
            # 迭代上限 20 轮：单调迭代通常 2~5 轮收敛；超限视为结构异常
            self._notify(f"支状喷淋倒推法：第{rnd + 1}轮迭代")
            # a. 自叶向根累加流量
            node_q: Dict[str, float] = {}
            # 本轮各节点累计流量（L/s）：叶节点仅含自身喷头流量
            pipe_q: Dict[str, float] = {}
            # 本轮各管道流量（L/s）：带符号，方向约定见下方
            for n in post:
                # 自叶向根遍历：保证子节点流量先算好，父节点才能累加
                q = self._sprinkler_flow(n, spr_p.get(n, 0.0)) if n in spr_p else 0.0
                # 自身流量：喷头节点按当前压力算 q=C√P，非喷头节点为 0
                for child, pid in self.children.get(n, []):
                    child_q = node_q.get(child, 0.0)
                    q += child_q
                    # 累加子节点流量：管道流量 = 下游全部喷头流量之和
                    # 带符号：水流方向 = 父 → 子；与管道 start→end 同向为正，反向为负
                    pipe = self.cad.pipe_by_id.get(pid)
                    if pipe and pipe.start_node_id != n:
                        child_q = -child_q
                    # 符号约定：管道在 CAD 中的 start/end 未必与水流方向一致；
                    # 若当前节点是管道的 end，则水流方向与管道方向相反 → 取负。
                    # 此符号仅用于 GUI 显示与水力方向一致，水损计算取绝对值
                    pipe_q[pid] = child_q
                node_q[n] = q
                # 节点累计流量 = 自身 + 全部子支路流量
            # b. 自叶向根计算节点需求压力（分支点取 max）
            need: Dict[str, float] = {}
            # 需求压力表：节点所需最低供水压力（m），保证该节点下游全部喷头达标
            for n in post:
                base = self.target_pressure if n in spr_p else 0.0
                # 自身基准：喷头节点需 ≥ P0；非喷头节点基准 0
                for child, pid in self.children.get(n, []):
                    h = self._headloss(node_q.get(child, 0.0), pid)
                    # 子支路管道水损（m）：按子节点流量与管道计算长度算
                    z_n = self._node_z(n)
                    z_c = self._node_z(child)
                    base = max(base, need.get(child, 0.0) + h + (z_c - z_n))
                    # 子支路需求 = 子节点需求 + 水损 + 高程差（子高父低为正，需额外压力）
                    # 分支点取所有子支路需求的**最大值**：保证所有喷头同时满足最低压力
                need[n] = base
                # 节点需求压力 = 自身基准与各子支路需求的最大值
            supply_need = need.get(self.root, 0.0)
            # 供水点所需压力 = 根节点需求压力（b 步最终结果）
            # c. 自根向叶正推实际压力
            actual: Dict[str, float] = {self.root: supply_need}
            # 实际压力表：根节点压力 = 供水点需求压力，逐层向下扣除水损与高程差
            for n in pre:
                # 自根向叶遍历：父节点压力先算出，子节点才能继承
                for child, pid in self.children.get(n, []):
                    h = self._headloss(node_q.get(child, 0.0), pid)
                    z_n = self._node_z(n)
                    z_c = self._node_z(child)
                    actual[child] = actual[n] - h - (z_c - z_n)
                    # 子节点实际压力 = 父节点压力 - 管损 - 高程差；
                    # 与 b 步公式互为逆运算，保证满足性与一致性
            # d. 更新喷头实际压力（单调不减），检查收敛
            max_dp = 0.0
            # 两轮间最大压力变化量（收敛判据之一）
            for n in spr_p:
                new_p = actual.get(n, self.target_pressure)
                # 本轮实际压力（理论上所有喷头都可达，缺省兜底 P0）
                max_dp = max(max_dp, abs(new_p - prev_pressure.get(n, new_p)))
                prev_pressure[n] = new_p
                # 记录本轮压力供下一轮比较
                if new_p > spr_p[n]:
                    spr_p[n] = new_p
                # 单调不减更新：只升不降。由于流量随压力单调增，
                # 水损随流量单调增，压力只会逐轮上升 → 必然收敛于不动点
            # 全部喷头满足最低压力且两轮稳定 → 收敛
            all_ok = all(actual.get(n, 0.0) >= self.target_pressure - 1e-6 for n in spr_p)
            # 满足性判据：全部喷头实际压力 ≥ P0（1e-6 容差避免浮点边界抖动）
            if all_ok and max_dp < 0.001:
                # 双重收敛条件：满足最低压力 + 两轮间压力变化 < 0.001m（稳定）
                # 记录最终结果
                self.node_flow = node_q
                # 节点流量表（L/s）：页面表格与结果导出读取
                self.pipe_flow = pipe_q
                # 管道流量表（带符号 L/s）
                self.node_pressure = actual
                # 节点实际压力表（m）：供水点压力 = actual[root]
                self.pipe_headloss = {pid: self._headloss(q, pid) for pid, q in pipe_q.items()}
                # 整管水损表（m）：按最终流量重算一次（与 pipe_flow 同键）
                self.pipe_velocity = {pid: self._velocity(q, pid) for pid, q in pipe_q.items()}
                # 管道流速表（m/s）：按最终流量重算
                self.sprinkler_self_flow = {
                    n: self._sprinkler_flow(n, spr_p.get(n, 0.0)) for n in spr_p}
                # 喷头自身流量表：按收敛后压力算 q=C√P（非喷头节点不在表内）
                return True, True
        return False, False
        # 20 轮未收敛：返回 (False, False)，由 solve 报告错误

    # ---------- 环检测与建树 ----------
    def _build_tree(self) -> Tuple[bool, str]:
        # 建树 + 环检测：从供水点出发 BFS/DFS，构建 parent/parent_pipe/children；
        # 发现非树边（成环）即返回失败——支状倒推法要求严格树状管网。
        adj: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        # 邻接表：node_id -> [(pipe_id, 邻接节点)]，仅含激活管道与激活节点
        for pipe in self.cad.pipes:
            if not pipe.is_active:
                continue
            # 跳过关闭（未激活）管道：不参与水力路径
            sn = self.cad.node_by_id.get(pipe.start_node_id)
            en = self.cad.node_by_id.get(pipe.end_node_id)
            if not sn or not en or not sn.is_active or not en.is_active:
                continue
            # 端点节点缺失或未激活：该管道也无法参与（数据异常时静默跳过）
            adj[pipe.start_node_id].append((pipe.pipe_id, pipe.end_node_id))
            adj[pipe.end_node_id].append((pipe.pipe_id, pipe.start_node_id))
            # 无向边：双向登记，供从根出发的遍历使用

        if self.root not in adj:
            # 供水点孤立（无任何激活管道连接）：无法建树
            return False, f"供水点节点 {self.root} 未连接任何管道"

        self.parent = {self.root: None}
        # 父节点表：根节点的父为 None
        self.parent_pipe = {self.root: None}
        # 连接父节点的管道表：根节点无进入管道
        self.children = defaultdict(list)
        # 子节点表：遍历中填充
        loop_pipes: List[str] = []
        # 成环管段收集：发现非树边时记录该管道 ID
        stack = [self.root]
        # 显式栈 DFS（避免递归深度限制，大管网安全）
        while stack:
            n = stack.pop()
            for pid, nb in adj.get(n, []):
                if nb == self.parent.get(n):
                    continue
                # 跳过父节点方向的边（无向图中回头边不是新边）
                if nb in self.parent:
                    loop_pipes.append(pid)          # 非树边 = 成环
                    # 邻居已被访问且不是父节点 → 该边构成环；记录管段
                    continue
                self.parent[nb] = n
                # 记录父节点（同时作为"已访问"标记：parent 表非空即已入树）
                self.parent_pipe[nb] = pid
                # 记录连接父节点的管道 ID
                self.children[n].append((nb, pid))
                # 加入子节点表（节点, 管道）二元组
                stack.append(nb)
                # 继续向下遍历

        if loop_pipes:
            return False, ("该管网存在环路（非支状），不适用于支状喷淋倒推法。\n"
                           "成环管段：" + ", ".join(sorted(set(loop_pipes))) +
                           "\n请改用「当量长度法」或「局部水损系数法」。")
            # 有环即拒绝：列出成环管段并给出替代算法建议（用户体验引导）
        return True, ""
        # 成功：返回 (True, 空错误消息)

    # ---------- 当量预分配 ----------
    def _assign_equiv_lengths(self) -> None:
        """一次性分配管道计算长度：几何×(1+系数) + 三通/四通当量 + 静态当量。

        支状管网流向唯一（供水点→喷头），三通/四通节点处：
        - 与进水管构成直通对的出水管 = 直通，加直通当量（0.2×侧向表值，与当量长度法一致）；
        - 与进水管不成直通对的出水管 = 支流，加侧向当量 Ls。
        """
        tables = self.analysis.tables
        # 当量数据表（由 fitting_analyzer 提供，含各管径的三通/四通侧向值）
        side_table = tables.get("三通或四通(侧向)", {})
        # 侧向当量表：DN -> 当量长度（m）；缺表时为空字典（.get 兜底 0）

        for node_id, rec in self.analysis.fittings.items():
            # 遍历全部管件记录：只为三通/四通节点分配支流当量
            if rec.fitting_type not in ("三通", "四通"):
                continue
            # 弯头/异径等静态当量走 static_lengths，不走本分支
            in_pipe = self.parent_pipe.get(node_id)
            # 进水管 = 连接父节点的管道（流向唯一：父 → 子）
            if not in_pipe:
                continue
            # 根节点没有进水管（理论上根节点不会是三通）→ 跳过
            dn = rec.diameter_mm
            # 该三通/四通的公称管径（mm），用于查当量表
            side_value = side_table.get(str(dn), 0.0)
            # 侧向当量 Ls：按管径查表；未知管径兜底 0
            ld = 0.2 * side_value                       # 直通当量
            # 直通当量 = 0.2 × 侧向值（与当量长度法模块的约定一致）
            # 出水管中与进水管构成直通对者 = 直通；否则 = 支流
            #
            # 【2026-10-27 修复】原代码用「pair_pipes 集合」判断直通：
            #     pair_pipes = set()
            #     for p1, p2 in rec.straight_pairs:
            #         pair_pipes.add(p1); pair_pipes.add(p2)
            #     ...
            #     if in_pipe in pair_pipes and pid in pair_pipes:
            # 该判断只在三通（仅 1 对直通）下碰巧正确；四通有 2 对直通，
            # pair_pipes 会包含全部 4 根管，而进水管必然属于其中之一，
            # 于是「所有出水管」都满足条件 → 全部错判为直通（0.2×Ls），
            # 实际应为每根四通的出水管中仅 1 根直通、其余为侧通（Ls）。
            # （实测某工程 16 个四通节点 × 3 出水管 = 48 根全部错判直通）
            # 正确判定必须要求「进水管与该出水管处于同一个直通对」，
            # 而不是各自出现在直通对集合中。判定口径与
            # core/equiv_length_engine.py 一致：
            #     any(p1 in pair and p2 in pair for pair in rec.straight_pairs)
            def _is_straight_pair(a, b):
                # 仅当两管位于同一配对中才算直通（同一对的两管夹角≈180°）
                return any(a in pair and b in pair for pair in rec.straight_pairs)
            # straight_pairs：管件分析给出的直通配对列表 [(p1, p2), ...]，
            # 配对的管道互为直通（如"一字形"布置的三通，两端口成 180°）
            for child, pid in self.children.get(node_id, []):
                # 遍历该节点的全部出水管（子支路）
                if pid == in_pipe:
                    continue
                # 跳过进水管自身（它不是出水管）
                if _is_straight_pair(in_pipe, pid):
                    self.l_current[(node_id, pid)] = ld
                    self.kinds[(node_id, pid)] = "直通"
                    # 进水管与该出水管构成同一直通对 → 直通：加直通当量 ld
                else:
                    self.l_current[(node_id, pid)] = side_value
                    self.kinds[(node_id, pid)] = "侧通"
                    # 不构成同一对 → 支流（侧向）：加侧向当量 Ls

        for pipe in self.cad.pipes:
            # 第二遍：汇总每根管道的计算长度
            if not pipe.is_active:
                continue
            # 未激活管道不计算（也不会出现在结果表）
            static = self.analysis.static_lengths.get(pipe.pipe_id, 0.0)
            # 静态当量：本管上的弯头/异径/蝶阀等管件当量长度（m）
            branch = 0.0
            # 支流当量累计：本管作为三通/四通支流（或直通）被分配的当量
            for (node_id, pid), v in self.l_current.items():
                if pid == pipe.pipe_id:
                    branch += v
            # 遍历 l_current 累加属于本管道的当量（管道可能在三通节点处）
            self.l_calc[pipe.pipe_id] = (pipe.length * (1.0 + self.tz_ratio)
                                         + static + branch)
            # 计算长度 = 几何×(1+局部水损系数) + 静态当量 + 三通/四通当量；
            # 之后 _headloss 一律按 l_calc 计算（局部水损已并入）

    # ---------- 初始末端喷头：ΣL_calc 加权路径最大 ----------
    def _initial_end_sprinkler(self) -> str:
        # 初始末端喷头选择：以"计算长度加权路径最长"的喷头作为初始最不利点。
        # 注意：当前主流程（solve → _iterate_to_convergence）未调用本方法，
        # 保留它是为兼容旧版"换末端"迭代策略的接口；新策略为单调压力迭代，
        # 不再需要初始末端猜测（接口保留供外部调用/测试）。
        path_len: Dict[str, float] = {self.root: 0.0}
        # 路径累计长度表：根到各节点的 l_calc 之和
        order = [self.root]
        # 遍历队列（此处为广度推进：每访问一个节点就追加其子节点）
        for n in order:
            for child, pid in self.children.get(n, []):
                path_len[child] = path_len[n] + self.l_calc.get(pid, 0.0)
                # 子节点路径长度 = 父节点路径长度 + 该管道计算长度
                order.append(child)
        return max(self.selected_node_ids, key=lambda n: path_len.get(n, -1.0))
        # 在所有勾选喷头中取路径长度最大者；路径缺失（未连通）兜底 -1.0 排最后

    # ---------- 水损 / 流速 / 喷头流量 ----------
    def _headloss(self, q_lps: float, pipe_id: str) -> float:
        """海澄-威廉姆斯沿程水头损失（m）。

        i = 10.667 × Q^1.852 / (C^1.852 × d^4.871)   （Q: m³/s, d: m）
        C 值取管材 roughness（与 EPANET H-W 一致，便于结果对照）。
        流量带符号（沿管道 start→end 为正），水损取绝对值。
        内径按 inner_diameter_offset 修正（如减1mm计算）。
        """
        # 沿程水损计算：被迭代（b/c 步）与结果组装（pipe_headloss）两处调用。
        # 公式为海曾-威廉姆斯经验式，指数 1.852/4.871 为规范固定值；
        # 局部水损已折算进 l_calc（几何×系数+当量），此处只算沿程部分。
        if not q_lps or not pipe_id:
            # 零流量或管道 ID 缺失：水损必为 0（也避免 0 流量导致公式除零）
            return 0.0
        pipe = self.cad.pipe_by_id.get(pipe_id)
        if not pipe:
            # 管道对象缺失（数据不一致）：兜底 0，不抛异常
            return 0.0
        d_m = (pipe.inner_diameter + self.inner_diameter_offset) / 1000.0
        # 内径修正并换算为米：CAD 内径（mm）+ 修正量（mm，如 -1.0）→ m
        if d_m <= 0:
            # 内径非正（异常数据）：无法计算，兜底 0
            return 0.0
        c = pipe.roughness if pipe.roughness and pipe.roughness > 0 else 120.0
        # 海曾-威廉姆斯 C 值：取管材 roughness；缺失/非正兜底 120（常见镀锌管值）
        q_m3s = abs(q_lps) / 1000.0
        # 流量取绝对值并换算为 m³/s（方向只影响符号，不影响水损大小）
        i = 10.667 * (q_m3s ** 1.852) / (c ** 1.852 * d_m ** 4.871)
        # 海曾-威廉姆斯坡度公式：i（m/m），指数为规范固定常数
        return i * self.l_calc.get(pipe_id, pipe.length)
        # 整管水损 = 坡度 × 计算长度（优先 l_calc，缺失时回退几何长度兜底）

    def _velocity(self, q_lps: float, pipe_id: str) -> float:
        # 流速计算：v = Q/A（m/s），Q 为流量（m³/s），A 为圆管截面积。
        # 被结果组装调用（pipe_velocity）；迭代内不依赖流速，仅展示用。
        if not q_lps or not pipe_id:
            # 零流量或管道 ID 缺失：流速 0
            return 0.0
        pipe = self.cad.pipe_by_id.get(pipe_id)
        if not pipe:
            # 管道对象缺失：兜底 0
            return 0.0
        d_m = (pipe.inner_diameter + self.inner_diameter_offset) / 1000.0
        # 内径修正并换算为米（与 _headloss 完全一致，保证结果自洽）
        if d_m <= 0:
            # 内径非正：兜底 0（防止除零）
            return 0.0
        q_m3s = abs(q_lps) / 1000.0
        # 流量取绝对值并换算为 m³/s
        return q_m3s / (math.pi * d_m * d_m / 4.0)
        # v = Q / (πd²/4)：圆管截面流速

    def _sprinkler_flow(self, node_id: str, pressure_m: float) -> float:
        """喷头流量（L/s）：q = C·√P，C = K/60·√0.1（与压力驱动求解器一致）"""
        # 喷头出流公式：q = K·√(10P)（L/min）换算为 L/s 即 q = K/60·√(10P)；
        # 与 pressure_driven_solver 的 C 系数定义完全一致，保证两种算法结果可对照。
        if pressure_m <= 0:
            # 压力非正：喷头不出流（q=0），避免对负数开平方
            return 0.0
        k = self.k_value_map.get(node_id, self.default_K)
        # 优先取 per-node K 覆盖值；无覆盖时用默认 K
        c = k / 60.0 * math.sqrt(0.1)
        # C 系数 = K/60·√0.1（把 q=K√(10P) L/min 折算为 L/s 的常数）
        return c * math.sqrt(pressure_m)
        # 喷头流量 = C·√P（L/s）

    # ---------- 辅助 ----------
    def _node_z(self, node_id: str) -> float:
        # 节点高程（米）：CAD 节点 z 为毫米（mm），除以 1000 换算为米。
        # 被迭代 b/c 步调用，用于高程差修正（子节点高于父节点需额外压力）。
        node = self.cad.node_by_id.get(node_id)
        return (node.z / 1000.0) if node else 0.0
        # 节点缺失（数据不一致）时兜底 0（视为与基准同高）

    # ---------- 结果组装 ----------
    def _build_results(self) -> Dict:
        # 结果组装：把求解器内部字典转换为与 ResultParser 同构的统一结构，
        # 供页面表格（节点/管道标签页）、摘要栏与导出功能直接消费。
        node_results = []
        # 节点结果列表：每行一个激活节点
        for node in self.cad.nodes:
            if not node.is_active:
                continue
            # 只输出激活节点（关闭节点不出现在结果表）
            nid = node.node_id
            p = self.node_pressure.get(nid, 0.0)
            # 节点实际压力（m）；未在树中的节点兜底 0
            node_results.append({
                "node_id": nid,
                "demand_lps": self.sprinkler_self_flow.get(nid, 0.0),
                # 节点流量 = 喷头自身流量（非喷头节点不在表中 → 0）
                "head_m": node.z / 1000.0 + p,
                # 总水头 = 高程（mm→m）+ 压力（m），与 EPANET head 语义一致
                "pressure_m": p,
                # 节点压力（m 水柱）
            })

        pipe_results = []
        # 管道结果列表：每行一条激活管道
        for pipe in self.cad.pipes:
            if not pipe.is_active:
                continue
            # 只输出激活管道
            pid = pipe.pipe_id
            flow = self.pipe_flow.get(pid, 0.0)
            # 管道流量（带符号 L/s；方向与 CAD start→end 一致为正）
            hl = self.pipe_headloss.get(pid, 0.0)          # 整管水损 (m)
            # 整管水损（m）：迭代收敛时按最终流量计算
            lcalc = self.l_calc.get(pid, pipe.length)
            # 计算长度（m）：几何+当量折算；缺失回退几何长度
            # headloss_m 字段语义 = 单位水损 (m/m)（与 EPANET/ResultParser 一致），
            # GUI 层水损 = headloss_m × calc_length；整管水损 = hl / lcalc × calc_length
            unit_hl = hl / lcalc if lcalc > 0 else 0.0
            # 单位水损 = 整管水损 / 计算长度（m/m）；lcalc 非正兜底 0 防除零
            pipe_results.append({
                "pipe_id": pid,
                "node1": pipe.start_node_id,
                "node2": pipe.end_node_id,
                # 两端节点 ID（CAD 原始命名）
                "flow_lps": flow,
                "velocity_mps": self.pipe_velocity.get(pid, 0.0),
                # 流速（m/s）
                "headloss_per_km": unit_hl * 1000.0,
                # 每千米水损（m/km）：单位水损 ×1000，供表格列直接显示
                "headloss_m": unit_hl,
                # 单位水损（m/m）：GUI 按此值 × calc_length 显示整管水损
                "diameter": pipe.inner_diameter,
                # 内径（mm）
                "nominal_diameter": pipe.nominal_diameter,
                # 公称管径
                "length": pipe.length,
                # 几何长度（m）
                "material": pipe.material,
                # 管材
                "roughness": pipe.roughness,
                # 粗糙度（海曾-威廉姆斯 C 值）
                "status": "Open" if pipe.status == "开" else "Closed",
                # 状态映射：CAD 中文"开/关" → 英文 Open/Closed（与 ResultParser 一致）
                "calc_length": lcalc,
                # 计算长度（m）：新增字段，供 GUI 水损计算使用
            })

        pressures = [r["pressure_m"] for r in node_results]
        # 全部节点压力列表（供摘要统计）
        summary = {
            "total_demand": sum(r["demand_lps"] for r in node_results),
            # 总需求（L/s）：全部节点流量之和（= 供水点总流量）
            "average_pressure": sum(pressures) / len(pressures) if pressures else 0,
            # 平均压力：节点压力均值；空列表兜底 0 防除零
            "maximum_pressure": max(pressures, default=0),
            # 最大压力：空列表兜底 0（default 参数防 ValueError）
            "minimum_pressure": min(pressures, default=0),
            # 最小压力：空列表兜底 0；最小压力对应最不利喷头位置
            "number_of_nodes": len(node_results),
            # 节点数
            "number_of_pipes": len(pipe_results),
            # 管道数
        }
        return {
            "node_results": node_results,
            # 节点结果表
            "pipe_results": pipe_results,
            # 管道结果表
            "demand_results": {},
            # 需求结果：预留空字典（当前未使用，与 ResultParser 结构对齐）
            "summary": summary,
            # 摘要统计
            "status": "完成",
            # 状态标记：成功路径恒为 "完成"
        }

    def _summary_message(self) -> str:
        # 一句话摘要：供水点所需压力与总流量（solve 成功时作为返回消息展示）。
        # 数值格式：压力 2 位小数（m），流量 3 位小数（L/s）。
        return (f"支状喷淋倒推法计算完成：供水点所需压力 = {self.supply_pressure:.2f}m，"
                f"总流量 = {self.total_flow:.3f}L/s")
