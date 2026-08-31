# Hex Editor

一个 Windows 窗口应用，使用 Python + WinForms（pythonnet）编写。

## 运行环境

- Python 3.12（当前使用 Codex 自带运行时）
- 需要已安装 pythonnet（`pip install pythonnet`）

## 文件格式

本软件创建/保存的文件为自定义 `.hex` 文件，用于存储特定类型的文件（如 PNG 图片）。

`.hex` 文件结构（固定头部 + 数据）：

| 偏移 | 大小 | 说明 |
|------|------|------|
| 0 | 4 | 魔数 `HEX1`，标识这是本软件的 .hex 文件 |
| 4 | 8 | 原始文件类型（如 `PNG`，右侧补空格） |
| 12 | 8 | 数据长度（字节） |
| 20 | 可变 | 原始文件内容 |

## 当前功能

- 新建（Ctrl+N）：创建空内容，保存时生成 `.hex` 文件
- 打开（Ctrl+O）：打开 `.hex` 文件，或直接打开图片等原始文件查看
- 保存（Ctrl+S）/ 另存为（Ctrl+Shift+S）：生成 `.hex` 文件
- 导出原始文件（Ctrl+E）：从 `.hex` 中还原出原始类型的文件
- 十六进制视图：偏移列 + 十六进制 + ASCII 侧栏
- 大文件最多显示前 512 KB，避免界面卡顿

## 运行方法

方式一：双击 `run.bat`

方式二：在 PowerShell 中运行

```powershell
python main.py
```

## 文件说明

- `main.py`：应用主体（窗口、菜单、.hex 读写）
- `hexformat.py`：.hex 容器与十六进制格式化逻辑
- `run.bat`：双击启动脚本

## 下一步计划

- 编辑十六进制字节
- 修改后保存回 .hex 文件
