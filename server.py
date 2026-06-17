"""
Black Battery - Ultra-Precision Cyberpunk Tracker

Features Sub-Percent Interpolation and an advanced HUD.
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime
import threading

import psutil

# Rich imports for premium UI
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, BarColumn, TextColumn
from rich.live import Live
from rich.align import Align
from rich.table import Table
from rich.box import ROUNDED

from ml_engine import ChargingPredictor

# -- Paths -----------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSIONS_FILE = os.path.join(BASE_DIR, "sessions.json")

# -- Config ----------------------------------------------------------
SAMPLE_INTERVAL = 5    # seconds for battery polling
UI_INTERVAL = 0.2      # UI refresh (5Hz for smooth sub-percent ticking)
MAX_SESSIONS = 50

# -- Shared State ---------------------------------------------------
lock = threading.Lock()
predictor = ChargingPredictor()

state = {
    "battery_level": 0,
    "is_charging": False,
    "session_start_time": None,
    "session_start_level": 0,
    "current_session": [],
    "prev_level": None,
    "level_first_seen_elapsed": None,
    "transitions": [],
    "charging_speed": 0.0,
    "current_rate_mpp": None,
    "sessions": [],
    "last_event": None,
}

console = Console()

# ====================================================================
# SPARKLINE GENERATOR
# ====================================================================

def generate_sparkline(data, width=20):
    """Generates an ASCII sparkline from a list of floats."""
    if not data:
        return "[dim]No data yet...[/]"
    
    ticks = " ▂▃▄▅▆▇█"
    
    # Pad or truncate to width
    if len(data) < width:
        padded = [0.0] * (width - len(data)) + data
    else:
        padded = data[-width:]
        
    valid = [x for x in data if x > 0]
    if not valid:
        return "[dim]" + " "*width + "[/]"
        
    vmin, vmax = min(valid), max(valid)
    if vmax == vmin:
        return "[#d97757]" + "▄" * width + "[/]"
        
    line = ""
    for v in padded:
        if v <= 0:
            line += " "
        else:
            idx = int((v - vmin) / (vmax - vmin) * 7)
            idx = max(0, min(7, idx))
            line += ticks[idx]
            
    return f"[#d97757]{line}[/]"

# ====================================================================
# PREMIUM TERMINAL UI (CYBERPUNK HUD)
# ====================================================================

def generate_layout():
    """Build the Rich UI layout dynamically based on current state."""
    with lock:
        level = state["battery_level"]
        is_charging = state["is_charging"]
        speed = state["charging_speed"]
        start_time = state["session_start_time"]
        n_transitions = len(state["transitions"])
        session_data = state["current_session"]
        rate_mpp = state["current_rate_mpp"]
        level_first_seen = state["level_first_seen_elapsed"]
        last_event = state["last_event"]
        
        # Gather recent speed history for sparkline
        history = [t["rate"] for t in state["transitions"]]
        # Invert rate (min/%) to speed (%/min) for graph
        speed_history = [(1.0/r if r > 0 else 0) for r in history]

    elapsed_min = 0
    start_level = 0
    if start_time:
        elapsed_min = (time.time() * 1000 - start_time) / 60000.0
    if session_data:
        start_level = session_data[0]["level"]

    # --- SUB-PERCENT INTERPOLATION ENGINE ---
    interpolated_level = float(level)
    if is_charging and rate_mpp and level_first_seen is not None and rate_mpp > 0:
        time_since_tick = elapsed_min - level_first_seen
        fractional_progress = time_since_tick / rate_mpp
        # Cap at 0.99 to prevent overshooting before the OS tick
        fractional_progress = max(0.0, min(0.99, fractional_progress))
        interpolated_level = level + fractional_progress

    pred_80 = {"minutes": None, "confidence": 0, "method": "waiting"}
    pred_90 = {"minutes": None, "confidence": 0, "method": "waiting"}

    if is_charging and len(session_data) >= 1:
        pred_80 = predictor.predict(level, 80, rate_mpp, n_transitions, elapsed_min, start_level)
        pred_90 = predictor.predict(level, 90, rate_mpp, n_transitions, elapsed_min, start_level)

    pred_info = predictor.get_info()

    # --- Setup Layout Grid ---
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=3)
    )
    layout["main"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=1)
    )
    layout["left"].split_column(
        Layout(name="battery", ratio=2),
        Layout(name="stats", ratio=3)
    )
    layout["right"].split_column(
        Layout(name="pred80", ratio=1),
        Layout(name="pred90", ratio=1)
    )

    # --- Header ---
    header_text = Text("◆ Black Battery", style="bold #d97757", justify="center")
    header_text.append("\nHigh-precision rate tracking active", style="dim white")
    layout["header"].update(Panel(header_text, style="#d97757", box=ROUNDED))

    # --- Battery Panel ---
    progress = Progress(
        TextColumn("[bold #d97757]{task.percentage:>5.2f}%"),
        BarColumn(bar_width=None, complete_style="#d97757" if level > 20 else "#d95757", finished_style="#d97757"),
        expand=True
    )
    task_id = progress.add_task("battery", total=100, completed=interpolated_level)
    
    battery_status = Text("\nStatus: ", style="bold #808080")
    if is_charging:
        battery_status.append("Charging", style="bold white")
    else:
        battery_status.append("Discharging", style="bold #808080")

    battery_group = Align.center(progress, vertical="middle")
    
    battery_panel = Panel(
        battery_group,
        title="[bold white]Battery Level",
        border_style="#d97757" if is_charging else "#808080",
        subtitle=battery_status,
        box=ROUNDED
    )
    layout["battery"].update(battery_panel)

    # --- Stats Panel ---
    stats_table = Table.grid(padding=(1, 2), expand=True)
    stats_table.add_column(justify="left", style="bold #808080")
    stats_table.add_column(justify="right", style="bold white")
    
    m = int(elapsed_min)
    s = int((elapsed_min % 1) * 60)
    
    stats_table.add_row("Elapsed Time:", f"{m:02d}:{s:02d}")
    
    if is_charging:
        stats_table.add_row("Charge Rate:", f"{speed:.2f} %/min")
        rate_str = f"{rate_mpp:.2f} min/%" if rate_mpp else "[dim white]Calibrating...[/]"
        stats_table.add_row("Pace:", rate_str)
        
        spark = generate_sparkline(speed_history, width=16)
        stats_table.add_row("Speed Curve:", spark)
    else:
        stats_table.add_row("Charge Rate:", "N/A")
        stats_table.add_row("Pace:", "N/A")
        stats_table.add_row("Speed Curve:", "N/A")

    stats_panel = Panel(Align.center(stats_table, vertical="middle"), title="[bold white]Telemetry", border_style="#808080", box=ROUNDED)
    layout["stats"].update(stats_panel)

    # --- Helper for Predictions ---
    def make_pred_panel(pred_data, target, current_level, color):
        if current_level >= target:
            content = Text("Target reached", style="bold #d97757", justify="center")
            return Panel(Align.center(content, vertical="middle"), title=f"[bold white]Target {target}%", border_style="#d97757", box=ROUNDED)
            
        if not is_charging:
            content = Text("Waiting for charger...", style="dim #808080", justify="center")
            return Panel(Align.center(content, vertical="middle"), title=f"[bold white]Target {target}%", border_style="#5c5c5c", box=ROUNDED)

        if pred_data["minutes"] is None:
            content = Text("Gathering calibration data...", style="dim white", justify="center")
            return Panel(Align.center(content, vertical="middle"), title=f"[bold white]Target {target}%", border_style="#808080", box=ROUNDED)

        mins = pred_data["minutes"]
        h, m = int(mins // 60), int(mins % 60)
        s = int((mins % 1) * 60)
        eta_time = datetime.fromtimestamp(time.time() + mins * 60).strftime("%I:%M %p")
        time_str = f"{h}h {m:02d}m {s:02d}s" if h > 0 else f"{m:02d}m {s:02d}s"
        conf_pct = int(pred_data["confidence"] * 100)

        t = Table.grid(padding=(0, 2), expand=True)
        t.add_column(justify="left", style="bold #808080")
        t.add_column(justify="right", style=f"bold {color}")
        t.add_row("Time remaining:", time_str)
        t.add_row("ETA:", eta_time)
        t.add_row("", "")
        
        method_style = "#d97757" if "Calibrated" in pred_data['method'] else "white"
        t.add_row("Method:", f"[{method_style}]{pred_data['method']}[/]")
        t.add_row("Confidence:", f"{conf_pct}%")

        return Panel(Align.center(t, vertical="middle"), title=f"[bold white]Target {target}%", border_style=color, box=ROUNDED)

    # --- Predictions ---
    layout["pred80"].update(make_pred_panel(pred_80, 80, level, "#808080"))
    layout["pred90"].update(make_pred_panel(pred_90, 90, level, "#808080"))

    # --- Footer ---
    ml_status = f"{pred_info['sessions_learned']} sessions modeled"
    if is_charging:
        ml_status += f"  •  {n_transitions} data points"
    
    footer_text = Text()
    footer_text.append("Intelligence: ", style="bold #808080")
    footer_text.append(ml_status, style="white")
    
    if last_event:
        elapsed_sec = time.time() - (last_event['time'] / 1000.0)
        if elapsed_sec < 5:
            footer_text.append(f"  •  {last_event['message']}", style="bold #d97757")

    layout["footer"].update(Panel(footer_text, border_style="#5c5c5c", subtitle="[dim #808080]Press CTRL+C to quit", box=ROUNDED))

    return layout

# ====================================================================
# CORE LOGIC
# ====================================================================

def _start_session(level):
    with lock:
        if state["current_session"] and len(state["transitions"]) >= 2:
            _save_session_to_history()

        now = time.time() * 1000
        state["session_start_time"] = now
        state["session_start_level"] = level
        state["current_session"] = []
        state["transitions"] = []
        state["prev_level"] = None
        state["level_first_seen_elapsed"] = None
        state["charging_speed"] = 0.0
        state["current_rate_mpp"] = None
        state["last_event"] = {"message": "Tracking started", "time": now}

    _record_sample(level)


def _end_session():
    with lock:
        transitions = state["transitions"][:]
    
    if len(transitions) >= 2:
        _save_session_to_history()
        predictor.learn_session(transitions)
        with lock:
            state["last_event"] = {"message": f"Session saved ({len(transitions)} points)", "time": time.time() * 1000}
    
    with lock:
        state["current_session"] = []
        state["transitions"] = []
        state["session_start_time"] = None
        state["prev_level"] = None
        state["level_first_seen_elapsed"] = None


def _record_sample(level):
    with lock:
        start = state["session_start_time"]
        if start is None:
            return

        now = time.time() * 1000
        elapsed = (now - start) / 60000.0

        if state["current_session"]:
            last = state["current_session"][-1]
            if abs(elapsed - last["elapsed"]) < 0.05:
                return

        state["current_session"].append({
            "elapsed": round(elapsed, 3),
            "level": level,
            "timestamp": now,
        })

        if state["prev_level"] is None:
            state["prev_level"] = level
            state["level_first_seen_elapsed"] = elapsed
            return

        if level > state["prev_level"]:
            transition_time = elapsed - state["level_first_seen_elapsed"]
            delta_level = level - state["prev_level"]
            rate_mpp = transition_time / delta_level

            if rate_mpp > 0:
                state["transitions"].append({
                    "from_level": state["prev_level"],
                    "to_level": level,
                    "rate": round(rate_mpp, 4),
                    "elapsed": round(elapsed, 3),
                })

            state["prev_level"] = level
            state["level_first_seen_elapsed"] = elapsed
            _update_rate()
            state["last_event"] = {"message": "Speed updated", "time": now}

        elif level < state["prev_level"]:
            state["prev_level"] = level
            state["level_first_seen_elapsed"] = elapsed

        _update_speed()


def _update_rate():
    transitions = state["transitions"]
    if not transitions:
        state["current_rate_mpp"] = None
        return

    recent = transitions[-6:]
    rates = [t["rate"] for t in recent]
    ema = rates[0]
    alpha = 0.4
    for r in rates[1:]:
        ema = alpha * r + (1 - alpha) * ema

    state["current_rate_mpp"] = round(ema, 4)


def _update_speed():
    if state["current_rate_mpp"] and state["current_rate_mpp"] > 0:
        state["charging_speed"] = round(1.0 / state["current_rate_mpp"], 3)
    elif len(state["current_session"]) >= 2:
        data = state["current_session"]
        first = data[0]
        last = data[-1]
        dt = last["elapsed"] - first["elapsed"]
        dl = last["level"] - first["level"]
        if dt > 0 and dl > 0:
            state["charging_speed"] = round(dl / dt, 3)
        else:
            state["charging_speed"] = 0.0
    else:
        state["charging_speed"] = 0.0


def _save_session_to_history():
    session_data = state["current_session"]
    transitions = state["transitions"]
    if len(session_data) < 2: return

    first, last = session_data[0], session_data[-1]
    duration = last["elapsed"]
    dl = last["level"] - first["level"]
    avg_speed = (dl / max(duration, 0.1)) if duration > 0 and dl > 0 else 0

    entry = {
        "id": int(time.time() * 1000),
        "start_time": first["timestamp"],
        "end_time": last["timestamp"],
        "start_level": first["level"],
        "end_level": last["level"],
        "duration": round(duration, 2),
        "samples": len(session_data),
        "transitions": len(transitions),
        "avg_speed": round(avg_speed, 3),
    }
    state["sessions"].append(entry)
    threading.Thread(target=save_sessions, daemon=True).start()


def load_sessions():
    try:
        if os.path.exists(SESSIONS_FILE):
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            with lock:
                state["sessions"] = data
        else:
            with lock: state["sessions"] = []
    except Exception:
        with lock: state["sessions"] = []


def save_sessions():
    try:
        with lock:
            data = state["sessions"][-MAX_SESSIONS:]
            state["sessions"] = data
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


# ====================================================================
# WINDOWS AUTOSTART
# ====================================================================

def setup_autostart():
    try:
        startup_dir = os.path.join(
            os.environ.get("APPDATA", ""),
            "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
        )
        bat_path = os.path.join(startup_dir, "BlackBattery.bat")
        
        bat_content = (
            f'@echo off\n'
            f'start "Black Battery Monitor" "pythonw.exe" "{os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor.pyw")}"\n'
        )
        with open(bat_path, "w") as f:
            f.write(bat_content)
        print(f"[Setup] Autostart enabled via monitor daemon.")
    except Exception as e:
        print(f"[Setup] Autostart failed: {e}")


def remove_autostart():
    try:
        startup_dir = os.path.join(
            os.environ.get("APPDATA", ""),
            "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
        )
        bat_path = os.path.join(startup_dir, "BlackBattery.bat")
        if os.path.exists(bat_path):
            os.remove(bat_path)
            print("[Setup] Autostart removed.")
    except Exception:
        pass


# ====================================================================
# MAIN LOOP
# ====================================================================

def main():
    parser = argparse.ArgumentParser(description="Black Battery - Smart Charging Tracker")
    parser.add_argument("--autostart", action="store_true", help="Run on Windows startup")
    parser.add_argument("--remove-autostart", action="store_true", help="Remove from startup")
    parser.add_argument("--auto-close", action="store_true", help="Automatically exit the script when unplugged")
    args = parser.parse_args()

    if args.autostart:
        setup_autostart()
        return
    if args.remove_autostart:
        remove_autostart()
        return

    battery = psutil.sensors_battery()
    if battery is None:
        console.print("[bold red]No battery detected on this system.[/]")
        return

    load_sessions()

    # Initial state
    with lock:
        state["is_charging"] = battery.power_plugged
        state["battery_level"] = int(round(battery.percent))
    if battery.power_plugged:
        _start_session(state["battery_level"])

    last_poll = time.time()

    try:
        # Start the Rich Live display (UI_INTERVAL = 0.2s for smooth ticking)
        with Live(generate_layout(), refresh_per_second=10, screen=True) as live:
            while True:
                now = time.time()
                
                # --- Poll Battery (every SAMPLE_INTERVAL) ---
                if now - last_poll >= SAMPLE_INTERVAL:
                    last_poll = now
                    battery = psutil.sensors_battery()
                    if battery:
                        level = int(round(battery.percent))
                        plugged = battery.power_plugged

                        with lock:
                            was_charging = state["is_charging"]
                            state["is_charging"] = plugged
                            state["battery_level"] = level

                        if plugged and not was_charging:
                            _start_session(level)
                        elif not plugged and was_charging:
                            _end_session()
                            if args.auto_close:
                                # Stop Live display and exit gracefully
                                live.stop()
                                console.print("[bold #d97757]Charger unplugged. Closing dashboard...[/]")
                                time.sleep(2)
                                sys.exit(0)

                        if plugged:
                            _record_sample(level)

                # --- Update Layout ---
                live.update(generate_layout())
                
                time.sleep(UI_INTERVAL)
                
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
