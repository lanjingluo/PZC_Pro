"""初设窗口（Python + WinForms）+ 六角格地图预览。

运行方式：命令行执行 python setup.py（在 setup 目录里双击也可以）
窗口一打开就会弹出“打开 .hex 文件”对话框；选中六角格画布（HEXMAP）文件后，
用 Hex_Editor 的解析逻辑读出纸张、格子数与地形，画在窗口里的地图画布上。

地图几何（hexformat.hex_layout）和配色（hexmap 里的地形表）都直接复用 Hex_Editor 的模块，
所以这里画出来的效果和 Hex Editor 打开同一个文件时一致。

界面背景图：basic_picture_resources/background2.jpg（每次打开窗口都从磁盘读，换图不用重新打包）
"""
import importlib.util
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
    Color,
    ContentAlignment,
    Font,
    Pen,
    Point,
    PointF,
    Rectangle,
    Size,
    SolidBrush,
)
from System.Drawing.Drawing2D import GraphicsPath, LineCap, LineJoin
from System.Threading import ApartmentState, Thread, ThreadStart
from System.Windows.Forms import (
    Application,
    Button,
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
    OpenFileDialog,
    Panel,
    PictureBox,
    PictureBoxSizeMode,
    StatusStrip,
    Timer,
    ToolStripStatusLabel,
)

WINDOW_TITLE = '初设'
WINDOW_SIZE = Size(1000, 700)
MINIMUM_SIZE = Size(640, 420)

BACKGROUND_MODULE = 'ui_background'
BACKGROUND_RELATIVE_PATH = os.path.join('basic_picture_resources', 'background2.jpg')
FALLBACK_BACK_COLOR = Color.FromArgb(32, 34, 38)

# 地图渲染参数：与 Hex_Editor/main.py 保持一致
GRID_PEN_WIDTH = 2.0
EDGE_PEN_WIDTH = 6.0
MIN_ZOOM = 0.1
MAX_ZOOM = 8.0
ZOOM_STEP = 1.25


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


