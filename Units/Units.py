"""Units.py - 单位模型与单位编成（纯逻辑，不依赖界面）

核心是 Units 类，一支单位的字段如下：

| 字段 | 含义 |
|------|------|
| name | 单位名字（番号） |
| type | 类型，对应 TYPE_TEMPLATES 的模板名（如 '装甲营'） |
| soft_attack | 软攻，打步兵等软目标的攻击力 |
| hard_attack | 硬攻，打装甲等硬目标的攻击力 |
| defense | 防御 |
| move | 移动力（当前剩余；move_max 记住本回合上限） |
| move_type | 移动类型，MOVE_TYPES 的键（徒步/骑兵/摩托化/履带……） |
| attached_units | 挂属单位：挂在这支单位下面的下级单位列表，可多层嵌套 |
| breakthrough | 突破：0 表示不具备突破能力，大于 0 为突破值 |
| step | 数量（兵力步数），减到 0 即被歼灭 |
| branch | 兵种，BRANCHES 里的名字（步兵/装甲/炮兵……） |
| establishment | 编制（编制表或隶属番号，字符串） |
| faction | 阵营（所属阵营/国家，字符串） |

另有三个框架字段，不属于游戏属性，只用于组织与存档：
id（编号，挂属与引用都用它）、attached_to（上级编号）、attrs（自定义扩展数据）。

常用操作：
    unit = Units.from_type('装甲营', name='第 1 装甲营', step=3)
    unit.attack_power('hard')          # 硬攻打装甲
    unit.defense_power(attacker=enemy)
    unit.combat_odds(enemy, kind='hard')   # 攻防比
    unit.spend_move(2)                 # 扣移动力
    unit.reset_turn()                  # 新回合复位
    unit.attach(sub)                   # 把下级单位挂上来
    unit.total_step()                  # 自身 + 挂属的数量合计
    unit.take_loss(1)                  # 数量 -1，归零即被歼灭

    roster = UnitRoster()              # 编成集合：管理许多单位
    roster.add(unit)
    roster.by_branch('装甲')
    roster.save_json('oob.json')

规则集中在这几张表里，按需要改表即可，不用改代码：
MOVE_TYPES 移动类型、BRANCHES 兵种、BRANCH_MATCHUPS 兵种克制、
TYPE_TEMPLATES 类型模板、ESTABLISHMENTS 编制名称、MOVE_TERRAIN_PENALTY 地形对移动的影响。
"""
import json

# 移动类型：名字 -> {mechanized: 是否机械化, desc: 说明}
MOVE_TYPES = {
    '徒步': {'mechanized': False, 'desc': '步行 / 骡马运输'},
    '骑兵': {'mechanized': False, 'desc': '骑马机动'},
    '自行车': {'mechanized': False, 'desc': '自行车机动'},
    '滑雪': {'mechanized': False, 'desc': '雪地机动'},
    '摩托化': {'mechanized': True, 'desc': '卡车输送'},
    '履带': {'mechanized': True, 'desc': '坦克 / 装甲车辆'},
    '半履带': {'mechanized': True, 'desc': '装甲输送车'},
    '两栖': {'mechanized': True, 'desc': '可涉水 / 登陆'},
    '航空': {'mechanized': True, 'desc': '飞行单位'},
}
MOVE_TYPE_NAMES = tuple(MOVE_TYPES)

# 兵种
BRANCHES = (
    '步兵', '装甲', '骑兵', '炮兵', '反坦克', '防空',
    '侦察', '工兵', '通信', '后勤', '指挥部', '航空',
)

