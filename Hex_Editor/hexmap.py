"""hexmap.py - 六角格单元与地图图结构（纯逻辑，不依赖界面）

- HexCell：一个格子。记录编号、行列坐标 (q, r)、中心坐标、三个地形属性
  （地形名字 terrain、移动力消耗 move_cost、地形修正 terrain_modifier），
  以及相邻的格子。
- HexMap：整张地图的格子集合。格子按行优先从 1 开始连续编号；
  相邻的六角格互相连接，形成一张无向图（每个格子最多 6 个邻居，边缘更少）。

地形分两类：
- 格子地形 TERRAINS：树林（绿）、山地（棕）、城市（黑）——决定"进入该格"的消耗；
- 格边地形 EDGE_TERRAINS：河流（蓝）——把某一条格边加粗成蓝色，决定"跨过这条边"的额外消耗。

跨格移动的消耗 = 目标格的格子地形消耗 + 跨过那条边的格边地形消耗。
移动力消耗 / 地形修正只是默认值，可按需修改这两张表。
"""
import heapq
import math

from hexformat import hex_corners, hex_layout

DIRECTIONS = ('N', 'NE', 'SE', 'S', 'SW', 'NW')
_MARGIN_KEYS = ('l', 't', 'r', 'b')
_OFFSETS_EVEN = ((0, -1), (1, -1), (1, 0), (0, 1), (-1, 0), (-1, -1))
_OFFSETS_ODD = ((0, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0))

# 格子地形表：名字 -> 颜色(RGB)、默认移动力消耗、默认地形修正（进入该格的消耗）
TERRAINS = {
    '树林': {'name': '树林', 'color': (60, 150, 70), 'move_cost': 2, 'modifier': -1},
    '山地': {'name': '山地', 'color': (150, 105, 60), 'move_cost': 3, 'modifier': -2},
    '城市': {'name': '城市', 'color': (0, 0, 0), 'move_cost': 1, 'modifier': -3},
}
TERRAIN_NAMES = ('树林', '山地', '城市')

# 格边地形表：名字 -> 颜色(RGB)、默认额外消耗、默认修正（跨过这条边的消耗）
EDGE_TERRAINS = {
    '河流': {'name': '河流', 'color': (70, 130, 200), 'move_cost': 2, 'modifier': -1},
}
EDGE_TERRAIN_NAMES = ('河流',)

# 旧版本（v4 及以前）把"河流"当作格子地形，这里保留定义，打开旧文件时仍能正确显示
TERRAINS.update({'河流': {'name': '河流', 'color': (70, 130, 200), 'move_cost': 3, 'modifier': -1}})
LEGACY_CELL_TERRAINS = ('河流',)

# 文件里出现、但不在表中的名字用这个颜色显示，避免静默丢失
UNKNOWN_TERRAIN_COLOR = (200, 200, 200)
# 每条边对应的方向：顶点 i 与 i+1 之间的边朝向 _EDGE_DIRECTIONS[i]
_EDGE_DIRECTIONS = ('SE', 'S', 'SW', 'NW', 'N', 'NE')


def neighbor_offsets(q):
    """列 q 的 6 个邻居偏移，顺序与 DIRECTIONS 一致。"""
    return _OFFSETS_ODD if (int(q) % 2) else _OFFSETS_EVEN


def normalize_margins(margins):
    """把边距统一成 l/t/r/b 四个非负整数。"""
    margins = margins or {}
    return {key: max(0, int(margins.get(key, 0))) for key in _MARGIN_KEYS}


def terrain_color(name):
    """地形颜色（RGB）：已知地形用表中颜色，未知地形用灰色，未设置返回 None。"""
    if not name:
        return None
    info = TERRAINS.get(name)
    if info is None:
        return UNKNOWN_TERRAIN_COLOR
    return info['color']


def edge_terrain_color(name):
    """格边地形颜色（RGB）：已知用表中颜色，未知用灰色，未设置返回 None。"""
    if not name:
        return None
    info = EDGE_TERRAINS.get(name)
    if info is None:
        return UNKNOWN_TERRAIN_COLOR
    return info['color']


