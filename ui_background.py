"""窗口背景图公共工具（launcher.py 和 new_game.py 都用它）。

两个窗口都是“按文件路径加载”本模块，而不是普通 import：打包成 exe 后，
PyInstaller 会把静态 import 到的模块塞进 exe 里，磁盘上的改动就不生效了；
按路径读磁盘才能真正做到换背景图、改这里的代码都不用重新打包。
"""
import clr

clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from System.Drawing import Bitmap, Color, Graphics, Image, Rectangle
from System.Drawing.Drawing2D import InterpolationMode, PixelOffsetMode
from System.IO import MemoryStream
from System.Windows.Forms import ImageLayout, Timer

FALLBACK_BACK_COLOR = Color.FromArgb(32, 34, 38)
DEBOUNCE_MS = 120


def load_image(path):
    """用 GDI+ 读取图片，返回 (图片, 失败原因)；失败时图片为 None。"""
    try:
        with open(path, 'rb') as handle:
            data = handle.read()
    except OSError as exc:
        return None, '读取失败 %s: %s' % (type(exc).__name__, exc)
    try:
        # 走内存流读取，不锁住图片文件，方便随时替换背景图
        return Image.FromStream(MemoryStream(data)), None
    except Exception as exc:
        # GDI+ 只认 PNG / JPG / BMP / GIF 等；文件其实是 WebP 时会在这里报错
        return None, '%s: %s' % (type(exc).__name__, exc)


def scale_to(image, size):
    """按目标尺寸高质量缩放（GDI+ 默认拉伸比较糊，这里自己插值）。"""
    bitmap = Bitmap(size.Width, size.Height)
    graphics = Graphics.FromImage(bitmap)
    try:
        graphics.InterpolationMode = InterpolationMode.HighQualityBicubic
        graphics.PixelOffsetMode = PixelOffsetMode.HighQuality
        graphics.DrawImage(image, Rectangle(0, 0, size.Width, size.Height))
    finally:
        graphics.Dispose()
    return bitmap


def apply(control, image_path, fallback_color=None):
    """把图片拉伸铺满控件（窗口或面板）。

    返回 None 表示成功，否则返回失败原因。图片会被拉伸填满，比例和控件不一致时会变形；
    窗口缩放停下约 0.12 秒后，会按新尺寸重新做一次高质量缩放。
    """
    if fallback_color is None:
        control.BackColor = FALLBACK_BACK_COLOR
    else:
        control.BackColor = fallback_color

    image, reason = load_image(image_path)
    if image is None:
        return reason

    control.BackgroundImageLayout = ImageLayout.Stretch
    state = {'bitmap': None}

    def fit():
        if control.ClientSize.Width <= 0 or control.ClientSize.Height <= 0:
            return
        previous = state['bitmap']
        state['bitmap'] = scale_to(image, control.ClientSize)
        control.BackgroundImage = state['bitmap']
        if previous is not None:
            previous.Dispose()

    timer = Timer()
    timer.Interval = DEBOUNCE_MS
    timer.Tick += lambda sender, event: (timer.Stop(), fit())
    control.Resize += lambda sender, event: (timer.Stop(), timer.Start())
    fit()
    return None
