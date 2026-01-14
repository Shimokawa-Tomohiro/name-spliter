import os
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import AzureOpenAI
from supabase import create_client, Client

app = FastAPI()

# --- 環境変数の読み込み ---
# Supabase設定
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

# Azure OpenAI設定
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_DEPLOYMENT_NAME = os.environ.get("AZURE_DEPLOYMENT_NAME") # デプロイ名
AZURE_API_VERSION = "2024-08-01-preview" # または利用可能なバージョン

# クライアントの初期化
# Azure OpenAIクライアント
azure_client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version=AZURE_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

# Supabaseクライアント
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# リクエストデータの定義
class SplitRequest(BaseModel):
    full_name: str
    pin_code: str

@app.post("/api/split")
async def split_name(req: SplitRequest):
    # 1. PINコードの確認と残高チェック
    try:
        res = supabase.table("user_credits").select("*").eq("pin_code", req.pin_code).execute()
    except Exception as e:
        # service_roleキーが間違っているとここでエラーになります
        print(f"DB Error: {e}")
        raise HTTPException(status_code=500, detail="データベース接続エラー")
    
    if not res.data:
        raise HTTPException(status_code=400, detail="無効なPINコードです。")
    
    user_data = res.data[0]
    credits = user_data["credits"]

    if credits <= 0:
        raise HTTPException(status_code=400, detail="残高がありません。")

    # 2. Azure OpenAIによる姓名分割
    try:
        chat_completion = azure_client.chat.completions.create(
            model=AZURE_DEPLOYMENT_NAME, # ここにはモデル名ではなく「デプロイ名」が入ります
            messages=[
                {
                    "role": "system",
                    "content": "あなたは日本の人名処理システムです。入力された氏名をJSON形式 {'last_name': '姓', 'first_name': '名'} で返してください。それ以外のテキストは一切含めないでください。"
                },
                {
                    "role": "user",
                    "content": req.full_name
                }
            ],
            response_format={"type": "json_object"}
        )
        ai_result = json.loads(chat_completion.choices[0].message.content)

    except Exception as e:
        print(f"Azure AI Error: {e}")
        raise HTTPException(status_code=500, detail=f"AI処理エラー: {str(e)}")

    # 3. 残高を減らす
    supabase.table("user_credits").update({"credits": credits - 1}).eq("id", user_data["id"]).execute()

    # 4. 結果を返す
    return {
        "status": "success",
        "result": ai_result,
        "remaining_credits": credits - 1
    }