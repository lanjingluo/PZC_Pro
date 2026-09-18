"""hexformat.py - .hex 容器、六角格画布几何与画布文档（纯逻辑，不依赖界面）"""
import json
import math
import struct
MAGIC = b'HEX1'
MAX_DISPLAY_BYTES = 512 * 1024
MAP_TYPE = 'HEXMAP'
MAP_PAYLOAD_VERSION = 5
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
def map_canvas_size(paper: str, width=None, height=None, dpi: int = 96) -> tuple:
    """返回画布像素尺寸：CUSTOM 用自定义尺寸，A 系列纸张按 DPI 换算。"""
    if paper.upper() == 'CUSTOM' and width and height:
        return (int(width), int(height))
    return paper_size_pixels(paper, dpi)
def hex_layout(cols: int, width: int, height: int, margins=None) -> dict:
    """计算平顶六角格布局，可指定网格四周留白（边距）。
    采用奇数列错位（odd-q）排布：
    - 网格区域 = 画布尺寸减去 margins（l/r/t/b）
    - 横向每列间距 1.5 * cell_size
    - 纵向每行间距 sqrt(3) * cell_size，奇数列整体上移半行
    - cell_size = 网格宽 / (1.5 * cols + 0.5)，恰好让首末两列贴住网格区域左右边
    - 行数自动取整，保证网格区域底边也被六角格覆盖
    返回 dict：cell_size（中心到顶点的像素）、rows（纵向行数）、
    centers（[(列 q, 行 r, 中心 x, 中心 y), ...]）。
    """
    margins = margins or {}
    ml = max(0, int(margins.get('l', 0)))
    mr = max(0, int(margins.get('r', 0)))
    mt = max(0, int(margins.get('t', 0)))
    mb = max(0, int(margins.get('b', 0)))
    cols = max(1, int(cols))
    width = max(1, int(width))
    height = max(1, int(height))
    grid_w = max(1, width - ml - mr)
    grid_h = max(1, height - mt - mb)
    cell_size = grid_w / (1.5 * cols + 0.5)
    row_step = math.sqrt(3) * cell_size
    rows = int(math.ceil(grid_h / row_step)) + 1
    centers = []
    half_h = math.sqrt(3) * cell_size * 0.5
    for r in range(rows):
        for q in range(cols):
            x = ml + cell_size * (1.5 * q + 1.0)
            y = mt + row_step * r + half_h
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
def _encode_terrain_items(source):
    """把 {键: 名字/三元组} 编码成 JSON 对象；三元组表示单独指定的消耗与修正。"""
    out = {}
    for key, value in (source or {}).items():
        if isinstance(key, str):
            item_key = key
        else:
            item_key = '%d,%d' % (int(key[0]), int(key[1]))
        if isinstance(value, (list, tuple)):
            name = value[0] if len(value) > 0 else None
            if not name:
                continue
            cost = value[1] if len(value) > 1 else None
            modifier = value[2] if len(value) > 2 else None
            out[item_key] = [str(name), cost, modifier]
        elif value:
            out[item_key] = str(value)
    return out


def _decode_terrain_items(source, key_parser):
    """把 JSON 对象解码成 {键: 名字 或 (名字, 消耗, 修正)}。"""
    out = {}
    for key, value in (source or {}).items():
        parsed = key_parser(key)
        if parsed is None:
            continue
        if isinstance(value, (list, tuple)):
            name = str(value[0]) if len(value) > 0 and value[0] else ''
            if not name:
                continue
            cost = value[1] if len(value) > 1 else None
            modifier = value[2] if len(value) > 2 else None
            out[parsed] = (name,
                           None if cost is None else int(cost),
                           None if modifier is None else int(modifier))
        elif value:
            out[parsed] = str(value)
    return out


def _parse_cell_key(key):
    """格子键 "列,行" -> (列, 行)。"""
    try:
        parts = str(key).split(',')
        return (int(parts[0]), int(parts[1]))
    except Exception:
        return None


def _parse_edge_key(key):
    """格边键必须含分隔符 |，原样返回字符串。"""
    text = str(key)
    if '|' not in text:
        return None
    return text


def make_hex_map_payload(paper: str, cols: int, width=None, height=None, margins=None,
                         terrains=None, edges=None) -> bytes:
    """把画布文档序列化成 .hex 负载（JSON，UTF-8）。
    v5：新增 edges 格边地形表（键形如 "列,行|列,行" 或边界的 "列,行|方向"），
        cells/edges 的值都支持 "河流"（默认消耗/修正）或 ["河流", 3, -1]（单独指定）；
        v1~v4 文件仍可读取。
    """
    paper = paper.upper()
    doc = {'v': MAP_PAYLOAD_VERSION, 'paper': paper, 'cols': int(cols)}
    if paper == 'CUSTOM' and width and height:
        doc['width'] = int(width)
        doc['height'] = int(height)
    if margins:
        clean = {}
        for key in ('l', 't', 'r', 'b'):
            if key in margins:
                clean[key] = int(margins[key])
        if clean:
            doc['margins'] = clean
    cells = _encode_terrain_items(terrains)
    if cells:
        doc['cells'] = cells
    edge_items = _encode_terrain_items(edges)
    if edge_items:
        doc['edges'] = edge_items
    return json.dumps(doc, ensure_ascii=False).encode('utf-8')
def parse_hex_map_payload(payload: bytes):
    """解析画布文档负载；不是合法画布文档时返回 None。
    返回 dict：paper、cols、width、height、margins、terrains、edges。
    """
    try:
        doc = json.loads(payload.decode('utf-8'))
        version = doc.get('v')
        if version not in (1, 2, 3, 4, 5):
            return None
        paper = str(doc.get('paper', '')).upper()
        cols = int(doc.get('cols', 0))
        if cols < 1:
            return None
        margins = {}
        raw_margins = doc.get('margins') or {}
        for key in ('l', 't', 'r', 'b'):
            if key in raw_margins:
                margins[key] = int(raw_margins[key])
        terrains = _decode_terrain_items(doc.get('cells'), _parse_cell_key)
        edges = _decode_terrain_items(doc.get('edges'), _parse_edge_key)
        if paper == 'CUSTOM':
            width = int(doc.get('width', 0))
            height = int(doc.get('height', 0))
            if width >= 1 and height >= 1:
                return {'paper': paper, 'cols': cols, 'width': width, 'height': height,
                        'margins': margins, 'terrains': terrains, 'edges': edges}
            return None
        if paper not in PAPER_SIZES_MM:
            return None
        return {'paper': paper, 'cols': cols, 'width': None, 'height': None,
                'margins': margins, 'terrains': terrains, 'edges': edges}
    except Exception:
        return None