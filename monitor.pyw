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
                if cmd and any("server.py" in arg for arg in cmd):
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False

def main():
    while True:
        battery = psutil.sensors_battery()
        if battery is not None:
            is_plugged = battery.power_plugged
            
            if is_plugged and not is_server_running():
                # Launch the visible dashboard in a new CMD window
                # The 'start' command opens a new independent window
                subprocess.Popen(
                    f'start "Black Battery" "{sys.executable}" "{SERVER_SCRIPT}" --auto-close', 
                    shell=True
                )
                
        time.sleep(5)

if __name__ == "__main__":
    main()
