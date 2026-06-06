# pipe_loss_calculator/config/material_manager.py
import json
import os
from typing import Dict, List, Optional

class MaterialManager:
    """管材管理器，管理所有管材数据（包括颜色-管径对照表）"""
    def __init__(self, materials_file: str):
        self.materials_file = materials_file
        self.default_materials_file = os.path.join(os.path.dirname(materials_file), "default_materials.json")
        self.materials: Dict[str, Dict] = {}
        self.default_materials: Dict[str, Dict] = {}
        self.load_default_materials()
        self.load_materials()
        
    def load_default_materials(self):
        """加载默认管材数据（只读）"""
        if os.path.exists(self.default_materials_file):
            try:
                with open(self.default_materials_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.default_materials = data.get("materials", {})
            except Exception as e:
                print(f"加载默认管材配置文件失败: {e}")
                self.default_materials = {}
        else:
            self.default_materials = {}
            print(f"默认管材配置文件不存在: {self.default_materials_file}")
        
    def load_materials(self):
        """从配置文件加载用户管材数据"""
        if os.path.exists(self.materials_file):
            try:
                with open(self.materials_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.materials = data.get("materials", {})
            except Exception as e:
                print(f"加载管材配置文件失败: {e}")
                self.materials = {}
        else:
            # 如果用户文件不存在，从默认文件复制
            self.materials = self.default_materials.copy()
            self.save_materials()
        
    def save_materials(self):
        """保存管材配置到文件"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.materials_file), exist_ok=True)
            data = {"materials": self.materials}
            with open(self.materials_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存管材配置失败: {e}")
        
    def get_materials(self) -> List[str]:
        """获取所有管材名称列表"""
        return list(self.materials.keys())
        
    def get_roughness(self, material: str) -> float:
        """获取管材粗糙系数"""
        if material in self.materials:
            return self.materials[material].get("roughness", 130)
        return 130
        
    def get_color_diameter_table(self, material: str) -> Dict:
        """获取管材的颜色-管径对照表"""
        if material in self.materials:
            return self.materials[material].get("color_diameter_table", {})
        return {}
        
    def get_default_color_diameter_table(self, material: str) -> Dict:
        """获取默认的颜色-管径对照表"""
        if material in self.default_materials:
            return self.default_materials[material].get("color_diameter_table", {})
        return {}
    
    def is_default_material(self, material: str) -> bool:
        """判断是否是默认管材"""
        return material in self.default_materials
        
    def restore_to_default(self, material: str):
        """将指定管材恢复到默认设置"""
        if material in self.default_materials:
            # 从默认数据复制
            default_data = self.default_materials[material]
            self.materials[material] = default_data.copy()
            self.save_materials()
    
    def add_material(self, name: str, roughness: float, color_diameter_table: Dict = None):
        """添加新管材"""
        if color_diameter_table is None:
            # 如果没有提供颜色-管径表，创建一个空的
            color_diameter_table = {}
        
        self.materials[name] = {
            "roughness": roughness,
            "color_diameter_table": color_diameter_table
        }
        self.save_materials()
        
    def delete_material(self, name: str):
        """删除管材"""
        if name in self.materials:
            del self.materials[name]
            self.save_materials()
    
    def update_material(self, name: str, roughness: Optional[float] = None):
        """更新管材粗糙系数"""
        if name in self.materials:
            if roughness is not None:
                self.materials[name]["roughness"] = roughness
            self.save_materials()
    
    def update_color_diameter_table(self, material: str, color_diameter_table: Dict):
        """更新指定管材的颜色-管径对照表"""
        if material in self.materials:
            self.materials[material]["color_diameter_table"] = color_diameter_table
            self.save_materials()
            
    def get_sorted_diameters(self, material: str, system_type: str = "hydrant") -> List[str]:
        color_table = self.get_color_diameter_table(material)
        diameters = []
        for color, info in color_table.items():
            dn_str = info.get("nominal", "")
            if dn_str and dn_str.startswith("DN"):
                try:
                    num = int(dn_str[2:])
                    if system_type == "hydrant":
                        allowed = {65, 100, 125, 150, 200, 250, 300, 350, 400}
                        if num in allowed:
                            diameters.append((num, dn_str))
                    elif system_type == "sprinkler":
                        if num not in {15, 20}:
                            diameters.append((num, dn_str))
                    else:
                        diameters.append((num, dn_str))
                except:
                    pass
        diameters.sort(key=lambda x: x[0])
        return [dn for _, dn in diameters]

    def get_next_diameter(self, current_dn: str, direction: str, material: str, system_type: str) -> str:
        """放大（'up'）或缩小（'down'）一级管径，若无更高级别则返回原值"""
        diameters = self.get_sorted_diameters(material, system_type)
        try:
            idx = diameters.index(current_dn)
            if direction == "up" and idx < len(diameters) - 1:
                return diameters[idx + 1]
            elif direction == "down" and idx > 0:
                return diameters[idx - 1]
        except ValueError:
            pass
        return current_dn

    def get_diameter_info(self, material: str, dn: str) -> Dict:
        """根据公称管径获取对应的内径等信息（从颜色表反向查找）"""
        color_table = self.get_color_diameter_table(material)
        for color, info in color_table.items():
            if info.get("nominal") == dn:
                return info
        return {"nominal": dn, "inner": 0.0}

