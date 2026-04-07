import sys
import os

# Ensure the root dir is in the load path since dashboard is run in an isolated process
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nicegui import ui
from dashboard.app import DashboardApp

def start_dashboard():
    dashboard = DashboardApp()
    
    # 2-second UI polling tick decoupled entirely from the core hyper_bot hot-path limits
    ui.timer(2.0, dashboard.update_data)
    
    # Deploy visually and expose to the AWS internal IP logic mapping
    ui.run(title="Hyperbot Control Dashboard", port=8080, host='0.0.0.0', reload=False)

if __name__ in {"__main__", "__mp_main__"}:
    start_dashboard()
