"""imagedetect.py - 从图片中识别六角格网格（列数与边距，纯逻辑）"""
import numpy as np
from PIL import Image

def detect_hex_grid(image_path, dark_threshold=128, max_cols=200):
    """识别图片中的平顶六角格网格。

    返回 dict：cols（横向格子数）、margins（{l,t,r,b} 网格到图像边缘的像素距离）、
    width、height（原图像素尺寸）；识别失败返回 None。
    """
    try:
        img = Image.open(image_path).convert('L')
    except Exception:
        return None
    orig_w, orig_h = img.size
    gray = np.asarray(img, dtype=np.uint8)
    dark = gray < dark_threshold
    if not dark.any():
        return None
    x_proj = dark.sum(axis=0)
    y_proj = dark.sum(axis=1)
    xs = np.nonzero(x_proj > 0)[0]
    ys = np.nonzero(y_proj > 0)[0]
    if len(xs) < 2 or len(ys) < 2:
        return None
    x_min = int(xs[0])
    x_max = int(xs[-1])
    y_min = int(ys[0])
    y_max = int(ys[-1])
    span = x_max - x_min
    pitch = _find_pitch_fft(x_proj, x_min, x_max, span)
    if pitch is None:
        return None
    cols = int(round(span / float(pitch) - 1.0 / 3.0))
    cols = max(1, min(max_cols, cols))
    best_cols = cols
    best_err = abs(span - (pitch * cols + pitch / 3.0)) / pitch
    for delta in (-1, 1):
        cand = cols + delta
        if 1 <= cand <= max_cols:
            err = abs(span - (pitch * cand + pitch / 3.0)) / pitch
            if err < best_err:
                best_err = err
                best_cols = cand
    cols = best_cols
    if best_err > 0.8:
        return None
    margins = {
        'l': int(x_min),
        't': int(y_min),
        'r': int((orig_w - 1) - x_max),
        'b': int((orig_h - 1) - y_max),
    }
    return {'cols': cols, 'margins': margins, 'width': orig_w, 'height': orig_h}

def _find_pitch_fft(profile, x_min, x_max, span):
    """用 FFT 找网格横向重复周期（列间距）。"""
    seg = profile[x_min:x_max + 1].astype(float)
    n = len(seg)
    if n < 12:
        return None
    mean = float(seg.mean())
    window = np.hanning(n)
    spec = np.abs(np.fft.rfft((seg - mean) * window))
    freqs = np.fft.rfftfreq(n)
    best_period = None
    best_mag = -1.0
    for k in range(1, len(spec)):
        if spec[k] <= 0:
            continue
        period = n / float(k)
        if period < 4 or period > n / 1.5:
            continue
        if spec[k] > best_mag:
            best_mag = float(spec[k])
            best_period = period
    if best_period is None:
        return None
    return best_period
