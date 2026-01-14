import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from openai import AzureOpenAI
from supabase import create_client, Client

app = FastAPI()

# --- HTMLデータをここに直接書きます (確実に表示させるため) ---
html_content = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Azure AI 姓名分割</title>
    <style>
        body { font-family: "Helvetica Neue", Arial, sans-serif; max-width: 600px; margin: 2rem auto; padding: 0 1rem; background-color: #f9fafb; }
        .container { background: white; padding: 2rem; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        h2 { text-align: center; color: #333; }
        label { display: block; margin-top: 15px; font-weight: bold; color: #555; }
        input { width: 100%; padding: 12px; margin-top: 5px; border: 1px solid #ddd; border-radius: 6px; box-sizing: border-box; font-size: 16px; }
        button { width: 100%; padding: 12px; margin-top: 20px; background-color: #0078d4; color: white; border: none; border-radius: 6px; font-size: 16px; font-weight: bold; cursor: pointer; transition: background 0.2s; }
        button:hover { background-color: #106ebe; }
        button:disabled { background-color: #ccc; cursor: not-allowed; }
        #result { margin-top: 25px; padding: 15px; background: #eff6ff; border-radius: 6px; display: none; }
        .result-item { font-size: 1.1rem; margin: 5px 0; }
        .error { color: #dc2626; background: #fef2f2 !important; }
        .credits { display: block; text-align: right; margin-top: 10px; font-size: 0.9rem; color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <h2>AI姓名分割 (Azure版)</h2>
        <p style="text-align: center; color: #666;">PINコードを入力してAIを利用できます</p>
        
        <label>PINコード</label>
        <input type="text" id="pin" placeholder="例: TEST-1234">
        
        <label>分割したい氏名</label>
        <input type="text" id="name" placeholder="例: 徳川家康">
        
        <button id="btn" onclick="splitName()">分割を実行する</button>
        
        <div id="result"></div>
    </div>

    <script>
        async function splitName() {
            const pin = document.getElementById('pin').value;
            const name = document.getElementById('name').value;
            const resultDiv = document.getElementById('result');
            const btn = document.getElementById('btn');
            
            if(!pin || !name) { alert("入力してください"); return; }

            resultDiv.style.display = 'block'; resultDiv.innerHTML = 'AIが考え中...'; resultDiv.className = '';
            btn.disabled = true;

            try {
                const response = await fetch('/api/split', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ pin_code: pin, full_name: name })
                });

                const data = await response.json();

                if (response.ok) {
                    resultDiv.innerHTML = `
                        <div class="result-item"><strong>姓:</strong> ${data.result.last_name}</div>
                        <div class="result-item"><strong>名:</strong> ${data.result.first_name}</div>
                        <span class="credits">残り回数: ${data.remaining_credits}回</span>
                    `;
                } else {
                    resultDiv.innerHTML = `<strong>エラー:</strong> ${data.detail}`;
                    resultDiv.className = 'error';
                }
            } catch (e) {
                console.error(e);
                resultDiv.innerHTML = '通信エラーが発生しました。';
                resultDiv.className = 'error';
            } finally {
                btn.disabled = false;
            }
        }
    </script>
</body>
</html>
"""

# --- 環境変数の読み込み ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_DEPLOYMENT_NAME = os.environ.get("AZURE_DEPLOYMENT_NAME")
AZURE_API_VERSION = "2024-08-01-preview"

# クライアントの初期化
azure_client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version=AZURE_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

class SplitRequest(BaseModel):
    full_name: str
    pin_code: str

# ★重要: ルートURL (/) にアクセスが来たらHTMLを返す設定
@app.get("/", response_class=HTMLResponse)
async def read_root():
    return html_content

@app.post("/api/split")
async def split_name(req: SplitRequest):
    # 1. PIN確認
    try:
        res = supabase.table("user_credits").select("*").eq("pin_code", req.pin_code).execute()
    except Exception as e:
        print(f"DB Error: {e}")
        raise HTTPException(status_code=500, detail="データベース接続エラー")
    
    if not res.data:
        raise HTTPException(status_code=400, detail="無効なPINコードです。")
    
    user_data = res.data[0]
    credits = user_data["credits"]

    if credits <= 0:
        raise HTTPException(status_code=400, detail="残高がありません。")

    # 2. Azure OpenAI
    try:
        chat_completion = azure_client.chat.completions.create(
            model=AZURE_DEPLOYMENT_NAME,
            messages=[
                { "role": "system", "content": "あなたは日本の人名処理システムです。入力された氏名をJSON形式 {'last_name': '姓', 'first_name': '名'} で返してください。" },
                { "role": "user", "content": req.full_name }
            ],
            response_format={"type": "json_object"}
        )
        ai_result = json.loads(chat_completion.choices[0].message.content)
    except Exception as e:
        print(f"Azure AI Error: {e}")
        raise HTTPException(status_code=500, detail=f"AI処理エラー: {str(e)}")

    # 3. 消費
    supabase.table("user_credits").update({"credits": credits - 1}).eq("id", user_data["id"]).execute()

    return { "status": "success", "result": ai_result, "remaining_credits": credits - 1 }
