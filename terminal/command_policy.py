"""Deterministic risk classification for assistant-generated Fish commands."""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from terminal.policy import RiskTier, TerminalPolicyError


MAX_COMMAND_CHARS = 4_096
_TIER_OVERRIDE_ENV_VARS = {
    RiskTier.READ_ONLY: "TERMINAL_TIER_1_OVERRIDE",
    RiskTier.MODIFICATION: "TERMINAL_TIER_2_OVERRIDE",
    RiskTier.HIGH_RISK: "TERMINAL_TIER_3_OVERRIDE",
}
_READ_ONLY_COMMANDS = frozenset(
    {
        "cat",
        "df",
        "file",
        "free",
        "grep",
        "head",
        "ls",
        "ps",
        "pwd",
        "stat",
        "tail",
        "uname",
        "uptime",
        "wc",
    }
)
_TIER_THREE_COMMANDS = frozenset(
    {
        "doas",
        "dd",
        "bash",
        "chattr",
        "chmod",
        "chown",
        "dash",
        "fdisk",
        "fish",
        "mkfs",
        "mkfs.btrfs",
        "mkfs.ext2",
        "mkfs.ext3",
        "mkfs.ext4",
        "mkfs.fat",
        "mkfs.ntfs",
        "mkfs.xfs",
        "mkswap",
        "modprobe",
        "mount",
        "nft",
        "parted",
        "passwd",
        "pkexec",
        "poweroff",
        "reboot",
        "rm",
        "rmdir",
        "sfdisk",
        "sh",
        "shred",
        "setfacl",
        "setcap",
        "sysctl",
        "shutdown",
        "su",
        "sudo",
        "swapoff",
        "swapon",
        "unlink",
        "umount",
        "useradd",
        "userdel",
        "usermod",
        "wipefs",
        "zsh",
        "xargs",
        "firewall-cmd",
        "iptables",
    }
)
_SHELL_PUNCTUATION = re.compile(r"[;&|<>`(){}$*?\\'\"\n\r]")
_FISH_COMMAND_KEYWORDS = frozenset(
    {
        "and",
        "begin",
        "case",
        "else",
        "end",
        "for",
        "function",
        "if",
        "not",
        "or",
        "then",
        "while",
    }
)
_COMMAND_WRAPPERS = frozenset({"builtin", "command", "env", "exec", "nohup", "time"})


@dataclass(frozen=True, slots=True)
class CommandAssessment:
    """App-assigned tier plus the direct argv form when Tier 1 is safe."""

    risk_tier: RiskTier
    reason: str
    argv: tuple[str, ...] | None = None


def tier_overrides_from_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[RiskTier, RiskTier]:
    """Read optional source-tier to effective-tier overrides.

    Missing settings preserve the built-in tier. Every configured value must
    be one of the three supported tiers; invalid configuration fails startup.
    """
    values = os.environ if environ is None else environ
    overrides: dict[RiskTier, RiskTier] = {}
    for source_tier, variable in _TIER_OVERRIDE_ENV_VARS.items():
        raw_value = values.get(variable)
        if raw_value is None:
            overrides[source_tier] = source_tier
            continue
        normalized = raw_value.strip()
        if normalized not in {"1", "2", "3"}:
            raise ValueError(f"{variable} must be 1, 2, or 3.")
        overrides[source_tier] = RiskTier(int(normalized))
    return overrides


def assess_command(command: str) -> CommandAssessment:
    """Classify a complete command request without trusting model metadata.

    Tier 1 is deliberately limited to one simple command from a small
    read-only catalog. Compound Fish syntax, commands outside that catalog,
    and commands the app cannot recognize are Tier 2 and require local
    approval. Known high-risk command names are Tier 3.
    """
    if not isinstance(command, str) or not command.strip():
        raise TerminalPolicyError("A terminal command is required.")
    if len(command) > MAX_COMMAND_CHARS:
        raise TerminalPolicyError("Terminal command exceeds the size limit.")
    if "\x00" in command:
        raise TerminalPolicyError("Terminal command contains a NUL byte.")

    if _contains_tier_three_command(command):
        return CommandAssessment(
            RiskTier.HIGH_RISK,
            "known_high_risk_command",
        )

    if _SHELL_PUNCTUATION.search(command):
        return CommandAssessment(
            RiskTier.MODIFICATION,
            "shell_syntax_requires_approval",
        )

    if any(ord(character) < 32 and character not in "\t" for character in command):
        return CommandAssessment(
            RiskTier.MODIFICATION,
            "control_character_requires_approval",
        )

    try:
        argv = tuple(shlex.split(command, comments=False, posix=True))
    except ValueError:
        return CommandAssessment(
            RiskTier.MODIFICATION,
            "command_syntax_requires_approval",
        )
    if not argv:
        raise TerminalPolicyError("A terminal command is required.")

    command_name = Path(argv[0]).name
    if command_name in _READ_ONLY_COMMANDS and _is_trusted_read_only_executable(
        argv[0], command_name
    ):
        return CommandAssessment(
            RiskTier.READ_ONLY,
            "recognized_read_only_command",
            argv,
        )

    return CommandAssessment(
        RiskTier.MODIFICATION,
        "unrecognized_or_mutating_command_requires_approval",
    )


def _contains_tier_three_command(command: str) -> bool:
    try:
        lexer = shlex.shlex(
            command,
            posix=True,
            punctuation_chars=";&|<>(){}\n\r",
        )
        lexer.whitespace_split = True
        lexer.whitespace = " \t"
        lexer.commenters = ""
        tokens = tuple(lexer)
    except ValueError:
        tokens = ()

    expect_command = True
    for token in tokens:
        if token in {";", "|", "||", "&&", "<", ">", "(", ")", "{", "}", "\n", "\r"}:
            expect_command = True
            continue
        candidate = token.strip()
        if not candidate:
            continue
        if candidate in {"and", "or"}:
            expect_command = True
            continue
        if candidate in _FISH_COMMAND_KEYWORDS:
            expect_command = True
            continue
        if candidate in {"-exec", "-execdir"}:
            expect_command = True
            continue
        if candidate == "-delete":
            return True
        if expect_command and (
            candidate in _COMMAND_WRAPPERS
            or candidate.startswith("-")
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", candidate)
        ):
            continue
        basename = Path(candidate).name.casefold()
        if expect_command and (
            basename in _TIER_THREE_COMMANDS or basename.startswith("mkfs.")
        ):
            return True
        expect_command = False

    return False


def _is_trusted_read_only_executable(command: str, command_name: str) -> bool:
    if command != command_name:
        return False
    resolved = shutil_which(command_name)
    if resolved is None:
        return False
    try:
        resolved_path = Path(resolved).resolve(strict=True)
    except OSError:
        return False
    return (
        resolved_path.parent == Path("/usr/bin")
        and os.access(resolved_path, os.X_OK)
    )


def shutil_which(command_name: str) -> str | None:
    """Resolve only from the fixed system PATH used by the sandbox."""
    for directory in ("/usr/bin", "/bin"):
        candidate = Path(directory, command_name)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None
