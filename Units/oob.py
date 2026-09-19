"""oob.py - 军队编制（战斗序列）数据：军 → 师 → 团 → 营 的架构

一个 .oob 文件描述一支军队的层级架构，每层是一个节点：
- name   番号（如 "第1装甲营"）
- level  编制级别（LEVELS：集团军/军/师/旅/团/营/连/排/班）
- type   对应的单位类型名（调用 units.data 里的类型，留空表示纯指挥/架子单位）
- step   数量（兵力步数，0 表示只是个指挥机构）——数量属于具体单位，不在类型数据里
- note   备注
- children 下级节点

数据文件默认放在 Units/oob/*.oob，内容是 JSON 文本，可以直接编辑：
    {"v": 1, "army": "第1装甲军", "faction": "德军", "root": {...}}

常用做法：
    import oob

    oob.load_file()                     # 读 Units/oob/army.oob
    oob.root()                          # 树根节点
    oob.root().total_step()             # 整支军队的数量合计
    node = oob.root().find('第1装甲营')
    node.capability()                   # 这个节点引用的单位类型有什么武器能力
    node.unit()                         # 按类型数据 + 节点数量建一支 Units 实例
    oob.check()                         # 检查各节点的单位类型在 units.data 里是否存在
    oob.save_file()                     # 写回 .oob 文件
"""
import json
import os

# 编制级别，从高到低
LEVELS = ('集团军', '军', '师', '旅', '团', '营', '连', '排', '班')

# 数据目录与默认文件
OOB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'oob')
OOB_FILE = os.path.join(OOB_DIR, 'army.oob')

_CURRENT_FILE = None


