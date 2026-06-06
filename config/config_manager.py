# config/config_manager.py
import json
import os
from typing import Dict, List, Any, Optional
import copy

class ConfigManager:
    """配置管理器，管理配置文件"""
    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        self.current_scheme = "默认方案"
        self.schemes = {}
        self.global_settings = {}
        self.live_config = {}
        self.load_config()

    def set_live_config(self, config_data: Dict[str, Any]):
        """✅ 新增：设置实时配置（内存中，不保存到文件）"""
        self.live_config = config_data
    
    def get_live_config(self) -> Dict[str, Any]:
        """✅ 新增：获取实时配置"""
        if self.live_config:
            return self.live_config
        return self.get_current_config()   
     
    def load_config(self):
        """从配置文件加载数据"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.current_scheme = config.get("last_scheme", "默认方案")
                self.schemes = config.get("schemes", {})
                self.global_settings = config.get("global_settings", {})

                # 确保有默认方案
                if "默认方案" not in self.schemes:
                    self.schemes["默认方案"] = self.create_default_scheme()

                # 确保有临时方案（不显示在列表中）
                if "临时方案" not in self.schemes:
                    self.schemes["临时方案"] = copy.deepcopy(self.create_default_scheme())

                # 启动时优先加载临时方案
                temp_scheme = self.schemes.get("临时方案")
                if temp_scheme:
                    if self.is_valid_scheme(temp_scheme):
                        self.current_scheme = "临时方案"
                    else:
                        self.current_scheme = "默认方案"
                else:
                    self.current_scheme = "默认方案"

                # 兼容旧配置：将 system_type 中的 "hydrant" 转换为 "indoor_hydrant"
                for scheme_name, scheme in self.schemes.items():
                    if scheme.get("system_type") == "hydrant":
                        scheme["system_type"] = "indoor_hydrant"

                self.save_config()
            except Exception as e:
                print(f"加载配置文件失败: {e}")
                self.create_empty_config()
        else:
            self.create_empty_config()
   
    def is_valid_scheme(self, scheme_config: Dict[str, Any]) -> bool:
        """检查方案是否有效（至少包含必要字段）"""
        required_fields = ["pipe_layers", "pipe_material"]
        for field in required_fields:
            if field not in scheme_config or not scheme_config[field]:
                return False
        return True
    
    def create_default_scheme(self) -> Dict[str, Any]:
        """创建默认方案配置"""
        return {
            "pipe_layers": ["PIPE-消防"],
            "riser_layers": ["VPIPE-消防"],             # 立管图层（用户输入）
            "riser_note_layers": ["DIM_消防"],          # 立管标注图层
            #"pipe_entity_type": "LWPOLYLINE",
            "drawing_unit": "毫米",
            "flow_unit": "L/s",
            "pressure_unit": "m",
            "pipe_material": "镀锌钢管",
            "supply_block_name": "supply_node",
            "supply_attribute_name": "GroupID",
            "demand_block_name": "demand_node",
            "demand_attribute_name": "GroupID",
            "valve_block_name": "valve",
            "valve_attribute_name": "Status",
            "tolerance": 10.0,
            "sprinkler_K": 80,                # 喷头流量系数
            "hydrant_Ad": 0.00172,            # 水带比阻
            "hydrant_Ld": 25,                 # 水带长度 (m)
            "hydrant_B": 1.577,               # 水枪特性系数
            "hydrant_Hak": 2.0,               # 栓口水损 (m)  
            "align_block_name": "Floorbase",      
            "align_attribute_name": "Elevation",
            "hydrant_block_name": "hydrant",  # 消火栓图块名
            "max_velocity": 5.0,              # 最高流速 (m/s)
            "min_velocity": 1.0,              # 最低流速 (m/s)
            "system_type": "outdoor_hydrant",   # 管网类型："室外消火栓" "室内消火栓" 或 "喷淋",可选值 "outdoor_hydrant" / "indoor_hydrant" / "sprinkler"       
        }
    
    def create_empty_config(self):
        """创建空配置文件"""
        self.current_scheme = "默认方案"
        self.global_settings = {
            "history_layers": []  # 全局历史图层
        }
        self.schemes = {
            "默认方案": self.create_default_scheme(),
            "临时方案": self.create_default_scheme()
        }
        self.save_config()
    
    def save_config(self):
        """保存配置文件"""
        try:
            config = {
                "last_scheme": self.current_scheme,
                "global_settings": self.global_settings,
                "schemes": self.schemes
            }
            
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置失败: {e}")
    
    def get_scheme_config(self, scheme_name: str) -> Dict[str, Any]:
        """获取指定方案的配置"""
        if scheme_name in self.schemes:
            return copy.deepcopy(self.schemes[scheme_name])
        return copy.deepcopy(self.create_default_scheme())
    
    def get_current_config(self) -> Dict[str, Any]:
        """获取当前方案的配置"""
        return self.get_scheme_config(self.current_scheme)
    
    def get_visible_schemes(self) -> List[str]:
        """获取可见的方案列表（排除临时方案）"""
        return [name for name in self.schemes.keys() if name != "临时方案"]
    
    def add_scheme(self, scheme_name: str, config_data: Dict[str, Any]):
        """添加新方案"""
        if scheme_name == "默认方案":
            raise ValueError("不能使用'默认方案'作为方案名称")
        
        if scheme_name == "临时方案":
            raise ValueError("不能使用'临时方案'作为方案名称")
        
        if scheme_name in self.schemes:
            raise ValueError(f"方案 '{scheme_name}' 已存在")
        
        self.schemes[scheme_name] = config_data
        self.current_scheme = scheme_name
        self.save_config()
    
    def delete_scheme(self, scheme_name: str):
        """删除方案"""
        if scheme_name in self.schemes and scheme_name not in ["默认方案", "临时方案"]:
            del self.schemes[scheme_name]
            if self.current_scheme == scheme_name:
                self.current_scheme = "默认方案"
            self.save_config()
    
    def set_current_scheme(self, scheme_name: str):
        """设置当前方案"""
        if scheme_name in self.schemes and scheme_name != "临时方案":
            self.current_scheme = scheme_name
            self.save_config()
    
    def update_current_config(self, key: str, value: Any):
        """更新当前方案的配置"""
        if self.current_scheme not in self.schemes:
            self.schemes[self.current_scheme] = self.create_default_scheme()
        
        self.schemes[self.current_scheme][key] = value
        self.save_config()
    
    def save_temp_scheme(self, config_data: Dict[str, Any]):
        """保存临时方案"""
        self.schemes["临时方案"] = copy.deepcopy(config_data)
        self.save_config()
    
    def update_global_setting(self, key: str, value: Any):
        """更新全局设置"""
        self.global_settings[key] = value
        self.save_config()
    
    def get_global_setting(self, key: str, default: Any = None) -> Any:
        """获取全局设置"""
        return self.global_settings.get(key, default)
    
    def get_history_layers(self) -> List[str]:
        """获取历史图层列表"""
        return self.global_settings.get("history_layers", [])
    
    def add_history_layer(self, layer: str):
        """添加图层到历史"""
        history_layers = self.get_history_layers()
        if layer and layer not in history_layers:
            history_layers.append(layer)
            self.update_global_setting("history_layers", history_layers)
    
    def remove_history_layer(self, layer: str):
        """从历史中移除图层"""
        history_layers = self.get_history_layers()
        if layer in history_layers:
            history_layers.remove(layer)
            self.update_global_setting("history_layers", history_layers)