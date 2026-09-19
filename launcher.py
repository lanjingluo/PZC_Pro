"""游戏启动器 - 窗口应用（Python + WinForms）

运行方式：双击 游戏启动器.exe（或 run_launcher.bat），也可命令行运行 python launcher.py
主区域按钮：新建游戏 / 载入存档 / 退出
左侧栏：两个工具入口——六角格编辑器（Hex_Editor/main.py）、初设（setup/setup.py）
背景图：basic_picture_resources/background.png（每次启动从磁盘读取，换图不用重新打包）

“新建游戏”会从磁盘加载同目录下的 new_game.py 并打开新游戏窗口，背景工具在 ui_background.py：
这些文件都不打进 exe，所以改游戏代码后不用重新打包，只有改本文件（启动器自己的窗口、
按钮）才需要重新打包。

左侧栏的两个入口用独立的 pythonw 进程打开对应的 .py（和 run_*.bat 一样）：
Hex_Editor / setup 都需要自己的 STA 线程和消息循环，塞进启动器进程里会互相阻塞。
"""
import importlib.util
import os
import shutil
import subprocess
import sys

try:
    import clr
except ImportError:
    import ctypes

    ctypes.windll.user32.MessageBoxW(
        0,
        '缺少依赖 pythonnet，程序无法启动。\n\n请在命令行执行：\n    python -m pip install pythonnet',
        '游戏启动器 - 缺少依赖',
        0x10,
    )
    raise SystemExit(1)

clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from System.Drawing import Color, Font, FontStyle, Point, Size
from System.Windows.Forms import (
    Application,
    Button,
    DockStyle,
    FlatStyle,
    Form,
    FormStartPosition,
    Label,
    MessageBox,
    MessageBoxButtons,
    MessageBoxIcon,
    Panel,
)

WINDOW_TITLE = '游戏启动器'
WINDOW_SIZE = Size(1024, 640)
MINIMUM_SIZE = Size(640, 400)

BUTTON_SIZE = Size(240, 48)
BUTTON_GAP = 16

# 左侧栏
SIDEBAR_WIDTH = 200
SIDEBAR_PADDING = 12
SIDEBAR_BUTTON_SIZE = Size(SIDEBAR_WIDTH - SIDEBAR_PADDING * 2, 44)
SIDEBAR_BACK_COLOR = Color.FromArgb(28, 30, 34)
SIDEBAR_TITLE_COLOR = Color.FromArgb(220, 220, 220)
# 工具入口：(按钮文字, 子目录, 入口脚本)
TOOL_ENTRIES = (
    ('六角格编辑器', 'Hex_Editor', 'main.py'),
    ('初设', 'setup', 'setup.py'),
)

NEW_GAME_MODULE = 'new_game'
NEW_GAME_FUNCTION = 'open_new_game_window'

# 背景图的读取、缩放、防抖都在 ui_background.py 里（new_game.py 也用它）
BACKGROUND_MODULE = 'ui_background'
BACKGROUND_RELATIVE_PATH = os.path.join('basic_picture_resources', 'background.png')
FALLBACK_BACK_COLOR = Color.FromArgb(32, 34, 38)

# 打包成 exe 后 sys.executable 是 exe 自己，不能再拿来跑 .py，所以留一个自带运行时的路径
# （和 run_launcher.bat / Hex_Editor/run.bat / setup/run_setup.bat 里写的一致）
BUNDLED_PYTHONW = os.path.join(
    r'C:\Users\36349\.cache\codex-runtimes\codex-primary-runtime\dependencies\python',
    'pythonw.exe',
)


