"""游戏窗口：把剧本数据画成游戏界面（地图 + 单位），并处理选中 / 缩放 / 平移。

- open_game_window(owner, scenario_path)：打开游戏窗口（剧本列表点卡片调用）
- main()：单独运行本文件，直接看 setupsaves 里的第一个剧本（只是开发时方便）

热座（同一台机器轮流操作）：
- 双方阵营按剧本里出现的 faction 轮流行动，顶栏显示第几回合、轮到哪一方；
  点“下一回合”把行动权交给对方，两方都走完一圈就进入下一回合。
- 移动：点自己方的单位选中它，地图上高亮的格子就是它这回合能走到的地方
  （数字是消耗的移动力），点一下就走过去。消耗 = 目标格地形消耗 + 跨过那条
  格边的额外消耗，用 Dijkstra 算最省路线；有敌方单位的格子进不去。
  移动力来自单位类型数据里的 move，走完就变淡，换回合时恢复。
- 不是当前行动方的单位画成半透明（双方都有单位时才这样区分）。
- 任何时间都能保存：顶栏“保存”/ Ctrl+S 直接写 saves/<剧本名>.hotseat，
  “另存为”/ Ctrl+Shift+S 换文件名。存档内容是场上地图、单位与回合状态，
  .hotseat 也是本文件能直接打开的输入（读回来接着打）。

操作：滚轮缩放（以光标为中心）、WASD 或方向键平移、按住左键拖动平移、
单击单位选中它（同一格多个单位就点哪个选哪个），左侧栏显示选中单位的具体情况。

本文件是自给自足的：剧本读取、地图几何、地形/阵营配色、北约军标画法都在这里，
不再依赖 setup/ 那套初设工具，也没有任何跳回它们的入口；数据导进来之后，
游戏界面只跟这份数据打交道。本文件从磁盘加载，改完不用重新打包 exe。
"""
import heapq
import json
import math
import os
import sys
import time

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
    DialogResult,
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
    SaveFileDialog,
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
STANDALONE_SEARCH_PATHS = (('setup', 'setupsaves'), ('scenarios'))

# 热座存档（.hotseat）：地图 + 单位 + 回合状态，保存在项目根目录的 saves 文件夹
# （.scenario 是开新局的初设，.hotseat 是打到一半的存档，两者共用同一套地图/单位字段）
SCENARIO_TYPE = 'SCENARIO'
HOTSEAT_TYPE = 'HOTSEAT'
HOTSEAT_VERSION = 1
HOTSEAT_SUFFIX = '.hotseat'
SAVES_DIR_NAME = 'saves'
HOTSEAT_FILE_FILTER = ('热座存档 (*.hotseat)|*.hotseat|'
                       '剧本 (*.scenario)|*.scenario|所有文件 (*.*)|*.*')

# 阵营推导：剧本里只写了一个阵营时补一个对手席位，一个都没有时用这组默认名
DEFAULT_FACTIONS = ('红方', '蓝方')
UNKNOWN_FACTION = '未编成'
NOTIONAL_FACTION = '对方'
# 不是当前行动方的单位画成半透明（0-255）
INACTIVE_ALPHA = 110


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
    """读游戏数据：.scenario（开新局的初设）或 .hotseat（热座存档）。

    两种文件都是 JSON，地图 / 格边 / 单位字段完全一样；存档另外带一个 turn 块
    （第几回合、轮到哪一方）。返回 (数据, 失败原因)。
    """
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        return None, '%s: %s' % (type(exc).__name__, exc)
    if not isinstance(data, dict):
        return None, '不是剧本文件（type 字段应为 SCENARIO / HOTSEAT）'
    kind = str(data.get('type') or '')
    if kind not in (SCENARIO_TYPE, HOTSEAT_TYPE):
        return None, '不是剧本文件（type 字段应为 SCENARIO / HOTSEAT）'
    if kind == HOTSEAT_TYPE and not isinstance(data.get('map'), dict):
        return None, '存档里没有地图数据（缺少 map）'
    return data, None


