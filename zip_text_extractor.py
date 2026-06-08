#!/usr/bin/env python3
"""
ZIPファイルから.txtファイルを抽出し、内容を結合するバックエンド関数
"""
import zipfile
from typing import Union
from io import BytesIO


def extract_text_from_zip(zip_path_or_buffer: Union[str, BytesIO]) -> str:
    """
    ZIPファイルから.txtファイルを抽出し、内容を結合する
    
    Args:
        zip_path_or_buffer (Union[str, BytesIO]): ZIPファイルのパスまたはバッファ
        
    Returns:
        str: 抽出されたテキストの内容を結合した文字列
        
    Raises:
        FileNotFoundError: ZIPファイルが見つからない場合
        zipfile.BadZipFile: ZIPファイルが破損している場合
    """
    # ZIPファイルを開く
    if isinstance(zip_path_or_buffer, str):
        # パスの場合
        with zipfile.ZipFile(zip_path_or_buffer, 'r') as zip_ref:
            return _extract_text_from_zip_ref(zip_ref)
    else:
        # バッファの場合
        with zipfile.ZipFile(zip_path_or_buffer, 'r') as zip_ref:
            return _extract_text_from_zip_ref(zip_ref)


def _extract_text_from_zip_ref(zip_ref: zipfile.ZipFile) -> str:
    """
    ZIPファイルから.txtファイルを抽出し、内容を結合する
    
    Args:
        zip_ref (zipfile.ZipFile): ZIPファイルのリファレンス
        
    Returns:
        str: 抽出されたテキストの内容を結合した文字列
        
    Raises:
        ValueError: ファイルパスに '..' や絶対パスが含まれている場合
    """
    combined_text = []
    
    # ZIPファイル内の全ファイルを走査
    for file_info in zip_ref.infolist():
        # .txtファイルのみを対象とする
        if file_info.filename.endswith('.txt'):
            # Zip Slip対策: ファイルパスに '..' や絶対パスが含まれていないか確認
            if '..' in file_info.filename or file_info.filename.startswith('/'):
                raise ValueError(f"不正なファイルパスが含まれています: {file_info.filename}")
            
            with zip_ref.open(file_info) as file:
                # ファイルの内容を読み込み
                text = file.read().decode('utf-8')
                combined_text.append(text)
    
    # 全てのテキストを結合して返す
    return '\n'.join(combined_text)