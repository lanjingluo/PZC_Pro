"""hexformat.py - .hex 容器、六角格画布几何与画布文档（纯逻辑，不依赖界面）"""
import json
import math
import struct
MAGIC = b'HEX1'
MAX_DISPLAY_BYTES = 512 * 1024
MAP_TYPE = 'HEXMAP'
MAP_PAYLOAD_VERSION = 1
# A 系列纸张（毫米，宽×高，纵向）
PAPER_SIZES_MM = {
    'A1': (594, 841),
    'A2': (420, 594),
    'A3': (297, 420),
    'A4': (210, 297),
}
MM_PER_INCH = 25.4
def make_hex_container(payload: bytes, original_type: str) -> bytes:
    """把原始文件内容打包成 .hex 容器。
    结构：魔数 HEX1(4) + 原始类型(8) + 数据长度(8，小端) + 原始内容
    """
    type_bytes = original_type.upper().encode('ascii', errors='replace')[:8].ljust(8, b' ')
    return MAGIC + type_bytes + struct.pack('<q', len(payload)) + payload
def read_hex_container(data: bytes) -> dict:
    """解析 .hex 容器；不是有效容器时原样返回。"""
    if len(data) < 20 or data[:4] != MAGIC:
        return {'is_hex': False, 'original_type': '', 'payload': data}
    original_type = data[4:12].decode('ascii', errors='replace').strip()
    length = struct.unpack('<q', data[12:20])[0]
    if length < 0 or 20 + length > len(data):
        return {'is_hex': False, 'original_type': '', 'payload': data}
    return {'is_hex': True, 'original_type': original_type, 'payload': data[20:20 + length]}
def paper_size_pixels(paper: str, dpi: int = 96) -> tuple:
    """把 A 系列纸张尺寸（毫米）按 DPI 换算成像素（宽, 高）。"""
    w_mm, h_mm = PAPER_SIZES_MM[paper.upper()]
    scale = dpi / MM_PER_INCH
    return (round(w_mm * scale), round(h_mm * scale))
def hex_layout(cols: int, width: int, height: int) -> dict:
    """计算能覆盖整张画布的平顶六角格布局。
    采用奇数列错位（odd-q）排布：
    - 横向每列间距 1.5 * cell_size
    - 纵向每行间距 sqrt(3) * cell_size，奇数列整体上移半行
    - cell_size = width / (1.5 * cols + 0.5)，恰好让第 1 列左侧与最后 1 列右侧贴住画布边缘
    - 行数自动取整，保证画布底边也被六角格覆盖
    返回 dict：cell_size（中心到顶点的像素）、rows（纵向行数）、
    centers（[(列 q, 行 r, 中心 x, 中心 y), ...]）。
    """
    cols = max(1, int(cols))
    width = max(1, int(width))
    height = max(1, int(height))
    cell_size = width / (1.5 * cols + 0.5)
    row_step = math.sqrt(3) * cell_size
    rows = int(math.ceil(height / row_step)) + 1
    centers = []
    half_h = math.sqrt(3) * cell_size * 0.5
    for r in range(rows):
        for q in range(cols):
            x = cell_size * (1.5 * q + 1.0)
            y = row_step * r + half_h
            if q % 2 == 1:
                y += half_h
            centers.append((q, r, x, y))
    return {'cell_size': cell_size, 'rows': rows, 'centers': centers}
def hex_corners(cx: float, cy: float, cell_size: float) -> list:
    """平顶正六边形 6 个顶点（逆时针），起点为右侧顶点。"""
    pts = []
    for i in range(6):
        ang = math.pi / 3.0 * i
        pts.append((cx + cell_size * math.cos(ang), cy + cell_size * math.sin(ang)))
    return pts
def format_hex_view(data: bytes, max_bytes: int = MAX_DISPLAY_BYTES) -> str:
    """把字节内容格式化成“偏移 + 十六进制 + ASCII”的多行文本。"""
    count = min(len(data), max_bytes)
    lines = []
    for i in range(0, count, 16):
        chunk = data[i:i + 16]
        hex_part = ' '.join(f'{b:02X}' for b in chunk)
        ascii_part = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
        lines.append(f'{i:08X}  {hex_part:<48} {ascii_part}')
    return '\n'.join(lines)
def make_hex_map_payload(paper: str, cols: int) -> bytes:
    """把画布文档序列化成 .hex 负载（JSON，UTF-8）。"""
    doc = {'v': MAP_PAYLOAD_VERSION, 'paper': paper.upper(), 'cols': int(cols)}
    return json.dumps(doc, ensure_ascii=False).encode('utf-8')
def parse_hex_map_payload(payload: bytes):
    """解析画布文档负载；不是合法画布文档时返回 None。"""
    try:
        doc = json.loads(payload.decode('utf-8'))
        if doc.get('v') != MAP_PAYLOAD_VERSION:
            return None
        paper = str(doc.get('paper', '')).upper()
        cols = int(doc.get('cols', 0))
        if paper not in PAPER_SIZES_MM or cols < 1:
            return None
        return {'paper': paper, 'cols': cols}
    except Exception:
        return None