def project_saves_dir():
    """存档目录（项目根目录下的 saves），不存在就创建；创建失败返回 None。"""
    path = os.path.join(project_dir(), SAVES_DIR_NAME)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return None
    return path


def faction_key(value):
    """阵营名归一（比较用）：去掉首尾空白。"""
    return str(value or '').strip()


class HotseatGame:
    """热座回合状态：双方阵营轮流行动，一方打完点“下一回合”换手。

    factions 是行动顺序。剧本里只写了一个阵营（演示剧本就是只有德军）时补一个
    “对方”席位，点“下一回合”照样能走完一圈回到第 2 回合。
    """

    def __init__(self, units=None, turn=None, mode=None):
        turn = turn if isinstance(turn, dict) else {}
        self.units = list(units or [])
        self.mode = str(mode or turn.get('mode') or '')
        self.source_scenario = str(turn.get('source_scenario') or '')
        self.path = None                     # 当前存档路径（另存为后更新）
        self.factions = self._build_factions(turn.get('factions'))
        self.number = max(1, int(turn.get('number') or 1))
        self.index = self._build_index(turn)

    def _build_factions(self, saved):
        """行动顺序：先信存档里记的，再按剧本里出现的阵营补齐。"""
        names = []
        for name in (saved or []):
            text = faction_key(name)
            if text and text not in names:
                names.append(text)
        for unit in self.units:
            text = faction_key(unit.get('faction')) or UNKNOWN_FACTION
            if text not in names:
                names.append(text)
        if len(names) == 1:
            names.append(NOTIONAL_FACTION)
        elif not names:
            names = list(DEFAULT_FACTIONS)
        return names

    def _build_index(self, turn):
        """轮到第几个阵营：优先按存档里的下标，其次按阵营名找。"""
        try:
            index = int(turn.get('index'))
        except (TypeError, ValueError):
            index = -1
        name = faction_key(turn.get('faction'))
        if not 0 <= index < len(self.factions) and name in self.factions:
            index = self.factions.index(name)
        if not 0 <= index < len(self.factions):
            index = 0
        return index

    @property
    def current(self):
        """轮到哪一方。"""
        return self.factions[self.index]

    def advance(self):
        """结束当前方的回合：轮到下一方；转完一圈就进入下一回合。"""
        self.index += 1
        if self.index >= len(self.factions):
            self.index = 0
            self.number += 1
        return self.current

    def unit_count(self, faction=None):
        """某一方还有多少单位（默认当前方）。"""
        name = self.current if faction is None else faction_key(faction)
        return sum(1 for unit in self.units
                   if faction_key(unit.get('faction')) == name)

    def to_dict(self):
        return {
            'number': self.number,
            'index': self.index,
            'faction': self.current,
            'factions': list(self.factions),
            'mode': self.mode,
            'source_scenario': self.source_scenario,
        }


def hotseat_payload(view, game, timestamp=None):
    """把场上地图、单位与回合状态打包成 .hotseat 内容（纯数据）。"""
    data = view.data if isinstance(view.data, dict) else {}
    return {
        'v': HOTSEAT_VERSION,
        'type': HOTSEAT_TYPE,
        'saved_at': timestamp or time.strftime('%Y-%m-%d %H:%M:%S'),
        'map': dict(view.map_info),
        'cells': dict(data.get('cells') or {}),
        'edges': dict(data.get('edges') or {}),
        'oob': data.get('oob'),
        'units': [dict(unit) for unit in view.units],
        'turn': game.to_dict(),
    }


def save_hotseat(path, view, game):
    """写 .hotseat 存档；返回 (是否成功, 失败原因)。"""
    try:
        payload = hotseat_payload(view, game)
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except (OSError, ValueError) as exc:
        return False, '%s: %s' % (type(exc).__name__, exc)
    return True, None


def hotseat_file_name(view, game):
    """快速保存 / 另存为对话框里的默认文件名。"""
    source = game.source_scenario or view.path or ''
    base = os.path.splitext(os.path.basename(source))[0].strip()
    if not base:
        base = (view.name or '').strip() or '未命名'
    return base + HOTSEAT_SUFFIX


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


# ---------- 移动规则（纯逻辑：只有单位数据与地图数据参与计算） ----------