# 类型模板：类型名 -> 建单位时的默认属性（可逐个覆盖）
TYPE_TEMPLATES = {
    '步兵营': {
        'branch': '步兵', 'soft_attack': 12, 'hard_attack': 2, 'defense': 14,
        'move': 4, 'move_type': '徒步', 'step': 3, 'establishment': '营',
    },
    '装甲营': {
        'branch': '装甲', 'soft_attack': 20, 'hard_attack': 24, 'defense': 22,
        'move': 7, 'move_type': '履带', 'step': 3, 'establishment': '营',
    },
    '机械化步兵营': {
        'branch': '步兵', 'soft_attack': 16, 'hard_attack': 8, 'defense': 18,
        'move': 6, 'move_type': '半履带', 'step': 3, 'establishment': '营',
    },
    '骑兵营': {
        'branch': '骑兵', 'soft_attack': 10, 'hard_attack': 2, 'defense': 10,
        'move': 8, 'move_type': '骑兵', 'step': 2, 'establishment': '营',
    },
    '炮兵营': {
        'branch': '炮兵', 'soft_attack': 26, 'hard_attack': 6, 'defense': 6,
        'move': 3, 'move_type': '摩托化', 'step': 2, 'establishment': '营',
    },
    '反坦克营': {
        'branch': '反坦克', 'soft_attack': 4, 'hard_attack': 28, 'defense': 10,
        'move': 5, 'move_type': '摩托化', 'step': 2, 'establishment': '营',
    },
    '防空营': {
        'branch': '防空', 'soft_attack': 8, 'hard_attack': 6, 'defense': 8,
        'move': 4, 'move_type': '摩托化', 'step': 2, 'establishment': '营',
    },
    '侦察连': {
        'branch': '侦察', 'soft_attack': 6, 'hard_attack': 6, 'defense': 8,
        'move': 8, 'move_type': '摩托化', 'step': 1, 'establishment': '连',
    },
    '工兵连': {
        'branch': '工兵', 'soft_attack': 8, 'hard_attack': 4, 'defense': 10,
        'move': 4, 'move_type': '徒步', 'step': 1, 'establishment': '连',
    },
    '指挥部': {
        'branch': '指挥部', 'soft_attack': 2, 'hard_attack': 0, 'defense': 6,
        'move': 6, 'move_type': '摩托化', 'step': 1, 'establishment': '营',
    },
    '航空中队': {
        'branch': '航空', 'soft_attack': 18, 'hard_attack': 16, 'defense': 4,
        'move': 0, 'move_type': '航空', 'step': 1, 'establishment': '连',
    },
}
TYPE_NAMES = tuple(TYPE_TEMPLATES)

# 编制名称（规模），给 establishment 字段做参考 / 下拉用
ESTABLISHMENTS = ('班', '排', '连', '营', '团', '旅', '师', '军', '集团军')

# 兵种克制：攻击方兵种 -> 目标兵种 -> 系数（查不到按 1.0）
BRANCH_MATCHUPS = {
    '反坦克': {'装甲': 1.5},
    '装甲': {'步兵': 1.3, '炮兵': 1.3, '指挥部': 1.5, '后勤': 1.4},
    '炮兵': {'步兵': 1.2, '指挥部': 1.4, '后勤': 1.3, '装甲': 0.8},
    '防空': {'航空': 1.6},
    '航空': {'装甲': 1.3, '炮兵': 1.3, '指挥部': 1.3, '防空': 0.7},
    '工兵': {'指挥部': 1.2},
    '侦察': {'指挥部': 1.2, '后勤': 1.2},
    '骑兵': {'后勤': 1.3, '炮兵': 1.2},
}

# 移动类型在特定地形上的额外消耗系数（缺省 1.0）
MOVE_TERRAIN_PENALTY = {
    '履带': {'树林': 1.5, '山地': 1.5, '城市': 1.2},
    '半履带': {'树林': 1.5, '山地': 1.5},
    '摩托化': {'树林': 1.5, '山地': 2.0},
    '骑兵': {'树林': 1.2, '山地': 1.5},
    '自行车': {'山地': 1.5},
    '滑雪': {'树林': 0.8, '山地': 0.8},
}

# 战力系数
STEP_POWER_FLOOR = 0.4            # 数量只剩最小编制时保留的战力比例
BREAKTHROUGH_ATTACK_BONUS = 0.15  # 每 1 点突破带来的攻击加成


def clamp(value, low, high):
    """把 value 夹在 [low, high] 之间。"""
    return max(low, min(high, value))


