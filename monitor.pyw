import time
import subprocess
import psutil
import os
import sys

# Ensure this runs without a console window when using pythonw.exe
# It acts as a silent watcher in the background.

SERVER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")

def is_server_running():
    # Check if python is running server.py
    for p in psutil.process_iter(['name', 'cmdline']):
        try:
            if p.info['name'] in ('python.exe', 'pythonw.exe'):
                cmd = p.info['cmdline']
                if cmd and any("server.py" in arg for arg in cmd) and "--auto-close" in cmd:
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False

def log(msg):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor_log.txt"), "a") as f:
        f.write(f"{time.ctime()}: {msg}\n")

def main():
    log("Monitor started.")
    while True:
        battery = psutil.sensors_battery()
        if battery is not None:
            is_plugged = battery.power_plugged
            running = is_server_running()
            log(f"Battery: {battery.percent}%, Plugged: {is_plugged}, Server Running: {running}")
            
            if is_plugged and not running:
                log("Attempting to spawn server...")
                python_exe = sys.executable.replace("pythonw.exe", "python.exe")
                try:
                    subprocess.Popen(
                        f'start "Black Battery" "{python_exe}" "{SERVER_SCRIPT}" --auto-close',
                        shell=True
                    )
                    log("Server spawn success.")
                except Exception as e:
                    log(f"Spawn error: {e}")
                
        time.sleep(5)

if __name__ == "__main__":
    main()
