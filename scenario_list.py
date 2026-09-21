"""剧本列表：把已有的 .scenario 以图形卡片列出来，点一张进入它的图形化界面。

- build_gallery(owner=None, on_back=None)：返回一个面板（顶部条 + 卡片列表），
  可以直接塞进窗口里（new_game.py 就是这么用的）。
- open_in_editor(owner, path)：用初设编辑器（setup/setup.py）打开这个剧本——
  地图格子、格边、编制树和单位部署都会显示出来，这就是剧本的图形化界面。
- open_scenario_gallery(owner=None)：单独开一个窗口显示列表（直接运行本文件时用它）。

和 new_game.py / ui_background.py 一样，本文件是“按路径从磁盘加载”的，改完不用重新打包 exe。
"""
import importlib.util
import json
import math
import os
import sys
import time

import clr

clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from System import Array
from System.Drawing import (
    Bitmap,
    Color,
    Font,
    FontStyle,
    Graphics,
    Pen,
    Point,
    PointF,
    Rectangle,
    RectangleF,
    Size,
    SolidBrush,
    StringAlignment,
    StringFormat,
    TextureBrush,
)
from System.Drawing.Drawing2D import SmoothingMode, WrapMode
from System.Threading import ApartmentState, Thread, ThreadStart
from System.Windows.Forms import (
    Application,
    Button,
    Cursors,
    DockStyle,
    FlatStyle,
    FlowDirection,
    FlowLayoutPanel,
    Form,
    FormStartPosition,
    Label,
    MessageBox,
    MessageBoxButtons,
    MessageBoxIcon,
    Padding,
    Panel,
    PictureBox,
    PictureBoxSizeMode,
)

SCENARIO_SUFFIX = '.scenario'
SCENARIO_TYPE = 'SCENARIO'
# 剧本目录（相对项目根目录）：初设编辑器默认存到 setup/setupsaves
SCENARIO_FOLDERS = (('setup', 'setupsaves'), ('scenarios',))

EDITOR_FOLDER = 'setup'
EDITOR_SCRIPT = 'setup.py'
# 点剧本卡片后打开的游戏窗口（游戏本体的界面在 game_window.py）
GAME_MODULE = 'game_window'

# 卡片尺寸：缩略图按 A 系纸张的纵向比例留白，所以做成竖着的卡片
CARD_WIDTH = 260
CARD_HEIGHT = 460
CARD_PADDING = 14
THUMB_SIZE = Size(CARD_WIDTH - CARD_PADDING * 2, 300)

DARK_BACK = Color.FromArgb(28, 30, 34)
TOPBAR_BACK = Color.FromArgb(34, 37, 42)
CARD_BACK = Color.FromArgb(38, 41, 46)
MAP_MATTE = Color.FromArgb(20, 22, 25)
MAP_PAPER = Color.FromArgb(58, 60, 64)
MAP_BORDER = Color.FromArgb(120, 126, 134)
GRID_COLOR = Color.FromArgb(96, 102, 110)
RIVER_COLOR = Color.FromArgb(90, 140, 220)
TEXT_COLOR = Color.FromArgb(235, 235, 235)
DIM_TEXT = Color.FromArgb(165, 165, 165)
FAINT_TEXT = Color.FromArgb(130, 134, 140)
ERROR_COLOR = Color.FromArgb(232, 120, 120)

# 阵营配色（和初设编辑器 setup.py 里的规则一致：名字里带颜色字就按字面取色）
FACTION_COLORS = {
    '红': (198, 60, 60), '蓝': (58, 110, 200), '绿': (66, 145, 86),
    '黄': (188, 148, 40), '白': (140, 140, 140), '黑': (70, 70, 70),
}
FACTION_PALETTE = ((198, 60, 60), (58, 110, 200), (66, 145, 86),
                   (188, 148, 40), (140, 100, 190), (120, 120, 120))

# 地图边界上的格边方向：平顶六边形六个边朝向的角度（度，y 轴向下）
DIRECTION_ANGLES = {'SE': 30.0, 'S': 90.0, 'SW': 150.0,
                    'NW': 210.0, 'N': 270.0, 'NE': 330.0}

