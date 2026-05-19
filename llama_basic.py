import json
import sqlite3
from flask import Flask, render_template_string, request, Response
import requests

app = Flask(__name__)

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "llama3.2"
DB_NAME = "llama_database_1.db"
SYSTEM_PROMPT = "Add emoji at the end of the sentence"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_question TEXT,
            ai_response TEXT,
            notes TEXT
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


def load_history_from_db():
    """從 SQLite 重建對話歷史，這樣重啟伺服器後記憶依然存在。"""
    history = [{"role": "system", "content": SYSTEM_PROMPT}]
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_question, ai_response FROM chat_records ORDER BY id ASC"
        )
        rows = cursor.fetchall()
        conn.close()
        for user_question, ai_response in rows:
            history.append({"role": "user", "content": user_question})
            history.append({"role": "assistant", "content": ai_response})
    except Exception as e:
        print(f"❌ 讀取歷史紀錄失敗: {e}")
    return history


def save_to_db(user_prompt, ai_response):
    """寫入一筆對話紀錄至 SQLite。"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO chat_records (user_question, ai_response, notes) VALUES (?, ?, ?)",
            (user_prompt, ai_response, "初始儲存"),
        )
        conn.commit()
        conn.close()
        print("💾 成功同步至 SQLite 資料庫！")
    except Exception as db_err:
        print(f"❌ 資料庫寫入失敗: {db_err}")


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>基於llama3.2 帶記憶的問答AI基本架構</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 600px; margin: 40px auto; padding: 0 20px; line-height: 1.6; }
        textarea { width: 100%; height: 100px; padding: 10px; box-sizing: border-box; border: 1px solid #ccc; border-radius: 4px; font-size: 16px; }
        button { background-color: #007aff; color: white; border: none; padding: 10px 20px; font-size: 16px; border-radius: 4px; cursor: pointer; margin-top: 10px; }
        button:disabled { background-color: #aaa; cursor: not-allowed; }
        button:hover:not(:disabled) { background-color: #0056b3; }
        #output-box { margin-top: 20px; padding: 15px; background-color: #f5f5f7; border-radius: 4px; min-height: 50px; border-left: 4px solid #007aff; white-space: pre-wrap; }
        .status-tag { font-size: 12px; color: #666; margin-top: 5px; font-style: italic; }
        #clear-btn { background-color: #ff3b30; margin-left: 10px; }
        #clear-btn:hover:not(:disabled) { background-color: #c0392b; }
    </style>
</head>
<body>
    <h2>Llama 3.2 + SQLite 整合對話系統</h2>
    <p> :-) 輸入你想對 AI 說的話（對話將自動存入llama_database_1）：</p>
    <textarea id="userInput" placeholder="例如：請自我介紹..."></textarea>
    <br>
    <button id="send-btn" onclick="sendToLlama()">Send</button>
    <button id="clear-btn" onclick="clearHistory()">清除記憶</button>

    <h3> :-D 輸出結果：</h3>
    <div id="output-box">等待輸入中...</div>
    <div id="status" class="status-tag"></div>

    <script>
        async function sendToLlama() {
            const userInput = document.getElementById('userInput').value;
            const outputBox = document.getElementById('output-box');
            const statusBox = document.getElementById('status');
            const sendBtn = document.getElementById('send-btn');

            if (!userInput.trim()) return alert('請先輸入文字！');

            outputBox.innerText = '思考中...';
            statusBox.innerText = '';
            sendBtn.disabled = true;

            try {
                const response = await fetch('/ask', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: userInput })
                });

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                outputBox.innerText = '';

                while (true) {
                    const { value, done } = await reader.read();
                    if (done) break;
                    outputBox.innerText += decoder.decode(value);
                }

                statusBox.innerText = "💾 本次對話已自動同步至本地資料庫 (llama_database_1.db)";
                document.getElementById('userInput').value = '';
            } catch (error) {
                outputBox.innerText = '發生錯誤：' + error;
            } finally {
                sendBtn.disabled = false;
            }
        }

        async function clearHistory() {
            if (!confirm('確定要清除所有對話記憶嗎？')) return;
            const res = await fetch('/clear', { method: 'POST' });
            const msg = await res.text();
            document.getElementById('status').innerText = msg;
            document.getElementById('output-box').innerText = '記憶已清除，可以開始新對話。';
        }

        // 按 Enter 送出（Shift+Enter 換行）
        document.addEventListener('DOMContentLoaded', () => {
            document.getElementById('userInput').addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendToLlama();
                }
            });
        });
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/ask", methods=["POST"])
def ask():
    user_data = request.get_json()
    user_prompt = user_data.get("prompt", "").strip()
    if not user_prompt:
        return Response("請輸入問題", mimetype="text/plain")

    # 每次請求都從 DB 重建歷史，重啟伺服器後記憶完整保留
    history = load_history_from_db()
    history.append({"role": "user", "content": user_prompt})

    ollama_payload = {
        "model": MODEL_NAME,
        "messages": history,
        "stream": True,
    }

    def generate():
        ai_response_accumulator = ""
        try:
            with requests.post(
                OLLAMA_CHAT_URL, json=ollama_payload, stream=True
            ) as r:
                for line in r.iter_lines():
                    if line:
                        json_data = json.loads(line.decode("utf-8"))
                        token = json_data.get("message", {}).get("content", "")
                        ai_response_accumulator += token
                        yield token
        except Exception as e:
            yield f"後端連線 Ollama 失敗: {str(e)}"
            return

        # streaming 結束後寫入 DB — 不需要 session，完全安全
        save_to_db(user_prompt, ai_response_accumulator)

    return Response(generate(), mimetype="text/plain")


@app.route("/clear", methods=["POST"])
def clear_history():
    """清除所有對話紀錄（給使用者重置記憶用）。"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_records")
        conn.commit()
        conn.close()
        print("🗑️ 對話歷史已清除")
        return Response("🗑️ 記憶已清除！", mimetype="text/plain")
    except Exception as e:
        return Response(f"❌ 清除失敗: {e}", mimetype="text/plain")


if __name__ == "__main__":
    app.run(port=5001, debug=True)