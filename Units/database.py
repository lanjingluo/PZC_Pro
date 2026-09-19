"""database.py - 单位类型数据库（数据全部放在 .data 文件里）

本模块**不含任何具体单位的数据**，只提供三样东西：
1. 记录模板 RECORD_TEMPLATE（字段名与 Units 类一致，值来自 Units.TEMPLATE），
   新建一个类型时用它把字段补全；
2. 内存数据库 UNIT_DATABASE（类型名 -> 一条记录）与增删改查接口；
3. 数据文件读写：默认文件 Units/database/units.data，也可以打开任意 .data。

单位类型有哪些、每种什么数值，全部记录在数据文件里，改数据不用改代码。

注意：类型数据衡量的是"武器能力"——软攻、硬攻、防御、移动力、移动类型、
兵种、编制、突破；**不含兵力数量**。数量属于具体单位，记录在 .oob 的编制节点里
（见 oob.py），需要建单位时用 create(类型名, step=N) 把数量传给 Units。

常用做法：
    import database

    database.load_file()                          # 读 Units/database/units.data
    database.names()                              # 文件里有哪些类型
    unit = database.create('装甲营', faction='德军')   # 用文件里的数据建一支 Units
    database.set_record('火箭炮营', {'branch': '炮兵', ...})   # 新建或修改类型
    database.save_file()                          # 写回 .data 文件

阵营（faction）不属于类型数据：类型是中立的，具体归属哪个阵营由剧本/编成决定，
建单位时用 create(..., faction='德军') 指定即可。
"""
import json
import os

from Units import (BRANCHES, ESTABLISHMENTS, MOVE_TYPES, TEMPLATE, Units,
                   _FIELDS as UNITS_FIELDS)

# 一条记录里会出现的字段（与 Units 类的字段同名，挂属单位不进数据库）
RECORD_FIELDS = ('type', 'soft_attack', 'hard_attack', 'defense', 'move',
                 'move_type', 'branch', 'establishment', 'breakthrough')

# 数值字段（读入 / 写入时转成整数）与文本字段
NUMERIC_FIELDS = ('soft_attack', 'hard_attack', 'defense', 'move', 'breakthrough')
TEXT_FIELDS = ('type', 'branch', 'move_type', 'establishment')

# 数据文件：Units/database/units.data（纯 JSON 文本，可直接编辑）
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database')
DATA_FILE = os.path.join(DATA_DIR, 'units.data')

# 当前正在使用的数据文件（None 表示用默认的 DATA_FILE）
_CURRENT_FILE = None

# 记录模板：新建类型时用它补全缺的字段；只有默认值，没有具体单位数据
RECORD_TEMPLATE = dict(TEMPLATE)
RECORD_TEMPLATE['type'] = ''

# 内存数据库：类型名 -> 记录（读 .data 文件得到，或由 set_record 写进来）
UNIT_DATABASE = {}
# 类型名列表，随数据库内容刷新
TYPE_NAMES = ()


def _normalize(name, record):
    """把一条记录补全并归一：缺的字段用模板默认值，数值转整数，字段顺序固定。"""
    data = dict(RECORD_TEMPLATE)
    data.update(record or {})
    data['type'] = str(data.get('type') or name or '')
    for key in NUMERIC_FIELDS:
        if data.get(key) is not None:
            try:
                data[key] = int(data[key])
            except (TypeError, ValueError):
                pass          # 非法值留着，由 check() 报出来
    for key in TEXT_FIELDS:
        if data.get(key) is not None:
            data[key] = str(data[key])
    # 先按固定顺序排，再带上用户自己加的额外字段
    ordered = {key: data[key] for key in RECORD_FIELDS if key in data}
    for key in data:
        if key not in ordered:
            ordered[key] = data[key]
    return ordered


def _refresh_names():
    """数据库内容变化后刷新 TYPE_NAMES。"""
    global TYPE_NAMES
    TYPE_NAMES = tuple(UNIT_DATABASE)
    return TYPE_NAMES


# ---------- 查 ----------
def get(type_name):
    """取某个类型的原始数据（副本，改它不会影响数据库）；没有返回 None。"""
    record = UNIT_DATABASE.get(type_name)
    return None if record is None else dict(record)


def has(type_name):
    """数据库里是否有这个类型。"""
    return type_name in UNIT_DATABASE


def names():
    """所有类型名。"""
    return list(TYPE_NAMES)


def template():
    """取一份记录模板（新建类型时的空白模板，字段已补全）。"""
    return _normalize('', {})


def capability(type_name):
    """取某个类型的"武器能力"摘要（不含数量）；数据库里没有返回 None。

    .oob 里的具体单位用这个了解自己引用的类型有多大本事。
    """
    record = get(type_name)
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


# ---------- 增 / 改 / 删 ----------
def set_record(type_name, record=None, **fields):
    """写入或更新一条类型记录（已存在就覆盖），返回归一化后的记录。

    没给的字段会用模板默认值补齐，所以 .data 里每条记录都是完整的。
    """
    type_name = str(type_name or '').strip()
    if not type_name:
        raise ValueError('类型名不能为空')
    data = dict(record or {})
    data.update(fields)
    data['type'] = type_name
    UNIT_DATABASE[type_name] = _normalize(type_name, data)
    _refresh_names()
    return dict(UNIT_DATABASE[type_name])


def rename_record(old_name, new_name, **fields):
    """把一条记录改名（相当于删掉旧的、建一个新的），返回新记录。"""
    old_name = str(old_name or '').strip()
    new_name = str(new_name or '').strip()
    if old_name not in UNIT_DATABASE:
        raise KeyError('数据库里没有这个单位类型：%s' % old_name)
    if not new_name:
        raise ValueError('类型名不能为空')
    data = dict(UNIT_DATABASE[old_name])
    data.update(fields)
    data['type'] = new_name
    if new_name != old_name:
        del UNIT_DATABASE[old_name]
    UNIT_DATABASE[new_name] = _normalize(new_name, data)
    _refresh_names()
    return dict(UNIT_DATABASE[new_name])


def delete_record(type_name):
    """删除一个类型，返回是否真的删掉了。"""
    removed = UNIT_DATABASE.pop(str(type_name), None) is not None
    if removed:
        _refresh_names()
    return removed


def clear():
    """清空内存数据库（不动文件）。"""
    UNIT_DATABASE.clear()
    _refresh_names()
    return 0


# ---------- 建单位 ----------
def create(type_name, name=None, **overrides):
    """按 .data 里的类型数据建一支 Units 实例。

    name 省略时用类型名；其余关键字覆盖记录里的值（如 faction='德军'、step=2）。
    记录之外的自定义字段会放进 Units.attrs，不会丢。数据库里没有这个类型会报 KeyError。
    """
    if type_name not in UNIT_DATABASE:
        raise KeyError('数据库里没有这个单位类型：%s' % type_name)
    data = dict(UNIT_DATABASE[type_name])
    data.update(overrides)
    data['name'] = name if name is not None else data.get('name') or type_name
    extra = {key: data.pop(key) for key in list(data) if key not in UNITS_FIELDS}
    unit = Units(**data)
    for key, value in extra.items():
        unit.set_attr(key, value)
    return unit


def create_all():
    """每种类型各建一支样板单位，返回 {类型名: Units}。"""
    return {type_name: create(type_name) for type_name in names()}


# ---------- 分类查询 ----------
def by_branch(branch):
    """某个兵种下的所有类型名。"""
    return [name for name in TYPE_NAMES if UNIT_DATABASE[name].get('branch') == branch]


def by_move_type(move_type):
    """某种移动类型的所有类型名。"""
    return [name for name in TYPE_NAMES if UNIT_DATABASE[name].get('move_type') == move_type]


def by_establishment(establishment):
    """某种编制的所有类型名。"""
    return [name for name in TYPE_NAMES if UNIT_DATABASE[name].get('establishment') == establishment]


def search(keyword):
    """类型名里包含关键字的类型。"""
    text = str(keyword)
    return [name for name in TYPE_NAMES if text in name]


# ---------- 检查与统计 ----------
def check():
    """数据自检：返回问题列表（空列表表示没问题）。

    检查兵种、移动类型、编制是否在 Units 的常量表里，数值字段是否为数字，
    以及记录里有没有多余字段。
    """
    problems = []
    for name, record in UNIT_DATABASE.items():
        for key in record:
            if key not in RECORD_FIELDS and key not in ('name', 'faction'):
                problems.append('%s：记录里有未知字段 %r' % (name, key))
        if record.get('branch') not in BRANCHES:
            problems.append('%s：未知兵种 %r' % (name, record.get('branch')))
        if record.get('move_type') not in MOVE_TYPES:
            problems.append('%s：未知移动类型 %r' % (name, record.get('move_type')))
        establishment = record.get('establishment')
        if establishment and establishment not in ESTABLISHMENTS:
            problems.append('%s：未知编制 %r' % (name, establishment))
        for key in NUMERIC_FIELDS:
            value = record.get(key, 0)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append('%s：%s 不是数字（%r）' % (name, key, value))
    return problems


def summary():
    """数据库概况：类型总数，以及按兵种、移动类型、编制的分布。"""
    def count(key):
        out = {}
        for record in UNIT_DATABASE.values():
            value = record.get(key)
            out[value] = out.get(value, 0) + 1
        return out
    return {
        'types': len(UNIT_DATABASE),
        'by_branch': count('branch'),
        'by_move_type': count('move_type'),
        'by_establishment': count('establishment'),
    }


# ---------- 存档互转 ----------
def to_dict():
    """导出整个数据库（可保存成 JSON 后手工编辑）。"""
    return {'v': 1, 'types': {name: dict(record) for name, record in UNIT_DATABASE.items()}}


def from_dict(data):
    """用一份数据替换内存数据库内容，返回装进去的类型数量。"""
    types = (data or {}).get('types')
    if not isinstance(types, dict):
        raise ValueError('不是有效的数据（缺少 types 段）')
    UNIT_DATABASE.clear()
    for name, record in types.items():
        UNIT_DATABASE[name] = _normalize(name, record)
    _refresh_names()
    return len(UNIT_DATABASE)


def save_json(path):
    """把数据库另存成一个 JSON 文件。"""
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(to_dict(), handle, ensure_ascii=False, indent=2)
    return path


def load_json(path):
    """从 JSON 文件读回数据库。"""
    with open(path, 'r', encoding='utf-8') as handle:
        return from_dict(json.load(handle))


# ---------- .data 数据文件（默认 Units/database/units.data） ----------
def current_file():
    """当前使用的 .data 文件路径（默认 Units/database/units.data）。"""
    return _CURRENT_FILE or DATA_FILE


def set_file(path):
    """把"当前数据文件"切成 path（只改路径，不读数据）；传 None 恢复默认文件。"""
    global _CURRENT_FILE
    _CURRENT_FILE = None if path is None else os.path.abspath(str(path))
    return current_file()


def save_file(path=None):
    """把内存数据库写进 .data 文件；不传路径就写当前数据文件，返回文件路径。"""
    path = path or current_file()
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(to_dict(), handle, ensure_ascii=False, indent=2)
    return path


def load_file(path=None):
    """从 .data 文件读入数据库，返回类型数量。

    传了路径就把它设为当前数据文件（文件不存在会报 FileNotFoundError）；
    不传路径时读当前数据文件，首次运行文件还不存在就按当前内存数据建一份。
    文件内容不合法会抛异常，此时内存数据保持原样。
    """
    global _CURRENT_FILE
    explicit = path is not None
    target = os.path.abspath(str(path)) if explicit else current_file()
    if not os.path.isfile(target):
        if explicit:
            raise FileNotFoundError('数据文件不存在：%s' % target)
        _CURRENT_FILE = target
        save_file(target)
        return len(UNIT_DATABASE)
    with open(target, 'r', encoding='utf-8') as handle:
        data = json.load(handle)
    count = from_dict(data)
    _CURRENT_FILE = target      # 解析成功后才切换当前文件
    return count


def reload_file(path=None):
    """丢弃内存里的改动，重新从 .data 文件读一遍。"""
    return load_file(path)
