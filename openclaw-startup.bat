@echo off
REM ============================================
REM OpenClaw Gateway 自動起動スクリプト
REM Gemini 3 Pro + Discord 連携
REM ============================================

REM Git Bash と npm をPATHに追加
set PATH=C:\Users\hakua\AppData\Roaming\npm;C:\Program Files\Git\bin;C:\Program Files\Git\usr\bin;%PATH%

REM Gemini API Key（フォールバック用）
set GEMINI_API_KEY=AIzaSyCiesz8LSjH6b7kc-o0OmOpmjnJaAE305c

REM Gemini CLI OAuth クレデンシャル
set GEMINI_CLI_OAUTH_CLIENT_ID=681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com
set GEMINI_CLI_OAUTH_CLIENT_SECRET=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

REM OpenClaw ディレクトリに移動
cd /d C:\Users\hakua\Downloads\OpenClaw

REM Gateway 起動（ポート18789）
echo [%date% %time%] OpenClaw Gateway を起動しています...
node scripts/run-node.mjs gateway --port 18789
