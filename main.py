"""Hex Editor - 窗口应用（Python + WinForms）

运行方式：双击 run.bat，或命令行运行 python main.py

文件格式：本软件创建/保存的文件为自定义 .hex 容器格式，
用于存储特定类型的文件（如图片）。
结构：魔数 HEX1(4) + 原始类型(8) + 数据长度(8) + 原始内容
"""

import os

import clr

clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from System.Windows.Forms import (
    Application,
    DialogResult,
    DockStyle,
    Form,
    FormStartPosition,
    Keys,
    MenuStrip,
    MessageBox,
    OpenFileDialog,
    SaveFileDialog,
    ScrollBars,
    StatusStrip,
    TextBox,
    ToolStripMenuItem,
    ToolStripSeparator,
    ToolStripStatusLabel,
)
from System.Drawing import Font, Size
import System

from hexformat import format_hex_view, make_hex_container, read_hex_container

MAX_DISPLAY_BYTES = 512 * 1024
DOCUMENTS_DIR = System.Environment.GetFolderPath(System.Environment.SpecialFolder.MyDocuments)
PICTURES_DIR = System.Environment.GetFolderPath(System.Environment.SpecialFolder.MyPictures)

IMAGE_FILTER = (
    '图片文件 (*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.tif;*.tiff;*.webp;*.ico)'
    '|*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.tif;*.tiff;*.webp;*.ico'
    '|所有文件 (*.*)|*.*'
)


class HexEditorApp:
    """主窗口应用。"""

    def __init__(self):
        self.file_bytes = b''
        self.file_path = None
        self.original_type = 'BIN'
        self.is_hex_file = False

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

        new_item = ToolStripMenuItem('新建')
        new_item.ShortcutKeys = Keys.Control | Keys.N
        new_item.Click += self.new_file

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

        file_menu.DropDownItems.Add(new_item)
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
        self.text_box = TextBox()
        self.text_box.Multiline = True
        self.text_box.ReadOnly = True
        self.text_box.ScrollBars = ScrollBars.Both
        self.text_box.WordWrap = False
        self.text_box.Font = Font('Consolas', 11)
        self.text_box.Dock = DockStyle.Fill
        self.text_box.Text = '新建文件已就绪。\r\n保存时默认生成 .hex 文件，用于存储特定类型的文件。'
        self.form.Controls.Add(self.text_box)

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
        if len(self.file_bytes) == 0:
            self.text_box.Text = '（空文件）\r\n保存时默认生成 .hex 文件，用于存储特定类型的文件。'
        else:
            self.text_box.Text = format_hex_view(self.file_bytes, MAX_DISPLAY_BYTES)

    # ---------- 菜单事件 ----------
    def close_app(self, sender=None, e=None):
        self.form.Close()

    def show_about(self, sender=None, e=None):
        MessageBox.Show(
            self.form,
            'Hex Editor\n版本 0.4（Python）\n创建/保存 .hex 文件，用于存储特定类型的文件',
            '关于',
        )

    # ---------- 文件操作 ----------
    def new_file(self, sender=None, e=None):
        self.file_bytes = b''
        self.file_path = None
        self.original_type = 'BIN'
        self.is_hex_file = False
        self.update_title()
        self.text_box.Text = '新建文件已就绪。\r\n保存时默认生成 .hex 文件，用于存储特定类型的文件。'
        self.set_status('已新建文件（未保存，默认类型 BIN）')

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
            data = make_hex_container(self.file_bytes, self.original_type)
            with open(dlg.FileName, 'wb') as f:
                f.write(data)
            self.file_path = dlg.FileName
            self.is_hex_file = True
            self.update_title()
            self.set_status(f'已保存 .hex 文件 {dlg.FileName}（内含类型：{self.original_type}）')
            return True
        except Exception as ex:
            MessageBox.Show(self.form, f'保存失败：{ex}', 'Hex Editor - 错误')
            return False

    def save_file(self, sender=None, e=None):
        if not self.file_path or not self.is_hex_file:
            self.save_as()
            return
        try:
            data = make_hex_container(self.file_bytes, self.original_type)
            with open(self.file_path, 'wb') as f:
                f.write(data)
            self.set_status(f'已保存 {self.file_path}（内含类型：{self.original_type}）')
        except Exception as ex:
            MessageBox.Show(self.form, f'保存失败：{ex}', 'Hex Editor - 错误')

    def export_original(self, sender=None, e=None):
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
