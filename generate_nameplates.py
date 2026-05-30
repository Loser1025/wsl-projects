import csv

# CSVファイルのパス
CSV_FILE = '/home/loser/wsl-projects/roman_correction_list.csv'
# 出力HTMLファイルのパス
OUTPUT_HTML = '/home/loser/wsl-projects/nameplates.html'

# HTMLのヘッダーとフッター
HTML_HEADER = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nameplates</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f0f0f0;
        }
        .slide {
            width: 800px;
            height: 600px;
            margin: 20px auto;
            background-color: white;
            border: 2px solid #333;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
        }
        .name {
            font-size: 48px;
            font-weight: bold;
            margin-bottom: 20px;
        }
        .roman {
            font-size: 36px;
            color: #555;
        }
    </style>
</head>
<body>
"""

HTML_FOOTER = """
</body>
</html>
"""

# CSVファイルを読み込み、HTMLを生成
def generate_nameplates():
    with open(CSV_FILE, mode='r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        nameplates = []
        for row in reader:
            name = row['名前']
            roman = row['正しいローマ字']
            nameplates.append(f"""
        <div class="slide">
            <div class="name">{name}</div>
            <div class="roman">{roman}</div>
        </div>
            """)

    # HTMLファイルを出力
    with open(OUTPUT_HTML, mode='w', encoding='utf-8') as file:
        file.write(HTML_HEADER)
        file.write("\n".join(nameplates))
        file.write(HTML_FOOTER)

if __name__ == '__main__':
    generate_nameplates()
    print(f"HTMLスライドを生成しました: {OUTPUT_HTML}")