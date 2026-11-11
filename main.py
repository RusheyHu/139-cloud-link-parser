import sys, os, re, json, time, base64, hashlib, random, string, urllib.parse, traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QMessageBox, QGroupBox, QFormLayout)
import requests
from playwright.sync_api import sync_playwright

APP_NAME = "中国移动云盘直链解析器"
BASE_URL = "https://share-kd-njs.yun.139.com/yun-share/richlifeApp/devapp/IOutLink"
PROFILE_DIR = Path.home() / ".139_link_parser" / "browser_profile"
STATE_DIR = Path.home() / ".139_link_parser"
STATE_DIR.mkdir(parents=True, exist_ok=True)


def parse_share(text):
    text = (text or "").strip()
    if not text:
        raise ValueError("请先粘贴中国移动云盘分享链接")
    # Common PC and mobile share routes. Also accept a bare share ID optionally followed by @passcode.
    pwd = ""
    m_pwd = re.search(r"(?:提取码|访问码|密码)\s*[:：]?\s*([A-Za-z0-9]{4,8})", text, re.I)
    if m_pwd:
        pwd = m_pwd.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{8,40}(?:@[A-Za-z0-9]{4,8})?", text):
        bits = text.split("@", 1)
        return bits[0], bits[1] if len(bits) > 1 else pwd
    # hash route: #/w/i/<id> or #/w/group/i/<id>
    patterns = [r"#/w/(?:group/)?i/([A-Za-z0-9_-]+)", r"#/m/i\?([A-Za-z0-9_-]+)", r"[?&](?:shareId|linkID)=([A-Za-z0-9_-]+)"]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1), pwd
    raise ValueError("无法识别分享 ID。请粘贴完整的 yun.139.com 分享链接或分享 ID。")


def md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def get_account_from_cookies(cookies: dict) -> str:
    """
    The share-download API's `account` field expects the account identifier
    (normally the mobile number), not the encrypted cookie value itself.
    The official web client stores it as Base64 in ORCHES-I-ACCOUNT-ENCRYPT.
    """
    raw = (cookies or {}).get("ORCHES-I-ACCOUNT-ENCRYPT", "")
    if not raw:
        raise ValueError(
            "登录信息缺少 ORCHES-I-ACCOUNT-ENCRYPT。请重新扫码登录；"
            "登录完成后仍缺失时，请检查浏览器是否登录到了 yun.139.com。"
        )

    # Browser cookie values may be URL-escaped and Base64 padding may be omitted.
    raw = urllib.parse.unquote(str(raw)).strip().strip('"')
    raw += "=" * ((4 - len(raw) % 4) % 4)
    try:
        decoded = base64.b64decode(raw, validate=True).decode("utf-8").strip()
    except Exception:
        raise ValueError(
            "无法解码登录 Cookie 中的账号标识。请退出程序后重新扫码登录，"
            "不要手动填写或分享 Cookie。"
        )

    # Do not expose the decoded account in logs or error messages.
    if not decoded or len(decoded) > 64 or any(ch.isspace() for ch in decoded):
        raise ValueError("登录 Cookie 解出的账号标识格式异常，请重新扫码登录。")
    return decoded


def make_headers(body, cookies):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    if body:
        compact = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        encoded = urllib.parse.quote(compact, safe="~()*!.'-")
        sorted_text = ''.join(sorted(encoded))
        first = md5(base64.b64encode(sorted_text.encode()).decode())
    else:
        first = md5(base64.b64encode(b"").decode())
    signature = md5(first + md5(stamp + ":" + nonce)).upper()
    h = {
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://yun.139.com",
        "Referer": "https://yun.139.com/shareweb/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
        "mcloud-sign": f"{stamp},{nonce},{signature}",
        "mcloud-client": "10702",
        "mcloud-version": "7.13.3",
        "mcloud-channel": "1000101",
    }
    if cookies.get("skey"):
        h["mcloud-skey"] = cookies["skey"]
    if cookies.get("authorization"):
        h["Authorization"] = cookies["authorization"]
        h["x-m4c-token"] = cookies.get("auth_token", "")
        h["x-m4c-account"] = cookies.get("ORCHES-I-ACCOUNT-ENCRYPT", "")
    return h


