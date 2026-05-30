import csv

# CSVファイルのパス
CSV_FILE = '/home/loser/wsl-projects/roman_correction_list.csv'
# 出力HTMLファイルのパス
OUTPUT_HTML = '/home/loser/wsl-projects/nameplates_stylish_v3.html'

# HTMLのヘッダーとフッター
HTML_HEADER = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stylish Nameplates</title>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@700&family=Montserrat:wght@400;700&display=swap" rel="stylesheet">
    <link href="https://unpkg.com/aos@2.3.1/dist/aos.css" rel="stylesheet">
    <style>
        body {
            font-family: 'Noto Sans JP', 'Montserrat', sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #0f0f1a;
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 20px;
            overflow-x: hidden;
        }
        .nameplate {
            width: 320px;
            height: 200px;
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            color: white;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(255, 255, 255, 0.1);
            padding: 20px;
            box-sizing: border-box;
            text-align: center;
            position: relative;
            overflow: hidden;
            transition: transform 0.3s ease;
        }
        .nameplate:hover {
            transform: scale(1.05);
        }
        .name {
            font-size: clamp(28px, 6vw, 40px);
            font-weight: bold;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.5);
            z-index: 2;
            line-height: 1.2;
        }
        .roman {
            font-size: clamp(20px, 4vw, 28px);
            opacity: 0.9;
            text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.5);
            z-index: 2;
        }
        .nameplate::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(45deg, #ff00cc, #3333ff, #00ccff);
            background-size: 300% 300%;
            animation: gradient 5s ease infinite;
            z-index: 1;
            opacity: 0.7;
        }
        @keyframes gradient {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }
    </style>
</head>
<body>
    <div id="particles-js"></div>
"""

HTML_FOOTER = """
    <script src="https://cdn.jsdelivr.net/particles.js/2.0.0/particles.min.js"></script>
    <script src="https://unpkg.com/aos@2.3.1/dist/aos.js"></script>
    <script>
        AOS.init();
        particlesJS('particles-js', {
            "particles": {
                "number": {
                    "value": 80,
                    "density": {
                        "enable": true,
                        "value_area": 800
                    }
                },
                "color": {
                    "value": "#ffffff"
                },
                "shape": {
                    "type": "circle",
                    "stroke": {
                        "width": 0,
                        "color": "#000000"
                    }
                },
                "opacity": {
                    "value": 0.5,
                    "random": true,
                    "anim": {
                        "enable": true,
                        "speed": 1,
                        "opacity_min": 0.1,
                        "sync": false
                    }
                },
                "size": {
                    "value": 3,
                    "random": true,
                    "anim": {
                        "enable": true,
                        "speed": 2,
                        "size_min": 0.1,
                        "sync": false
                    }
                },
                "line_linked": {
                    "enable": true,
                    "distance": 150,
                    "color": "#ffffff",
                    "opacity": 0.4,
                    "width": 1
                },
                "move": {
                    "enable": true,
                    "speed": 1,
                    "direction": "none",
                    "random": true,
                    "straight": false,
                    "out_mode": "out",
                    "bounce": false
                }
            },
            "interactivity": {
                "detect_on": "canvas",
                "events": {
                    "onhover": {
                        "enable": true,
                        "mode": "grab"
                    },
                    "onclick": {
                        "enable": true,
                        "mode": "push"
                    }
                }
            }
        });
    </script>
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
        <div class="nameplate" data-aos="fade-up">
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