"""把 launcher.py 打包成单文件 exe（游戏启动器.exe）。

运行方式：双击 build_launcher_exe.bat，或命令行运行 python build_launcher_exe.py
产物：根目录下的 游戏启动器.exe，双击即弹出空白启动器窗口。

用 Python 执行打包而不是把命令写进 .bat，是因为 cmd.exe 按 GBK 解析批处理文件，
UTF-8 的 exe 名字直接写进 .bat 会乱码；交给 Python 调用 PyInstaller 更稳。
"""
import os
import shutil
import subprocess
import sys

# 控制台编码可能不是中文代码页，避免打印中文时直接抛异常
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors='replace')
    except Exception:
        pass

EXE_NAME = '游戏启动器'
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(PROJECT_DIR, 'launcher.py')
DIST_DIR = os.path.join(PROJECT_DIR, 'dist')
BUILD_DIR = os.path.join(PROJECT_DIR, 'build')
FINAL_EXE = os.path.join(PROJECT_DIR, EXE_NAME + '.exe')

ARGS = [
    '--noconfirm',
    '--onefile',
    '--windowed',
    '--name', EXE_NAME,
    '--distpath', DIST_DIR,
    '--workpath', BUILD_DIR,
    '--specpath', BUILD_DIR,
    ENTRY,
]


def main():
    if not os.path.isfile(ENTRY):
        print('找不到入口文件：%s' % ENTRY)
        return 1

    env = dict(os.environ)
    # 不让用户级 site-packages 混进分析结果，保证打进 exe 的依赖只来自当前 Python 环境
    env['PYTHONNOUSERSITE'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'

    print('正在打包 %s.exe ...' % EXE_NAME)
    code = subprocess.call([sys.executable, '-m', 'PyInstaller'] + ARGS, cwd=PROJECT_DIR, env=env)
    if code != 0:
        print('PyInstaller 打包失败（退出码 %d）。' % code)
        return code

    built = os.path.join(DIST_DIR, EXE_NAME + '.exe')
    if not os.path.isfile(built):
        print('打包结束但没找到产物：%s' % built)
        return 1

    shutil.move(built, FINAL_EXE)
    if os.path.isdir(DIST_DIR) and not os.listdir(DIST_DIR):
        os.rmdir(DIST_DIR)

    size_mb = os.path.getsize(FINAL_EXE) / 1024 / 1024
    print('完成：%s（%.1f MB）' % (FINAL_EXE, size_mb))
    return 0


if __name__ == '__main__':
    sys.exit(main())
