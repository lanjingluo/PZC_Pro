"""hexmap.py - 六角格单元与地图图结构（纯逻辑，不依赖界面）

- HexCell：一个格子，记录编号、行列坐标 (q, r)、中心坐标、自定义属性 attrs，
  以及与之相邻的格子编号。
- HexMap：整张地图的格子集合。格子按行优先从 1 开始连续编号；
  相邻的六角格之间互相连接，形成一张无向图（沿边相邻，每个格子最多 6 个邻居，
  边缘格子会少一些）。

平顶六角格、奇数列下移半行（odd-q）的邻居偏移：
偶数列与奇数列的偏移不同，边缘超出地图的邻居会被忽略。
"""
from hexformat import hex_corners, hex_layout

DIRECTIONS = ('N', 'NE', 'SE', 'S', 'SW', 'NW')
_MARGIN_KEYS = ('l', 't', 'r', 'b')
_OFFSETS_EVEN = ((0, -1), (1, -1), (1, 0), (0, 1), (-1, 0), (-1, -1))
_OFFSETS_ODD = ((0, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0))


def neighbor_offsets(q):
    """列 q 的 6 个邻居偏移，顺序与 DIRECTIONS 一致。"""
    return _OFFSETS_ODD if (int(q) % 2) else _OFFSETS_EVEN


def normalize_margins(margins):
    """把边距统一成 l/t/r/b 四个非负整数。"""
    margins = margins or {}
    return {key: max(0, int(margins.get(key, 0))) for key in _MARGIN_KEYS}


class HexCell:
    """一个六角格：编号、坐标、几何与自定义属性。"""

    def __init__(self, cell_id, q, r, cx, cy, cell_size):
        self.id = int(cell_id)          # 编号（从 1 开始，按行从左到右）
        self.q = int(q)                 # 列
        self.r = int(r)                 # 行
        self.cx = float(cx)             # 中心 x
        self.cy = float(cy)             # 中心 y
        self.cell_size = float(cell_size)
        self.neighbors = []             # 相邻格子编号（含全部存在的邻居）
        self.neighbor_map = {}          # 方向 -> 相邻格子编号（边界上缺失的方向不出现）
        self.attrs = {}                 # 自定义属性：颜色、文字、占用情况等

    @property
    def number(self):
        """格子编号（与 id 相同）。"""
        return self.id

    @property
    def degree(self):
        """相邻格子数量（0-6）。"""
        return len(self.neighbors)

    def corners(self):
        """该格 6 个顶点的坐标列表。"""
        return hex_corners(self.cx, self.cy, self.cell_size)

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
            'attrs': dict(self.attrs),
        }

    def __repr__(self):
        return 'HexCell(#%d, q=%d, r=%d, 邻居=%d)' % (self.id, self.q, self.r, len(self.neighbors))


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
                if old is not None and old.attrs:
                    cell.attrs = dict(old.attrs)
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

    def neighbor_ids(self, cell_id):
        """相邻格子的编号列表。"""
        return list(self.cells[int(cell_id)].neighbors)

    def neighbors(self, cell_id):
        """相邻格子对象列表。"""
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
        """两个格子是否相邻。"""
        return int(b) in self.cells[int(a)].neighbors

    def iter_cells(self):
        """按编号从小到大遍历所有格子。"""
        for cell_id in sorted(self.cells):
            yield self.cells[cell_id]

    # ---------- 统计 ----------
    def edge_count(self):
        """相邻边的数量（无向图，每条边只算一次）。"""
        return sum(len(cell.neighbors) for cell in self.cells.values()) // 2

    def degree_stats(self):
        if not self.cells:
            return {'min': 0, 'max': 0, 'avg': 0.0}
        degrees = [len(cell.neighbors) for cell in self.cells.values()]
        return {'min': min(degrees), 'max': max(degrees), 'avg': sum(degrees) / float(len(degrees))}

    def is_connected(self):
        """整张图是否连通。"""
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
        """地图与图结构的简要统计。"""
        stats = self.degree_stats()
        return {
            'cols': self.cols,
            'rows': self.rows,
            'cells': len(self.cells),
            'edges': self.edge_count(),
            'degree_min': stats['min'],
            'degree_max': stats['max'],
            'connected': self.is_connected(),
        }

    def to_dict(self):
        """导出为可序列化的字典（含每个格子的属性）。"""
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