# 单位类型数据里没写 move 时的兜底移动力
DEFAULT_MOVE_POINTS = 4
# 可达格高亮的填充 / 描边透明度
MOVE_OVERLAY_ALPHA = 60
MOVE_OVERLAY_EDGE_ALPHA = 170
# 高亮格上写消耗数字的最小格子像素
MOVE_COST_MIN_PIXELS = 26.0

# 平顶六边形（奇数列错位）的 6 个邻居偏移，和 Hex_Editor/hexmap.py 用同一张表
_OFFSETS_EVEN = ((0, -1), (1, -1), (1, 0), (0, 1), (-1, 0), (-1, -1))
_OFFSETS_ODD = ((0, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0))


def neighbor_offsets(q):
    """列 q 的 6 个邻居偏移（保证寻路和 Hex_Editor 画出的地图一致）。"""
    return _OFFSETS_ODD if (int(q) % 2) else _OFFSETS_EVEN


def neighbors_of(centers, cell):
    """地图上真实存在的邻居格。"""
    q, r = int(cell[0]), int(cell[1])
    for dq, dr in neighbor_offsets(q):
        other = (q + dq, r + dr)
        if other in centers:
            yield other


def unit_cell(unit):
    """单位所在格：(列, 行)；取不到返回 None。"""
    q, r = unit.get('q'), unit.get('r')
    if q is None or r is None:
        return parse_cell_key(unit.get('cell'))
    try:
        return (int(q), int(r))
    except (TypeError, ValueError):
        return None


def unit_move_allowance(unit):
    """一支单位每回合的移动力：优先单位自己的 move，其次单位类型数据，最后兜底。"""
    for source in (unit.get('move'), unit_stats(unit.get('type')).get('move')):
        try:
            value = int(source)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return DEFAULT_MOVE_POINTS


def effective_move_left(unit):
    """本回合还剩多少移动力（没记过就按满移动力算）。"""
    value = unit.get('move_left')
    if value is None:
        return unit_move_allowance(unit)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return unit_move_allowance(unit)


def ensure_unit_moves(units):
    """给还没有 move_left 字段的单位补上满移动力（不动已经消耗过的记录）。"""
    for unit in units:
        if unit.get('move_left') is None:
            unit['move_left'] = unit_move_allowance(unit)


def reset_unit_moves(units, faction):
    """进入某一方的回合：把该方所有单位的移动力补满。"""
    name = faction_key(faction)
    for unit in units:
        if faction_key(unit.get('faction')) == name:
            unit['move_left'] = unit_move_allowance(unit)


def cell_move_cost(view, cell):
    """进入某格的消耗：场景里单独标过就用它，否则按地形表。"""
    q, r = int(cell[0]), int(cell[1])
    cost = view.terrain_costs.get((q, r))
    if cost is not None:
        return max(1, int(cost))
    return max(1, terrain_cost(view.terrain_cells.get((q, r), '空地')))


def edge_move_cost(view, cell_a, cell_b):
    """跨过两格之间那条边的额外消耗（没有格边地形就是 0）。"""
    key = frozenset(((int(cell_a[0]), int(cell_a[1])),
                     (int(cell_b[0]), int(cell_b[1]))))
    cost = view.edge_costs.get(key)
    if cost is not None:
        return max(0, int(cost))
    name = view.edge_between.get(key)
    return max(0, edge_cost(name)) if name else 0


def step_move_cost(view, cell_a, cell_b):
    """从 A 走到相邻格 B 的消耗 = B 的地形消耗 + 跨过那条边的消耗。"""
    return cell_move_cost(view, cell_b) + edge_move_cost(view, cell_a, cell_b)


def occupied_by_others(view, unit):
    """走不过去的格子：有别的阵营单位驻扎的格（自己人可以叠加，不算阻挡）。"""
    mine = faction_key(unit.get('faction'))
    return {cell for cell, records in view.stacks.items()
            if any(faction_key(other.get('faction')) != mine for other in records)}


