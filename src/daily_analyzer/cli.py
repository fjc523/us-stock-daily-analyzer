"""本地美股每日分析器命令行入口。"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from daily_analyzer.config import SUPPORTED_REASONING_EFFORTS


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

    consistency_parser = commands.add_parser('consistency', help='仅显式测试：重跑保存输入的一致性')
    consistency_parser.add_argument('--run-id', required=True)
    consistency_parser.add_argument('--repeats', type=int, default=2)
    consistency_parser.add_argument('--from', dest='from_stage', choices=('debate', 'analysts'), default='debate')
    consistency_parser.add_argument('--tickers', help='仅测试指定保存标的，逗号分隔')
    consistency_parser.add_argument('--test-mode', action='store_true', help='显式允许重复测试；生产默认关闭')

    commands.add_parser("settle", help="回填并结算独立评估窗口")
    evaluate_parser = commands.add_parser("evaluate", help="生成三层评级客观评估报告")
    evaluate_parser.add_argument("--since", metavar="YYYY-MM-DD")
    evaluate_parser.add_argument("--window", type=int, choices=(5, 10, 20), default=5)
    evaluate_parser.add_argument("--layer", choices=("rm", "trader", "pm", "all"), default="all")

    commands.add_parser("serve", help="启动仅本机的报告与订阅管理")
    viewer_parser = commands.add_parser("viewer", help="管理本机查看器服务")
    viewer_parser.add_argument("viewer_action", choices=("install", "uninstall", "status"))
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


def _run_analysis(root: Path, args: argparse.Namespace):
    from daily_analyzer.runner import run_analysis

    return run_analysis(
        root,
        date_value=args.date,
        tickers=args.tickers,
        force=args.force,
        scheduled=args.scheduled,
        model=args.model,
        effort=args.effort,
    )


def _build_site(root: Path):
    from daily_analyzer.site import build_site

    return build_site(root)


def _doctor(root: Path, ping: bool):
    from daily_analyzer.deployment import doctor

    return doctor(root, ping=ping)


def _schedule(root: Path, action: str):
    from daily_analyzer.deployment import (
        schedule_install,
        schedule_status,
        schedule_uninstall,
    )

    operations = {
        "install": schedule_install,
        "uninstall": schedule_uninstall,
        "status": schedule_status,
    }
    return operations[action](root)


def _print_mapping(title: str, result: Any) -> None:
    if isinstance(result, dict):
        for key, value in result.items():
            print(f"{title}{key}：{value}")
    else:
        print(f"{title}{result}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path.cwd()
    if args.command == "run":
        outcome = _run_analysis(root, args)
        stream = sys.stdout if outcome.exit_code == 0 else sys.stderr
        print(outcome.message, file=stream)
        return outcome.exit_code

    if args.command == 'consistency':
        from daily_analyzer.evaluation.consistency import run_consistency
        try:
            result = run_consistency(root, args.run_id, repeats=args.repeats, from_stage=args.from_stage,
                test_mode=args.test_mode, symbols=args.tickers.split(',') if args.tickers else None)
            _print_mapping('一致性测试 ', result)
            return 0
        except (ValueError, OSError) as exc:
            print(f'一致性测试失败：{exc}', file=sys.stderr)
            return 2

    if args.command in {"settle", "evaluate"}:
        try:
            if args.command == "settle":
                from daily_analyzer.evaluation import settle
                result = settle(root)
            else:
                from daily_analyzer.evaluation.report import evaluate
                result = evaluate(root, since=args.since, window=args.window, layer=args.layer)
            _print_mapping("评估 ", result)
            return 0
        except (ValueError, OSError) as exc:
            print(f"评估失败：{exc}", file=sys.stderr)
            return 2

    if args.command == "build-site":
        result = _build_site(root)
        if result.get("ok"):
            print(f"站点已生成：{result.get('site_path')}")
            return 0
        print(f"站点构建失败：{result.get('error') or '未知错误'}", file=sys.stderr)
        return 1

    if args.command == "doctor":
        result = _doctor(root, ping=args.ping)
        for check in result.get("checks", []):
            print(f"[{check.get('status', 'info')}] {check.get('name')}: {check.get('detail')}")
        print(result.get("summary", "自检完成"))
        return int(result.get("exit_code", 0 if result.get("ok") else 1))

    if args.command == "serve":
        from daily_analyzer.viewer import serve
        try:
            serve(root)
        except OSError as exc:
            print(f"查看器启动失败：{exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "viewer":
        from daily_analyzer.deployment.viewer import viewer_action
        result = viewer_action(root, args.viewer_action)
        _print_mapping("查看器 ", result)
        return 0 if result.get("ok") else 1

    result = _schedule(root, args.schedule_action)
    if result.get("ok"):
        action_text = {
            "install": "定时任务已安装",
            "uninstall": "定时任务已卸载",
            "status": "定时任务状态",
        }[args.schedule_action]
        print(action_text)
        _print_mapping("  ", result)
        return 0
    print(f"定时任务操作失败：{result.get('error') or '未知错误'}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
