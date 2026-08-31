"""hexformat.py - .hex 容器与十六进制视图格式化（纯逻辑，不依赖界面）"""

import struct

MAGIC = b'HEX1'
MAX_DISPLAY_BYTES = 512 * 1024


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
