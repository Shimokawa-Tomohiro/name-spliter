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

# --- HTMLコンテンツ (エラー回避のためここに直接記述) ---
html_content = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI姓名分割ツール Pro</title>
    <style>
        body { font-family: "Helvetica Neue", Arial, sans-serif; background-color: #f3f4f6; color: #333; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        header { text-align: center; margin-bottom: 40px; }
        h1 { color: #2563eb; }
        
        /* プランカード */
        .plans { display: flex; gap: 20px; justify-content: center; flex-wrap: wrap; }
        .card { background: white; padding: 20px; border-radius: 12px; width: 250px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-align: center; }
        .card h3 { margin-top: 0; color: #555; }
        .price { font-size: 24px; font-weight: bold; color: #2563eb; margin: 10px 0; }
        .btn-buy { display: inline-block; background-color: #2563eb; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold; margin-top: 15px; }
        .btn-buy:hover { background-color: #1d4ed8; }
        
        /* 残高確認 */
        .checker { background: white; padding: 20px; border-radius: 12px; margin-top: 40px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        input { padding: 10px; border: 1px solid #ddd; border-radius: 6px; width: 60%; font-size: 16px; }
        button { padding: 10px 20px; background-color: #4b5563; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 16px; }
        #balance-result { margin-top: 15px; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>AI姓名分割ツール</h1>
            <p>スプレッドシートで使える高精度な分割関数。PINコードを購入して今すぐ開始。</p>
        </header>

        <div class="plans">
            <div class="card">
                <h3>スターター</h3>
                <div class="price">500円</div>
                <p>100回分</p>
                <a href="https://buy.stripe.com/test_8x23coecJfeUay7aSCfbq00" class="btn-buy" target="_blank">購入する</a>
            </div>
            <div class="card">
                <h3>プロ</h3>
                <div class="price">3,000円</div>
                <p>1,000回分</p>
                <p><small>（お買い得）</small></p>
                <a href="https://buy.stripe.com/test_5kQ8wIb0x6Io21B9Oyfbq01" class="btn-buy" target="_blank">購入する</a>
            </div>
        </div>

        <div class="checker">
            <h3>残高・有効性チェック</h3>
            <input type="text" id="pin-input" placeholder="PINコードを入力 (例: AI-XXXX...)">
            <button onclick="checkBalance()">確認</button>
            <div id="balance-result"></div>
        </div>
    </div>

    <script>
        async function checkBalance() {
            const pin = document.getElementById('pin-input').value;
            const resDiv = document.getElementById('balance-result');
            if(!pin) return;
            
            resDiv.innerText = "確認中...";
            try {
                const res = await fetch(`/api/balance?pin=${pin}`);
                const data = await res.json();
                if(data.valid) {
                    resDiv.innerHTML = `<span style="color:green">有効</span> 残り: ${data.credits}回 (プラン: ${data.plan})`;
                } else {
                    resDiv.innerHTML = `<span style="color:red">無効なPINコードです</span>`;
                }
            } catch(e) {
                resDiv.innerText = "エラーが発生しました";
            }
        }
    </script>
</body>
</html>
"""

# --- ヘルパー関数: PIN生成 ---
def generate_pin():
    return f"AI-{str(uuid.uuid4())[:8].upper()}"

# --- ヘルパー関数: メール送信 ---
def send_pin_email(to_email: str, pin_code: str, credits: int):
    try:
        # Resendの無料枠はFromアドレスに制限がある場合があります
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

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        customer_email = session.get("customer_details", {}).get("email")
        amount_total = session.get("amount_total")
        
        added_credits = 100
        plan_name = "Standard"
        if amount_total >= 1000:
            added_credits = 1000
            plan_name = "Pro"

        new_pin = generate_pin()
        
        try:
            supabase.table("user_credits").insert({
                "pin_code": new_pin,
                "credits": added_credits,
                "email": customer_email,
                "plan_type": plan_name
            }).execute()
            
            send_pin_email(customer_email, new_pin, added_credits)
            
        except Exception as e:
            print(f"DB Insert Error: {e}")
            return JSONResponse(content={"status": "error"}, status_code=500)

    return {"status": "success"}

# ---------------------------------------------------------
# 2. スプレッドシート用 API
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
# 4. フロントエンド配信 (HTMLを直接返す)
# ---------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def read_root():
    # ファイル読み込みをやめて、変数から返す
    return html_content
