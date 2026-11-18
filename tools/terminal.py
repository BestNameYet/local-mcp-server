"""
tools/terminal.py — Bash Terminal Emulator & Runtime Execution Environment.

Provides a terminal tool for autonomous agents to:
- Execute shell and unix commands (git, python, pytest, ls, cat, grep, etc.).
- Use GitHub as the project filesystem and interact directly with git.
- Operate within the project repository as their workspace runtime environment.
- Automatically receive unread channel messages piggybacked onto terminal output.
"""

import glob
import os
from pathlib import Path
import subprocess
from typing import Any, Optional

from tools.channel import format_with_inbox, get_caller_agent_id

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
MAX_OUTPUT_LENGTH = 50_000


def find_shell() -> tuple[str, list[str]]:
    """Locate the best bash/sh executable and required PATH directories on Windows."""
    # 1. Check for bundled Git/Bash in GitHub Desktop
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        pattern = os.path.join(local_app_data, "GitHubDesktop", "app-*", "resources", "app", "git")
        for git_root in sorted(glob.glob(pattern), reverse=True):
            sh_path = os.path.join(git_root, "usr", "bin", "sh.exe")
            if os.path.isfile(sh_path):
                cmd_dir = os.path.join(git_root, "cmd")
                usr_dir = os.path.join(git_root, "usr", "bin")
                return sh_path, [cmd_dir, usr_dir]

    # 2. Check for standard Git for Windows
    for prog in ["ProgramFiles", "ProgramFiles(x86)"]:
        pf = os.environ.get(prog, "")
        if pf:
            bash_path = os.path.join(pf, "Git", "bin", "bash.exe")
            if os.path.isfile(bash_path):
                return bash_path, [
                    os.path.join(pf, "Git", "cmd"),
                    os.path.join(pf, "Git", "usr", "bin"),
                ]
            sh_path = os.path.join(pf, "Git", "usr", "bin", "sh.exe")
            if os.path.isfile(sh_path):
                return sh_path, [
                    os.path.join(pf, "Git", "cmd"),
                    os.path.join(pf, "Git", "usr", "bin"),
                ]

    # 3. Fallback to system powershell if no bash/sh is found
    return "powershell.exe", []


def get_runtime_environment(extra_paths: list[str]) -> dict[str, str]:
    """Build a complete execution environment including venv python and git tools."""
    env = os.environ.copy()

    # Prepend virtualenv Scripts directory so `python` and `pip` use the project venv
    venv_scripts = str(WORKSPACE_DIR / ".venv" / "Scripts")
    path_entries = []
    if os.path.isdir(venv_scripts):
        path_entries.append(venv_scripts)

    path_entries.extend(extra_paths)
    path_entries.append(env.get("PATH", ""))

    env["PATH"] = os.pathsep.join(path_entries)
    env["PYTHONUNBUFFERED"] = "1"
    env["TERM"] = "xterm-256color"

    return env


def execute_bash(
    command: str,
    cwd: Optional[str] = None,
    agent_id: Optional[str] = None,
    timeout: Optional[float] = 60.0,
) -> str:
    """Execute a command in the bash terminal emulator environment.

    Args:
        command: The shell/bash command string to run (e.g. 'git status', 'python test.py').
        cwd: Working directory (relative or absolute). Defaults to the repository workspace root.
             Restricted to stay within the repository boundary for security.
        agent_id: Optional calling agent ID. When provided, any unread messages from your
                  subscribed channels will be automatically attached to this terminal output.
        timeout: Maximum execution timeout in seconds (default 60s, max 90s).

    Returns:
        Formatted terminal output including exit code, stdout, stderr, and piggybacked channel messages.
    """
    clean_command = (command or "").strip()
    if not clean_command:
        return "[Error] Command cannot be empty."

    # Enforce safe timeout under Cloudflare's 100-second proxy limit
    effective_timeout = min(max(float(timeout or 60.0), 1.0), 90.0)

    # Resolve working directory safely within the workspace boundary
    if cwd and cwd.strip():
        resolved_cwd = (WORKSPACE_DIR / cwd.strip()).resolve()
        # Security: restrict to workspace directory to prevent arbitrary traversal
        try:
            if not resolved_cwd.is_relative_to(WORKSPACE_DIR):
                resolved_cwd = WORKSPACE_DIR
        except AttributeError:
            # Python < 3.9 fallback
            if not str(resolved_cwd).startswith(str(WORKSPACE_DIR)):
                resolved_cwd = WORKSPACE_DIR
    else:
        resolved_cwd = WORKSPACE_DIR

    if not resolved_cwd.is_dir():
        resolved_cwd = WORKSPACE_DIR

    shell_exe, extra_paths = find_shell()
    env = get_runtime_environment(extra_paths)

    # Determine execution arguments based on shell type
    if shell_exe.lower().endswith("powershell.exe"):
        args = [shell_exe, "-NoProfile", "-NonInteractive", "-Command", clean_command]
    else:
        # sh.exe or bash.exe
        args = [shell_exe, "-c", clean_command]

    try:
        proc = subprocess.run(
            args,
            cwd=str(resolved_cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
            errors="replace",
        )
        exit_code = proc.returncode
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

    except subprocess.TimeoutExpired:
        exit_code = 124
        stdout = ""
        stderr = f"[TIMEOUT] Command timed out after {effective_timeout:.1f} seconds."

    except Exception as e:
        exit_code = 1
        stdout = ""
        stderr = f"[EXECUTION ERROR] {str(e)}"

    # Format the terminal output block
    output_parts = [
        f"[Exit Code: {exit_code}]",
        f"[Working Directory: {resolved_cwd}]",
    ]

    if stdout:
        output_parts.append(f"\n--- STDOUT ---\n{stdout}")
    if stderr:
        output_parts.append(f"\n--- STDERR ---\n{stderr}")
    if not stdout and not stderr:
        output_parts.append("\n(No output produced)")

    raw_result = "\n".join(output_parts)

    # Truncate if output exceeds memory/context limits
    if len(raw_result) > MAX_OUTPUT_LENGTH:
        half = MAX_OUTPUT_LENGTH // 2
        omitted = len(raw_result) - MAX_OUTPUT_LENGTH
        raw_result = (
            raw_result[:half]
            + f"\n\n[... Output truncated: {omitted} characters omitted to protect context window ...]\n\n"
            + raw_result[-half:]
        )

    # Piggyback unread channel messages if agent_id is provided
    effective_agent = get_caller_agent_id(agent_id)
    return format_with_inbox(raw_result, agent_id=effective_agent)
