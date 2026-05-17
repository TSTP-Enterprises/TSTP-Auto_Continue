import uuid
from dataclasses import asdict, dataclass, field
from typing import Dict, List


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class TargetSpec:
    id: str = field(default_factory=new_id)
    name: str = "Unnamed Target"
    target_type: str = "image"  # image or text
    value: str = ""  # file path or phrase
    threshold: float = 0.88
    enabled: bool = True

    @staticmethod
    def from_dict(data: Dict) -> "TargetSpec":
        return TargetSpec(
            id=str(data.get("id") or new_id()),
            name=str(data.get("name", "Unnamed Target")),
            target_type=str(data.get("target_type", "image")),
            value=str(data.get("value", "")),
            threshold=float(data.get("threshold", 0.88)),
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> Dict:
        return asdict(self)

    def label(self) -> str:
        state = "ON" if self.enabled else "OFF"
        return f"[{state}] {self.name} ({self.target_type})"


@dataclass
class AppConfig:
    scan_interval_value: float = 10.0
    scan_interval_unit: str = "ms"
    sequence_reset_value: float = 2.0
    sequence_reset_unit: str = "s"
    mode: str = "parallel"  # parallel or sequence
    selected_monitors: List[int] = field(default_factory=lambda: [-1])
    max_clicks_per_cycle: int = 20
    show_mouse_movement: bool = False
    mouse_move_duration_value: float = 50.0
    mouse_move_duration_unit: str = "ms"
    notifications_enabled: bool = True
    minimize_to_tray_on_close: bool = True
    minimize_on_start: bool = False
    emergency_hotkey: str = "<esc>"
    start_hotkey: str = "<ctrl>+<alt>+s"
    prompt_restart_after_emergency_stop: bool = True
    click_targets: List[TargetSpec] = field(default_factory=list)
    stop_targets: List[TargetSpec] = field(default_factory=list)
    sequence_order: List[str] = field(default_factory=list)
    ocr_path: str = ""

    @staticmethod
    def from_dict(data: Dict) -> "AppConfig":
        click_targets = [TargetSpec.from_dict(t) for t in data.get("click_targets", []) if isinstance(t, dict)]
        stop_targets = [TargetSpec.from_dict(t) for t in data.get("stop_targets", []) if isinstance(t, dict)]
        return AppConfig(
            scan_interval_value=float(data.get("scan_interval_value", 10.0)),
            scan_interval_unit=str(data.get("scan_interval_unit", "ms")),
            sequence_reset_value=float(data.get("sequence_reset_value", 2.0)),
            sequence_reset_unit=str(data.get("sequence_reset_unit", "s")),
            mode=str(data.get("mode", "parallel")),
            selected_monitors=list(data.get("selected_monitors", [-1])),
            max_clicks_per_cycle=int(data.get("max_clicks_per_cycle", 20)),
            show_mouse_movement=bool(data.get("show_mouse_movement", False)),
            mouse_move_duration_value=float(data.get("mouse_move_duration_value", 50.0)),
            mouse_move_duration_unit=str(data.get("mouse_move_duration_unit", "ms")),
            notifications_enabled=bool(data.get("notifications_enabled", True)),
            minimize_to_tray_on_close=bool(data.get("minimize_to_tray_on_close", True)),
            minimize_on_start=bool(data.get("minimize_on_start", False)),
            emergency_hotkey=str(data.get("emergency_hotkey", "<esc>")),
            start_hotkey=str(data.get("start_hotkey", "<ctrl>+<alt>+s")),
            prompt_restart_after_emergency_stop=bool(
                data.get("prompt_restart_after_emergency_stop", True)
            ),
            click_targets=click_targets,
            stop_targets=stop_targets,
            sequence_order=list(data.get("sequence_order", [t.id for t in click_targets])),
            ocr_path=str(data.get("ocr_path", "")),
        )

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["click_targets"] = [target.to_dict() for target in self.click_targets]
        data["stop_targets"] = [target.to_dict() for target in self.stop_targets]
        return data

