"""游戏启动器 - 窗口应用（Python + WinForms）

运行方式：双击 run_launcher.bat，或命令行运行 python launcher.py
当前版本只提供一个空白主窗口，作为后续功能的容器：
标题、尺寸、菜单、按钮、游戏列表等都可以在 build_launcher() 里继续添加。
"""
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

from System.Drawing import Size
from System.Windows.Forms import (
    Application,
    Form,
    FormStartPosition,
)

WINDOW_TITLE = '游戏启动器'
WINDOW_SIZE = Size(1024, 640)
MINIMUM_SIZE = Size(640, 400)


def build_launcher():
    """创建启动器主窗口；当前为空窗口，不放任何控件。"""
    form = Form()
    form.Text = WINDOW_TITLE
    form.ClientSize = WINDOW_SIZE
    form.MinimumSize = MINIMUM_SIZE
    form.StartPosition = FormStartPosition.CenterScreen
    return form


def main():
    Application.EnableVisualStyles()
    Application.SetCompatibleTextRenderingDefault(False)
    Application.Run(build_launcher())
    return 0


if __name__ == '__main__':
    sys.exit(main())
