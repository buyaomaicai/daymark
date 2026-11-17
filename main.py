import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QDate, QTime, QTimer, QSize, QRectF
from PySide6.QtGui import QAction, QFont, QIcon, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QDateEdit, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QMenu, QPushButton, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTimeEdit,
    QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    ComboBox, FluentIcon, LineEdit,
    MessageBox, setTheme, Theme,
)

APP_NAME = "Daymark"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "tasks.sqlite3"
STARTUP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "Microsoft/Windows/Start Menu/Programs/Startup"


def now():
    return datetime.now().astimezone()


def parse_local(value):
    return datetime.fromisoformat(value)


class Store:
    def __init__(self):
        self.db = sqlite3.connect(DB_PATH)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
            created_at TEXT NOT NULL, due_at TEXT, interval_minutes INTEGER,
            next_reminder TEXT, completed_at TEXT, completed_date TEXT)""")
        self.db.commit()

    def all(self):
        return self.db.execute("SELECT * FROM tasks ORDER BY CASE WHEN kind='deadline' THEN due_at ELSE title END").fetchall()

    def add(self, title, kind, due=None, interval=None):
        created = now()
        next_reminder = created + timedelta(minutes=interval) if due and due > created else None
        self.db.execute("""INSERT INTO tasks(title,kind,created_at,due_at,interval_minutes,next_reminder)
            VALUES(?,?,?,?,?,?)""", (title, kind, created.isoformat(), due.isoformat() if due else None,
                                       interval, next_reminder.isoformat() if next_reminder else None))
        self.db.commit()

    def complete(self, task):
        if task["kind"] == "daily":
            self.db.execute("UPDATE tasks SET completed_date=? WHERE id=?", (date.today().isoformat(), task["id"]))
        else:
            self.db.execute("UPDATE tasks SET completed_at=? WHERE id=?", (now().isoformat(), task["id"]))
        self.db.commit()

    def delete(self, task_id):
        self.db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self.db.commit()

    def check_reminders(self):
        current = now()
        due_items = self.db.execute("SELECT * FROM tasks WHERE kind='deadline' AND completed_at IS NULL AND next_reminder IS NOT NULL").fetchall()
        notifications = []
        for task in due_items:
            deadline = parse_local(task["due_at"])
            if current >= deadline:
                self.db.execute("UPDATE tasks SET next_reminder=NULL WHERE id=?", (task["id"],))
            elif current >= parse_local(task["next_reminder"]):
                notifications.append(task["title"])
                next_time = current + timedelta(minutes=task["interval_minutes"])
                self.db.execute("UPDATE tasks SET next_reminder=? WHERE id=?", (next_time.isoformat(), task["id"]))
        self.db.commit()
        return notifications


class StatCard(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setFixedHeight(82)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(2)
        self.title = QLabel(title)
        self.value = QLabel("0")
        self.value.setStyleSheet("color: #286bd1; font-size: 20px; font-weight: 700; background: transparent; border: none;")
        self.title.setStyleSheet("color: #5b687b; font-size: 12px; background: transparent; border: none;")
        layout.addWidget(self.title)
        layout.addWidget(self.value)


class GlassNavButton(QPushButton):
    def __init__(self, text="", icon=None, checkable=False, parent=None):
        super().__init__(text, parent)
        if icon:
            self.setIcon(icon)
        self.setCheckable(checkable)
        self.setIconSize(QSize(16, 16))
        self.setMinimumHeight(40)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        if self.isDown():
            start, end = QColor(211, 229, 251, 235), QColor(189, 215, 247, 210)
        elif self.isChecked():
            start, end = QColor(241, 247, 255, 238), QColor(214, 231, 255, 218)
        elif self.underMouse():
            start, end = QColor(255, 255, 255, 245), QColor(232, 242, 255, 232)
        else:
            start, end = QColor(255, 255, 255, 166), QColor(255, 255, 255, 108)
        gradient.setColorAt(0, start)
        gradient.setColorAt(1, end)
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1))
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, 15, 15)

        label = self.text().strip()
        icon_size = self.iconSize()
        text_width = painter.fontMetrics().horizontalAdvance(label)
        gap = 9 if label and not self.icon().isNull() else 0
        content_width = text_width + (icon_size.width() + gap if not self.icon().isNull() else 0)
        x = (self.width() - content_width) / 2
        if not self.icon().isNull():
            icon_rect = QRectF(x, (self.height() - icon_size.height()) / 2, icon_size.width(), icon_size.height())
            self.icon().paint(painter, icon_rect.toRect(), Qt.AlignmentFlag.AlignCenter)
            x += icon_size.width() + gap
        color = QColor("#28588f") if self.isChecked() or self.underMouse() else QColor("#34445b")
        painter.setPen(color)
        painter.drawText(QRectF(x, 0, max(0, self.width() - x), self.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        painter.end()


class FeedbackToast(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("feedbackToast")
        self.setFixedSize(360, 58)
        self.hide()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 10, 8)
        layout.setSpacing(10)
        self.icon = QLabel("✓")
        self.icon.setFixedSize(22, 22)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title = QLabel()
        self.title.setStyleSheet("color: #25354b; font-weight: 700; background: transparent; border: none;")
        self.content = QLabel()
        self.content.setMaximumWidth(170)
        self.content.setStyleSheet("color: #52637a; background: transparent; border: none;")
        self.close_button = QPushButton("×")
        self.close_button.setFixedSize(24, 24)
        self.close_button.setStyleSheet("QPushButton { color: #6d7b8e; background: transparent; border: none; border-radius: 12px; font-size: 17px; padding: 0; } QPushButton:hover { color: #27384f; background: rgba(255,255,255,180); }")
        self.close_button.clicked.connect(self.hide)
        layout.addWidget(self.icon)
        layout.addWidget(self.title)
        layout.addWidget(self.content, 1)
        layout.addWidget(self.close_button)

        self.setStyleSheet("#feedbackToast { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 rgba(255,255,255,248),stop:0.45 rgba(236,246,255,238),stop:1 rgba(220,239,255,232)); border: 1px solid rgba(255,255,255,250); border-radius: 16px; }")
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def show_message(self, title, content, success=True, duration=2200):
        self.icon.setText("✓" if success else "!")
        self.icon.setStyleSheet(
            "color: #17834a; background: rgba(37,174,103,35); border-radius: 11px; font-weight: 700;"
            if success else
            "color: #a45b00; background: rgba(235,169,64,45); border-radius: 11px; font-weight: 700;"
        )
        self.title.setText(title)
        self.content.setText(content)
        self.content.setToolTip(content)
        self.move((self.parentWidget().width() - self.width()) // 2, 12)
        self.raise_()
        self.show()
        self.timer.start(duration)


class TaskDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("新建任务")
        self.setMinimumWidth(560)
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.surface = QFrame()
        self.surface.setObjectName("dialogSurface")
        outer.addWidget(self.surface)

        layout = QVBoxLayout(self.surface)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)

        heading = QLabel("新建任务")
        heading.setStyleSheet("color: #24344a; font-size: 20px; font-weight: 700;")
        header = QHBoxLayout()
        header.addWidget(heading)
        header.addStretch(1)
        close = QPushButton("×")
        close.setToolTip("关闭")
        close.setFixedSize(32, 32)
        close.setStyleSheet("QPushButton { color: #59677c; background: rgba(255,255,255,180); border: 1px solid rgba(165,180,202,100); border-radius: 16px; font-size: 18px; padding: 0; } QPushButton:hover { background: white; }")
        close.clicked.connect(self.reject)
        header.addWidget(close)
        layout.addLayout(header)

        fields = QGridLayout()
        fields.setHorizontalSpacing(12)
        fields.setVerticalSpacing(8)
        name_label = QLabel("任务名称")
        type_label = QLabel("任务类型")
        for label in (name_label, type_label):
            label.setStyleSheet("color: #65738a; font-size: 12px;")
        self.name = LineEdit()
        self.name.setPlaceholderText("写下要做的事")
        self.name.setMinimumHeight(42)
        self.kind = ComboBox()
        self.kind.addItems(["普通任务", "每日任务", "截止任务"])
        self.kind.setMinimumHeight(42)
        fields.addWidget(name_label, 0, 0)
        fields.addWidget(type_label, 0, 1)
        fields.addWidget(self.name, 1, 0)
        fields.addWidget(self.kind, 1, 1)
        fields.setColumnStretch(0, 3)
        fields.setColumnStretch(1, 2)
        layout.addLayout(fields)

        self.deadline_panel = QFrame()
        self.deadline_panel.setObjectName("deadlinePanel")
        deadline_layout = QVBoxLayout(self.deadline_panel)
        deadline_layout.setContentsMargins(16, 14, 16, 16)
        deadline_layout.setSpacing(10)
        deadline_title = QLabel("截止与提醒")
        deadline_title.setStyleSheet("color: #34445b; font-size: 13px; font-weight: 600;")
        deadline_layout.addWidget(deadline_title)

        deadline_fields = QGridLayout()
        deadline_fields.setHorizontalSpacing(12)
        deadline_fields.setVerticalSpacing(7)
        for column, text in enumerate(("截止日期", "截止时间", "提醒间隔")):
            label = QLabel(text)
            label.setStyleSheet("color: #718097; font-size: 12px;")
            deadline_fields.addWidget(label, 0, column)

        self.due_date = QDateEdit(QDate.currentDate().addDays(1))
        self.due_date.setCalendarPopup(True)
        self.due_date.setDisplayFormat("yyyy-MM-dd")
        self.due_date.setMinimumHeight(40)
        self.due_time = QTimeEdit(QTime.currentTime().addSecs(7200))
        self.due_time.setDisplayFormat("HH:mm")
        self.due_time.setMinimumHeight(40)
        self.interval = ComboBox()
        self.interval.addItems(["5", "10", "15", "30", "60", "120", "240"])
        self.interval.setCurrentText("30")
        self.interval.setMinimumHeight(40)
        deadline_fields.addWidget(self.due_date, 1, 0)
        deadline_fields.addWidget(self.due_time, 1, 1)
        deadline_fields.addWidget(self.interval, 1, 2)
        for column in range(3):
            deadline_fields.setColumnStretch(column, 1)
        deadline_layout.addLayout(deadline_fields)
        layout.addWidget(self.deadline_panel)

        self.error = QLabel("请输入任务名称。")
        self.error.setStyleSheet("color: #b42318; font-size: 12px;")
        self.error.hide()
        layout.addWidget(self.error)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("取消")
        save = QPushButton("创建任务")
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept_task)
        cancel.setStyleSheet("QPushButton { color: #34445b; background: rgba(255,255,255,190); border: 1px solid rgba(133,151,175,90); border-radius: 12px; padding: 9px 18px; min-height: 20px; } QPushButton:hover { background: white; }")
        save.setStyleSheet("QPushButton { color: white; font-weight: 600; background: #4e87d7; border: 1px solid rgba(255,255,255,190); border-radius: 12px; padding: 9px 18px; min-height: 20px; } QPushButton:hover { background: #3f78c8; }")
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addLayout(actions)

        self.setStyleSheet("""
            QDialog { background: transparent; }
            #dialogSurface { background: rgba(245, 248, 253, 250); border: 1px solid rgba(255,255,255,235); border-radius: 22px; }
            QLineEdit, QComboBox, QDateEdit, QTimeEdit {
                color: #29384d; background: rgba(255,255,255,235);
                border: 1px solid rgba(165,180,202,130); border-radius: 12px;
                padding: 7px 10px; selection-background-color: rgba(79,137,226,110);
            }
            QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus {
                border: 1px solid #78a5e5;
            }
            #deadlinePanel { background: rgba(255,255,255,150); border: 1px solid rgba(255,255,255,230); border-radius: 18px; }
        """)
        self.name.returnPressed.connect(self.accept_task)
        self.kind.currentIndexChanged.connect(self.update_deadline_visibility)
        self.update_deadline_visibility()

        self._drag_offset = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 58:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def update_deadline_visibility(self, *_):
        self.deadline_panel.setVisible(self.kind.currentIndex() == 2)
        self.adjustSize()

    def accept_task(self):
        if not self.name.text().strip():
            self.error.show()
            self.name.setFocus()
            return
        self.accept()

    def task_values(self):
        kind = ("task", "daily", "deadline")[self.kind.currentIndex()]
        if kind != "deadline":
            return self.name.text().strip(), kind, None, None
        qdate = self.due_date.date()
        qtime = self.due_time.time()
        due = datetime(qdate.year(), qdate.month(), qdate.day(), qtime.hour(), qtime.minute()).astimezone()
        return self.name.text().strip(), kind, due, int(self.interval.currentText())


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.store = Store()
        self.view = "全部任务"
        self.startup_enabled = (STARTUP_DIR / "Daymark.bat").exists()
        self.setWindowTitle("Daymark")
        self.setWindowIcon(QIcon())
        self.resize(1280, 800)
        self.setMinimumSize(1000, 650)
        self.build_ui()
        self.toast = FeedbackToast(self)
        self.setup_tray()
        QTimer.singleShot(0, self.apply_native_backdrop)
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.reminder_tick)
        self.timer.start(30000)
        QTimer.singleShot(1200, self.reminder_tick)

    def build_ui(self):
        self.setObjectName("mainWindow")
        self.setAutoFillBackground(False)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(252)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(18, 24, 18, 18)
        side_layout.setSpacing(10)
        brand = QLabel("✦  Daymark")
        brand.setStyleSheet("font-size: 21px; font-weight: 700; color: #2563eb; padding: 4px 8px 14px; background: transparent;")
        side_layout.addWidget(brand)
        self.day_button = GlassNavButton(date.today().strftime("%Y-%m-%d"), FluentIcon.CALENDAR.icon(Theme.LIGHT))
        self.day_button.clicked.connect(lambda: self.set_view("今天"))
        side_layout.addWidget(self.day_button)

        stats = QHBoxLayout()
        stats.setSpacing(8)
        self.pending_card = StatCard("未完成")
        self.completed_card = StatCard("今日完成")
        stats.addWidget(self.pending_card)
        stats.addWidget(self.completed_card)
        side_layout.addLayout(stats)
        section = QLabel("任务视图")
        section.setStyleSheet("color: #8491a3; padding: 10px 8px 2px; background: transparent;")
        side_layout.addWidget(section)
        self.nav_buttons = {}
        for name, icon in (("全部任务", FluentIcon.HOME), ("未完成", FluentIcon.CHECKBOX),
                           ("今天", FluentIcon.CALENDAR), ("已完成", FluentIcon.COMPLETED)):
            button = GlassNavButton(name, icon.icon(Theme.LIGHT), checkable=True)
            button.setChecked(name == self.view)
            button.clicked.connect(lambda checked=False, value=name: self.set_view(value))
            self.nav_buttons[name] = button
            side_layout.addWidget(button)
        side_layout.addStretch(1)
        note = QLabel("关闭窗口后，Daymark 会继续\n在系统托盘后台运行。")
        note.setStyleSheet("color: #8491a3; padding: 8px; background: transparent;")
        side_layout.addWidget(note)
        root.addWidget(side)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 24, 28, 20)
        content_layout.setSpacing(16)
        top = QHBoxLayout()
        title_column = QVBoxLayout()
        self.page_title = QLabel("全部任务")
        self.page_title.setStyleSheet("font-size: 26px; font-weight: 700; background: transparent;")
        self.date_label = QLabel(date.today().strftime("%Y年%m月%d日  ·  %A"))
        self.date_label.setStyleSheet("color: #65738a; background: transparent;")
        title_column.addWidget(self.page_title)
        title_column.addWidget(self.date_label)
        top.addLayout(title_column)
        top.addStretch(1)
        self.startup_button = QPushButton("开机启动 ✓" if self.startup_enabled else "开机启动")
        self.startup_button.clicked.connect(self.toggle_startup)
        top.addWidget(self.startup_button)
        content_layout.addLayout(top)

        tools = QHBoxLayout()
        self.search = LineEdit()
        self.search.setPlaceholderText("搜索任务")
        self.search.textChanged.connect(self.refresh)
        tools.addWidget(self.search, 1)
        self.new_task_button = QPushButton("新建任务")
        self.new_task_button.setIcon(FluentIcon.ADD.icon(Theme.LIGHT))
        self.new_task_button.setText("  " + self.new_task_button.text())
        self.new_task_button.clicked.connect(self.focus_new_task)
        tools.addWidget(self.new_task_button)
        content_layout.addLayout(tools)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["", "任务名称", "类型", "截止时间", "状态"])
        self.table.setColumnWidth(0, 44)
        self.table.setColumnWidth(1, 450)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 190)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.itemChanged.connect(self.on_table_item_changed)
        content_layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.complete_button = QPushButton("标记完成")
        self.complete_button.setIcon(FluentIcon.ACCEPT.icon(Theme.LIGHT))
        self.complete_button.setText("  " + self.complete_button.text())
        self.complete_button.clicked.connect(self.complete_selected)
        self.delete_button = QPushButton("删除")
        self.delete_button.setIcon(FluentIcon.DELETE.icon(Theme.LIGHT))
        self.delete_button.setText("  " + self.delete_button.text())
        self.delete_button.clicked.connect(self.delete_selected)
        actions.addWidget(self.complete_button)
        actions.addWidget(self.delete_button)
        content_layout.addLayout(actions)
        root.addWidget(content, 1)

        content.setAutoFillBackground(False)
        content.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        content.setStyleSheet("background-color: rgba(0,0,0,0);")
        self.table.setStyleSheet("""
            QTableWidget { background: rgba(255,255,255,64); border: 1px solid rgba(255,255,255,220); border-radius: 24px; gridline-color: transparent; }
            QTableWidget::item { padding: 12px 12px; border-bottom: 1px solid rgba(255,255,255,105); color: #273449; }
            QTableWidget::item:selected { background: rgba(102,158,238,85); color: #18345b; }
            QHeaderView { background: transparent; }
            QHeaderView::section { background: rgba(255,255,255,70); color: #718097; padding: 15px 12px; border: none; border-bottom: 1px solid rgba(255,255,255,120); font-weight: 600; }
            QHeaderView::section:first { border-top-left-radius: 24px; }
            QHeaderView::section:last { border-top-right-radius: 24px; }
            QCheckBox::indicator { width: 20px; height: 20px; border-radius: 10px; border: 1px solid rgba(91,120,161,115); background: rgba(255,255,255,145); }
            QCheckBox::indicator:hover { border: 1px solid #6f9fe5; background: rgba(255,255,255,225); }
            QCheckBox::indicator:checked { background: #6f9fe5; border: 1px solid #6f9fe5; }
        """)
        side.setStyleSheet("#sidebar { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(238,244,252,125), stop:1 rgba(249,251,255,72)); border-right: 1px solid rgba(255,255,255,205); }")
        self.setStyleSheet("""
            #mainWindow { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #dce2ea, stop:0.5 #eef1f5, stop:1 #d9e0e8); }
            #mainWindow[nativeBackdrop="true"] { background: transparent; }
            QLabel { background: transparent; border: none; }
            #statCard { background: rgba(255,255,255,105); border: 1px solid rgba(255,255,255,215); border-radius: 18px; }
            QToolTip { color: #263449; background: rgba(255,255,255,220); border: 1px solid rgba(255,255,255,245); border-radius: 10px; padding: 6px 9px; }
        """)
        for button in (self.startup_button, self.complete_button, self.delete_button):
            self.style_glass_button(button)
        self.style_glass_button(self.new_task_button, primary=True)
        self.search.setStyleSheet("color: #29384d; background: rgba(255,255,255,220); border: 1px solid rgba(255,255,255,240); border-radius: 14px; padding: 7px 12px; selection-background-color: rgba(79,137,226,110);")

    def apply_native_backdrop(self):
        if os.name != "nt":
            return
        try:
            import ctypes

            dwm = ctypes.WinDLL("dwmapi")
            set_attribute = dwm.DwmSetWindowAttribute
            set_attribute.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
            set_attribute.restype = ctypes.c_long
            hwnd = ctypes.c_void_p(int(self.winId()))
            light_titlebar = ctypes.c_int(0)
            set_attribute(hwnd, 20, ctypes.byref(light_titlebar), ctypes.sizeof(light_titlebar))

            class BlurBehind(ctypes.Structure):
                _fields_ = [("flags", ctypes.c_uint), ("enabled", ctypes.c_int),
                            ("region", ctypes.c_void_p), ("transition", ctypes.c_int)]

            enable_blur = dwm.DwmEnableBlurBehindWindow
            enable_blur.argtypes = [ctypes.c_void_p, ctypes.POINTER(BlurBehind)]
            enable_blur.restype = ctypes.c_long
            blur = BlurBehind(1, 1, None, 0)
            blur_result = enable_blur(hwnd, ctypes.byref(blur))

            # Win11's transient backdrop gives the full client area Acrylic material.
            system_backdrop = ctypes.c_int(3)
            backdrop_result = set_attribute(hwnd, 38, ctypes.byref(system_backdrop), ctypes.sizeof(system_backdrop))
            class AccentPolicy(ctypes.Structure):
                _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int),
                            ("gradient_color", ctypes.c_uint), ("animation_id", ctypes.c_int)]

            class CompositionData(ctypes.Structure):
                _fields_ = [("attribute", ctypes.c_int), ("data", ctypes.c_void_p),
                            ("size", ctypes.c_size_t)]

            set_composition = ctypes.WinDLL("user32").SetWindowCompositionAttribute
            set_composition.argtypes = [ctypes.c_void_p, ctypes.POINTER(CompositionData)]
            set_composition.restype = ctypes.c_bool
            accent_flags = 0x20 | 0x40 | 0x80 | 0x100
            accent = AccentPolicy(4, accent_flags, 0x66E8F1FC, 0)
            data = CompositionData(19, ctypes.cast(ctypes.byref(accent), ctypes.c_void_p), ctypes.sizeof(accent))
            accent_applied = set_composition(hwnd, ctypes.byref(data))
            if accent_applied or backdrop_result == 0 or blur_result == 0:
                self.setProperty("nativeBackdrop", True)
                self.style().unpolish(self)
                self.style().polish(self)
                self.update()
        except (AttributeError, OSError):
            pass
    @staticmethod
    def style_glass_button(button, primary=False):
        button.setIconSize(QSize(16, 16))
        button.setMinimumHeight(40)
        button.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if primary:
            button.setStyleSheet("""
                QPushButton { color: #214f86; font-weight: 600; border: 1px solid rgba(255,255,255,235); border-radius: 15px; padding: 10px 17px;
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 rgba(255,255,255,242),stop:0.2 rgba(224,239,255,236),stop:0.52 rgba(157,195,245,228),stop:1 rgba(196,220,252,232)); }
                QPushButton:hover { color: #183f70; background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 rgba(255,255,255,255),stop:0.22 rgba(232,243,255,250),stop:0.55 rgba(174,207,249,245),stop:1 rgba(211,230,255,248)); border: 1px solid white; border-radius: 15px; }
                QPushButton:pressed { background: rgba(125,170,228,245); border-radius: 15px; padding-top: 11px; padding-bottom: 9px; }
                QPushButton:disabled { color: rgba(33,79,134,120); background: rgba(220,230,243,150); border-radius: 15px; }
            """)
        else:
            button.setStyleSheet(f"""
                QPushButton {{ color: #34445b; border: 1px solid rgba(255,255,255,205); border-radius: 15px; padding: 9px 14px;
                    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(255,255,255,165),stop:1 rgba(255,255,255,106)); }}
                QPushButton:hover {{ color: #28588f; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(255,255,255,235),stop:1 rgba(224,238,255,215)); border: 1px solid rgba(255,255,255,245); border-radius: 15px; }}
                QPushButton:pressed {{ background: rgba(202,222,250,205); border: 1px solid rgba(255,255,255,255); border-radius: 15px; padding-top: 10px; padding-bottom: 8px; }}
                QPushButton:checked {{ color: #28588f; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(240,247,255,230),stop:1 rgba(213,231,255,195)); border: 1px solid rgba(255,255,255,240); border-radius: 15px; }}
            """)

    def focus_new_task(self):
        self.add_task()

    def show_feedback(self, title, content, success=True):
        self.toast.show_message(title, content, success)

    def add_task(self):
        dialog = TaskDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        title, kind, due, interval = dialog.task_values()
        self.store.add(title, kind, due, interval)
        self.refresh()
        self.show_feedback("任务已添加", title)

    def task_status(self, task):
        if task["kind"] == "daily":
            done = task["completed_date"] == date.today().isoformat()
            return done, "今日已完成" if done else "进行中", "每天"
        if task["kind"] == "task":
            done = bool(task["completed_at"])
            return done, "已完成" if done else "进行中", "无截止时间"
        deadline = parse_local(task["due_at"])
        done = bool(task["completed_at"])
        status = "已完成" if done else ("已逾期" if now() >= deadline else "进行中")
        return done, status, deadline.strftime("%Y-%m-%d %H:%M")

    def refresh(self, *_):
        tasks = self.store.all()
        query = self.search.text().strip().casefold() if hasattr(self, "search") else ""
        visible = []
        pending = complete = 0
        for task in tasks:
            done, status, due = self.task_status(task)
            pending += not done
            complete += done
            if query and query not in task["title"].casefold():
                continue
            if self.view == "未完成" and done:
                continue
            if self.view == "已完成" and not done:
                continue
            if self.view == "今天" and task["kind"] == "deadline" and parse_local(task["due_at"]).date() != date.today():
                continue
            visible.append((task, status, due))
        self.pending_card.value.setText(str(pending))
        self.completed_card.value.setText(str(complete))
        signals_were_blocked = self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(visible))
            for row, (task, status, due) in enumerate(visible):
                done, _, _ = self.task_status(task)
                check_item = QTableWidgetItem()
                check_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                check_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
                check_item.setCheckState(Qt.CheckState.Checked if done else Qt.CheckState.Unchecked)
                check_item.setData(Qt.ItemDataRole.UserRole, task["id"])
                if done:
                    check_item.setFlags(check_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                self.table.setItem(row, 0, check_item)
                values = (task["title"], {"task": "普通", "daily": "每日", "deadline": "截止"}[task["kind"]], due, status)
                for col, value in enumerate(values, start=1):
                    item = QTableWidgetItem(value)
                    if col == 4 and status == "已逾期":
                        item.setForeground(Qt.GlobalColor.red)
                    self.table.setItem(row, col, item)
                self.table.item(row, 1).setData(Qt.ItemDataRole.UserRole, task["id"])
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
        finally:
            self.table.setUpdatesEnabled(True)
            self.table.blockSignals(signals_were_blocked)
            self.table.viewport().update()

    def on_table_item_changed(self, item):
        if item.column() != 0 or item.checkState() != Qt.CheckState.Checked:
            return
        task_id = item.data(Qt.ItemDataRole.UserRole)
        task = next((task for task in self.store.all() if task["id"] == task_id), None)
        if task and not self.task_status(task)[0]:
            self.complete_task(task)

    def set_view(self, name):
        self.view = name
        self.page_title.setText(name)
        for label, button in self.nav_buttons.items():
            button.setChecked(label == name)
        self.refresh()

    def selected_task(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        task_id = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)
        return next((task for task in self.store.all() if task["id"] == task_id), None)

    def complete_task(self, task):
        self.store.complete(task)
        self.refresh()
        self.show_feedback("已标记完成", task["title"])

    def complete_selected(self):
        task = self.selected_task()
        if task:
            self.complete_task(task)
        else:
            self.show_feedback("请选择任务", "先在列表中选中一项。", success=False)

    def delete_selected(self):
        task = self.selected_task()
        if task:
            dialog = MessageBox("删除任务", f"确定删除「{task['title']}」吗？此操作无法撤销。", self)
            dialog.yesButton.setText("删除")
            dialog.cancelButton.setText("取消")
            if dialog.exec():
                self.store.delete(task["id"])
                self.refresh()
                self.show_feedback("任务已删除", task["title"])
        else:
            self.show_feedback("请选择任务", "先在列表中选中要删除的任务。", success=False)

    def reminder_tick(self):
        for title in self.store.check_reminders():
            try:
                from winotify import Notification
                Notification(app_id=APP_NAME, title="待办提醒", msg=title).show()
            except Exception:
                pass
        self.refresh()

    def setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_FileDialogInfoView))
        self.tray.setToolTip("Daymark 正在后台运行")
        menu = QMenu()
        open_action = QAction("打开 Daymark", self)
        open_action.triggered.connect(self.show_window)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(open_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_window() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self.tray.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()

    def toggle_startup(self):
        STARTUP_DIR.mkdir(parents=True, exist_ok=True)
        startup_file = STARTUP_DIR / "Daymark.bat"
        if startup_file.exists():
            startup_file.unlink()
            self.startup_enabled = False
        else:
            script = Path(__file__).resolve()
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            launcher = pythonw if pythonw.exists() else Path(sys.executable)
            startup_file.write_text(f'@echo off\nstart "" "{launcher}" "{script}"\n', encoding="utf-8")
            self.startup_enabled = True
        self.startup_button.setText("开机启动 ✓" if self.startup_enabled else "开机启动")
        self.show_feedback("开机启动已开启" if self.startup_enabled else "开机启动已关闭",
                           "设置已保存到当前 Windows 用户。")


if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    setTheme(Theme.LIGHT)
    window = MainWindow()
    available = app.primaryScreen().availableGeometry()
    window.move(available.center() - window.rect().center())
    window.show()
    sys.exit(app.exec())
