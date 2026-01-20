import sys
import os

# 将 src 目录添加到 Python 路径，以便导入模块
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from PyQt5.QtWidgets import QApplication
from src.gui.main_window import EveSearchApp

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = EveSearchApp()
    window.show()
    sys.exit(app.exec_())
