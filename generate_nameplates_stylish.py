import csv

# CSVファイルのパス
CSV_FILE = '/home/loser/wsl-projects/roman_correction_list.csv'
# 出力HTMLファイルのパス
OUTPUT_HTML = '/home/loser/wsl-projects/nameplates_stylish.html'

# HTMLのヘッダーとフッター
HTML_HEADER = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stylish Nameplates</title>
    <style>
        body {
            font-family: 'Arial', sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f0f0f0;
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 20px;
        }
        .nameplate {
            width: 320px;
            height: 200px;
            background: linear-gradient(135deg, #6e8efb, #a777e3);
            border-radius: 10px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            color: white;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
            padding: 20px;
            box-sizing: border-box;
            text-align: center;
        }
        .name {
            font-size: 28px;
            font-weight: bold;
            margin-bottom: 10px;
            text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.3);
        }
        .roman {
            font-size: 20px;
            opacity: 0.9;
            text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.3);
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
        <div class="nameplate">
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
    print(f"スタイリッシュなHTML名刺を生成しました: {OUTPUT_HTML}")