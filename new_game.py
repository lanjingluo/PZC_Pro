"""新建游戏窗口（Python + WinForms）。

由游戏启动器（launcher.py / 游戏启动器.exe）的“新建游戏”按钮加载调用，
也可以单独运行：python new_game.py

启动器是每次点击都从磁盘重新读取本文件的，所以改完这里直接生效，
不需要重新打包 exe；只有改 launcher.py（启动器自己的窗口、按钮）才需要重新打包。

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
        '新建游戏 - 缺少依赖',
        0x10,
    )
    raise SystemExit(1)

clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from System.Drawing import Color, Size
from System.Windows.Forms import (
    Application,
    Form,
    FormStartPosition,
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
    """创建“新建游戏”窗口；目前是空窗口，后续的新游戏界面加在这里。"""
    form = Form()
    form.Text = WINDOW_TITLE
    form.ClientSize = WINDOW_SIZE
    form.MinimumSize = MINIMUM_SIZE
    if owner is not None:
        form.StartPosition = FormStartPosition.CenterParent
    else:
        form.StartPosition = FormStartPosition.CenterScreen
    apply_background(form)
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
