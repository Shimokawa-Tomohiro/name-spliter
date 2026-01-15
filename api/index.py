import os
import json
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel
from openai import AzureOpenAI
from supabase import create_client, Client

app = FastAPI()

# --- 環境変数の読み込み ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_DEPLOYMENT_NAME = os.environ.get("AZURE_DEPLOYMENT_NAME")
AZURE_API_VERSION = "2024-08-01-preview"

# クライアント初期化
azure_client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version=AZURE_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# 共通ロジック: PIN確認と残高消費
def process_payment_and_check_pin(pin_code: str):
    try:
        res = supabase.table("user_credits").select("*").eq("pin_code", pin_code).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail="データベース接続エラー")
    
    if not res.data:
        raise HTTPException(status_code=400, detail="無効なPINコード")
    
    user_data = res.data[0]
    credits = user_data["credits"]

    if credits <= 0:
        raise HTTPException(status_code=400, detail="残高ゼロ")
        
    return user_data

# 共通ロジック: AI処理
def run_ai_split(full_name: str):
    try:
        chat_completion = azure_client.chat.completions.create(
            model=AZURE_DEPLOYMENT_NAME,
            messages=[
                { "role": "system", "content": "あなたは日本の人名処理システムです。入力された氏名をJSON形式 {'last_name': '姓', 'first_name': '名'} で返してください。" },
                { "role": "user", "content": full_name }
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(chat_completion.choices[0].message.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")

# Request Model for POST
class SplitRequest(BaseModel):
    full_name: str
    pin_code: str

# ---------------------------------------------------------
# 1. Webブラウザ用 UI (変更なし)
# ---------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def read_root():
    # 前回ご提供したHTMLと同じ内容を返します
    return """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <title>AI姓名分割 (Azure版)</title>
        <style>body{font-family:sans-serif;max-width:600px;margin:2rem auto;padding:1rem;}input,button{width:100%;padding:10px;margin-top:10px;}</style>
    </head>
    <body>
        <h2>AI姓名分割</h2>
        <input id="pin" placeholder="PINコード"><input id="name" placeholder="氏名">
        <button onclick="run()">実行</button><div id="res"></div>
        <script>
            async function run(){
                const pin=document.getElementById('pin').value, name=document.getElementById('name').value;
                document.getElementById('res').innerText = "処理中...";
                const res = await fetch('/api/split', {
                    method:'POST', headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({pin_code:pin, full_name:name})
                });
                const d = await res.json();
                document.getElementById('res').innerText = res.ok ? `姓:${d.result.last_name} 名:${d.result.first_name}` : `エラー:${d.detail}`;
            }
        </script>
    </body>
    </html>
    """

# ---------------------------------------------------------
# 2. POST API (Web UIや外部アプリ用)
# ---------------------------------------------------------
@app.post("/api/split")
async def split_name_post(req: SplitRequest):
    user_data = process_payment_and_check_pin(req.pin_code)
    ai_result = run_ai_split(req.full_name)
    
    # 消費
    supabase.table("user_credits").update({"credits": user_data["credits"] - 1}).eq("id", user_data["id"]).execute()
    
    return { "status": "success", "result": ai_result, "remaining_credits": user_data["credits"] - 1 }

# ---------------------------------------------------------
# 3. GET API (スプレッドシート関数用) ★ここが追加部分
# ---------------------------------------------------------
@app.get("/api/sheet", response_class=PlainTextResponse)
async def split_name_sheet(
    pin: str = Query(..., description="購入したPINコード"),
    name: str = Query(..., description="分割したい氏名")
):
    """
    スプレッドシートの IMPORTDATA関数 で使うためのエンドポイント
    例: =IMPORTDATA(".../api/sheet?pin=123&name=徳川家康")
    戻り値: "徳川,家康" (CSV形式)
    """
    try:
        # PINチェック
        user_data = process_payment_and_check_pin(pin)
        
        # AI実行
        ai_result = run_ai_split(name)
        
        # 消費実行
        supabase.table("user_credits").update({"credits": user_data["credits"] - 1}).eq("id", user_data["id"]).execute()
        
        # CSV形式 "姓,名" で返す (スプレッドシートが勝手にセル分けしてくれる)
        return f"{ai_result['last_name']},{ai_result['first_name']}"
        
    except HTTPException as e:
        # スプレッドシートのセルにエラーを表示させる
        return f"Error: {e.detail}"
