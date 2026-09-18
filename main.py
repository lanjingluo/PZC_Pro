"""Hex Editor - 窗口应用（Python + WinForms）
运行方式：双击 run.bat，或命令行运行 python main.py
文件格式：本软件创建/保存的文件为自定义 .hex 容器格式，
用于存储特定类型的文件。
结构：魔数 HEX1(4) + 原始类型(8) + 数据长度(8) + 原始内容
六角格画布：新建空白画布时选择 A1-A4 纸张，整张画布被平顶正六边形覆盖；
通过顶部输入框或滑块调整横向格子数，格子大小随纸张尺寸与格子数自动计算；确认格子后再保存，也可从图片识别格子布局。
"""
import os

try:
    import clr
except ImportError:
    import ctypes
    ctypes.windll.user32.MessageBoxW(
        0,
        '缺少依赖 pythonnet，程序无法启动。\n\n请在命令行执行：\n    python -m pip install pythonnet',
        'Hex Editor - 缺少依赖',
        0x10,
    )
    raise SystemExit(1)
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
import System.Windows.Forms
import System.Drawing
from System.Windows.Forms import (
    Application,
    Button,
    ComboBox,
    ComboBoxStyle,
    Control,
    DialogResult,
    DockStyle,
    Form,
    FormBorderStyle,
    FormStartPosition,
    Keys,
    Label,
    MenuStrip,
    MessageBox,
    OpenFileDialog,
    Padding,
    Panel,
    PictureBox,
    PictureBoxSizeMode,
    SaveFileDialog,
    ScrollBars,
    StatusStrip,
    TextBox,
    ToolStripMenuItem,
    ToolStripSeparator,
    ToolStripStatusLabel,
    Timer,
    TrackBar,
)
from System.Threading import ApartmentState, Thread, ThreadStart
from System.Drawing import Bitmap, Color, Font, Graphics, Pen, Point, PointF, Rectangle, Size
from System.Drawing.Drawing2D import GraphicsPath, InterpolationMode
import System
from hexformat import (
    MAP_TYPE,
    format_hex_view,
    hex_corners,
    hex_layout,
    make_hex_container,
    make_hex_map_payload,
    map_canvas_size,
    paper_size_pixels,
    parse_hex_map_payload,
    read_hex_container,
)
from hexmap import HexMap, normalize_margins
try:
    from imagedetect import detect_hex_grid
except Exception:
    detect_hex_grid = None
