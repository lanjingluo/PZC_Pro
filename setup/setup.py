"""初设窗口（Python + WinForms）：剧本编辑（地图 + 编制 + 部队部署）。

运行方式：命令行执行 python setup.py（在 setup 目录里双击也可以）
窗口打开先是“剧本”起始页，两个按钮：
    新建剧本 → 先打开 .hex 画布（Hex_Editor 的解析逻辑），画在地图画布上，
               紧接着弹“打开 .oob 军队编制”（Units/oob.py 的编制树），
               并顺带做一次单位类型检查。
    导入剧本 → 打开已有的 .scenario，把地图每个格子的地形、格边地形、
               编制树快照和每个单位的部署位置全部还原，可以继续修改。

左上角“剧本选择”可以随时回到起始页。

地图缩放：滚轮（含鼠标左右倾轮）只用来缩放，以光标位置为锚点；
工具条的“缩小/放大/适应窗口”按钮同一套缩放逻辑，适应窗口＝整幅居中。
地图平移：按住 WASD 或方向键，或者把鼠标移到地图区域边缘（越靠边越快）。

左侧栏是编制树（可视化 OOB），部署流程：
    在左侧点一个单位 → 点地图上的格子 → 该格子出现一个北约军标（APP-6 风格：
    方框 + 兵种符号 + 级别标记 + 类型/数量标注，框色按阵营区分）。
一个格子可以堆多个单位（暂时不限数量），格子里的军标会自动排成小网格。

点没有放单位的格子＝选中该格里的**全部**单位（右侧栏列出它们）；
右侧栏可以逐条勾选/取消，只对其中一部分做操作：
    「移除选中 (Del)」删除勾选的单位，
    「移动选中到…」再点目标格子＝把勾选的单位整体搬过去，
    「全选」/「取消勾选」批量调整。
Esc（或“取消放置”）＝退出放置/移动状态。部署过的节点在树里带 ● 前缀，
鼠标扫过格子时状态栏显示最上面那个单位的信息。

改完可以保存成 .scenario 初设文件（左侧栏“保存 .scenario”/“另存为 .scenario...”）：
里面记录纸张/格子数/每个格子的地形/每条格边的地形 + 每个单位所在的格子坐标，
以及一份编制树快照，是纯数据（不是图片），供游戏导入初设时直接读取。

地图几何（hexformat.hex_layout）和配色（hexmap 里的地形表）都直接复用 Hex_Editor 的模块，
所以这里画出来的效果和 Hex Editor 打开同一个文件时一致。

界面背景图：basic_picture_resources/background2.jpg（每次打开窗口都从磁盘读，换图不用重新打包）
"""
import importlib.util
import json
import math
import os
import sys

try:
    import clr
except ImportError:
    import ctypes

    ctypes.windll.user32.MessageBoxW(
        0,
        '缺少依赖 pythonnet，程序无法启动。\n\n请在命令行执行：\n    python -m pip install pythonnet',
        '初设 - 缺少依赖',
        0x10,
    )
    raise SystemExit(1)

clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from System import EventHandler
from System.Drawing import (
    Bitmap,
    Color,
    ContentAlignment,
    Font,
    FontStyle,
    Pen,
    Point,
    PointF,
    Rectangle,
    RectangleF,
    Size,
    SolidBrush,
)
from System.Drawing.Drawing2D import GraphicsPath, LineCap, LineJoin, SmoothingMode
from System.Threading import ApartmentState, Thread, ThreadStart
from System.Windows.Forms import (
    Application,
    BorderStyle,
    Button,
    CheckState,
    CheckedListBox,
    Control,
    DialogResult,
    DockStyle,
    FlatStyle,
    Form,
    FormStartPosition,
    Keys,
    Label,
    MessageBox,
    MessageBoxButtons,
    MessageBoxIcon,
    MouseButtons,
    OpenFileDialog,
    Padding,
    Panel,
    PictureBox,
    PictureBoxSizeMode,
    SaveFileDialog,
    Splitter,
    StatusStrip,
    Timer,
    ToolStripStatusLabel,
    TreeNode,
    TreeView,
)

WINDOW_TITLE = '初设'
WINDOW_SIZE = Size(1240, 780)
MINIMUM_SIZE = Size(820, 520)

BACKGROUND_MODULE = 'ui_background'
BACKGROUND_RELATIVE_PATH = os.path.join('basic_picture_resources', 'background2.jpg')
FALLBACK_BACK_COLOR = Color.FromArgb(32, 34, 38)

# 地图渲染参数：与 Hex_Editor/main.py 保持一致
GRID_PEN_WIDTH = 2.0
EDGE_PEN_WIDTH = 6.0
MIN_ZOOM = 0.1
MAX_ZOOM = 8.0
ZOOM_STEP = 1.25
# WinForms/GDI+ 对超大控件支持有限（超过这个尺寸容易出现绘制错误），画布框住上限
MAX_CANVAS_PIXELS = 16000

# 军队编制文件（与 Units/units_editor.py 保持一致）
OOB_FILE_FILTER = '军队编制文件 (*.oob)|*.oob|所有文件 (*.*)|*.*'

# 军标宽高比（宽 / 高）
SYMBOL_RATIO = 1.4

# 平移（WASD / 方向键、横向滚轮、鼠标贴边）
PAN_TICK_MS = 30            # 平移定时器周期
PAN_KEY_STEP = 17           # 按住按键时每个周期平移的像素
EDGE_PAN_BAND = 26          # 鼠标进入视口边缘多少像素内开始平移
EDGE_PAN_MAX_SPEED = 23     # 贴住边缘时每个周期的平移像素
PAN_KEYS = {
    'W': (0, -1), 'S': (0, 1), 'A': (-1, 0), 'D': (1, 0),
    'Up': (0, -1), 'Down': (0, 1), 'Left': (-1, 0), 'Right': (1, 0),
}
WM_MOUSEHWHEEL = 0x020E

# 初设文件（.scenario）：地图每个格子的情况 + 单位部署位置
SCENARIO_TYPE = 'SCENARIO'
SCENARIO_VERSION = 1
SCENARIO_FILE_FILTER = '初设文件 (*.scenario)|*.scenario|所有文件 (*.*)|*.*'

# 左侧编制栏
PANEL_WIDTH = 250
PANEL_BACK_COLOR = Color.FromArgb(38, 41, 46)
SELECT_PANEL_WIDTH = 250
SELECT_BACK_COLOR = Color.FromArgb(44, 47, 53)
MIN_PANEL_WIDTH = 140       # 窗口变窄时左右栏能缩到的最小宽度
PANEL_SHARE = 0.25          # 左右栏最多各占窗口宽度的这个比例
SPLITTER_WIDTH = 8          # 左右栏分隔条宽度（拖它调栏宽）
SPLITTER_COLOR = Color.FromArgb(96, 102, 112)
MIN_MAP_WIDTH = 200         # 拖栏时给地图留的最小宽度

# 左右栏的显示状态 / 宽度记在这里，下次启动沿用
UI_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'setup_ui.json')
PANEL_TEXT_COLOR = Color.FromArgb(235, 235, 235)
PANEL_HINT_COLOR = Color.FromArgb(165, 165, 165)

# 北约军标：编制级别写在方框上方（• 班/排，I 连，II 营，III 团，X 旅，XX 师，XXX 军，XXXX 集团军）
LEVEL_MARKS = {
    '班': '•', '排': '••', '连': 'I', '营': 'II', '团': 'III',
    '旅': 'X', '师': 'XX', '军': 'XXX', '集团军': 'XXXX',
}
# 阵营配色（军标框颜色）：名字里带颜色字就按字面取色，否则按名字稳定散列
FACTION_COLORS = {
    '红': (198, 60, 60), '蓝': (58, 110, 200), '绿': (66, 145, 86),
    '黄': (188, 148, 40), '白': (140, 140, 140), '黑': (70, 70, 70),
}
FACTION_PALETTE = ((198, 60, 60), (58, 110, 200), (66, 145, 86),
                   (188, 148, 40), (140, 100, 190), (120, 120, 120))


