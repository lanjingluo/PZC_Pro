"""hexmap.py - 六角格单元与地图图结构（纯逻辑，不依赖界面）

- HexCell：一个格子。记录编号、行列坐标 (q, r)、中心坐标、三个地形属性
  （地形名字 terrain、移动力消耗 move_cost、地形修正 terrain_modifier），
  以及相邻的格子。
- HexMap：整张地图的格子集合。格子按行优先从 1 开始连续编号；
  相邻的六角格互相连接，形成一张无向图（每个格子最多 6 个邻居，边缘更少）。

地形定义见 TERRAINS：树林（绿）、山地（棕）、城市（黑）。
移动力消耗 / 地形修正只是默认值，可按需修改这张表。
"""
import math

from hexformat import hex_corners, hex_layout

DIRECTIONS = ('N', 'NE', 'SE', 'S', 'SW', 'NW')
_MARGIN_KEYS = ('l', 't', 'r', 'b')
_OFFSETS_EVEN = ((0, -1), (1, -1), (1, 0), (0, 1), (-1, 0), (-1, -1))
_OFFSETS_ODD = ((0, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0))

# 地形表：名字 -> 颜色(RGB)、默认移动力消耗、默认地形修正
TERRAINS = {
    '树林': {'name': '树林', 'color': (60, 150, 70), 'move_cost': 2, 'modifier': -1},
    '山地': {'name': '山地', 'color': (150, 105, 60), 'move_cost': 3, 'modifier': -2},
    '城市': {'name': '城市', 'color': (0, 0, 0), 'move_cost': 1, 'modifier': -3},
}
TERRAIN_NAMES = ('树林', '山地', '城市')


def neighbor_offsets(q):
    """列 q 的 6 个邻居偏移，顺序与 DIRECTIONS 一致。"""
    return _OFFSETS_ODD if (int(q) % 2) else _OFFSETS_EVEN


def normalize_margins(margins):
    """把边距统一成 l/t/r/b 四个非负整数。"""
    margins = margins or {}
    return {key: max(0, int(margins.get(key, 0))) for key in _MARGIN_KEYS}


def terrain_color(name):
    """地形颜色（RGB），未设置地形返回 None。"""
    info = TERRAINS.get(name)
    if info is None:
        return None
    return info['color']


class HexCell:
    """一个六角格：编号、坐标、几何、地形属性与相邻关系。"""

    def __init__(self, cell_id, q, r, cx, cy, cell_size):
        self.id = int(cell_id)          # 编号（从 1 开始，按行从左到右）
        self.q = int(q)                 # 列
        self.r = int(r)                 # 行
        self.cx = float(cx)             # 中心 x
        self.cy = float(cy)             # 中心 y
        self.cell_size = float(cell_size)
        self.neighbors = []             # 相邻格子编号
        self.neighbor_map = {}          # 方向 -> 相邻格子编号（边界缺失的方向不出现）
        self.attrs = {}                 # 其它自定义属性
        self.terrain = None             # 地形名字（None 表示空地）
        self.move_cost = None           # 移动力消耗
        self.terrain_modifier = None    # 地形修正

    @property
    def number(self):
        return self.id

    @property
    def degree(self):
        """相邻格子数量（0-6）。"""
        return len(self.neighbors)

    @property
    def is_empty(self):
        """是否是未设置地形的空地。"""
        return self.terrain is None

    def corners(self):
        """该格 6 个顶点的坐标列表。"""
        return hex_corners(self.cx, self.cy, self.cell_size)

    def set_terrain(self, name, move_cost=None, modifier=None):
        """设置地形，并套用该地形的默认移动力消耗与地形修正。

        name 为 None 或不在 TERRAINS 中时清空地形；
        传入 move_cost / modifier 可覆盖默认值（用于单个格子的特殊调整）。
        """
        info = TERRAINS.get(name)
        if info is None:
            self.terrain = None
            self.move_cost = None
            self.terrain_modifier = None
        else:
            self.terrain = info['name']
            self.move_cost = info['move_cost'] if move_cost is None else int(move_cost)
            self.terrain_modifier = info['modifier'] if modifier is None else int(modifier)
        return self

    def clear_terrain(self):
        """把格子恢复成空地。"""
        return self.set_terrain(None)

    def terrain_info(self):
        """三个地形属性的当前值。"""
        return {
            'terrain': self.terrain,
            'move_cost': self.move_cost,
            'terrain_modifier': self.terrain_modifier,
        }

    def terrain_color(self):
        return terrain_color(self.terrain)

    # ---------- 其它自定义属性 ----------
    def set_attr(self, key, value):
        self.attrs[key] = value
        return self

    def get_attr(self, key, default=None):
        return self.attrs.get(key, default)

    def clear_attr(self, key):
        self.attrs.pop(key, None)

    def to_dict(self):
        return {
            'id': self.id,
            'q': self.q,
            'r': self.r,
            'cx': round(self.cx, 3),
            'cy': round(self.cy, 3),
            'neighbors': list(self.neighbors),
            'neighbor_map': dict(self.neighbor_map),
            'terrain': self.terrain,
            'move_cost': self.move_cost,
            'terrain_modifier': self.terrain_modifier,
            'attrs': dict(self.attrs),
        }

    def __repr__(self):
        return 'HexCell(#%d, q=%d, r=%d, 地形=%s, 邻居=%d)' % (
            self.id, self.q, self.r, self.terrain or '空地', len(self.neighbors)
        )


