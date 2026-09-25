@echo off
chcp 65001 >nul
echo ========================================================
echo Zoom Translator - PyInstaller Build Script
echo ========================================================

echo.
echo [1/4] Python環境の確認...
python --version
if errorlevel 1 (
    echo [ERROR] Pythonがインストールされていないか、PATHが通っていません。
    goto error
)

echo.
echo [2/4] 依存パッケージのインストール (ランタイム用 + ビルド用)...
pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 (
    echo [ERROR] 依存パッケージのインストールに失敗しました。
    goto error
)

echo.
echo [3/4] PyInstallerによる単一exeのビルド開始...
:: 初回ダウンロード方式のため、モデルは同梱せず、依存ライブラリの隠れインポート(collect-all)を指定します。
pyinstaller --onefile --windowed --name ZoomTranslator ^
    --collect-all faster_whisper ^
    --collect-all ctranslate2 ^
    --collect-all av ^
    --collect-all argostranslate ^
    --collect-all soundcard ^
    --collect-all numpy ^
    main.py

if errorlevel 1 (
    echo [ERROR] PyInstallerによるビルドに失敗しました。
    goto error
)

echo.
echo ========================================================
echo [4/4] ビルド成功！
echo 出力先: dist\ZoomTranslator.exe
echo ========================================================
goto end

:error
echo.
echo [ERROR] ビルドプロセス中にエラーが発生しました。
pause
exit /b 1

:end
pause
