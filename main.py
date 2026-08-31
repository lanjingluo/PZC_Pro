"""Hex Editor - 窗口应用（Python + WinForms）
运行方式：双击 run.bat，或命令行运行 python main.py
文件格式：本软件创建/保存的文件为自定义 .hex 容器格式，
用于存储特定类型的文件。
结构：魔数 HEX1(4) + 原始类型(8) + 数据长度(8) + 原始内容
六角格画布：新建空白画布时选择 A1-A4 纸张，整张画布被平顶正六边形覆盖；
通过顶部输入框或滑块调整横向格子数，格子大小随纸张尺寸与格子数自动计算。
"""
import os
import clr
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
import System.Windows.Forms
import System.Drawing
from System.Windows.Forms import (
    Application,
    Button,
    ComboBox,
    ComboBoxStyle,
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
    TrackBar,
)
from System.Drawing import Bitmap, Color, Font, Graphics, Pen, Point, PointF, Size
from System.Drawing.Drawing2D import GraphicsPath
import System
from hexformat import (
    MAP_TYPE,
    format_hex_view,
    hex_corners,
    hex_layout,
    make_hex_container,
    make_hex_map_payload,
    paper_size_pixels,
    parse_hex_map_payload,
    read_hex_container,
)
MAX_DISPLAY_BYTES = 512 * 1024
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
        self._syncing = False
        self._grid_bitmap = None
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
        help_menu = ToolStripMenuItem('帮助')
        about_item = ToolStripMenuItem('关于')
        about_item.Click += self.show_about
        help_menu.DropDownItems.Add(about_item)
        menubar.Items.Add(file_menu)
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
        self.top_bar.Height = 76
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
        self.cols_track.Location = Point(108, 34)
        self.cols_track.Size = Size(360, 40)
        self.cols_track.Minimum = MIN_COLS
        self.cols_track.Maximum = MAX_COLS
        self.cols_track.Value = DEFAULT_COLS
        self.cols_track.SmallChange = 1
        self.cols_track.LargeChange = 5
        self.cols_track.TickFrequency = 5
        self.cols_track.ValueChanged += self.on_cols_track_changed
        self.top_bar.Controls.Add(self.cols_track)
        self.map_info_label = Label()
        self.map_info_label.AutoSize = True
        self.map_info_label.Location = Point(484, 44)
        self.top_bar.Controls.Add(self.map_info_label)
        # 六角格画布（可滚动）
        self.canvas_scroll = Panel()
        self.canvas_scroll.Dock = DockStyle.Fill
        self.canvas_scroll.AutoScroll = True
        self.canvas_box = PictureBox()
        self.canvas_box.SizeMode = PictureBoxSizeMode.Normal
        self.canvas_box.BackColor = Color.White
        self.canvas_box.Paint += self.on_canvas_paint
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
    def show_canvas(self, paper, cols):
        self.mode = 'map'
        self.map_paper = paper
        self.map_cols = max(MIN_COLS, min(MAX_COLS, int(cols)))
        w, h = paper_size_pixels(self.map_paper)
        self.canvas_box.Size = Size(w, h)
        self.text_box.Visible = False
        self.canvas_scroll.Visible = True
        self.top_bar.Visible = True
        self._syncing = True
        self.cols_box.Text = str(self.map_cols)
        self.cols_track.Value = self.map_cols
        self._syncing = False
        self.render_grid_bitmap()
        self.canvas_box.Invalidate()
        self.update_map_info()
        self.update_title()
    def update_map_info(self):
        if self.mode != 'map':
            return
        w, h = paper_size_pixels(self.map_paper)
        layout = hex_layout(self.map_cols, w, h)
        self.map_info_label.Text = (
            f'{self.map_paper} · {w}×{h} px · 格大小 {layout["cell_size"]:.1f} px · 纵向 {layout["rows"]} 行'
        )
    def current_payload_and_type(self):
        if self.mode == 'map':
            return make_hex_map_payload(self.map_paper, self.map_cols), MAP_TYPE
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
        self.render_grid_bitmap()
        self.canvas_box.Invalidate()
        self.update_map_info()
    def render_grid_bitmap(self):
        if self.mode != 'map':
            return
        self.form.UseWaitCursor = True
        try:
            w, h = paper_size_pixels(self.map_paper)
            bmp = Bitmap(w, h)
            g = Graphics.FromImage(bmp)
            try:
                g.Clear(Color.White)
                layout = hex_layout(self.map_cols, w, h)
                size = layout['cell_size']
                path = GraphicsPath()
                for _q, _r, cx, cy in layout['centers']:
                    pts = [PointF(p[0], p[1]) for p in hex_corners(cx, cy, size)]
                    path.AddPolygon(pts)
                pen = Pen(Color.FromArgb(170, 90, 90, 90), 1.0)
                g.DrawPath(pen, path)
                pen.Dispose()
                path.Dispose()
            finally:
                g.Dispose()
            if self._grid_bitmap is not None:
                self._grid_bitmap.Dispose()
            self._grid_bitmap = bmp
        finally:
            self.form.UseWaitCursor = False

    def on_canvas_paint(self, sender, e):
        g = e.Graphics
        g.Clear(Color.White)
        if self.mode != 'map' or self._grid_bitmap is None:
            return
        g.DrawImageUnscaled(self._grid_bitmap, 0, 0)
    # ---------- 菜单事件 ----------
    def close_app(self, sender=None, e=None):
        self.form.Close()
    def show_about(self, sender=None, e=None):
        MessageBox.Show(
            self.form,
            'Hex Editor\n版本 0.6（Python）\n'
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
        cols = DEFAULT_COLS
        dlg = SaveFileDialog()
        dlg.Title = '保存空白六角格画布'
        dlg.Filter = 'Hex 文件 (*.hex)|*.hex|所有文件 (*.*)|*.*'
        dlg.DefaultExt = 'hex'
        dlg.AddExtension = True
        dlg.FileName = f'{paper}-空白.hex'
        dlg.InitialDirectory = DOCUMENTS_DIR
        if dlg.ShowDialog(self.form) != DialogResult.OK:
            return
        try:
            payload = make_hex_map_payload(paper, cols)
            data = make_hex_container(payload, MAP_TYPE)
            with open(dlg.FileName, 'wb') as f:
                f.write(data)
            self.file_path = dlg.FileName
            self.file_bytes = payload
            self.original_type = MAP_TYPE
            self.is_hex_file = True
            self.show_canvas(paper, cols)
            self.set_status(f'已创建空白画布：{paper}，{cols} 列（保存于 {dlg.FileName}）')
        except Exception as ex:
            MessageBox.Show(self.form, f'创建失败：{ex}', 'Hex Editor - 错误')
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
                    self.show_canvas(map_doc['paper'], map_doc['cols'])
                    w, h = paper_size_pixels(map_doc['paper'])
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
            dlg.InitialDirectory = os.path.dirname(self.file_path)
        else:
            dlg.FileName = '未命名.hex'
            dlg.InitialDirectory = DOCUMENTS_DIR
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
            payload = make_hex_map_payload(self.map_paper, self.map_cols)
            dlg = SaveFileDialog()
            dlg.Title = '导出画布数据'
            dlg.Filter = 'JSON 文件 (*.json)|*.json|所有文件 (*.*)|*.*'
            dlg.DefaultExt = 'json'
            dlg.AddExtension = True
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
    app = HexEditorApp()
    Application.Run(app.form)
if __name__ == '__main__':
    main()