MAX_DISPLAY_BYTES = 512 * 1024
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SAVES_DIR = os.path.join(PROJECT_DIR, 'saves')
os.makedirs(SAVES_DIR, exist_ok=True)
DOCUMENTS_DIR = System.Environment.GetFolderPath(System.Environment.SpecialFolder.MyDocuments)
PICTURES_DIR = System.Environment.GetFolderPath(System.Environment.SpecialFolder.MyPictures)
IMAGE_FILTER = (
    '图片文件 (*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.tif;*.tiff;*.webp;*.ico)'
    '|*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.tif;*.tiff;*.webp;*.ico'
    '|所有文件 (*.*)|*.*'
)
PAPER_ORDER = ['A1', 'A2', 'A3', 'A4']
PAPER_LABELS = [
    'A1（594×841 mm）',
    'A2（420×594 mm）',
    'A3（297×420 mm）',
    'A4（210×297 mm）',
]
MIN_COLS = 1
MAX_COLS = 100
DEFAULT_COLS = 12
MIN_ZOOM = 0.1
MAX_ZOOM = 8.0
ZOOM_STEP = 1.25
GRID_PEN_WIDTH = 2.0
class HexEditorApp:
    """主窗口应用。"""
    def __init__(self):
        self.file_bytes = b''
        self.file_path = None
        self.original_type = 'BIN'
        self.is_hex_file = False
        # 六角格画布状态
        self.mode = 'hex'          # 'hex' 或 'map'
        self.map_paper = 'A4'
        self.map_cols = DEFAULT_COLS
        self.map_width = None
        self.map_height = None
        self.map_margins = {}
        self._syncing = False
        self._grid_path = None
        self.hex_map = None
        self.zoom = 1.0
        self._render_timer = Timer()
        self._render_timer.Interval = 120
        self._render_timer.Tick += self.on_render_timer_tick
        self.form = Form()
        self.form.Text = '未命名 - Hex Editor'
        self.form.Size = Size(960, 640)
        self.form.StartPosition = FormStartPosition.CenterScreen
        self.form.Font = Font('Microsoft YaHei UI', 9)
        self._build_menu()
        self._build_main_area()
        self._build_status_bar()
    # ---------- 界面构建 ----------
    def _build_menu(self):
        menubar = MenuStrip()
        file_menu = ToolStripMenuItem('文件')
        new_map_item = ToolStripMenuItem('新建六角格画布...')
        new_map_item.ShortcutKeys = Keys.Control | Keys.N
        new_map_item.Click += self.new_hex_map
        open_item = ToolStripMenuItem('打开文件...')
        open_item.ShortcutKeys = Keys.Control | Keys.O
        open_item.Click += self.open_file
        save_item = ToolStripMenuItem('保存')
        save_item.ShortcutKeys = Keys.Control | Keys.S
        save_item.Click += self.save_file
        save_as_item = ToolStripMenuItem('另存为...')
        save_as_item.ShortcutKeys = Keys.Control | Keys.Shift | Keys.S
        save_as_item.Click += self.save_as
        export_item = ToolStripMenuItem('导出原始文件...')
        export_item.ShortcutKeys = Keys.Control | Keys.E
        export_item.Click += self.export_original
        exit_item = ToolStripMenuItem('退出')
        exit_item.Click += self.close_app
        file_menu.DropDownItems.Add(new_map_item)
        file_menu.DropDownItems.Add(open_item)
        file_menu.DropDownItems.Add(save_item)
        file_menu.DropDownItems.Add(save_as_item)
        file_menu.DropDownItems.Add(export_item)
        file_menu.DropDownItems.Add(ToolStripSeparator())
        file_menu.DropDownItems.Add(exit_item)
        view_menu = ToolStripMenuItem('视图')
        zoom_in_item = ToolStripMenuItem('放大')
        zoom_in_item.ShortcutKeys = Keys.Control | Keys.Oemplus
        zoom_in_item.Click += self.on_zoom_in
        zoom_out_item = ToolStripMenuItem('缩小')
        zoom_out_item.ShortcutKeys = Keys.Control | Keys.OemMinus
        zoom_out_item.Click += self.on_zoom_out
        zoom_reset_item = ToolStripMenuItem('实际大小')
        zoom_reset_item.ShortcutKeys = Keys.Control | Keys.D0
        zoom_reset_item.Click += self.on_zoom_reset
        view_menu.DropDownItems.Add(zoom_in_item)
        view_menu.DropDownItems.Add(zoom_out_item)
        view_menu.DropDownItems.Add(zoom_reset_item)
        help_menu = ToolStripMenuItem('帮助')
        about_item = ToolStripMenuItem('关于')
        about_item.Click += self.show_about
        help_menu.DropDownItems.Add(about_item)
        menubar.Items.Add(file_menu)
        menubar.Items.Add(view_menu)
        menubar.Items.Add(help_menu)
        self.form.MainMenuStrip = menubar
        self.form.Controls.Add(menubar)
    def _build_main_area(self):
        # 十六进制视图
        self.text_box = TextBox()
        self.text_box.Multiline = True
        self.text_box.ReadOnly = True
        self.text_box.ScrollBars = ScrollBars.Both
        self.text_box.WordWrap = False
        self.text_box.Font = Font('Consolas', 11)
        self.text_box.Dock = DockStyle.Fill
        self.text_box.Text = '新建文件已就绪。\r\n保存时默认生成 .hex 文件，用于存储特定类型的文件。'
        self.form.Controls.Add(self.text_box)
        # 六角格画布顶部栏：横向格子数输入框 + 下方滑块
        self.top_bar = Panel()
        self.top_bar.Dock = DockStyle.Top
        self.top_bar.Height = 152
        self.top_bar.Padding = Padding(8, 4, 8, 4)
        self.cols_label = Label()
        self.cols_label.Text = '横向格子数：'
        self.cols_label.Location = Point(12, 10)
        self.cols_label.AutoSize = True
        self.top_bar.Controls.Add(self.cols_label)
        self.cols_box = TextBox()
        self.cols_box.Location = Point(108, 6)
        self.cols_box.Size = Size(64, 26)
        self.cols_box.Text = str(DEFAULT_COLS)
        self.cols_box.TextChanged += self.on_cols_text_changed
        self.top_bar.Controls.Add(self.cols_box)
        self.cols_track = TrackBar()
        self.cols_track.Location = Point(180, 2)
        self.cols_track.Size = Size(320, 40)
        self.cols_track.Minimum = MIN_COLS
        self.cols_track.Maximum = MAX_COLS
        self.cols_track.Value = DEFAULT_COLS
        self.cols_track.SmallChange = 1
        self.cols_track.LargeChange = 5
        self.cols_track.TickFrequency = 5
        self.cols_track.ValueChanged += self.on_cols_track_changed
        self.top_bar.Controls.Add(self.cols_track)
        self.detect_button = Button()
        self.detect_button.Text = '从图片识别格子...'
        self.detect_button.Location = Point(108, 72)
        self.detect_button.Size = Size(150, 28)
        self.detect_button.Click += self.on_detect_image
        self.top_bar.Controls.Add(self.detect_button)
        self.confirm_button = Button()
        self.confirm_button.Text = '确认格子并保存...'
        self.confirm_button.Location = Point(268, 72)
        self.confirm_button.Size = Size(150, 28)
        self.confirm_button.Click += self.confirm_and_save
        self.top_bar.Controls.Add(self.confirm_button)
        self.zoom_out_button = Button()
        self.zoom_out_button.Text = '缩小'
        self.zoom_out_button.Location = Point(438, 72)
        self.zoom_out_button.Size = Size(44, 28)
        self.zoom_out_button.Click += self.on_zoom_out
        self.top_bar.Controls.Add(self.zoom_out_button)
        self.zoom_in_button = Button()
        self.zoom_in_button.Text = '放大'
        self.zoom_in_button.Location = Point(488, 72)
        self.zoom_in_button.Size = Size(44, 28)
        self.zoom_in_button.Click += self.on_zoom_in
        self.top_bar.Controls.Add(self.zoom_in_button)
        self.zoom_reset_button = Button()
        self.zoom_reset_button.Text = '100%'
        self.zoom_reset_button.Location = Point(538, 72)
        self.zoom_reset_button.Size = Size(56, 28)
        self.zoom_reset_button.Click += self.on_zoom_reset
        self.top_bar.Controls.Add(self.zoom_reset_button)
        self.zoom_label = Label()
        self.zoom_label.AutoSize = True
        self.zoom_label.Text = '100%'
        self.zoom_label.Location = Point(602, 78)
        self.top_bar.Controls.Add(self.zoom_label)
        self.map_info_label = Label()
        self.map_info_label.AutoSize = True
        self.map_info_label.Location = Point(12, 112)
        self.top_bar.Controls.Add(self.map_info_label)
        # 六角格画布（可滚动）
        self.canvas_scroll = Panel()
        self.canvas_scroll.Dock = DockStyle.Fill
        self.canvas_scroll.AutoScroll = True
        self.canvas_box = PictureBox()
        self.canvas_box.SizeMode = PictureBoxSizeMode.Normal
        self.canvas_box.BackColor = Color.White
        self.canvas_box.Paint += self.on_canvas_paint
        self.canvas_box.MouseWheel += self.on_canvas_mouse_wheel
        self.canvas_scroll.Controls.Add(self.canvas_box)
        self.top_bar.Visible = False
        self.canvas_scroll.Visible = False
        self.form.Controls.Add(self.top_bar)
        self.form.Controls.Add(self.canvas_scroll)
    def _build_status_bar(self):
        self.status_bar = StatusStrip()
        self.status_label = ToolStripStatusLabel('就绪')
        self.status_bar.Items.Add(self.status_label)
        self.form.Controls.Add(self.status_bar)
    # ---------- 界面辅助 ----------
    def set_status(self, text):
        self.status_label.Text = text
    def update_title(self):
        if self.file_path:
            self.form.Text = f'{os.path.basename(self.file_path)} - Hex Editor'
        else:
            self.form.Text = '未命名 - Hex Editor'
    def show_hex_view(self):
        self.mode = 'hex'
        self.top_bar.Visible = False
        self.canvas_scroll.Visible = False
        self.text_box.Visible = True
        if len(self.file_bytes) == 0:
            self.text_box.Text = '（空文件）\r\n保存时默认生成 .hex 文件，用于存储特定类型的文件。'
        else:
            self.text_box.Text = format_hex_view(self.file_bytes, MAX_DISPLAY_BYTES)
    def show_canvas(self, paper, cols, width=None, height=None, margins=None):
        self.mode = 'map'
        self.map_paper = paper
        self.map_cols = max(MIN_COLS, min(MAX_COLS, int(cols)))
        self.map_width = width
        self.map_height = height
        self.map_margins = margins or {}
        w, h = map_canvas_size(self.map_paper, self.map_width, self.map_height)
        self.canvas_box.Size = Size(max(1, round(w * self.zoom)), max(1, round(h * self.zoom)))
        self.text_box.Visible = False
        self.canvas_scroll.Visible = True
        self.top_bar.Visible = True
        self._syncing = True
        self.cols_box.Text = str(self.map_cols)
        self.cols_track.Value = self.map_cols
        self._syncing = False
        if self._grid_path is not None:
            self._grid_path.Dispose()
            self._grid_path = None
        self.canvas_box.Invalidate()
        self.rebuild_hex_map()
        self.update_map_info()
        self.schedule_render()
        self.update_title()
    def update_map_info(self):
        if self.mode != 'map':
            return
        w, h = map_canvas_size(self.map_paper, self.map_width, self.map_height)
        layout = hex_layout(self.map_cols, w, h, self.map_margins)
        name = self.map_paper
        if name == 'CUSTOM':
            name = '自定义'
        margins_text = ''
        if self.map_margins:
            margins_text = (
                f' · 边距 L{self.map_margins.get("l", 0)} '
                f'T{self.map_margins.get("t", 0)} R{self.map_margins.get("r", 0)} '
                f'B{self.map_margins.get("b", 0)}'
            )
        cells_text = ''
        if self.hex_map is not None:
            cells_text = f' · 格子 {len(self.hex_map)} 个'
        self.map_info_label.Text = (
            f'{name} · {w}×{h} px · 格大小 {layout["cell_size"]:.1f} px · 纵向 {layout["rows"]} 行'
            f'{margins_text}{cells_text}'
        )
    def current_payload_and_type(self):
        if self.mode == 'map':
            return make_hex_map_payload(
                self.map_paper, self.map_cols, self.map_width, self.map_height, self.map_margins
            ), MAP_TYPE
        return self.file_bytes, self.original_type
    # ---------- 六角格画布事件 ----------
    def on_cols_text_changed(self, sender, e):
        if self._syncing or self.mode != 'map':
            return
        text = self.cols_box.Text.strip()
        try:
            val = int(text)
        except ValueError:
            return
        if val < MIN_COLS or val > MAX_COLS:
            return
        self.apply_cols(val)
    def on_cols_track_changed(self, sender, e):
        if self._syncing or self.mode != 'map':
            return
        self.apply_cols(self.cols_track.Value)
    def apply_cols(self, val):
        self.map_cols = val
        self._syncing = True
        self.cols_box.Text = str(val)
        self.cols_track.Value = val
        self._syncing = False
        self.update_map_info()
        self.schedule_render()
    def schedule_render(self):
        if self.mode != 'map':
            return
        if self._render_timer.Enabled:
            self._render_timer.Stop()
        self._render_timer.Start()

    def rebuild_hex_map(self):
        """按当前画布参数重建格子集合与相邻关系；参数未变时直接复用。

        返回 True 表示本次真的重建了。
        """
        if self.mode != 'map':
            return False
        w, h = map_canvas_size(self.map_paper, self.map_width, self.map_height)
        margins = normalize_margins(self.map_margins)
        current = self.hex_map
        if (current is not None and current.cols == self.map_cols and current.width == w
                and current.height == h and current.margins == margins):
            return False
        previous = current
        if current is not None and (current.width != w or current.height != h or current.margins != margins):
            previous = None
        self.hex_map = HexMap(self.map_cols, w, h, margins, previous=previous)
        return True

    def on_render_timer_tick(self, sender, e):
        self._render_timer.Stop()
        if self.mode != 'map':
            return
        if self.rebuild_hex_map() and self.hex_map is not None:
            stats = self.hex_map.summary()
            self.set_status(
                '画布就绪：%d 个格子，%d 条相邻边（连通：%s）'
                % (stats['cells'], stats['edges'], '是' if stats['connected'] else '否')
            )
        self.render_grid_path()
        self.canvas_box.Invalidate()
        self.update_map_info()

    def render_grid_path(self):
        if self.mode != 'map':
            return
        self.form.UseWaitCursor = True
        try:
            w, h = map_canvas_size(self.map_paper, self.map_width, self.map_height)
            dw = max(1, round(w * self.zoom))
            dh = max(1, round(h * self.zoom))
            scale_margins = {}
            for key in ('l', 't', 'r', 'b'):
                scale_margins[key] = max(0, int(round(self.map_margins.get(key, 0) * self.zoom)))
            layout = hex_layout(self.map_cols, dw, dh, scale_margins)
            size = layout['cell_size']
            path = GraphicsPath()
            for _q, _r, cx, cy in layout['centers']:
                pts = [PointF(p[0], p[1]) for p in hex_corners(cx, cy, size)]
                path.AddPolygon(pts)
            if self._grid_path is not None:
                self._grid_path.Dispose()
            self._grid_path = path
        finally:
            self.form.UseWaitCursor = False

    def on_canvas_paint(self, sender, e):
        g = e.Graphics
        g.Clear(Color.White)
        if self.mode != 'map' or self._grid_path is None:
            return
        ml = max(0, int(round(self.map_margins.get('l', 0) * self.zoom)))
        mr = max(0, int(round(self.map_margins.get('r', 0) * self.zoom)))
        mt = max(0, int(round(self.map_margins.get('t', 0) * self.zoom)))
        mb = max(0, int(round(self.map_margins.get('b', 0) * self.zoom)))
        if ml or mr or mt or mb:
            g.SetClip(Rectangle(ml, mt, max(1, self.canvas_box.Width - ml - mr), max(1, self.canvas_box.Height - mt - mb)))
        pen = Pen(Color.FromArgb(170, 90, 90, 90), GRID_PEN_WIDTH)
        g.DrawPath(pen, self._grid_path)
        pen.Dispose()
    def set_zoom(self, zoom):
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, float(zoom)))
        if abs(zoom - self.zoom) < 0.001:
            return
        self.zoom = zoom
        if self.mode == 'map':
            w, h = map_canvas_size(self.map_paper, self.map_width, self.map_height)
            self.canvas_box.Size = Size(max(1, round(w * self.zoom)), max(1, round(h * self.zoom)))
            self.canvas_box.Invalidate()
            self.schedule_render()
        self.zoom_label.Text = f'{int(round(self.zoom * 100))}%'

    def on_zoom_in(self, sender=None, e=None):
        self.set_zoom(self.zoom * ZOOM_STEP)

    def on_zoom_out(self, sender=None, e=None):
        self.set_zoom(self.zoom / ZOOM_STEP)

    def on_zoom_reset(self, sender=None, e=None):
        self.set_zoom(1.0)

    def on_canvas_mouse_wheel(self, sender, e):
        if (Control.ModifierKeys & Keys.Control) != 0:
            if e.Delta > 0:
                self.on_zoom_in()
            else:
                self.on_zoom_out()
            e.Handled = True

    # ---------- 菜单事件 ----------
    def close_app(self, sender=None, e=None):
        self.form.Close()
    def show_about(self, sender=None, e=None):
        MessageBox.Show(
            self.form,
            'Hex Editor\n版本 1.0（Python）\n'
            '创建/保存 .hex 文件；六角格画布支持 A1-A4 纸张与正六边形平铺',
            '关于',
        )
    # ---------- 文件操作 ----------
    def _choose_paper_size(self):
        dlg = Form()
        dlg.Text = '新建六角格画布 - 选择纸张尺寸'
        dlg.FormBorderStyle = FormBorderStyle.FixedDialog
        dlg.MaximizeBox = False
        dlg.MinimizeBox = False
        dlg.StartPosition = FormStartPosition.CenterParent
        dlg.ClientSize = Size(360, 150)
        dlg.Font = self.form.Font
        prompt = Label()
        prompt.Text = '请选择纸张尺寸（纵向）：'
        prompt.Location = Point(16, 16)
        prompt.AutoSize = True
        dlg.Controls.Add(prompt)
        combo = ComboBox()
        combo.Location = Point(16, 44)
        combo.Size = Size(220, 26)
        combo.DropDownStyle = ComboBoxStyle.DropDownList
        for label in PAPER_LABELS:
            combo.Items.Add(label)
        combo.SelectedIndex = 3
        dlg.Controls.Add(combo)
        ok = Button()
        ok.Text = '创建'
        ok.Location = Point(170, 100)
        ok.Size = Size(80, 30)
        ok.DialogResult = DialogResult.OK
        dlg.Controls.Add(ok)
        cancel = Button()
        cancel.Text = '取消'
        cancel.Location = Point(260, 100)
        cancel.Size = Size(80, 30)
        cancel.DialogResult = DialogResult.Cancel
        dlg.Controls.Add(cancel)
        dlg.AcceptButton = ok
        dlg.CancelButton = cancel
        if dlg.ShowDialog(self.form) == DialogResult.OK:
            return PAPER_ORDER[combo.SelectedIndex]
        return None
    def new_hex_map(self, sender=None, e=None):
        paper = self._choose_paper_size()
        if paper is None:
            return
        self.file_path = None
        self.file_bytes = b''
        self.original_type = MAP_TYPE
        self.is_hex_file = False
        self.show_canvas(paper, DEFAULT_COLS)
        self.set_status('已创建空白画布（未保存）：调整格子数后点击“确认格子并保存”')

    def on_detect_image(self, sender=None, e=None):
        if detect_hex_grid is None:
            MessageBox.Show(
                self.form,
                '缺少 numpy / Pillow 依赖，无法识别图片。\n请执行：python -m pip install numpy pillow',
                'Hex Editor - 缺少依赖',
            )
            return
        dlg = OpenFileDialog()
        dlg.Title = '选择包含六角格网格的图片'
        dlg.Filter = IMAGE_FILTER
        dlg.InitialDirectory = PICTURES_DIR
        if dlg.ShowDialog(self.form) != DialogResult.OK:
            return
        self.form.UseWaitCursor = True
        try:
            result = detect_hex_grid(dlg.FileName)
        except Exception as ex:
            MessageBox.Show(self.form, f'识别失败：{ex}', 'Hex Editor - 错误')
            return
        finally:
            self.form.UseWaitCursor = False
        if result is None:
            MessageBox.Show(
                self.form,
                '未能在图片中识别出六角格网格。\n'
                '请使用线条清晰的六角格图片（如本软件生成的画布截图）。',
                'Hex Editor - 识别',
            )
            return
        self.show_canvas('CUSTOM', result['cols'], result['width'], result['height'], result['margins'])
        m = result['margins']
        self.set_status(
            f'已从图片识别：{result["cols"]} 列，边距 左{m["l"]} 上{m["t"]} 右{m["r"]} 下{m["b"]} px（未保存）'
        )

    def confirm_and_save(self, sender=None, e=None):
        if self.mode != 'map':
            return
        if self.file_path and self.is_hex_file:
            self.save_file()
        else:
            self.save_as()
    def open_file(self, sender=None, e=None):
        dlg = OpenFileDialog()
        dlg.Title = '打开文件'
        dlg.Filter = 'Hex 文件 (*.hex)|*.hex|' + IMAGE_FILTER
        dlg.InitialDirectory = DOCUMENTS_DIR
        if dlg.ShowDialog(self.form) != DialogResult.OK:
            return
        try:
            with open(dlg.FileName, 'rb') as f:
                raw = f.read()
            info = read_hex_container(raw)
            if info['is_hex']:
                map_doc = parse_hex_map_payload(info['payload'])
                if map_doc is not None:
                    self.file_bytes = info['payload']
                    self.original_type = info['original_type']
                    self.is_hex_file = True
                    self.file_path = dlg.FileName
                    self.update_title()
                    self.show_canvas(
                        map_doc['paper'], map_doc['cols'], map_doc['width'], map_doc['height'], map_doc['margins']
                    )
                    w, h = map_canvas_size(map_doc['paper'], map_doc['width'], map_doc['height'])
                    self.set_status(
                        f'已打开六角格画布：{map_doc["paper"]}，{map_doc["cols"]} 列（{w}×{h} px）'
                    )
                    return
                self.file_bytes = info['payload']
                self.original_type = info['original_type']
                self.is_hex_file = True
            else:
                self.file_bytes = raw
                ext = os.path.splitext(dlg.FileName)[1].lstrip('.').upper()
                self.original_type = ext or 'BIN'
                self.is_hex_file = False
            self.file_path = dlg.FileName
            self.update_title()
            self.show_hex_view()
            size_text = f'{len(self.file_bytes):,} 字节'
            if self.is_hex_file:
                self.set_status(f'已打开 .hex 文件（内含类型：{self.original_type}，{size_text}）')
            else:
                self.set_status(f'已打开 {dlg.FileName}（{size_text}，非 .hex 原始文件）')
        except Exception as ex:
            MessageBox.Show(self.form, f'打开失败：{ex}', 'Hex Editor - 错误')
    def save_as(self, sender=None, e=None):
        payload, otype = self.current_payload_and_type()
        dlg = SaveFileDialog()
        dlg.Title = '另存为 .hex 文件'
        dlg.Filter = 'Hex 文件 (*.hex)|*.hex|所有文件 (*.*)|*.*'
        dlg.DefaultExt = 'hex'
        dlg.AddExtension = True
        if self.file_path:
            base = os.path.splitext(os.path.basename(self.file_path))[0]
            dlg.FileName = base + '.hex'
            dlg.InitialDirectory = SAVES_DIR
        else:
            if self.mode == 'map':
                if self.map_paper == 'CUSTOM':
                    dlg.FileName = f'画布-{self.map_cols}列.hex'
                else:
                    dlg.FileName = f'{self.map_paper}-{self.map_cols}列.hex'
            else:
                dlg.FileName = '未命名.hex'
            dlg.InitialDirectory = SAVES_DIR
        if dlg.ShowDialog(self.form) != DialogResult.OK:
            return False
        try:
            data = make_hex_container(payload, otype)
            with open(dlg.FileName, 'wb') as f:
                f.write(data)
            self.file_path = dlg.FileName
            self.file_bytes = payload
            self.original_type = otype
            self.is_hex_file = True
            self.update_title()
            self.set_status(f'已保存 .hex 文件 {dlg.FileName}（内含类型：{otype}）')
            return True
        except Exception as ex:
            MessageBox.Show(self.form, f'保存失败：{ex}', 'Hex Editor - 错误')
            return False
    def save_file(self, sender=None, e=None):
        if not self.file_path or not self.is_hex_file:
            self.save_as()
            return
        try:
            payload, otype = self.current_payload_and_type()
            data = make_hex_container(payload, otype)
            with open(self.file_path, 'wb') as f:
                f.write(data)
            self.file_bytes = payload
            self.original_type = otype
            self.set_status(f'已保存 {self.file_path}（内含类型：{otype}）')
        except Exception as ex:
            MessageBox.Show(self.form, f'保存失败：{ex}', 'Hex Editor - 错误')
    def export_original(self, sender=None, e=None):
        if self.mode == 'map':
            payload, _ = self.current_payload_and_type()
            dlg = SaveFileDialog()
            dlg.Title = '导出画布数据'
            dlg.Filter = 'JSON 文件 (*.json)|*.json|所有文件 (*.*)|*.*'
            dlg.DefaultExt = 'json'
            dlg.AddExtension = True
            dlg.InitialDirectory = SAVES_DIR
            base = '未命名'
            if self.file_path:
                base = os.path.splitext(os.path.basename(self.file_path))[0]
            dlg.FileName = f'{base}.json'
            if dlg.ShowDialog(self.form) != DialogResult.OK:
                return
            try:
                with open(dlg.FileName, 'wb') as f:
                    f.write(payload)
                self.set_status(f'已导出画布数据 {dlg.FileName}')
            except Exception as ex:
                MessageBox.Show(self.form, f'导出失败：{ex}', 'Hex Editor - 错误')
            return
        ext = self.original_type.lower() or 'bin'
        dlg = SaveFileDialog()
        dlg.Title = '导出原始文件'
        dlg.Filter = f'{self.original_type} 文件 (*.{ext})|*.{ext}|所有文件 (*.*)|*.*'
        dlg.DefaultExt = ext
        dlg.AddExtension = True
        dlg.InitialDirectory = SAVES_DIR
        base = '未命名'
        if self.file_path:
            base = os.path.splitext(os.path.basename(self.file_path))[0]
        dlg.FileName = f'{base}.{ext}'
        if dlg.ShowDialog(self.form) != DialogResult.OK:
            return
        try:
            with open(dlg.FileName, 'wb') as f:
                f.write(self.file_bytes)
            self.set_status(f'已导出原始文件 {dlg.FileName}（{len(self.file_bytes)} 字节）')
        except Exception as ex:
            MessageBox.Show(self.form, f'导出失败：{ex}', 'Hex Editor - 错误')
def main():
    def run():
        app = HexEditorApp()
        Application.Run(app.form)

    thread = Thread(ThreadStart(run))
    thread.SetApartmentState(ApartmentState.STA)
    thread.Start()
    thread.Join()
if __name__ == '__main__':
    main()