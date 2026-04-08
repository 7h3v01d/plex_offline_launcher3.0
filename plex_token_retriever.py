"""
Plex Token Retriever
KeystoneAI — Plex Offline Launcher Setup Utility

Authenticates with Plex.tv and saves the auth token to launcher_config.json.
Run standalone: python plex_token_retriever.py
Importable:     from plex_token_retriever import run_token_retriever
"""

import sys
import json
import requests
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFrame, QMessageBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QCursor


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PLEX_AUTH_URL  = "https://plex.tv/users/sign_in.json"
PLEX_PRODUCT   = "Plex Offline Launcher"
PLEX_CLIENT_ID = "plex-offline-launcher-keystone"
DEFAULT_CONFIG  = Path(__file__).parent / "launcher_config.json"

HEADERS = {
    "X-Plex-Client-Identifier": PLEX_CLIENT_ID,
    "X-Plex-Product": PLEX_PRODUCT,
    "X-Plex-Version": "1.0.0",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


# ---------------------------------------------------------------------------
# Auth worker (runs off the main thread)
# ---------------------------------------------------------------------------

class AuthWorker(QThread):
    success = pyqtSignal(str, str)   # token, display_name
    failure = pyqtSignal(str)        # error message

    def __init__(self, username: str, password: str):
        super().__init__()
        self.username = username
        self.password = password

    def run(self):
        try:
            resp = requests.post(
                PLEX_AUTH_URL,
                headers=HEADERS,
                json={"user": {"login": self.username, "password": self.password}},
                timeout=10,
            )
            if resp.status_code == 201:
                data = resp.json()
                token = data["user"]["authToken"]
                name  = data["user"].get("title") or data["user"].get("username") or self.username
                self.success.emit(token, name)
            elif resp.status_code == 401:
                self.failure.emit("Incorrect username or password.")
            elif resp.status_code == 422:
                self.failure.emit("Invalid request — check your credentials.")
            else:
                self.failure.emit(f"Plex returned HTTP {resp.status_code}.")
        except requests.exceptions.ConnectionError:
            self.failure.emit("No connection — check your internet and try again.")
        except requests.exceptions.Timeout:
            self.failure.emit("Request timed out. Plex may be unavailable.")
        except Exception as e:
            self.failure.emit(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

class HSep(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet("background: #22263a; border: none;")


def field_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet("color: #6b7280; font-size: 10px; font-weight: 600; letter-spacing: 1.2px;")
    return lbl


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

STYLESHEET = """
QWidget {
    background-color: #12141a;
    color: #cdd1de;
    font-family: 'Segoe UI', 'SF Pro Display', sans-serif;
    font-size: 13px;
}

QLineEdit {
    background: #1b1e2a;
    border: 1px solid #282c3e;
    border-radius: 6px;
    padding: 10px 14px;
    color: #e0e4f0;
    font-size: 13px;
    selection-background-color: #e5a00d40;
}

QLineEdit:focus {
    border: 1px solid #e5a00d;
    background: #1e2132;
}

QLineEdit:hover {
    border: 1px solid #343a52;
}

QPushButton#auth_btn {
    background: #e5a00d;
    color: #0d0f14;
    border: none;
    border-radius: 6px;
    padding: 12px;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.4px;
}
QPushButton#auth_btn:hover    { background: #f0b422; }
QPushButton#auth_btn:pressed  { background: #c98b0a; }
QPushButton#auth_btn:disabled { background: #2a2d3a; color: #555; }

QPushButton#copy_btn {
    background: #1b1e2a;
    color: #9ca3af;
    border: 1px solid #282c3e;
    border-radius: 6px;
    padding: 7px 14px;
    font-size: 12px;
}
QPushButton#copy_btn:hover { background: #222638; color: #cdd1de; border-color: #383f58; }

QPushButton#reset_btn {
    background: transparent;
    color: #4b5268;
    border: none;
    font-size: 11px;
    padding: 0;
}
QPushButton#reset_btn:hover { color: #e5a00d; }

QFrame#token_box {
    background: #181b26;
    border: 1px solid #252a3a;
    border-radius: 8px;
}

QMessageBox {
    background: #1a1d28;
    color: #cdd1de;
}
"""


class PlexTokenRetriever(QWidget):
    def __init__(self, config_path: Path = DEFAULT_CONFIG):
        super().__init__()
        self.config_path = config_path
        self._token: str = ""
        self._worker: AuthWorker | None = None

        self.setWindowTitle("Plex Token Retriever — Keystone Launcher")
        self.setFixedSize(430, 530)
        self.setStyleSheet(STYLESHEET)
        self._build_ui()
        self._check_existing()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(12)

        play = QLabel("▶")
        play.setStyleSheet("color: #e5a00d; font-size: 26px;")

        titles = QVBoxLayout()
        titles.setSpacing(3)
        t = QLabel("Plex Token Retriever")
        t.setStyleSheet("color: #e8ecf4; font-size: 19px; font-weight: 600; letter-spacing: 0.3px;")
        s = QLabel("Keystone Offline Launcher — setup")
        s.setStyleSheet("color: #4b5268; font-size: 11px;")
        titles.addWidget(t)
        titles.addWidget(s)

        hdr.addWidget(play, 0, Qt.AlignmentFlag.AlignTop)
        hdr.addLayout(titles)
        hdr.addStretch()
        root.addLayout(hdr)

        root.addSpacing(22)
        root.addWidget(HSep())
        root.addSpacing(22)

        # ── Credential fields ─────────────────────────────────────────
        root.addWidget(field_label("Plex Username or Email"))
        root.addSpacing(6)
        self.username_in = QLineEdit()
        self.username_in.setPlaceholderText("you@example.com")
        self.username_in.returnPressed.connect(self._authenticate)
        root.addWidget(self.username_in)

        root.addSpacing(14)

        root.addWidget(field_label("Password"))
        root.addSpacing(6)
        self.password_in = QLineEdit()
        self.password_in.setPlaceholderText("••••••••••")
        self.password_in.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_in.returnPressed.connect(self._authenticate)
        root.addWidget(self.password_in)

        root.addSpacing(20)

        # ── Auth button ───────────────────────────────────────────────
        self.auth_btn = QPushButton("Retrieve Token")
        self.auth_btn.setObjectName("auth_btn")
        self.auth_btn.setFixedHeight(44)
        self.auth_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.auth_btn.clicked.connect(self._authenticate)
        root.addWidget(self.auth_btn)

        root.addSpacing(8)

        # ── Status ────────────────────────────────────────────────────
        self.status_lbl = QLabel("Enter your Plex.tv credentials above.")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setStyleSheet("color: #4b5268; font-size: 11px;")
        root.addWidget(self.status_lbl)

        root.addSpacing(18)
        root.addWidget(HSep())
        root.addSpacing(16)

        # ── Token display ─────────────────────────────────────────────
        tok_hdr = QHBoxLayout()
        tok_hdr.addWidget(field_label("Saved Token"))
        tok_hdr.addStretch()
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setObjectName("copy_btn")
        self.copy_btn.setVisible(False)
        self.copy_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.copy_btn.clicked.connect(self._copy_token)
        tok_hdr.addWidget(self.copy_btn)
        root.addLayout(tok_hdr)

        root.addSpacing(8)

        self.token_box = QFrame()
        self.token_box.setObjectName("token_box")
        tb_layout = QVBoxLayout(self.token_box)
        tb_layout.setContentsMargins(14, 10, 14, 10)

        self.token_lbl = QLabel("—")
        self.token_lbl.setStyleSheet(
            "color: #e5a00d; font-family: 'Consolas','Cascadia Code','Courier New',monospace;"
            "font-size: 11px; background: transparent;"
        )
        self.token_lbl.setWordWrap(True)
        self.token_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        tb_layout.addWidget(self.token_lbl)
        root.addWidget(self.token_box)

        root.addSpacing(10)

        # ── Footer row ────────────────────────────────────────────────
        footer = QHBoxLayout()
        self.cfg_lbl = QLabel(f"Config: {self.config_path.name}")
        self.cfg_lbl.setStyleSheet("color: #333848; font-size: 10px;")
        self.cfg_lbl.setToolTip(str(self.config_path))

        self.reset_btn = QPushButton("Clear saved token")
        self.reset_btn.setObjectName("reset_btn")
        self.reset_btn.setVisible(False)
        self.reset_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.reset_btn.clicked.connect(self._clear_token)

        footer.addWidget(self.cfg_lbl)
        footer.addStretch()
        footer.addWidget(self.reset_btn)
        root.addLayout(footer)

        root.addStretch()

    # ------------------------------------------------------------------
    # Logic
    # ------------------------------------------------------------------

    def _check_existing(self):
        token = self._load_token()
        if token:
            self._token = token
            self.token_lbl.setText(self._mask(token))
            self._set_status("✓  Token already saved in config.", "ok")
            self.auth_btn.setText("Re-authenticate")
            self.copy_btn.setVisible(True)
            self.reset_btn.setVisible(True)

    def _authenticate(self):
        username = self.username_in.text().strip()
        password = self.password_in.text()

        if not username:
            self._set_status("Username is required.", "err")
            self.username_in.setFocus()
            return
        if not password:
            self._set_status("Password is required.", "err")
            self.password_in.setFocus()
            return

        self.auth_btn.setEnabled(False)
        self.auth_btn.setText("Authenticating…")
        self._set_status("Contacting Plex.tv…", "info")

        self._worker = AuthWorker(username, password)
        self._worker.success.connect(self._on_success)
        self._worker.failure.connect(self._on_failure)
        self._worker.start()

    def _on_success(self, token: str, name: str):
        self._token = token
        self.token_lbl.setText(self._mask(token))
        self._set_status(f"✓  Authenticated as {name}", "ok")
        self.auth_btn.setEnabled(True)
        self.auth_btn.setText("Re-authenticate")
        self.copy_btn.setVisible(True)
        self.reset_btn.setVisible(True)
        self.password_in.clear()
        self._save_token(token, name)

    def _on_failure(self, message: str):
        self._set_status(f"✕  {message}", "err")
        self.auth_btn.setEnabled(True)
        self.auth_btn.setText("Retrieve Token")

    def _copy_token(self):
        if self._token:
            QApplication.clipboard().setText(self._token)
            self.copy_btn.setText("Copied!")
            QTimer.singleShot(1800, lambda: self.copy_btn.setText("Copy"))

    def _clear_token(self):
        reply = QMessageBox.question(
            self, "Clear Token",
            f"Remove the saved Plex token from {self.config_path.name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._delete_token()
            self._token = ""
            self.token_lbl.setText("—")
            self.copy_btn.setVisible(False)
            self.reset_btn.setVisible(False)
            self._set_status("Token cleared.", "info")
            self.auth_btn.setText("Retrieve Token")

    def _set_status(self, text: str, level: str = "info"):
        colours = {"ok": "#4ade80", "err": "#f87171", "info": "#4b5268"}
        weights = {"ok": "600",     "err": "400",    "info": "400"}
        c = colours.get(level, "#4b5268")
        w = weights.get(level, "400")
        self.status_lbl.setStyleSheet(f"color: {c}; font-size: 12px; font-weight: {w};")
        self.status_lbl.setText(text)

    # ------------------------------------------------------------------
    # Config I/O
    # ------------------------------------------------------------------

    def _load_token(self) -> str:
        if not self.config_path.exists():
            return ""
        try:
            with open(self.config_path) as f:
                return json.load(f).get("plex_token", "")
        except Exception:
            return ""

    def _save_token(self, token: str, name: str = ""):
        data: dict = {}
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    data = json.load(f)
            except Exception:
                pass
        data["plex_token"] = token
        if name:
            data["plex_username"] = name
        try:
            with open(self.config_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "Save Failed", f"Could not write config:\n{e}")

    def _delete_token(self):
        if not self.config_path.exists():
            return
        try:
            with open(self.config_path) as f:
                data = json.load(f)
            data.pop("plex_token", None)
            data.pop("plex_username", None)
            with open(self.config_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    @staticmethod
    def _mask(token: str) -> str:
        if len(token) <= 8:
            return "••••••••"
        return token[:4] + "•" * (len(token) - 8) + token[-4:]


# ---------------------------------------------------------------------------
# Public API + entry point
# ---------------------------------------------------------------------------

def run_token_retriever(config_path: Path = DEFAULT_CONFIG) -> None:
    """
    Launch the token retriever window.
    Call from your launcher's setup flow, e.g.:

        from plex_token_retriever import run_token_retriever
        run_token_retriever(config_path=Path("launcher_config.json"))
    """
    app = QApplication.instance() or QApplication(sys.argv)
    window = PlexTokenRetriever(config_path=config_path)
    window.show()
    app.exec()


if __name__ == "__main__":
    run_token_retriever()
