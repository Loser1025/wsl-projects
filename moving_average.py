def calculate_moving_average(data, window_size):
    """
    与えられた数値の配列から、指定された要素数ごとの移動平均を計算する関数
    
    Args:
        data (list): 数値のリスト
        window_size (int): 移動平均のウィンドウサイズ
        
    Returns:
        list: 各地点での移動平均値のリスト
    """
    if window_size <= 0:
        raise ValueError("window_size は1以上である必要があります")
    
    if len(data) < window_size:
        return []
    
    moving_averages = []
    for i in range(len(data) - window_size + 1):
        window = data[i:i + window_size]
        average = sum(window) / window_size
        moving_averages.append(average)
    
    return moving_averages