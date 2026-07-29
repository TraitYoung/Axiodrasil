"""PyInstaller / 直接运行入口（避免以 __main__.py 作为脚本路径时的包解析问题）。"""

from launcher.app import main

if __name__ == "__main__":
    main()
