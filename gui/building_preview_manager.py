import tkinter as tk
from tkinter import ttk
import logging

logger = logging.getLogger(__name__)


class BuildingPreviewManager:
    """单栋建筑的预览组件管理器。

    封装该建筑的楼层标签组、画布组和楼层视图状态。
    非区域模式下 PreviewPage 持有一个 building_id=None 的 singleton manager。
    区域模式下每栋建筑对应一个 manager，由外层 building_notebook 切换激活。

    PreviewPage 通过 property 代理将 floor_notebook / floor_canvases /
    floor_view_state / current_floor_name / current_view_mode

    _current_canvas 和 canvas 保留为 PreviewPage 的直接属性，
    在 building/floor 切换时与 manager 同步。
    """

    def __init__(self, preview_page, building_id=None):
        self.preview_page = preview_page
        self.building_id = building_id

        self.floor_notebook = None
        self.floor_canvases = {}
        self._current_canvas = None
        self.current_floor_name = None
        self.current_view_mode = "floor"
        self.floor_view_state = {}

    def build(self, parent_widget):
        self.floor_notebook = ttk.Notebook(parent_widget)
        self.floor_notebook.pack(fill="both", expand=True)

    def save_current_state(self):
        if self._current_canvas and self.current_floor_name:
            pp = self.preview_page
            self.floor_view_state[self.current_floor_name] = (
                pp.scale, pp.translate_x, pp.translate_y
            )
