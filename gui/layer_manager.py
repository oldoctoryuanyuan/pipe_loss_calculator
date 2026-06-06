# gui/layer_manager.py
import tkinter as tk
from tkinter import ttk

class LayerManager:
    """图层管理器组件"""
    def __init__(self, parent, config_manager, on_change_callback=None, config_key="pipe_layers"):
        self.frame = ttk.LabelFrame(parent, text="图层设置")
        self.config_manager = config_manager
        self.on_change_callback = on_change_callback
        self.config_key = config_key   # 用于区分不同图层的存储键
        self.history_layers = []
        self.create_widgets()
        self.load_history_layers()
    
    def create_widgets(self):
        """创建图层管理界面"""
        # 第一行：输入行
        input_frame = ttk.Frame(self.frame)
        input_frame.pack(fill="x", padx=5, pady=(5, 0))
        
        ttk.Label(input_frame, text="横管图层(多个用逗号隔开):").pack(side="left", padx=(0, 5))
        
        self.layer_entry_var = tk.StringVar()
        self.layer_entry = ttk.Entry(input_frame, textvariable=self.layer_entry_var, width=50)
        self.layer_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        # 绑定事件实现自动保存
        self.layer_entry.bind("<FocusOut>", self.on_entry_focus_out)
        self.layer_entry.bind("<Return>", self.on_entry_return)
        
        # 第二行：横管历史图层显示
        self.history_frame = ttk.Frame(self.frame)
        self.history_frame.pack(fill="x", padx=5, pady=(0, 5))
        
        ttk.Label(self.history_frame, text="横管历史图层:").pack(side="left", anchor="nw", padx=(0, 5))
        
        # 用于显示横管历史图层的容器
        self.history_container = ttk.Frame(self.history_frame)
        self.history_container.pack(side="left", fill="x", expand=True)
    
    def load_history_layers(self):
        """加载历史图层（根据config_key存储）"""
        # 使用全局设置存储不同组的历史图层，键名如 "history_layers_pipe_layers"
        history_key = f"history_layers_{self.config_key}"
        self.history_layers = self.config_manager.get_global_setting(history_key, [])
        self.update_history_display()
    
    def on_entry_return(self, event=None):
        """回车键处理"""
        self.process_layer_entry()
    
    def on_entry_focus_out(self, event=None):
        """失去焦点处理"""
        self.process_layer_entry()
    
    def process_layer_entry(self):
        """处理图层输入"""
        entry_text = self.layer_entry_var.get().strip()
        if entry_text:
            # 按逗号分割，去除空格
            new_layers = [layer.strip() for layer in entry_text.split(",") if layer.strip()]
            
            # 添加新图层到历史（根据config_key独立存储）
            history_key = f"history_layers_{self.config_key}"
            for layer in new_layers:
                if layer and layer not in self.history_layers:
                    self.history_layers.append(layer)
                    current_history = self.config_manager.get_global_setting(history_key, [])
                    if layer not in current_history:
                        current_history.append(layer)
                        self.config_manager.update_global_setting(history_key, current_history)
            
            # 更新历史显示
            self.update_history_display()
            
            # 重要：这里不再清空输入框！！！
            # 触发回调，更新当前方案的图层列表（使用当前输入框的内容）
            if self.on_change_callback:
                current_layers = self.get_current_layers()
                self.on_change_callback(current_layers)
    
    def update_history_display(self):
        """更新历史图层显示"""
        # 清除现有显示
        for widget in self.history_container.winfo_children():
            widget.destroy()
        
        # 创建标签和删除按钮
        for layer in self.history_layers:
            layer_frame = ttk.Frame(self.history_container)
            layer_frame.pack(side="left", padx=2, pady=2)
            
            # 图层标签
            layer_label = ttk.Label(layer_frame, text=layer, padding=3,
                                   relief="solid", borderwidth=1, cursor="hand2")
            layer_label.pack(side="left", padx=(0, 2))
            layer_label.bind("<Button-1>", lambda e, l=layer: self.on_layer_click(l))
            
            # 删除按钮（叉号）
            close_btn = ttk.Label(layer_frame, text="×", foreground="red", cursor="hand2")
            close_btn.pack(side="left")
            close_btn.bind("<Button-1>", lambda e, l=layer: self.delete_history_layer(l))
    
    def on_layer_click(self, layer):
        """点击图层标签时处理"""
        current_text = self.layer_entry_var.get().strip()
        if current_text:
            # 检查是否已经包含该图层
            current_layers = [l.strip() for l in current_text.split(",") if l.strip()]
            if layer not in current_layers:
                if current_text.endswith(","):
                    self.layer_entry_var.set(current_text + layer)
                else:
                    self.layer_entry_var.set(current_text + ", " + layer)
        else:
            self.layer_entry_var.set(layer)
        
        # 焦点回到输入框
        self.layer_entry.focus_set()
    
    def delete_history_layer(self, layer):
        """从历史中删除图层"""
        if layer in self.history_layers:
            self.history_layers.remove(layer)
            history_key = f"history_layers_{self.config_key}"
            current_history = self.config_manager.get_global_setting(history_key, [])
            if layer in current_history:
                current_history.remove(layer)
                self.config_manager.update_global_setting(history_key, current_history)
            self.update_history_display()
    
    def set_entry_text(self, text):
        """设置输入框文本"""
        self.layer_entry_var.set(text)
    
    def get_entry_text(self):
        """获取输入框文本"""
        return self.layer_entry_var.get().strip()
    
    def get_current_layers(self):
        """获取当前输入框中的图层列表"""
        entry_text = self.get_entry_text()
        if entry_text:
            return [layer.strip() for layer in entry_text.split(",") if layer.strip()]
        return []
    
    def get_all_history_layers(self):
        """获取所有历史图层"""
        return self.history_layers.copy()
    
    def pack(self, **kwargs):
        """包装frame的pack方法"""
        self.frame.pack(**kwargs)
    
    def grid(self, **kwargs):
        """包装frame的grid方法"""
        self.frame.grid(**kwargs)
        
