import os
import json
import uuid
import stripe
import resend
from fastapi import FastAPI, HTTPException, Query, Request, Header
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse
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
STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")

# --- クライアント初期化 ---
azure_client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version="2024-08-01-preview",
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
stripe.api_key = STRIPE_API_KEY
resend.api_key = RESEND_API_KEY

# --- ヘルパー関数: PIN生成 ---
def generate_pin():
    # "AI-xxxx-xxxx" のような読みやすいPINを生成
    return f"AI-{str(uuid.uuid4())[:8].upper()}"

# --- ヘルパー関数: メール送信 ---
def send_pin_email(to_email: str, pin_code: str, credits: int):
    try:
        # ※ Resendの無料枠では、Fromは 'onboarding@resend.dev' 固定の場合があります。
        # 独自ドメイン設定済みの場合はそれを指定してください。
        resend.Emails.send({
            "from": "onboarding@resend.dev",
            "to": to_email,
            "subject": "【姓名分割AI】PINコードの発行完了",
            "html": f"""
            <h2>ご購入ありがとうございます</h2>
            <p>姓名分割AI関数のPINコードを発行しました。</p>
            <p><strong>PINコード: {pin_code}</strong></p>
            <p>利用可能回数: {credits}回</p>
            <hr>
            <p>使い方の例:<br>
            <code>=IMPORTDATA("https://name-spliter.vercel.app/api/sheet?name=" & ENCODEURL(A1) & "&pin={pin_code}")</code>
            </p>
            """
        })
        print(f"Email sent to {to_email}")
    except Exception as e:
        print(f"Email Error: {e}")

# ---------------------------------------------------------
# 1. 決済連携 (Stripe Webhook)
# ---------------------------------------------------------
@app.post("/api/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    payload = await request.body()
    
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 決済完了イベントのみ処理
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        
        # 顧客情報の取得
        customer_email = session.get("customer_details", {}).get("email")
        amount_total = session.get("amount_total") # 金額でプラン判定も可能
        
        # プラン判定ロジック (メタデータまたは金額で判定)
        # ここでは簡易的に金額で分岐させる例
        added_credits = 100
        plan_name = "Standard"
        
        # Stripeの商品設定でメタデータに 'credits' を入れておくとベストですが、簡易判定:
        if amount_total >= 1000: # 例: 1000円以上ならPro
            added_credits = 1000
            plan_name = "Pro"

        # PIN生成とDB保存
        new_pin = generate_pin()
        
        try:
            supabase.table("user_credits").insert({
                "pin_code": new_pin,
                "credits": added_credits,
                "email": customer_email,
                "plan_type": plan_name
            }).execute()
            
            # メール送信
            send_pin_email(customer_email, new_pin, added_credits)
            
        except Exception as e:
            print(f"DB Insert Error: {e}")
            return JSONResponse(content={"status": "error"}, status_code=500)

    return {"status": "success"}

# ---------------------------------------------------------
# 2. スプレッドシート用 API (前回と同じ)
# ---------------------------------------------------------
@app.get("/api/sheet", response_class=PlainTextResponse)
async def split_name_sheet(
    name: str = Query(..., description="分割したい氏名"),
    pin: str = Query(..., description="購入したPINコード"),
    target: str = Query("all", description="出力モード: all, last, first")
):
    # --- PIN確認 ---
    res = supabase.table("user_credits").select("*").eq("pin_code", pin).execute()
    if not res.data:
        return "Error: 無効なPINコード"
    
    user_data = res.data[0]
    if user_data["credits"] <= 0:
        return "Error: 残高ゼロ"

    # --- AI実行 ---
    try:
        chat_completion = azure_client.chat.completions.create(
            model=AZURE_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": "入力された氏名をJSON形式 {'last_name': '姓', 'first_name': '名'} で返してください。"},
                {"role": "user", "content": name}
            ],
            response_format={"type": "json_object"}
        )
        ai_result = json.loads(chat_completion.choices[0].message.content)
    except Exception as e:
        return f"Error: AI処理失敗 {str(e)}"

    # --- 消費 ---
    supabase.table("user_credits").update({"credits": user_data["credits"] - 1}).eq("id", user_data["id"]).execute()

    # --- 返却 ---
    if target == "last": return ai_result['last_name']
    elif target == "first": return ai_result['first_name']
    else: return f"{ai_result['last_name']},{ai_result['first_name']}"

# ---------------------------------------------------------
# 3. 残高確認 API
# ---------------------------------------------------------
@app.get("/api/balance")
async def check_balance(pin: str):
    res = supabase.table("user_credits").select("credits, plan_type").eq("pin_code", pin).execute()
    if not res.data:
        return {"valid": False}
    return {"valid": True, "credits": res.data[0]["credits"], "plan": res.data[0]["plan_type"]}

# ---------------------------------------------------------
# 4. フロントエンド用 HTML配信
# ---------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("public/index.html", "r", encoding="utf-8") as f:
        return f.read()