def reachable_cells(view, unit, budget=None):
    """单位在剩余移动力内能走到的格子：{(列,行): 最省累计消耗}。

    用 Dijkstra 求最省消耗，地形贵的地方会绕开；进入一格的消耗算的是目标格地形
    加跨边消耗。有别的阵营单位的格子不能进；自己人的格子可以路过，但不当落脚点
    （点那种格子是选中单位，不是移动）。
    """
    start = unit_cell(unit)
    if start is None or start not in view.centers:
        return {}
    if budget is None:
        budget = effective_move_left(unit)
    if budget <= 0:
        return {}

    blocked = occupied_by_others(view, unit)
    dist = {start: 0}
    heap = [(0, start)]
    while heap:
        cost, cell = heapq.heappop(heap)
        if cost > dist.get(cell, float('inf')):
            continue
        for other in neighbors_of(view.centers, cell):
            if other in blocked:
                continue
            new_cost = cost + step_move_cost(view, cell, other)
            if new_cost > budget:
                continue
            if new_cost < dist.get(other, float('inf')):
                dist[other] = new_cost
                heapq.heappush(heap, (new_cost, other))

    dist.pop(start, None)
    for cell in list(dist):
        if cell in view.stacks:
            dist.pop(cell)
    return dist


def unit_can_move(unit, faction):
    """这支单位现在能不能动：必须是当前行动方，且本回合还有移动力。"""
    current = faction_key(faction)
    return (bool(current)
            and faction_key(unit.get('faction')) == current
            and effective_move_left(unit) > 0)


def apply_unit_move(view, unit, cell, cost):
    """把单位搬到目标格：更新坐标 / 格号 / 中心像素，并扣掉移动力。返回剩余移动力。"""
    q, r = int(cell[0]), int(cell[1])
    unit['q'] = q
    unit['r'] = r
    unit['cell'] = '%d,%d' % (q, r)
    cols = int(view.map_info.get('cols') or 0)
    if cols > 0:
        unit['cell_id'] = r * cols + q + 1        # 和 Hex_Editor 的编号规则一致
    center = view.centers.get((q, r))
    if center is not None:
        unit['center_px'] = [float(center[0]), float(center[1])]
    left = max(0, effective_move_left(unit) - max(0, int(cost)))
    unit['move_left'] = left
    return left


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


