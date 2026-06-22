"""
管道页面模块
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os

import logging

logger = logging.getLogger(__name__)

class PipePage(ttk.Frame):
    """管道页面"""
    
    def __init__(self, parent, config_manager, material_manager, cad_data_manager, status_callback=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.material_manager = material_manager
        self.cad_data_manager = cad_data_manager
        self.status_callback = status_callback
        
        self.pipe_data = []
        self.create_widgets()
        self.setup_context_menu()
    
    def create_widgets(self):
        """创建界面控件"""
        
        # 管道数据表格
        self.create_pipe_table()
    
    def create_pipe_table(self):
        """创建管道数据表格"""
        columns = ("管段ID", "起点", "终点", "管径", "内径(mm)", "管长(m)", "状态", "类型", "管材")
        
        # 创建Treeview
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=25)
        
        # 设置列标题和宽度
        col_widths = {
            "管段ID": 80,
            "起点": 80,
            "终点": 80,
            "管径": 80,
            "内径(mm)": 80,
            "管长(m)": 80,
            "状态": 60,
            "类型": 60,
            "管材": 100
        }
        
        for col in columns:
            self.tree.heading(col, text=col)
            width = col_widths.get(col, 100)
            self.tree.column(col, width=width, anchor="center")
        
        # 细滚动条
        scrollbar = tk.Scrollbar(
            self,
            orient="vertical",
            command=self.tree.yview,
            width=10
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        # 布局
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5)
        # 配置无效行样式
        self.tree.tag_configure('inactive', foreground='gray')
    
    def setup_context_menu(self):
        """设置右键菜单"""
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(
            label="导出为CSV",
            command=self.export_to_csv
        )
        self.context_menu.add_command(
            label="反写管道ID到CAD",
            command=self.write_back_to_cad
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="跳转至整体预览",
            command=self.jump_to_pipe_global
        )
        self.context_menu.add_command(
            label="跳转至楼层预览",
            command=self.jump_to_pipe_floor
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="刷新",
            command=self.refresh_data
        )
        
        # 绑定右键事件
        self.tree.bind("<Button-3>", self.show_context_menu)
    def refresh_data(self):
        """刷新管道数据"""
        if not self.cad_data_manager.is_loaded:
            if self.status_callback:
                self.status_callback("请先在设置页面读取CAD数据", is_error=True)
            return
        
        try:
            self.pipe_data = self.cad_data_manager.pipes
            self.update_table()
            
            if len(self.pipe_data) == 0:
                if self.status_callback:
                    self.status_callback("警告：未识别到任何管道，请检查图层和颜色设置", is_error=True)
                
        except Exception as e:
            if self.status_callback:
                self.status_callback(f"刷新失败: {str(e)}", is_error=True)
    
    def update_table(self):
        """更新表格数据"""
        # 清空现有数据
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # 添加新数据
        for pipe in self.pipe_data:
            values = (
                pipe.pipe_id,
                pipe.start_node_id,
                pipe.end_node_id,
                pipe.nominal_diameter,
                f"{pipe.inner_diameter:.1f}",
                f"{pipe.length:.2f}",
                pipe.status,
                pipe.pipe_type,
                pipe.material
            )
            item = self.tree.insert("", tk.END, values=values)
            if not pipe.is_active:
                self.tree.item(item, tags=('inactive',))
    
    def export_to_csv(self):
        """导出为CSV文件"""
        if not self.pipe_data:
            messagebox.showwarning("无数据", "没有可导出的管道数据")
            return
        
        try:
            # 获取保存路径
            default_dir = os.path.dirname(self.cad_data_manager.cad_file_path) \
                if self.cad_data_manager.cad_file_path else os.getcwd()
            
            file_path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV文件", "*.csv")],
                initialdir=default_dir,
                initialfile="管道数据.csv"
            )
            
            if file_path:
                import pandas as pd
                df = self.cad_data_manager.export_to_dataframe("pipes")
                df.to_csv(file_path, index=False, encoding='utf-8-sig')
                messagebox.showinfo("导出成功", f"已导出到:\n{file_path}")
                
        except Exception as e:
            messagebox.showerror("导出失败", f"导出失败:\n{str(e)}")
    
    def write_back_to_cad(self):
        """将管道ID和管径反写到CAD"""
        if not self.pipe_data:
            logger.warning("没有可反写的管道数据")
            return
        
        try:
            success, fail, message, _ = self.cad_data_manager.write_back_to_cad("pipes", self.pipe_data)
            
            # ✅ 简单地通过日志和状态栏显示
            logger.info(f"管道反写结果: {message}")
            
            # 尝试获取主程序并显示消息
            try:
                root = self.winfo_toplevel()
                if hasattr(root, 'show_temp_message'):
                    root.show_temp_message(message, 2000)
            except:
                pass
                
        except Exception as e:
            error_msg = f"反写异常: {str(e)}"
            logger.error(error_msg)
            try:
                root = self.winfo_toplevel()
                if hasattr(root, 'show_temp_message'):
                    root.show_temp_message(error_msg, 3000)
            except:
                pass


    def show_context_menu(self, event):
        """显示右键菜单"""
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _switch_to_preview(self):
        root = self.winfo_toplevel()
        main_app = getattr(root, 'main_app', None)
        if not main_app:
            return None
        notebook = main_app.notebook
        for tab_id in notebook.tabs():
            if notebook.tab(tab_id, "text") == "管网预览":
                notebook.select(tab_id)
                break
        return main_app.pages.get("管网预览")

    def jump_to_pipe_global(self):
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        if not values:
            return
        preview = self._switch_to_preview()
        if preview:
            preview.jump_to_pipe(values[0], to_global=True)

    def jump_to_pipe_floor(self):
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        if not values:
            return
        preview = self._switch_to_preview()
        if preview:
            preview.jump_to_pipe(values[0], to_global=False)