# Units 构造函数的字段名（from_type 用它区分"属性"与"扩展数据"）
_FIELDS = frozenset((
    'name', 'type', 'soft_attack', 'hard_attack', 'defense', 'move',
    'move_type', 'attached_units', 'breakthrough', 'step', 'branch',
    'establishment', 'faction',
))


def branch_multiplier(attacker_branch, target_branch):
    """兵种克制系数：反坦克打装甲之类，查不到返回 1.0。"""
    return float(BRANCH_MATCHUPS.get(attacker_branch, {}).get(target_branch, 1.0))


def terrain_move_factor(move_type, terrain=None):
    """某个移动类型在某种地形上的消耗系数（缺省 1.0）。"""
    if not terrain:
        return 1.0
    return float(MOVE_TERRAIN_PENALTY.get(move_type, {}).get(terrain, 1.0))


class Units:
    """一支单位：上面那张字段表 + 移动、战斗、挂属、存档等操作。

    直接构造时所有字段都可以显式传入；更常见的做法是用 from_type()
    按 TYPE_TEMPLATES 里的模板建单位，再覆盖个别字段。
    """

    def __init__(self, name='', type='', soft_attack=0, hard_attack=0, defense=0,
                 move=0, move_type='徒步', attached_units=None,
                 breakthrough=0, step=1, branch='步兵', establishment='',
                 faction='', unit_id=None):
        # ---- 游戏属性 ----
        self.name = str(name)                     # 单位名字
        self.type = str(type)                     # 类型
        self.soft_attack = int(soft_attack)       # 软攻
        self.hard_attack = int(hard_attack)       # 硬攻
        self.defense = int(defense)               # 防御
        self.move = int(move)                     # 移动力（当前剩余）
        self.move_type = str(move_type)           # 移动类型
        self.attached_units = list(attached_units or [])   # 挂属单位
        self.breakthrough = int(breakthrough)     # 突破
        self.step = int(step)                     # 数量
        self.branch = str(branch)                 # 兵种
        self.establishment = str(establishment)   # 编制
        self.faction = str(faction)               # 阵营

        # ---- 框架字段 ----
        self.id = None if unit_id is None else int(unit_id)   # 编号
        self.attached_to = None                   # 上级单位的编号
        self._parent = None                       # 上级单位（对象引用）
        self.attrs = {}                           # 自定义扩展数据

        # ---- 派生记录（建好之后自动维护） ----
        self.move_max = self.move                 # 本回合移动力上限
        self.step_max = max(1, self.step)         # 满编数量，用于算战力比例
        for child in self.attached_units:
            if isinstance(child, Units):
                child.attached_to = self.id
                child._parent = self

    # ---------- 建单位 ----------
    @classmethod
    def from_type(cls, type_name, name=None, **overrides):
        """按 TYPE_TEMPLATES 建单位：未知类型照样建出来，缺的字段用默认值。

        type_name 是模板名（'装甲营'、'炮兵营'……）；name 省略时用类型名；
        其余关键字（step、move、breakthrough……）覆盖模板或默认值。
        """
        data = dict(TYPE_TEMPLATES.get(type_name, {}))
        data.update(overrides)
        unit = cls(name=name if name is not None else type_name, type=type_name,
                   **{key: value for key, value in data.items() if key in _FIELDS})
        for key, value in data.items():
            if key not in _FIELDS:
                unit.set_attr(key, value)
        return unit

    def copy(self, keep_id=False):
        """复制一支单位（含挂属单位）；默认不带编号，加入编成时会重新分配。"""
        clone = Units.from_dict(self.to_dict())
        if not keep_id:
            clone.id = None
            for child in clone.all_units():
                child.id = None
        return clone

    # ---------- 数量（step） ----------
    @property
    def is_eliminated(self):
        """数量减到 0 即被歼灭。"""
        return self.step <= 0

    @property
    def step_factor(self):
        """数量对战力影响的系数：满编 1.0，最低保留 STEP_POWER_FLOOR。"""
        if self.step <= 0 or self.step_max <= 0:
            return 0.0
        ratio = clamp(self.step / float(self.step_max), 0.0, 1.0)
        return STEP_POWER_FLOOR + (1.0 - STEP_POWER_FLOOR) * ratio

    def add_step(self, amount=1):
        """补充数量（不超过满编），返回实际补充的数量。"""
        before = self.step
        self.step = min(self.step_max, self.step + int(amount))
        return self.step - before

    def take_loss(self, steps=1):
        """损失数量，减到 0 即被歼灭，返回剩余数量。"""
        self.step = max(0, self.step - int(steps))
        return self.step

    # ---------- 移动 ----------
    @property
    def is_mechanized(self):
        """是否机械化移动（MOVE_TYPES 里的 mechanized 标记）。"""
        return bool(MOVE_TYPES.get(self.move_type, {}).get('mechanized', False))

    def terrain_cost(self, base_cost=1, terrain=None):
        """在某种地形上移动一格的消耗：基础消耗 × 该移动类型的地形系数。"""
        factor = terrain_move_factor(self.move_type, terrain)
        return int(round(int(base_cost) * factor)) or 1

    def can_move(self, cost=1):
        """剩余移动力是否够走这一格。"""
        return self.step > 0 and self.move >= int(cost)

    def spend_move(self, cost=1):
        """扣移动力：够则扣掉返回 True，不够返回 False。"""
        cost = int(cost)
        if not self.can_move(cost):
            return False
        self.move -= cost
        return True

    def reset_turn(self):
        """新回合开始：移动力回满。"""
        self.move = self.move_max
        return self

    # ---------- 突破 ----------
    @property
    def has_breakthrough(self):
        """是否具备突破能力（突破值大于 0）。"""
        return self.breakthrough > 0

    def breakthrough_bonus(self):
        """突破带来的攻击加成系数：1.0 表示没有加成。"""
        return 1.0 + BREAKTHROUGH_ATTACK_BONUS * max(0, self.breakthrough)

    # ---------- 战力 ----------
    def attack_power(self, kind='soft', target=None):
        """攻击力 = 基础攻击 × 数量系数 × 突破加成 × 兵种克制。

        kind='soft' 用软攻打软目标，kind='hard' 用硬攻打硬目标；
        target 传另一支单位时按其兵种乘上 BRANCH_MATCHUPS 里的克制系数。
        """
        base = self.hard_attack if kind == 'hard' else self.soft_attack
        power = base * self.step_factor * self.breakthrough_bonus()
        if target is not None:
            power *= branch_multiplier(self.branch, target.branch)
        return round(power, 2)

    def defense_power(self, attacker=None):
        """防御力 = 基础防御 × 数量系数，可被攻击方兵种克制削弱。"""
        power = self.defense * self.step_factor
        if attacker is not None:
            power /= branch_multiplier(attacker.branch, self.branch)
        return round(power, 2)

    def combat_odds(self, defender, kind='soft'):
        """攻防比 = 攻击力 / 对方防御力（对方防御为 0 时返回 None）。"""
        defense = defender.defense_power(attacker=self)
        if defense <= 0:
            return None
        return round(self.attack_power(kind=kind, target=defender) / defense, 2)

    # ---------- 挂属单位 ----------
    def attach(self, unit):
        """挂上一个下级单位（原本挂在别处会先摘掉；已经挂在同一上级下则无操作）。"""
        if unit is self:
            raise ValueError('单位不能挂属到自己')
        # 沿上级链往上找：unit 是本单位的上级时，挂下去会形成环路
        current = self._parent
        while current is not None:
            if current is unit:
                raise ValueError('不能把上级单位挂到自己的下级去（会形成环路）')
            current = current._parent
        if unit._parent is self:
            return self
        if unit._parent is not None:
            unit._parent.detach(unit)
        unit._parent = self
        unit.attached_to = self.id
        if unit not in self.attached_units:
            self.attached_units.append(unit)
        return self

    def detach(self, target):
        """摘下挂属单位：target 可传 Units、编号或名字，会在所有层级里找；返回是否摘下。"""
        for unit in self.all_units():
            keep = []
            hit = False
            for child in unit.attached_units:
                if isinstance(child, Units) and _same_unit(child, target):
                    child.attached_to = None
                    child._parent = None
                    hit = True
                else:
                    keep.append(child)
            if hit:
                unit.attached_units = keep
                return True
        return False

    def iter_attached(self):
        """只遍历直接挂属的下级单位。"""
        return iter(list(self.attached_units))

    def all_units(self):
        """自身 + 所有层级的挂属单位（深度优先，按对象去重）。"""
        seen = []
        stack = [self]
        while stack:
            current = stack.pop()
            if any(current is item for item in seen):
                continue
            seen.append(current)
            for child in current.attached_units:
                if isinstance(child, Units):
                    stack.append(child)
        return seen

    def find(self, key):
        """在自己和所有挂属单位里按编号或名字找一支单位；找不到返回 None。"""
        for unit in self.all_units():
            if _same_unit(unit, key):
                return unit
        return None

    def attached_step(self):
        """所有挂属单位的数量合计（不含自身）。"""
        return sum(u.step for u in self.all_units() if u is not self)

    def total_step(self):
        """自身 + 挂属单位的数量合计。"""
        return self.step + self.attached_step()

    def total_attack_power(self, kind='soft'):
        """自身 + 挂属单位的攻击力合计（下级单位各自算各自的克制）。"""
        return round(sum(u.attack_power(kind=kind) for u in self.all_units()), 2)

    # ---------- 其它自定义属性 ----------
    def set_attr(self, key, value):
        self.attrs[key] = value
        return self

    def get_attr(self, key, default=None):
        return self.attrs.get(key, default)

    def clear_attr(self, key):
        self.attrs.pop(key, None)

    # ---------- 汇总与序列化 ----------
    def summary(self):
        """一行式摘要，便于调试与列表显示。"""
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'branch': self.branch,
            'establishment': self.establishment,
            'step': self.step,
            'soft_attack': self.soft_attack,
            'hard_attack': self.hard_attack,
            'defense': self.defense,
            'move': self.move,
            'move_type': self.move_type,
            'breakthrough': self.breakthrough,
            'attached': [u.name for u in self.attached_units if isinstance(u, Units)],
            'total_step': self.total_step(),
            'eliminated': self.is_eliminated,
        }

    def to_dict(self, with_attached=True):
        """导出成可保存的字典；with_attached=False 时只导出自身（挂属另存编号）。"""
        data = {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'soft_attack': self.soft_attack,
            'hard_attack': self.hard_attack,
            'defense': self.defense,
            'move': self.move,
            'move_max': self.move_max,
            'move_type': self.move_type,
            'breakthrough': self.breakthrough,
            'step': self.step,
            'step_max': self.step_max,
            'branch': self.branch,
            'establishment': self.establishment,
            'faction': self.faction,
            'attached_to': self.attached_to,
            'attrs': dict(self.attrs),
        }
        if with_attached:
            data['attached_units'] = [u.to_dict() for u in self.attached_units
                                      if isinstance(u, Units)]
        else:
            data['attached_units'] = [u.id for u in self.attached_units
                                      if isinstance(u, Units)]
        return data

    @classmethod
    def from_dict(cls, data, with_attached=True):
        """从 to_dict() 的结果还原；缺字段用默认值补齐。"""
        data = data or {}
        unit = cls(name=data.get('name', ''),
                   type=data.get('type', ''),
                   soft_attack=data.get('soft_attack', 0),
                   hard_attack=data.get('hard_attack', 0),
                   defense=data.get('defense', 0),
                   move=data.get('move', 0),
                   move_type=data.get('move_type', '徒步'),
                   breakthrough=data.get('breakthrough', 0),
                   step=data.get('step', 1),
                   branch=data.get('branch', '步兵'),
                   establishment=data.get('establishment', ''),
                   faction=data.get('faction', ''),
                   unit_id=data.get('id'))
        unit.move_max = int(data.get('move_max', unit.move))
        unit.step_max = max(1, int(data.get('step_max', unit.step)))
        unit.attached_to = data.get('attached_to')
        unit.attrs = dict(data.get('attrs') or {})
        if with_attached:
            for item in data.get('attached_units') or ():
                if isinstance(item, dict):
                    unit.attach(cls.from_dict(item))
        return unit

    def __repr__(self):
        return 'Units(#%s %s [%s/%s], 软攻=%d 硬攻=%d 防御=%d, 移动=%d/%s, 数量=%d, 挂属=%d)' % (
            self.id, self.name, self.type, self.branch,
            self.soft_attack, self.hard_attack, self.defense,
            self.move, self.move_type, self.step, len(self.attached_units),
        )