class CloudClient:
    def __init__(self, cookies=None):
        self.cookies = cookies or {}
        self.session = requests.Session()

    def post(self, endpoint, body):
        url = f"{BASE_URL}/{endpoint}"
        cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        headers = make_headers(body, self.cookies)
        if cookie_str:
            headers["Cookie"] = cookie_str
        r = self.session.post(url, json=body, headers=headers, timeout=25)
        r.raise_for_status()
        try:
            data = r.json()
        except Exception:
            raise RuntimeError(f"服务器返回非 JSON 内容（HTTP {r.status_code}）")
        code = str(data.get("resultCode", data.get("code", "")))
        desc = str(data.get("desc", data.get("message", "")))
        if code and code not in ("0", "000000", "200", "success", "200000000"):
            if code == "200000401" or "鉴权失败" in desc:
                raise PermissionError(f"账号鉴权失败（{code}）：{desc or '请重新扫码登录'}")
            if "提取码" in desc or "密码" in desc:
                raise ValueError(f"分享提取码错误或缺失：{desc}")
            raise RuntimeError(f"移动云盘接口返回错误 {code}：{desc or '未提供错误说明'}")
        return data

    def list_root(self, link_id, passwd):
        body = {"getOutLinkInfoReq": {
            "linkID": link_id, "passwd": passwd, "pCaID": "root",
            "bNum": 1, "eNum": 200, "srtDr": 1, "caSrt": "", "coSrt": ""
        }}
        return self.post("getOutLinkInfoV6", body)

    def get_direct(self, link_id, fpath):
        account = get_account_from_cookies(self.cookies)
        body = {"dlFromOutLinkReqV3": {
            "account": account, "linkID": link_id,
            "coIDLst": {"item": [fpath]}
        }}
        return self.post("dlFromOutLinkV3", body)


class LoginWorker(QThread):
    log = Signal(str)
    done = Signal(bool, str)

    def run(self):
        try:
            self.log.emit("正在打开中国移动云盘网页，请在浏览器中使用移动云盘 App 扫码登录……")
            with sync_playwright() as p:
                browser_type = p.chromium
                launch_args = {"headless": False, "args": ["--disable-blink-features=AutomationControlled"]}
                # Prefer installed Microsoft Edge; fall back to installed Google Chrome.
                try:
                    context = browser_type.launch_persistent_context(str(PROFILE_DIR), channel="msedge", **launch_args)
                except Exception:
                    context = browser_type.launch_persistent_context(str(PROFILE_DIR), channel="chrome", **launch_args)
                pages = context.pages
                page = pages[0] if pages else context.new_page()
                page.goto("https://yun.139.com/shareweb/", wait_until="domcontentloaded", timeout=60000)
                self.log.emit("浏览器已打开。请完成扫码；程序正在等待登录态 Cookie……")
                deadline = time.time() + 240
                found = {}
                while time.time() < deadline:
                    try:
                        all_cookies = context.cookies(["https://yun.139.com", "https://139.com"])
                        found = {c["name"]: c["value"] for c in all_cookies}
                        # Persist all first-party cookies in the Playwright profile; only required names are checked.
                        if found.get("authorization") and (found.get("auth_token") or found.get("skey")):
                            break
                    except Exception:
                        pass
                    time.sleep(2)
                context.close()
                if not found.get("authorization"):
                    self.done.emit(False, "等待超时或未发现有效登录 Cookie。请确认已在网页中完成扫码登录后重试。")
                    return
                wanted = ["authorization", "auth_token", "token", "skey", "a_k", "ud_id", "ORCHES-I-ACCOUNT-ENCRYPT"]
                saved = {k: found[k] for k in wanted if found.get(k)}
                (STATE_DIR / "cookies.json").write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
                self.done.emit(True, "扫码登录态已保存到本机。不会上传到第三方服务器。")
        except Exception as e:
            self.done.emit(False, f"扫码登录失败：{e}")


