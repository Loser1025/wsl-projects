#!/usr/bin/env python3
"""
実装したextract_text_from_zip関数をテストするスクリプト
"""
import os
import zipfile
from io import BytesIO
from zip_text_extractor import extract_text_from_zip


def create_test_zip_file(zip_path: str, files: dict) -> None:
    """
    テスト用のZIPファイルを作成する
    
    Args:
        zip_path (str): 作成するZIPファイルのパス
        files (dict): ファイル名と内容の辞書
    """
    with zipfile.ZipFile(zip_path, 'w') as zip_ref:
        for filename, content in files.items():
            zip_ref.writestr(filename, content)


def test_extract_text_from_zip():
    """
    extract_text_from_zip関数のテストを実行する
    """
    # テスト用のZIPファイルを作成
    test_zip_path = "test_files.zip"
    test_files = {
        "file1.txt": "Hello, this is file 1.",
        "file2.txt": "This is file 2.",
        "file3.log": "This is a log file.",
        "file4.txt": "This is file 4.",
    }
    create_test_zip_file(test_zip_path, test_files)
    
    # テスト1: ZIPファイルのパスを指定してテキストを抽出
    print("=== テスト1: ZIPファイルのパスを指定してテキストを抽出 ===")
    try:
        result = extract_text_from_zip(test_zip_path)
        print("抽出されたテキスト:")
        print(result)
    except Exception as e:
        print(f"エラーが発生しました: {e}")
    
    # テスト2: ZIPファイルのバッファを指定してテキストを抽出
    print("\n=== テスト2: ZIPファイルのバッファを指定してテキストを抽出 ===")
    try:
        with open(test_zip_path, 'rb') as f:
            zip_buffer = BytesIO(f.read())
        result = extract_text_from_zip(zip_buffer)
        print("抽出されたテキスト:")
        print(result)
    except Exception as e:
        print(f"エラーが発生しました: {e}")
    
    # テスト3: .txtファイルが含まれていないZIPファイル
    print("\n=== テスト3: .txtファイルが含まれていないZIPファイル ===")
    test_zip_path_no_txt = "test_files_no_txt.zip"
    test_files_no_txt = {
        "file1.log": "This is a log file.",
        "file2.csv": "1,2,3",
    }
    create_test_zip_file(test_zip_path_no_txt, test_files_no_txt)
    try:
        result = extract_text_from_zip(test_zip_path_no_txt)
        print("抽出されたテキスト:")
        print(result if result else "(空)")
    except Exception as e:
        print(f"エラーが発生しました: {e}")
    
    # テスト4: 存在しないZIPファイル
    print("\n=== テスト4: 存在しないZIPファイル ===")
    try:
        result = extract_text_from_zip("nonexistent.zip")
        print("抽出されたテキスト:")
        print(result)
    except Exception as e:
        print(f"エラーが発生しました: {e}")
    
    # テスト5: 破損したZIPファイル
    print("\n=== テスト5: 破損したZIPファイル ===")
    test_corrupted_zip_path = "test_corrupted.zip"
    with open(test_corrupted_zip_path, 'wb') as f:
        f.write(b"This is not a valid ZIP file.")
    try:
        result = extract_text_from_zip(test_corrupted_zip_path)
        print("抽出されたテキスト:")
        print(result)
    except Exception as e:
        print(f"エラーが発生しました: {e}")
    
    # テスト用のZIPファイルを削除
    for file in [test_zip_path, test_zip_path_no_txt, test_corrupted_zip_path]:
        if os.path.exists(file):
            os.remove(file)


if __name__ == "__main__":
    test_extract_text_from_zip()