def unit_details(unit, cell, terrain_name, stack_size, index, stats=None,
                 active_faction=None):
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

    lines.extend(['', '── 本回合移动 ──',
                  '移动力：剩余 %d / %d' % (effective_move_left(unit),
                                            unit_move_allowance(unit))])
    if not active_faction:
        lines.append('没有回合信息，不能移动')
    elif faction_key(unit.get('faction')) != faction_key(active_faction):
        lines.append('现在轮到 %s：这支部队要等自己回合才能动' % active_faction)
    elif effective_move_left(unit) <= 0:
        lines.append('本回合移动力已用完，点“下一回合”后恢复')
    else:
        lines.append('点地图上高亮的格子把它走过去')

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

    def __init__(self, picture, on_select=None, on_zoom=None, on_move=None):
        self.picture = picture
        self.on_select = on_select                # 回调(选中格, 该格单位, 选中序号)
        self.on_zoom = on_zoom                    # 回调(缩放比例)
        self.on_move = on_move                    # 回调(单位, 目标格, 消耗) → 是否移动成功
        self.data = None
        self.path = None
        self.name = ''
        self.map_width = 0
        self.map_height = 0
        self.map_info = {}
        self.margins = {}
        self.cell = 0.0
        self.centers = {}
        self.terrain_cells = {}
        self.terrain_costs = {}                   # 场景里单独标过的格子消耗
        self.edge_items = []
        self.edge_costs = {}                      # 格边 -> 单独标过的跨边消耗
        self.edge_between = {}                    # 相邻两格 -> 格边地形名
        self.reachable = {}                       # 选中单位能走到的格子
        self.stacks = {}
        self.units = []
        self.zoom = 1.0
        self.view_x = 0.0
        self.view_y = 0.0
        self.selected_cell = None
        self.selected_units = []
        self.selected_index = 0
        self.active_faction = None                # 当前行动方（对方单位画半透明）
        self.dim_inactive = False                 # 双方都有单位时才需要区分
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
        self.map_info = dict(map_info)
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
        self.terrain_costs = {}
        for key, value in (data.get('cells') or {}).items():
            cell = parse_cell_key(key)
            name = value[0] if isinstance(value, (list, tuple)) and value else value
            if cell is None or not name:
                continue
            self.terrain_cells[cell] = str(name)
            # 值写成 [地形名, 消耗, 修正] 时，消耗以场景为准
            if isinstance(value, (list, tuple)) and len(value) > 1:
                try:
                    self.terrain_costs[cell] = int(value[1])
                except (TypeError, ValueError):
                    pass

        self.edge_items = []
        self.edge_costs = {}
        self.edge_between = {}
        for key, value in (data.get('edges') or {}).items():
            name = value[0] if isinstance(value, (list, tuple)) and value else value
            if not name:
                continue
            name = str(name)
            self.edge_items.append((name, key))
            ends = [parse_cell_key(part) for part in str(key).split('|')]
            if len(ends) != 2 or ends[0] is None or ends[1] is None:
                continue                          # 地图边界上的格边：不参与两格之间的移动
            pair = frozenset((ends[0], ends[1]))
            self.edge_between[pair] = name
            if isinstance(value, (list, tuple)) and len(value) > 1:
                try:
                    self.edge_costs[pair] = int(value[1])
                except (TypeError, ValueError):
                    pass

        self.units = list(data.get('units') or [])
        self.stacks = group_units(self.units)
        self.active_faction = None
        self.reachable = {}
        self.clear_selection()
        self._tile = None
        self._tile_key = None
        self.fit()

    def clear_selection(self):
        self.selected_cell = None
        self.selected_units = []
        self.selected_index = 0
        self.reachable = {}

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
        """点击：先看是不是“把选中的单位走到这一格”，否则选中格子 / 单位。"""
        cell = self.cell_at(sx, sy)
        if cell is None:
            self.select_cell(None)
            return
        # 已经选中一支能动的单位：点高亮的空格 = 走过去（点有单位的格子还是选中）
        units = self.stacks.get(cell, [])
        if not units and cell in self.reachable and self.on_move is not None:
            unit = self.selected_unit()
            if unit is not None and self.on_move(unit, cell, self.reachable[cell]):
                return
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

    def refresh_reachable(self):
        """选中变化后重算可达格：只有当前行动方、还有移动力的单位才高亮。"""
        unit = self.selected_unit()
        if unit is None or not unit_can_move(unit, self.active_faction):
            self.reachable = {}
            return
        self.reachable = reachable_cells(self, unit)

    def select_cell(self, cell, index=0):
        if cell is None:
            self.clear_selection()
        else:
            self.selected_cell = (int(cell[0]), int(cell[1]))
            self.selected_units = self.stacks.get(self.selected_cell, [])
            self.selected_index = index if 0 <= index < len(self.selected_units) else 0
        self.refresh_reachable()
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
        if self.reachable:
            self.draw_reachable(graphics, cell_px)
        if cell_px >= 9.0:
            self.draw_units(graphics, cell_px)
        self.draw_selection(graphics)

    def draw_reachable(self, graphics, cell_px):
        """可达格高亮：阵营色半透明填充 + 描边，格子够大时写下走到这里要几点移动力。"""
        rgb = faction_color(self.active_faction)
        fill = SolidBrush(Color.FromArgb(MOVE_OVERLAY_ALPHA, rgb[0], rgb[1], rgb[2]))
        pen = Pen(Color.FromArgb(MOVE_OVERLAY_EDGE_ALPHA, rgb[0], rgb[1], rgb[2]), 1.5)
        show_cost = cell_px >= MOVE_COST_MIN_PIXELS
        for cell, cost in self.reachable.items():
            center = self.centers.get(cell)
            if center is None:
                continue
            points = self.hex_points(center[0], center[1])
            graphics.FillPolygon(fill, points)
            graphics.DrawPolygon(pen, points)
            if show_cost:
                cx, cy = self.to_screen(center[0], center[1])
                self.draw_centered_text(graphics, str(cost), cx, cy - 7.0,
                                        self.name_font, TEXT_COLOR)
        pen.Dispose()
        fill.Dispose()

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
                unit = records[index]
                self.draw_unit_symbol(graphics, bx, by, bw, bh, unit,
                                      number=(index + 1) if len(records) > 1 else 0,
                                      selected=selected_stack and index == self.selected_index,
                                      dim=self.unit_is_dim(unit))

    def unit_is_dim(self, unit):
        """画成半透明的两种情况：不是当前行动方的部队；本方但本回合移动力已用完。"""
        active = faction_key(self.active_faction)
        if not active:
            return False
        if faction_key(unit.get('faction')) != active:
            return self.dim_inactive
        return effective_move_left(unit) <= 0

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
                         number=0, selected=False, dim=False):
        """一个北约军标：阵营色底框（敌军画菱形）+ 兵种符号 + 上方级别标记；底下不写番号。

        dim=True（不是当前行动方的单位）时整体画成半透明，方便热座时一眼看清轮到谁。
        """
        from System import Array
        rgb = faction_color(unit.get('faction'))
        color = to_color(rgb)
        ink = ink_color(rgb)
        if dim:
            color = Color.FromArgb(INACTIVE_ALPHA, rgb[0], rgb[1], rgb[2])
            ink = Color.FromArgb(INACTIVE_ALPHA, ink.R, ink.G, ink.B)
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


