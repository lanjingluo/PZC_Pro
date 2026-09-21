"""游戏窗口：把剧本数据画成游戏界面（地图 + 单位），并处理选中 / 缩放 / 平移。

- open_game_window(owner, scenario_path)：打开游戏窗口（剧本列表点卡片调用）
- main()：单独运行本文件，直接看 setupsaves 里的第一个剧本（只是开发时方便）

操作：滚轮缩放（以光标为中心）、WASD 或方向键平移、按住左键拖动平移、
单击单位选中它（同一格多个单位就点哪个选哪个），左侧栏显示选中单位的具体情况。

本文件是自给自足的：剧本读取、地图几何、地形/阵营配色、北约军标画法都在这里，
不再依赖 setup/ 那套初设工具，也没有任何跳回它们的入口；数据导进来之后，
游戏界面只跟这份数据打交道。本文件从磁盘加载，改完不用重新打包 exe。
"""
import json
import math
import os
import sys

import clr

clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from System.Drawing import (
    Bitmap,
    Color,
    ContentAlignment,
    Font,
    FontStyle,
    Graphics,
    Pen,
    Point,
    PointF,
    RectangleF,
    Size,
    SolidBrush,
    TextureBrush,
)
from System.Drawing.Drawing2D import Matrix, SmoothingMode, WrapMode
from System.Windows.Forms import (
    Application,
    BorderStyle,
    Button,
    Control,
    Cursor,
    Cursors,
    DockStyle,
    FlatStyle,
    Form,
    FormStartPosition,
    Keys,
    Label,
    ListBox,
    MessageBox,
    MessageBoxButtons,
    MessageBoxIcon,
    Padding,
    Panel,
    PictureBox,
    PictureBoxSizeMode,
    SelectionMode,
)
from System.Threading import ApartmentState, Thread, ThreadStart

# BorderStyle 的成员名 None 是 Python 关键字，只能这样取
BORDER_NONE = getattr(BorderStyle, 'None')

WINDOW_TITLE = '游戏'
WINDOW_SIZE = Size(1280, 800)
MINIMUM_SIZE = Size(900, 560)

TOP_BAR_HEIGHT = 52
SIDE_WIDTH = 300
STATUS_HEIGHT = 28

MIN_ZOOM = 0.05
MAX_ZOOM = 8.0
ZOOM_STEP = 1.25
PAN_STEP = 90.0                       # WASD 每次平移的屏幕像素

# 画法参数（和初设编辑器一致，两个窗口看起来是同一套）
GRID_PEN_WIDTH = 2.0
EDGE_PEN_WIDTH = 6.0
SYMBOL_RATIO = 1.4
LEVEL_MARKS = {
    '班': '•', '排': '••', '连': 'I', '营': 'II', '团': 'III',
    '旅': 'X', '师': 'XX', '军': 'XXX', '集团军': 'XXXX',
}

# 地形与格边配色、默认消耗（和 Hex_Editor/hexmap.py 的表一致，游戏这边自己存一份）
TERRAIN_COLORS = {
    '树林': (60, 150, 70),
    '山地': (150, 105, 60),
    '城市': (0, 0, 0),
    '河流': (70, 130, 200),           # 旧版本把河流当格子地形
}
TERRAIN_COSTS = {'树林': 2, '山地': 3, '城市': 1, '河流': 3}
EDGE_COLORS = {'河流': (70, 130, 200)}
EDGE_COSTS = {'河流': 2}
UNKNOWN_TERRAIN_COLOR = (200, 200, 200)

# 单位类型数据（软攻/硬攻/防御/突破/移动…）：Units/database/units.data
UNIT_DATA_RELATIVE_PATH = os.path.join('Units', 'database', 'units.data')
STAT_FIELDS = (
    ('soft_attack', '软攻'),
    ('hard_attack', '硬攻'),
    ('defense', '防御'),
    ('breakthrough', '突破'),
)

# 北约军标：底框形状按“敌我识别”取（没有这个字段就按友军画矩形）
FRAME_RECT = 'rect'
FRAME_DIAMOND = 'diamond'
AFFILIATION_FRAMES = {
    '友军': FRAME_RECT, '友': FRAME_RECT, 'friendly': FRAME_RECT, 'friend': FRAME_RECT,
    '敌军': FRAME_DIAMOND, '敌': FRAME_DIAMOND, 'hostile': FRAME_DIAMOND, 'enemy': FRAME_DIAMOND,
    '中立': FRAME_RECT, 'neutral': FRAME_RECT,
    '未知': FRAME_RECT, 'unknown': FRAME_RECT,
}

FACTION_COLORS = {
    '红': (198, 60, 60), '蓝': (58, 110, 200), '绿': (66, 145, 86),
    '黄': (188, 148, 40), '白': (140, 140, 140), '黑': (70, 70, 70),
}
FACTION_PALETTE = ((198, 60, 60), (58, 110, 200), (66, 145, 86),
                   (188, 148, 40), (140, 100, 190), (120, 120, 120))

GAME_BACK = Color.FromArgb(24, 26, 30)
BAR_BACK = Color.FromArgb(34, 37, 42)
PANEL_BACK = Color.FromArgb(30, 33, 38)
PAPER_COLOR = Color.FromArgb(58, 60, 64)
GRID_COLOR = Color.FromArgb(96, 102, 110)
TEXT_COLOR = Color.FromArgb(235, 235, 235)
DIM_TEXT = Color.FromArgb(165, 165, 165)
SELECT_COLOR = Color.FromArgb(255, 210, 60)
UNIT_SELECT_COLOR = Color.FromArgb(255, 210, 40)

# 独立运行（python game_window.py）时去哪里找剧本；游戏窗口本身不依赖这些路径
STANDALONE_SEARCH_PATHS = (('setup', 'setupsaves'), ('scenarios',))


