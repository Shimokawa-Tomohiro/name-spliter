import os
import json
import uuid
import stripe
import resend
from fastapi import FastAPI, HTTPException, Query, Request, Header
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse
from pydantic import BaseModel
from openai import OpenAI
from supabase import create_client, Client

app = FastAPI()

# --- 環境変数の読み込み ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")

# --- クライアント初期化 ---
openai_client = OpenAI(api_key=OPENAI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
stripe.api_key = STRIPE_API_KEY
resend.api_key = RESEND_API_KEY

# =========================================================
#  フロントエンド (HTML) - 3段階プランUI
# =========================================================
# ※ 下記の href="YOUR_STRIPE_LINK_..." の部分を、
#    ご自身がStripeで作成した支払リンクURLに書き換えてください。
# =========================================================
html_content = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI姓名分割ツール</title>
    <style>
        body { font-family: "Helvetica Neue", Arial, sans-serif; background-color: #f8fafc; color: #334155; margin: 0; padding: 0; }
        .container { max-width: 900px; margin: 0 auto; padding: 40px 20px; }
        
        /* ヘッダー */
        header { text-align: center; margin-bottom: 50px; }
        h1 { color: #0f172a; font-size: 2.5rem; margin-bottom: 10px; }
        .subtitle { font-size: 1.1rem; color: #64748b; }

        /* プラン表示エリア */
        .plans { 
            display: flex; 
            gap: 20px; 
            justify-content: center; 
            flex-wrap: wrap; 
            align-items: flex-start; /* 高さを揃えない（おすすめを目立たせるため） */
        }
        
        .card { 
            background: white; 
            padding: 30px 20px; 
            border-radius: 16px; 
            width: 260px; 
            text-align: center; 
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); 
            transition: transform 0.2s;
            position: relative;
            border: 1px solid #e2e8f0;
        }
        
        .card:hover { transform: translateY(-5px); }

        /* おすすめプランの強調スタイル */
        .card.recommended { 
            border: 2px solid #3b82f6; 
            box-shadow: 0 10px 15px -3px rgba(59, 130, 246, 0.2);
            transform: scale(1.05);
            z-index: 10;
        }
        .card.recommended:hover { transform: scale(1.08); }
        
        .badge {
            background-color: #3b82f6;
            color: white;
            position: absolute;
            top: -12px;
            left: 50%;
            transform: translateX(-50%);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: bold;
        }

        /* 文字スタイル */
        .plan-name { font-size: 1.25rem; font-weight: bold; color: #334155; margin-bottom: 10px; }
        .price { font-size: 2rem; font-weight: 800; color: #0f172a; margin: 10px 0; }
        .unit { font-size: 1rem; font-weight: normal; color: #64748b; }
        .desc { color: #64748b; font-size: 0.95rem; margin-bottom: 25px; min-height: 40px;}
        
        /* ボタン */
        .btn-buy { 
            display: block; 
            width: 100%; 
            padding: 12px 0; 
            border-radius: 8px; 
            text-decoration: none; 
            font-weight: bold; 
            transition: opacity 0.2s;
            box-sizing: border-box;
        }
        .btn-plain { background-color: #f1f5f9; color: #334155; }
        .btn-plain:hover { background-color: #e2e8f0; }
        
        .btn-primary { background-color: #3b82f6; color: white; box-shadow: 0 4px 6px rgba(59, 130, 246, 0.3); }
        .btn-primary:hover { background-color: #2563eb; }

        /* 残高確認エリア */
        .checker { 
            background: white; 
            max-width: 500px;
            margin: 60px auto 0;
            padding: 30px; 
            border-radius: 12px; 
            text-align: center; 
            box-shadow: 0 4px 6px rgba(0,0,0,0.05); 
            border: 1px solid #e2e8f0;
        }
        .input-group { display: flex; gap: 10px; margin-top: 20px; }
        input { flex: 1; padding: 12px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 16px; outline: none; }
        input:focus { border-color: #3b82f6; }
        .btn-check { padding: 0 20px; background-color: #334155; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; }
        #balance-result { margin-top: 20px; font-weight: bold; min-height: 1.5em; }

    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>AI姓名分割ツール</h1>
            <p class="subtitle">スプレッドシートやExcelで使える高精度な関数。<br>PINコードを購入して、今すぐ利用開始。</p>
        </header>

        <div class="plans">
            <div class="card">
                <div class="plan-name">ライト</div>
                <div class="price">500<span class="unit">円</span></div>
                <p class="desc">500件分<br><small>（単価 1.0円）</small></p>
                <a href="YOUR_STRIPE_LINK_LITE" class="btn-buy btn-plain" target="_blank">購入する</a>
            </div>

            <div class="card recommended">
                <div class="badge">人気 No.1</div>
                <div class="plan-name">スタンダード</div>
                <div class="price">2,000<span class="unit">円</span></div>
                <p class="desc">3,000件分<br><small style="color:#ef4444; font-weight:bold;">（単価 約0.6円 / 1,000件お得）</small></p>
                <a href="YOUR_STRIPE_LINK_STANDARD" class="btn-buy btn-primary" target="_blank">購入する</a>
            </div>

            <div class="card">
                <div class="plan-name">ビジネス</div>
                <div class="price">5,000<span class="unit">円</span></div>
                <p class="desc">10,000件分<br><small>（単価 0.5円 / 大量処理に）</small></p>
                <a href="YOUR_STRIPE_LINK_BUSINESS" class="btn-buy btn-plain" target="_blank">購入する</a>
            </div>
        </div>

        <div class="checker">
            <h3>残高・有効性チェック</h3>
            <p style="font-size:0.9rem; color:#64748b;">メールで届いたPINコードを入力してください</p>
            <div class="input-group">
                <input type="text" id="pin-input" placeholder="例: AI-ABCD1234...">
                <button class="btn-check" onclick="checkBalance()">確認</button>
            </div>
            <div id="balance-result"></div>
        </div>
    </div>

    <script>
        async function checkBalance() {
            const pin = document.getElementById('pin-input').value.trim();
            const resDiv = document.getElementById('balance-result');
            if(!pin) return;
            
            resDiv.innerText = "確認中...";
            resDiv.style.color = "#64748b";
            
            try {
                const res = await fetch(`/api/balance?pin=${pin}`);
                const data = await res.json();
                if(data.valid) {
                    resDiv.innerHTML = `<span style="color:#10b981">● 有効</span> 残り: ${data.credits.toLocaleString()}回 (プラン: ${data.plan})`;
                } else {
                    resDiv.innerHTML = `<span style="color:#ef4444">× 無効なPINコードです</span>`;
                }
            } catch(e) {
                resDiv.innerText = "通信エラーが発生しました";
            }
        }
    </script>
</body>
</html>
"""

# =========================================================
#  バックエンド処理 (FastAPI)
# =========================================================

# --- メール送信関数 ---
def send_pin_email(to_email: str, pin_code: str, credits: int, plan_name: str):
    try:
        # Resendの設定: 独自ドメイン未設定の場合は onboarding@resend.dev を使用
        # 独自ドメインがある場合は "support@yourdomain.com" などに変更
        resend.Emails.send({
            "from": "onboarding@resend.dev", 
            "to": to_email,
            "subject": "【姓名分割AI】PINコード発行のお知らせ",
            "html": f"""
            <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #3b82f6;">ご購入ありがとうございます</h2>
                <p>以下のPINコードですぐに姓名分割関数をご利用いただけます。</p>
                
                <div style="background: #f1f5f9; padding: 20px; border-radius: 8px; text-align: center; margin: 20px 0;">
                    <p style="margin: 0; color: #64748b; font-size: 0.9rem;">あなたのPINコード</p>
                    <p style="margin: 10px 0; font-size: 24px; font-weight: bold; letter-spacing: 2px; color: #0f172a;">{pin_code}</p>
                    <p style="margin: 0; font-size: 0.9rem;">プラン: {plan_name} ({credits:,}回分)</p>
                </div>
                
                <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
                
                <h3>使い方（スプレッドシート）</h3>
                <p>以下の数式をコピーしてセルに貼り付けてください。</p>
                <code style="display: block; background: #1e293b; color: #e2e8f0; padding: 15px; border-radius: 6px; overflow-x: auto;">
                    =IMPORTDATA("https://{os.environ.get('VERCEL_URL', 'name-spliter.vercel.app')}/api/sheet?name=" & ENCODEURL(A1) & "&pin={pin_code}")
                </code>
            </div>
            """
        })
        print(f"Email sent to {to_email}")
    except Exception as e:
        print(f"Email Error: {e}")

# --- 1. 決済連携 (Stripe Webhook) ---
@app.post("/api/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    payload = await request.body()
    
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError
