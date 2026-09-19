"""units_editor.py - 单位编辑器（Python + WinForms）

运行方式：双击同目录的 run.bat，或在命令行运行 python units_editor.py

界面内容：
- 启动后先弹「选择要编辑的文件类型」：单位数据（*.data）或军队编制（*.oob），
  选完再弹打开文件对话框，选中哪个文件就编辑哪个；
- 单位数据模式（.data，衡量武器能力）：左侧表格列出每种单位类型（兵种、编制、
  移动类型、软攻、硬攻、防御、移动力、突破），右侧详情把这些数值画成数值条；
  按钮「新建 / 修改单位类型...」可新建或修改类型，保存写回该 .data 文件。
  类型数据里没有"数量"——数量属于具体单位；
- 军队编制模式（.oob，具体单位）：左侧是军 → 师 → 旅 → 团 → 营 → 连 的编制树，
  右侧显示选中节点的级别、引用的单位类型、下级数、合计数量、编制路径、本级数量条，
  以及**该单位类型从 .data 里调出来的能力数值条**；
  按钮「新增下级...」「修改节点...」「删除节点」直接改这棵树，保存写回该 .oob 文件；
  新增/修改节点时，选完"单位类型"会立刻显示这个类型的能力，数量填的是这支具体部队的数量；
- 两个模式都用「打开文件...」按钮切换（会重新问文件类型），双击表格行/树节点可直接编辑；
- 底部一行状态栏，显示当前文件路径与类型数量或节点数量；

.data 与 .oob 都是 JSON 文本，字段分别跟 database.py / oob.py 里的一致，
可以直接用文本编辑器改；改完在编辑器里重新打开即可生效。
"""
import os
import sys

# 保证从任何目录启动都能 import 到同目录的 Units.py / database.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import clr
except ImportError:
    import ctypes

    ctypes.windll.user32.MessageBoxW(
        0,
        '缺少依赖 pythonnet，程序无法启动。\n\n请在命令行执行：\n    python -m pip install pythonnet',
        '单位编辑器 - 缺少依赖',
        0x10,
    )
    raise SystemExit(1)

clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from System import Decimal
from System.Drawing import Color, ContentAlignment, Point, Size
from System.Threading import ApartmentState, Thread, ThreadStart
from System.Windows.Forms import (
    Application,
    BorderStyle,
    Button,
    ColumnHeaderStyle,
    ComboBox,
    ComboBoxStyle,
    DialogResult,
    DockStyle,
    FlatStyle,
    Form,
    FormBorderStyle,
    FormStartPosition,
    Label,
    ListView,
    ListViewItem,
    MessageBox,
    MessageBoxButtons,
    MessageBoxIcon,
    NumericUpDown,
    OpenFileDialog,
    Padding,
    Panel,
    TextBox,
    TreeNode,
    TreeView,
    View,
)

import database
import oob
from Units import BRANCHES, ESTABLISHMENTS, MOVE_TYPES

WINDOW_TITLE = '单位编辑器'
WINDOW_SIZE = Size(1024, 640)
MINIMUM_SIZE = Size(640, 400)

DIALOG_TITLE = '单位类型'
OOB_TITLE = '军队编制'
DATA_FILE_FILTER = '单位数据文件 (*.data)|*.data|所有文件 (*.*)|*.*'
OOB_FILE_FILTER = '军队编制文件 (*.oob)|*.oob|所有文件 (*.*)|*.*'
NO_TYPE = '（无）'
LABEL_X = 16
FIELD_X = 116
FIELD_W = 300
ROW_H = 34

# 对话框里的数值字段：(标签, 字段名, 上限)，字段名与 Units / database 一致
NUMERIC_ROWS = (
    ('软攻', 'soft_attack', 100),
    ('硬攻', 'hard_attack', 100),
    ('防御', 'defense', 100),
    ('移动力', 'move', 20),
    ('突破', 'breakthrough', 10),
)

# 主窗口表格的列：(标题, 记录字段, 列宽)
TABLE_COLUMNS = (
    ('类型名', 'type', 150),
    ('兵种', 'branch', 60),
    ('编制', 'establishment', 55),
    ('移动类型', 'move_type', 70),
    ('软攻', 'soft_attack', 50),
    ('硬攻', 'hard_attack', 50),
    ('防御', 'defense', 50),
    ('移动力', 'move', 55),
    ('突破', 'breakthrough', 50),
)

# 右侧详情里的数值条：(字段, 标题, 满值, 颜色)
DETAIL_BARS = (
    ('soft_attack', '软攻', 100, Color.FromArgb(205, 85, 60)),
    ('hard_attack', '硬攻', 100, Color.FromArgb(60, 110, 205)),
    ('defense', '防御', 100, Color.FromArgb(70, 165, 95)),
    ('move', '移动力', 20, Color.FromArgb(185, 145, 55)),
    ('breakthrough', '突破', 10, Color.FromArgb(150, 85, 185)),
)
BAR_TRACK_WIDTH = 120

# 编制节点引用的单位类型能力（去掉"数量"，数量是节点自己的）
CAPABILITY_BARS = tuple(
    (key, text, top, color) for key, text, top, color in DETAIL_BARS
)


def add_bar_row(panel, text, y, color, track_width=BAR_TRACK_WIDTH):
    """在面板上加一行"名称 + 数值条 + 数值"，返回 (数值标签, 色条)。"""
    label = Label()
    label.Text = text
    label.AutoSize = False
    label.Location = Point(12, y)
    label.Size = Size(58, 20)
    panel.Controls.Add(label)

    track = Panel()
    track.Location = Point(74, y + 3)
    track.Size = Size(track_width, 14)
    track.BackColor = Color.FromArgb(228, 228, 232)
    bar = Panel()
    bar.Location = Point(0, 0)
    bar.Size = Size(0, 14)
    bar.BackColor = color
    track.Controls.Add(bar)
    panel.Controls.Add(track)

    value = Label()
    value.Text = '-'
    value.AutoSize = False
    value.TextAlign = ContentAlignment.MiddleRight
    value.Location = Point(74 + track_width + 6, y)
    value.Size = Size(80, 20)
    panel.Controls.Add(value)
    return value, bar


def set_bar(bar, value, top):
    """按 value/top 的比例设置色条宽度。"""
    ratio = 0.0 if top <= 0 else max(0.0, min(1.0, float(value) / float(top)))
    bar.Width = int(round(BAR_TRACK_WIDTH * ratio))
    return bar.Width


def number_value(box):
    """读取 NumericUpDown 的整数（System.Decimal 在 pythonnet 里不能直接 int()）。"""
    return int(str(box.Value))


class UnitTypeDialog:
    """新建 / 修改一种单位类型的对话框；保存时写入 .data 数据文件。"""

    def __init__(self, owner=None, type_name=None):
        self.owner = owner
        self.saved_type = None        # 保存成功后的类型名
        self.created = False          # 是新建还是修改
        self.numbers = {}             # 字段名 -> NumericUpDown
        self.limits = {key: top for _, key, top in NUMERIC_ROWS}

        self.form = Form()
        form = self.form
        form.Text = DIALOG_TITLE
        form.FormBorderStyle = FormBorderStyle.FixedDialog
        form.StartPosition = FormStartPosition.CenterParent
        form.MaximizeBox = False
        form.MinimizeBox = False
        form.ShowInTaskbar = False
        form.ClientSize = Size(440, 400 + ROW_H)

        hint = Label()
        hint.Text = '选择已有类型即可修改；输入新的名字就是新建。'
        hint.Location = Point(LABEL_X, 12)
        hint.Size = Size(400, 20)
        form.Controls.Add(hint)

        y = 40
        self.type_combo = self._add_combo(form, '类型名', y, editable=True)
        for name in database.names():
            self.type_combo.Items.Add(name)
        self.type_combo.SelectedIndexChanged += self.on_type_selected
        self.type_combo.TextChanged += self.on_type_selected

        y += ROW_H
        self.branch_combo = self._add_combo(form, '兵种', y)
        for name in BRANCHES:
            self.branch_combo.Items.Add(name)

        y += ROW_H
        self.est_combo = self._add_combo(form, '编制', y)
        for name in ESTABLISHMENTS:
            self.est_combo.Items.Add(name)

        y += ROW_H
        self.move_combo = self._add_combo(form, '移动类型', y)
        for name in MOVE_TYPES:
            self.move_combo.Items.Add(name)

        for label, key, top in NUMERIC_ROWS:
            y += ROW_H
            self._add_label(form, label, y)
            box = NumericUpDown()
            box.Location = Point(FIELD_X, y)
            box.Size = Size(90, 24)
            box.Minimum = Decimal(0)
            box.Maximum = Decimal(top)
            form.Controls.Add(box)
            self.numbers[key] = box

        save = Button()
        save.Text = '保存'
        save.Size = Size(90, 28)
        save.Location = Point(FIELD_X, y + ROW_H + 10)
        save.Click += self.save
        form.Controls.Add(save)

        cancel = Button()
        cancel.Text = '取消'
        cancel.Size = Size(90, 28)
        cancel.Location = Point(FIELD_X + 100, y + ROW_H + 10)
        cancel.DialogResult = DialogResult.Cancel
        form.Controls.Add(cancel)
        form.CancelButton = cancel
        form.AcceptButton = save

        if type_name:
            self.type_combo.Text = str(type_name)
        self.load_type(type_name or '')

    # ---------- 界面小工具 ----------
    def _add_label(self, form, text, y):
        label = Label()
        label.Text = text
        label.Location = Point(LABEL_X, y + 4)
        label.Size = Size(95, 20)
        form.Controls.Add(label)
        return label

    def _add_combo(self, form, text, y, editable=False):
        self._add_label(form, text, y)
        combo = ComboBox()
        combo.Location = Point(FIELD_X, y)
        combo.Size = Size(FIELD_W, 24)
        combo.DropDownStyle = ComboBoxStyle.DropDown if editable else ComboBoxStyle.DropDownList
        form.Controls.Add(combo)
        return combo

    # ---------- 读写 ----------
    def on_type_selected(self, sender, args):
        """类型名变化时，把该类型的数据填进各控件。"""
        self.load_type(str(self.type_combo.Text or '').strip())

    def load_type(self, type_name):
        """把某个类型的数据填进控件；数据库里没有就用模板默认值。"""
        record = (database.get(type_name) if type_name else None) or database.template()
        self._select(self.branch_combo, record.get('branch', BRANCHES[0]))
        self._select(self.est_combo, record.get('establishment', ESTABLISHMENTS[0]))
        self._select(self.move_combo, record.get('move_type', '徒步'))
        for key, box in self.numbers.items():
            value = int(record.get(key, 0) or 0)
            value = max(0, min(self.limits[key], value))
            box.Value = Decimal(value)
        return record

    def _select(self, combo, value):
        """在 ComboBox 里选中某个值；列表里没有就补进去，避免丢数据。"""
        value = '' if value is None else str(value)
        items = [str(item) for item in combo.Items]
        if value and value not in items:
            combo.Items.Add(value)
            items.append(value)
        if value in items:
            for item in combo.Items:
                if str(item) == value:
                    combo.SelectedItem = item
                    return
        combo.SelectedIndex = -1

    def collect(self):
        """把界面上的值收集成一条记录。"""
        record = {
            'type': str(self.type_combo.Text or '').strip(),
            'branch': str(self.branch_combo.SelectedItem or ''),
            'establishment': str(self.est_combo.SelectedItem or ''),
            'move_type': str(self.move_combo.SelectedItem or ''),
        }
        for key, box in self.numbers.items():
            record[key] = number_value(box)
        return record

    def save(self, sender, args):
        """保存按钮：写数据库 + 写 .data 文件；成功后关闭对话框。"""
        record = self.collect()
        if not record['type']:
            MessageBox.Show(self.form, '请先填写类型名。', DIALOG_TITLE,
                            MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return
        self.created = not database.has(record['type'])
        try:
            database.set_record(record['type'], record)
            database.save_file()
        except Exception as ex:
            MessageBox.Show(self.form, '保存失败：%s' % ex, DIALOG_TITLE,
                            MessageBoxButtons.OK, MessageBoxIcon.Error)
            return
        self.saved_type = record['type']
        self.form.DialogResult = DialogResult.OK

    def show(self):
        """显示对话框，返回 DialogResult。"""
        return self.form.ShowDialog(self.owner) if self.owner is not None else self.form.ShowDialog()


class TypeBrowser:
    """左侧类型表格 + 右侧详情面板：把 .data 里的单位类型数据显示出来。"""

    def __init__(self):
        self.table = ListView()
        self.table.View = View.Details
        self.table.Dock = DockStyle.Fill
        self.table.FullRowSelect = True
        self.table.MultiSelect = False
        self.table.GridLines = True
        self.table.HideSelection = False
        self.table.HeaderStyle = ColumnHeaderStyle.Nonclickable
        for text, _key, width in TABLE_COLUMNS:
            self.table.Columns.Add(text, width)
        self.table.SelectedIndexChanged += self.on_select

        self.panel = Panel()
        self.panel.Dock = DockStyle.Right
        self.panel.Width = 300
        self.panel.BorderStyle = BorderStyle.FixedSingle
        self.bars = {}          # 字段 -> (数值标签, 色条, 满值)
        self.current = None     # 当前详情里显示的类型名
        self._build_detail()

    # ---------- 右侧详情 ----------
    def _build_detail(self):
        self.title = Label()
        self.title.Text = '（未选择类型）'
        self.title.AutoSize = False
        self.title.Location = Point(12, 10)
        self.title.Size = Size(270, 24)
        self.panel.Controls.Add(self.title)

        self.info = Label()
        self.info.Text = ''
        self.info.AutoSize = False
        self.info.Location = Point(12, 38)
        self.info.Size = Size(270, 44)
        self.panel.Controls.Add(self.info)

        y = 92
        for key, text, top, color in DETAIL_BARS:
            value, bar = add_bar_row(self.panel, text, y, color)
            self.bars[key] = (value, bar, top)
            y += 30

    def show(self, type_name):
        """把某个类型的数据显示到详情面板；传 None 清空。"""
        record = database.get(type_name) if type_name else None
        self.current = str(type_name) if record else None
        if not record:
            self.title.Text = '（未选择类型）'
            self.info.Text = ''
            for value, bar, _top in self.bars.values():
                value.Text = '-'
                bar.Width = 0
            return None
        self.title.Text = str(record.get('type') or type_name)
        self.info.Text = '兵种：%s\n编制：%s\n移动类型：%s' % (
            record.get('branch', ''), record.get('establishment', ''),
            record.get('move_type', ''))
        for key, (value_label, bar, top) in self.bars.items():
            value = int(record.get(key, 0) or 0)
            value_label.Text = str(value)
            set_bar(bar, value, top)
        return record

    # ---------- 左侧表格 ----------
    def reload(self):
        """按数据库当前内容重建表格，并刷新详情。"""
        self.table.BeginUpdate()
        self.table.Items.Clear()
        for name in database.names():
            record = database.get(name) or {}
            item = ListViewItem(str(name))
            for _text, key, _width in TABLE_COLUMNS[1:]:
                item.SubItems.Add(str(record.get(key, '')))
            item.Tag = str(name)
            self.table.Items.Add(item)
        self.table.EndUpdate()
        if self.table.Items.Count:
            self.table.Items[0].Selected = True
            self.show(self.table.Items[0].Tag)
        else:
            self.show(None)
        return self.table.Items.Count

    def select(self, type_name):
        """选中某个类型所在的行，返回是否找到。"""
        for item in self.table.Items:
            if str(item.Tag) == str(type_name):
                item.Selected = True
                item.EnsureVisible()
                self.show(type_name)
                return True
        return False

    def selected_name(self):
        """当前选中的类型名；没有选中返回 None。"""
        if self.table.SelectedItems.Count:
            return str(self.table.SelectedItems[0].Tag)
        return self.current

    def on_select(self, sender, args):
        if self.table.SelectedItems.Count:
            self.show(self.table.SelectedItems[0].Tag)


class OobBrowser:
    """左侧编制树 + 右侧详情：把 .oob 里的军队架构（军→师→团→营）显示出来。"""

    def __init__(self):
        self.tree = TreeView()
        self.tree.Dock = DockStyle.Fill
        self.tree.HideSelection = False
        self.tree.AfterSelect += self.on_select

        self.panel = Panel()
        self.panel.Dock = DockStyle.Right
        self.panel.Width = 300
        self.panel.BorderStyle = BorderStyle.FixedSingle
        self.current = None         # 当前详情里显示的节点
        self._build_detail()

    # ---------- 右侧详情 ----------
    def _build_detail(self):
        self.title = Label()
        self.title.Text = '（未选择节点）'
        self.title.AutoSize = False
        self.title.Location = Point(12, 10)
        self.title.Size = Size(270, 24)
        self.panel.Controls.Add(self.title)

        self.info = Label()
        self.info.Text = ''
        self.info.AutoSize = False
        self.info.Location = Point(12, 38)
        self.info.Size = Size(270, 92)
        self.panel.Controls.Add(self.info)

        self.step_value, self.step_bar = add_bar_row(
            self.panel, '本级数量', 138, Color.FromArgb(90, 140, 200))

        self.cap_title = Label()
        self.cap_title.Text = '单位类型能力（来自单位数据）'
        self.cap_title.AutoSize = False
        self.cap_title.Location = Point(12, 170)
        self.cap_title.Size = Size(270, 20)
        self.panel.Controls.Add(self.cap_title)

        self.caps = {}
        y = 196
        for key, text, top, color in CAPABILITY_BARS:
            value, bar = add_bar_row(self.panel, text, y, color)
            self.caps[key] = (value, bar, top)
            y += 28

        self.path_label = Label()
        self.path_label.Text = ''
        self.path_label.AutoSize = False
        self.path_label.Location = Point(12, y + 6)
        self.path_label.Size = Size(270, 60)
        self.panel.Controls.Add(self.path_label)

    def show(self, node):
        """把某个节点的数据显示到详情面板；传 None 清空。"""
        self.current = node
        if node is None:
            self.title.Text = '（未选择节点）'
            self.info.Text = ''
            self.path_label.Text = ''
            self.step_value.Text = '-'
            self.step_bar.Width = 0
            for value, bar, _top in self.caps.values():
                value.Text = '-'
                bar.Width = 0
            return None
        self.title.Text = str(node.name)
        self.info.Text = '级别：%s\n单位类型：%s\n下级：%d 个\n合计数量：%d' % (
            node.level, node.type or '（无）', len(node.children), node.total_step())
        self.path_label.Text = '编制路径：\n' + ' → '.join(node.path())
        value = int(node.step or 0)
        self.step_value.Text = str(value)
        set_bar(self.step_bar, value, 20)
        # 单位类型能力：从 units.data 里调出来显示
        record = node.capability()
        self.cap_title.Text = '单位类型能力：%s' % (node.type or '（无）')
        for key, (value_label, bar, top) in self.caps.items():
            number = int(record.get(key, 0) or 0) if record else 0
            value_label.Text = str(number) if record else '-'
            set_bar(bar, number, top)
        return node

    # ---------- 左侧树 ----------
    def _make_item(self, node):
        text = '%s（%s）' % (node.name, node.level)
        if node.type:
            text += ' · ' + node.type
        item = TreeNode(text)
        item.Tag = node
        for child in node.children:
            item.Nodes.Add(self._make_item(child))
        return item

    def reload(self):
        """按当前编制树重建左侧树，并刷新详情，返回节点总数。"""
        root = oob.root()
        self.tree.BeginUpdate()
        self.tree.Nodes.Clear()
        count = 0
        if root is not None:
            item = self._make_item(root)
            self.tree.Nodes.Add(item)
            self.tree.ExpandAll()
            self.tree.SelectedNode = item
            self.show(root)
            count = root.count()
        else:
            self.show(None)
        self.tree.EndUpdate()
        return count

    def select(self, node):
        """选中某个节点对应的树项，返回是否找到。"""
        item = self._find_item(self.tree.Nodes, node)
        if item is None:
            return False
        self.tree.SelectedNode = item
        self.show(node)
        return True

    def _find_item(self, items, node):
        for item in items:
            if item.Tag is node:
                return item
            found = self._find_item(item.Nodes, node)
            if found is not None:
                return found
        return None

    def selected_node(self):
        """当前选中的编制节点；没有选中返回 None。"""
        if self.tree.SelectedNode is not None:
            return self.tree.SelectedNode.Tag
        return None

    def on_select(self, sender, args):
        if self.tree.SelectedNode is not None:
            self.show(self.tree.SelectedNode.Tag)


class OobNodeDialog:
    """新增 / 修改编制树上的节点：番号、级别、单位类型、数量、备注。"""

    def __init__(self, owner=None, node=None, parent=None):
        self.owner = owner
        self.node = node            # 修改模式下的目标节点
        self.parent = parent        # 新建模式下的上级节点
        self.saved_node = None
        self.created = node is None

        self.form = Form()
        form = self.form
        form.Text = '修改节点' if node is not None else '新增下级节点'
        form.FormBorderStyle = FormBorderStyle.FixedDialog
        form.StartPosition = FormStartPosition.CenterParent
        form.MaximizeBox = False
        form.MinimizeBox = False
        form.ShowInTaskbar = False
        form.ClientSize = Size(440, 288)

        y = 18
        self.name_box = self._add_text(form, '番号', y)
        y += ROW_H
        self.level_combo = self._add_combo(form, '级别', y, oob.LEVELS)
        y += ROW_H
        self.type_combo = self._add_combo(form, '单位类型', y, [NO_TYPE] + database.names())
        y += ROW_H
        self.type_combo.SelectedIndexChanged += self.on_type_changed

        self.cap_label = Label()
        self.cap_label.Text = ''
        self.cap_label.AutoSize = False
        self.cap_label.Location = Point(LABEL_X, y)
        self.cap_label.Size = Size(FIELD_W + 90, 38)
        form.Controls.Add(self.cap_label)
        y += 44

        self._add_label(form, '数量', y)
        self.step_box = NumericUpDown()
        self.step_box.Location = Point(FIELD_X, y)
        self.step_box.Size = Size(90, 24)
        self.step_box.Minimum = Decimal(0)
        self.step_box.Maximum = Decimal(20)
        form.Controls.Add(self.step_box)
        y += ROW_H

        self.note_box = self._add_text(form, '备注', y)
        y += ROW_H

        save = Button()
        save.Text = '保存'
        save.Size = Size(90, 28)
        save.Location = Point(FIELD_X, y + 8)
        save.Click += self.save
        form.Controls.Add(save)

        cancel = Button()
        cancel.Text = '取消'
        cancel.Size = Size(90, 28)
        cancel.Location = Point(FIELD_X + 100, y + 8)
        cancel.DialogResult = DialogResult.Cancel
        form.Controls.Add(cancel)
        form.AcceptButton = save
        form.CancelButton = cancel

        self.load()

    # ---------- 界面小工具 ----------
    def _add_label(self, form, text, y):
        label = Label()
        label.Text = text
        label.Location = Point(LABEL_X, y + 4)
        label.Size = Size(95, 20)
        form.Controls.Add(label)
        return label

    def _add_text(self, form, text, y):
        self._add_label(form, text, y)
        box = TextBox()
        box.Location = Point(FIELD_X, y)
        box.Size = Size(FIELD_W, 24)
        form.Controls.Add(box)
        return box

    def _add_combo(self, form, text, y, values):
        self._add_label(form, text, y)
        combo = ComboBox()
        combo.Location = Point(FIELD_X, y)
        combo.Size = Size(FIELD_W, 24)
        combo.DropDownStyle = ComboBoxStyle.DropDownList
        for value in values:
            combo.Items.Add(value)
        form.Controls.Add(combo)
        return combo

    def _select(self, combo, value):
        value = '' if value is None else str(value)
        items = [str(item) for item in combo.Items]
        if value and value not in items:
            combo.Items.Add(value)
            items.append(value)
        if value in items:
            for item in combo.Items:
                if str(item) == value:
                    combo.SelectedItem = item
                    return
        combo.SelectedIndex = -1

    # ---------- 读写 ----------
    def load(self):
        """把节点数据填进控件；新建时按上级推算默认级别。"""
        node = self.node
        if node is not None:
            self.name_box.Text = node.name
            self._select(self.level_combo, node.level)
            self._select(self.type_combo, node.type or NO_TYPE)
            self.step_box.Value = Decimal(max(0, min(20, int(node.step))))
            self.note_box.Text = node.note
        else:
            self.name_box.Text = ''
            level = self.parent.deeper_level() if self.parent is not None else '营'
            self._select(self.level_combo, level)
            self._select(self.type_combo, NO_TYPE)
            self.step_box.Value = Decimal(1)
            self.note_box.Text = ''
        self.on_type_changed(None, None)
        return node

    def on_type_changed(self, sender, args):
        """单位类型变了就把它在 units.data 里的能力显示出来。"""
        type_name = str(self.type_combo.SelectedItem or '')
        if type_name == NO_TYPE:
            type_name = ''
        record = database.get(type_name) if type_name else None
        if record is None:
            self.cap_label.Text = '（未选择单位类型：可以留空做纯指挥机构）' if not type_name \
                else '（单位数据里没有这个类型：%s）' % type_name
            return None
        self.cap_label.Text = '%s · 软攻 %s / 硬攻 %s / 防御 %s\n移动力 %s（%s）· 突破 %s · 兵种 %s' % (
            type_name, record.get('soft_attack', 0), record.get('hard_attack', 0),
            record.get('defense', 0), record.get('move', 0), record.get('move_type', ''),
            record.get('breakthrough', 0), record.get('branch', ''))
        return record

    def collect(self):
        """把界面上的值收集成一个节点的数据。"""
        type_name = str(self.type_combo.SelectedItem or '')
        if type_name == NO_TYPE:
            type_name = ''
        return {
            'name': str(self.name_box.Text or '').strip(),
            'level': str(self.level_combo.SelectedItem or '营'),
            'type': type_name,
            'step': number_value(self.step_box),
            'note': str(self.note_box.Text or ''),
        }

    def save(self, sender, args):
        """保存按钮：写进编制树 + 写 .oob 文件；成功后关闭对话框。"""
        data = self.collect()
        if not data['name']:
            MessageBox.Show(self.form, '请先填写番号。', OOB_TITLE,
                            MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return
        if self.node is not None:
            self.node.name = data['name']
            self.node.level = data['level']
            self.node.type = data['type']
            self.node.step = data['step']
            self.node.note = data['note']
            self.saved_node = self.node
        else:
            node = oob.OobNode(name=data['name'], level=data['level'],
                               type_name=data['type'], step=data['step'],
                               note=data['note'])
            if self.parent is not None:
                self.parent.add_child(node)
            self.saved_node = node
        try:
            oob.save_file()
        except Exception as ex:
            MessageBox.Show(self.form, '保存失败：%s' % ex, OOB_TITLE,
                            MessageBoxButtons.OK, MessageBoxIcon.Error)
            return
        self.form.DialogResult = DialogResult.OK

    def show(self):
        """显示对话框，返回 DialogResult。"""
        return self.form.ShowDialog(self.owner) if self.owner is not None else self.form.ShowDialog()


def choose_file_type(owner=None):
    """先问要编辑哪类文件：返回 'data'（单位数据）/'oob'（军队编制）/None（取消）。"""
    form = Form()
    form.Text = '选择要编辑的文件类型'
    form.FormBorderStyle = FormBorderStyle.FixedDialog
    form.StartPosition = FormStartPosition.CenterParent
    form.MaximizeBox = False
    form.MinimizeBox = False
    form.ShowInTaskbar = False
    form.ClientSize = Size(400, 176)

    hint = Label()
    hint.Text = '请选择这次要打开并修改的文件类型：'
    hint.AutoSize = False
    hint.Location = Point(16, 14)
    hint.Size = Size(360, 20)
    form.Controls.Add(hint)

    def pick(kind):
        def handler(sender, args):
            form.Tag = kind
            form.DialogResult = DialogResult.OK
        return handler

    data_button = Button()
    data_button.Text = '单位数据（*.data）'
    data_button.Size = Size(180, 32)
    data_button.Location = Point(16, 48)
    data_button.Click += pick('data')
    form.Controls.Add(data_button)

    oob_button = Button()
    oob_button.Text = '军队编制（*.oob）'
    oob_button.Size = Size(180, 32)
    oob_button.Location = Point(204, 48)
    oob_button.Click += pick('oob')
    form.Controls.Add(oob_button)

    note = Label()
    note.Text = '单位数据：定义每种单位类型的数值；军队编制：军→师→团→营 的架构。'
    note.AutoSize = False
    note.Location = Point(16, 92)
    note.Size = Size(368, 34)
    form.Controls.Add(note)

    cancel = Button()
    cancel.Text = '取消'
    cancel.Size = Size(90, 28)
    cancel.Location = Point(294, 132)
    cancel.DialogResult = DialogResult.Cancel
    form.Controls.Add(cancel)
    form.CancelButton = cancel

    if owner is not None:
        form.ShowDialog(owner)
    else:
        form.ShowDialog()
    return form.Tag if form.DialogResult == DialogResult.OK else None


def refresh_status(status, message=None):
    """刷新底部状态栏；不传 detail 时显示单位数据文件与类型数量。"""
    return refresh_status_detail(status, message, data_status_detail())


def data_status_detail():
    """单位数据模式的状态栏内容。"""
    return '数据文件：%s（共 %d 种单位类型）' % (
        database.current_file(), len(database.UNIT_DATABASE))


def oob_status_detail():
    """军队编制模式的状态栏内容。"""
    count = oob.root().count() if oob.root() is not None else 0
    return '编制文件：%s（共 %d 个节点）' % (oob.current_file(), count)


def refresh_status_detail(status, message, detail):
    """按给定内容刷新状态栏（message 是最近一次操作结果，可为空）。"""
    text = detail if not message else '%s　|　%s' % (message, detail)
    status.Text = text
    return text


def set_window_title(form, path=None):
    """窗口标题带上当前数据文件名，方便同时打开多个文件时区分。"""
    path = path or database.current_file()
    form.Text = '%s - %s' % (WINDOW_TITLE, os.path.basename(path))
    return form.Text


def open_type_dialog(owner, status, browser=None, type_name=None):
    """打开「新建 / 修改单位类型」对话框；保存成功后刷新表格与状态栏。"""
    dialog = UnitTypeDialog(owner, type_name)
    result = dialog.show()
    if result == DialogResult.OK and dialog.saved_type:
        action = '已新建' if dialog.created else '已修改'
        if browser is not None:
            browser.reload()
            browser.select(dialog.saved_type)
        refresh_status(status, '%s类型：%s' % (action, dialog.saved_type))
    return dialog


class UnitsEditor:
    """编辑器主窗口：单位数据（.data）与军队编制（.oob）两类文件的编辑界面。"""

    def __init__(self, browser=None, tree_browser=None):
        self.form = Form()
        self.browser = browser or TypeBrowser()
        self.tree_browser = tree_browser or OobBrowser()
        self.mode = None
        self._build()

    # ---------- 界面 ----------
    def _build(self):
        form = self.form
        form.Text = WINDOW_TITLE
        form.ClientSize = WINDOW_SIZE
        form.MinimumSize = MINIMUM_SIZE
        form.StartPosition = FormStartPosition.CenterScreen

        # 停靠顺序有讲究：Fill 的视图先加，靠边控件后加（实测这样布局才对）
        form.Controls.Add(self.browser.table)
        form.Controls.Add(self.tree_browser.tree)
        form.Controls.Add(self.browser.panel)
        form.Controls.Add(self.tree_browser.panel)

        toolbar = Panel()
        toolbar.Dock = DockStyle.Top
        toolbar.Height = 46
        form.Controls.Add(toolbar)

        self.status = Label()
        self.status.Dock = DockStyle.Bottom
        self.status.Height = 24
        self.status.TextAlign = ContentAlignment.MiddleLeft
        self.status.Padding = Padding(8, 0, 8, 0)
        form.Controls.Add(self.status)

        self.open_button = self._add_button(toolbar, '打开文件...', 8, 110,
                                            lambda s, a: self.open_file())
        self.type_button = self._add_button(toolbar, '新建 / 修改单位类型...', 126, 190,
                                            lambda s, a: open_type_dialog(form, self.status, self.browser))
        self.add_node_button = self._add_button(toolbar, '新增下级...', 126, 110,
                                                lambda s, a: self.add_node())
        self.edit_node_button = self._add_button(toolbar, '修改节点...', 242, 100,
                                                 lambda s, a: self.edit_node())
        self.delete_node_button = self._add_button(toolbar, '删除节点', 346, 100,
                                                   lambda s, a: self.delete_node())

        # 双击：表格里的一行 = 修改类型；树上的一个节点 = 修改节点
        self.browser.table.DoubleClick += lambda sender, args: open_type_dialog(
            form, self.status, self.browser, self.browser.selected_name())
        self.tree_browser.tree.DoubleClick += lambda sender, args: self.edit_node()

    def _add_button(self, parent, text, x, width, handler):
        button = Button()
        button.Text = text
        button.FlatStyle = FlatStyle.System
        button.Location = Point(x, 9)
        button.Size = Size(width, 28)
        button.Click += handler
        parent.Controls.Add(button)
        return button

    def set_mode(self, kind):
        """切到 'data'（单位数据）或 'oob'（军队编制）模式，显示对应的视图与按钮。"""
        self.mode = kind
        data_mode = kind != 'oob'
        self.browser.table.Visible = data_mode
        self.browser.panel.Visible = data_mode
        self.type_button.Visible = data_mode
        self.tree_browser.tree.Visible = not data_mode
        self.tree_browser.panel.Visible = not data_mode
        for button in (self.add_node_button, self.edit_node_button, self.delete_node_button):
            button.Visible = not data_mode
        return kind

    # ---------- 启动与打开文件 ----------
    def start(self):
        """启动流程：先选文件类型，再选要打开的文件；取消则打开默认单位数据文件。"""
        kind = choose_file_type(self.form)
        if kind is None:
            self.load_default()
            return None
        return self.open_file(kind)

    def load_default(self):
        """打开默认的单位数据文件（Units/database/units.data）。"""
        try:
            database.load_file()
        except Exception as ex:
            MessageBox.Show(self.form, '读取数据文件失败：%s' % ex, WINDOW_TITLE,
                            MessageBoxButtons.OK, MessageBoxIcon.Error)
        self.set_mode('data')
        self.browser.reload()
        set_window_title(self.form)
        refresh_status(self.status)
        return None

    def open_file(self, kind=None, sender=None, args=None):
        """打开 .data 或 .oob 文件；kind 省略时先弹"选择文件类型"对话框。

        sender / args 是为了能被 WinForms 事件直接调用（点按钮时它会传两个参数）。
        """
        if kind is None:
            kind = choose_file_type(self.form)
            if kind is None:
                return None
        if kind == 'oob':
            return self.open_oob_file()
        return self.open_data_file()

    def _ask_path(self, title, file_filter, initial_dir):
        dialog = OpenFileDialog()
        dialog.Title = title
        dialog.Filter = file_filter
        dialog.InitialDirectory = initial_dir
        if dialog.ShowDialog(self.form) != DialogResult.OK:
            return None
        return str(dialog.FileName)

    def open_data_file(self):
        """打开一个 .data 文件，切到单位数据模式。"""
        path = self._ask_path('打开单位数据文件', DATA_FILE_FILTER, database.DATA_DIR)
        if path is None:
            return None
        try:
            count = database.load_file(path)
        except Exception as ex:
            MessageBox.Show(self.form, '打开失败：%s' % ex, WINDOW_TITLE,
                            MessageBoxButtons.OK, MessageBoxIcon.Error)
            return None
        self.set_mode('data')
        self.browser.reload()
        set_window_title(self.form, path)
        refresh_status(self.status, '已打开 %s（%d 种类型）' % (os.path.basename(path), count))
        return path

    def open_oob_file(self):
        """打开一个 .oob 文件，切到军队编制模式。"""
        path = self._ask_path('打开军队编制文件', OOB_FILE_FILTER, oob.OOB_DIR)
        if path is None:
            return None
        try:
            count = oob.load_file(path)
        except Exception as ex:
            MessageBox.Show(self.form, '打开失败：%s' % ex, WINDOW_TITLE,
                            MessageBoxButtons.OK, MessageBoxIcon.Error)
            return None
        self.set_mode('oob')
        self.tree_browser.reload()
        set_window_title(self.form, path)
        refresh_status_detail(self.status,
                              '已打开 %s（%d 个节点）' % (os.path.basename(path), count),
                              oob_status_detail())
        return path

    # ---------- 编制节点的增 / 改 / 删 ----------
    def add_node(self, sender=None, args=None):
        """给选中的节点加一个下级。"""
        parent = self.tree_browser.selected_node()
        if parent is None:
            MessageBox.Show(self.form, '请先在左侧选择一个上级节点。', OOB_TITLE,
                            MessageBoxButtons.OK, MessageBoxIcon.Information)
            return None
        dialog = OobNodeDialog(self.form, parent=parent)
        if dialog.show() != DialogResult.OK or dialog.saved_node is None:
            return None
        self.tree_browser.reload()
        self.tree_browser.select(dialog.saved_node)
        refresh_status_detail(self.status, '已新增：%s' % dialog.saved_node.name, oob_status_detail())
        return dialog.saved_node

    def edit_node(self, sender=None, args=None):
        """修改选中的节点。"""
        node = self.tree_browser.selected_node()
        if node is None:
            MessageBox.Show(self.form, '请先在左侧选择一个节点。', OOB_TITLE,
                            MessageBoxButtons.OK, MessageBoxIcon.Information)
            return None
        dialog = OobNodeDialog(self.form, node=node)
        if dialog.show() != DialogResult.OK:
            return None
        self.tree_browser.reload()
        self.tree_browser.select(node)
        refresh_status_detail(self.status, '已修改：%s' % node.name, oob_status_detail())
        return node

    def delete_node(self, sender=None, args=None):
        """删除选中的节点及其全部下级（根节点不能删）。"""
        node = self.tree_browser.selected_node()
        if node is None:
            MessageBox.Show(self.form, '请先在左侧选择一个节点。', OOB_TITLE,
                            MessageBoxButtons.OK, MessageBoxIcon.Information)
            return 0
        if node.parent is None:
            MessageBox.Show(self.form, '根节点不能删除。', OOB_TITLE,
                            MessageBoxButtons.OK, MessageBoxIcon.Information)
            return 0
        answer = MessageBox.Show(
            self.form, '确定删除「%s」及其全部下级（共 %d 个节点）吗？' % (node.name, node.count()),
            OOB_TITLE, MessageBoxButtons.YesNo, MessageBoxIcon.Question)
        if answer != DialogResult.Yes:
            return 0
        count = node.count()
        name = node.name
        node.detach()
        oob.save_file()
        self.tree_browser.reload()
        refresh_status_detail(self.status, '已删除：%s（%d 个节点）' % (name, count), oob_status_detail())
        return count


def build_editor(browser=None, tree_browser=None, load_default=True):
    """创建编辑器主窗口并返回 Form。

    browser / tree_browser 一般不用传；测试里想拿视图对象时可以自己建好传进来。
    load_default=True 时直接载入默认单位数据文件（不弹选择框，供测试与旧用法）。
    """
    editor = UnitsEditor(browser=browser, tree_browser=tree_browser)
    if load_default:
        editor.load_default()
    return editor.form


def install_exception_guard():
    """把 WinForms 事件里没被接住的异常变成提示框，避免整个程序直接退出。"""
    def on_error(sender, args):
        try:
            detail = str(args.Exception)
        except Exception:
            detail = '未知错误'
        MessageBox.Show('操作出错，已取消：\n\n%s' % detail, WINDOW_TITLE,
                        MessageBoxButtons.OK, MessageBoxIcon.Error)
    Application.ThreadException += on_error
    return on_error


def run_editor():
    """在 STA 线程上运行编辑器（文件对话框等 WinForms 组件需要 STA）。"""
    def run():
        Application.EnableVisualStyles()
        Application.SetCompatibleTextRenderingDefault(False)
        install_exception_guard()
        editor = UnitsEditor()
        editor.start()          # 先选文件类型与文件，再进入消息循环
        Application.Run(editor.form)

    thread = Thread(ThreadStart(run))
    thread.SetApartmentState(ApartmentState.STA)
    thread.Start()
    thread.Join()
    return 0


def main():
    """程序入口：打开单位编辑器窗口。"""
    return run_editor()


if __name__ == '__main__':
    sys.exit(main())