def project_dir():
    """游戏文件所在目录：打包成 exe 后是 exe 所在目录，开发时是本文件所在目录。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def show_error(message, owner=None, title='游戏 - 出错'):
    if owner is not None:
        MessageBox.Show(owner, message, title, MessageBoxButtons.OK, MessageBoxIcon.Error)
    else:
        MessageBox.Show(message, title, MessageBoxButtons.OK, MessageBoxIcon.Error)


def to_color(rgb):
    return Color.FromArgb(int(rgb[0]), int(rgb[1]), int(rgb[2]))


def read_scenario(path):
    """读剧本数据（.scenario 就是一份 JSON）。返回 (数据, 失败原因)。"""
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        return None, '%s: %s' % (type(exc).__name__, exc)
    if not isinstance(data, dict) or data.get('type') != 'SCENARIO':
        return None, '不是剧本文件（type 字段应为 SCENARIO）'
    return data, None


def parse_cell_key(key):
    """'列,行' → (列, 行)，解析不出来返回 None。"""
    try:
        parts = str(key).split(',')
        return (int(parts[0]), int(parts[1]))
    except (IndexError, ValueError):
        return None


def terrain_color(name):
    return TERRAIN_COLORS.get(str(name), UNKNOWN_TERRAIN_COLOR)


def edge_color(name):
    return EDGE_COLORS.get(str(name), (90, 140, 220))


def terrain_cost(name):
    """进入该格的默认消耗（空地按 1 算）——以后做移动力时用。"""
    return TERRAIN_COSTS.get(str(name), 1)


def edge_cost(name):
    """跨过该格边的额外消耗——以后做移动力时用。"""
    return EDGE_COSTS.get(str(name), 0)


def faction_color(faction):
    """阵营 → RGB：名字里带颜色字就按字面取色，否则按名字稳定散列。"""
    text = str(faction or '')
    for key, rgb in FACTION_COLORS.items():
        if key in text:
            return rgb
    if not text:
        return FACTION_PALETTE[-1]
    total = sum(ord(ch) for ch in text)
    return FACTION_PALETTE[total % len(FACTION_PALETTE)]


_UNIT_STATS = None


def load_unit_stats():
    """读单位类型数据（Units/database/units.data）。读不到就返回空表，不影响界面打开。"""
    global _UNIT_STATS
    if _UNIT_STATS is None:
        path = os.path.join(project_dir(), UNIT_DATA_RELATIVE_PATH)
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
            _UNIT_STATS = data.get('types') or {}
        except (OSError, ValueError):
            _UNIT_STATS = {}
    return _UNIT_STATS


def unit_stats(unit_type):
    """按单位类型取数据表里的一条记录（没有就返回空 dict）。"""
    record = load_unit_stats().get(str(unit_type)) if unit_type else None
    return record if isinstance(record, dict) else {}


def affiliation_frame(unit):
    """敌我识别 → 底框形状（没有这个字段就按友军画矩形）。"""
    text = str(unit.get('affiliation') or unit.get('side') or '').strip().lower()
    if text in AFFILIATION_FRAMES:
        return AFFILIATION_FRAMES[text]
    for key, shape in AFFILIATION_FRAMES.items():
        if key in text:
            return shape
    return FRAME_RECT


def frame_points(shape, cx, cy, width, height):
    """军标底框的四个顶点。"""
    half_w, half_h = width / 2.0, height / 2.0
    if shape == FRAME_DIAMOND:
        return ((cx, cy - half_h), (cx + half_w, cy), (cx, cy + half_h), (cx - half_w, cy))
    return ((cx - half_w, cy - half_h), (cx + half_w, cy - half_h),
            (cx + half_w, cy + half_h), (cx - half_w, cy + half_h))


def ink_color(rgb):
    """在阵营色底上画符号用哪种颜色：底色亮用黑，暗用白。"""
    luminance = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    if luminance > 150:
        return Color.FromArgb(20, 20, 20)
    return Color.FromArgb(245, 245, 245)


def hex_layout(cols, width, height, margins=None, cell_size=None):
    """平顶六角格布局（奇数列错位），算法同 Hex_Editor/hexformat.py。

    剧本里存了 cell_size 就直接用，没存就按画布宽度算。
    返回 {'cell_size': 中心到顶点, 'rows': 行数, 'centers': [(列,行,x,y), ...]}。
    """
    margins = margins or {}
    margin_left = max(0, int(margins.get('l', 0)))
    margin_right = max(0, int(margins.get('r', 0)))
    margin_top = max(0, int(margins.get('t', 0)))
    margin_bottom = max(0, int(margins.get('b', 0)))
    cols = max(1, int(cols))
    width = max(1, int(width))
    height = max(1, int(height))
    grid_w = max(1, width - margin_left - margin_right)
    grid_h = max(1, height - margin_top - margin_bottom)
    if not cell_size:
        cell_size = grid_w / (1.5 * cols + 0.5)
    cell_size = float(cell_size)
    row_step = math.sqrt(3.0) * cell_size
    rows = int(math.ceil(grid_h / row_step)) + 1
    half_h = row_step * 0.5
    centers = []
    for r in range(rows):
        for q in range(cols):
            x = margin_left + cell_size * (1.5 * q + 1.0)
            y = margin_top + row_step * r + half_h
            if q % 2 == 1:
                y += half_h
            centers.append((q, r, x, y))
    return {'cell_size': cell_size, 'rows': rows, 'centers': centers}


def hex_corners(cx, cy, cell_size):
    """平顶正六边形 6 个顶点（逆时针，起点是右侧顶点）。"""
    points = []
    for index in range(6):
        angle = math.pi / 3.0 * index
        points.append((cx + cell_size * math.cos(angle), cy + cell_size * math.sin(angle)))
    return points


def draw_nato_glyph(graphics, rect, branch, pen):
    """在军标方框里画兵种符号（APP-6 风格），画法同初设编辑器。"""
    left, top = rect.Left, rect.Top
    w, h = rect.Width, rect.Height
    x1, x2 = left + w * 0.24, left + w * 0.76
    y1, y2 = top + h * 0.24, top + h * 0.76
    cx, cy = left + w / 2.0, top + h / 2.0

    if branch == '步兵':
        graphics.DrawLine(pen, x1, y1, x2, y2)
        graphics.DrawLine(pen, x1, y2, x2, y1)
    elif branch == '装甲':
        graphics.DrawEllipse(pen, left + w * 0.20, top + h * 0.28, w * 0.60, h * 0.44)
    elif branch == '骑兵':
        graphics.DrawLine(pen, x1, y2, x2, y1)
    elif branch == '炮兵':
        brush = SolidBrush(pen.Color)
        graphics.FillEllipse(brush, cx - w * 0.11, cy - h * 0.16, w * 0.22, h * 0.32)
        brush.Dispose()
    elif branch == '反坦克':
        graphics.DrawLine(pen, x1, y2, cx, y1)
        graphics.DrawLine(pen, cx, y1, x2, y2)
    elif branch == '防空':
        # APP-6 防空：向上的半圆弧（穹顶）
        graphics.DrawArc(pen, cx - w * 0.30, cy - h * 0.14, w * 0.60, h * 0.56, 180.0, 180.0)
    elif branch == '侦察':
        graphics.DrawLine(pen, x1, y2, x2, y1)
        brush = SolidBrush(pen.Color)
        graphics.FillEllipse(brush, x2 - w * 0.14, y1 - h * 0.12, w * 0.14, h * 0.20)
        brush.Dispose()
    elif branch == '工兵':
        graphics.DrawLine(pen, x1, y1, x1, y2)
        for y in (y1, cy, y2):
            graphics.DrawLine(pen, x1, y, x2, y)
    elif branch == '通信':
        graphics.DrawLines(pen, [PointF(x2, y1), PointF(cx + w * 0.04, cy),
                                 PointF(cx - w * 0.04, cy), PointF(x1, y2)])
    elif branch == '后勤':
        for y in (y1, cy, y2):
            graphics.DrawLine(pen, x1, y, x2, y)
    elif branch == '指挥部':
        flag_x = left + w * 0.32
        graphics.DrawLine(pen, flag_x, y1, flag_x, y2)
        graphics.DrawLine(pen, flag_x, y1, flag_x + w * 0.24, y1 + h * 0.10)
        graphics.DrawLine(pen, flag_x + w * 0.24, y1 + h * 0.10, flag_x, y1 + h * 0.20)
    elif branch == '航空':
        graphics.DrawLine(pen, cx, y1, cx, y2)
        graphics.DrawLine(pen, x1, cy + h * 0.06, cx, cy - h * 0.14)
        graphics.DrawLine(pen, cx, cy - h * 0.14, x2, cy + h * 0.06)


def group_units(units):
    """按格子把单位分组：{(列,行): [单位, ...]}。"""
    stacks = {}
    for unit in (units or []):
        q, r = unit.get('q'), unit.get('r')
        if q is None or r is None:
            cell = parse_cell_key(unit.get('cell'))
            if cell is None:
                continue
            q, r = cell
        stacks.setdefault((int(q), int(r)), []).append(unit)
    return stacks


def make_grid_tile(cell, color):
    """可平铺的六角格线贴图：宽 3*cell、高 sqrt(3)*cell 正好一个周期。

    逐格画几百个六边形在 pythonnet 里很慢（每次调用都有开销），
    做成贴图后用 TextureBrush 一次铺满。
    """
    from System import Array
    step = math.sqrt(3.0) * cell
    width = max(2, int(math.ceil(3.0 * cell)))
    height = max(2, int(math.ceil(step)))
    tile = Bitmap(width, height)
    graphics = Graphics.FromImage(tile)
    pen = Pen(color)
    try:
        graphics.SmoothingMode = SmoothingMode.AntiAlias
        for cx, cy in ((cell, step / 2.0), (2.5 * cell, step)):
            corners = hex_corners(cx, cy, cell)
            for dx in (-width, 0, width):          # 压边的格子要补画，平铺才无缝
                for dy in (-height, 0, height):
                    graphics.DrawPolygon(pen, Array[PointF]([
                        PointF(x + dx, y + dy) for x, y in corners
                    ]))
    finally:
        pen.Dispose()
        graphics.Dispose()
    return tile


def edge_segment(key, centers, cell):
    """格边键 → 一条线段（地图坐标）："列,行|列,行"（两格之间）或 "列,行|方向"（地图边界）。"""
    direction_angles = {'SE': 30.0, 'S': 90.0, 'SW': 150.0,
                        'NW': 210.0, 'N': 270.0, 'NE': 330.0}
    text = str(key)
    if '|' not in text:
        return None
    left, _, right = text.partition('|')
    origin = parse_cell_key(left)
    if origin is None:
        return None
    center = centers.get(origin)
    if center is None:
        return None

    if ',' in right:
        other_key = parse_cell_key(right)
        if other_key is None:
            return None
        other = centers.get(other_key)
        if other is None:
            return None
        return center, other

    angle = direction_angles.get(right.strip().upper())
    if angle is None:
        return None
    rad = math.radians(angle)
    mid = (center[0] + cell * 0.866 * math.cos(rad), center[1] + cell * 0.866 * math.sin(rad))
    tangent = (math.cos(rad + math.pi / 2.0), math.sin(rad + math.pi / 2.0))
    half = cell * 0.5
    return ((mid[0] - tangent[0] * half, mid[1] - tangent[1] * half),
            (mid[0] + tangent[0] * half, mid[1] + tangent[1] * half))


def unit_details(unit, cell, terrain_name, stack_size, index, stats=None):
    """左侧栏里显示的单位详情：本身属性 + 上级编制 + units.data 里的作战数据。"""
    path = unit.get('path') or []
    step = unit.get('step')
    lines = [
        '番号：%s' % (unit.get('name') or '—'),
        '类型：%s' % (unit.get('type') or '—'),
        '级别：%s' % (unit.get('level') or '—'),
        '兵种：%s' % (unit.get('branch') or '—'),
        '阵营：%s' % (unit.get('faction') or '—'),
        '步数：%s' % ('—' if step is None else step),
        '',
        '位置：(%d, %d)' % (cell[0], cell[1]),
        '地形：%s（进入消耗 %d）' % (terrain_name, terrain_cost(terrain_name)),
        '',
        '上级编制：',
    ]
    if path:
        lines.extend('　' * min(position + 1, 4) + str(name)
                     for position, name in enumerate(path))
    else:
        lines.append('　—')
    if unit.get('note'):
        lines.extend(['', '备注：%s' % unit['note']])
    if stack_size > 1:
        lines.extend(['', '本格共 %d 个单位，当前第 %d 个（点地图上的军标可切换）'
                      % (stack_size, index + 1)])

    lines.extend(['', '── 单位数据（units.data）──'])
    if stats:
        values = [('%s %s' % (label, stats.get(field, '—'))) for field, label in STAT_FIELDS]
        lines.append('　'.join(values[:2]))
        lines.append('　'.join(values[2:]))
        lines.append('移动 %s（%s）' % (stats.get('move', '—'), stats.get('move_type') or '—'))
        if stats.get('establishment'):
            lines.append('编制 %s' % stats['establishment'])
    else:
        lines.append('数据表里没有“%s”这个类型' % (unit.get('type') or '—'))
    return '\n'.join(lines)


class GameView:
    """地图视图：渲染成 Bitmap 交给 PictureBox，并处理缩放 / 平移 / 选中单位。"""

    def __init__(self, picture, on_select=None, on_zoom=None):
        self.picture = picture
        self.on_select = on_select                # 回调(选中格, 该格单位, 选中序号)
        self.on_zoom = on_zoom                    # 回调(缩放比例)
        self.data = None
        self.path = None
        self.name = ''
        self.map_width = 0
        self.map_height = 0
        self.margins = {}
        self.cell = 0.0
        self.centers = {}
        self.terrain_cells = {}
        self.edge_items = []
        self.stacks = {}
        self.units = []
        self.zoom = 1.0
        self.view_x = 0.0
        self.view_y = 0.0
        self.selected_cell = None
        self.selected_units = []
        self.selected_index = 0
        self.mark_font = Font('Microsoft YaHei UI', 8, FontStyle.Bold)
        self.name_font = Font('Microsoft YaHei UI', 7)
        self._tile = None
        self._tile_key = None
        self._drag_from = None
        self._drag_view = None
        self._dragged = False
        self._wheel_handled = False               # 画布与窗口都会收到滚轮，用它去重
        picture.Cursor = Cursors.Hand
        picture.MouseDown += self.on_mouse_down
        picture.MouseMove += self.on_mouse_move
        picture.MouseUp += self.on_mouse_up
        picture.MouseWheel += self.on_picture_wheel
        picture.Resize += lambda sender, event: self.render()

    # ---------- 载入 ----------
    def load(self, data, path):
        self.data = data
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0] if path else '未命名'

        map_info = data.get('map') or {}
        cols = int(map_info.get('cols') or 0)
        self.map_width = int(map_info.get('width') or 0)
        self.map_height = int(map_info.get('height') or 0)
        self.margins = map_info.get('margins') or {}
        if cols < 1 or self.map_width < 1 or self.map_height < 1:
            raise ValueError('剧本里的地图信息不完整（cols / width / height）')

        layout = hex_layout(cols, self.map_width, self.map_height, self.margins,
                            map_info.get('cell_size'))
        self.cell = float(layout['cell_size'])
        self.centers = {(q, r): (x, y) for q, r, x, y in layout['centers']}

        self.terrain_cells = {}
        for key, value in (data.get('cells') or {}).items():
            cell = parse_cell_key(key)
            name = value[0] if isinstance(value, (list, tuple)) and value else value
            if cell is not None and name:
                self.terrain_cells[cell] = str(name)

        self.edge_items = []
        for key, value in (data.get('edges') or {}).items():
            name = value[0] if isinstance(value, (list, tuple)) and value else value
            if name:
                self.edge_items.append((str(name), key))

        self.units = list(data.get('units') or [])
        self.stacks = group_units(self.units)
        self.clear_selection()
        self._tile = None
        self._tile_key = None
        self.fit()

    def clear_selection(self):
        self.selected_cell = None
        self.selected_units = []
        self.selected_index = 0

    # ---------- 坐标换算 ----------
    def to_screen(self, x, y):
        return ((x - self.view_x) * self.zoom, (y - self.view_y) * self.zoom)

    def to_map(self, sx, sy):
        return (sx / self.zoom + self.view_x, sy / self.zoom + self.view_y)

    def grid_tile(self, cell_px):
        """网格贴图：尺寸（放大比例）没变就复用。"""
        key = round(cell_px, 1)
        if self._tile is None or self._tile_key != key:
            self._tile = make_grid_tile(cell_px, GRID_COLOR)
            self._tile_key = key
        return self._tile

    # ---------- 视图 ----------
    def fit(self):
        width = max(1, self.picture.ClientSize.Width)
        height = max(1, self.picture.ClientSize.Height)
        if self.map_width <= 0 or self.map_height <= 0:
            return
        zoom = min(width / float(self.map_width), height / float(self.map_height)) * 0.98
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        self.center_on(self.map_width / 2.0, self.map_height / 2.0)

    def center_on(self, x, y):
        width = max(1, self.picture.ClientSize.Width)
        height = max(1, self.picture.ClientSize.Height)
        self.view_x = x - width / (2.0 * self.zoom)
        self.view_y = y - height / (2.0 * self.zoom)
        self.clamp_view()
        self.render()

    def clamp_view(self):
        """地图比视口小就居中，否则不许拖出边界。"""
        width = max(1, self.picture.ClientSize.Width) / self.zoom
        height = max(1, self.picture.ClientSize.Height) / self.zoom
        if self.map_width <= width:
            self.view_x = (self.map_width - width) / 2.0
        else:
            self.view_x = max(0.0, min(self.view_x, self.map_width - width))
        if self.map_height <= height:
            self.view_y = (self.map_height - height) / 2.0
        else:
            self.view_y = max(0.0, min(self.view_y, self.map_height - height))

    def zoom_at(self, factor, sx, sy):
        """以给定屏幕点为锚点缩放。"""
        map_x, map_y = self.to_map(sx, sy)
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * factor))
        self.view_x = map_x - sx / self.zoom
        self.view_y = map_y - sy / self.zoom
        self.clamp_view()
        self.render()

    def zoom_center(self, factor):
        self.zoom_at(factor, self.picture.ClientSize.Width // 2,
                     self.picture.ClientSize.Height // 2)

    def pan_by(self, dx, dy):
        """按屏幕像素平移：dx/dy 是画面移动方向。"""
        self.view_x -= dx / self.zoom
        self.view_y -= dy / self.zoom
        self.clamp_view()
        self.render()

    # ---------- 鼠标 ----------
    def on_mouse_down(self, sender, event):
        self._drag_from = (event.X, event.Y)
        self._drag_view = (self.view_x, self.view_y)
        self._dragged = False
        self.picture.Capture = True

    def on_mouse_move(self, sender, event):
        if self._drag_from is None:
            return
        dx = event.X - self._drag_from[0]
        dy = event.Y - self._drag_from[1]
        if abs(dx) > 3 or abs(dy) > 3:
            self._dragged = True
        self.view_x = self._drag_view[0] - dx / self.zoom
        self.view_y = self._drag_view[1] - dy / self.zoom
        self.clamp_view()
        self.render()

    def on_mouse_up(self, sender, event):
        self.picture.Capture = False
        was_drag = self._dragged
        self._drag_from = None
        if was_drag:
            return
        self.select_at(event.X, event.Y)

    def on_picture_wheel(self, sender, event):
        self._wheel_handled = True
        self.handle_wheel(event)

    def on_form_wheel(self, sender, event):
        """滚轮冒泡到窗口：画布已处理过就跳过，否则鼠标在画布上才处理。"""
        if self._wheel_handled:
            self._wheel_handled = False
            return
        position = self.picture.PointToClient(Cursor.Position)
        if not self.picture.ClientRectangle.Contains(position):
            return
        self.handle_wheel(event)

    def handle_wheel(self, event):
        """滚轮直接缩放（以光标为中心）；按住 Shift 则改成左右平移。"""
        if self.data is None:
            return
        position = self.picture.PointToClient(Cursor.Position)
        if not self.picture.ClientRectangle.Contains(position):
            position = Point(self.picture.ClientSize.Width // 2,
                             self.picture.ClientSize.Height // 2)
        if (Control.ModifierKeys & Keys.Shift) == Keys.Shift:
            self.pan_by(event.Delta / 3.0, 0)
        else:
            factor = ZOOM_STEP if event.Delta > 0 else 1.0 / ZOOM_STEP
            self.zoom_at(factor, position.X, position.Y)

    # ---------- 选中 ----------
    def cell_at(self, sx, sy):
        """屏幕坐标 → 最近的格子（超出约一格就算没点到）。"""
        map_x, map_y = self.to_map(sx, sy)
        best = None
        best_distance = self.cell * 1.05
        for key, (cx, cy) in self.centers.items():
            distance = math.hypot(cx - map_x, cy - map_y)
            if distance < best_distance:
                best_distance = distance
                best = key
        return best

    def select_at(self, sx, sy):
        """点击：选中格子；如果点到某个军标，就选中那个单位。"""
        cell = self.cell_at(sx, sy)
        if cell is None:
            self.select_cell(None)
            return
        units = self.stacks.get(cell, [])
        index = 0
        if len(units) > 1:
            center = self.centers.get(cell)
            if center is not None:
                cx, cy = self.to_screen(center[0], center[1])
                slots = self.stack_slots(cx, cy, self.cell * self.zoom, len(units))
                for position, (bx, by, bw, bh) in enumerate(slots):
                    if (bx - bw / 2.0) <= sx <= (bx + bw / 2.0) and \
                       (by - bh / 2.0) <= sy <= (by + bh / 2.0):
                        index = position
                        break
        self.select_cell(cell, index)

    def select_cell(self, cell, index=0):
        if cell is None:
            self.clear_selection()
        else:
            self.selected_cell = (int(cell[0]), int(cell[1]))
            self.selected_units = self.stacks.get(self.selected_cell, [])
            self.selected_index = index if 0 <= index < len(self.selected_units) else 0
        self.render()
        if self.on_select is not None:
            self.on_select(self.selected_cell, self.selected_units, self.selected_index)

    def select_unit_index(self, index):
        if self.selected_units and 0 <= index < len(self.selected_units):
            self.select_cell(self.selected_cell, index)

    def focus_cell(self, q, r):
        """选中并把某格居中（以后做“跳到单位”之类的功能用）。"""
        self.select_cell((q, r))
        center = self.centers.get((q, r))
        if center is not None:
            self.center_on(center[0], center[1])
        else:
            self.render()

    def selected_unit(self):
        if self.selected_units and 0 <= self.selected_index < len(self.selected_units):
            return self.selected_units[self.selected_index]
        return None

    # ---------- 渲染 ----------
    def render(self):
        width = max(1, self.picture.ClientSize.Width)
        height = max(1, self.picture.ClientSize.Height)
        bitmap = Bitmap(width, height)
        graphics = Graphics.FromImage(bitmap)
        try:
            graphics.Clear(GAME_BACK)
            if self.data is not None:
                self.draw_map(graphics, width, height)
        finally:
            graphics.Dispose()
        previous = self.picture.Image
        self.picture.Image = bitmap
        if previous is not None:
            previous.Dispose()
        if self.on_zoom is not None and self.data is not None:
            self.on_zoom(self.zoom)

    def draw_map(self, graphics, width, height):
        zoom = self.zoom
        origin_x, origin_y = self.to_screen(0.0, 0.0)
        paper = RectangleF(origin_x, origin_y, self.map_width * zoom, self.map_height * zoom)

        paper_brush = SolidBrush(PAPER_COLOR)
        graphics.FillRectangle(paper_brush, paper)
        paper_brush.Dispose()

        cell_px = self.cell * zoom
        if cell_px >= 3.0:
            tile = self.grid_tile(cell_px)
            texture = TextureBrush(tile)
            texture.WrapMode = WrapMode.Tile
            # 贴图尺寸取的是整数（ceil），直接平铺会和真实周期差一丁点，越往右下越偏。
            # 这里把贴图缩放回精确周期，格线和格子就严格对齐了。
            texture.Transform = Matrix(
                (3.0 * cell_px) / tile.Width, 0.0,
                0.0, (math.sqrt(3.0) * cell_px) / tile.Height,
                origin_x + float(self.margins.get('l') or 0) * zoom,
                origin_y + float(self.margins.get('t') or 0) * zoom,
            )
            graphics.FillRectangle(texture, paper)
            texture.ResetTransform()
            texture.Dispose()

        graphics.SmoothingMode = SmoothingMode.AntiAlias
        view = (self.view_x, self.view_y,
                self.view_x + width / zoom, self.view_y + height / zoom)
        self.draw_terrain(graphics, view)
        self.draw_edges(graphics, view)
        if cell_px >= 9.0:
            self.draw_units(graphics, cell_px)
        self.draw_selection(graphics)

    def in_view(self, x, y, view, pad):
        return (view[0] - pad) <= x <= (view[2] + pad) and (view[1] - pad) <= y <= (view[3] + pad)

    def hex_points(self, cx, cy):
        from System import Array
        return Array[PointF]([
            PointF(*self.to_screen(x, y))
            for x, y in hex_corners(cx, cy, self.cell)
        ])

    def draw_terrain(self, graphics, view):
        for (q, r), name in self.terrain_cells.items():
            center = self.centers.get((q, r))
            if center is None or not self.in_view(center[0], center[1], view, self.cell):
                continue
            brush = SolidBrush(to_color(terrain_color(name)))
            graphics.FillPolygon(brush, self.hex_points(center[0], center[1]))
            brush.Dispose()

    def draw_edges(self, graphics, view):
        for name, key in self.edge_items:
            segment = edge_segment(key, self.centers, self.cell)
            if segment is None:
                continue
            (x1, y1), (x2, y2) = segment
            if not (self.in_view(x1, y1, view, self.cell)
                    or self.in_view(x2, y2, view, self.cell)):
                continue
            pen = Pen(to_color(edge_color(name)), max(2.0, EDGE_PEN_WIDTH * self.zoom))
            graphics.DrawLine(pen, PointF(*self.to_screen(x1, y1)),
                              PointF(*self.to_screen(x2, y2)))
            pen.Dispose()

    def draw_units(self, graphics, cell_px):
        for (q, r), records in self.stacks.items():
            center = self.centers.get((q, r))
            if center is None:
                continue
            cx, cy = self.to_screen(center[0], center[1])
            selected_stack = self.selected_cell == (q, r)
            slots = self.stack_slots(cx, cy, cell_px, len(records))
            for index, (bx, by, bw, bh) in enumerate(slots):
                self.draw_unit_symbol(graphics, bx, by, bw, bh, records[index],
                                      number=(index + 1) if len(records) > 1 else 0,
                                      selected=selected_stack and index == self.selected_index)

    def stack_slots(self, cx, cy, cell_px, count):
        """一格内多个军标的排布（列数取 sqrt(n) 向上取整），返回 [(中心x, 中心y, 宽, 高)]。"""
        count = max(1, count)
        columns = max(1, int(math.ceil(math.sqrt(count))))
        rows = max(1, int(math.ceil(count / float(columns))))
        box_w = cell_px * 1.30
        box_h = cell_px * 1.24
        slot_w = box_w / columns
        slot_h = box_h / rows
        width = max(7.0, min(slot_w * 0.94, slot_h * 0.94 * SYMBOL_RATIO))
        height = max(5.0, width / SYMBOL_RATIO)
        slots = []
        for index in range(count):
            column = index % columns
            row = index // columns
            slots.append((cx - box_w / 2.0 + slot_w * (column + 0.5),
                          cy - box_h / 2.0 + slot_h * (row + 0.5),
                          width, height))
        return slots

    def draw_unit_symbol(self, graphics, cx, cy, width, height, unit,
                         number=0, selected=False):
        """一个北约军标：阵营色底框（敌军画菱形）+ 兵种符号 + 上方级别标记；底下不写番号。"""
        from System import Array
        rgb = faction_color(unit.get('faction'))
        color = to_color(rgb)
        ink = ink_color(rgb)
        shape = affiliation_frame(unit)
        corners = frame_points(shape, cx, cy, width, height)
        points = Array[PointF]([PointF(x, y) for x, y in corners])

        face = SolidBrush(color)
        graphics.FillPolygon(face, points)
        face.Dispose()

        pen = Pen(ink, max(1.0, width * 0.05))
        graphics.DrawPolygon(pen, points)
        if height >= 8:
            draw_nato_glyph(graphics, RectangleF(cx - width / 2.0, cy - height / 2.0,
                                                 width, height),
                            unit.get('branch') or '', pen)
        pen.Dispose()

        if selected:
            scale_x = (width + 4.0) / width
            scale_y = (height + 4.0) / height
            highlight = Pen(UNIT_SELECT_COLOR, max(1.5, width * 0.07))
            graphics.DrawPolygon(highlight, Array[PointF]([
                PointF(cx + (x - cx) * scale_x, cy + (y - cy) * scale_y) for x, y in corners
            ]))
            highlight.Dispose()

        mark = LEVEL_MARKS.get(unit.get('level') or '')
        if mark and height >= 12:
            self.draw_centered_text(graphics, mark, cx, cy - height * 1.22,
                                    self.mark_font, color)
        if number and height >= 12:
            self.draw_centered_text(graphics, str(number), cx - width * 0.34,
                                    cy - height * 1.22, self.name_font, color)

    def draw_centered_text(self, graphics, text, cx, y, font, color):
        size = graphics.MeasureString(text, font)
        brush = SolidBrush(color)
        graphics.DrawString(text, font, brush, float(cx - size.Width / 2.0), float(y))
        brush.Dispose()

    def draw_selection(self, graphics):
        if self.selected_cell is None:
            return
        center = self.centers.get(self.selected_cell)
        if center is None:
            return
        pen = Pen(SELECT_COLOR, 2.5)
        graphics.DrawPolygon(pen, self.hex_points(center[0], center[1]))
        pen.Dispose()

    def dispose(self):
        if self.picture.Image is not None:
            self.picture.Image.Dispose()
            self.picture.Image = None
        if self._tile is not None:
            self._tile.Dispose()
            self._tile = None


def _bar_button(text, width=96):
    button = Button()
    button.Text = text
    button.Size = Size(width, 32)
    button.FlatStyle = FlatStyle.System
    return button


def build_game_window(owner=None, scenario_path=None):
    """创建游戏窗口：顶栏 + 左侧单位栏 + 地图画布 + 状态栏。"""
    data = None
    reason = None
    if scenario_path:
        data, reason = read_scenario(scenario_path)

    form = Form()
    form.Text = WINDOW_TITLE
    form.ClientSize = WINDOW_SIZE
    form.MinimumSize = MINIMUM_SIZE
    form.BackColor = GAME_BACK
    form.KeyPreview = True                     # WASD 在窗口任何位置都有效
    if owner is not None:
        form.StartPosition = FormStartPosition.CenterParent
    else:
        form.StartPosition = FormStartPosition.CenterScreen

    # 先加 Fill，再加四周停靠的面板：各区域不会重叠
    picture = PictureBox()
    picture.Dock = DockStyle.Fill
    picture.BackColor = GAME_BACK
    picture.SizeMode = PictureBoxSizeMode.Normal
    form.Controls.Add(picture)

    side = Panel()
    side.Dock = DockStyle.Left
    side.Width = SIDE_WIDTH
    side.BackColor = PANEL_BACK
    form.Controls.Add(side)

    details = Label()
    details.Dock = DockStyle.Fill
    details.ForeColor = TEXT_COLOR
    details.BackColor = PANEL_BACK
    details.Font = Font('Microsoft YaHei UI', 9)
    details.Padding = Padding(12, 8, 12, 8)
    side.Controls.Add(details)

    stack_list = ListBox()
    stack_list.Dock = DockStyle.Top
    stack_list.Height = 112
    stack_list.BackColor = PANEL_BACK
    stack_list.ForeColor = TEXT_COLOR
    stack_list.Font = Font('Microsoft YaHei UI', 9)
    stack_list.BorderStyle = BORDER_NONE
    stack_list.IntegralHeight = False
    stack_list.SelectionMode = SelectionMode.One
    side.Controls.Add(stack_list)

    side_title = Label()
    side_title.Text = '单位'
    side_title.Dock = DockStyle.Top
    side_title.Height = 30
    side_title.TextAlign = ContentAlignment.MiddleLeft
    side_title.ForeColor = TEXT_COLOR
    side_title.BackColor = PANEL_BACK
    side_title.Font = Font('Microsoft YaHei UI', 10, FontStyle.Bold)
    side_title.Padding = Padding(12, 0, 0, 0)
    side.Controls.Add(side_title)

    status = Label()
    status.Dock = DockStyle.Bottom
    status.Height = STATUS_HEIGHT
    status.BackColor = PANEL_BACK
    status.ForeColor = DIM_TEXT
    status.TextAlign = ContentAlignment.MiddleLeft
    status.Padding = Padding(10, 0, 0, 0)
    status.Font = Font('Microsoft YaHei UI', 9)
    form.Controls.Add(status)

    top = Panel()
    top.Dock = DockStyle.Top
    top.Height = TOP_BAR_HEIGHT
    top.BackColor = BAR_BACK
    form.Controls.Add(top)

    title = Label()
    title.AutoSize = True
    title.ForeColor = TEXT_COLOR
    title.BackColor = Color.Transparent
    title.Font = Font('Microsoft YaHei UI', 12, FontStyle.Bold)
    title.Location = Point(14, 15)
    top.Controls.Add(title)

    zoom_label = Label()
    zoom_label.AutoSize = True
    zoom_label.ForeColor = DIM_TEXT
    zoom_label.BackColor = Color.Transparent
    zoom_label.Font = Font('Microsoft YaHei UI', 9)
    top.Controls.Add(zoom_label)

    view = GameView(picture,
                    on_select=lambda cell, units, index: refresh_selection(cell, units, index),
                    on_zoom=lambda zoom: update_zoom(zoom))

    def update_zoom(zoom):
        zoom_label.Text = '%d%%' % round(zoom * 100)
        zoom_label.Location = Point(max(240, top.ClientSize.Width - zoom_label.Width - 150), 20)

    def scenario_line():
        map_info = (data or {}).get('map') or {}
        paper = str(map_info.get('paper') or '?').upper()
        return ('%s · %s · %d 列 · 地形 %d · 格边 %d · 单位 %d'
                % (view.name, '自定义' if paper == 'CUSTOM' else paper,
                   int(map_info.get('cols') or 0), len(view.terrain_cells),
                   len(view.edge_items), len(view.units)))

    syncing = {'flag': False}

    def refresh_selection(cell, units, index):
        """画布选中变化 → 刷新左侧单位栏与状态栏。"""
        syncing['flag'] = True
        try:
            stack_list.Items.Clear()
            for position, unit in enumerate(units):
                stack_list.Items.Add('%d. %s（%s · %s）' % (
                    position + 1,
                    unit.get('name') or unit.get('type') or '?',
                    unit.get('level') or '—',
                    unit.get('branch') or '—',
                ))
            if units:
                stack_list.SelectedIndex = index if 0 <= index < len(units) else 0
        finally:
            syncing['flag'] = False

        if not cell:
            details.Text = ('点击地图上的单位来选中它。\n\n'
                            '滚轮缩放（以光标为中心）\n'
                            'WASD / 方向键平移\n'
                            'Shift+滚轮左右平移\n'
                            '按住左键拖动平移')
            status.Text = scenario_line() + '　|　点击地图上的单位'
            return

        terrain = view.terrain_cells.get(cell, '空地')
        if not units:
            details.Text = ('位置：(%d, %d)\n地形：%s（进入消耗 %d）\n\n该格没有单位。'
                            % (cell[0], cell[1], terrain, terrain_cost(terrain)))
            status.Text = ('%s　|　选中 (%d,%d) %s · 无单位'
                           % (scenario_line(), cell[0], cell[1], terrain))
            return

        unit = units[index] if 0 <= index < len(units) else units[0]
        details.Text = unit_details(unit, cell, terrain, len(units), index,
                                    unit_stats(unit.get('type')))
        status.Text = ('%s　|　选中 %s (%d,%d)%s'
                       % (scenario_line(), unit.get('name') or unit.get('type') or '?',
                          cell[0], cell[1],
                          '　本格 %d 个单位' % len(units) if len(units) > 1 else ''))

    def on_stack_selected(sender, event):
        if syncing['flag'] or view.selected_cell is None:
            return
        index = stack_list.SelectedIndex
        if index >= 0:
            view.select_unit_index(index)

    stack_list.SelectedIndexChanged += on_stack_selected

    def on_key_down(sender, event):
        key = event.KeyCode
        if key in (Keys.W, Keys.Up):
            view.pan_by(0, PAN_STEP)
        elif key in (Keys.S, Keys.Down):
            view.pan_by(0, -PAN_STEP)
        elif key in (Keys.A, Keys.Left):
            view.pan_by(PAN_STEP, 0)
        elif key in (Keys.D, Keys.Right):
            view.pan_by(-PAN_STEP, 0)
        elif key in (Keys.Add, Keys.Oemplus):
            view.zoom_center(ZOOM_STEP)
        elif key in (Keys.Subtract, Keys.OemMinus):
            view.zoom_center(1.0 / ZOOM_STEP)
        else:
            return
        event.Handled = True

    form.KeyDown += on_key_down
    form.MouseWheel += view.on_form_wheel        # 焦点不在画布上时滚轮也能用

    fit_button = _bar_button('适应窗口')
    fit_button.Click += lambda sender, event: view.fit()
    zoom_in = _bar_button('放大', 76)
    zoom_in.Click += lambda sender, event: view.zoom_center(ZOOM_STEP)
    zoom_out = _bar_button('缩小', 76)
    zoom_out.Click += lambda sender, event: view.zoom_center(1.0 / ZOOM_STEP)

    x = 220
    for button in (fit_button, zoom_in, zoom_out):
        button.Location = Point(x, 10)
        top.Controls.Add(button)
        x += button.Width + 8

    if data is not None:
        try:
            view.load(data, scenario_path)
            title.Text = view.name
            form.Text = '%s - %s' % (view.name, WINDOW_TITLE)
            refresh_selection(None, [], 0)
            update_zoom(view.zoom)
        except Exception as exc:
            title.Text = '打开剧本失败'
            show_error('打开剧本失败：\n\n%s\n（%s: %s）'
                       % (scenario_path, type(exc).__name__, exc), form)
    else:
        title.Text = '没有剧本'
        show_error('读取剧本失败：\n\n%s\n（%s）' % (scenario_path, reason), form)

    form.FormClosed += lambda sender, event: view.dispose()
    form.game_view = view                        # 方便以后接游戏功能 / 脚本
    return form


def open_game_window(owner, scenario_path):
    """打开游戏窗口（剧本列表点卡片调用）。"""
    form = build_game_window(owner, scenario_path)
    try:
        if owner is not None:
            form.ShowDialog(owner)
        else:
            form.ShowDialog()
    finally:
        form.Dispose()
    return True


def main():
    """单独运行：打开找到的第一个剧本（只是开发时方便，游戏窗口不依赖这个搜索路径）。"""
    def run():
        Application.EnableVisualStyles()
        Application.SetCompatibleTextRenderingDefault(False)
        root = project_dir()
        for parts in STANDALONE_SEARCH_PATHS:
            folder = os.path.join(root, *parts)
            if not os.path.isdir(folder):
                continue
            for name in sorted(os.listdir(folder)):
                if name.lower().endswith('.scenario'):
                    open_game_window(None, os.path.join(folder, name))
                    return
        show_error('没有找到 .scenario 剧本。')

    thread = Thread(ThreadStart(run))
    thread.SetApartmentState(ApartmentState.STA)
    thread.Start()
    thread.Join()
    return 0


if __name__ == '__main__':
    sys.exit(main())