def project_dir():
    """游戏文件所在目录：打包成 exe 后是 exe 所在目录，开发时是本文件所在目录。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def background_path():
    """启动器背景图完整路径。"""
    return os.path.join(project_dir(), BACKGROUND_RELATIVE_PATH)


def load_local_module(name):
    """从磁盘读取并执行同目录下的 <name>.py，返回模块对象。

    每次调用都重新读文件，所以改完 new_game.py / ui_background.py 立刻生效，exe 不用重新打包。
    """
    directory = project_dir()
    path = os.path.join(directory, name + '.py')
    if not os.path.isfile(path):
        raise FileNotFoundError('找不到 %s.py：%s' % (name, path))

    # 让被加载的模块里 import 同目录的其它模块（如 Hex_Editor 里的文件）也能成功
    if directory not in sys.path:
        sys.path.insert(0, directory)

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def setup_background(control, image_path):
    """给窗口/面板铺背景图；出错只提示，不让启动器挂掉。"""
    try:
        module = load_local_module(BACKGROUND_MODULE)
    except Exception as exc:
        control.BackColor = FALLBACK_BACK_COLOR
        show_error('加载 %s.py 失败：\n\n%s: %s' % (BACKGROUND_MODULE, type(exc).__name__, exc))
        return

    reason = module.apply(control, image_path)
    if reason is not None:
        show_error(
            '背景图加载失败：\n\n%s\n（%s）\n\n'
            'GDI+ 只支持 PNG / JPG / BMP / GIF；如果文件其实是 WebP，请先转换格式。\n'
            '窗口会先用纯色背景继续运行。' % (image_path, reason)
        )


def show_error(message, title='游戏启动器 - 出错'):
    MessageBox.Show(message, title, MessageBoxButtons.OK, MessageBoxIcon.Error)


def pythonw_path():
    """找一个能跑 .py 的解释器，优先不弹黑框的 pythonw。

    开发时直接用当前解释器（它本来就是 pythonw / python）；打包成 exe 后
    sys.executable 是 exe 自己，所以要另找自带运行时或系统 PATH 里的 pythonw。
    """
    if not getattr(sys, 'frozen', False) and sys.executable:
        exe = sys.executable
        if not os.path.basename(exe).lower().startswith('pythonw'):
            sibling = os.path.join(os.path.dirname(exe), 'pythonw.exe')
            if os.path.isfile(sibling):
                return sibling
        return exe

    if os.path.isfile(BUNDLED_PYTHONW):
        return BUNDLED_PYTHONW
    for name in ('pythonw.exe', 'pythonw', 'python.exe', 'python'):
        found = shutil.which(name)
        if found:
            return found
    return None


def launch_tool(text, folder, script):
    """用独立进程打开子目录里的 .py（Hex_Editor/main.py、setup/setup.py）。"""
    directory = os.path.join(project_dir(), folder)
    path = os.path.join(directory, script)
    if not os.path.isfile(path):
        show_error('找不到 %s 的入口文件：\n\n%s' % (text, path))
        return

    exe = pythonw_path()
    if not exe:
        show_error(
            '找不到可用的 Python 解释器，无法打开 %s。\n\n'
            '请确认已安装 Python（或 %s 存在）。' % (text, BUNDLED_PYTHONW)
        )
        return

    try:
        # cwd 设成工具自己的目录，和 run_*.bat 里 cd /d "%~dp0" 一样
        subprocess.Popen([exe, path], cwd=directory)
    except OSError as exc:
        show_error('打开 %s 失败：\n\n%s: %s' % (text, type(exc).__name__, exc))


def build_sidebar():
    """左侧栏：竖排的工具入口按钮。"""
    sidebar = Panel()
    sidebar.Dock = DockStyle.Left
    sidebar.Width = SIDEBAR_WIDTH
    sidebar.BackColor = SIDEBAR_BACK_COLOR

    title = Label()
    title.Text = '工具'
    title.ForeColor = SIDEBAR_TITLE_COLOR
    title.Font = Font('Microsoft YaHei UI', 10, FontStyle.Bold)
    title.Location = Point(SIDEBAR_PADDING, 14)
    title.AutoSize = True
    sidebar.Controls.Add(title)

    y = 46
    for text, folder, script in TOOL_ENTRIES:
        button = make_button(
            text,
            lambda sender, event, text=text, folder=folder, script=script: launch_tool(text, folder, script),
            SIDEBAR_BUTTON_SIZE,
        )
        button.Location = Point(SIDEBAR_PADDING, y)
        sidebar.Controls.Add(button)
        y += SIDEBAR_BUTTON_SIZE.Height + 10
    return sidebar


def on_new_game(owner):
    """“新建游戏”：调用 new_game.py 打开新游戏窗口。"""
    try:
        module = load_local_module(NEW_GAME_MODULE)
    except Exception as exc:
        show_error('打开 %s.py 失败：\n\n%s: %s' % (NEW_GAME_MODULE, type(exc).__name__, exc))
        return

    opener = getattr(module, NEW_GAME_FUNCTION, None)
    if opener is None:
        show_error('%s.py 里没有找到 %s() 函数。' % (NEW_GAME_MODULE, NEW_GAME_FUNCTION))
        return

    try:
        opener(owner)
    except Exception as exc:
        show_error('新建游戏窗口出错：\n\n%s: %s' % (type(exc).__name__, exc))


def on_load_save(owner):
    """“载入存档”：暂时是占位按钮。"""
    MessageBox.Show(
        owner,
        '载入存档还没有实现。\n\n下一步可以在这里放存档列表，读取 saves 目录里的 .hex 文件。',
        '载入存档',
        MessageBoxButtons.OK,
        MessageBoxIcon.Information,
    )


def make_button(text, handler, size=None):
    button = Button()
    button.Text = text
    button.Size = size or BUTTON_SIZE
    button.FlatStyle = FlatStyle.System
    button.Click += handler
    return button


def center_buttons(panel, buttons):
    """把按钮竖排居中显示，窗口缩放时重新计算。"""
    total = sum(b.Height for b in buttons) + BUTTON_GAP * (len(buttons) - 1)
    y = max(0, (panel.ClientSize.Height - total) // 2)
    for button in buttons:
        button.Location = Point(max(0, (panel.ClientSize.Width - button.Width) // 2), y)
        y += button.Height + BUTTON_GAP


def build_launcher():
    """创建启动器主窗口：左侧栏（工具入口）+ 背景图 + 竖排三个按钮（新建游戏 / 载入存档 / 退出）。"""
    form = Form()
    form.Text = WINDOW_TITLE
    form.ClientSize = WINDOW_SIZE
    form.MinimumSize = MINIMUM_SIZE
    form.StartPosition = FormStartPosition.CenterScreen

    panel = Panel()
    panel.Dock = DockStyle.Fill
    form.Controls.Add(panel)

    setup_background(panel, background_path())

    # 左侧栏要在 Fill 面板之后加，Dock 才会先给它让出位置
    form.Controls.Add(build_sidebar())

    buttons = [
        make_button('新建游戏', lambda sender, event: on_new_game(form)),
        make_button('载入存档', lambda sender, event: on_load_save(form)),
        make_button('退出', lambda sender, event: form.Close()),
    ]
    for button in buttons:
        panel.Controls.Add(button)

    panel.Resize += lambda sender, event: center_buttons(panel, buttons)
    center_buttons(panel, buttons)

    form.AcceptButton = buttons[0]   # 回车 = 新建游戏
    form.CancelButton = buttons[2]   # Esc = 退出
    return form


def main():
    Application.EnableVisualStyles()
    Application.SetCompatibleTextRenderingDefault(False)
    Application.Run(build_launcher())
    return 0


if __name__ == '__main__':
    sys.exit(main())
