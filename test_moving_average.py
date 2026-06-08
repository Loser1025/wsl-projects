#!/usr/bin/env python3
"""
実装したcalculate_moving_average関数をテストするスクリプト
"""
from moving_average import calculate_moving_average

# テストケース1: 基本的な動作確認
data1 = [1, 2, 3, 4, 5]
window_size1 = 3
result1 = calculate_moving_average(data1, window_size1)
print(f"テストケース1: {data1} (window_size={window_size1}) -> {result1}")

# テストケース2: ウィンドウサイズがデータ数より大きい場合
data2 = [1, 2, 3]
window_size2 = 5
result2 = calculate_moving_average(data2, window_size2)
print(f"テストケース2: {data2} (window_size={window_size2}) -> {result2}")

# テストケース3: ウィンドウサイズが1の場合
data3 = [10, 20, 30, 40]
window_size3 = 1
result3 = calculate_moving_average(data3, window_size3)
print(f"テストケース3: {data3} (window_size={window_size3}) -> {result3}")

# テストケース4: ウィンドウサイズが0以下の場合（エラー処理確認）
data4 = [1, 2, 3]
window_size4 = 0
try:
    result4 = calculate_moving_average(data4, window_size4)
    print(f"テストケース4: {data4} (window_size={window_size4}) -> {result4}")
except ValueError as e:
    print(f"テストケース4: エラーが発生しました -> {e}")

# テストケース5: 空のリストの場合
data5 = []
window_size5 = 2
result5 = calculate_moving_average(data5, window_size5)
print(f"テストケース5: {data5} (window_size={window_size5}) -> {result5}")