def build_game_window(owner=None, scenario_path=None, mode=None):
    """创建游戏窗口：顶栏 + 左侧单位栏 + 地图画布 + 状态栏。

    mode 是剧本列表上选的游戏模式（PVE / PVP / HOTSEAT）：现在只在状态栏里显示，玩法还没接。
    """
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
    title.AutoSize = False
    title.Size = Size(196, 20)
    title.AutoEllipsis = True
    title.TextAlign = ContentAlignment.MiddleLeft
    title.ForeColor = TEXT_COLOR
    title.BackColor = Color.Transparent
    title.Font = Font('Microsoft YaHei UI', 11, FontStyle.Bold)
    title.Location = Point(14, 5)
    top.Controls.Add(title)

    # 顶栏第二行：现在是第几回合、轮到哪一方（颜色跟着阵营走）
    turn_label = Label()
    turn_label.AutoSize = False
    turn_label.Size = Size(196, 16)
    turn_label.AutoEllipsis = True
    turn_label.ForeColor = SELECT_COLOR
    turn_label.BackColor = Color.Transparent
    turn_label.Font = Font('Microsoft YaHei UI', 9, FontStyle.Bold)
    turn_label.Location = Point(14, 27)
    top.Controls.Add(turn_label)

    zoom_label = Label()
    zoom_label.AutoSize = True
    zoom_label.ForeColor = DIM_TEXT
    zoom_label.BackColor = Color.Transparent
    zoom_label.Font = Font('Microsoft YaHei UI', 9)
    top.Controls.Add(zoom_label)

    view = GameView(picture,
                    on_select=lambda cell, units, index: refresh_selection(cell, units, index),
                    on_zoom=lambda zoom: update_zoom(zoom),
                    on_move=lambda unit, cell, cost: move_selected(unit, cell, cost))

    # 游戏状态：回合状态与当前存档路径（载入后才有值）
    state = {'game': None, 'save_path': None}

    def update_zoom(zoom):
        zoom_label.Text = '%d%%' % round(zoom * 100)
        layout_top()

    def turn_text():
        """状态栏 / 顶栏里的回合文字：第几回合 · 轮到哪一方。"""
        game = state['game']
        if game is None:
            return ''
        return '第 %d 回合 · %s' % (game.number, game.current)

    def update_turn_label():
        game = state['game']
        if game is None:
            turn_label.Text = ''
            return
        turn_label.Text = '第%d回合 · %s行动 · %d单位' % (
            game.number, game.current, game.unit_count())
        turn_label.ForeColor = to_color(faction_color(game.current))

    def scenario_line():
        map_info = (data or {}).get('map') or {}
        paper = str(map_info.get('paper') or '?').upper()
        game = state['game']
        parts = []
        if game is not None:
            parts.append(turn_text() + ' 行动')
            if game.mode:
                parts.append('模式 %s' % game.mode)
        parts.append('%s · %s · %d 列 · 地形 %d · 格边 %d · 单位 %d'
                     % (view.name, '自定义' if paper == 'CUSTOM' else paper,
                        int(map_info.get('cols') or 0), len(view.terrain_cells),
                        len(view.edge_items), len(view.units)))
        return '　|　'.join(parts)

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
            game = state['game']
            head = ''
            if game is not None:
                head = ('当前：第 %d 回合 · %s 行动（该方单位 %d 个）\n'
                        '点“下一回合”换对方行动；对方单位在地图上显示为半透明。\n\n'
                        % (game.number, game.current, game.unit_count()))
            details.Text = (head +
                            '点自己方的单位选中它 → 地图上高亮的格子就是它这回合\n'
                            '能走到的地方（数字是消耗的移动力），点一下就走过去。\n'
                            '移动力用完的单位会变淡，点“下一回合”后恢复。\n\n'
                            '滚轮缩放（以光标为中心）\n'
                            'WASD / 方向键平移\n'
                            'Shift+滚轮左右平移\n'
                            '按住左键拖动平移\n'
                            'Esc 取消选中\n'
                            'Ctrl+S 保存存档　Ctrl+Shift+S 另存为')
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
        game = state['game']
        details.Text = unit_details(unit, cell, terrain, len(units), index,
                                    unit_stats(unit.get('type')),
                                    game.current if game is not None else None)
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
        modifiers = Control.ModifierKeys
        if (modifiers & Keys.Control) == Keys.Control and key == Keys.S:
            save_game(as_new=(modifiers & Keys.Shift) == Keys.Shift)
            event.Handled = True
            return
        if key == Keys.Escape:
            view.select_cell(None)               # 取消选中 / 结束这次的移动
            event.Handled = True
            return
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

    next_turn_button = _bar_button('下一回合', 96)
    save_button = _bar_button('保存', 72)
    save_as_button = _bar_button('另存为', 80)
    for button in (fit_button, zoom_in, zoom_out,
                   next_turn_button, save_button, save_as_button):
        top.Controls.Add(button)

    def layout_top():
        """顶栏摆位：左边是回合控制，右边是视图控制，窗口变窄也不会重叠。"""
        right = top.ClientSize.Width - 14 - zoom_label.Width
        zoom_label.Location = Point(max(0, right), 20)
        x = right - 12
        for button in reversed((fit_button, zoom_in, zoom_out)):
            x -= button.Width
            button.Location = Point(max(0, x), 10)
            x -= 8
        x = 220
        for button in (next_turn_button, save_button, save_as_button):
            button.Location = Point(x, 10)
            x += button.Width + 8

    top.Resize += lambda sender, event: layout_top()
    layout_top()

    def update_game_state():
        """回合换手后统一刷新：顶栏标签、地图半透明、选中状态与状态栏。"""
        game = state['game']
        view.active_faction = game.current if game is not None else None
        update_turn_label()
        view.clear_selection()
        refresh_selection(None, [], 0)
        view.render()

    def move_selected(unit, cell, cost):
        """把选中的单位走到目标格；只有当前行动方的单位能移动。"""
        game = state['game']
        if game is None or not unit_can_move(unit, game.current):
            status.Text = '现在不是这支部队的回合，不能移动它。'
            return False
        left = apply_unit_move(view, unit, cell, cost)
        view.stacks = group_units(view.units)          # 单位换了格子，重新分组
        group = view.stacks.get(cell) or []
        if unit in group:
            unit['stack'] = group.index(unit)          # 同一格里的序号也跟着更新
        view.select_cell(cell, group.index(unit) if unit in group else 0)
        status.Text = '%s　|　%s 走到 (%d,%d)，消耗 %d，剩余移动力 %d' % (
            scenario_line(), unit.get('name') or unit.get('type') or '单位',
            int(cell[0]), int(cell[1]), int(cost), left)
        return True

    def advance_turn():
        """结束当前方的回合，换对方行动；两方都走完就进入下一回合。"""
        game = state['game']
        if game is None:
            return
        game.advance()
        reset_unit_moves(view.units, game.current)     # 换手后新行动方的移动力补满
        update_game_state()
        status.Text = '%s　|　轮到 %s 行动（该方单位 %d 个，移动力已恢复）' % (
            scenario_line(), game.current, game.unit_count())

    def save_game(as_new=False):
        """保存热座存档（.hotseat）：场上地图 + 单位 + 回合状态，存到 saves 目录。"""
        game = state['game']
        if game is None:
            show_error('还没有打开剧本，无法保存。', form)
            return
        path = None if as_new else state['save_path']
        if not path:
            folder = project_saves_dir()
            if folder is None:
                show_error('创建存档目录失败：\n\n%s'
                           % os.path.join(project_dir(), SAVES_DIR_NAME), form)
                return
            target = os.path.abspath(os.path.join(folder, hotseat_file_name(view, game)))
            saved_before = (state['save_path'] and
                            os.path.abspath(state['save_path']) == target)
            # 覆盖别人的存档前先让用户自己选文件名，避免误伤
            if as_new or (os.path.isfile(target) and not saved_before):
                dlg = SaveFileDialog()
                dlg.Title = '保存热座存档'
                dlg.Filter = HOTSEAT_FILE_FILTER
                dlg.InitialDirectory = folder
                dlg.FileName = os.path.basename(target)
                if dlg.ShowDialog(form) != DialogResult.OK:
                    return
                path = dlg.FileName
            else:
                path = target
        path = os.path.abspath(path)
        ok, reason = save_hotseat(path, view, game)
        if not ok:
            show_error('保存存档失败：\n\n%s\n（%s）' % (path, reason), form)
            return
        state['save_path'] = path
        game.path = path
        status.Text = '已保存存档 %s　|　%s 行动　|　模式 %s' % (
            os.path.basename(path), turn_text(), game.mode or '—')

    next_turn_button.Click += lambda sender, event: advance_turn()
    save_button.Click += lambda sender, event: save_game()
    save_as_button.Click += lambda sender, event: save_game(as_new=True)

    if data is not None:
        try:
            view.load(data, scenario_path)
            ensure_unit_moves(view.units)          # 老存档没有 move_left 的补满
            turn_block = data.get('turn') if isinstance(data.get('turn'), dict) else {}
            game = HotseatGame(view.units, turn_block, mode or turn_block.get('mode'))
            if scenario_path:
                is_hotseat = str(scenario_path).lower().endswith(HOTSEAT_SUFFIX)
                if is_hotseat:
                    # 已经打开的存档：保存直接写回它自己
                    state['save_path'] = os.path.abspath(scenario_path)
                else:
                    game.source_scenario = os.path.abspath(scenario_path)
            state['game'] = game
            # 两边都有单位时才需要把非行动方画成半透明
            view.dim_inactive = len({faction_key(unit.get('faction'))
                                     for unit in view.units}) >= 2
            view.active_faction = game.current
            title.Text = view.name
            form.Text = '%s - %s' % (view.name, WINDOW_TITLE)
            update_turn_label()
            refresh_selection(None, [], 0)
            view.render()
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
    form.game_state = state                      # 回合状态与存档路径
    form.advance_turn = advance_turn             # 和顶栏“下一回合”同一个函数
    form.save_game = save_game                   # 和顶栏“保存 / 另存为”同一个函数
    return form


def open_game_window(owner, scenario_path=None, mode=None):
    """打开游戏窗口（剧本列表点卡片调用；mode 由列表上的模式选择传来）。"""
    form = build_game_window(owner, scenario_path, mode)
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
                if name.lower().endswith(('.scenario', HOTSEAT_SUFFIX)):
                    open_game_window(None, os.path.join(folder, name))
                    return
        show_error('没有找到 .scenario 剧本 / .hotseat 存档。')

    thread = Thread(ThreadStart(run))
    thread.SetApartmentState(ApartmentState.STA)
    thread.Start()
    thread.Join()
    return 0


if __name__ == '__main__':
    sys.exit(main())