class MultiLayerManager(ttk.LabelFrame):
    """多图层管理器：同时管理横管、立管、立管标注图层"""
    def __init__(self, parent, config_manager, callbacks):
        super().__init__(parent, text="图层设置")
        self.config_manager = config_manager
        self.callbacks = callbacks
        self.widgets = {}
        self.create_widgets()
        self.load_history()

    def create_widgets(self):
        types = [
            ('pipe', '横管图层'),
            ('riser', '立管图层'),
            ('riser_note', '立管标注图层')
        ]
        for key, label_text in types:
            # 输入行
            input_frame = ttk.Frame(self)
            input_frame.pack(fill='x', padx=5, pady=(5 if key=='pipe' else 2, 0))
            ttk.Label(input_frame, text=f"{label_text}(多个用逗号隔开):").pack(side='left', padx=(0,5))
            entry_var = tk.StringVar()
            entry = ttk.Entry(input_frame, textvariable=entry_var, width=40)
            entry.pack(side='left', fill='x', expand=True, padx=(0,5))
            # 历史行
            hist_frame = ttk.Frame(self)
            hist_frame.pack(fill='x', padx=5, pady=(0, 2))
            ttk.Label(hist_frame, text=f"历史图层:").pack(side='left', padx=(0,5))
            hist_container = ttk.Frame(hist_frame)
            hist_container.pack(side='left', fill='x', expand=True)
            
            self.widgets[key] = {
                'entry_var': entry_var,
                'entry': entry,
                'hist_container': hist_container,
                'history': []
            }
            entry.bind('<FocusOut>', lambda e, k=key: self.process_entry(k))
            entry.bind('<Return>', lambda e, k=key: self.process_entry(k))

    def load_history(self):
        for key in self.widgets:
            history_key = f"history_layers_{key}"
            self.widgets[key]['history'] = self.config_manager.get_global_setting(history_key, [])
            self.update_history_display(key)

    def process_entry(self, key):
        entry_var = self.widgets[key]['entry_var']
        entry_text = entry_var.get().strip()
        if not entry_text:
            return
        new_layers = [l.strip() for l in entry_text.split(',') if l.strip()]
        if not new_layers:
            return
        history_key = f"history_layers_{key}"
        current_history = self.widgets[key]['history']
        for layer in new_layers:
            if layer and layer not in current_history:
                current_history.append(layer)
                full_history = self.config_manager.get_global_setting(history_key, [])
                if layer not in full_history:
                    full_history.append(layer)
                    self.config_manager.update_global_setting(history_key, full_history)
        self.widgets[key]['history'] = current_history
        self.update_history_display(key)
        if self.callbacks and key in self.callbacks:
            self.callbacks[key](new_layers)

    def update_history_display(self, key):
        hist_container = self.widgets[key]['hist_container']
        for widget in hist_container.winfo_children():
            widget.destroy()
        for layer in self.widgets[key]['history']:
            layer_frame = ttk.Frame(hist_container)
            layer_frame.pack(side='left', padx=2, pady=2)
            label = ttk.Label(layer_frame, text=layer, padding=3,
                             relief='solid', borderwidth=1, cursor='hand2')
            label.pack(side='left', padx=(0,2))
            label.bind('<Button-1>', lambda e, l=layer, k=key: self.on_layer_click(l, k))
            close_btn = ttk.Label(layer_frame, text='×', foreground='red', cursor='hand2')
            close_btn.pack(side='left')
            close_btn.bind('<Button-1>', lambda e, l=layer, k=key: self.delete_history_layer(l, k))

    def on_layer_click(self, layer, key):
        entry_var = self.widgets[key]['entry_var']
        current = entry_var.get().strip()
        if current:
            parts = [p.strip() for p in current.split(',') if p.strip()]
            if layer not in parts:
                if current.endswith(','):
                    entry_var.set(current + layer)
                else:
                    entry_var.set(current + ', ' + layer)
        else:
            entry_var.set(layer)
        self.widgets[key]['entry'].focus_set()

    def delete_history_layer(self, layer, key):
        history_key = f"history_layers_{key}"
        full_history = self.config_manager.get_global_setting(history_key, [])
        if layer in full_history:
            full_history.remove(layer)
            self.config_manager.update_global_setting(history_key, full_history)
        self.widgets[key]['history'] = full_history
        self.update_history_display(key)

    def set_entry_text(self, key, text):
        self.widgets[key]['entry_var'].set(text)

    def get_current_layers(self, key):
        text = self.widgets[key]['entry_var'].get().strip()
        if text:
            return [l.strip() for l in text.split(',') if l.strip()]
        return []