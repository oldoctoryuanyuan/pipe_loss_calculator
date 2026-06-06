# gui/color_diameter_table_config.py
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Tuple, Callable

class ColorDiameterTableConfig:
    """基于管材管理器的颜色管径对照表组件"""
    def __init__(self, parent, config_manager, material_manager, on_change_callback=None):
        self.frame = ttk.LabelFrame(parent, text="颜色-管径对照表")
        self.config_manager = config_manager
        self.material_manager = material_manager
        self.on_change_callback = on_change_callback
        self.current_material = None
        self.data = {}  # 格式: {color: {"nominal": "DNXX", "inner": 0.0}}
        
        self.create_widgets()
    
    def create_widgets(self):
        """创建颜色管径对照表界面"""
        # 标题栏和恢复默认按钮
        title_frame = ttk.Frame(self.frame)
        title_frame.pack(fill="x", padx=5, pady=(5, 0))
        
        ttk.Label(title_frame, text="颜色-公称管径-内径对照表").pack(side="left")
        
        # 恢复默认按钮
        self.restore_btn = ttk.Button(
            title_frame, 
            text="恢复默认",
            command=self.restore_default,
            width=10
        )
        self.restore_btn.pack(side="right", padx=(0, 5))
        
        # 创建Treeview
        columns = ("颜色", "公称管径", "内径(mm)", "操作")
        self.tree = ttk.Treeview(
            self.frame, 
            columns=columns, 
            show="headings",
            height=20,
            selectmode="browse"
        )
        
        # 设置列标题和宽度
        self.tree.heading("颜色", text="颜色代码")
        self.tree.heading("公称管径", text="公称管径")
        self.tree.heading("内径(mm)", text="内径(mm)")
        self.tree.heading("操作", text="操作")
        
        self.tree.column("颜色", width=100, anchor="center")
        self.tree.column("公称管径", width=120, anchor="center")
        self.tree.column("内径(mm)", width=120, anchor="center")
        self.tree.column("操作", width=60, anchor="center")
        
        # 设置网格线
        style = ttk.Style()
        style.configure("Treeview", rowheight=25)
        style.configure("Treeview.Heading", font=('Arial', 9, 'bold'))
        
        # 添加滚动条
        tree_scrollbar = tk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scrollbar.set)
        
        # 放置Treeview和滚动条
        self.tree.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)
        tree_scrollbar.pack(side="right", fill="y", padx=(0, 5), pady=5)
        
        # 绑定编辑事件
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<FocusOut>", self.on_tree_focus_out)
        self.tree.bind("<KeyRelease>", self.on_tree_key_release)
    
    def set_material(self, material: str):
        """设置当前管材"""
        self.current_material = material
        
        # 从管材管理器加载颜色-管径对照表
        self.load_data_from_material_manager()
        
        # 刷新显示
        self.refresh_table()
    
    def load_data_from_material_manager(self):
        """从管材管理器加载数据"""
        if not self.current_material:
            return
        
        # 从管材管理器获取颜色-管径对照表
        table_data = self.material_manager.get_color_diameter_table(self.current_material)
        
        if table_data:
            self.data = table_data.copy()
        else:
            # 如果没有数据，创建一个空的
            self.data = {}
    
    def refresh_table(self):
        """刷新表格显示"""
        # 清空现有行
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        if not self.data:
            # 添加空行用于输入新数据
            self.tree.insert("", "end", values=("", "", "", "✓"), tags=("new_row",))
            self.tree.tag_configure("new_row", background="#f0f0f0")
            return
        
        # 按公称管径排序
        sorted_items = self.sort_by_diameter(self.data)
        
        # 添加数据行
        for color, info in sorted_items:
            nominal_diameter = info["nominal"]
            inner_diameter = info["inner"]
            
            self.tree.insert("", "end", values=(
                color,
                nominal_diameter,
                f"{inner_diameter:.1f}" if inner_diameter > 0 else "",
                "×"
            ))
        
        # 添加空行用于输入新数据
        self.tree.insert("", "end", values=("", "", "", "✓"), tags=("new_row",))
        self.tree.tag_configure("new_row", background="#f0f0f0")
    
    def sort_by_diameter(self, table_data: Dict) -> List[Tuple[str, Dict]]:
        """按公称管径排序"""
        def diameter_key(item):
            # 提取数字部分用于排序
            diameter_str = item[1]["nominal"]  # 如 "DN100"
            try:
                return int(diameter_str[2:])  # 去掉"DN"，转数字
            except:
                return 0
        
        return sorted(table_data.items(), key=diameter_key)
    
    def on_double_click(self, event):
        """双击编辑"""
        item = self.tree.selection()
        if not item:
            return
        
        # 获取点击的列
        column = self.tree.identify_column(event.x)
        item_id = item[0]
        values = list(self.tree.item(item_id, "values"))
        
        if column == "#4":  # 操作列
            if values[3] == "×":  # 删除
                self.delete_row(item_id)
            elif values[3] == "✓":  # 添加新行
                self.add_row(item_id)
        elif column in ["#1", "#2", "#3"]:  # 颜色、公称管径、内径列
            self.edit_cell(item_id, int(column[1:]) - 1)
    
    def edit_cell(self, item_id, column_index):
        """编辑单元格"""
        # 检查是否是空行
        values = self.tree.item(item_id, "values")
        if len(values) < 4:
            return
        
        # 获取当前位置
        bbox = self.tree.bbox(item_id, column_index)
        if not bbox:
            return
        
        # 创建编辑框
        x, y, width, height = bbox
        current_value = values[column_index]
        
        edit_var = tk.StringVar(value=current_value)
        edit_entry = ttk.Entry(self.tree, textvariable=edit_var, width=width//8)
        edit_entry.place(x=x, y=y, width=width, height=height)
        edit_entry.focus_set()
        edit_entry.select_range(0, tk.END)
        
        def save_edit(event=None):
            new_value = edit_var.get().strip()
            edit_entry.destroy()
            
            if new_value != current_value:
                # 获取所有值
                current_values = list(self.tree.item(item_id, "values"))
                current_values[column_index] = new_value
                
                # 如果是内径列，需要验证是否为数字
                if column_index == 2:
                    try:
                        float(new_value)
                    except ValueError:
                        # 如果不是数字，恢复原值
                        current_values[column_index] = current_value
                        self.tree.item(item_id, values=current_values)
                        return
                
                # 更新显示
                self.tree.item(item_id, values=current_values)
                
                # 如果是已有行，更新数据
                if current_values[3] == "×":
                    color = current_values[0]
                    if color and self.current_material:
                        # 更新内存中的数据
                        self.data[color] = {
                            "nominal": current_values[1],
                            "inner": float(current_values[2]) if current_values[2] else 0.0
                        }
                        
                        # 立即保存到materials.json（光标离开时保存）
                        self.save_data_to_material_manager()
                        
                        # 重新排序并刷新
                        self.reorder_and_refresh()
                        
                        # 触发回调（如果需要）
                        if self.on_change_callback:
                            self.on_change_callback(self.data)
        
        def cancel_edit(event=None):
            edit_entry.destroy()
            # 失去焦点时也保存（这是关键修改：光标离开就保存）
            save_edit()
        
        edit_entry.bind("<Return>", save_edit)
        edit_entry.bind("<FocusOut>", cancel_edit)  # 关键：光标离开时保存
        edit_entry.bind("<Escape>", cancel_edit)
    
    def add_row(self, item_id):
        """添加新行"""
        values = self.tree.item(item_id, "values")
        color = values[0].strip()
        nominal = values[1].strip()
        inner = values[2].strip()
        
        if not color or not nominal:
            return  # 颜色和公称管径不能为空
        
        # 验证内径是否为数字
        try:
            inner_value = float(inner) if inner else 0.0
        except ValueError:
            return
        
        if self.current_material:
            # 添加到数据
            self.data[color] = {
                "nominal": nominal,
                "inner": inner_value
            }
            
            # 立即保存到materials.json
            self.save_data_to_material_manager()
            
            # 重新排序并刷新
            self.reorder_and_refresh()
            
            # 触发回调
            if self.on_change_callback:
                self.on_change_callback(self.data)
    
    def delete_row(self, item_id):
        """删除行"""
        values = self.tree.item(item_id, "values")
        color = values[0]
        
        if color and color in self.data:
            del self.data[color]
            
            # 立即保存到materials.json
            self.save_data_to_material_manager()
            
            # 刷新表格
            self.refresh_table()
            
            # 触发回调
            if self.on_change_callback:
                self.on_change_callback(self.data)
    
    def on_tree_focus_out(self, event):
        """表格失去焦点时自动保存"""
        self.save_data_to_material_manager()
    
    def on_tree_key_release(self, event):
        """键盘释放时自动保存（针对直接编辑）"""
        if event.keysym in ["Return", "Tab", "Up", "Down"]:
            self.save_data_to_material_manager()
    
    def reorder_and_refresh(self):
        """重新排序并刷新表格"""
        self.refresh_table()
    
    def restore_default(self):
        """恢复默认设置"""
        if not self.current_material:
            return
        
        # 从管材管理器恢复默认
        self.material_manager.restore_to_default(self.current_material)
        
        # 重新加载数据
        self.load_data_from_material_manager()
        
        # 刷新表格
        self.refresh_table()
        
        # 触发回调
        if self.on_change_callback:
            self.on_change_callback(self.data)
    
    def save_data_to_material_manager(self):
        """保存数据到管材管理器（即保存到materials.json）"""
        if not self.current_material:
            return
        
        # 通过管材管理器保存数据
        self.material_manager.update_color_diameter_table(self.current_material, self.data)
    
    def pack(self, **kwargs):
        """包装frame的pack方法"""
        self.frame.pack(**kwargs)
    
    def grid(self, **kwargs):
        """包装frame的grid方法"""
        self.frame.grid(**kwargs)