class ParseWorker(QThread):
    log = Signal(str)
    success = Signal(str, str)
    failed = Signal(str)

    def __init__(self, link_text, passcode):
        super().__init__()
        self.link_text = link_text
        self.passcode = passcode

    def run(self):
        try:
            link_id, embedded_pwd = parse_share(self.link_text)
            pwd = self.passcode.strip() or embedded_pwd
            self.log.emit(f"已识别分享 ID：{link_id}\n正在读取分享文件信息……")
            cookie_file = STATE_DIR / "cookies.json"
            cookies = json.loads(cookie_file.read_text(encoding="utf-8")) if cookie_file.exists() else {}
            client = CloudClient(cookies)
            info = client.list_root(link_id, pwd)
            data = info.get("data", info)
            files = data.get("coLst") or data.get("fileList") or []
            folders = data.get("caLst") or []
            if not files:
                if folders:
                    self.failed.emit("分享目录中包含子文件夹。当前版本尚未递归列出子目录，请先打开分享页确认文件位置。")
                    return
                self.failed.emit("已请求分享信息，但接口没有返回文件列表。请检查分享是否有效、是否需要提取码。")
                return
            if len(files) > 1:
                # Present all direct URLs only when one file can be unambiguously selected.
                lines = []
                for i, f in enumerate(files, 1):
                    lines.append(f"{i}. {f.get('coName', '未命名文件')}（{f.get('coSize', '?')} 字节）")
                self.failed.emit("该分享包含多个文件。当前版本为避免复制错误，暂不自动选择。\n" + "\n".join(lines))
                return
            f = files[0]
            fpath = f.get("path")
            if not fpath:
                raise RuntimeError("分享信息中没有返回文件 path，无法申请下载直链。")
            self.log.emit(f"文件：{f.get('coName', '未命名文件')}\n正在申请下载直链……")
            result = client.get_direct(link_id, fpath)
            payload = result.get("data", result)
            direct = payload.get("redrUrl") or payload.get("downloadUrl") or payload.get("url")
            if not direct:
                raise RuntimeError("接口已响应，但没有返回 redrUrl。可能是账号鉴权、分享权限或接口版本发生变化。")
            self.success.emit(str(f.get("coName", "文件")), str(direct))
        except PermissionError as e:
            self.failed.emit(f"需要登录授权：{e}\n请先点击“扫码登录”，完成登录后重新解析。")
        except Exception as e:
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(760, 580)
        self.setMinimumSize(650, 500)
        root = QWidget(); self.setCentralWidget(root)
        layout = QVBoxLayout(root); layout.setSpacing(12)
        title = QLabel("中国移动云盘直链解析器")
        title.setStyleSheet("font-size:22px;font-weight:700")
        subtitle = QLabel("扫码登录后，解析分享文件的 CDN 下载直链；本程序只解析和复制，不下载文件。")
        subtitle.setStyleSheet("color:#666")
        layout.addWidget(title); layout.addWidget(subtitle)
        group = QGroupBox("分享信息")
        form = QFormLayout(group)
        self.link = QTextEdit(); self.link.setPlaceholderText("粘贴 https://yun.139.com/shareweb/#/w/i/... 分享链接")
        self.link.setMaximumHeight(90)
        self.pwd = QLineEdit(); self.pwd.setPlaceholderText("没有提取码可留空")
        form.addRow("分享链接：", self.link); form.addRow("提取码：", self.pwd)
        layout.addWidget(group)
        buttons = QHBoxLayout()
        self.login_btn = QPushButton("扫码登录")
        self.parse_btn = QPushButton("解析下载直链")
        self.copy_btn = QPushButton("复制下载地址")
        self.copy_btn.setEnabled(False)
        self.login_btn.clicked.connect(self.login)
        self.parse_btn.clicked.connect(self.parse)
        self.copy_btn.clicked.connect(self.copy_url)
        buttons.addWidget(self.login_btn); buttons.addWidget(self.parse_btn); buttons.addWidget(self.copy_btn)
        layout.addLayout(buttons)
        self.file_label = QLabel("文件：尚未解析")
        layout.addWidget(self.file_label)
        layout.addWidget(QLabel("解析结果 / 状态："))
        self.output = QTextEdit(); self.output.setReadOnly(True)
        self.output.setPlaceholderText("解析结果会显示在这里……")
        layout.addWidget(self.output, 1)
        foot = QLabel("安全提示：登录 Cookie 仅保存在当前 Windows 用户目录；不要把 cookies.json 分享给他人。下载直链通常有时效，建议获取后立即使用。")
        foot.setWordWrap(True); foot.setStyleSheet("color:#777;font-size:11px")
        layout.addWidget(foot)
        self.direct_url = ""
        self.login_worker = None; self.parse_worker = None
        self.load_example()

    
    def load_example(self):
        self.link.clear()
        self.output.setPlainText("请粘贴中国移动云盘分享链接，然后点击解析。")


    def login(self):
        self.login_btn.setEnabled(False)
        self.output.append("\n开始扫码登录……")
        self.login_worker = LoginWorker()
        self.login_worker.log.connect(self.output.append)
        self.login_worker.done.connect(self.login_done)
        self.login_worker.start()

    def login_done(self, ok, message):
        self.login_btn.setEnabled(True)
        self.output.append(("✓ " if ok else "✗ ") + message)
        if not ok:
            QMessageBox.warning(self, "扫码登录", message)

    def parse(self):
        self.parse_btn.setEnabled(False); self.copy_btn.setEnabled(False)
        self.direct_url = ""; self.file_label.setText("文件：正在解析……")
        self.output.append("\n开始解析……")
        self.parse_worker = ParseWorker(self.link.toPlainText(), self.pwd.text())
        self.parse_worker.log.connect(self.output.append)
        self.parse_worker.success.connect(self.parse_success)
        self.parse_worker.failed.connect(self.parse_failed)
        self.parse_worker.start()

    def parse_success(self, filename, url):
        self.parse_btn.setEnabled(True); self.direct_url = url
        self.file_label.setText(f"文件：{filename}")
        self.output.append("✓ 解析成功，下载直链如下：\n" + url)
        self.copy_btn.setEnabled(True)

    def parse_failed(self, message):
        self.parse_btn.setEnabled(True); self.file_label.setText("文件：解析失败")
        self.output.append("✗ 解析失败：\n" + message)
        QMessageBox.warning(self, "解析失败", message)

    def copy_url(self):
        if self.direct_url:
            QApplication.clipboard().setText(self.direct_url)
            self.output.append("\n✓ 下载地址已复制到剪贴板。")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow(); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
