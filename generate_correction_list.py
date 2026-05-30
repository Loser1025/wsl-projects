#!/usr/bin/env python3
"""
メンリストとスライドのテキストを比較し、訂正リストを生成するスクリプト
"""
import csv
import re

# メンリストのローマ字マッピング
ROMAN_MAPPING = {
    "廣田 珠輝": "TAMAKI HIROTA",
    "吉村 行雲": "KOUN YOSHIMURA",
    "塩見 慎太郎": "SHINTARO SHIOMI",
    "本田 顕士": "KENTO HONDA",
    "秋山 匠": "TAKUMI AKIYAMA",
    "藤村 俊枝": "TOSHIE FUJIMURA",
    "石井 晴": "HARUSHI ISHII",
    "稲垣 太一": "TAICHI INAGAKI",
    "池上 雄斗": "YUTO IKEGAMI",
    "熊谷 侑輝": "YUKI KUMAGAI",
    "加藤 亮平": "RYOHEI KATO",
    "安藤 優世": "YUSEI ANDO",
    "江波戸 健": "TAKERU EBATO",
    "田畑 陽菜": "HINA TAHATA",
    "中田 恵里": "ERI NAKADA",
    "星野 優輝": "YUKI HOSHINO",
    "栗原 堅太": "KENTA KURIHARA",
    "村中 媛香": "HIMEKA MURANAKA",
    "島田 優": "YU SHIMADA",
    "石橋 乙葉": "OTOHA ISHIBASHI",
    "並河 真一": "SHINICHI NAMIKAWA",
    "共田 悠馬": "YUMA TOMODA",
    "進藤 彪": "HYO SHINDO",
    "宮本 悠大": "YUDAI MIYAMOTO",
    "中川 翔太": "SHOTA NAKAGAWA",
    "山﨑 陽向": "HINATA YAMASAKI",
    "熊倉 空大": "KUTO KUMAKURA",
    "吉房 つばさ": "TSUBASA YOSHIFUSA",
    "大関 秀": "SHU OSEKI",
    "髙 未佳": "MIKA KO",
    "金 亜耶": "AYA KIN",
    "穂原 志織": "SHIORI HOBARA",
    "石田 悠真": "YUMA ISHIDA",
    "堀野 昌樹": "MASAKI HORINO",
    "森本 風子": "FUKO MORIMOTO",
    "髙橋 涼夏": "SUZUKA TAKAHASHI",
    "大村 愛咲": "AISA OMURA",
    "田本 翔真": "SHOMA TAMOTO",
    "宮良 高基": "TAKATO MIYARA",
    "吉川 秀斗": "SHUTO KIKKAWA",
    "長谷川 ひらり": "HIRARI HASEGAWA",
    "幡野 智也": "TOMOYA HATANO",
    "皆川 雅斗": "MASATO MINAGAWA",
    "濱田 涼介": "RYOSUKE HAMADA"
}


def normalize_roman(text):
    """テキストからスペースを削除し、大文字を維持（例：T A K A H A S H I -> TAKAHASHI）"""
    return re.sub(r'\s+', '', text)


def extract_roman_from_text(text):
    """テキストからローマ字部分を抽出（大文字のアルファベット列）"""
    # 大文字のアルファベット列を抽出（スペース付きでもOK）
    roman_matches = re.findall(r'[A-Z][\sA-Z]*', text)
    if roman_matches:
        return roman_matches[0].strip()
    return None


def main():
    # CSVファイルを読み込み
    with open('slide_text_export.csv', 'r', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        next(reader)  # ヘッダーをスキップ
        
        # 訂正リストを格納
        correction_list = []
        
        for row in reader:
            slide_id, shape_id, text = row
            
            # 名前を検索
            for name, correct_roman in ROMAN_MAPPING.items():
                if name in text:
                    # ローマ字部分を抽出
                    current_roman = extract_roman_from_text(text)
                    if not current_roman:
                        continue  # ローマ字が見つからない場合はスキップ
                    
                    # 正規化して比較
                    normalized_current = normalize_roman(current_roman)
                    normalized_correct = normalize_roman(correct_roman)
                    
                    if normalized_current != normalized_correct:
                        correction_list.append({
                            'Slide ID': slide_id,
                            'Shape ID': shape_id,
                            'Name': name,
                            'Current Roman': current_roman,
                            'Correct Roman': correct_roman
                        })
                    break
        
        # 訂正リストをCSVファイルに書き込み
        with open('roman_correction_list_final.csv', 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['Slide ID', 'Shape ID', 'Name', 'Current Roman', 'Correct Roman']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for correction in correction_list:
                writer.writerow(correction)
        
        print(f"Successfully generated correction list: {len(correction_list)} corrections found.")


if __name__ == '__main__':
    main()
