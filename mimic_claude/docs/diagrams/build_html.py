import base64
import os
from datetime import datetime

output_dir = r"C:\Users\Loser\Desktop\-\tamalabo\mimic3\docs\diagrams"

diagrams = [
    ("mimic3_architecture",      "Mimic3 System Architecture (Component Diagram)"),
    ("dual_mode_sequence",       "DualModelOrchestrator - Thinker/Actor Sequence"),
    ("workflow_graph_state",     "WorkflowGraph - PlanStep State Transition"),
    ("react_loop",               "InteractiveOrchestrator - ReAct Loop"),
    ("class_diagram",            "Mimic3 Class Diagram"),
]

html_rows = []
for name, title in diagrams:
    png_path = os.path.join(output_dir, f"{name}.png")
    with open(png_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    data_uri = f"data:image/png;base64,{b64}"
    print(f"Encoded: {name} ({len(b64)} chars)")

    row = f"""    <div class="diagram">
        <h2>{title}</h2>
        <img src="{data_uri}" alt="{name}" />
        <p class="download"><a href="{data_uri}" download="{name}.png">Download PNG</a></p>
    </div>"""
    html_rows.append(row)

diagrams_html = "\n".join(html_rows)
date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mimic3 Architecture Diagrams</title>
<style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
        font-family: "Segoe UI", "Hiragino Sans", sans-serif;
        background: #1a1a2e;
        color: #e0e0e0;
        padding: 20px;
    }}
    h1 {{
        text-align: center;
        color: #00d4ff;
        font-size: 2em;
        margin-bottom: 10px;
    }}
    .subtitle {{
        text-align: center;
        color: #888;
        margin-bottom: 40px;
        font-size: 0.9em;
    }}
    .diagram {{
        background: #16213e;
        border-radius: 12px;
        padding: 30px;
        margin-bottom: 40px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        border: 1px solid #0f3460;
    }}
    .diagram h2 {{
        color: #00d4ff;
        margin-bottom: 20px;
        font-size: 1.3em;
        border-bottom: 1px solid #0f3460;
        padding-bottom: 10px;
    }}
    .diagram img {{
        width: 100%;
        max-width: 1200px;
        height: auto;
        display: block;
        margin: 0 auto;
        border-radius: 8px;
        background: #fafafa;
    }}
    .download {{
        text-align: right;
        margin-top: 15px;
    }}
    .download a {{
        color: #00d4ff;
        text-decoration: none;
        font-size: 0.85em;
    }}
    .download a:hover {{ text-decoration: underline; }}
    .footer {{
        text-align: center;
        color: #555;
        margin-top: 40px;
        font-size: 0.8em;
    }}
</style>
</head>
<body>
<h1>Mimic3 Architecture Diagrams</h1>
<p class="subtitle">PlantUML to PNG | Generated: {date_str}</p>

{diagrams_html}

<div class="footer">
    Generated from ARCHITECTURE.puml | Powered by plantuml.com
</div>
</body>
</html>"""

html_path = os.path.join(output_dir, "architecture.html")
with open(html_path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"\nHTML saved: {html_path} ({os.path.getsize(html_path)} bytes)")
