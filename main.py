# pipe_loss_calculator/main.py
import tkinter as tk
from tkinter import ttk, font, messagebox
import os
import sys
import logging
from datetime import datetime
# logging.basicConfig(level=logging.DEBUG)

# 获取程序所在目录
if getattr(sys, 'frozen', False):  # 如果是打包后的程序
    BASE_DIR = os.path.dirname(sys.executable)
else:  # 如果是源代码
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 添加项目根目录到Python路径
sys.path.insert(0, BASE_DIR)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(BASE_DIR, "app.log"), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

from config.config_manager import ConfigManager
from config.material_manager import MaterialManager
from cad_data_manager import CADDataManager
from gui.settings_page import SettingsPage
from gui.pipe_module import PipePage
from gui.node_module import NodePage
from gui.supply_demand_module import SupplyDemandPage
from gui.valve_module import ValvePage
from gui.preview_module import PreviewPage
from gui.calculation_module import CalculationPage
from export_import_manager import ProjectExporter, ProjectImporter


class MainApplication:
    """主应用程序"""
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("管网水损计算程序")
        self.root.geometry("1200x800")
        
        # 设置字体
        default_font = font.nametofont("TkDefaultFont")
        default_font.configure(size=9)

        # 设置日志级别，减少不必要的输出
        logging.getLogger('pyautocad').setLevel(logging.WARNING)
        logging.getLogger('comtypes').setLevel(logging.WARNING)
        
        # ✅ 使用grid布局而不是pack
        self.root.grid_rowconfigure(0, weight=1)  # notebook占用剩余空间
        self.root.grid_rowconfigure(1, weight=0)  # status_bar固定高度
        self.root.grid_columnconfigure(0, weight=1)
        
        # 创建主容器
        self.main_container = ttk.Frame(self.root)
        self.main_container.grid(row=0, column=0, sticky="nsew")
        self.main_container.grid_rowconfigure(0, weight=1)
        self.main_container.grid_columnconfigure(0, weight=1)
        
        # 初始化管理器
        self.config_manager = ConfigManager(os.path.join(BASE_DIR, "config.json"))
        self.material_manager = MaterialManager(os.path.join(BASE_DIR, "materials.json"))
        self.cad_data_manager = CADDataManager(
            self.config_manager,
            self.material_manager,
            os.path.join(BASE_DIR, "cad_cache.json")
        )
        
        # 创建标签页
        self.notebook = ttk.Notebook(self.main_container)
        self.notebook.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        
        # 存储页面实例
        self.pages = {}
        
        # 创建各个页面
        self.create_pages()

        # 创建菜单栏
        self._create_menu_bar()

        # 绑定事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)
        
        # 状态栏
        self.create_status_bar()
        
        # ✅ 初始化提示消息队列
        self.pending_messages = []
        self.root.main_app = self   # 新增：让根窗口可以访问主应用实例
        logger.info("主应用程序初始化完成")

    def show_temp_message(self, message: str, duration: int = 2000):
        """显示临时消息"""
        # 保存原始状态
        original_text = self.data_status_label.cget("text")
        original_color = self.data_status_label.cget("foreground")
        
        # 显示新消息
        self.data_status_label.config(text=message, foreground="green" if "成功" in message else "red")
        
        # 设置定时器恢复原状
        def restore():
            self.data_status_label.config(text=original_text, foreground=original_color)
        
        self.after(duration, restore)

    def get_data_status_text(self):
        """获取数据状态文本"""
        if self.cad_data_manager.is_loaded and self.cad_data_manager.cad_file_path:
            file_name = os.path.basename(self.cad_data_manager.cad_file_path)
            pipes_count = len(self.cad_data_manager.pipes)
            nodes_count = len(self.cad_data_manager.nodes)
            
            if pipes_count == 0 and nodes_count == 0:
                return f"数据: {file_name} (无数据)"
            else:
                return f"数据: {file_name} ({pipes_count}管, {nodes_count}节)"
        else:
            return "数据: 未加载"

    def reset_calculation_and_preview(self):
        """重置计算页面和预览页面的缓存数据"""
        if '计算' in self.pages and hasattr(self.pages['计算'], 'reset_state'):
            self.pages['计算'].reset_state()
        if '管网预览' in self.pages and hasattr(self.pages['管网预览'], 'reset_state'):
            self.pages['管网预览'].reset_state()

    def create_status_bar(self):
        """创建状态栏（始终显示）"""
        # ✅ 直接添加到root而不是main_container
        status_frame = ttk.Frame(self.root, height=25)
        status_frame.grid(row=1, column=0, sticky="ew")
        status_frame.grid_propagate(False)  # 固定高度
        
        # CAD状态
        self.cad_status_label = ttk.Label(
            status_frame,
            text="CAD: 未连接",
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(5, 0)
        )
        self.cad_status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 数据状态
        self.data_status_label = ttk.Label(
            status_frame,
            text="数据: 未加载",
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(5, 0)
        )
        self.data_status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 版本信息
        version_label = ttk.Label(
            status_frame,
            text="管网水损计算程序 v1.0",
            relief=tk.SUNKEN,
            anchor=tk.E,
            padding=(5, 0)
        )
        version_label.pack(side=tk.RIGHT)
    
    def update_status(self):
        """更新状态栏"""
        # CAD连接状态
        if hasattr(self.cad_data_manager, 'acad') and self.cad_data_manager.acad:
            cad_status = "CAD: 已连接"
        else:
            cad_status = "CAD: 未连接"
        
        # 数据状态（显示详细信息）
        if self.cad_data_manager.is_loaded and self.cad_data_manager.cad_file_path:
            file_name = os.path.basename(self.cad_data_manager.cad_file_path)
            pipes_count = len(self.cad_data_manager.pipes)
            nodes_count = len(self.cad_data_manager.nodes)
            
            if pipes_count == 0 and nodes_count == 0:
                data_status = f"数据: {file_name} (无数据)"
            else:
                data_status = f"数据: {file_name} ({pipes_count}管, {nodes_count}节)"
        else:
            data_status = "数据: 未加载"
        
        self.cad_status_label.config(text=cad_status)
        self.data_status_label.config(text=data_status)
    
    def on_tab_changed(self, event):
        """标签页切换事件"""
        try:
            selected_tab = self.notebook.select()
            if not selected_tab:
                return
            
            tab_index = self.notebook.index(selected_tab)
            tab_text = self.notebook.tab(tab_index, "text")
            
            logger.debug(f"切换到标签页: {tab_text}")
            
            # 更新状态栏
            self.update_status()
            
            # 自动刷新当前页面的数据
            if tab_text in self.pages:
                page = self.pages[tab_text]
                if hasattr(page, 'refresh_data'):
                    try:
                        page.refresh_data()
                    except Exception as e:
                        logger.error(f"自动刷新{tab_text}页面数据失败: {e}")
                        
        except Exception as e:
            logger.error(f"标签页切换错误: {e}")

    def on_closing(self):
        """退出时保存数据"""
        try:
            # 保存最后使用的CAD文件路径
            if self.cad_data_manager.cad_file_path:
                self.config_manager.update_global_setting("last_cad_file", self.cad_data_manager.cad_file_path)
            # 保存配置 
            if hasattr(self, 'settings_page'):
                self.config_manager.save_temp_scheme(self.settings_page.current_config)
            
            # 关闭CAD数据管理器
            self.cad_data_manager.close()
            
            logger.info("应用程序正在关闭...")
            
        except Exception as e:
            logger.error(f"关闭应用程序时出错: {e}")
        
        # 关闭窗口
        self.root.destroy()
    
    def create_pages(self):
        """创建所有标签页"""
        # 设置页面
        self.settings_page = SettingsPage(
            self.notebook,
            self.config_manager,
            self.material_manager,
            self.cad_data_manager
        )
        self.notebook.add(self.settings_page, text="设置")
        self.pages["设置"] = self.settings_page
        
        # 管道页面
        self.pipe_page = PipePage(
            self.notebook,
            self.config_manager,
            self.material_manager,
            self.cad_data_manager
        )
        self.notebook.add(self.pipe_page, text="管道")
        self.pages["管道"] = self.pipe_page
        
        # 节点页面
        self.node_page = NodePage(
            self.notebook,
            self.config_manager,
            self.material_manager,
            self.cad_data_manager
        )
        self.notebook.add(self.node_page, text="节点")
        self.pages["节点"] = self.node_page
        
        # 供水点和用水点页面
        self.supply_demand_page = SupplyDemandPage(
            self.notebook,
            self.config_manager,
            self.material_manager,
            self.cad_data_manager
        )
        self.notebook.add(self.supply_demand_page, text="供水点和用水点")
        self.pages["供水点和用水点"] = self.supply_demand_page
        
        # 阀门页面
        self.valve_page = ValvePage(
            self.notebook,
            self.config_manager,
            self.material_manager,
            self.cad_data_manager
        )
        self.notebook.add(self.valve_page, text="阀门")
        self.pages["阀门"] = self.valve_page
        
        # 管网预览页面
        self.preview_page = PreviewPage(
            self.notebook,
            self.config_manager,
            self.material_manager,
            self.cad_data_manager
        )
        self.notebook.add(self.preview_page, text="管网预览")
        self.pages["管网预览"] = self.preview_page
        
        # 计算页面
        self.calculation_page = CalculationPage(
            self.notebook,
            self.config_manager,
            self.material_manager,
            self.cad_data_manager
        )
        self.notebook.add(self.calculation_page, text="计算")
        self.pages["计算"] = self.calculation_page
        
        logger.info("所有页面创建完成")

    def refresh_all_pages(self):
        """刷新所有页面的数据"""
        for page_name, page in self.pages.items():
            if hasattr(page, 'refresh_data'):
                try:
                    page.refresh_data()
                except Exception as e:
                    logger.error(f"刷新页面 {page_name} 失败: {e}")

    def notify_units_changed(self):
        """通知所有页面单位设置已改变"""
        for page_name, page in self.pages.items():
            if hasattr(page, 'on_units_changed'):
                try:
                    page.on_units_changed()
                except Exception as e:
                    logger.error(f"通知页面 {page_name} 单位改变失败: {e}")

    def run(self):
        """运行应用程序"""
        # 初始状态
        self.update_status()

        # 运行主循环
        try:
            self.root.mainloop()
        except Exception as e:
            logger.error(f"主循环错误: {e}")
            messagebox.showerror("运行错误", f"应用程序运行失败:\n{str(e)}")

    def _create_menu_bar(self):
        """创建菜单栏"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="导出项目...",
                              command=self.export_project,
                              accelerator="Ctrl+E")
        file_menu.add_command(label="导入项目...",
                              command=self.import_project,
                              accelerator="Ctrl+I")
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.on_closing)
        menubar.add_cascade(label="文件", menu=file_menu)

        # 绑定快捷键
        self.root.bind_all("<Control-e>", lambda e: self.export_project())
        self.root.bind_all("<Control-E>", lambda e: self.export_project())
        self.root.bind_all("<Control-i>", lambda e: self.import_project())
        self.root.bind_all("<Control-I>", lambda e: self.import_project())

    def export_project(self):
        """导出项目到文件"""
        if not self.cad_data_manager.is_loaded:
            messagebox.showerror("错误", "尚未加载管网数据，无法导出")
            return

        from tkinter import simpledialog, filedialog

        # 默认模型名
        cad_path = self.cad_data_manager.cad_file_path or ""
        cad_name = os.path.splitext(os.path.basename(cad_path))[0] if cad_path else "project"
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"{cad_name}_{date_str}"

        # 询问模型名
        model_name = simpledialog.askstring(
            "导出项目",
            "请输入管网模型名:",
            initialvalue=default_name,
            parent=self.root
        )
        if not model_name:
            return

        # 默认导出根目录
        default_export_root = os.path.join(BASE_DIR, "exports")
        os.makedirs(default_export_root, exist_ok=True)

        # 选择保存路径
        zip_path = filedialog.asksaveasfilename(
            title="保存导出文件",
            initialfile=f"{model_name}.zip",
            defaultextension=".zip",
            filetypes=[("ZIP文件", "*.zip")],
            parent=self.root
        )
        if not zip_path:
            return

        try:
            exporter = ProjectExporter(
                self.cad_data_manager,
                self.config_manager,
                self.material_manager,
                settings_page=self.settings_page,
                preview_page=self.preview_page,
                calculation_page=self.calculation_page,
            )
            exporter.export_to_zip(zip_path, model_name)
            messagebox.showinfo("导出成功",
                                f"项目已导出到:\n{zip_path}")

        except Exception as e:
            logger.error(f"导出失败: {e}", exc_info=True)
            messagebox.showerror("导出失败", f"导出过程中发生错误:\n{str(e)}")

    def import_project(self):
        """从文件导入项目"""
        from tkinter import filedialog

        # 如果已有数据，确认覆盖
        if self.cad_data_manager.is_loaded:
            if not messagebox.askyesno("确认",
                                       "当前已加载管网数据，导入将覆盖所有现有数据。\n是否继续？"):
                return

        # 选择ZIP文件
        last_dir = self.config_manager.get_global_setting(
            "last_export_import_dir",
            os.path.join(BASE_DIR, "exports")
        )
        zip_path = filedialog.askopenfilename(
            title="选择要导入的ZIP文件",
            initialdir=last_dir,
            filetypes=[("ZIP文件", "*.zip"), ("所有文件", "*.*")],
            parent=self.root
        )
        if not zip_path:
            return

        try:
            # 先重置计算和预览状态
            self.reset_calculation_and_preview()

            importer = ProjectImporter(
                self.cad_data_manager,
                self.config_manager,
                self.material_manager,
                app_instance=self,
            )
            success = importer.import_from_zip(zip_path)
            
            self.config_manager.update_global_setting(
                "last_export_import_dir",
                os.path.dirname(zip_path)
            )
            
            if not success:
                messagebox.showerror("导入失败", "导入过程中发生错误，请查看日志")
                return

            # 恢复配置到设置页面
            if hasattr(self.settings_page, "load_current_config"):
                self.settings_page.load_current_config()
            if hasattr(self.settings_page, "update_all_widgets"):
                self.settings_page.update_all_widgets()

            # 刷新所有页面
            self.refresh_all_pages()
            self.notify_units_changed()
            self.update_status()

            # 重建预览页面楼层标签
            if hasattr(self.preview_page, "refresh_data"):
                self.preview_page.refresh_data()

            messagebox.showinfo("导入成功",
                                f"项目已从导入恢复:\n{zip_path}\n\n"
                                "当前为导入模式，CAD写回功能不可用。\n"
                                "您可以查看数据、编辑参数和重新计算。")

        except Exception as e:
            logger.error(f"导入失败: {e}", exc_info=True)
            messagebox.showerror("导入失败", f"导入过程中发生错误:\n{str(e)}")


if __name__ == "__main__":
    try:
        app = MainApplication()
        app.run()
    except Exception as e:
        logger.error(f"应用程序启动错误: {e}", exc_info=True)
        messagebox.showerror("启动错误", f"应用程序启动失败:\n{str(e)}")