def project_dir():
    """项目根目录：本文件在 setup/ 子目录里，所以要从上一级找。

    打包成 exe 后游戏文件（含 Hex_Editor、basic_picture_resources、ui_background.py）
    在 exe 所在目录，开发时则在 setup 的上一级目录。
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))

    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    if os.path.isdir(os.path.join(parent, 'basic_picture_resources')):
        return parent
    return here


def hex_editor_dir():
    """Hex_Editor 目录（.hex 解析与地图几何都在那里）。"""
    return os.path.join(project_dir(), 'Hex_Editor')


def units_dir():
    """Units 目录（Units.py 单位模型、oob.py 军队编制、database.py 单位数据都在那里）。"""
    return os.path.join(project_dir(), 'Units')


# hexmap.py 里写的是 `from hexformat import ...`，所以 Hex_Editor 得先进 sys.path
_HEX_EDITOR_DIR = hex_editor_dir()
if os.path.isdir(_HEX_EDITOR_DIR) and _HEX_EDITOR_DIR not in sys.path:
    sys.path.insert(0, _HEX_EDITOR_DIR)

# Units.py 是纯逻辑模块，放进 sys.path 就能 import
_UNITS_DIR = units_dir()
if os.path.isdir(_UNITS_DIR) and _UNITS_DIR not in sys.path:
    sys.path.insert(0, _UNITS_DIR)

try:
    from hexformat import map_canvas_size, parse_hex_map_payload, read_hex_container
    from hexmap import (
        EDGE_TERRAINS,
        TERRAINS,
        HexMap,
        edge_terrain_color,
        normalize_margins,
        terrain_color,
    )

    HEX_IMPORT_ERROR = None
except Exception as _exc:            # 缺文件 / 语法错误都不该让窗口本身打不开
    HEX_IMPORT_ERROR = '%s: %s' % (type(_exc).__name__, _exc)

try:
    import oob                      # 军队编制（.oob）：编制树 + load_file/save_file/summary/check

    OOB_IMPORT_ERROR = None
except Exception as _exc:
    OOB_IMPORT_ERROR = '%s: %s' % (type(_exc).__name__, _exc)


def load_local_module(name):
    """从项目根目录读取并执行 <name>.py，返回模块对象（每次都重新读，改完立刻生效）。"""
    directory = project_dir()
    path = os.path.join(directory, name + '.py')
    if not os.path.isfile(path):
        raise FileNotFoundError('找不到 %s.py：%s' % (name, path))
    if directory not in sys.path:
        sys.path.insert(0, directory)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def show_error(message, title='初设 - 出错'):
    MessageBox.Show(message, title, MessageBoxButtons.OK, MessageBoxIcon.Error)


def apply_background(form):
    """给窗口铺界面背景图；出错只提示，不影响窗口打开。"""
    path = os.path.join(project_dir(), BACKGROUND_RELATIVE_PATH)
    try:
        module = load_local_module(BACKGROUND_MODULE)
    except Exception as exc:
        form.BackColor = FALLBACK_BACK_COLOR
        show_error('加载 %s.py 失败：\n\n%s: %s' % (BACKGROUND_MODULE, type(exc).__name__, exc))
        return

    reason = module.apply(form, path, FALLBACK_BACK_COLOR)
    if reason is not None:
        show_error(
            '界面背景图加载失败：\n\n%s\n（%s）\n\n'
            'GDI+ 只支持 PNG / JPG / BMP / GIF；如果文件其实是 WebP，请先转换格式。\n'
            '窗口会先用纯色背景继续运行。' % (path, reason)
        )


def encode_cell_items(mapping):
    """格子地形表的键统一成 "列,行" 字符串（HexMap 导出的键是 (q, r) 元组）。"""
    out = {}
    for key, value in (mapping or {}).items():
        if isinstance(key, str):
            out[key] = value
        else:
            out['%d,%d' % (int(key[0]), int(key[1]))] = value
    return out


def decode_payload_text(payload):
    """负载转文本：UTF-8（带不带 BOM 都行），不行再退回 GBK。"""
    for encoding in ('utf-8-sig', 'gbk'):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode('utf-8', errors='replace')


def _payload_cell_key(key):
    try:
        parts = str(key).split(',')
        return (int(parts[0]), int(parts[1]))
    except Exception:
        return None


def _payload_edge_key(key):
    text = str(key)
    return text if '|' in text else None


def decode_terrain_items(source, key_parser):
    """把 {键: 名字 或 [名字, 消耗, 修正]} 解成 {(列,行): 名字 或 (名字, 消耗, 修正)}。"""
    out = {}
    for key, value in (source or {}).items():
        parsed = key_parser(key)
        if parsed is None:
            continue
        if isinstance(value, (list, tuple)):
            name = str(value[0]) if len(value) > 0 and value[0] else ''
            if not name:
                continue
            cost = value[1] if len(value) > 1 else None
            modifier = value[2] if len(value) > 2 else None
            out[parsed] = (name,
                           None if cost is None else int(cost),
                           None if modifier is None else int(modifier))
        elif value:
            out[parsed] = str(value)
    return out


def parse_map_doc(payload):
    """解析画布文档：先走 Hex_Editor 的正规解析，不通过再用宽松解析兜底。

    宽松解析能多认几种真实情况：负载其实是导出的 JSON（没有 HEX1 头）、
    JSON 带 BOM 或是 GBK 编码、版本号比现在新、paper 缺失/不是 A1-A4。
    """
    doc = parse_hex_map_payload(payload)
    if doc is not None:
        return doc

    try:
        data = json.loads(decode_payload_text(payload).lstrip('\ufeff'))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    try:
        cols = int(data.get('cols') or 0)
    except (TypeError, ValueError):
        return None
    if cols < 1:
        return None

    width = data.get('width')
    height = data.get('height')
    paper = str(data.get('paper') or '').upper()
    if paper == 'CUSTOM' and not (width and height):
        return None
    if paper not in ('A1', 'A2', 'A3', 'A4', 'CUSTOM'):
        paper = 'CUSTOM' if (width and height) else 'A4'

    margins = {}
    for key in ('l', 't', 'r', 'b'):
        raw = (data.get('margins') or {}).get(key)
        if raw is None:
            continue
        try:
            margins[key] = int(raw)
        except (TypeError, ValueError):
            pass

    return {
        'paper': paper,
        'cols': cols,
        'width': width,
        'height': height,
        'margins': margins,
        'terrains': decode_terrain_items(data.get('cells'), _payload_cell_key),
        'edges': decode_terrain_items(data.get('edges'), _payload_edge_key),
    }


def faction_color(faction):
    """阵营 → RGB：名字里有“红/蓝/绿…”就按字面取色，否则按名字稳定散列。"""
    text = str(faction or '')
    for key, rgb in FACTION_COLORS.items():
        if key in text:
            return rgb
    if not text:
        return FACTION_PALETTE[-1]
    total = sum(ord(ch) for ch in text)
    return FACTION_PALETTE[total % len(FACTION_PALETTE)]


def draw_nato_glyph(g, rect, branch, pen):
    """在军标方框里画兵种符号（APP-6 风格）。

    步兵=交叉线，装甲=椭圆，炮兵=实心圆，反坦克=上尖角，防空=向上箭头，
    骑兵=斜线，侦察=斜线加观测点，工兵=梳形 E，通信=闪电，后勤=三道横线，
    指挥部=旗，航空=机翼；没有兵种（比如纯指挥架子单位）就只留空框。
    """
    left, top = rect.Left, rect.Top
    w, h = rect.Width, rect.Height
    x1, x2 = left + w * 0.24, left + w * 0.76
    y1, y2 = top + h * 0.24, top + h * 0.76
    cx, cy = left + w / 2.0, top + h / 2.0

    if branch == '步兵':
        g.DrawLine(pen, x1, y1, x2, y2)
        g.DrawLine(pen, x1, y2, x2, y1)
    elif branch == '装甲':
        g.DrawEllipse(pen, left + w * 0.20, top + h * 0.28, w * 0.60, h * 0.44)
    elif branch == '骑兵':
        g.DrawLine(pen, x1, y2, x2, y1)
    elif branch == '炮兵':
        brush = SolidBrush(pen.Color)
        g.FillEllipse(brush, cx - w * 0.11, cy - h * 0.16, w * 0.22, h * 0.32)
        brush.Dispose()
    elif branch == '反坦克':
        g.DrawLine(pen, x1, y2, cx, y1)
        g.DrawLine(pen, cx, y1, x2, y2)
    elif branch == '防空':
        g.DrawLine(pen, cx, y2, cx, y1)
        g.DrawLine(pen, cx, y1, cx - w * 0.10, y1 + h * 0.16)
        g.DrawLine(pen, cx, y1, cx + w * 0.10, y1 + h * 0.16)
    elif branch == '侦察':
        g.DrawLine(pen, x1, y2, x2, y1)
        brush = SolidBrush(pen.Color)
        g.FillEllipse(brush, x2 - w * 0.14, y1 - h * 0.12, w * 0.14, h * 0.20)
        brush.Dispose()
    elif branch == '工兵':
        g.DrawLine(pen, x1, y1, x1, y2)
        for y in (y1, cy, y2):
            g.DrawLine(pen, x1, y, x2, y)
    elif branch == '通信':
        g.DrawLines(pen, [PointF(x2, y1), PointF(cx + w * 0.04, cy),
                          PointF(cx - w * 0.04, cy), PointF(x1, y2)])
    elif branch == '后勤':
        for y in (y1, cy, y2):
            g.DrawLine(pen, x1, y, x2, y)
    elif branch == '指挥部':
        flag_x = left + w * 0.32
        g.DrawLine(pen, flag_x, y1, flag_x, y2)
        g.DrawLine(pen, flag_x, y1, flag_x + w * 0.24, y1 + h * 0.10)
        g.DrawLine(pen, flag_x + w * 0.24, y1 + h * 0.10, flag_x, y1 + h * 0.20)
    elif branch == '航空':
        g.DrawLine(pen, cx, y1, cx, y2)
        g.DrawLine(pen, x1, cy + h * 0.06, cx, cy - h * 0.14)
        g.DrawLine(pen, cx, cy - h * 0.14, x2, cy + h * 0.06)


class PanPictureBox(PictureBox):
    """带横向滚轮回调的画布控件。

    .NET 的 MouseWheel 只报纵向，鼠标的左右倾轮是 WM_MOUSEHWHEEL 消息，
    要拦 WndProc 才能拿到。
    """

    def __init__(self):
        PictureBox.__init__(self)
        self.horizontal_wheel = None      # 回调(delta)：delta 是 120 的整数倍

    def WndProc(self, message):
        if message.Msg == WM_MOUSEHWHEEL and self.horizontal_wheel is not None:
            value = message.WParam.ToInt64() & 0xFFFFFFFF
            delta = (value >> 16) & 0xFFFF
            if delta >= 0x8000:
                delta -= 0x10000
            self.horizontal_wheel(delta)
            return
        PictureBox.WndProc(self, message)


class SetupWindow:
    """初设窗口：顶部工具条 + 地图画布 + 底部状态栏。"""

    def __init__(self):
        # 地图状态
        self.file_path = None
        self.map_paper = 'A4'
        self.map_cols = 1
        self.map_width = None
        self.map_height = None
        self.map_margins = {}
        self.map_size = None            # (宽, 高) 画布像素尺寸
        self.hex_map = None
        self.zoom = 1.0
        self.auto_fit = True            # 缩放是否跟随窗口大小自动适配
        self._cell_paths = {}           # 格子地形名 -> 路径
        self._edge_paths = {}           # 格边地形名 -> 路径
        # 军队编制（.oob）
        self.oob_path = None
        self.oob_summary = None
        self.source_hex_name = None      # 初设是照着哪个 .hex 做的（只作记录）
        self.selected_records = []       # 右侧栏里勾选的单位（可以只勾一格里的部分）
        self.selection_cell = None       # 当前选中的格子 (q, r)
        self.cell_records = []           # 该格子里的全部单位（与右侧列表一一对应）
        self.move_mode = False           # “移动选中到…”状态
        self._filling_selection = False   # 正在重建右侧列表，忽略 ItemCheck
        self._pan_keys = set()            # 按住的平移键（WASD / 方向键）
        self._edge_pan = (0, 0)           # 鼠标贴边产生的平移向量
        self._side_buttons = []           # 左栏按钮（随栏宽缩放）
        self._select_buttons = []         # 右栏按钮
        self._canvas_base = (0, 0)        # 画布在容器里的基位（未滚动时的位置）
        self._panel_manual = False        # 用户拖过分隔条后，宽度不再自动变
        self._side_open = True            # 左栏是否打开（用户可关）
        self._select_open = True          # 右栏是否打开
        self.selected_node = None        # 左侧编制树里选中的节点（选中即可往地图上放）
        self.deployments = []            # 已部署单位：[{'node':..., 'path':[...], 'q':..., 'r':...}]
        self.scenario_path = None
        self._base_status = ''           # 鼠标移到单位格子上时，用来恢复状态栏

        # 军标用的字体（固定字号，不跟缩放走，保证可读）
        self.mark_font = Font('Microsoft YaHei UI', 8, FontStyle.Bold)
        self.name_font = Font('Microsoft YaHei UI', 7)

        # 缩放/改变大小时先攒一下再重绘，避免卡顿（和 Hex Editor 一样 120ms）
        self._render_timer = Timer()
        self._render_timer.Interval = 120
        self._render_timer.Tick += self.on_render_timer_tick

        # 平移定时器：键盘按住、鼠标贴边都靠它连续走动
        self._pan_timer = Timer()
        self._pan_timer.Interval = PAN_TICK_MS
        self._pan_timer.Tick += self.on_pan_timer_tick

        self.form = Form()
        self.form.Text = WINDOW_TITLE
        self.form.ClientSize = WINDOW_SIZE
        self.form.StartPosition = FormStartPosition.CenterScreen
        self.fit_window_to_screen()      # 屏幕不够大就缩小，别让左右跑到屏幕外
        self.form.Font = Font('Microsoft YaHei UI', 9)
        apply_background(self.form)

        self._build_canvas()        # Fill 的先加，下面的工具条/状态栏才不会被盖住
        self._build_oob_panel()     # 左侧栏：编制树 + 部署操作
        self._build_select_panel()  # 右侧栏：选中单位列表
        self._build_toolbar()
        self._build_status_bar()
        self._build_hint()
        self._build_start_view()    # 起始页（最后加，盖在最上面）

        self.form.Resize += self.on_form_resize
        self.form.Shown += self.on_form_shown_fit
        self.form.FormClosed += self.on_form_closed
        self.form.KeyPreview = True                 # Delete / Esc 快捷键
        self.form.KeyDown += self.on_form_key_down
        self.form.KeyUp += self.on_form_key_up
        self.load_ui_state()                        # 沿用上次的栏开关与宽度
        self.update_panel_layout()                  # 左右栏按窗口宽度定宽
        self.update_toggle_labels()
        self.enter_start_mode()

    # ---------- 界面构建 ----------
    def fit_window_to_screen(self, control=None):
        """窗口尺寸按屏幕工作区收缩。

        StartPosition=CenterScreen 时如果窗口比屏幕还宽，窗口会被推到左边界以外——
        表现就是“左边（左侧编制栏）看不到、也居中不了”。所以先按工作区留出边距。
        """
        try:
            from System.Windows.Forms import Screen
            screen = Screen.FromControl(control) if control is not None else Screen.FromPoint(Control.MousePosition)
            area = screen.WorkingArea
        except Exception:
            try:
                from System.Windows.Forms import Screen
                area = Screen.PrimaryScreen.WorkingArea
            except Exception:
                return
        margin = 48
        # 屏幕特别小 / 显示缩放特别大时，宁可窗口比默认值小，也不要超出屏幕
        width = min(WINDOW_SIZE.Width, max(320, area.Width - margin))
        height = min(WINDOW_SIZE.Height, max(240, area.Height - margin))
        self.form.ClientSize = Size(width, height)
        # MinimumSize 是外框尺寸，不能比当前窗口还大，否则会被强行撑回去
        self.form.MinimumSize = Size(min(MINIMUM_SIZE.Width, self.form.Width),
                                     min(MINIMUM_SIZE.Height, self.form.Height))
        # 上限定在工作区：拖边框、双击标题栏最大化都不会超出屏幕
        self.form.MaximumSize = Size(max(self.form.Width, area.Width),
                                     max(self.form.Height, area.Height))

    def on_form_shown_fit(self, sender, e):
        """窗口真正显示后再按它所在的那块显示器校正一次（多显示器 / 缩放不一致时保险）。"""
        self.fit_window_to_screen(self.form)

    def _build_toolbar(self):
        self.top_bar = Panel()
        self.top_bar.Dock = DockStyle.Top
        self.top_bar.Height = 44
        self.top_bar.BackColor = Color.FromArgb(45, 48, 54)
        self.form.Controls.Add(self.top_bar)

        self._make_toolbar_button('剧本选择', 10, 76, self.on_back_to_start_click)
        self.side_toggle_button = self._make_toolbar_button('隐藏左栏', 92, 76, self.on_toggle_side_click)
        self.select_toggle_button = self._make_toolbar_button('隐藏右栏', 174, 76, self.on_toggle_select_click)
        self.focus_button = self._make_toolbar_button('专注', 256, 84, self.on_focus_map_click)
        self._make_toolbar_button('自检', 346, 48, self.on_selfcheck_click)
        self.open_button = self._make_toolbar_button('打开 .hex 文件...', 400, 136, self.on_open_click)
        self.oob_button = self._make_toolbar_button('打开 .oob 编制...', 542, 136, self.on_open_oob_click)
        self._make_toolbar_button('缩小', 684, 44, self.on_zoom_out)
        self._make_toolbar_button('放大', 734, 44, self.on_zoom_in)
        self._make_toolbar_button('适应窗口', 784, 84, self.on_zoom_fit)

        self.zoom_label = Label()
        self.zoom_label.Text = '100%'
        self.zoom_label.ForeColor = Color.White
        self.zoom_label.Location = Point(876, 14)
        self.zoom_label.AutoSize = True
        self.top_bar.Controls.Add(self.zoom_label)

        self.file_label = Label()
        self.file_label.Text = '（还没有打开文件）'
        self.file_label.ForeColor = Color.FromArgb(210, 210, 210)
        self.file_label.Location = Point(944, 14)
        self.file_label.AutoSize = True
        self.top_bar.Controls.Add(self.file_label)

    def _make_toolbar_button(self, text, x, width, handler):
        button = Button()
        button.Text = text
        button.Location = Point(x, 8)
        button.Size = Size(width, 28)
        button.FlatStyle = FlatStyle.System
        button.Click += handler
        self.top_bar.Controls.Add(button)
        return button

    def _build_canvas(self):
        self.canvas_scroll = Panel()
        self.canvas_scroll.Dock = DockStyle.Fill
        self.canvas_scroll.AutoScroll = True
        self.canvas_scroll.BackColor = Color.White
        self.canvas_scroll.Visible = False          # 还没打开地图时露出窗口背景图
        self.canvas_scroll.Resize += self.on_canvas_resize

        self.canvas_box = PanPictureBox()
        self.canvas_box.SizeMode = PictureBoxSizeMode.Normal
        self.canvas_box.BackColor = Color.White
        self.canvas_box.Location = Point(0, 0)
        self.canvas_box.Size = Size(1, 1)
        self.canvas_box.Paint += self.on_canvas_paint
        self.canvas_box.MouseWheel += self.on_canvas_mouse_wheel
        self.canvas_box.MouseDown += self.on_canvas_mouse_down
        self.canvas_box.MouseMove += self.on_canvas_mouse_move
        self.canvas_box.MouseLeave += self.on_canvas_mouse_leave
        self.canvas_box.horizontal_wheel = self.on_horizontal_wheel
        self.canvas_scroll.Controls.Add(self.canvas_box)
        self.form.Controls.Add(self.canvas_scroll)

    def _build_oob_panel(self):
        """左侧栏：编制树（可视化 OOB）+ 部署操作按钮。"""
        self.side_panel = Panel()
        self.side_panel.Dock = DockStyle.Left
        self.side_panel.Width = PANEL_WIDTH
        self.side_panel.MinimumSize = Size(MIN_PANEL_WIDTH, 0)
        self.side_panel.BackColor = PANEL_BACK_COLOR

        # Dock 顺序：Fill 先加、Top/Bottom 后加，否则后加的标题会压在内容上
        self.oob_tree = TreeView()
        self.oob_tree.Dock = DockStyle.Fill
        self.oob_tree.BorderStyle = getattr(BorderStyle, 'None')   # None 是 Python 关键字，只能这样取
        self.oob_tree.BackColor = Color.FromArgb(50, 54, 60)
        self.oob_tree.ForeColor = PANEL_TEXT_COLOR
        self.oob_tree.HideSelection = False
        self.oob_tree.AfterSelect += self.on_oob_tree_select
        self.side_panel.Controls.Add(self.oob_tree)

        self._make_panel_header(self.side_panel, '军队编制（OOB）', self.on_toggle_side_click)

        actions = Panel()
        actions.Dock = DockStyle.Bottom
        actions.Height = 172
        actions.BackColor = PANEL_BACK_COLOR
        self.side_panel.Controls.Add(actions)

        self.sel_label = Label()
        self.sel_label.ForeColor = PANEL_TEXT_COLOR
        self.sel_label.Dock = DockStyle.Top
        self.sel_label.Height = 44
        self.sel_label.Padding = Padding(8, 2, 6, 0)
        actions.Controls.Add(self.sel_label)

        self.disarm_button = self._make_panel_button(actions, '取消放置 (Esc)', self.on_disarm_click, 48)
        self.clear_button = self._make_panel_button(actions, '清空全部部署', self.on_clear_click, 78)
        self.save_button = self._make_panel_button(actions, '保存 .scenario', self.on_save_scenario_click, 108)
        self.save_as_button = self._make_panel_button(actions, '另存为 .scenario...', self.on_save_as_scenario_click, 138)

        self._side_buttons = [self.disarm_button, self.clear_button,
                              self.save_button, self.save_as_button]

        # 分隔条：拖着调整左栏宽度（要在左栏之前加，Dock 顺序才对）
        self.side_splitter = Splitter()
        self.side_splitter.Dock = DockStyle.Left
        self.side_splitter.Width = SPLITTER_WIDTH
        self.side_splitter.BackColor = SPLITTER_COLOR
        self.side_splitter.MinSize = MIN_PANEL_WIDTH      # 栏本身最小宽度
        self.side_splitter.MinExtra = MIN_MAP_WIDTH       # 另一侧（地图）最少留多少
        self.side_splitter.SplitterMoved += self.on_splitter_moved
        self.side_splitter.Paint += self.on_splitter_paint
        self.side_splitter.DoubleClick += lambda sender, e: self.on_toggle_side_click()
        self.form.Controls.Add(self.side_splitter)
        self.form.Controls.Add(self.side_panel)
        self.refresh_oob_tree()
        self.update_sel_label()

    def _make_panel_button(self, parent, text, handler, y, panel_width=PANEL_WIDTH):
        button = Button()
        button.Text = text
        button.Location = Point(8, y)
        button.Size = Size(panel_width - 18, 26)
        button.FlatStyle = FlatStyle.System
        button.Click += handler
        parent.Controls.Add(button)
        return button

    def _make_panel_header(self, panel, title, close_handler):
        """栏顶标题条：左边标题、右边一个“×”用来关掉这栏。"""
        header = Panel()
        header.Dock = DockStyle.Top
        header.Height = 26
        header.BackColor = PANEL_BACK_COLOR

        title_label = Label()
        title_label.Text = title
        title_label.Font = Font('Microsoft YaHei UI', 9.5, FontStyle.Bold)
        title_label.ForeColor = PANEL_TEXT_COLOR
        title_label.Dock = DockStyle.Fill
        title_label.TextAlign = ContentAlignment.MiddleLeft
        title_label.Padding = Padding(8, 0, 0, 0)
        header.Controls.Add(title_label)

        close = Button()
        close.Text = '×'
        close.Dock = DockStyle.Right
        close.Width = 26
        close.FlatStyle = FlatStyle.System
        close.Click += close_handler
        header.Controls.Add(close)

        panel.Controls.Add(header)
        return header

    def _build_select_panel(self):
        """右侧栏：列出当前选中格子里的单位，可逐条勾选/取消。"""
        self.select_panel = Panel()
        self.select_panel.Dock = DockStyle.Right
        self.select_panel.Width = SELECT_PANEL_WIDTH
        self.select_panel.MinimumSize = Size(MIN_PANEL_WIDTH, 0)
        self.select_panel.BackColor = SELECT_BACK_COLOR

        # Dock 顺序：Fill 先加、Top/Bottom 后加（同左栏）
        self.selection_box = CheckedListBox()
        self.selection_box.Dock = DockStyle.Fill
        self.selection_box.CheckOnClick = True
        self.selection_box.BackColor = Color.FromArgb(56, 60, 66)
        self.selection_box.ForeColor = PANEL_TEXT_COLOR
        self.selection_box.BorderStyle = getattr(BorderStyle, 'None')
        self.selection_box.ItemCheck += self.on_selection_item_check
        self.select_panel.Controls.Add(self.selection_box)

        self._make_panel_header(self.select_panel, '选中单位', self.on_toggle_select_click)

        actions = Panel()
        actions.Dock = DockStyle.Bottom
        actions.Height = 178
        actions.BackColor = SELECT_BACK_COLOR
        self.select_panel.Controls.Add(actions)

        self.selection_label = Label()
        self.selection_label.ForeColor = PANEL_TEXT_COLOR
        self.selection_label.Dock = DockStyle.Top
        self.selection_label.Height = 46
        self.selection_label.Padding = Padding(8, 2, 6, 0)
        actions.Controls.Add(self.selection_label)

        self.select_all_button = self._make_panel_button(actions, '全选', self.on_select_all_click, 48, SELECT_PANEL_WIDTH)
        self.select_none_button = self._make_panel_button(actions, '取消勾选', self.on_select_none_click, 78, SELECT_PANEL_WIDTH)
        self.remove_selected_button = self._make_panel_button(actions, '移除选中 (Del)', self.on_remove_click, 108, SELECT_PANEL_WIDTH)
        self.move_selected_button = self._make_panel_button(actions, '移动选中到…', self.on_move_selected_click, 138, SELECT_PANEL_WIDTH)

        self._select_buttons = [self.select_all_button, self.select_none_button,
                                self.remove_selected_button, self.move_selected_button]

        # 右侧分隔条（要在右栏之前加）
        self.select_splitter = Splitter()
        self.select_splitter.Dock = DockStyle.Right
        self.select_splitter.Width = SPLITTER_WIDTH
        self.select_splitter.BackColor = SPLITTER_COLOR
        self.select_splitter.MinSize = MIN_PANEL_WIDTH
        self.select_splitter.MinExtra = MIN_MAP_WIDTH
        self.select_splitter.SplitterMoved += self.on_splitter_moved
        self.select_splitter.Paint += self.on_splitter_paint
        self.select_splitter.DoubleClick += lambda sender, e: self.on_toggle_select_click()
        self.form.Controls.Add(self.select_splitter)
        self.form.Controls.Add(self.select_panel)
        self.update_selection_label()

    def _build_status_bar(self):
        self.status_bar = StatusStrip()
        self.status_label = ToolStripStatusLabel('正在等待打开 .hex 文件...')
        self.status_label.Spring = True                 # 地图信息占满左侧剩余空间
        self.status_label.TextAlign = ContentAlignment.MiddleLeft
        self.oob_label = ToolStripStatusLabel('编制：未载入')
        self.status_bar.Items.Add(self.status_label)
        self.status_bar.Items.Add(self.oob_label)
        self.form.Controls.Add(self.status_bar)

    def _build_hint(self):
        self.hint_label = Label()
        self.hint_label.Text = '还没有打开地图\r\n点“打开 .hex 文件...”选择六角格画布'
        self.hint_label.Font = Font('Microsoft YaHei UI', 12)
        self.hint_label.ForeColor = Color.White
        self.hint_label.BackColor = Color.Transparent
        self.hint_label.TextAlign = ContentAlignment.MiddleCenter
        self.hint_label.AutoSize = True
        self.form.Controls.Add(self.hint_label)
        self.center_hint()

    def _build_start_view(self):
        """起始页：新建剧本 / 导入剧本。"""
        self.start_panel = Panel()
        self.start_panel.Dock = DockStyle.Fill
        self.start_panel.BackColor = Color.Transparent      # 露出窗口背景图

        self.start_title = Label()
        self.start_title.Text = '剧本'
        self.start_title.Font = Font('Microsoft YaHei UI', 20, FontStyle.Bold)
        self.start_title.ForeColor = Color.White
        self.start_title.BackColor = Color.Transparent
        self.start_title.AutoSize = True
        self.start_title.TextAlign = ContentAlignment.MiddleCenter
        self.start_panel.Controls.Add(self.start_title)

        self.new_scenario_button = self._make_start_button('新建剧本', self.on_new_scenario_click)
        self.import_scenario_button = self._make_start_button('导入剧本', self.on_import_scenario_click)
        self.form.Controls.Add(self.start_panel)
        self.center_start_buttons()

    def _make_start_button(self, text, handler):
        button = Button()
        button.Text = text
        button.Size = Size(220, 52)
        button.FlatStyle = FlatStyle.System
        button.Click += handler
        self.start_panel.Controls.Add(button)
        return button

    def center_start_buttons(self):
        """起始页内容居中（标题 + 两个按钮）。"""
        panel = self.start_panel
        buttons = [self.new_scenario_button, self.import_scenario_button]
        gap = 22
        total = sum(b.Height for b in buttons) + gap * (len(buttons) - 1)
        top = max(0, (panel.ClientSize.Height - total) // 2)
        self.start_title.Location = Point(
            max(0, (panel.ClientSize.Width - self.start_title.Width) // 2),
            max(0, top - self.start_title.Height - 18),
        )
        y = top
        for button in buttons:
            button.Location = Point(max(0, (panel.ClientSize.Width - button.Width) // 2), y)
            y += button.Height + gap

    def enter_start_mode(self):
        """回到“剧本”起始页：藏起编辑界面。"""
        self.top_bar.Visible = False
        self.side_panel.Visible = False
        self.select_panel.Visible = False
        self.side_splitter.Visible = False
        self.select_splitter.Visible = False
        self.canvas_scroll.Visible = False
        self.hint_label.Visible = False
        self.start_panel.Visible = True
        self.start_panel.BringToFront()
        self.center_start_buttons()
        self.set_status('请选择：新建剧本（.hex + .oob）或导入剧本（.scenario）')

    def enter_edit_mode(self):
        """进入编辑界面：显示工具条与左侧编制栏。"""
        self.start_panel.Visible = False
        self.top_bar.Visible = True
        self.apply_panel_visibility()
        self.update_toggle_labels()
        self.canvas_scroll.Visible = self.hex_map is not None
        self.hint_label.Visible = self.hex_map is None

    def on_back_to_start_click(self, sender=None, e=None):
        self.enter_start_mode()

    def reset_scenario_state(self):
        """清空当前剧本（地图 / 编制 / 部署），回到刚打开时的状态。"""
        self.clear_paths()
        self.hex_map = None
        self.map_size = None
        self.map_paper = 'A4'
        self.map_cols = 1
        self.map_width = None
        self.map_height = None
        self.map_margins = {}
        self.file_path = None
        self.scenario_path = None
        self.deployments = []
        self.selected_node = None
        self.selected_records = []
        self.selection_cell = None
        self.cell_records = []
        self.move_mode = False
        self.oob_path = None
        self.oob_summary = None
        self.source_hex_name = None
        if OOB_IMPORT_ERROR is None:
            try:
                oob.set_root(None, army='', faction='')
            except Exception:
                pass
        self.canvas_box.Size = Size(1, 1)
        self.canvas_box.Invalidate()
        self.refresh_oob_tree()
        self.update_sel_label()
        self.refresh_selection_panel()
        self.update_oob_label()
        self.file_label.Text = '（还没有打开文件）'
        self.form.Text = WINDOW_TITLE

    def on_new_scenario_click(self, sender=None, e=None):
        """新建剧本：清空状态 → 打开 .hex → 画地图 → 弹 .oob。"""
        self.reset_scenario_state()
        self.enter_edit_mode()
        self.set_status('新建剧本：请选择 .hex 六角格画布')
        self.open_hex_file()

    def on_import_scenario_click(self, sender=None, e=None):
        """导入剧本：读 .scenario，恢复地图 / 编制 / 部署。"""
        self.reset_scenario_state()
        self.enter_edit_mode()
        self.open_scenario_file()

    def center_hint(self):
        """把提示摆在“两个栏之间”的地图区域正中（不是整个窗口）。"""
        client = self.form.ClientSize
        rect = self.canvas_area(client)
        self.hint_label.Location = Point(
            max(0, rect.X + (rect.Width - self.hint_label.Width) // 2),
            max(0, rect.Y + (rect.Height - self.hint_label.Height) // 2),
        )

    def canvas_area(self, client=None):
        """地图区域（窗口客户区里去掉工具条、状态栏和左右栏剩下的矩形）。"""
        if client is None:
            client = self.form.ClientSize
        left = self.side_panel.Width if self.side_panel.Visible else 0
        right = self.select_panel.Width if self.select_panel.Visible else 0
        if self.side_panel.Visible and self.side_splitter.Visible:
            left += self.side_splitter.Width
        if self.select_panel.Visible and self.select_splitter.Visible:
            right += self.select_splitter.Width
        top = self.top_bar.Height if self.top_bar.Visible else 0
        bottom = self.status_bar.Height if self.status_bar.Visible else 0
        return Rectangle(left, top,
                         max(1, client.Width - left - right),
                         max(1, client.Height - top - bottom))

    def update_panel_layout(self):
        """左右栏宽度跟着窗口走：窗口窄时变窄，保证地图留得下。"""
        client_w = max(1, self.form.ClientSize.Width)
        width = max(MIN_PANEL_WIDTH, min(PANEL_WIDTH, int(client_w * PANEL_SHARE)))
        if not self._panel_manual:
            for panel in (self.side_panel, self.select_panel):
                if panel.Width != width:
                    panel.Width = width
        else:
            self.clamp_panel_widths()      # 手动宽度也要给地图留够地方
        self.apply_panel_button_widths()
        self.center_hint()

    def clamp_panel_widths(self):
        """把左右栏夹到“另一边 + 分隔条 + 地图最小宽度”的品牌内。"""
        client_w = max(1, self.form.ClientSize.Width)
        splitters = self.side_splitter.Width * 2
        for _ in range(2):                 # 两边互相约束，跑两轮就收敛了
            for panel, other in ((self.side_panel, self.select_panel),
                                 (self.select_panel, self.side_panel)):
                limit = max(MIN_PANEL_WIDTH,
                            client_w - other.Width - splitters - MIN_MAP_WIDTH)
                if panel.Width > limit:
                    panel.Width = limit

    def apply_panel_button_widths(self):
        """栏内按钮宽度跟着栏宽走。"""
        for panel, buttons in ((self.side_panel, self._side_buttons),
                               (self.select_panel, self._select_buttons)):
            for button in buttons:
                button.Width = max(60, panel.Width - 18)

    def on_splitter_moved(self, sender, e):
        """拖了分隔条：记住手动宽度，并且保证地图还剩得下。"""
        self._panel_manual = True
        self.clamp_panel_widths()
        self.apply_panel_button_widths()
        self.center_hint()

    def on_focus_map_click(self, sender=None, e=None):
        """专注地图：一键收起/展开两侧栏（连分隔条一起）。"""
        hide = self._side_open or self._select_open
        self._side_open = not hide
        self._select_open = not hide
        self.apply_panel_visibility()
        self.update_toggle_labels()
        self.save_ui_state()
        self.set_status('专注地图：%s' % ('两侧栏已收起' if hide else '两侧栏已展开'))

    # ---------- 布局自检（排查遮挡用） ----------
    def pixel_kind(self, color):
        r, g, b = color.R, color.G, color.B
        if r > 200 and g > 200 and b > 200:
            return '白底'
        if abs(r - 145) < 14 and abs(g - 145) < 14 and abs(b - 145) < 14:
            return '网格线'
        if r < 90 and g < 90 and b < 90:
            return '深色'
        return '其它'

    def describe_pixels(self, bitmap, bounds):
        counts = {}
        step = max(2, bounds.Width // 120)
        for y in range(bounds.Top, bounds.Bottom, step):
            for x in range(bounds.Left, bounds.Right, step):
                key = self.pixel_kind(bitmap.GetPixel(x, y))
                counts[key] = counts.get(key, 0) + 1
        total = sum(counts.values()) or 1
        return '，'.join('%s %.0f%%' % (key, value * 100.0 / total)
                         for key, value in sorted(counts.items()))

    def describe_tree(self, container, tag, problems, depth=0):
        lines = []
        pad = '  ' * (depth + 1)
        for control in container.Controls:
            if not control.Visible:
                continue
            bounds = control.Bounds
            text = str(getattr(control, 'Text', '') or '').splitlines()
            label = (text[0][:16] if text else type(control).__name__)
            lines.append('%s%s %s (%d,%d %dx%d)' % (pad, type(control).__name__, label,
                                                    bounds.X, bounds.Y, bounds.Width, bounds.Height))
            if control.Controls.Count:
                lines.extend(self.describe_tree(control, label, problems, depth + 1))
        items = [c for c in container.Controls if c.Visible]
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if items[i].Bounds.IntersectsWith(items[j].Bounds):
                    problems.append('%s: %s 与 %s 重叠'
                                    % (tag, type(items[i]).__name__, type(items[j]).__name__))
        return lines

    def layout_report(self):
        """生成布局自检文本：窗口/屏幕、各控件矩形、重叠、各区像素统计。"""
        client = self.form.ClientSize
        lines = ['初设窗口布局自检',
                 '窗口客户区：%dx%d（外框 %dx%d，屏幕位置 %d,%d）'
                 % (client.Width, client.Height, self.form.Width, self.form.Height,
                    self.form.Location.X, self.form.Location.Y)]
        try:
            from System.Windows.Forms import Screen
            area = Screen.FromControl(self.form).WorkingArea
            lines.append('所在显示器工作区：%dx%d' % (area.Width, area.Height))
        except Exception:
            pass
        region = self.canvas_area()
        lines.append('左右栏：左 %d / 右 %d；分隔条 %d；地图区域 (%d,%d %dx%d)'
                     % (self.side_panel.Width, self.select_panel.Width, self.side_splitter.Width,
                        region.X, region.Y, region.Width, region.Height))
        lines.append('缩放：%.1f%%（上限 %.1f%%）；地图：%s；已部署 %d'
                     % (self.zoom * 100, self.max_zoom() * 100,
                        self.map_size if self.map_size else '未打开', len(self.deployments)))
        lines.append('')
        lines.append('控件矩形（只列可见项）：')
        problems = []
        lines.extend(self.describe_tree(self.form, 'form', problems))
        lines.append('重叠检查：%s' % ('无' if not problems else '；'.join(problems)))
        lines.append('')
        try:
            bitmap = Bitmap(client.Width, client.Height)
            self.form.DrawToBitmap(bitmap, Rectangle(0, 0, client.Width, client.Height))
            for name, bounds in (('左栏', self.side_panel.Bounds),
                                 ('地图区域', self.canvas_scroll.Bounds),
                                 ('右栏', self.select_panel.Bounds)):
                lines.append('%s 像素：%s' % (name, self.describe_pixels(bitmap, bounds)))
            bitmap.Dispose()
        except Exception as exc:
            lines.append('像素统计失败：%s: %s' % (type(exc).__name__, exc))
        return '\n'.join(lines)

    def on_selfcheck_click(self, sender=None, e=None):
        """把布局自检写成文本文件并弹窗显示（排查遮挡时把它发我）。"""
        report = self.layout_report()
        folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'setupsaves')
        path = os.path.join(folder, 'layout_report.txt')
        try:
            os.makedirs(folder, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(report)
        except OSError as exc:
            show_error('自检报告写入失败：\n\n%s' % exc)
            return False
        MessageBox.Show(self.form, '%s\n\n（完整内容已写入：%s）' % (report[:1500], path),
                        '初设 - 布局自检', MessageBoxButtons.OK, MessageBoxIcon.Information)
        return True

    def on_toggle_side_click(self, sender=None, e=None):
        """打开/关闭左侧编制栏（工具栏按钮或栏内 × 都走这里）。"""
        self._side_open = not self._side_open
        self.apply_panel_visibility()
        self.update_toggle_labels()
        self.save_ui_state()
        self.set_status('左侧编制栏：%s' % ('已打开' if self._side_open else '已关闭'))

    def on_toggle_select_click(self, sender=None, e=None):
        """打开/关闭右侧选中栏。"""
        self._select_open = not self._select_open
        self.apply_panel_visibility()
        self.update_toggle_labels()
        self.save_ui_state()
        self.set_status('右侧选中栏：%s' % ('已打开' if self._select_open else '已关闭'))

    def apply_panel_visibility(self):
        """按 _side_open / _select_open 显示或隐藏两栏（起始页里一律隐藏）。"""
        if self.start_panel.Visible:
            return
        self.side_panel.Visible = self._side_open
        self.side_splitter.Visible = self._side_open
        self.select_panel.Visible = self._select_open
        self.select_splitter.Visible = self._select_open
        self.apply_panel_button_widths()
        self.center_hint()

    def update_toggle_labels(self):
        """工具条按钮文字跟着栏的开合状态变。"""
        self.side_toggle_button.Text = '隐藏左栏' if self._side_open else '显示左栏'
        self.select_toggle_button.Text = '隐藏右栏' if self._select_open else '显示右栏'
        self.focus_button.Text = '专注' if (self._side_open and self._select_open) else '恢复两栏'

    def on_splitter_paint(self, sender, e):
        """分隔条上画几个小点，提示这条可以拖。"""
        rect = sender.ClientRectangle
        brush = SolidBrush(Color.FromArgb(205, 210, 220))
        for y in range(12, max(12, rect.Height - 12), 8):
            e.Graphics.FillRectangle(brush, rect.Width // 2 - 1, y, 2, 2)
        brush.Dispose()

    def load_ui_state(self):
        """读上次的栏开关与宽度（没有配置文件就用默认）。"""
        try:
            with open(UI_STATE_FILE, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for key, panel in (('side', self.side_panel), ('select', self.select_panel)):
            item = data.get(key)
            if not isinstance(item, dict):
                continue
            width = item.get('width')
            if isinstance(width, int) and MIN_PANEL_WIDTH <= width <= 900:
                panel.Width = width
            if 'open' in item:
                if key == 'side':
                    self._side_open = bool(item['open'])
                else:
                    self._select_open = bool(item['open'])
        self._panel_manual = bool(data.get('widths_manual'))

    def save_ui_state(self):
        """把栏开关与宽度记到 setup_ui.json，下次启动沿用。"""
        try:
            with open(UI_STATE_FILE, 'w', encoding='utf-8') as handle:
                json.dump({
                    'side': {'open': self._side_open, 'width': self.side_panel.Width},
                    'select': {'open': self._select_open, 'width': self.select_panel.Width},
                    'widths_manual': self._panel_manual,
                }, handle, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # ---------- 打开 / 解析 .hex ----------
    def on_open_click(self, sender=None, e=None):
        self.open_hex_file()

    def open_hex_file(self):
        if HEX_IMPORT_ERROR is not None:
            show_error(
                '加载 Hex_Editor 里的解析模块失败，无法打开地图：\n\n%s\n\n'
                '请检查 %s 是否存在、能否正常导入。' % (HEX_IMPORT_ERROR, hex_editor_dir())
            )
            return

        saves = os.path.join(hex_editor_dir(), 'saves')
        dlg = OpenFileDialog()
        dlg.Title = '打开 .hex 文件'
        dlg.Filter = '六角格画布 (*.hex;*.json)|*.hex;*.json|所有文件 (*.*)|*.*'
        dlg.InitialDirectory = saves if os.path.isdir(saves) else project_dir()
        if dlg.ShowDialog(self.form) != DialogResult.OK:
            self.set_status('没有选择文件；点击“打开 .hex 文件...”可以重试')
            return
        if self.load_hex_file(dlg.FileName):
            # 地图画好之后紧接着问单位表；用 BeginInvoke 让上一个对话框先彻底关掉
            self.form.BeginInvoke(EventHandler(self.on_deferred_open_oob))

    def load_hex_file(self, path):
        """读文件 → 解析 .hex 容器 → 解析画布文档 → 画到地图上。"""
        try:
            with open(path, 'rb') as handle:
                raw = handle.read()
        except OSError as exc:
            show_error('读取文件失败：\n\n%s: %s' % (type(exc).__name__, exc))
            return False

        info = read_hex_container(raw)
        payload = info['payload'] if info['is_hex'] else raw
        doc = parse_map_doc(payload)          # 正规解析 + 宽松兜底
        if doc is None:
            if info['is_hex']:
                show_error(
                    '这个 .hex 里的内容不是六角格画布，没法画成地图。\n\n'
                    '文件：%s\n容器里的内容类型：%s\n数据长度：%d 字节\n\n'
                    '（只有 Hex Editor 保存的 HEXMAP 画布能显示成地图）'
                    % (path, info['original_type'] or '未知', len(info['payload']))
                )
                self.set_status('打开失败：内容类型 %s 不是六角格画布' % (info['original_type'] or '未知'))
            else:
                show_error(
                    '这个文件读不出六角格画布。\n\n'
                    '文件：%s\n大小：%d 字节\n\n'
                    '既没有 HEX1 文件头，内容也不是画布 JSON（缺少 cols 等字段）。'
                    % (path, len(raw))
                )
                self.set_status('打开失败：不是 .hex 容器，也不是画布 JSON')
            return False

        self.file_path = path
        self.source_hex_name = os.path.basename(path)
        self.show_map(doc)
        self.form.Text = '%s - %s' % (os.path.basename(path), WINDOW_TITLE)
        return True

    # ---------- 军队编制（.oob） ----------
    def on_deferred_open_oob(self, sender=None, e=None):
        """地图打开后接着弹“打开军队编制文件”。"""
        try:
            self.open_oob_file()
        except Exception as exc:
            show_error('打开编制对话框出错：\n\n%s: %s' % (type(exc).__name__, exc))
            self.set_status('打开编制对话框出错；可以点“打开 .oob 编制...”重试')

    def on_open_oob_click(self, sender=None, e=None):
        self.open_oob_file()

    def open_oob_file(self):
        """选一个 .oob 军队编制文件并载入；取消就只留状态栏提示。"""
        if OOB_IMPORT_ERROR is not None:
            show_error(
                '加载 Units/oob.py 失败，无法读取编制文件：\n\n%s\n\n'
                '请检查 %s 是否存在、能否正常导入。' % (OOB_IMPORT_ERROR, units_dir())
            )
            return False

        dlg = OpenFileDialog()
        dlg.Title = '打开军队编制文件'
        dlg.Filter = OOB_FILE_FILTER
        dlg.InitialDirectory = oob.OOB_DIR if os.path.isdir(oob.OOB_DIR) else project_dir()
        if dlg.ShowDialog(self.form) != DialogResult.OK:
            if self.oob_path:
                self.set_status('已跳过编制选择；当前仍是 %s' % os.path.basename(self.oob_path))
            else:
                self.set_status('已跳过编制选择；点“打开 .oob 编制...”可以再选')
            return False
        return self.load_oob_file(dlg.FileName)

    def load_oob_file(self, path):
        """读取 .oob（oob.load_file）：记住编制树并统计，暂时不画到地图上。"""
        try:
            oob.load_file(path)
        except Exception as exc:
            show_error(
                '读取编制文件失败：\n\n%s\n（%s: %s）\n\n'
                '（.oob 是 Units/oob.py 写出的 JSON：{"v": 1, "army": ..., "root": {...}}）'
                % (path, type(exc).__name__, exc)
            )
            self.set_status('读取编制文件失败；可以点“打开 .oob 编制...”重试')
            return False

        self.oob_path = os.path.abspath(path)
        self.oob_summary = oob.summary()
        self.update_oob_label()
        self.selected_node = None
        self.refresh_oob_tree()          # 左侧树按新编制重建
        self.update_sel_label()
        kept, dropped = self.remap_deployments()
        if dropped:
            self.set_status('新编制里找不到这些已部署单位，已丢弃它们的部署：%s'
                            % '、'.join(dropped[:4]))
        self.report_oob_problems()
        return True

    def remap_deployments(self):
        """换了一份编制后，把已有部署按“名字路径”重新挂到新节点对象上。

        返回（保留数, 丢弃的名字列表）。不做这一步的话，同一个单位会因为是新对象
        而被当成没部署过，重复落子。
        """
        if not self.deployments:
            return 0, []
        root = oob.root() if OOB_IMPORT_ERROR is None else None
        kept = []
        dropped = []
        for record in self.deployments:
            node = self.find_node_by_path(root, record.get('path') or [])
            if node is None:
                dropped.append(record.get('name') or '?')
                continue
            fresh = self.node_record(node)
            for key in ('q', 'r', 'cell_id', 'cell', 'center_px'):
                if key in record:
                    fresh[key] = record[key]
            kept.append(fresh)
        self.deployments = kept
        return len(kept), dropped

    def update_oob_label(self):
        """状态栏右侧显示编制概况与部署数量。"""
        has_tree = OOB_IMPORT_ERROR is None and oob.root() is not None
        if not has_tree:
            self.oob_label.Text = '编制：未载入'
            return
        data = self.oob_summary or {}
        name = os.path.basename(self.oob_path) if self.oob_path else '初设内快照'
        text = '编制 %s：%s' % (name, data.get('army') or '未命名')
        if data.get('faction'):
            text += '（%s）' % data['faction']
        text += ' · 节点 %d · %d 层 · 数量合计 %d' % (
            data.get('nodes', 0), data.get('depth', 0), data.get('step', 0))
        levels = data.get('levels') or {}
        if levels:
            ranked = sorted(levels.items(), key=lambda item: (-item[1], item[0]))
            text += ' · ' + ' / '.join('%s %d' % (name, count) for name, count in ranked[:3])
        types = data.get('types') or []
        if types:
            text += ' · 用到 %d 种单位类型' % len(types)
        text += ' · 已部署 %d' % len(self.deployments)
        self.oob_label.Text = text

    def report_oob_problems(self, limit=6):
        """编制检查（级别是否合法、单位类型是否在 units.data 里），有问题就提醒一次。"""
        try:
            problems = oob.check()
        except Exception:
            return []
        if problems:
            shown = '\n'.join(problems[:limit])
            more = '' if len(problems) <= limit else '\n…（另外 %d 处）' % (len(problems) - limit)
            MessageBox.Show(
                self.form,
                '编制文件有 %d 处问题：\n\n%s%s\n\n'
                '（单位类型来自 Units/database/units.data，可以用 Units/units_editor.py 修）'
                % (len(problems), shown, more),
                '初设 - 编制检查',
                MessageBoxButtons.OK,
                MessageBoxIcon.Warning,
            )
        return problems

    # ---------- 导入剧本（.scenario） ----------
    def open_scenario_file(self):
        """选一个 .scenario 导入。"""
        dlg = OpenFileDialog()
        dlg.Title = '导入剧本 (.scenario)'
        dlg.Filter = SCENARIO_FILE_FILTER
        saves = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'setupsaves')
        if os.path.isdir(saves):
            dlg.InitialDirectory = saves
        if dlg.ShowDialog(self.form) != DialogResult.OK:
            if self.hex_map is None:
                self.enter_start_mode()             # 什么都没有就退回起始页
            else:
                self.set_status('已取消导入剧本')
            return False
        return self.load_scenario_file(dlg.FileName)

    def load_scenario_file(self, path):
        """读 .scenario：恢复地图格子、格边、编制树快照与各单位部署。"""
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            show_error('读取剧本失败：\n\n%s\n（%s: %s）' % (path, type(exc).__name__, exc))
            self.set_status('读取剧本失败；可以点“导入剧本”重试')
            return False

        if not isinstance(data, dict) or data.get('type') != SCENARIO_TYPE:
            show_error(
                '这不是初设文件（%s）。\n\n'
                '初设文件由本窗口“保存 .scenario”生成，type 字段应为 %s。'
                % (path, SCENARIO_TYPE)
            )
            self.set_status('导入失败：不是初设文件')
            return False

        map_info = data.get('map') or {}
        cols = int(map_info.get('cols') or 0)
        if cols < 1:
            show_error('初设文件里的地图信息不完整（缺少 cols）：\n\n%s' % path)
            self.set_status('导入失败：地图信息不完整')
            return False

        doc = {
            'paper': map_info.get('paper') or 'A4',
            'cols': cols,
            'width': map_info.get('width'),
            'height': map_info.get('height'),
            'margins': map_info.get('margins') or {},
            'terrains': data.get('cells') or {},     # "列,行" -> 地形（apply_terrains 直接吃这个格式）
            'edges': data.get('edges') or {},        # "A|B" -> 格边地形
        }
        self.file_path = None                        # 地图来自初设，不来自 .hex
        self.source_hex_name = map_info.get('source_hex')
        self.show_map(doc)                           # show_map 会清空旧部署

        # 编制：优先用初设里的快照，没有快照就沿用当前已载入的编制
        oob_block = data.get('oob') or {}
        oob_note = ''
        if isinstance(oob_block.get('root'), dict) and OOB_IMPORT_ERROR is None:
            try:
                oob.from_dict({
                    'v': 1,
                    'army': oob_block.get('army'),
                    'faction': oob_block.get('faction'),
                    'root': oob_block['root'],
                })
                self.oob_path = None                 # 不是从 .oob 文件来的
                self.oob_summary = oob.summary()
                self.selected_node = None
                self.refresh_oob_tree()
                self.update_sel_label()
            except Exception as exc:
                oob_note = '（编制快照读入失败：%s）' % exc
        elif oob.root() is not None:
            oob_note = '（初设里没有编制快照，沿用当前编制）'

        placed, missing = self.apply_scenario_units(data.get('units') or [])
        self.selected_records = []
        self.selection_cell = None
        self.cell_records = []
        self.refresh_selection_panel()
        self.scenario_path = os.path.abspath(path)
        self.form.Text = '%s - %s' % (os.path.basename(path), WINDOW_TITLE)
        self.file_label.Text = os.path.basename(path)
        self.update_oob_label()
        self.update_sel_label()
        self.canvas_box.Invalidate()

        text = ('已导入剧本 %s：%s · %d 列 · 格子 %d 个 · 地形 %d 处 · 格边 %d 条 · 部署 %d 个单位%s'
                % (os.path.basename(path), '自定义' if self.map_paper == 'CUSTOM' else self.map_paper,
                   self.map_cols, len(self.hex_map), len(data.get('cells') or {}),
                   len(data.get('edges') or {}), placed, oob_note))
        if missing:
            text += ' · 有 %d 条部署找不到对应单位/格子：%s' % (
                len(missing), '、'.join(missing[:3]) + ('…' if len(missing) > 3 else ''))
        self.set_status(text)
        return True

    def find_node_by_path(self, root, path):
        """按初设里存的“从根到该节点的名字数组”在编制树里找节点。

        名字对不上时退一步按番号找，尽量让改动过编制的初设也能导入。
        """
        if root is None or not path:
            return None
        wanted = [str(name) for name in path]
        for node in root.walk():
            if list(node.path()) == wanted:
                return node
        for node in root.walk():
            if node.name == wanted[-1]:
                return node
        return None

    def apply_scenario_units(self, units):
        """按初设里的部署重建军标，返回（成功数, 找不到的列表）。"""
        self.deployments = []
        placed = 0
        missing = []
        root = oob.root() if OOB_IMPORT_ERROR is None else None
        for item in units:
            name = item.get('name') or '?'
            node = self.find_node_by_path(root, item.get('path') or [])
            if node is None:
                missing.append(name)
                continue
            cell = None
            try:
                cell = self.hex_map.cell_at(int(item.get('q', -1)), int(item.get('r', -1)))
            except (TypeError, ValueError):
                cell = None
            if cell is None:
                missing.append('%s（格子 %s）' % (name, item.get('cell')))
                continue
            record = self.node_record(node)
            record.update({
                'cell': item.get('cell') or '%d,%d' % (cell.q, cell.r),
                'q': cell.q,
                'r': cell.r,
                'cell_id': cell.id,
                'center_px': [round(cell.cx, 2), round(cell.cy, 2)],
            })
            self.deployments.append(record)
            placed += 1
        return placed, missing

    # ---------- 左侧编制树 ----------
    def refresh_oob_tree(self):
        """按当前编制树重建左侧列表。"""
        self.oob_tree.BeginUpdate()
        try:
            self.oob_tree.Nodes.Clear()
            root = None
            if OOB_IMPORT_ERROR is None:
                try:
                    root = oob.root()
                except Exception:
                    root = None
            if root is None:
                hint = TreeNode('（还没有编制：点上方“打开 .oob 编制...”加载）')
                self.oob_tree.Nodes.Add(hint)
                return
            self._add_tree_nodes(self.oob_tree.Nodes, root)
        finally:
            self.oob_tree.EndUpdate()
        self.oob_tree.ExpandAll()
        self.sync_tree_selection(self.selected_node)

    def _add_tree_nodes(self, collection, node):
        item = TreeNode(self.node_text(node))
        item.Tag = node
        collection.Add(item)
        for child in node.children:
            self._add_tree_nodes(item.Nodes, child)

    def node_text(self, node):
        """树里的节点文字：番号（级别 · 类型 · 数量），已部署的加 ● 前缀。"""
        info = [node.level or '?']
        if node.type:
            info.append(node.type)
        if node.step:
            info.append('%d 步' % node.step)
        mark = '● ' if self.find_deployment(node=node) is not None else ''
        return '%s%s（%s）' % (mark, node.name or '（未命名）', ' · '.join(info))

    def find_tree_item(self, items, node):
        """在树里按节点对象找 TreeView 项。"""
        for item in items:
            if item.Tag is node:
                return item
            found = self.find_tree_item(item.Nodes, node)
            if found is not None:
                return found
        return None

    def refresh_tree_labels(self):
        """部署变化后刷新节点文字（● 标记）。"""
        def walk(items):
            for item in items:
                if item.Tag is not None:
                    item.Text = self.node_text(item.Tag)
                walk(item.Nodes)

        walk(self.oob_tree.Nodes)

    def sync_tree_selection(self, node):
        """把左侧树的选中项切到某个节点（点地图反查单位时用）。"""
        if node is None:
            return
        item = self.find_tree_item(self.oob_tree.Nodes, node)
        if item is not None:
            self.oob_tree.SelectedNode = item

    def on_oob_tree_select(self, sender, e):
        """在左侧选中一个单位 → 进入“可放置”状态。"""
        tag = e.Node.Tag if e.Node is not None else None
        self.selected_node = tag
        self.update_sel_label()
        if tag is None:
            return
        record = self.find_deployment(node=tag)
        if record is None:
            self.set_status('已选择 %s（%s%s）：点地图上的格子放置'
                            % (tag.name, tag.level, (' · %s' % tag.type) if tag.type else ''))
        else:
            self.set_status('%s 当前部署在 格子 #%s（%s）'
                            % (tag.name, record.get('cell_id'), record.get('cell')))

    def update_sel_label(self):
        """左侧栏那句“选中 / 状态”。"""
        node = self.selected_node
        if node is None:
            self.sel_label.Text = '选中：无\r\n先在下面选单位，再点地图格子'
            return
        record = self.find_deployment(node=node)
        if record is None:
            where = '状态：未部署（点地图格子放置）'
        else:
            where = '状态：格子 #%s（%s）' % (record.get('cell_id'), record.get('cell'))
        self.sel_label.Text = '选中：%s（%s）\r\n%s' % (node.name, node.level, where)

    # ---------- 部署（占格子 / 移动 / 移除） ----------
    def find_deployment(self, node=None, q=None, r=None):
        """按编制节点找部署记录（格子里的多个单位用 deployments_at）。"""
        for record in self.deployments:
            if node is not None and record.get('node') is node:
                return record
        if node is None and q is not None:
            found = self.deployments_at(q, r)
            if found:
                return found[0]
        return None

    def deployments_at(self, q, r):
        """某个格子上堆着的单位（按部署先后）。"""
        return [record for record in self.deployments
                if record.get('q') == q and record.get('r') == r]

    # ---------- 右侧：选中单位 ----------
    def is_selected(self, record):
        return any(record is item for item in self.selected_records)

    def selection_text(self, record, index):
        """右侧列表里一行的文字。"""
        info = [record.get('level') or '?']
        if record.get('type'):
            info.append(record['type'])
        if record.get('step'):
            info.append('%d 步' % record['step'])
        if record.get('faction'):
            info.append(record['faction'])
        return '%d. %s（%s）' % (index, record.get('name') or '（未命名）', ' · '.join(info))

    def select_cell(self, cell):
        """选中某个格子里的全部单位（右侧列出、默认全勾选）。"""
        self.selection_cell = (cell.q, cell.r)
        self.cell_records = self.deployments_at(cell.q, cell.r)
        self.selected_records = list(self.cell_records)
        self.refresh_selection_panel()
        self.canvas_box.Invalidate()

    def refresh_selection_panel(self):
        """按 cell_records / selected_records 重建右侧列表。"""
        self._filling_selection = True
        try:
            self.selection_box.Items.Clear()
            for index, record in enumerate(self.cell_records, 1):
                self.selection_box.Items.Add(self.selection_text(record, index),
                                             self.is_selected(record))
        finally:
            self._filling_selection = False
        self.update_selection_label()

    def update_selection_label(self):
        """右侧栏那句“格子 / 勾选情况”。"""
        if not self.cell_records:
            if self.selection_cell and self.hex_map is not None:
                q, r = self.selection_cell
                cell = self.hex_map.cell_at(q, r)
                head = '格子 #%s（%d,%d）：空' % (cell.id if cell else '?', q, r)
            else:
                head = '还没有选中格子'
            self.selection_label.Text = '%s\r\n点地图上的格子＝选中该格全部单位' % head
            return
        q, r = self.selection_cell
        cell = self.hex_map.cell_at(q, r) if self.hex_map is not None else None
        mode = '移动中：点目标格子' if self.move_mode else '已勾选 %d 个' % len(self.selected_records)
        self.selection_label.Text = '格子 #%s（%d,%d）：%d 个单位\r\n%s' % (
            cell.id if cell else '?', q, r, len(self.cell_records), mode)

    def on_selection_item_check(self, sender, e):
        """勾选状态变化 → 更新选中集合。"""
        if self._filling_selection:
            return
        if not (0 <= e.Index < len(self.cell_records)):
            return
        record = self.cell_records[e.Index]
        if e.NewValue == CheckState.Checked:
            if not self.is_selected(record):
                self.selected_records.append(record)
        else:
            self.selected_records = [item for item in self.selected_records if item is not record]
        self.update_selection_label()
        self.canvas_box.Invalidate()

    def on_select_all_click(self, sender=None, e=None):
        if not self.cell_records:
            self.set_status('还没有选中格子；点地图上的格子即可')
            return
        self.selected_records = list(self.cell_records)
        self.refresh_selection_panel()
        self.canvas_box.Invalidate()
        self.set_status('已全选格子里的 %d 个单位' % len(self.cell_records))

    def on_select_none_click(self, sender=None, e=None):
        if not self.cell_records:
            return
        self.selected_records = []
        self.refresh_selection_panel()
        self.canvas_box.Invalidate()
        self.set_status('已取消勾选（%d 个单位仍在格子上）' % len(self.cell_records))

    def on_move_selected_click(self, sender=None, e=None):
        """进入“移动选中”状态：再点目标格子完成搬迁。"""
        if not self.selected_records:
            self.set_status('先在右侧勾选要移动的单位')
            return False
        self.selected_node = None
        self.oob_tree.SelectedNode = None
        self.update_sel_label()
        self.move_mode = True
        self.update_selection_label()
        self.set_status('移动 %d 个单位：点地图上的目标格子完成（Esc 取消）' % len(self.selected_records))
        return True

    def move_selected_to(self, cell):
        """把勾选的单位搬到目标格子（堆到那一格上）。"""
        moving = list(self.selected_records)
        if not moving:
            self.set_status('还没有勾选要移动的单位')
            return False
        for record in moving:
            record['q'], record['r'], record['cell_id'] = cell.q, cell.r, cell.id
            record['cell'] = '%d,%d' % (cell.q, cell.r)
            record['center_px'] = [round(cell.cx, 2), round(cell.cy, 2)]
        self.move_mode = False
        self.refresh_tree_labels()
        self.select_cell(cell)
        self.set_status('已把 %d 个单位移动到 格子 #%d（%d,%d）'
                        % (len(moving), cell.id, cell.q, cell.r))
        return True

    def node_record(self, node):
        """把编制节点变成可保存的部署记录（名字/级别/类型/数量/阵营/兵种）。"""
        capability = None
        try:
            capability = node.capability()
        except Exception:
            capability = None
        return {
            'node': node,
            'path': node.path(),
            'name': node.name,
            'level': node.level,
            'type': node.type,
            'step': node.step,
            'note': node.note,
            'faction': '' if OOB_IMPORT_ERROR is not None else oob.FACTION,
            'branch': (capability or {}).get('branch', ''),
        }

    def place_node(self, node, cell):
        """把一个编制节点放到某个格子上（已放过就移动过去；同一格可以堆多个单位）。"""
        record = self.find_deployment(node=node)
        if record is None:
            record = self.node_record(node)
            self.deployments.append(record)
            action = '已部署'
        else:
            action = '已移动'
        record['q'], record['r'], record['cell_id'] = cell.q, cell.r, cell.id
        record['cell'] = '%d,%d' % (cell.q, cell.r)
        record['center_px'] = [round(cell.cx, 2), round(cell.cy, 2)]

        self.update_sel_label()
        self.refresh_tree_labels()
        self.update_oob_label()
        self.canvas_box.Invalidate()
        stack = len(self.deployments_at(cell.q, cell.r))
        self.set_status('%s %s 到 第 %d 列 第 %d 行（格子 #%d，该格现在 %d 个单位）'
                        % (action, record['name'], cell.q, cell.r, cell.id, stack))
        return True

    def on_remove_click(self, sender=None, e=None):
        """移除右侧勾选的单位；没有勾选时退回“移除当前编制节点的部署”。"""
        if self.selected_records:
            removed = list(self.selected_records)
            self.deployments = [record for record in self.deployments
                                if not any(record is item for item in removed)]
            self.selected_records = []
            if self.selection_cell is not None:
                self.cell_records = self.deployments_at(*self.selection_cell)
            self.refresh_selection_panel()
            self.refresh_tree_labels()
            self.update_oob_label()
            self.canvas_box.Invalidate()
            self.set_status('已移除 %d 个单位：%s'
                            % (len(removed), '、'.join(r['name'] for r in removed[:4])))
            return True

        node = self.selected_node
        if node is None:
            self.set_status('先在右侧勾选单位（或点格子选中），再移除')
            return False
        record = self.find_deployment(node=node)
        if record is None:
            self.set_status('%s 还没有部署' % node.name)
            return False
        self.deployments.remove(record)
        if self.selection_cell is not None:
            self.cell_records = self.deployments_at(*self.selection_cell)
            self.refresh_selection_panel()
        self.update_sel_label()
        self.refresh_tree_labels()
        self.update_oob_label()
        self.canvas_box.Invalidate()
        self.set_status('已移除 %s 的部署（原在 格子 #%s）'
                        % (record['name'], record.get('cell_id')))
        return True

    def on_disarm_click(self, sender=None, e=None):
        """取消放置/移动状态：之后点格子只是选中该格单位。"""
        self.selected_node = None
        self.move_mode = False
        self.oob_tree.SelectedNode = None
        self.update_sel_label()
        self.update_selection_label()
        self.canvas_box.Invalidate()
        self.set_status('已取消放置/移动：现在点格子只会选中该格上的单位')

    def on_clear_click(self, sender=None, e=None):
        """清空全部部署。"""
        if not self.deployments:
            self.set_status('还没有任何部署')
            return False
        answer = MessageBox.Show(
            self.form, '要清空全部 %d 处部署吗？' % len(self.deployments),
            '初设 - 清空部署', MessageBoxButtons.YesNo, MessageBoxIcon.Question,
        )
        if answer != DialogResult.Yes:
            return False
        count = len(self.deployments)
        self.deployments = []
        self.selected_records = []
        self.update_sel_label()
        self.refresh_tree_labels()
        self.refresh_selection_panel()
        self.update_oob_label()
        self.canvas_box.Invalidate()
        self.set_status('已清空 %d 处部署' % count)
        return True

    def on_canvas_mouse_down(self, sender, e):
        """左键点格子：移动选中 → 放置新单位 → 否则选中该格里的全部单位。"""
        if self.hex_map is None or e.Button != MouseButtons.Left:
            return
        cell = self.hex_map.cell_at_point(e.X / self.zoom, e.Y / self.zoom)
        if cell is None:
            self.set_status('这里没有格子')
            return

        if self.move_mode and self.selected_records:
            self.move_selected_to(cell)
            return

        if self.selected_node is not None:
            self.place_node(self.selected_node, cell)
            self.select_cell(cell)          # 放完顺手选中这一格，方便继续调整
            return

        self.select_cell(cell)
        count = len(self.cell_records)
        if count == 0:
            self.set_status('格子 #%d（%d,%d）：空地。先在左侧选一个单位，再点这里放置'
                            % (cell.id, cell.q, cell.r))
        else:
            self.set_status('已选中格子 #%d（%d,%d）里的 %d 个单位；右侧可以逐条取消勾选'
                            % (cell.id, cell.q, cell.r, count))

    def on_canvas_mouse_move(self, sender, e):
        """鼠标扫过有单位的格子时状态栏显示信息；贴住视口边缘时开始平移。"""
        if self.hex_map is None:
            return
        scroll = self.canvas_scroll.AutoScrollPosition       # 是负值，用来换算到视口坐标
        self.update_edge_pan(e.X + scroll.X, e.Y + scroll.Y)
        cell = self.hex_map.cell_at_point(e.X / self.zoom, e.Y / self.zoom)
        stack = [] if cell is None else self.deployments_at(cell.q, cell.r)
        if not stack:
            if self.status_label.Text != self._base_status:
                self.set_status(self._base_status, remember=False)
            return
        record = stack[0]
        text = ('单位：%s（%s · %s）· 阵营 %s · 数量 %s · 格子 #%d（%s）'
                % (record['name'], record['level'], record['type'] or '无类型',
                   record['faction'] or '未填', record['step'], record['cell_id'], record['cell']))
        if len(stack) > 1:
            text += ' · 该格共 %d 个单位' % len(stack)
        if self.status_label.Text != text:
            self.set_status(text, remember=False)

    def on_form_key_down(self, sender, e):
        """WASD/方向键 = 平移地图；Delete = 移除选中；Esc = 取消放置/移动。"""
        if self.add_pan_key(e.KeyCode):
            return
        if e.KeyCode == Keys.Delete:
            self.on_remove_click()
        elif e.KeyCode == Keys.Escape:
            self.on_disarm_click()

    def show_map(self, doc):
        """按画布文档建格子集合、灌入地形，并显示画布。"""
        self.map_paper = doc['paper']
        self.map_cols = doc['cols']
        self.map_width = doc['width']
        self.map_height = doc['height']
        self.map_margins = normalize_margins(doc['margins'])
        width, height = map_canvas_size(self.map_paper, self.map_width, self.map_height)
        self.map_size = (width, height)

        self.hex_map = HexMap(self.map_cols, width, height, self.map_margins)
        terrain_count = self.hex_map.apply_terrains(doc.get('terrains')) or 0
        edge_count = self.hex_map.apply_edges(doc.get('edges')) or 0

        self.canvas_scroll.Visible = True
        self.hint_label.Visible = False
        self.file_label.Text = os.path.basename(self.file_path) if self.file_path else '（未命名）'

        # 换了地图，格子全变了，旧的部署位置作废
        self.deployments = []
        self.update_sel_label()
        self.update_oob_label()

        self.set_zoom(self.fit_zoom(), auto_fit=True)      # 先按窗口大小整幅显示
        self.render_now()

        paper_text = '自定义' if self.map_paper == 'CUSTOM' else self.map_paper
        text = (
            '已解析 %s：%s · %d 列 · %d×%d px · 格子 %d 个 · 纵向 %d 行 · 地形 %d 格 / 格边 %d 条'
            % (os.path.basename(self.file_path or '画布'), paper_text, self.map_cols,
               width, height, len(self.hex_map), self.hex_map.rows, terrain_count, edge_count)
        )
        unknown = self.hex_map.unknown_terrains()
        unknown_edges = self.hex_map.unknown_edge_terrains()
        if unknown:
            text += ' · 未知地形 %s（灰色显示）' % '、'.join(unknown)
        if unknown_edges:
            text += ' · 未知格边地形 %s（灰色显示）' % '、'.join(unknown_edges)
        self.set_status(text)

    # ---------- 缩放 ----------
    def fit_zoom(self):
        """算出能把整幅地图放进窗口的缩放比例。"""
        if self.map_size is None:
            return 1.0
        pad = 8                                  # 留一点边，避免刚好顶出滚动条
        view_w = max(1, self.canvas_scroll.ClientSize.Width - pad)
        view_h = max(1, self.canvas_scroll.ClientSize.Height - pad)
        doc_w, doc_h = self.map_size
        return min(view_w / float(max(1, doc_w)), view_h / float(max(1, doc_h)))

    def set_zoom(self, zoom, auto_fit=False):
        self.zoom = max(MIN_ZOOM, min(self.max_zoom(), float(zoom)))
        self.auto_fit = bool(auto_fit)
        self.zoom_label.Text = '%d%%' % round(self.zoom * 100)
        self.schedule_render()

    def max_zoom(self):
        """缩放上限：既受 MAX_ZOOM，也受画布像素上限约束。"""
        limit = MAX_ZOOM
        if self.map_size:
            doc_w, doc_h = max(1, self.map_size[0]), max(1, self.map_size[1])
            limit = min(limit, MAX_CANVAS_PIXELS / float(doc_w), MAX_CANVAS_PIXELS / float(doc_h))
        return max(MIN_ZOOM, limit)

    def on_zoom_in(self, sender=None, e=None):
        self.zoom_at(ZOOM_STEP)

    def on_zoom_out(self, sender=None, e=None):
        self.zoom_at(1.0 / ZOOM_STEP)

    def on_zoom_fit(self, sender=None, e=None):
        self.set_zoom(self.fit_zoom(), auto_fit=True)

    def on_canvas_mouse_wheel(self, sender, e):
        """滚轮只用来缩放（以光标位置为锚点），平移交给 WASD / 贴边。"""
        point = Point(e.X + self.canvas_box.Location.X, e.Y + self.canvas_box.Location.Y)
        self.zoom_at(ZOOM_STEP if e.Delta > 0 else 1.0 / ZOOM_STEP, point)

    def zoom_at(self, factor, view_point=None):
        """以视口里的某个点为锚点缩放（省略锚点时用视口中心）。

        锚点下的那个文档位置缩放后仍停在原处，滚轮缩放时不会“跑偏”。
        """
        if self.hex_map is None or self.map_size is None:
            return False

        view = self.canvas_scroll.ClientSize
        if view_point is None:
            view_point = Point(max(0, view.Width // 2), max(0, view.Height // 2))
        old_zoom = self.zoom
        new_zoom = max(MIN_ZOOM, min(self.max_zoom(), old_zoom * factor))
        if abs(new_zoom - old_zoom) < 1e-9:
            return False

        # 锚点落在文档的哪个位置（画布像素坐标 ÷ 当前缩放）
        base_x, base_y = self._canvas_base
        offset_x = -self.canvas_scroll.AutoScrollPosition.X
        offset_y = -self.canvas_scroll.AutoScrollPosition.Y
        doc_x = (view_point.X - base_x + offset_x) / old_zoom
        doc_y = (view_point.Y - base_y + offset_y) / old_zoom

        self.zoom = new_zoom
        self.auto_fit = False
        self.zoom_label.Text = '%d%%' % round(new_zoom * 100)
        self.render_now()                      # 重设画布尺寸并重新布局

        # 把锚点摆回原来的视口位置
        self.set_scroll(self._canvas_base[0] + doc_x * new_zoom - view_point.X,
                        self._canvas_base[1] + doc_y * new_zoom - view_point.Y)
        return True

    def set_scroll(self, x, y):
        """设置滚动偏移（像素，自动夹在可滚动范围内）。"""
        scroll = self.canvas_scroll
        max_x = max(0, scroll.DisplayRectangle.Width - scroll.ClientSize.Width)
        max_y = max(0, scroll.DisplayRectangle.Height - scroll.ClientSize.Height)
        scroll.AutoScrollPosition = Point(
            max(0, min(max_x, int(round(x)))),
            max(0, min(max_y, int(round(y)))),
        )

    # ---------- 平移（WASD / 横向滚轮 / 鼠标贴边） ----------
    def pan_by(self, dx, dy):
        """按像素平移视图：dx>0 表示往右看，dy>0 表示往下看。"""
        if self.hex_map is None:
            return False
        scroll = self.canvas_scroll
        current_x = -scroll.AutoScrollPosition.X
        current_y = -scroll.AutoScrollPosition.Y
        target_x = int(round(current_x + dx))
        target_y = int(round(current_y + dy))
        self.set_scroll(target_x, target_y)
        moved = (-scroll.AutoScrollPosition.X, -scroll.AutoScrollPosition.Y)
        if moved == (current_x, current_y):
            return False
        self.auto_fit = False          # 手动平移过就别再自动回正中
        return True

    def on_horizontal_wheel(self, delta):
        """鼠标左右倾轮（侧轮）：和纵向滚轮一样，只缩放（以视口中心为锚点）。"""
        self.zoom_at(ZOOM_STEP if delta > 0 else 1.0 / ZOOM_STEP)

    def pan_step(self):
        """本周期该平移多少：按住的键 + 鼠标贴边。"""
        dx = dy = 0
        for key in self._pan_keys:
            offset = PAN_KEYS.get(key)
            if offset is not None:
                dx += offset[0] * PAN_KEY_STEP
                dy += offset[1] * PAN_KEY_STEP
        dx += self._edge_pan[0]
        dy += self._edge_pan[1]
        return dx, dy

    def update_pan_timer(self):
        """有平移需求就开定时器，没有就停掉。"""
        dx, dy = self.pan_step()
        if self.hex_map is not None and (dx or dy) and self.can_pan():
            if not self._pan_timer.Enabled:
                self._pan_timer.Start()
        elif self._pan_timer.Enabled:
            self._pan_timer.Stop()

    def can_pan(self):
        """当前视图是否真的还有可滚动的余量（整幅都在视口里时就不用平移）。"""
        scroll = self.canvas_scroll
        return (scroll.DisplayRectangle.Width > scroll.ClientSize.Width
                or scroll.DisplayRectangle.Height > scroll.ClientSize.Height)

    def on_pan_timer_tick(self, sender, e):
        dx, dy = self.pan_step()
        if not (dx or dy):
            self._pan_timer.Stop()
            return
        self.pan_by(dx, dy)

    def add_pan_key(self, key_code):
        """按下 WASD / 方向键 → 记下来（真正的平移交给定时器，按住就连续走）。"""
        name = str(key_code)
        if name in PAN_KEYS:
            self._pan_keys.add(name)
            self.update_pan_timer()
            return True
        return False

    def remove_pan_key(self, key_code):
        name = str(key_code)
        if name in self._pan_keys:
            self._pan_keys.discard(name)
            self.update_pan_timer()
        elif name in PAN_KEYS:
            self.update_pan_timer()

    def on_form_key_up(self, sender, e):
        self.remove_pan_key(e.KeyCode)

    def update_edge_pan(self, view_x, view_y):
        """鼠标进入视口边缘带 → 产生平移向量（离边越近越快）。"""
        view = self.canvas_scroll.ClientSize
        if view_x is None or view_y is None or view.Width <= 1 or view.Height <= 1:
            self.set_edge_pan(0, 0)
            return
        dx = dy = 0
        if view_x <= EDGE_PAN_BAND:
            dx = -EDGE_PAN_MAX_SPEED * (1.0 - max(0.0, view_x) / float(EDGE_PAN_BAND))
        elif view_x >= view.Width - EDGE_PAN_BAND:
            dx = EDGE_PAN_MAX_SPEED * (1.0 - max(0.0, view.Width - view_x) / float(EDGE_PAN_BAND))
        if view_y <= EDGE_PAN_BAND:
            dy = -EDGE_PAN_MAX_SPEED * (1.0 - max(0.0, view_y) / float(EDGE_PAN_BAND))
        elif view_y >= view.Height - EDGE_PAN_BAND:
            dy = EDGE_PAN_MAX_SPEED * (1.0 - max(0.0, view.Height - view_y) / float(EDGE_PAN_BAND))
        self.set_edge_pan(dx, dy)

    def set_edge_pan(self, dx, dy):
        target = (int(round(dx)), int(round(dy)))
        if target != self._edge_pan:
            self._edge_pan = target
            self.update_pan_timer()

    def on_canvas_mouse_leave(self, sender, e):
        """鼠标离开画布：停止贴边平移。"""
        self.set_edge_pan(0, 0)

    def on_canvas_resize(self, sender, e):
        if self.auto_fit and self.hex_map is not None:
            self.set_zoom(self.fit_zoom(), auto_fit=True)
        else:
            self.layout_canvas()

    def on_form_resize(self, sender, e):
        self.update_panel_layout()
        if self.hint_label.Visible:
            self.center_hint()
        if self.start_panel.Visible:
            self.center_start_buttons()

    # ---------- 渲染 ----------
    def schedule_render(self):
        if self.hex_map is None:
            return
        if self._render_timer.Enabled:
            self._render_timer.Stop()
        self._render_timer.Start()

    def on_render_timer_tick(self, sender, e):
        self._render_timer.Stop()
        self.render_now()

    def render_now(self):
        """按当前缩放重建路径并重绘画布。"""
        if self.hex_map is None or self.map_size is None:
            return
        zoom = self.zoom
        self.canvas_box.Size = Size(max(1, int(round(self.map_size[0] * zoom))),
                                    max(1, int(round(self.map_size[1] * zoom))))
        self.layout_canvas()
        self.render_paths()
        self.canvas_box.Invalidate()

    def layout_canvas(self):
        """把画布摆进容器：比视口小就居中；比视口大就贴左上，其余靠滚动条看。

        只在“基位”（未滚动时的位置）变化时才动 Location，避免每次重绘把滚动位置顶回原点。
        """
        view = self.canvas_scroll.ClientSize
        size = self.canvas_box.Size
        target = (max(0, (view.Width - size.Width) // 2),
                  max(0, (view.Height - size.Height) // 2))
        if target == self._canvas_base:
            return
        self._canvas_base = target
        self.canvas_scroll.AutoScrollPosition = Point(0, 0)      # 基位变了，滚动归零
        self.canvas_box.Location = Point(target[0], target[1])

    def render_paths(self):
        """按地形分组生成路径：同一种地形的格子合成一条路径，画起来快。"""
        self.clear_paths()
        if self.hex_map is None:
            return
        zoom = self.zoom

        cell_paths = {}
        for cell in self.hex_map.cells.values():
            key = cell.terrain or ''
            path = cell_paths.get(key)
            if path is None:
                path = GraphicsPath()
                cell_paths[key] = path
            path.AddPolygon([PointF(cx * zoom, cy * zoom) for cx, cy in cell.corners()])

        edge_paths = {}
        for edge in self.hex_map.edges.values():
            if not edge.terrain:
                continue
            path = edge_paths.get(edge.terrain)
            if path is None:
                path = GraphicsPath()
                edge_paths[edge.terrain] = path
            # 每段单独起一个图元，否则 GDI+ 会把相邻线段的端点连起来
            path.StartFigure()
            path.AddLine(PointF(edge.p1[0] * zoom, edge.p1[1] * zoom),
                         PointF(edge.p2[0] * zoom, edge.p2[1] * zoom))

        self._cell_paths = cell_paths
        self._edge_paths = edge_paths

    def clear_paths(self):
        for path in self._cell_paths.values():
            path.Dispose()
        for path in self._edge_paths.values():
            path.Dispose()
        self._cell_paths = {}
        self._edge_paths = {}

    def on_canvas_paint(self, sender, e):
        self.draw_map(e.Graphics)

    def draw_map(self, g):
        """把地图画到指定 Graphics 上（单独抽出来，方便离屏渲染自检）。"""
        g.Clear(Color.White)
        g.SmoothingMode = SmoothingMode.AntiAlias
        if self.hex_map is None or not self._cell_paths:
            return

        zoom = self.zoom
        ml = max(0, int(round(self.map_margins.get('l', 0) * zoom)))
        mr = max(0, int(round(self.map_margins.get('r', 0) * zoom)))
        mt = max(0, int(round(self.map_margins.get('t', 0) * zoom)))
        mb = max(0, int(round(self.map_margins.get('b', 0) * zoom)))
        if ml or mr or mt or mb:
            g.SetClip(Rectangle(ml, mt,
                                max(1, self.canvas_box.Width - ml - mr),
                                max(1, self.canvas_box.Height - mt - mb)))

        for name, path in self._cell_paths.items():
            rgb = terrain_color(name)
            if rgb is None:
                continue
            brush = SolidBrush(Color.FromArgb(rgb[0], rgb[1], rgb[2]))
            g.FillPath(brush, path)
            brush.Dispose()

        pen = Pen(Color.FromArgb(170, 90, 90, 90), GRID_PEN_WIDTH)
        for path in self._cell_paths.values():
            g.DrawPath(pen, path)
        pen.Dispose()

        for name, path in self._edge_paths.items():
            rgb = edge_terrain_color(name)
            if rgb is None:
                continue
            edge_pen = Pen(Color.FromArgb(rgb[0], rgb[1], rgb[2]), EDGE_PEN_WIDTH * zoom)
            edge_pen.StartCap = LineCap.Round
            edge_pen.EndCap = LineCap.Round
            edge_pen.LineJoin = LineJoin.Round
            g.DrawPath(edge_pen, path)
            edge_pen.Dispose()

        self.draw_units(g)

    # ---------- 单位军标 ----------
    def draw_units(self, g):
        """把已部署单位画成北约军标；同一格多个单位时在格子里排成小网格。"""
        if self.hex_map is None or not self.deployments:
            return
        zoom = self.zoom
        cell_size = self.hex_map.cell_size * zoom
        if cell_size < 9:       # 太小就不画，避免糊成一团
            return
        groups = {}
        for record in self.deployments:
            groups.setdefault((record.get('q'), record.get('r')), []).append(record)
        for (q, r), records in groups.items():
            cell = self.hex_map.cell_at(q, r)
            if cell is None:
                continue
            self.draw_stack(g, cell.cx * zoom, cell.cy * zoom, cell_size, records)

    def draw_stack(self, g, cx, cy, cell_size, records):
        """在一个格子里排布 1..n 个军标（列数取 sqrt(n) 向上取整）。"""
        count = len(records)
        columns = max(1, int(math.ceil(math.sqrt(count))))
        rows = max(1, int(math.ceil(count / float(columns))))
        box_w = cell_size * 1.30        # 格子内部可用的排布区域
        box_h = cell_size * 1.24
        slot_w = box_w / columns
        slot_h = box_h / rows
        width = min(slot_w * 0.94, slot_h * 0.94 * SYMBOL_RATIO)
        width = max(7.0, width)
        height = max(5.0, width / SYMBOL_RATIO)

        for index, record in enumerate(records):
            row = index // columns
            col = index % columns
            x = cx - box_w / 2.0 + slot_w * (col + 0.5)
            y = cy - box_h / 2.0 + slot_h * (row + 0.5)
            self.draw_unit_symbol(g, x, y, width, height, record,
                                  number=(index + 1) if count > 1 else 0)

    def draw_unit_symbol(self, g, cx, cy, width, height, record, number=0):
        """画一个军标：阵营色方框 + 兵种符号 + 级别标记 + 类型/番号标注。"""
        rgb = faction_color(record.get('faction'))
        color = Color.FromArgb(rgb[0], rgb[1], rgb[2])
        left = cx - width / 2.0
        top = cy - height / 2.0

        brush = SolidBrush(Color.FromArgb(238, 255, 255, 255))
        g.FillRectangle(brush, left, top, width, height)
        brush.Dispose()

        pen = Pen(color, max(1.2, width * 0.06))
        g.DrawRectangle(pen, left, top, width, height)
        draw_nato_glyph(g, RectangleF(left, top, width, height), record.get('branch') or '', pen)
        pen.Dispose()

        selected = self.is_selected(record) or (
            self.selected_node is not None and record.get('node') is self.selected_node)
        if selected:                                        # 选中的单位加一圈高亮
            sel = Pen(Color.FromArgb(255, 210, 40, 40), max(1.5, width * 0.07))
            g.DrawRectangle(sel, left - 2.0, top - 2.0, width + 4.0, height + 4.0)
            sel.Dispose()

        mark = LEVEL_MARKS.get(record.get('level') or '')
        if mark and height >= 12:
            self.draw_centered_text(g, mark, cx, top - height * 0.72, self.mark_font, color)
        if number and height >= 12:                         # 堆叠序号，和右侧列表对应
            self.draw_centered_text(g, str(number), left + width * 0.16,
                                    top - height * 0.72, self.name_font, color)
        label = record.get('type') or record.get('name') or ''
        if label and height >= 18:
            suffix = '·%s' % record['step'] if record.get('step') else ''
            self.draw_centered_text(g, label + suffix, cx, top + height + 1.0, self.name_font, color)

    def draw_centered_text(self, g, text, cx, y, font, color):
        size = g.MeasureString(text, font)
        brush = SolidBrush(color)
        g.DrawString(text, font, brush, cx - size.Width / 2.0, y)
        brush.Dispose()

    # ---------- 保存初设（.scenario） ----------
    def scenario_dict(self):
        """把当前地图 + 部署打包成初设数据（纯数据，不是图片）。"""
        cells = encode_cell_items(self.hex_map.terrain_cells()) if self.hex_map is not None else {}
        edges = encode_cell_items(self.hex_map.edge_terrain_cells()) if self.hex_map is not None else {}
        stack_index = {}
        units = []
        for index, record in enumerate(self.deployments, 1):
            cell_key = (record.get('q'), record.get('r'))
            stack = stack_index.get(cell_key, 0)      # 同一格里的第几个（从 0 开始）
            stack_index[cell_key] = stack + 1
            units.append({
                'id': index,
                'stack': stack,
                'path': list(record.get('path') or []),
                'name': record.get('name', ''),
                'level': record.get('level', ''),
                'type': record.get('type', ''),
                'branch': record.get('branch', ''),
                'faction': record.get('faction', ''),
                'step': record.get('step', 0),
                'note': record.get('note', ''),
                'cell': record.get('cell', ''),
                'q': record.get('q'),
                'r': record.get('r'),
                'cell_id': record.get('cell_id'),
                'center_px': record.get('center_px'),
            })

        oob_block = None
        if OOB_IMPORT_ERROR is None and oob.root() is not None:
            oob_block = {
                'file': os.path.basename(self.oob_path) if self.oob_path else None,
                'army': oob.ARMY,
                'faction': oob.FACTION,
                'root': oob.root().to_dict(),
            }

        return {
            'v': SCENARIO_VERSION,
            'type': SCENARIO_TYPE,
            'map': {
                'paper': self.map_paper,
                'cols': self.map_cols,
                'width': self.map_size[0] if self.map_size else None,
                'height': self.map_size[1] if self.map_size else None,
                'margins': dict(self.map_margins),
                'rows': self.hex_map.rows if self.hex_map is not None else 0,
                'cell_size': round(self.hex_map.cell_size, 4) if self.hex_map is not None else 0,
                'source_hex': self.source_hex_name or (
                    os.path.basename(self.file_path) if self.file_path else None),
            },
            # "列,行" -> 地形名 或 [地形名, 消耗, 修正]；没出现的格子就是空地
            'cells': cells,
            # "列,行|列,行"（或 "列,行|方向"）-> 格边地形，例如河流
            'edges': edges,
            # 单位部署：每个单位一格，带格子坐标
            'units': units,
            # 编制快照：这样初设文件不依赖 .oob 也能被游戏读懂
            'oob': oob_block,
        }

    def on_save_scenario_click(self, sender=None, e=None):
        """保存：已经有关联的 .scenario（导入过）就直接覆盖，否则另存为。"""
        if self.scenario_path and os.path.isfile(self.scenario_path):
            return self.save_scenario(self.scenario_path)
        return self.save_scenario()

    def on_save_as_scenario_click(self, sender=None, e=None):
        self.save_scenario()

    def save_scenario(self, path=None):
        """保存 .scenario；不传路径就弹“另存为”。"""
        if self.hex_map is None:
            show_error('还没有打开地图，先打开 .hex 再保存初设。')
            return False

        if not path:
            saves = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'setupsaves')
            source = self.scenario_path or self.file_path or '未命名'
            base = os.path.splitext(os.path.basename(source))[0]
            dlg = SaveFileDialog()
            dlg.Title = '保存初设文件'
            dlg.Filter = SCENARIO_FILE_FILTER
            dlg.FileName = base + '.scenario'
            if os.path.isdir(saves):
                dlg.InitialDirectory = saves
            if dlg.ShowDialog(self.form) != DialogResult.OK:
                return False
            path = dlg.FileName

        try:
            data = self.scenario_dict()
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
        except (OSError, ValueError) as exc:
            show_error('保存初设失败：\n\n%s\n（%s: %s）' % (path, type(exc).__name__, exc))
            return False

        self.scenario_path = os.path.abspath(path)
        self.set_status('已保存初设 %s：格子地形 %d 处 · 格边 %d 条 · 部署 %d 个单位'
                        % (os.path.basename(path), len(data['cells']),
                           len(data['edges']), len(data['units'])))
        return True

    # ---------- 其它 ----------
    def set_status(self, text, remember=True):
        """更新状态栏；remember=False 用于临时提示（鼠标经过），不会覆盖基准文案。"""
        self.status_label.Text = text
        if remember:
            self._base_status = text

    def on_form_closed(self, sender, e):
        self._render_timer.Stop()
        self._pan_timer.Stop()
        self.save_ui_state()
        self.clear_paths()
        self.mark_font.Dispose()
        self.name_font.Dispose()


def build_setup_window(owner=None):
    """创建初设窗口（顶部工具条 + 地图画布 + 状态栏）。"""
    window = SetupWindow()
    if owner is not None:
        window.form.StartPosition = FormStartPosition.CenterParent
    return window


def open_setup_window(owner=None):
    """显示初设窗口；由启动器传入 owner 时以模态方式打开。"""
    window = build_setup_window(owner)
    try:
        if owner is not None:
            window.form.ShowDialog(owner)
        else:
            window.form.ShowDialog()
    finally:
        window.form.Dispose()


def main():
    """在 STA 线程里跑界面。

    Windows 的“打开文件”是外壳对话框（COM），必须用 STA 线程，
    否则对话框创建不出来、主窗口却已经被模态禁用，看起来就是“打开后卡住、无法操作”。
    Hex_Editor/main.py 也是同样的写法。
    """
    def run():
        Application.EnableVisualStyles()
        Application.SetCompatibleTextRenderingDefault(False)
        open_setup_window()

    thread = Thread(ThreadStart(run))
    thread.SetApartmentState(ApartmentState.STA)
    thread.Start()
    thread.Join()
    return 0


if __name__ == '__main__':
    sys.exit(main())
