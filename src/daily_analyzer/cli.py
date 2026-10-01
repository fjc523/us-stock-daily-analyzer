"""命令行入口。当前只提供可发现的命令骨架。"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from daily_analyzer.config import (
    SUPPORTED_REASONING_EFFORTS,
    ConfigurationError,
    apply_llm_overrides,
    load_settings,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daily-analyzer",
        description="本地美股每日分析器",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run_parser = commands.add_parser("run", help="运行自选清单分析")
    run_parser.add_argument("--date", metavar="YYYY-MM-DD")
    run_parser.add_argument("--tickers", metavar="A,B")
    run_parser.add_argument("--force", action="store_true")
    run_parser.add_argument("--scheduled", action="store_true")
    run_parser.add_argument("--model", help="临时覆盖 deep 与 quick 模型")
    run_parser.add_argument(
        "--effort",
        choices=sorted(SUPPORTED_REASONING_EFFORTS),
        help="临时覆盖 deep 与 quick 推理强度",
    )

    commands.add_parser("build-site", help="根据已有结果重建 HTML 站点")
    doctor_parser = commands.add_parser("doctor", help="检查本机运行环境")
    doctor_parser.add_argument("--ping", action="store_true", help="执行极小模型连通性检查")

    schedule_parser = commands.add_parser("schedule", help="管理 launchd 定时任务")
    schedule_commands = schedule_parser.add_subparsers(
        dest="schedule_action", required=True
    )
    schedule_commands.add_parser("install", help="安装定时任务")
    schedule_commands.add_parser("uninstall", help="卸载定时任务")
    schedule_commands.add_parser("status", help="查询定时任务状态")
    return parser


def _not_implemented(args: argparse.Namespace) -> int:
    if args.command == "schedule":
        operation = f"schedule {args.schedule_action}"
    else:
        operation = args.command
    print(
        f"{operation} 尚未实现；当前阶段只提供命令入口与参数骨架。",
        file=sys.stderr,
    )
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        try:
            settings = load_settings(Path.cwd())
            apply_llm_overrides(settings, model=args.model, effort=args.effort)
        except ConfigurationError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    return _not_implemented(args)


if __name__ == "__main__":
    raise SystemExit(main())