def _point_segment_distance(px, py, p1, p2):
    """点 (px, py) 到线段 p1-p2 的最短距离。"""
    x1, y1 = p1
    x2, y2 = p2
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / float(dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


class HexEdge:
    """一条格边：连接两个相邻格子（地图边界上的边只属于一个格子），可带地形属性。

    格边地形决定"跨过这条边"的额外移动力消耗（例如河流）。
    """

    def __init__(self, key, cells, p1, p2, direction=None):
        self.key = key                  # 规范化坐标键（两端点排序）
        self.cells = tuple(cells)       # 相邻格子编号（1 个 = 地图边界，2 个 = 两格之间）
        self.p1 = p1                    # 端点坐标（文档坐标）
        self.p2 = p2
        self.direction = direction      # 建边时对应的方向（边界边用来做稳定键）
        self.terrain = None             # 格边地形名字（None = 无）
        self.move_cost = None           # 跨边额外移动力消耗
        self.terrain_modifier = None    # 格边地形修正

    @property
    def is_border(self):
        """是否是地图边界上的边（只属于一个格子）。"""
        return len(self.cells) == 1

    @property
    def length(self):
        return math.hypot(self.p2[0] - self.p1[0], self.p2[1] - self.p1[1])

    def midpoint(self):
        return ((self.p1[0] + self.p2[0]) / 2.0, (self.p1[1] + self.p2[1]) / 2.0)

    def other(self, cell_id):
        """这条边另一侧的格子编号；边界边返回 None。"""
        cell_id = int(cell_id)
        for cid in self.cells:
            if cid != cell_id:
                return cid
        return None

    def set_terrain(self, name, move_cost=None, modifier=None):
        """设置格边地形；name 为 None/空串时清除；未知名字原样保留（灰色显示）。"""
        if name is None or name == '':
            self.terrain = None
            self.move_cost = None
            self.terrain_modifier = None
            return self
        info = EDGE_TERRAINS.get(name)
        self.terrain = info['name'] if info is not None else str(name)
        default_cost = info['move_cost'] if info is not None else None
        default_modifier = info['modifier'] if info is not None else None
        self.move_cost = default_cost if move_cost is None else int(move_cost)
        self.terrain_modifier = default_modifier if modifier is None else int(modifier)
        return self

    def clear_terrain(self):
        return self.set_terrain(None)

    def terrain_info(self):
        return {
            'terrain': self.terrain,
            'move_cost': self.move_cost,
            'terrain_modifier': self.terrain_modifier,
        }

    def terrain_color(self):
        return edge_terrain_color(self.terrain)

    def to_dict(self):
        return {
            'cells': list(self.cells),
            'direction': self.direction,
            'terrain': self.terrain,
            'move_cost': self.move_cost,
            'terrain_modifier': self.terrain_modifier,
        }

    def __repr__(self):
        return 'HexEdge(格子=%s, 方向=%s, 地形=%s)' % (list(self.cells), self.direction, self.terrain or '无')


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

    @property
    def is_known_terrain(self):
        """地形名字是否在 TERRAINS 表中（空地为 False）。"""
        return bool(self.terrain) and self.terrain in TERRAINS

    def corners(self):
        """该格 6 个顶点的坐标列表。"""
        return hex_corners(self.cx, self.cy, self.cell_size)

    def set_terrain(self, name, move_cost=None, modifier=None):
        """设置地形，并套用该地形的默认移动力消耗与地形修正。

        name 为 None 或空字符串时清空地形（空地）。
        不在 TERRAINS 中的名字会被原样保留（视为未知地形，用灰色显示），
        以免读入旧文件时静默丢数据；此时消耗/修正取传入值或 None。
        传入 move_cost / modifier 可覆盖默认值（用于单个格子的特殊调整）。
        """
        if name is None or name == '':
            self.terrain = None
            self.move_cost = None
            self.terrain_modifier = None
            return self
        info = TERRAINS.get(name)
        self.terrain = info['name'] if info is not None else str(name)
        default_cost = info['move_cost'] if info is not None else None
        default_modifier = info['modifier'] if info is not None else None
        self.move_cost = default_cost if move_cost is None else int(move_cost)
        self.terrain_modifier = default_modifier if modifier is None else int(modifier)
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
        self.edges = {}                 # 规范化坐标键 -> HexEdge
        self.edge_index = {}            # 稳定语义键 -> HexEdge
        self.edge_by_cells = {}         # (较小编号, 较大编号) -> HexEdge
        self._build_edges(previous)

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

    def _edge_key(self, p1, p2):
        a = (round(p1[0], 2), round(p1[1], 2))
        b = (round(p2[0], 2), round(p2[1], 2))
        return (a, b) if a <= b else (b, a)

    def _build_edges(self, previous=None):
        """按格子顶点生成所有格边：相邻格共享的边只保留一条，边界边只有一格。"""
        for cell in self.cells.values():
            corners = cell.corners()
            total = len(corners)
            for i in range(total):
                p1 = corners[i]
                p2 = corners[(i + 1) % total]
                key = self._edge_key(p1, p2)
                edge = self.edges.get(key)
                if edge is None:
                    edge = HexEdge(key, [cell.id], p1, p2, _EDGE_DIRECTIONS[i % len(_EDGE_DIRECTIONS)])
                    self.edges[key] = edge
                elif cell.id not in edge.cells:
                    edge.cells = edge.cells + (cell.id,)
        for edge in self.edges.values():
            if len(edge.cells) == 2:
                lo, hi = sorted(edge.cells)
                self.edge_by_cells[(lo, hi)] = edge
        self._rebuild_edge_index()
        if previous is not None:
            for key, edge in self.edges.items():
                old = previous.edge_by_key(key)
                if old is not None and old.terrain:
                    edge.terrain = old.terrain
                    edge.move_cost = old.move_cost
                    edge.terrain_modifier = old.terrain_modifier

    def _rebuild_edge_index(self):
        self.edge_index = {}
        for edge in self.edges.values():
            self.edge_index[self.edge_semantic_key(edge)] = edge

    def edge_semantic_key(self, edge):
        """格边的稳定键：两格之间为 "q1,r1|q2,r2"，地图边界为 "q,r|方向"。"""
        if len(edge.cells) == 2:
            a = self.cells[edge.cells[0]]
            b = self.cells[edge.cells[1]]
            pair = sorted([(a.q, a.r), (b.q, b.r)])
            return '%d,%d|%d,%d' % (pair[0][0], pair[0][1], pair[1][0], pair[1][1])
        cell = self.cells[edge.cells[0]]
        return '%d,%d|%s' % (cell.q, cell.r, edge.direction or 'N')

    def edge_by_key(self, key):
        """按稳定键取格边。"""
        key = str(key)
        if '|' not in key:
            return None
        left, right = key.split('|', 1)
        if ',' in right:
            try:
                q1, r1 = [int(v) for v in left.split(',')]
                q2, r2 = [int(v) for v in right.split(',')]
            except Exception:
                return None
            a = self.cell_at(q1, r1)
            b = self.cell_at(q2, r2)
            if a is None or b is None:
                return None
            return self.edge_between(a.id, b.id)
        return self.edge_index.get(key)

    def edge_between(self, cell_a, cell_b):
        """两格之间的格边；不相邻返回 None。"""
        pair = (min(int(cell_a), int(cell_b)), max(int(cell_a), int(cell_b)))
        return self.edge_by_cells.get(pair)

    def edges_of(self, cell_id):
        """与某格相接的所有格边。"""
        cell_id = int(cell_id)
        return [edge for edge in self.edges.values() if cell_id in edge.cells]

    def edge_at_point(self, x, y, max_distance=None):
        """离点 (x, y) 最近的格边；超出 max_distance 时返回 None。"""
        best = None
        best_dist = None
        for edge in self.edges.values():
            dist = _point_segment_distance(x, y, edge.p1, edge.p2)
            if best_dist is None or dist < best_dist:
                best = edge
                best_dist = dist
        if best is None:
            return None
        if max_distance is not None and best_dist > max_distance:
            return None
        return best

    def apply_edges(self, mapping):
        """按稳定键批量设置格边地形，返回生效的边数。"""
        count = 0
        for key, value in (mapping or {}).items():
            edge = self.edge_by_key(key)
            if edge is None:
                continue
            if isinstance(value, (list, tuple)):
                name = value[0] if len(value) > 0 else None
                cost = value[1] if len(value) > 1 else None
                modifier = value[2] if len(value) > 2 else None
                edge.set_terrain(name, cost, modifier)
            else:
                edge.set_terrain(value)
            count += 1
        return count

    def edge_terrain_cells(self):
        """导出可保存的格边地形表（默认值只存名字，自定义过消耗/修正的存三元组）。"""
        out = {}
        for edge in self.edges.values():
            if not edge.terrain:
                continue
            info = EDGE_TERRAINS.get(edge.terrain)
            key = self.edge_semantic_key(edge)
            if (info is not None and edge.move_cost == info['move_cost']
                    and edge.terrain_modifier == info['modifier']):
                out[key] = edge.terrain
            else:
                out[key] = [edge.terrain, edge.move_cost, edge.terrain_modifier]
        return out

    def edge_terrain_counts(self):
        """统计各格边地形的数量。"""
        counts = {}
        for edge in self.edges.values():
            if edge.terrain:
                counts[edge.terrain] = counts.get(edge.terrain, 0) + 1
        return counts

    def unknown_edge_terrains(self):
        """出现过、但不在 EDGE_TERRAINS 表中的格边地形名。"""
        return sorted({edge.terrain for edge in self.edges.values()
                       if edge.terrain and edge.terrain not in EDGE_TERRAINS})

    # ---------- 移动力 ----------
    def enter_cost(self, cell_id, from_cell_id=None):
        """进入某格的消耗 = 该格地形消耗 + 跨过那条边的额外消耗（无地形时按 1 计）。"""
        cell = self.cells[int(cell_id)]
        base = cell.move_cost if cell.move_cost is not None else 1
        if from_cell_id is None:
            return base
        edge = self.edge_between(from_cell_id, cell_id)
        if edge is not None and edge.terrain:
            return base + (edge.move_cost or 0)
        return base

    def move_options(self, cell_id):
        """从某格出发的所有走法：[(邻居编号, 消耗), ...]。"""
        return [(nid, self.enter_cost(nid, cell_id)) for nid in self.cells[int(cell_id)].neighbors]

    def find_path(self, start_id, goal_id, max_cost=None):
        """按移动力消耗求最省路径（Dijkstra）。返回 (格子编号列表, 总消耗)；不可达返回 (None, None)。"""
        start_id = int(start_id)
        goal_id = int(goal_id)
        if start_id not in self.cells or goal_id not in self.cells:
            return None, None
        dist = {start_id: 0}
        prev = {}
        heap = [(0, start_id)]
        while heap:
            cost_so_far, current = heapq.heappop(heap)
            if cost_so_far > dist.get(current, float('inf')):
                continue
            if current == goal_id:
                break
            for nid, step in self.move_options(current):
                new_cost = cost_so_far + step
                if max_cost is not None and new_cost > max_cost:
                    continue
                if new_cost < dist.get(nid, float('inf')):
                    dist[nid] = new_cost
                    prev[nid] = current
                    heapq.heappush(heap, (new_cost, nid))
        if goal_id not in dist:
            return None, None
        path = [goal_id]
        while path[-1] != start_id:
            path.append(prev[path[-1]])
        path.reverse()
        return path, dist[goal_id]

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
        """批量设置地形，返回生效的格子数。

        键可以是 "列,行" 字符串或 (列, 行) 元组；
        值可以是地形名字符串，也可以是 (名字, 消耗, 修正) 序列。
        """
        count = 0
        for key, value in (mapping or {}).items():
            if isinstance(key, str):
                parts = key.split(',')
                q, r = int(parts[0]), int(parts[1])
            else:
                q, r = int(key[0]), int(key[1])
            cell = self.cell_at(q, r)
            if cell is None:
                continue
            if isinstance(value, (list, tuple)):
                name = value[0] if len(value) > 0 else None
                cost = value[1] if len(value) > 1 else None
                modifier = value[2] if len(value) > 2 else None
                cell.set_terrain(name, cost, modifier)
            else:
                cell.set_terrain(value)
            count += 1
        return count

    def terrain_map(self):
        """导出 {(q, r): 地形名}（只含已设置地形的格子）。"""
        return {(cell.q, cell.r): cell.terrain for cell in self.cells.values() if cell.terrain}

    def terrain_cells(self):
        """导出可保存的地形表。

        与地形默认值相同的格子只存名字；单独改过消耗/修正的格子存 [名字, 消耗, 修正]。
        """
        out = {}
        for cell in self.cells.values():
            if not cell.terrain:
                continue
            info = TERRAINS.get(cell.terrain)
            if (info is not None and cell.move_cost == info['move_cost']
                    and cell.terrain_modifier == info['modifier']):
                out[(cell.q, cell.r)] = cell.terrain
            else:
                out[(cell.q, cell.r)] = [cell.terrain, cell.move_cost, cell.terrain_modifier]
        return out

    def unknown_terrains(self):
        """文件里出现过、但不在 TERRAINS 表中的地形名（去重排序）。"""
        names = set()
        for cell in self.cells.values():
            if cell.terrain and cell.terrain not in TERRAINS:
                names.add(cell.terrain)
        return sorted(names)

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
            'edge_terrains': self.edge_terrain_counts(),
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
            'edges': [edge.to_dict() for edge in self.edges.values() if edge.terrain],
        }

    def __len__(self):
        return len(self.cells)

    def __repr__(self):
        return 'HexMap(%d列×%d行, %d 格, %d 条相邻边)' % (
            self.cols, self.rows, len(self.cells), self.edge_count()
        )