# hexmap.py 里写的是 `from hexformat import ...`，所以 Hex_Editor 得先进 sys.path
_HEX_EDITOR_DIR = hex_editor_dir()
if os.path.isdir(_HEX_EDITOR_DIR) and _HEX_EDITOR_DIR not in sys.path:
    sys.path.insert(0, _HEX_EDITOR_DIR)

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
        self._auto_open_done = False

        # 缩放/改变大小时先攒一下再重绘，避免卡顿（和 Hex Editor 一样 120ms）
        self._render_timer = Timer()
        self._render_timer.Interval = 120
        self._render_timer.Tick += self.on_render_timer_tick

        self.form = Form()
        self.form.Text = WINDOW_TITLE
        self.form.ClientSize = WINDOW_SIZE
        self.form.MinimumSize = MINIMUM_SIZE
        self.form.StartPosition = FormStartPosition.CenterScreen
        self.form.Font = Font('Microsoft YaHei UI', 9)
        apply_background(self.form)

        self._build_canvas()        # Fill 的先加，下面的工具条/状态栏才不会被盖住
        self._build_toolbar()
        self._build_status_bar()
        self._build_hint()

        self.form.Resize += self.on_form_resize
        self.form.Shown += self.on_form_shown
        self.form.FormClosed += self.on_form_closed

    # ---------- 界面构建 ----------
    def _build_toolbar(self):
        self.top_bar = Panel()
        self.top_bar.Dock = DockStyle.Top
        self.top_bar.Height = 44
        self.top_bar.BackColor = Color.FromArgb(45, 48, 54)
        self.form.Controls.Add(self.top_bar)

        self.open_button = Button()
        self.open_button.Text = '打开 .hex 文件...'
        self.open_button.Location = Point(10, 8)
        self.open_button.Size = Size(140, 28)
        self.open_button.FlatStyle = FlatStyle.System
        self.open_button.Click += self.on_open_click
        self.top_bar.Controls.Add(self.open_button)

        self._make_zoom_button('缩小', 160, 44, self.on_zoom_out)
        self._make_zoom_button('放大', 208, 44, self.on_zoom_in)
        self._make_zoom_button('适应窗口', 256, 84, self.on_zoom_fit)

        self.zoom_label = Label()
        self.zoom_label.Text = '100%'
        self.zoom_label.ForeColor = Color.White
        self.zoom_label.Location = Point(350, 14)
        self.zoom_label.AutoSize = True
        self.top_bar.Controls.Add(self.zoom_label)

        self.file_label = Label()
        self.file_label.Text = '（还没有打开文件）'
        self.file_label.ForeColor = Color.FromArgb(210, 210, 210)
        self.file_label.Location = Point(412, 14)
        self.file_label.AutoSize = True
        self.top_bar.Controls.Add(self.file_label)

    def _make_zoom_button(self, text, x, width, handler):
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

        self.canvas_box = PictureBox()
        self.canvas_box.SizeMode = PictureBoxSizeMode.Normal
        self.canvas_box.BackColor = Color.White
        self.canvas_box.Location = Point(0, 0)
        self.canvas_box.Size = Size(1, 1)
        self.canvas_box.Paint += self.on_canvas_paint
        self.canvas_box.MouseWheel += self.on_canvas_mouse_wheel
        self.canvas_scroll.Controls.Add(self.canvas_box)
        self.form.Controls.Add(self.canvas_scroll)

    def _build_status_bar(self):
        self.status_bar = StatusStrip()
        self.status_label = ToolStripStatusLabel('正在等待打开 .hex 文件...')
        self.status_bar.Items.Add(self.status_label)
        self.form.Controls.Add(self.status_bar)

    def _build_hint(self):
        self.hint_label = Label()
        self.hint_label.Text = '还没有打开地图\r\n点击“打开 .hex 文件...”选择六角格画布'
        self.hint_label.Font = Font('Microsoft YaHei UI', 12)
        self.hint_label.ForeColor = Color.White
        self.hint_label.BackColor = Color.Transparent
        self.hint_label.TextAlign = ContentAlignment.MiddleCenter
        self.hint_label.AutoSize = True
        self.form.Controls.Add(self.hint_label)
        self.center_hint()

    def center_hint(self):
        width = max(1, self.form.ClientSize.Width)
        height = max(1, self.form.ClientSize.Height)
        self.hint_label.Location = Point(
            max(0, (width - self.hint_label.Width) // 2),
            max(0, (height - self.hint_label.Height) // 2),
        )

    # ---------- 打开 / 解析 .hex ----------
    def on_form_shown(self, sender, e):
        """窗口一显示就弹出“打开 .hex 文件”对话框（只自动弹一次）。

        注意：不能在 Shown 事件里直接 ShowDialog——那时窗口还没完成激活，
        模态对话框会和它互相等待，结果是对话框不出现、主窗口已被禁用，
        Windows 直接把窗口标成“未响应”。所以用 BeginInvoke 把弹窗排进消息队列，
        等 Shown 处理完、窗口真正激活之后再弹。
        """
        if self._auto_open_done:
            return
        self._auto_open_done = True
        self.form.BeginInvoke(EventHandler(self.on_deferred_open))

    def on_deferred_open(self, sender=None, e=None):
        """BeginInvoke 排过来的“第一次弹窗”。"""
        try:
            self.form.Activate()
            self.open_hex_file()
        except Exception as exc:            # 弹窗这一步出问题也不该让窗口卡住
            show_error('打开文件对话框出错：\n\n%s: %s' % (type(exc).__name__, exc))
            self.set_status('打开文件对话框出错；可以点“打开 .hex 文件...”重试')

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
        dlg.Filter = 'Hex 文件 (*.hex)|*.hex|所有文件 (*.*)|*.*'
        dlg.InitialDirectory = saves if os.path.isdir(saves) else project_dir()
        if dlg.ShowDialog(self.form) != DialogResult.OK:
            self.set_status('没有选择文件；点击“打开 .hex 文件...”可以重试')
            return
        self.load_hex_file(dlg.FileName)

    def load_hex_file(self, path):
        """读文件 → 解析 .hex 容器 → 解析画布文档 → 画到地图上。"""
        try:
            with open(path, 'rb') as handle:
                raw = handle.read()
        except OSError as exc:
            show_error('读取文件失败：\n\n%s: %s' % (type(exc).__name__, exc))
            return False

        info = read_hex_container(raw)
        if not info['is_hex']:
            show_error('这不是 .hex 容器文件（缺少 HEX1 魔数）：\n\n%s' % path)
            self.set_status('打开失败：不是 .hex 容器文件')
            return False

        doc = parse_hex_map_payload(info['payload'])
        if doc is None:
            show_error(
                '这个 .hex 里的内容不是六角格画布，没法画成地图。\n\n'
                '文件：%s\n内容类型：%s\n\n'
                '（只有 Hex Editor 保存的 HEXMAP 画布才能显示成地图）'
                % (path, info['original_type'] or '未知')
            )
            self.set_status('打开失败：内容类型 %s 不是六角格画布' % (info['original_type'] or '未知'))
            return False

        self.file_path = path
        self.show_map(doc)
        self.form.Text = '%s - %s' % (os.path.basename(path), WINDOW_TITLE)
        return True

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
        view_w = max(1, self.canvas_scroll.ClientSize.Width)
        view_h = max(1, self.canvas_scroll.ClientSize.Height)
        doc_w, doc_h = self.map_size
        return min(view_w / float(max(1, doc_w)), view_h / float(max(1, doc_h)))

    def set_zoom(self, zoom, auto_fit=False):
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, float(zoom)))
        self.auto_fit = bool(auto_fit)
        self.zoom_label.Text = '%d%%' % round(self.zoom * 100)
        self.schedule_render()

    def on_zoom_in(self, sender=None, e=None):
        self.set_zoom(self.zoom * ZOOM_STEP)

    def on_zoom_out(self, sender=None, e=None):
        self.set_zoom(self.zoom / ZOOM_STEP)

    def on_zoom_fit(self, sender=None, e=None):
        self.set_zoom(self.fit_zoom(), auto_fit=True)

    def on_canvas_mouse_wheel(self, sender, e):
        """Ctrl + 滚轮缩放（和 Hex Editor 一样）。"""
        if not (Control.ModifierKeys & Keys.Control):
            return
        self.set_zoom(self.zoom * (ZOOM_STEP if e.Delta > 0 else 1.0 / ZOOM_STEP))

    def on_canvas_resize(self, sender, e):
        if self.auto_fit and self.hex_map is not None:
            self.set_zoom(self.fit_zoom(), auto_fit=True)

    def on_form_resize(self, sender, e):
        if self.hint_label.Visible:
            self.center_hint()

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
        self.render_paths()
        self.canvas_box.Invalidate()

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

    # ---------- 其它 ----------
    def set_status(self, text):
        self.status_label.Text = text

    def on_form_closed(self, sender, e):
        self._render_timer.Stop()
        self.clear_paths()


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
