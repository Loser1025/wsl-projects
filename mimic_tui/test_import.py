import sys
import os
sys.path.insert(0, '/home/loser/wsl-projects/mimic_tui')
os.chdir('/home/loser/wsl-projects/mimic_tui')

try:
    from agent import OpenRouterAgent
    from tools import ToolRegistry
    print("✓ Agent classes imported successfully")
    
    # Try to create a basic agent instance
    from config import OpenRouterConfig
    config = OpenRouterConfig(api_keys=["test_key"])
    registry = ToolRegistry()
    agent = OpenRouterAgent(config, registry)
    print("✓ OpenRouterAgent instance created successfully")
    
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
