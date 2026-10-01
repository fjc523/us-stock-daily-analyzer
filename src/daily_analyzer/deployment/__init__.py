"""launchd 调度管理和本机环境自检。"""

from daily_analyzer.deployment.doctor import doctor
from daily_analyzer.deployment.schedule import (
    LABEL,
    PLIST_NAME,
    machine_timezone,
    render_plist,
    schedule_install,
    schedule_status,
    schedule_trigger_times,
    schedule_uninstall,
)

__all__ = [
    "LABEL",
    "PLIST_NAME",
    "doctor",
    "machine_timezone",
    "render_plist",
    "schedule_install",
    "schedule_status",
    "schedule_trigger_times",
    "schedule_uninstall",
]