class HexMap:
    """整张地图：六角格集合 + 相邻关系图。"""

    def __init__(self, cols, width, height, margins=None, previous=None):
        layout = hex_layout(cols, width, height, margins)
        self.cols = max(1, int(cols))
        self.rows = layout['rows']
        self.cell_size = layout['cell_size']
        self.width = int(width)
        self.height = int(height)
        self.margins = normalize_margins(margins)
        self.cells = {}                 # 编号 -> HexCell
        self.index = {}                 # (q, r) -> 编号
        for q, r, cx, cy in layout['centers']:
            cell_id = r * self.cols + q + 1
            cell = HexCell(cell_id, q, r, cx, cy, self.cell_size)
            if previous is not None:
                old = previous.cell_at(q, r)
                if old is not None:
                    cell.attrs = dict(old.attrs)
                    cell.terrain = old.terrain
                    cell.move_cost = old.move_cost
                    cell.terrain_modifier = old.terrain_modifier
            self.cells[cell_id] = cell
            self.index[(q, r)] = cell_id
        self._link_neighbors()

    def _link_neighbors(self):
        for cell in self.cells.values():
            ids = []
            dir_map = {}
            for pos, (dq, dr) in enumerate(neighbor_offsets(cell.q)):
                other = self.index.get((cell.q + dq, cell.r + dr))
                if other is not None:
                    ids.append(other)
                    dir_map[DIRECTIONS[pos]] = other
            cell.neighbors = ids
            cell.neighbor_map = dir_map

    # ---------- 查询 ----------
    def cell(self, cell_id):
        """按编号取格子。"""
        return self.cells[int(cell_id)]

    def cell_at(self, q, r):
        """按行列坐标取格子；不存在返回 None。"""
        cell_id = self.index.get((int(q), int(r)))
        if cell_id is None:
            return None
        return self.cells[cell_id]

    def cell_at_point(self, x, y):
        """点 (x, y) 落在哪个格子里（坐标按画布尺寸，不含缩放）；没命中返回 None。"""
        apothem = math.sqrt(3) / 2.0 * self.cell_size
        cos30 = math.sqrt(3) / 2.0
        sin30 = 0.5
        for cell in self.cells.values():
            dx = x - cell.cx
            if abs(dx) > self.cell_size:
                continue
            dy = y - cell.cy
            if abs(dy) > apothem:
                continue
            if abs(cos30 * dx + sin30 * dy) > apothem:
                continue
            if abs(-sin30 * dx + cos30 * dy) > apothem:
                continue
            return cell
        return None

    def neighbor_ids(self, cell_id):
        return list(self.cells[int(cell_id)].neighbors)

    def neighbors(self, cell_id):
        return [self.cells[nid] for nid in self.cells[int(cell_id)].neighbors]

    def neighbor(self, cell_id, direction):
        """按方向取邻居：N、NE、SE、S、SW、NW；该方向没有格子时返回 None。"""
        if direction not in DIRECTIONS:
            raise ValueError('未知方向：%s' % direction)
        other = self.cells[int(cell_id)].neighbor_map.get(direction)
        if other is None:
            return None
        return self.cells[other]

    def direction_of(self, cell_id, other_id):
        """从 cell_id 看向 other_id 的方向名；不相邻时返回 None。"""
        for name, nid in self.cells[int(cell_id)].neighbor_map.items():
            if nid == int(other_id):
                return name
        return None

    def are_adjacent(self, a, b):
        return int(b) in self.cells[int(a)].neighbors

    def iter_cells(self):
        """按编号从小到大遍历所有格子。"""
        for cell_id in sorted(self.cells):
            yield self.cells[cell_id]

    # ---------- 地形 ----------
    def apply_terrains(self, mapping):
        """批量设置地形：{(q, r): 地形名}；返回生效的格子数。"""
        count = 0
        for key, name in (mapping or {}).items():
            if isinstance(key, str):
                parts = key.split(',')
                q, r = int(parts[0]), int(parts[1])
            else:
                q, r = int(key[0]), int(key[1])
            cell = self.cell_at(q, r)
            if cell is not None:
                cell.set_terrain(name)
                count += 1
        return count

    def terrain_map(self):
        """导出 {(q, r): 地形名}（只含已设置地形的格子）。"""
        return {(cell.q, cell.r): cell.terrain for cell in self.cells.values() if cell.terrain}

    def terrain_counts(self):
        """统计各地形的格子数。"""
        counts = {}
        for cell in self.cells.values():
            if cell.terrain:
                counts[cell.terrain] = counts.get(cell.terrain, 0) + 1
        return counts

    # ---------- 统计 ----------
    def edge_count(self):
        return sum(len(cell.neighbors) for cell in self.cells.values()) // 2

    def degree_stats(self):
        if not self.cells:
            return {'min': 0, 'max': 0, 'avg': 0.0}
        degrees = [len(cell.neighbors) for cell in self.cells.values()]
        return {'min': min(degrees), 'max': max(degrees), 'avg': sum(degrees) / float(len(degrees))}

    def is_connected(self):
        if not self.cells:
            return True
        start = next(iter(self.cells))
        seen = {start}
        queue = [start]
        while queue:
            current = queue.pop()
            for nid in self.cells[current].neighbors:
                if nid not in seen:
                    seen.add(nid)
                    queue.append(nid)
        return len(seen) == len(self.cells)

    def summary(self):
        stats = self.degree_stats()
        return {
            'cols': self.cols,
            'rows': self.rows,
            'cells': len(self.cells),
            'edges': self.edge_count(),
            'degree_min': stats['min'],
            'degree_max': stats['max'],
            'connected': self.is_connected(),
            'terrains': self.terrain_counts(),
        }

    def to_dict(self):
        return {
            'cols': self.cols,
            'rows': self.rows,
            'cell_size': round(self.cell_size, 4),
            'width': self.width,
            'height': self.height,
            'margins': dict(self.margins),
            'cells': [cell.to_dict() for cell in self.iter_cells()],
        }

    def __len__(self):
        return len(self.cells)

    def __repr__(self):
        return 'HexMap(%d列×%d行, %d 格, %d 条相邻边)' % (
            self.cols, self.rows, len(self.cells), self.edge_count()
        )
