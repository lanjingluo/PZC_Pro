"""新建游戏窗口（Python + WinForms）。

由游戏启动器（launcher.py / 游戏启动器.exe）的“新建游戏”按钮加载调用，
也可以单独运行：python new_game.py

启动器是每次点击都从磁盘重新读取本文件的，所以改完这里直接生效，
不需要重新打包 exe；只有改 launcher.py（启动器自己的窗口、按钮）才需要重新打包。

界面背景图：basic_picture_resources/background2.jpg（每次打开窗口都从磁盘读，换图不用重新打包）
窗口中心是“选择剧本”选项：点开后列出 setup/setupsaves 里已有的 .scenario，
每张卡片都是这个剧本的图形化预览，点卡片就用初设编辑器打开它的图形化界面。
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
        '新建游戏 - 缺少依赖',
        0x10,
    )
    raise SystemExit(1)

clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from System.Drawing import Color, Font, Point, Size
from System.Windows.Forms import (
    Application,
    Button,
    FlatStyle,
    Form,
    FormStartPosition,
    Label,
    MessageBox,
    MessageBoxButtons,
    MessageBoxIcon,
)

WINDOW_TITLE = '新建游戏'
WINDOW_SIZE = Size(900, 600)
MINIMUM_SIZE = Size(600, 400)

# 界面背景图的读取、缩放、防抖都在 ui_background.py 里（启动器也用它）
BACKGROUND_MODULE = 'ui_background'
BACKGROUND_RELATIVE_PATH = os.path.join('basic_picture_resources', 'background2.jpg')
FALLBACK_BACK_COLOR = Color.FromArgb(32, 34, 38)

# 窗口中心的选项：点开列出已有剧本（列表与缩略图都在 scenario_list.py 里）
SCENARIO_MODULE = 'scenario_list'
OPTION_TEXT = '选择剧本'
OPTION_HINT = '读取 setup/setupsaves 里已有的 .scenario'
OPTION_BUTTON_SIZE = Size(260, 52)


def project_dir():
    """游戏文件所在目录：打包成 exe 后是 exe 所在目录，开发时是本文件所在目录。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def load_local_module(name):
    """从磁盘读取并执行同目录下的 <name>.py（原因见 ui_background.py 顶部说明）。"""
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


def show_error(message, title='新建游戏 - 出错'):
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

    reason = module.apply(form, path)
    if reason is not None:
        show_error(
            '界面背景图加载失败：\n\n%s\n（%s）\n\n'
            'GDI+ 只支持 PNG / JPG / BMP / GIF；如果文件其实是 WebP，请先转换格式。\n'
            '窗口会先用纯色背景继续运行。' % (path, reason)
        )


def build_new_game_window(owner=None):
    """创建“新建游戏”窗口：中心一个选项，点开后变成已有剧本的图形列表。"""
    form = Form()
    form.Text = WINDOW_TITLE
    form.ClientSize = WINDOW_SIZE
    form.MinimumSize = MINIMUM_SIZE
    if owner is not None:
        form.StartPosition = FormStartPosition.CenterParent
    else:
        form.StartPosition = FormStartPosition.CenterScreen
    apply_background(form)

    page = {'gallery': None}

    option = Button()
    option.Text = OPTION_TEXT
    option.Size = OPTION_BUTTON_SIZE
    option.FlatStyle = FlatStyle.System

    hint = Label()
    hint.Text = OPTION_HINT
    hint.AutoSize = True
    hint.Font = Font('Microsoft YaHei UI', 10)
    hint.ForeColor = Color.FromArgb(240, 240, 240)
    hint.BackColor = Color.Transparent

    form.Controls.Add(option)
    form.Controls.Add(hint)

    def center_options():
        """选项和提示文字成组居中；窗口缩放时跟着走。"""
        top = max(0, (form.ClientSize.Height - option.Height - 6 - hint.Height) // 2)
        option.Location = Point(max(0, (form.ClientSize.Width - option.Width) // 2), top)
        hint.Location = Point(max(0, (form.ClientSize.Width - hint.Width) // 2), top + option.Height + 6)

    def show_options():
        gallery = page['gallery']
        if gallery is not None:
            form.Controls.Remove(gallery)
            gallery.Dispose()
            page['gallery'] = None
        option.Visible = True
        hint.Visible = True
        center_options()
        option.Focus()

    def show_gallery():
        if page['gallery'] is not None:
            return
        try:
            module = load_local_module(SCENARIO_MODULE)
            gallery = module.build_gallery(form, on_back=show_options, on_open=open_scenario)
        except Exception as exc:
            show_error('打开剧本列表失败：\n\n%s: %s' % (type(exc).__name__, exc))
            return
        page['gallery'] = gallery
        option.Visible = False
        hint.Visible = False
        form.Controls.Add(gallery)
        gallery.BringToFront()

    def open_scenario(path):
        """选好剧本＝进入游戏：先把新建游戏窗口关掉，再打开游戏窗口，不叠着两个窗口。"""
        form.Hide()
        try:
            module = load_local_module(SCENARIO_MODULE)
            module.open_in_game(None, path)      # 前一个窗口已经关了，游戏窗口独立打开
        finally:
            form.Close()

    option.Click += lambda sender, event: show_gallery()
    form.Resize += lambda sender, event: center_options()
    form.AcceptButton = option          # 回车 = 选择剧本
    center_options()
    return form


def open_new_game_window(owner=None):
    """显示“新建游戏”窗口；由启动器传入 owner 时以模态方式打开。"""
    form = build_new_game_window(owner)
    try:
        if owner is not None:
            form.ShowDialog(owner)
        else:
            form.ShowDialog()
    finally:
        form.Dispose()


def main():
    Application.EnableVisualStyles()
    Application.SetCompatibleTextRenderingDefault(False)
    open_new_game_window()
    return 0


if __name__ == '__main__':
    sys.exit(main())