UNIT_MARKER_MIN = 6.0


def project_dir():
    """游戏文件所在目录：打包成 exe 后是 exe 所在目录，开发时是本文件所在目录。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _prepare_hex_editor_path():
    """把 Hex_Editor 放进 sys.path：地图几何（hexformat）和地形配色（hexmap）都在那里。"""
    directory = os.path.join(project_dir(), 'Hex_Editor')
    if os.path.isdir(directory) and directory not in sys.path:
        sys.path.insert(0, directory)
    return directory


_prepare_hex_editor_path()

try:
    from hexformat import hex_corners, hex_layout
    from hexmap import terrain_color

    HEX_LIB_ERROR = None
except Exception as _exc:                 # 缺文件也不该让列表打不开
    HEX_LIB_ERROR = '%s: %s' % (type(_exc).__name__, _exc)


def show_error(message, owner=None):
    if owner is not None:
        MessageBox.Show(owner, message, '选择剧本 - 出错', MessageBoxButtons.OK, MessageBoxIcon.Error)
    else:
        MessageBox.Show(message, '选择剧本 - 出错', MessageBoxButtons.OK, MessageBoxIcon.Error)


def _to_color(rgb):
    return Color.FromArgb(int(rgb[0]), int(rgb[1]), int(rgb[2]))


def faction_color(faction):
    """阵营 → RGB（规则同初设编辑器 setup.py）。"""
    text = str(faction or '')
    for key, rgb in FACTION_COLORS.items():
        if key in text:
            return rgb
    if not text:
        return FACTION_PALETTE[-1]
    total = sum(ord(ch) for ch in text)
    return FACTION_PALETTE[total % len(FACTION_PALETTE)]


def scenario_folders():
    """所有存在的剧本目录。"""
    root = project_dir()
    folders = []
    for parts in SCENARIO_FOLDERS:
        folder = os.path.join(root, *parts)
        if os.path.isdir(folder) and folder not in folders:
            folders.append(folder)
    return folders


def find_scenarios():
    """列出所有 .scenario，返回 [(路径, 修改时间, 大小)]，按修改时间从新到旧。"""
    found = []
    for folder in scenario_folders():
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            if not name.lower().endswith(SCENARIO_SUFFIX):
                continue
            path = os.path.join(folder, name)
            try:
                info = os.stat(path)
            except OSError:
                continue
            found.append((path, info.st_mtime, info.st_size))
    found.sort(key=lambda item: item[1], reverse=True)
    return found


def read_scenario(path):
    """读 .scenario，返回 (数据, 失败原因)。"""
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        return None, '%s: %s' % (type(exc).__name__, exc)
    if not isinstance(data, dict) or data.get('type') != SCENARIO_TYPE:
        return None, '不是初设文件（type 字段应为 %s）' % SCENARIO_TYPE
    return data, None


def scenario_titles(data, path):
    """卡片上的文字：名字 + 两三行概要。"""
    map_info = data.get('map') or {}
    paper = str(map_info.get('paper') or '?').upper()
    lines = []
    try:
        cols = int(map_info.get('cols') or 0)
        rows = int(map_info.get('rows') or 0)
    except (TypeError, ValueError):
        cols, rows = 0, 0
    lines.append('%s · %d 列 × %d 行' % ('自定义' if paper == 'CUSTOM' else paper, cols, rows))

    cells = data.get('cells') or {}
    edges = data.get('edges') or {}
    units = data.get('units') or []
    lines.append('地形 %d · 格边 %d · 单位 %d' % (len(cells), len(edges), len(units)))

    oob = data.get('oob') or {}
    faction = str(oob.get('faction') or '')
    army = str(oob.get('army') or '')
    if faction or army:
        lines.append('阵营 %s%s' % (faction or '—', (' · %s' % army) if army else ''))
    source = map_info.get('source_hex')
    if source:
        lines.append('地图 %s' % source)
    return lines


def group_units(units):
    """按格子把单位分组：{(列,行): [单位, ...]}。

    单位缺少 q/r 时退回解析 cell 字段（"列,行"），两条路都解析不出来就丢掉。
    """
    stacks = {}
    for unit in (units or []):
        q, r = unit.get('q'), unit.get('r')
        if q is None or r is None:
            cell_key = str(unit.get('cell') or '')
            if ',' not in cell_key:
                continue
            try:
                q, r = (int(part) for part in cell_key.split(',')[:2])
            except ValueError:
                continue
        stacks.setdefault((int(q), int(r)), []).append(unit)
    return stacks


def edge_segment(key, centers, cell):
    """格边键 → 一条线段（地图坐标）："列,行|列,行"（两格之间）或 "列,行|方向"（地图边界）。"""
    text = str(key)
    if '|' not in text:
        return None
    left, _, right = text.partition('|')
    try:
        q, r = (int(part) for part in left.split(',')[:2])
    except ValueError:
        return None
    center = centers.get((q, r))
    if center is None:
        return None

    if ',' in right:
        try:
            q2, r2 = (int(part) for part in right.split(',')[:2])
        except ValueError:
            return None
        other = centers.get((q2, r2))
        if other is None:
            return None
        return center, other

    angle = DIRECTION_ANGLES.get(right.strip().upper())
    if angle is None:
        return None
    rad = math.radians(angle)
    # 边中点离格心约 0.866 * 边长，线段沿边的方向、长度等于边长
    mid = (center[0] + cell * 0.866 * math.cos(rad), center[1] + cell * 0.866 * math.sin(rad))
    tangent = (math.cos(rad + math.pi / 2.0), math.sin(rad + math.pi / 2.0))
    half = cell * 0.5
    return ((mid[0] - tangent[0] * half, mid[1] - tangent[1] * half),
            (mid[0] + tangent[0] * half, mid[1] + tangent[1] * half))


def _draw_centered(graphics, box, text, color=None):
    font = Font('Microsoft YaHei UI', 9)
    brush = SolidBrush(color or DIM_TEXT)
    fmt = StringFormat()
    fmt.Alignment = StringAlignment.Center
    fmt.LineAlignment = StringAlignment.Center
    try:
        graphics.DrawString(text, font, brush, RectangleF(0.0, 0.0, float(box.Width), float(box.Height)), fmt)
    finally:
        font.Dispose()
        brush.Dispose()
        fmt.Dispose()


def grid_tile(cell, color):
    """做一张可以平铺的六角格线贴图：宽 3*cell、高 sqrt(3)*cell 正好是一个周期。

    逐格画 884 个六边形要 0.5 秒（pythonnet 每次调用都有开销），
    做成贴图后用 TextureBrush 一次铺满，快两个数量级。
    """
    step = math.sqrt(3.0) * cell
    width = max(2, int(math.ceil(3.0 * cell)))
    height = max(2, int(math.ceil(step)))
    tile = Bitmap(width, height)
    graphics = Graphics.FromImage(tile)
    pen = Pen(color)
    try:
        graphics.SmoothingMode = SmoothingMode.AntiAlias
        # 一个周期里有两种列：偶数列中心在 y = step/2，奇数列整体再下移半个格
        for cx, cy in ((cell, step / 2.0), (2.5 * cell, step)):
            corners = hex_corners(cx, cy, cell)
            for dx in (-width, 0, width):          # 贴上边缘的格子要补画，保证平铺无缝
                for dy in (-height, 0, height):
                    graphics.DrawPolygon(pen, Array[PointF]([
                        PointF(x + dx, y + dy) for x, y in corners
                    ]))
    finally:
        pen.Dispose()
        graphics.Dispose()
    return tile


def render_thumbnail(data, box):
    """把剧本地图画成缩略图：纸张底色 + 六角格 + 地形 + 格边（河流）+ 单位标记。"""
    bitmap = Bitmap(box.Width, box.Height)
    graphics = Graphics.FromImage(bitmap)
    disposables = []
    try:
        graphics.Clear(MAP_MATTE)
        graphics.SmoothingMode = SmoothingMode.AntiAlias

        map_info = data.get('map') or {}
        try:
            cols = int(map_info.get('cols') or 0)
            width = int(map_info.get('width') or 0)
            height = int(map_info.get('height') or 0)
        except (TypeError, ValueError):
            cols, width, height = 0, 0, 0

        if HEX_LIB_ERROR is not None:
            _draw_centered(graphics, box, '缺少 Hex_Editor 模块', ERROR_COLOR)
            return bitmap
        if cols < 1 or width < 1 or height < 1:
            _draw_centered(graphics, box, '地图信息不完整', ERROR_COLOR)
            return bitmap

        layout = hex_layout(cols, width, height, map_info.get('margins'))
        cell = float(layout['cell_size'])
        scale = min(box.Width / float(width), box.Height / float(height))
        offset_x = (box.Width - width * scale) / 2.0
        offset_y = (box.Height - height * scale) / 2.0

        centers = {}
        for q, r, cx, cy in layout['centers']:
            centers[(q, r)] = (cx, cy)

        paper_brush = SolidBrush(MAP_PAPER)
        disposables.append(paper_brush)
        graphics.FillRectangle(paper_brush, RectangleF(offset_x, offset_y,
                                                       width * scale, height * scale))

        border_pen = Pen(MAP_BORDER, 1.5)
        disposables.append(border_pen)
        edge_pen = Pen(RIVER_COLOR, max(1.5, cell * scale * 0.3))
        disposables.append(edge_pen)

        margins = map_info.get('margins') or {}
        margin_left = float(margins.get('l') or 0)
        margin_top = float(margins.get('t') or 0)

        # 网格：一张周期贴图平铺，一次 FillRectangle 画完
        if cell * scale >= 4.0:
            tile = grid_tile(cell * scale, GRID_COLOR)
            disposables.append(tile)
            texture = TextureBrush(tile)
            disposables.append(texture)
            texture.WrapMode = WrapMode.Tile
            texture.TranslateTransform(offset_x + margin_left * scale, offset_y + margin_top * scale)
            graphics.FillRectangle(texture, RectangleF(offset_x, offset_y,
                                                       width * scale, height * scale))
            texture.ResetTransform()

        # 地形：只画有地形的格子（一般不多）
        terrain = data.get('cells') or {}
        brushes = {}
        for (q, r), (cx, cy) in centers.items():
            name = terrain.get('%d,%d' % (q, r))
            if not name:
                continue
            key = str(name)
            brush = brushes.get(key)
            if brush is None:
                brush = SolidBrush(_to_color(terrain_color(key)))
                brushes[key] = brush
                disposables.append(brush)
            graphics.FillPolygon(brush, Array[PointF]([
                PointF(offset_x + x * scale, offset_y + y * scale)
                for x, y in hex_corners(cx, cy, cell)
            ]))

        for key, value in (data.get('edges') or {}).items():
            name = value[0] if isinstance(value, (list, tuple)) and value else value
            if not name:
                continue
            segment = edge_segment(key, centers, cell)
            if segment is None:
                continue
            (x1, y1), (x2, y2) = segment
            graphics.DrawLine(edge_pen,
                              PointF(offset_x + x1 * scale, offset_y + y1 * scale),
                              PointF(offset_x + x2 * scale, offset_y + y2 * scale))

        stacks = group_units(data.get('units'))

        marker = max(UNIT_MARKER_MIN, cell * scale * 1.1)
        count_font = Font('Microsoft YaHei UI', 6)
        disposables.append(count_font)
        count_format = StringFormat()
        count_format.Alignment = StringAlignment.Center
        count_format.LineAlignment = StringAlignment.Center
        disposables.append(count_format)
        count_brush = SolidBrush(Color.White)
        disposables.append(count_brush)
        for (q, r), units in stacks.items():
            center = centers.get((q, r))
            if center is None:
                continue
            cx = offset_x + center[0] * scale
            cy = offset_y + center[1] * scale
            brush = SolidBrush(_to_color(faction_color(units[0].get('faction'))))
            disposables.append(brush)
            graphics.FillRectangle(brush, RectangleF(cx - marker / 2.0, cy - marker / 2.0,
                                                     marker, marker))
            if marker >= 9.0 and len(units) > 1:
                graphics.DrawString(str(len(units)), count_font, count_brush,
                                    RectangleF(cx - marker, cy - marker, marker * 2.0, marker * 2.0),
                                    count_format)

        # DrawRectangle 的 RectangleF 重载在 pythonnet 里匹配不上，直接传 4 个 float
        graphics.DrawRectangle(border_pen, float(offset_x), float(offset_y),
                               float(max(1.0, width * scale - 1.0)),
                               float(max(1.0, height * scale - 1.0)))
        return bitmap
    finally:
        for item in disposables:
            item.Dispose()
        graphics.Dispose()


def _text_label(text, size, color, width, bold=False, height=None):
    label = Label()
    label.Text = text
    label.AutoSize = False
    label.Width = width
    label.Height = height or int(size * 2.3)
    label.Font = Font('Microsoft YaHei UI', size, FontStyle.Bold if bold else FontStyle.Regular)
    label.ForeColor = color
    label.BackColor = Color.Transparent
    label.Cursor = Cursors.Hand
    return label


def _bar_button(text, width=96):
    button = Button()
    button.Text = text
    button.Size = Size(width, 32)
    button.FlatStyle = FlatStyle.System
    return button


def make_card(owner, path, mtime, size, on_open=None):
    """一张剧本卡片：缩略图 + 名字 + 概要；点它就用初设编辑器打开这个剧本。

    卡片本身用“无边框按钮”当容器：按钮才自带 PerformClick、也认 BM_CLICK，
    这样脚本能点它，键盘 Tab 也能选中它；内容（缩略图、文字）都是它的子控件。
    """
    data, reason = read_scenario(path)
    card = Button()
    card.Size = Size(CARD_WIDTH, CARD_HEIGHT)
    card.BackColor = CARD_BACK
    card.FlatStyle = FlatStyle.Flat
    card.UseVisualStyleBackColor = False
    card.FlatAppearance.BorderSize = 0
    card.Text = ''                       # 文字都交给子控件排，按钮自己不画字
    card.TabStop = True
    card.Margin = Padding(10)
    card.Cursor = Cursors.Hand

    picture = PictureBox()
    picture.Location = Point(CARD_PADDING, CARD_PADDING)
    picture.Size = THUMB_SIZE
    picture.SizeMode = PictureBoxSizeMode.Normal
    picture.Cursor = Cursors.Hand
    if data is not None:
        picture.Image = render_thumbnail(data, THUMB_SIZE)
    else:
        placeholder = Bitmap(THUMB_SIZE.Width, THUMB_SIZE.Height)
        graphics = Graphics.FromImage(placeholder)
        graphics.Clear(MAP_MATTE)
        _draw_centered(graphics, THUMB_SIZE, '读取失败', ERROR_COLOR)
        graphics.Dispose()
        picture.Image = placeholder
    card.Controls.Add(picture)

    clickable = [card, picture]
    text_width = CARD_WIDTH - CARD_PADDING * 2

    title = _text_label(os.path.splitext(os.path.basename(path))[0], 12, TEXT_COLOR,
                        text_width, bold=True)
    title.Location = Point(CARD_PADDING, CARD_PADDING + THUMB_SIZE.Height + 8)
    card.Controls.Add(title)
    clickable.append(title)

    y = title.Location.Y + title.Height
    lines = scenario_titles(data, path) if data is not None else ['读取失败：%s' % reason]
    for index, line in enumerate(lines):
        label = _text_label(line, 9, ERROR_COLOR if data is None else DIM_TEXT, text_width)
        label.Location = Point(CARD_PADDING, y)
        card.Controls.Add(label)
        clickable.append(label)
        y += label.Height
        if data is None and index == 0:
            break

    footer = _text_label('%s · %s' % (os.path.basename(path),
                                      time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime))),
                         8, FAINT_TEXT, text_width)
    footer.Location = Point(CARD_PADDING, CARD_HEIGHT - CARD_PADDING - footer.Height)
    card.Controls.Add(footer)
    clickable.append(footer)

    def open_card(sender=None, event=None):
        if data is None:
            show_error('读取剧本失败：\n\n%s\n（%s）' % (path, reason), owner)
            return
        if on_open is not None:
            on_open(path)          # 交给宿主窗口决定怎么切（比如先关掉自己再开游戏窗口）
        else:
            open_in_game(owner, path)

    for control in clickable:
        control.Click += open_card
    return card


def make_empty_hint(owner):
    """一个剧本都没有时的提示。"""
    panel = Panel()
    panel.Size = Size(520, 190)
    panel.BackColor = CARD_BACK
    panel.Margin = Padding(10)

    title = _text_label('还没有找到 .scenario 剧本', 12, TEXT_COLOR, 480, bold=True)
    title.Location = Point(20, 18)
    title.Cursor = Cursors.Default
    panel.Controls.Add(title)

    folders = scenario_folders()
    hint = _text_label('查找目录：%s\n\n' % ('、'.join(folders) if folders else project_dir()) +
                       '可以用左侧栏的“初设”工具新建剧本并“保存 .scenario”，再回来点“刷新”。',
                       9, DIM_TEXT, 480, height=76)
    hint.Location = Point(20, 52)
    hint.Cursor = Cursors.Default
    panel.Controls.Add(hint)

    button = _bar_button('打开初设编辑器', 160)
    button.Location = Point(20, 138)
    button.Click += lambda sender, event: open_in_editor(owner, None)
    panel.Controls.Add(button)
    return panel


def _dispose_card(card):
    """销毁卡片前先释放缩略图，否则 Bitmap 会一直占着 GDI+ 对象。"""
    try:
        for control in card.Controls:
            if isinstance(control, PictureBox) and control.Image is not None:
                control.Image.Dispose()
                control.Image = None
    except Exception:
        pass
    card.Dispose()


def build_gallery(owner=None, on_back=None, on_open=None):
    """构造剧本列表面板：顶部条（返回 / 标题 / 刷新）+ 竖排卡片列表。

    on_open(path)：点卡片时调用；不传就默认打开游戏窗口。
    """
    panel = Panel()
    panel.Dock = DockStyle.Fill
    panel.BackColor = DARK_BACK

    listings = FlowLayoutPanel()
    listings.Dock = DockStyle.Fill
    listings.AutoScroll = True
    listings.WrapContents = True
    listings.FlowDirection = FlowDirection.LeftToRight
    listings.BackColor = DARK_BACK
    listings.Padding = Padding(10)
    panel.Controls.Add(listings)

    top = Panel()
    top.Dock = DockStyle.Top
    top.Height = 52
    top.BackColor = TOPBAR_BACK

    if on_back is not None:
        back = _bar_button('← 返回')
        back.Location = Point(12, 10)
        back.Click += lambda sender, event: on_back()
        top.Controls.Add(back)

    refresh = _bar_button('刷新')
    refresh.Click += lambda sender, event: reload_cards()

    title = Label()
    title.Text = '选择剧本'
    title.AutoSize = True
    title.Font = Font('Microsoft YaHei UI', 12, FontStyle.Bold)
    title.ForeColor = TEXT_COLOR
    title.BackColor = Color.Transparent
    title.Location = Point(124, 15)
    top.Controls.Add(title)

    count_label = Label()
    count_label.AutoSize = True
    count_label.Font = Font('Microsoft YaHei UI', 9)
    count_label.ForeColor = DIM_TEXT
    count_label.BackColor = Color.Transparent
    count_label.Location = Point(232, 20)
    top.Controls.Add(count_label)

    top.Controls.Add(refresh)

    def place_top_controls():
        refresh.Location = Point(max(260, top.ClientSize.Width - refresh.Width - 12), 10)

    top.Resize += lambda sender, event: place_top_controls()
    place_top_controls()

    panel.Controls.Add(top)

    def reload_cards():
        listings.SuspendLayout()
        for control in list(listings.Controls):
            listings.Controls.Remove(control)
            _dispose_card(control)
        entries = find_scenarios()
        if entries:
            for path, mtime, size in entries:
                listings.Controls.Add(make_card(owner, path, mtime, size, on_open))
        else:
            listings.Controls.Add(make_empty_hint(owner))
        count_label.Text = '找到 %d 个剧本' % len(entries)
        listings.ResumeLayout()

    reload_cards()
    return panel


def load_editor_module():
    """从磁盘加载初设编辑器（setup/setup.py）。"""
    path = os.path.join(project_dir(), EDITOR_FOLDER, EDITOR_SCRIPT)
    if not os.path.isfile(path):
        return None, '找不到 %s' % path
    try:
        spec = importlib.util.spec_from_file_location('setup_tool', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, None
    except Exception as exc:
        return None, '%s: %s' % (type(exc).__name__, exc)


def load_local_module(name):
    """从项目根目录按路径加载 <name>.py（不打包进 exe，改完立刻生效）。"""
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


def open_in_game(owner, path):
    """点剧本卡片：按这个剧本的初设打开游戏窗口。"""
    try:
        module = load_local_module(GAME_MODULE)
    except Exception as exc:
        show_error('打开游戏窗口失败：\n\n%s: %s' % (type(exc).__name__, exc), owner)
        return False
    try:
        return module.open_game_window(owner, path)
    except Exception as exc:
        show_error('游戏窗口出错：\n\n%s: %s' % (type(exc).__name__, exc), owner)
        return False


def open_in_editor(owner, path):
    """打开剧本的图形化界面：用初设编辑器载入这个剧本（path 为 None 就开个空的编辑器）。

    编辑器跑在独立的 STA 线程里：Windows 的“打开文件”对话框需要 STA 线程，
    而且这样它是独立窗口，不会把启动器卡住。
    """
    module, reason = load_editor_module()
    if module is None:
        show_error('打开初设编辑器失败：\n\n%s' % reason, owner)
        return False

    def run():
        try:
            window = module.build_setup_window(None)
            try:
                if path is not None and not window.load_scenario_file(path):
                    window.form.Dispose()
                    return
                # 剧本是在窗口显示前载入的，显示后再适应一次窗口，免得缩放不对
                window.form.Shown += lambda sender, event: window.on_zoom_fit()
                window.form.ShowDialog()
            finally:
                window.form.Dispose()
        except Exception as exc:
            show_error('初设编辑器出错：\n\n%s: %s' % (type(exc).__name__, exc))

    thread = Thread(ThreadStart(run))
    thread.SetApartmentState(ApartmentState.STA)
    thread.Start()
    return True


def open_scenario_gallery(owner=None):
    """单独开一个窗口显示剧本列表（直接运行本文件时用它）。"""
    form = Form()
    form.Text = '选择剧本'
    form.ClientSize = Size(1024, 640)
    form.MinimumSize = Size(680, 440)
    if owner is not None:
        form.StartPosition = FormStartPosition.CenterParent
    else:
        form.StartPosition = FormStartPosition.CenterScreen
    form.Controls.Add(build_gallery(owner, on_back=None))
    try:
        if owner is not None:
            form.ShowDialog(owner)
        else:
            form.ShowDialog()
    finally:
        form.Dispose()


def main():
    """在 STA 线程里跑界面（和 setup.py / Hex_Editor 的写法一致）。"""
    def run():
        Application.EnableVisualStyles()
        Application.SetCompatibleTextRenderingDefault(False)
        open_scenario_gallery()

    thread = Thread(ThreadStart(run))
    thread.SetApartmentState(ApartmentState.STA)
    thread.Start()
    thread.Join()
    return 0


if __name__ == '__main__':
    sys.exit(main())
