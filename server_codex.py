"""Owner-initiated official Codex device login on this private server.

Only the temporary device code is returned to the authenticated owner. OAuth
credentials are managed exclusively by Codex; they never pass through the API.
"""
from __future__ import annotations
import os
from pathlib import Path
import re
import subprocess
import threading
import time

from codex_backend import command_prefix, runtime_environment

DEVICE_URL = 'https://auth.openai.com/codex/device'
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def server_mode():
    return os.getenv('TRADESCOUT_CODEX_MODE', 'local') == 'server'


def prepare_home():
    path = Path(runtime_environment()['CODEX_HOME'])
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def cli_args():
    return command_prefix() + ['-c', 'cli_auth_credentials_store="file"', '-c', 'forced_login_method="chatgpt"']


def subscription_login():
    try:
        response = subprocess.run(cli_args() + ['login', 'status'], env=runtime_environment(),
                                  capture_output=True, text=True, timeout=12)
        message = (response.stdout + response.stderr).lower()
        return response.returncode == 0 and 'chatgpt' in message and 'api key' not in message
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return False


def parse_device_prompt(output):
    plain = ANSI.sub('', output)
    # Accept only the official fixed verification URL and the code following
    # the CLI's device-code instruction, never arbitrary diagnostic content.
    if DEVICE_URL not in plain:
        return None
    match = re.search(r'Enter this one-time code[^\n]*\n\s*([A-Z0-9]{3,8}(?:-[A-Z0-9]{3,8})+)\s*(?:\n|$)', plain)
    return match.group(1) if match else None


class DeviceLogin:
    def __init__(self):
        self.lock = threading.RLock()
        self.process = None
        self.state = 'idle'
        self.code = None
        self.deadline = 0
        self.generation = 0
        self.cached_login = False
        self.checked_at = 0

    def authenticated(self, force=False):
        with self.lock:
            if force or time.monotonic() - self.checked_at > 5:
                self.cached_login = subscription_login()
                self.checked_at = time.monotonic()
            return self.cached_login

    def snapshot(self):
        with self.lock:
            signed_in = self.authenticated()
            state = 'authenticated' if signed_in else self.state
            messages = {
                'idle': '尚未登录服务器 Codex。',
                'starting': '正在向 OpenAI 请求设备码……',
                'pending': '请在 OpenAI 官方页面输入设备码并授权。',
                'authenticated': '已使用 ChatGPT 账号登录；请测试实际 AI 连接。',
                'error': '设备登录失败。请确认账号允许设备码登录，或稍后重试；服务器可能无法访问 OpenAI。',
                'expired': '设备码已过期，请重新发起登录。',
            }
            return {'state': state, 'authenticated': signed_in, 'message': messages.get(state, ''),
                    'verification_url': DEVICE_URL if state == 'pending' else None,
                    'user_code': self.code if state == 'pending' else None,
                    'expires_in': max(0, int(self.deadline-time.time())) if state == 'pending' else 0}

    def start(self):
        with self.lock:
            if self.authenticated(force=True):
                return self.snapshot()
            if self.process and self.process.poll() is None:
                return self.snapshot()
            prepare_home()
            self.generation += 1
            generation = self.generation
            self.code = None
            self.state = 'starting'
            self.deadline = time.time()+900
            try:
                self.process = subprocess.Popen(cli_args() + ['login', '--device-auth'],
                    env=runtime_environment(), stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace', bufsize=1)
            except (OSError, RuntimeError):
                self.state = 'error'
                return self.snapshot()
            process = self.process
            threading.Thread(target=self._read, args=(process,generation), daemon=True).start()
            threading.Thread(target=self._timeout, args=(process,generation), daemon=True).start()
            return self.snapshot()

    def _read(self, process, generation):
        output = ''
        for line in process.stdout:
            output = (output+line)[-12000:]
            code = parse_device_prompt(output)
            if code:
                with self.lock:
                    if generation == self.generation:
                        self.code = code
                        self.state = 'pending'
        process.wait()
        with self.lock:
            if generation != self.generation:
                return
            self.code = None
            if self.state != 'expired':
                self.state = 'authenticated' if self.authenticated(force=True) else 'error'
        process.stdout.close()

    def _timeout(self, process, generation):
        try:
            process.wait(timeout=900)
        except subprocess.TimeoutExpired:
            with self.lock:
                if generation == self.generation:
                    self.state = 'expired'
                    self.code = None
            process.kill()

    def logout(self):
        with self.lock:
            self.generation += 1
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            try:
                result = subprocess.run(cli_args()+['logout'], env=runtime_environment(), capture_output=True, timeout=15)
                if result.returncode:
                    raise RuntimeError('退出 Codex 失败，请稍后重试。')
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError('退出 Codex 失败，请稍后重试。') from exc
            self.state, self.code = 'idle', None
            self.cached_login, self.checked_at = False, time.monotonic()
            return self.snapshot()

    def stop_login(self):
        with self.lock:
            self.generation += 1
            if self.process and self.process.poll() is None:
                self.process.terminate()


login = DeviceLogin()
