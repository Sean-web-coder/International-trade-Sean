"""Call the locally authenticated Codex CLI without a shell or API-key copy."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def command_prefix() -> list[str]:
    executable = shutil.which(os.getenv("CODEX_BIN", "codex"))
    if not executable:
        raise RuntimeError("未找到 Codex CLI。请先安装 Node.js LTS，运行 npm install -g @openai/codex，再运行 codex login。")
    # npm on Windows installs a .cmd wrapper. Invoke its JS entry directly so
    # prompts never pass through cmd.exe and paths containing spaces work.
    if Path(executable).suffix.lower() in {".cmd", ".bat", ".ps1"}:
        entry = Path(executable).parent / "node_modules/@openai/codex/bin/codex.js"
        node = shutil.which("node")
        if not entry.is_file() or not node:
            raise RuntimeError("无法定位 npm 安装的 Codex。请重新运行 npm install -g @openai/codex。")
        return [node, str(entry)]
    return [executable]


def connection_status() -> str:
    prefix = command_prefix()
    try:
        version = subprocess.run(prefix + ["--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
        status = subprocess.run(prefix + ["login", "status"], capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("无法启动 Codex CLI，请在终端检查 codex --version。") from exc
    if version.returncode or status.returncode:
        raise RuntimeError("Codex 尚未就绪或登录。请在运行本应用的电脑终端执行 codex login。")
    return f"{version.stdout.strip()} · 已登录（模型连通性需进一步测试）"


def invoke_codex(instructions: str, task: str, model: str = "", use_search: bool = True) -> str:
    prefix = command_prefix()
    timeout = int(os.getenv("CODEX_TIMEOUT_SECONDS", "240"))
    with tempfile.TemporaryDirectory(prefix="tradescout-") as directory:
        output = Path(directory) / "response.txt"
        command = prefix + [
            "-a", "never", "-c", 'web_search="live"' if use_search else 'web_search="disabled"',
            "-c", "features.shell_tool=false",
            "exec", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
            "--color", "never", "--cd", directory, "--output-last-message", str(output),
        ]
        if model.strip():
            command += ["--model", model.strip()]
        command += ["-"]
        prompt = instructions + "\nDo not run commands, read local files, or use MCP integrations. Use only web search when research is requested. Return only the requested JSON.\n\nTask data:\n" + task
        try:
            result = subprocess.run(command, input=prompt, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Codex 请求超过 {timeout} 秒。请缩小查询范围后重试。") from exc
        except OSError as exc:
            raise RuntimeError("Codex 进程启动失败，请检查本机安装。") from exc
        if result.returncode:
            # Do not expose CLI diagnostics: they may contain account/config data.
            raise RuntimeError(f"Codex 调用失败（退出码 {result.returncode}）。请在本机终端运行 codex，检查登录、额度、网络和模型权限；Windows 如遇沙箱问题可使用 WSL。")
        if not output.is_file() or not output.read_text(encoding="utf-8").strip():
            raise RuntimeError("Codex 未返回结果，请检查模型权限或稍后重试。")
        return output.read_text(encoding="utf-8")