def make_unit(type_name, **kwargs):
    """按类型模板新建一支单位（相当于 Units.from_type）。"""
    return Units.from_type(type_name, **kwargs)


def _same_unit(unit, key):
    """判断 key（Units / 编号 / 名字）是否指同一支单位。"""
    if isinstance(key, Units):
        return unit is key
    if isinstance(key, int):
        return unit.id == key
    return unit.name == str(key)


class UnitRoster:
    """单位编成：把许多单位收在一起管理，按编号索引，挂属关系原样保留。"""

    def __init__(self, units=None):
        self.units = {}          # 编号 -> Units（含挂属单位，扁平存放）
        self._next_id = 1
        for unit in units or ():
            self.add(unit)

    # ---------- 增删 ----------
    def add(self, unit):
        """登记一支单位（连同它下面的挂属单位），返回该单位。"""
        for item in unit.all_units():
            self._register(item)
        self._sync_links()
        return unit

    def _register(self, unit):
        """分配编号并放进编成；编号可用且没被别的单位占用时沿用。"""
        used = self.units.get(unit.id) if unit.id is not None else None
        if unit.id is None or int(unit.id) < 1 or (used is not None and used is not unit):
            unit.id = self._next_id
        self.units[unit.id] = unit
        self._next_id = max(self._next_id, unit.id + 1)
        for child in unit.attached_units:
            if isinstance(child, Units):
                child._parent = unit

    def _sync_links(self):
        """按上级对象把 attached_to 编号刷新一遍（编号是登记后才定下来的）。"""
        for item in self.units.values():
            item.attached_to = item._parent.id if item._parent is not None else None
        return self

    def remove(self, unit_id):
        """移除一支单位（连同它下面的挂属单位），返回被移除的单位数。"""
        unit = self.units.get(int(unit_id))
        if unit is None:
            return 0
        if unit._parent is not None:
            unit._parent.detach(unit)
        count = 0
        for item in unit.all_units():
            if self.units.pop(item.id, None) is not None:
                count += 1
        self._sync_links()
        return count

    def clear(self):
        """清空编成。"""
        self.units.clear()
        self._next_id = 1

    def attach(self, parent, child):
        """在编成里把 child 挂到 parent 下面（两支单位都会登记），返回 parent。"""
        self.add(parent)
        self.add(child)
        parent.attach(child)
        return self._sync_links()

    # ---------- 查询 ----------
    def get(self, unit_id, default=None):
        """按编号取单位。"""
        return self.units.get(int(unit_id), default)

    def roots(self):
        """没有上级的顶层单位。"""
        return [u for u in self.iter_units() if u._parent is None]

    def by_branch(self, branch):
        """按兵种筛选。"""
        return [u for u in self.iter_units() if u.branch == branch]

    def by_type(self, type_name):
        """按类型筛选。"""
        return [u for u in self.iter_units() if u.type == type_name]

    def by_move_type(self, move_type):
        """按移动类型筛选。"""
        return [u for u in self.iter_units() if u.move_type == move_type]

    def by_establishment(self, establishment):
        """按编制筛选。"""
        return [u for u in self.iter_units() if u.establishment == establishment]

    def alive(self):
        """还没被歼灭的单位（数量大于 0）。"""
        return [u for u in self.iter_units() if not u.is_eliminated]

    def attached_to(self, unit_id):
        """某支单位直接挂属的下级单位。"""
        unit = self.get(unit_id)
        return [] if unit is None else list(unit.attached_units)

    def reset_turn(self):
        """所有单位进入新回合（移动力回满）。"""
        for unit in self.units.values():
            unit.reset_turn()
        return self

    # ---------- 统计 ----------
    def totals(self):
        """总体统计：单位数、数量合计、三个战力合计、按兵种 / 类型分布。

        按登记单位直接相加（上级与下级都算各算一份），"顶层"单列。
        """
        branches = {}
        types = {}
        for unit in self.iter_units():
            branches[unit.branch] = branches.get(unit.branch, 0) + 1
            types[unit.type] = types.get(unit.type, 0) + 1
        return {
            'units': len(self.units),
            'roots': len(self.roots()),
            'eliminated': len(self.units) - len(self.alive()),
            'step': sum(u.step for u in self.iter_units()),
            'soft_attack': sum(u.soft_attack for u in self.iter_units()),
            'hard_attack': sum(u.hard_attack for u in self.iter_units()),
            'defense': sum(u.defense for u in self.iter_units()),
            'by_branch': branches,
            'by_type': types,
        }

    def summary(self):
        """编成摘要：统计 + 顶层单位名字。"""
        data = self.totals()
        data['top_units'] = [u.name for u in self.roots()]
        return data

    # ---------- 序列化 ----------
    def to_dict(self):
        """导出成扁平结构：每个单位一条记录，用 attached_to 指向上级编号。

        扁平存放是为了避免嵌套递归造成的重复与循环。
        """
        items = []
        for unit in self.iter_units():
            item = unit.to_dict(with_attached=False)
            item['attached_to'] = unit._parent.id if unit._parent is not None else None
            items.append(item)
        return {'v': 1, 'units': items}

    @classmethod
    def from_dict(cls, data):
        """从 to_dict() 的扁平结构还原，并按 attached_to 重新接好挂属关系。"""
        items = list((data or {}).get('units', ()))
        roster = cls()
        built = []
        for item in items:
            unit = Units.from_dict(item, with_attached=False)
            built.append(unit)
        by_id = {}
        for item, unit in zip(items, built):
            raw_id = item.get('id')
            unit.id = None if raw_id is None else int(raw_id)
            if unit.id is not None and unit.id not in roster.units:
                roster.units[unit.id] = unit
                roster._next_id = max(roster._next_id, unit.id + 1)
            else:
                roster._register(unit)
            by_id[unit.id] = unit
        for item, unit in zip(items, built):
            parent_id = item.get('attached_to')
            parent = by_id.get(parent_id) if parent_id is not None else None
            if parent is not None:
                parent.attach(unit)
        # 还原挂属顺序：按存档里 attached_units 的先后重排
        for item, unit in zip(items, built):
            order = [cid for cid in (item.get('attached_units') or ()) if cid in roster.units]
            if order:
                rank = {cid: pos for pos, cid in enumerate(order)}
                unit.attached_units.sort(key=lambda child: rank.get(child.id, len(rank)))
        return roster._sync_links()

    def save_json(self, path):
        """保存成 JSON 文件（UTF-8，中文不转义）。"""
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)
        return path

    @classmethod
    def load_json(cls, path):
        """读取 save_json() 写出的 JSON 文件。"""
        with open(path, 'r', encoding='utf-8') as handle:
            return cls.from_dict(json.load(handle))

    # ---------- 容器协议 ----------
    def iter_units(self):
        """按编号从小到大遍历所有单位。"""
        for unit_id in sorted(self.units):
            yield self.units[unit_id]

    def __len__(self):
        return len(self.units)

    def __iter__(self):
        return self.iter_units()

    def __contains__(self, unit_id):
        return int(unit_id) in self.units

    def __getitem__(self, unit_id):
        return self.units[int(unit_id)]

    def __repr__(self):
        totals = self.totals()
        return 'UnitRoster(%d 支单位, %d 个顶层, 数量合计 %d)' % (
            totals['units'], totals['roots'], totals['step'],
        )
