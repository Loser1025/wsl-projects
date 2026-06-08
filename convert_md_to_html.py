#!/usr/bin/env python3
"""Convert Markdown to HTML using Python's built-in libraries."""

import re
import sys
from pathlib import Path


def markdown_to_html(md_content: str) -> str:
    """Convert basic Markdown to HTML."""
    # Convert headers
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', md_content, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', html, flags=re.MULTILINE)
    
    # Convert bold and italic
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    
    # Convert code blocks
    html = re.sub(r'```([\s\S]+?)```', r'<pre><code>\1</code></pre>', html)
    html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)
    
    # Convert links
    html = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', html)
    
    # Convert lists
    html = re.sub(r'^\* (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    html = re.sub(r'(<li>.+</li>)', r'<ul>\1</ul>', html, flags=re.MULTILINE)
    
    # Convert tables
    html = re.sub(
        r'^\|(.+)\|\n\|(.+)\|\n((?:\|.+\|\n)+)',
        r'<table><thead><tr>\1</tr></thead><tbody>\3</tbody></table>',
        html,
        flags=re.MULTILINE,
    )
    html = re.sub(r'\|', r'</td><td>', html)
    html = re.sub(r'<td>', r'<td>', html)
    html = re.sub(r'^<tr>', r'<tr><td>', html, flags=re.MULTILINE)
    
    # Convert horizontal rules
    html = re.sub(r'^---$', r'<hr>', html, flags=re.MULTILINE)
    
    # Convert paragraphs
    html = re.sub(r'^([^<].+)$', r'<p>\1</p>', html, flags=re.MULTILINE)
    
    # Basic HTML structure
    html_content = html.strip()
    full_html = f"""
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CLI Agent Demo Analysis Report</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f9f9f9;
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #2980b9;
            border-bottom: 1px solid #3498db;
            padding-bottom: 5px;
        }}
        h3 {{
            color: #3498db;
        }}
        pre {{
            background-color: #f0f0f0;
            padding: 10px;
            border-radius: 5px;
            overflow-x: auto;
        }}
        code {{
            background-color: #f0f0f0;
            padding: 2px 5px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }}
        th {{
            background-color: #f2f2f2;
        }}
        tr:nth-child(even) {{
            background-color: #f9f9f9;
        }}
        hr {{
            border: 0;
            height: 1px;
            background: #ddd;
            margin: 20px 0;
        }}
        .container {{
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
    </style>
</head>
<body>
    <div class="container">
        {html_content}
    </div>
</body>
</html>
"""
    return full_html


def main():
    if len(sys.argv) != 2:
        print("Usage: python convert_md_to_html.py <input.md>")
        sys.exit(1)
    
    input_file = Path(sys.argv[1])
    if not input_file.exists():
        print(f"Error: File {input_file} not found.")
        sys.exit(1)
    
    output_file = input_file.with_suffix('.html')
    
    with open(input_file, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    html_content = markdown_to_html(md_content)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"Successfully converted {input_file} to {output_file}")


if __name__ == '__main__':
    main()