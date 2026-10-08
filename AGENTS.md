# 运行环境（.venv）说明

**一句话结论：本项目所有 Python 入口都跑项目根目录的 `.venv`，不要用 Codex 自带的运行时。**

## 1. 为什么用项目自己的 .venv

早期这些窗口程序是拿 Codex 自带的 Python 跑的，路径写在 `run_*.bat` 和
`launcher.py` 里：

```
C:\Users\36349\.cache\codex-runtimes\codex-primary-runtime\dependencies\python
```

这个目录**会随 Codex 运行时更新被整个换掉**（2026-09-28 那次更新就把装好的
pythonnet 清空了，`import clr` 直接报 `ModuleNotFoundError`，所有窗口都打不开）。
所以现在改成项目自己的虚拟环境，依赖固定在 `requirements.txt` 里，跟 Codex 升级无关。

## 2. 环境内容

| 项目 | 值 |
|------|-----|
| 虚拟环境 | `E:\PZC_Pro\.venv`（不进版本库，见 `.gitignore` 的 `.venv/`） |
| 解释器 | `.venv\Scripts\python.exe` / GUI 用 `.venv\Scripts\pythonw.exe` |
| Python 版本 | 3.13.2 |
| 基础解释器 | `C:\Users\36349\AppData\Local\Programs\Python\Python313`（`pyvenv.cfg` 的 home） |
| 是否带系统包 | 否（`include-system-site-packages = false`），依赖只从 `requirements.txt` 来 |

`requirements.txt` 里固定的依赖及用途：

| 包 | 版本 | 用途 |
|----|------|------|
| pythonnet | 3.1.0 | `clr` / `System.Windows.Forms`，**所有 GUI 入口都靠它** |
| numpy | 2.5.3 | 只有 `Hex_Editor/imagedetect.py`（图片识别格子）用 |
| pillow | 12.3.0 | 图片读取（同上） |
| pyinstaller | 6.22.3 | 只有 `build_launcher_exe.py` 打包 exe 时用 |

pythonnet 3.1.0 的 wheel 覆盖 CPython 3.10–3.14，所以基础解释器在这几个版本内都能用。

## 3. 创建 / 重建环境

```bat
:: 项目根目录，双击或命令行运行都行
setup_env.bat
```

它做的事：用 `py -3.13 -m venv .venv` 建环境 → `pip install -r requirements.txt`。
删掉 `.venv` 再跑一遍即可重建，**不要手动往 venv 里装 requirements.txt 之外的东西**。

手动等价命令：

```powershell
py -3.13 -m venv E:\PZC_Pro\.venv
E:\PZC_Pro\.venv\Scripts\python.exe -m pip install -r E:\PZC_Pro\requirements.txt
```

环境自检（应该打印 `venv ok: 3.13.2 numpy 2.5.3 pillow 12.3.0`）：

```powershell
E:\PZC_Pro\.venv\Scripts\python.exe -c "import clr, numpy, PIL; clr.AddReference('System.Windows.Forms'); import System.Windows.Forms; print('venv ok:', __import__('sys').version.split()[0], 'numpy', numpy.__version__, 'pillow', PIL.__version__)"
```

## 4. 各入口用哪个解释器

所有 `.bat` 都已经指向 `.venv`，直接双击即可；找不到 `.venv` 时会退回 PATH 上的 `python`。

| 入口 | 脚本 | 解释器 |
|------|------|--------|
| 游戏启动器 | `run_launcher.bat` → `launcher.py` | `.venv\Scripts\pythonw.exe` |
| 六角格编辑器 | `Hex_Editor\run.bat` → `main.py` | `..\.venv\Scripts\pythonw.exe` |
| 初设 | `setup\run_setup.bat` → `setup.py` | `..\.venv\Scripts\pythonw.exe` |
| 单位/编制编辑器 | `Units\run.bat` → `units_editor.py` | `..\.venv\Scripts\pythonw.exe` |
| 重打包启动器 exe | `build_launcher_exe.bat` → `build_launcher_exe.py` | `.venv\Scripts\python.exe` |

启动器窗口的左侧栏（六角格编辑器 / 初设）是用**另一个进程**拉起来的：这两个工具各自
需要 STA 线程和自己的消息循环，塞进启动器进程里会互相阻塞。给它们找解释器的是
`launcher.py` 的 `pythonw_path()`，顺序是：

1. 开发态（直接跑 `launcher.py`）：用当前解释器（或其同目录的 `pythonw.exe`）；
2. 打包态（跑 `游戏启动器.exe`）：先找 `<项目根>\.venv\Scripts\pythonw.exe`；
3. 找不到再退回旧的 Codex 运行时路径（只作兜底，随时可能被清掉）；
4. 最后才找 PATH 上的 `pythonw` / `python`。

`game_window.py` / `new_game.py` / `scenario_list.py` 是按路径从磁盘动态加载的，
改完不用重打包；只有改 `launcher.py`（启动器自己的窗口、按钮、解释器查找）才需要
跑 `build_launcher_exe.bat` 重新打包 exe。

## 5. 沙箱 / 自动化执行注意

- `.venv\Scripts\python.exe` 是 venv 的转发器，它最终要启动**系统 Python 3.13**
  （`C:\Users\36349\AppData\Local\Programs\Python\Python313\python.exe`）。
  如果沙箱不允许执行工作区外的程序，直接调用会失败，报：
  `Unable to create process using '"...\.venv\Scripts\python.exe" ...'`，
  或 PowerShell 报 `Program 'python.exe' failed to run: ... 拒绝访问`。
  这时需要用提权（unsandboxed）方式运行。
- 用 Codex 自带运行时的 Python 跑本项目**不等于**环境没问题：它现在可能装着
  pythonnet，但那目录随时会被运行时更新清空，验证请在 `.venv` 下做。
- GUI 入口会创建 WinForms 窗口；想无窗口验证逻辑时，用 `System.Threading.Thread` +
  `SetApartmentState(STA)` 里构造 `Form` 但不要 `ShowDialog()`。

## 6. 常见故障

| 现象 | 原因 / 处理 |
|------|-------------|
| `ModuleNotFoundError: No module named 'clr'` | 用错解释器或没装 pythonnet。换成 `.venv\Scripts\python.exe`，或先跑 `setup_env.bat` |
| `Unable to create process using '...\.venv\Scripts\python.exe'` | 基础 Python 3.13 不见了，或被沙箱拦；重装 Python 3.13 或提权运行 |
| 双击 exe 后左栏工具打不开 | 打包态按第 4 节的顺序找解释器；确认 `.venv` 存在，改过 `launcher.py` 就要重打包 |
| 改了依赖却提示装不上 | 依赖以 `requirements.txt` 为唯一来源，改完重跑 `setup_env.bat` |
| 窗口能开但地图/单位画不出来 | 多半是数据文件问题（`Units/database/units.data`、`.scenario`），跟环境无关 |

## 7. 改依赖时的规矩

1. 只改 `requirements.txt`（写死版本），不要只在 venv 里 `pip install`；
2. 重跑 `setup_env.bat` 让 `.venv` 与文件一致；
3. 若新增的是 GUI 依赖，确认 `pythonnet` 仍在，且 `import clr` 自检通过；
4. `.venv/`、`build/`、`dist/`、`*.spec`、`*.exe` 都不进版本库。