class OobNode:
    """编制树上的一个节点（一支具体部队/单位），可以有任意多级下级。"""

    def __init__(self, name='', level='营', type_name='', step=0, note=''):
        self.name = str(name)
        self.level = str(level)
        self.type = str(type_name)      # units.data 里的类型名，可为空
        self.step = int(step)
        self.note = str(note)
        self.children = []
        self.parent = None              # 上级节点（对象引用）

    # ---------- 结构 ----------
    @property
    def level_index(self):
        """编制级别在 LEVELS 里的序号（越小级别越高）；未知级别返回最大值。"""
        try:
            return LEVELS.index(self.level)
        except ValueError:
            return len(LEVELS)

    def deeper_level(self):
        """下一级编制名（用于新增下级时的默认值）。"""
        index = self.level_index
        if index >= len(LEVELS) - 1:
            return LEVELS[-1]
        return LEVELS[index + 1]

    def add_child(self, node, index=None):
        """挂一个下级节点（会先从原来的上级摘掉），返回这个节点。"""
        if node is self:
            raise ValueError('节点不能挂到自己下面')
        current = self
        while current is not None:
            if current is node:
                raise ValueError('不能把上级节点挂到自己的下级（会形成环路）')
            current = current.parent
        if node.parent is not None and node.parent is not self:
            node.parent.remove_child(node)
        node.parent = self
        if index is None or not 0 <= index <= len(self.children):
            self.children.append(node)
        else:
            self.children.insert(index, node)
        return node

    def remove_child(self, node):
        """摘掉一个直接下级，返回是否摘掉了。"""
        for index, child in enumerate(self.children):
            if child is node:
                child.parent = None
                del self.children[index]
                return True
        return False

    def detach(self):
        """把自己从上级摘下来。"""
        if self.parent is not None:
            self.parent.remove_child(self)
        return self

    def delete_child(self, node):
        """删除一个下级及其整棵子树，返回删掉的节点数。"""
        if not self.remove_child(node):
            return 0
        return len(node.walk())

    def walk(self):
        """自身 + 所有下级（深度优先）。"""
        result = [self]
        for child in self.children:
            result.extend(child.walk())
        return result

    def depth(self):
        """以自己为根的最大层数（自己算 1 层）。"""
        if not self.children:
            return 1
        return 1 + max(child.depth() for child in self.children)

    def find(self, key):
        """在自己与所有下级里按节点、名字或类型找；找不到返回 None。"""
        for node in self.walk():
            if node is key:
                return node
            if isinstance(key, str) and (node.name == key or node.type == key):
                return node
        return None

    def path(self):
        """从根到自己的名称路径，如 ['第1装甲军', '第1装甲师', '第1装甲营']。"""
        names = [self.name]
        current = self.parent
        while current is not None:
            names.append(current.name)
            current = current.parent
        names.reverse()
        return names

    # ---------- 统计 ----------
    def total_step(self):
        """自身 + 所有下级的数量合计。"""
        return sum(node.step for node in self.walk())

    def count(self):
        """自身 + 所有下级的节点数量。"""
        return len(self.walk())

    def level_counts(self):
        """各编制级别下的节点数。"""
        out = {}
        for node in self.walk():
            out[node.level] = out.get(node.level, 0) + 1
        return out

    def used_types(self):
        """这棵子树里用到的单位类型名（去重排序）。"""
        return sorted({node.type for node in self.walk() if node.type})

    # ---------- 调用单位类型数据 ----------
    def type_record(self):
        """取自己引用的单位类型数据（来自 units.data）；没引用或查不到返回 None。"""
        if not self.type:
            return None
        try:
            import database
        except Exception:
            return None
        if not database.UNIT_DATABASE:
            try:
                database.load_file()
            except Exception:
                pass
        return database.get(self.type)

    def capability(self):
        """自己引用的单位类型有什么武器能力（软攻/硬攻/防御/移动力/突破……）。

        这是"具体单位调用类型数据"的入口：查不到返回 None。
        """
        record = self.type_record()
        if record is None:
            return None
        return {
            'type': record.get('type', ''),
            'branch': record.get('branch', ''),
            'soft_attack': record.get('soft_attack', 0),
            'hard_attack': record.get('hard_attack', 0),
            'defense': record.get('defense', 0),
            'move': record.get('move', 0),
            'move_type': record.get('move_type', ''),
            'breakthrough': record.get('breakthrough', 0),
        }

    def unit(self, name=None, faction=None, step=None):
        """按引用的单位类型建一支 Units 实例：能力来自 .data，数量取本节点。

        没有引用类型时返回 None；step 省略时用节点自己的数量。
        """
        if not self.type:
            return None
        try:
            import database
        except Exception:
            return None
        return database.create(self.type,
                               name=name or self.name,
                               step=self.step if step is None else step,
                               faction=faction or FACTION)

    # ---------- 序列化 ----------
    def to_dict(self):
        """导出成可保存的字典（下级递归嵌套）。"""
        return {
            'name': self.name,
            'level': self.level,
            'type': self.type,
            'step': self.step,
            'note': self.note,
            'children': [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, data):
        """从 to_dict() 的结果还原一棵子树（缺字段用默认值）。"""
        data = data or {}
        node = cls(name=data.get('name', ''),
                   level=data.get('level', '营'),
                   type_name=data.get('type', ''),
                   step=data.get('step', 0),
                   note=data.get('note', ''))
        for item in data.get('children') or ():
            node.add_child(cls.from_dict(item))
        return node

    def __repr__(self):
        return 'OobNode(%s [%s]%s, 数量=%d, 下级=%d)' % (
            self.name, self.level,
            ' 类型=%s' % self.type if self.type else '',
            self.step, len(self.children),
        )


# 当前内存里的编制树（读 .oob 得到，或在界面里改）
ROOT = None
ARMY = ''
FACTION = ''


def set_root(node, army=None, faction=None):
    """设置当前编制树（以及军队名 / 阵营）。"""
    global ROOT, ARMY, FACTION
    ROOT = node
    if army is not None:
        ARMY = str(army)
    elif node is not None and not ARMY:
        ARMY = node.name
    if faction is not None:
        FACTION = str(faction)
    return ROOT


def root():
    """当前编制树的根节点（没有则 None）。"""
    return ROOT


def new_tree(name='新建军队', level='军', faction=''):
    """新建一棵只有根节点的编制树，返回根节点。"""
    return set_root(OobNode(name=name, level=level), army=name, faction=faction)


def current_file():
    """当前 .oob 文件路径（默认 Units/oob/army.oob）。"""
    return _CURRENT_FILE or OOB_FILE


def set_file(path):
    """切换当前 .oob 文件（只改路径，不读数据）。"""
    global _CURRENT_FILE
    _CURRENT_FILE = None if path is None else os.path.abspath(str(path))
    return current_file()


def to_dict():
    """把当前编制树导出成可保存的字典。"""
    return {
        'v': 1,
        'army': ARMY,
        'faction': FACTION,
        'root': ROOT.to_dict() if ROOT is not None else None,
    }


def from_dict(data):
    """用一份数据替换当前编制树，返回节点总数。"""
    if not isinstance(data, dict) or not isinstance(data.get('root'), dict):
        raise ValueError('不是有效的编制文件（缺少 root）')
    node = OobNode.from_dict(data['root'])
    set_root(node, army=data.get('army') or node.name, faction=data.get('faction') or '')
    return node.count()


def save_file(path=None):
    """把当前编制树写进 .oob 文件；不传路径就写当前文件。"""
    path = path or current_file()
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(to_dict(), handle, ensure_ascii=False, indent=2)
    return path


def load_file(path=None):
    """从 .oob 文件读入编制树，返回节点总数。

    传了路径就把它设为当前文件（文件不存在会报 FileNotFoundError）；
    不传路径时读当前文件，文件还不存在就新建一棵空树并写出文件。
    """
    global _CURRENT_FILE
    explicit = path is not None
    target = os.path.abspath(str(path)) if explicit else current_file()
    if not os.path.isfile(target):
        if explicit:
            raise FileNotFoundError('编制文件不存在：%s' % target)
        _CURRENT_FILE = target
        if ROOT is None:
            new_tree()
        save_file(target)
        return ROOT.count()
    with open(target, 'r', encoding='utf-8') as handle:
        data = json.load(handle)
    count = from_dict(data)
    _CURRENT_FILE = target
    return count


def reload_file(path=None):
    """丢弃内存里的改动，重新从文件读一遍。"""
    return load_file(path)


def check(types=None):
    """检查编制里用到的单位类型是否存在，返回问题列表（空表示没问题）。

    types 省略时自动从 database 取当前数据文件里的类型名。
    """
    if types is None:
        try:
            import database
            # 单独用 oob 模块时内存里可能还没有单位数据，先按文件载入一次
            if not database.UNIT_DATABASE and os.path.isfile(database.current_file()):
                database.load_file()
            types = set(database.names())
        except Exception:
            types = None
    if ROOT is None:
        return ['还没有编制树']
    problems = []
    if types is not None:
        for node in ROOT.walk():
            if node.type and node.type not in types:
                problems.append('%s：单位类型 %r 不在单位数据里' % (node.name, node.type))
    for node in ROOT.walk():
        if node.level not in LEVELS:
            problems.append('%s：未知编制级别 %r' % (node.name, node.level))
    return problems


def summary():
    """编制概况：军队名、节点数、层数、数量合计、各编制级别分布。"""
    if ROOT is None:
        return {'army': '', 'nodes': 0, 'depth': 0, 'step': 0, 'levels': {}}
    return {
        'army': ARMY,
        'faction': FACTION,
        'nodes': ROOT.count(),
        'depth': ROOT.depth(),
        'step': ROOT.total_step(),
        'levels': ROOT.level_counts(),
        'types': ROOT.used_types(),
    }
