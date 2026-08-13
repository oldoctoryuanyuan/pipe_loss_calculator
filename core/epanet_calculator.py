"""
EPANET计算器（改用 WNTR 实现）
负责调用 WNTR 的 EpanetSimulator 进行水力计算
"""
import os
import threading
import time
from typing import Dict, Tuple, Optional
import logging
import wntr

logger = logging.getLogger(__name__)

class EpanetCalculator:
    """EPANET计算器（WNTR版）"""
    
    def __init__(self, epanet_dir: str = "epanet2.2"):
        """
        初始化计算器（epanet_dir 参数保留兼容，但不使用）
        """
        self.is_running = False
        self.progress = 0
        self.current_status = ""
        self.last_results = None   # 保存最后一次的 WNTR 结果对象
        self.last_wn = None        # 保存最后一次的 WaterNetworkModel 对象
        
    def run_analysis(self, 
                    inp_file: str, 
                    rpt_file: Optional[str] = None,
                    bin_file: Optional[str] = None,
                    timeout: int = 60) -> Tuple[bool, str, str]:
        """
        使用 WNTR 运行水力分析（需求驱动模式）
        
        Args:
            inp_file: 输入INP文件路径
            rpt_file: 输出报告文件路径（可选，WNTR 不自动生成，但我们可以生成一个简化的报告）
            bin_file: 输出二进制文件路径（可选，WNTR 不生成）
            timeout: 超时时间（秒）
            
        Returns:
            (success, message, report_path)
        """
        if not os.path.exists(inp_file):
            return False, f"INP文件不存在: {inp_file}", ""
        
        try:
            self.is_running = True
            self.progress = 0
            self.current_status = "正在加载模型..."

            # 1. 读取 INP 文件创建管网模型
            wn = wntr.network.WaterNetworkModel(inp_file)

            self.progress = 30
            self.current_status = "正在运行水力模拟..."

            # 2. 确保使用需求驱动分析（DDA）
            wn.options.hydraulic.demand_model = 'DDA'

            # 3. 运行模拟（使用 EpanetSimulator 保持与 EPANET 结果一致）
            sim = wntr.sim.EpanetSimulator(wn)
            
            # 启动一个线程来模拟进度（WNTR 本身不提供进度回调）
            def monitor():
                elapsed = 0
                while self.is_running and elapsed < timeout:
                    time.sleep(0.5)
                    elapsed += 0.5
                    self.progress = min(90, int((elapsed / timeout) * 90))
                    if elapsed < timeout * 0.3:
                        self.current_status = "正在读取网络数据..."
                    elif elapsed < timeout * 0.6:
                        self.current_status = "正在执行水力分析..."
                    else:
                        self.current_status = "正在生成计算结果..."

            monitor_thread = threading.Thread(target=monitor)
            monitor_thread.daemon = True
            monitor_thread.start()

            # 实际计算（可能会阻塞）
            results = sim.run_sim()

            self.is_running = False
            self.progress = 100
            self.current_status = "计算完成"

            # 保存结果对象供解析器使用
            self.last_results = results
            self.last_wn = wn

            # 如果需要生成 rpt 文件（可选），可以在这里写一个简单的报告
            if rpt_file:
                self._generate_simple_rpt(results, wn, rpt_file)

            logger.info("WNTR 计算成功完成")
            return True, "计算成功完成", rpt_file if rpt_file else ""

        except Exception as e:
            self.is_running = False
            self.progress = 0
            self.current_status = f"计算失败: {str(e)}"
            logger.error(f"WNTR 计算异常: {e}", exc_info=True)
            return False, f"计算失败: {str(e)}", ""

    # ---------- 内存模式（P3 优化：模型只加载一次，迭代间改 demand/head 直接重算） ----------
    def load_model(self, inp_file: str) -> Tuple[bool, str]:
        """将 INP 加载为内存模型（仅首次需要），保存到 self.last_wn，供后续内存模式复用"""
        try:
            wn = wntr.network.WaterNetworkModel(inp_file)
            wn.options.hydraulic.demand_model = 'DDA'
            self.last_wn = wn
            logger.info(f"内存模型加载成功: {inp_file}")
            return True, ""
        except Exception as e:
            logger.error(f"加载模型失败: {e}", exc_info=True)
            return False, str(e)

    def set_demands(self, demand_map: Dict[str, float]) -> None:
        """批量设置节点需求（单位 L/s，内部转换为 WNTR 的 m³/s）"""
        if self.last_wn is None:
            return
        for node_id, q_lps in demand_map.items():
            node = self.last_wn.get_node(node_id)
            if node is None:
                continue
            try:
                ts_list = node.demand_timeseries_list
                if len(ts_list) > 0:
                    ts_list[0].base_value = q_lps / 1000.0
            except Exception as e:
                logger.warning(f"设置节点 {node_id} 需求失败: {e}")

    def set_reservoir_head(self, node_id: str, head_m: float) -> None:
        """设置水库水头（米），模式C二分时更新供水压力用"""
        if self.last_wn is None:
            return
        node = self.last_wn.get_node(node_id)
        if node is None:
            return
        try:
            node.base_head = head_m
        except Exception as e:
            logger.warning(f"设置水库 {node_id} 水头失败: {e}")

    def run_loaded_model(self) -> Tuple[bool, str]:
        """用内存模型运行水力模拟（与 run_analysis 使用同一 EpanetSimulator 引擎）"""
        if self.last_wn is None:
            return False, "模型未加载"
        try:
            sim = wntr.sim.EpanetSimulator(self.last_wn)
            results = sim.run_sim()
            self.last_results = results
            return True, "计算成功完成"
        except Exception as e:
            logger.error(f"内存模式计算异常: {e}", exc_info=True)
            return False, f"计算失败: {str(e)}"

    def _generate_simple_rpt(self, results, wn, rpt_path):
        """生成一个简化的 rpt 文件，内容与 EPANET 报告类似（可选）"""
        try:
            with open(rpt_path, 'w', encoding='utf-8') as f:
                f.write("EPANET 计算结果（由 WNTR 生成）\n")
                f.write("=" * 50 + "\n\n")
                f.write("Node Results:\n")
                f.write("--------------\n")
                f.write("Node ID          Demand     Head     Pressure\n")
                # 获取最后时间步的数据
                node_pressure = results.node['pressure'].iloc[-1]
                node_demand = results.node['demand'].iloc[-1]
                node_head = results.node['head'].iloc[-1]
                for node_id in wn.node_name_list:
                    if node_id in node_pressure.index:
                        f.write(f"{node_id:<16} {node_demand[node_id]*1000:8.2f} {node_head[node_id]:8.2f} {node_pressure[node_id]:8.2f}\n")
                f.write("\n")
                f.write("Link Results:\n")
                f.write("--------------\n")
                # 获取管道数据
                link_flow = results.link['flowrate'].iloc[-1]
                link_velocity = results.link['velocity'].iloc[-1] if 'velocity' in results.link else None
                if 'headloss' in results.link:
                    link_headloss = results.link['headloss'].iloc[-1]
                    f.write("Link ID          Flow     Velocity HeadLoss(m)\n")
                    for link_id in wn.link_name_list:
                        if link_id in link_flow.index:
                            flow_lps = link_flow[link_id] * 1000
                            vel = link_velocity[link_id] if link_velocity is not None else 0
                            hl = link_headloss[link_id] if link_headloss is not None else 0
                            f.write(f"{link_id:<16} {flow_lps:8.2f} {vel:8.2f} {hl:8.4f}\n")
                else:
                    f.write("Link ID          Flow     Velocity\n")
                    for link_id in wn.link_name_list:
                        if link_id in link_flow.index:
                            flow_lps = link_flow[link_id] * 1000
                            vel = link_velocity[link_id] if link_velocity is not None else 0
                            f.write(f"{link_id:<16} {flow_lps:8.2f} {vel:8.2f}\n")
        except Exception as e:
            logger.warning(f"生成 rpt 文件失败: {e}")

    def get_status(self):
        """获取当前计算状态"""
        return {
            "is_running": self.is_running,
            "progress": self.progress,
            "status": self.current_status
        }