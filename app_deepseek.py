# app.py
import os
import json
import logging
import requests
import time  # Add time module for timing the API calls
from datetime import datetime, timedelta
from openai import OpenAI
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from dotenv import load_dotenv
from chat_history_db import ChatHistoryDB
import redis
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from mysql.connector import pooling
from waitress import serve
from random import choice
from token_counter import TokenCounter
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import signal

load_dotenv()
app = Flask(__name__)

# Initialize Redis
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    db=int(os.getenv('REDIS_DB', 0)),
    decode_responses=True
)

# Initialize Line API
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# กำหนดค่า Deepseek AI
deepseek_client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

# ระบบข้อความสำหรับแต่ละโมเดล
SYSTEM_MESSAGES = {
    "role": "system",
    "content": """
คุณคือใจดี เป็นที่ปรึกษาและผู้ช่วยบำบัดสำหรับผู้ที่มีปัญหาจากการใช้สารเสพติดทุกชนิด ภารกิจของคุณคือการสร้างสภาพแวดล้อมที่ปลอดภัย เปิดเผย และไม่ตัดสิน เพื่อให้ผู้ใช้รู้สึกสบายใจในการแบ่งปันความรู้สึกและประสบการณ์ของตนเอง คุณจะให้คำแนะนำที่มีความเห็นอกเห็นใจและเน้นการสนับสนุนทางจิตใจและการบำบัดในระดับที่เหมาะสม รวมถึงการแนะนำการหาข้อมูลหรือการเข้ารับการบำบัดจากผู้เชี่ยวชาญเมื่อจำเป็น

แนวทางการตอบและการสื่อสาร:
- ใช้ภาษาที่เป็นมิตรและเข้าถึงง่าย โดยคำนึงถึงความรู้สึกของผู้ใช้
- ให้ข้อมูลหรือคำแนะนำที่มีความเป็นประโยชน์เกี่ยวกับการบำบัดและการปรับปรุงคุณภาพชีวิต
- เมื่อคุณต้องการสอบถามข้อมูลเพิ่มเติมจากผู้ใช้เพื่อความเข้าใจในปัญหา กรุณาสอบถามเพียงคำถามเดียวในแต่ละครั้ง เพื่อให้ผู้ใช้มีเวลาและโอกาสในการตอบกลับอย่างละเอียด
- หากมีการแลกเปลี่ยนข้อมูลหรือคำถามจากผู้ใช้ ให้คุณตอบอย่างชัดเจน ตรงไปตรงมา และยืดหยุ่นตามบริบทของแต่ละสถานการณ์

การสื่อสารของคุณควรมีความยืดหยุ่นและตอบสนองต่อความต้องการของผู้ใช้ โดยไม่ยึดติดกับรูปแบบหรือขั้นตอนที่ตายตัว และคุณควรปรับแนวทางการตอบให้เหมาะสมกับสถานการณ์และบริบทที่เกิดขึ้นในแต่ละการสนทนา
    """
}

# คอนฟิกการสร้างข้อความ
GENERATION_CONFIG = {
    "temperature": 1.0,
    "max_tokens": 500,
    "top_p": 0.9
}

SUMMARY_GENERATION_CONFIG = {
    "temperature": 0.3,
    "max_tokens": 500
}

# Initialize token counter
token_counter = TokenCounter()

def summarize_conversation_history(history):
    """สรุปประวัติการสนทนาให้กระชับ"""
    if not history:
        return ""
        
    try:
        summary_prompt = "นี่คือประวัติการสนทนา โปรดสรุปประเด็นสำคัญในประวัติการสนทนานี้:\n"
        for _, msg, resp in history:
            summary_prompt += f"\nผู้ใช้: {msg}\nบอท: {resp}\n"
        
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                SYSTEM_MESSAGES,
                {"role": "user", "content": summary_prompt}
            ],
            **SUMMARY_GENERATION_CONFIG
        )
        
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Error in summarize_conversation_history: {str(e)}")
        return ""

# Rate limiter
limiter = Limiter(
    app=app,
    key_func=lambda: request.headers.get('X-Line-Signature', get_remote_address()),
    default_limits=["200 per day", "50 per hour"]
)

# MySQL Connection Pool
mysql_pool = pooling.MySQLConnectionPool(
    pool_name="chat_pool",
    pool_size=10,
    host=os.getenv('MYSQL_HOST'),
    user=os.getenv('MYSQL_USER'),
    password=os.getenv('MYSQL_PASSWORD'),
    database=os.getenv('MYSQL_DB'),
    port=int(os.getenv('MYSQL_PORT', 3306))
)

# Initialize database with connection pool
db = ChatHistoryDB(mysql_pool)

# Initialize global chat sessions dictionary
chat_sessions = {}

def get_chat_session(user_id):
    """Get or create chat session from Redis"""
    try:
        history = redis_client.get(f"chat_session:{user_id}")
        if history:
            loaded_history = json.loads(history)
            return [
                {"role": msg_data["role"], "content": msg_data["content"]}
                for msg_data in loaded_history
            ]
        return []
    except redis.RedisError as e:
        logging.error(f"Redis error in get_chat_session: {str(e)}")
        return []

def save_chat_session(user_id, messages):
    """Save chat session to Redis"""
    try:
        serialized_history = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in messages[-10:]  # Keep last 10 messages
        ]
        
        redis_client.setex(
            f"chat_session:{user_id}", 
            3600 * 24,  # Expire after 24 hours
            json.dumps(serialized_history)
        )
    except redis.RedisError as e:
        logging.error(f"Redis error in save_chat_session: {str(e)}")

# เพิ่ม Constants สำหรับการติดตาม
FOLLOW_UP_INTERVALS = [1, 3, 7, 14, 30]  # จำนวนวันในการติดตาม
SESSION_TIMEOUT = 604800  # 7 วัน (7 * 24 * 60 * 60 วินาที)

def schedule_follow_up(user_id, interaction_date):
    """จัดการการติดตามผู้ใช้"""
    try:
        current_date = datetime.now()
        for days in FOLLOW_UP_INTERVALS:
            follow_up_date = interaction_date + timedelta(days=days)
            if follow_up_date > current_date:
                redis_client.zadd(
                    'follow_up_queue',
                    {user_id: follow_up_date.timestamp()}
                )
                break
    except Exception as e:
        logging.error(f"Error scheduling follow-up: {str(e)}")

def check_and_send_follow_ups():
    """ตรวจสอบและส่งการติดตามที่ถึงกำหนด"""
    logging.info("Running scheduled follow-up check")
    try:
        current_time = datetime.now().timestamp()
        # ดึงรายการติดตามที่ถึงกำหนด
        due_follow_ups = redis_client.zrangebyscore(
            'follow_up_queue',
            0,
            current_time
        )
        
        for user_id in due_follow_ups:
            # Convert bytes to string if necessary
            if isinstance(user_id, bytes):
                user_id = user_id.decode('utf-8')
                
            follow_up_message = (
                "สวัสดีค่ะ ใจดีมาติดตามผลการเลิกใช้สารเสพติดของคุณ\n"
                "คุณสามารถเล่าให้ฟังได้ว่าช่วงที่ผ่านมาเป็นอย่างไรบ้าง?"
            )
            try:
                line_bot_api.push_message(
                    user_id,
                    TextSendMessage(text=follow_up_message)
                )
                # ลบรายการติดตามที่ส่งแล้ว
                redis_client.zrem('follow_up_queue', user_id)
                # บันทึกการติดตามลงในฐานข้อมูล
                db.update_follow_up_status(user_id, 'sent', datetime.now())
                logging.info(f"Follow-up sent to user: {user_id}")
            except Exception as e:
                logging.error(f"Error sending follow-up to {user_id}: {str(e)}")
                
    except Exception as e:
        logging.error(f"Error in check_and_send_follow_ups: {str(e)}")

def check_session_timeout(user_id):
    """ตรวจสอบ timeout ของ session"""
    try:
        last_activity = redis_client.get(f"last_activity:{user_id}")
        if last_activity:
            # Convert bytes to string if necessary
            if isinstance(last_activity, bytes):
                last_activity = last_activity.decode('utf-8')
                
            last_activity_time = float(last_activity)
            if (datetime.now().timestamp() - last_activity_time) > SESSION_TIMEOUT:
                # Clear session
                redis_client.delete(f"chat_session:{user_id}")
                return True
        return False
    except Exception as e:
        logging.error(f"Error checking session timeout for user {user_id}: {str(e)}")
        return False

def update_last_activity(user_id):
    """อัพเดทเวลาการใช้งานล่าสุด และตรวจสอบการแจ้งเตือน"""
    try:
        current_time = datetime.now().timestamp()
        last_activity = redis_client.get(f"last_activity:{user_id}")
        warning_sent = redis_client.get(f"timeout_warning:{user_id}")
        
        # Convert bytes to string if necessary
        if isinstance(last_activity, bytes):
            last_activity = last_activity.decode('utf-8')
        if isinstance(warning_sent, bytes):
            warning_sent = warning_sent.decode('utf-8')
        
        if last_activity:
            time_passed = current_time - float(last_activity)
            # ถ้าเวลาผ่านไป 6 วัน (1 วันก่อนหมด session) และยังไม่เคยส่งการแจ้งเตือน
            if time_passed > (SESSION_TIMEOUT - 86400) and not warning_sent:  # 86400 = 1 วัน
                warning_message = (
                    "⚠️ เซสชันของคุณจะหมดอายุในอีก 1 วัน\n"
                    "หากต้องการคุยต่อ กรุณาพิมพ์ข้อความใดๆ เพื่อต่ออายุเซสชัน"
                )
                line_bot_api.push_message(
                    user_id,
                    TextSendMessage(text=warning_message)
                )
                # ตั้งค่าว่าได้ส่งการแจ้งเตือนแล้ว
                redis_client.setex(
                    f"timeout_warning:{user_id}",
                    86400,  # หมดอายุใน 1 วัน
                    "1"
                )
                logging.info(f"Session timeout warning sent to user: {user_id}")
        
        # อัพเดทเวลาใช้งานล่าสุด
        redis_client.setex(
            f"last_activity:{user_id}",
            SESSION_TIMEOUT,
            str(current_time)
        )
        
    except Exception as e:
        logging.error(f"Error updating last activity for user {user_id}: {str(e)}")

# คำที่บ่งชี้ความเสี่ยง
RISK_KEYWORDS = {
    'high_risk': [
        'ฆ่าตัวตาย', 'ทำร้ายตัวเอง', 'อยากตาย',
        'เกินขนาด', 'overdose', 'od',
        'เลือดออก', 'ชัก', 'หมดสติ'
    ],
    'medium_risk': [
        'นอนไม่หลับ', 'เครียด', 'กังวล',
        'ซึมเศร้า', 'เหงา', 'ท้อแท้'
    ]
}

def assess_risk(message):
    """ประเมินความเสี่ยงจากข้อความ"""
    message = message.lower()
    risk_level = 'low'
    matched_keywords = []
    
    for keyword in RISK_KEYWORDS['high_risk']:
        if keyword in message:
            risk_level = 'high'
            matched_keywords.append(keyword)
    
    if risk_level == 'low':
        for keyword in RISK_KEYWORDS['medium_risk']:
            if keyword in message:
                risk_level = 'medium'
                matched_keywords.append(keyword)
    
    return risk_level, matched_keywords

def save_progress_data(user_id, risk_level, keywords):
    """บันทึกข้อมูลความก้าวหน้า"""
    try:
        progress_data = {
            'timestamp': datetime.now().isoformat(),
            'risk_level': risk_level,
            'keywords': keywords
        }
        redis_client.lpush(f"progress:{user_id}", json.dumps(progress_data))
        redis_client.ltrim(f"progress:{user_id}", 0, 99)  # เก็บแค่ 100 รายการล่าสุด
    except Exception as e:
        logging.error(f"Error saving progress: {str(e)}")

def generate_progress_report(user_id):
    """สร้างรายงานความก้าวหน้า"""
    try:
        progress_data = redis_client.lrange(f"progress:{user_id}", 0, -1)
        if not progress_data:
            return "ยังไม่มีข้อมูลความก้าวหน้า"

        data = [json.loads(item) for item in progress_data]
        
        # วิเคราะห์แนวโน้มความเสี่ยง
        risk_trends = {
            'high': sum(1 for d in data if d['risk_level'] == 'high'),
            'medium': sum(1 for d in data if d['risk_level'] == 'medium'),
            'low': sum(1 for d in data if d['risk_level'] == 'low')
        }
        
        report = (
            "📊 รายงานความก้าวหน้า\n\n"
            f"📅 ช่วงเวลา: {data[-1]['timestamp'][:10]} ถึง {data[0]['timestamp'][:10]}\n"
            f"📈 การประเมินความเสี่ยง:\n"
            f"▫️ ความเสี่ยงสูง: {risk_trends['high']} ครั้ง\n"
            f"▫️ ความเสี่ยงปานกลาง: {risk_trends['medium']} ครั้ง\n"
            f"▫️ ความเสี่ยงต่ำ: {risk_trends['low']} ครั้ง\n"
        )
        return report
    except Exception as e:
        logging.error(f"Error generating progress report: {str(e)}")
        return "ไม่สามารถสร้างรายงานได้"

# เพิ่ม Constants สำหรับการล็อคข้อความ
MESSAGE_LOCK_TIMEOUT = 30  # ระยะเวลาล็อค (วินาที)

def is_user_locked(user_id):
    """ตรวจสอบว่าผู้ใช้ถูกล็อคอยู่หรือไม่"""
    return redis_client.exists(f"message_lock:{user_id}")

def lock_user(user_id):
    """ล็อคผู้ใช้"""
    redis_client.setex(f"message_lock:{user_id}", MESSAGE_LOCK_TIMEOUT, "1")

def unlock_user(user_id):
    """ปลดล็อคผู้ใช้"""
    redis_client.delete(f"message_lock:{user_id}")

# เพิ่ม Constants สำหรับข้อความสถานะ
PROCESSING_MESSAGES = [
    "⌛ กำลังคิดอยู่ค่ะ...",
    "🤔 กำลังประมวลผลข้อความของคุณ...",
    "📝 กำลังเรียบเรียงคำตอบ...",
    "🔄 รอสักครู่นะคะ..."
]

def send_processing_status(user_id, reply_token):
    """ส่งข้อความแจ้งสถานะกำลังประมวลผล"""
    try:
        # ส่งข้อความว่ากำลังประมวลผลทันที
        processing_message = choice(PROCESSING_MESSAGES)
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=processing_message)
        )
        return True
    except Exception as e:
        logging.error(f"Error sending processing status: {str(e)}")
        return False

def send_final_response(user_id, bot_response):
    """ส่งคำตอบสุดท้ายหลังประมวลผลเสร็จ"""
    try:
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=bot_response)
        )
        return True
    except Exception as e:
        logging.error(f"Error sending final response: {str(e)}")
        return False

def start_loading_animation(user_id, duration=60):
    """Display LINE's loading animation to the user
    
    Args:
        user_id (str): The LINE user ID
        duration (int): Duration in seconds (must be 5-60 and multiple of 5)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Always use 60 seconds (maximum allowed by LINE API)
        # This gives maximum time for the API to respond
        duration = 60
        
        # Get access token from env
        access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
        
        # Create request
        url = 'https://api.line.me/v2/bot/chat/loading/start'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }
        payload = {
            'chatId': user_id,
            'loadingSeconds': duration
        }
        
        # Send request
        response = requests.post(url, headers=headers, json=payload)
        
        # Check response - both 200 and 202 are considered success
        # 202 means "Accepted" in HTTP, which is fine for async operations
        if response.status_code in [200, 202]:
            logging.info(f"Loading animation started for user {user_id} for {duration} seconds (status: {response.status_code})")
            return True, duration
        else:
            logging.error(f"Failed to start loading animation: {response.status_code} {response.text}")
            return False, 0
    except Exception as e:
        logging.error(f"Error starting loading animation: {str(e)}")
        return False, 0

def calculate_processing_time(message_length):
    """Calculate approximate processing time based on message length
    
    Args:
        message_length (int): Length of the user message
    
    Returns:
        int: Estimated processing time in seconds (5-60, multiple of 5)
    """
    # Base time for any processing - starting at 5 seconds (minimum required)
    base_time = 5
    
    # Additional time based on message length
    if message_length < 50:
        additional_time = 0
    elif message_length < 150:
        additional_time = 5
    elif message_length < 300:
        additional_time = 10
    else:
        additional_time = 15  # Longer messages get more time
    
    # Total estimated time, ensuring it's a multiple of 5
    total_time = base_time + additional_time
    
    # Return as a valid value for the LINE API
    return total_time

@app.route("/callback", methods=['POST'])
@limiter.limit("10/minute")
def callback():
    # Get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # Get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text

    # ตรวจสอบการล็อค
    if is_user_locked(user_id):
        # Check if we've recently sent a wait notice to avoid spamming
        wait_notice_sent = redis_client.exists(f"wait_notice:{user_id}")
        
        if not wait_notice_sent:
            # Use push_message instead of reply_message to avoid interrupting the animation
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text="กรุณารอระบบประมวลผลข้อความก่อนหน้าให้เสร็จสิ้นก่อนค่ะ")
            )
            
            # Set a flag to avoid sending too many notifications (expires after 10 seconds)
            redis_client.setex(f"wait_notice:{user_id}", 10, "1")
            
        # Simply ignore the message without replying to the webhook
        return

    # ล็อคผู้ใช้ทันทีที่ได้รับข้อความ
    lock_user(user_id)

    try:
        # Record start time for timing the operation
        start_time = time.time()
        
        # Clear any previous wait notice flag
        redis_client.delete(f"wait_notice:{user_id}")
        
        # Start loading animation with maximum duration (60 seconds)
        animation_success, animation_duration = start_loading_animation(user_id)
        
        # If animation fails, use the old method as fallback
        if not animation_success:
            send_processing_status(user_id, event.reply_token)
        
        # ตรวจสอบ timeout
        if check_session_timeout(user_id):
            welcome_back = (
                "เซสชันก่อนหน้าหมดอายุแล้ว เริ่มการสนทนาใหม่นะคะ\n\n"
                "🔄 ต้องการดูประวัติการสนทนาก่อนหน้า พิมพ์: /status\n"
                "❓ ต้องการความช่วยเหลือ พิมพ์: /help"
            )
            send_final_response(user_id, welcome_back)
            unlock_user(user_id)
            return

        # อัพเดทเวลาใช้งานล่าสุด
        update_last_activity(user_id)

        if user_message.startswith('/'):
            handle_command_with_processing(user_id, user_message)
            unlock_user(user_id)
            return

        try:
            # ประมวลผลข้อความและสร้างคำตอบ
            messages = get_chat_session(user_id)
            
            # Load and process history
            optimized_history = db.get_user_history(user_id, max_tokens=10000)
            if len(optimized_history) > 5:
                summary = summarize_conversation_history(optimized_history[5:])
                if summary:
                    messages.append({"role": "assistant", "content": f"สรุปการสนทนาก่อนหน้า: {summary}"})

            # Add user message
            messages.append({"role": "user", "content": user_message})
            
            # Get response from Deepseek
            response = deepseek_client.chat.completions.create(
                model="deepseek-chat",
                messages=[SYSTEM_MESSAGES] + messages,
                **GENERATION_CONFIG
            )
            
            bot_response = response.choices[0].message.content
            messages.append({"role": "assistant", "content": bot_response})

            # Count tokens for the conversation
            token_count = token_counter.count_tokens(user_message + bot_response)

            # ประเมินความเสี่ยง
            risk_level, keywords = assess_risk(user_message)
            save_progress_data(user_id, risk_level, keywords)

            # Save conversation and schedule follow-up
            save_chat_session(user_id, messages)
            db.save_conversation(
                user_id=user_id,
                user_message=user_message,
                bot_response=bot_response,
                token_count=token_count
            )
            schedule_follow_up(user_id, datetime.now())

            # Calculate elapsed time
            elapsed_time = time.time() - start_time
            
            # If we have a successful animation and API response comes back quickly,
            # let's add a small delay to ensure users see the animation for a reasonable time
            # but not too long to cause frustration (minimum 5 seconds, max 15 seconds)
            if animation_success and elapsed_time < 5:
                # Add a small delay to ensure animation is seen for at least 5 seconds
                time.sleep(5 - elapsed_time)
            
            # ส่งการแจ้งเตือนถ้าพบความเสี่ยงสูง
            if risk_level == 'high':
                emergency_message = (
                    "⚠️ ดิฉันพบว่าคุณอาจกำลังมีภาวะเสี่ยง\n"
                    "กรุณาติดต่อสายด่วนช่วยเหลือ:\n"
                    "📞 สายด่วนสุขภาพจิต 1323\n"
                    "📞 สายด่วนยาเสพติด 1165"
                )
                send_final_response(user_id, emergency_message)

            # Send final response
            send_final_response(user_id, bot_response)
            
            # Log the total processing time
            logging.info(f"Total processing time for user {user_id}: {time.time() - start_time:.2f} seconds")

        except Exception as e:
            logging.error(f"Error: {str(e)}", exc_info=True)
            error_message = "ขออภัยค่ะ เกิดข้อผิดพลาดในการประมวลผล"
            send_final_response(user_id, error_message)

    finally:
        # ปลดล็อคผู้ใช้เมื่อเสร็จสิ้นการประมวลผล
        unlock_user(user_id)

def handle_command_with_processing(user_id, command):
    """จัดการคำสั่งพร้อมแสดงสถานะประมวลผล"""
    # For commands, use a shorter animation (10 seconds) since commands process quickly
    animation_success, _ = start_loading_animation(user_id, duration=10)
    
    response_text = None
    
    if command == '/reset':
        db.clear_user_history(user_id)
        redis_client.delete(f"chat_session:{user_id}")
        if user_id in chat_sessions:
            del chat_sessions[user_id]
        response_text = "ลบประวัติการสนทนาทั้งหมดแล้วค่ะ"
    
    elif command == '/help':
        response_text = (
            "สวัสดีค่ะ 👋 ฉันคือน้องใจดี ผู้ช่วยประเมินการใช้สารเสพติดและให้คำปรึกษาแบบ MI\n\n"
            "💬 คุณสามารถ:\n"
            "- เริ่มต้นการประเมินด้วยการตอบคำถามเกี่ยวกับการใช้สาร\n"
            "- ปรึกษาเกี่ยวกับผลกระทบจากการใช้สาร\n"
            "- รับเทคนิคการจัดการ cravings\n\n"
            "📋 คำสั่งที่ใช้ได้:\n"
            "📊 /status - ดูสถานะการประเมิน\n"
            "🚨 /emergency - ดูข้อมูลฉุกเฉินและสายด่วน\n"
            "📩 /feedback - ส่งความคิดเห็นเพื่อพัฒนาระบบ\n"
            "❓ /help - แสดงเมนูช่วยเหลือนี้\n\n"
            "💡 ตัวอย่างการใช้งาน:\n"
            "- \"เริ่มประเมิน\" - เริ่มกระบวนการประเมินการติดสารเสพติด\n"
            "- \"ผลกระทบจากสารเสพติด\" - รับคำแนะนำ\n"
            "- \"จัดการ cravings ยังไง\" - รับเทคนิคการควบคุมตนเอง"
        )
    
    elif command == '/status':
        status_data = {
        'history_count': db.get_user_history_count(user_id),
        'important_count': db.get_important_message_count(user_id),
        'last_interaction': db.get_last_interaction(user_id),
        'current_session': redis_client.exists(f"chat_session:{user_id}") == 1,
        'total_tokens': db.get_total_tokens(user_id) or 0,
        'session_tokens': 0,
        }

        # Calculate session tokens
        session_data = redis_client.get(f"chat_session:{user_id}")
        if session_data:
            history = json.loads(session_data)
            total_session_text = ""
            for msg in history:
                if msg['role'] in ['user', 'assistant']:
                    total_session_text += msg.get('content', '')
            status_data['session_tokens'] = token_counter.count_tokens(total_session_text)

        # Updated status text with key number
        response_text = (
            "📈 สถิติการใช้งาน\n"
            f"▫️ จำนวนการสนทนาที่บันทึก: {status_data['history_count']} ครั้ง\n"
            f"▫️ ข้อความสำคัญ: {status_data['important_count']} รายการ\n"
            f"▫️ อัพเดตล่าสุด: {status_data['last_interaction']}\n"
            f"▫️ สถานะเซสชันปัจจุบัน: {'🟢 ใช้งานอยู่' if status_data['current_session'] else '🔴 ปิดอยู่'}\n"
            f"🔢 Token ทั้งหมดที่ใช้: {status_data['total_tokens']}\n"
            f"🔄 Token ในเซสชันนี้: {status_data['session_tokens']}"
        )
    
    elif command == '/emergency':
        response_text = (
            "🚨 ระบบตอบสนองฉุกเฉิน 🚨\n\n"
            "หากพบสัญญาณต่อไปนี้:\n"
            "- ใช้สารเกินขนาด\n"
            "- มีอาการชัก/หายใจลำบาก\n"
            "- ความคิดทำร้ายตัวเอง\n\n"
            "📞 ติดต่อ:\n"
            "- สายด่วนกรมควบคุมโรค 1422\n"
            "- ศูนย์ปรึกษายาเสพติด 1165\n"
            "- หน่วยกู้ชีพ 1669\n\n"
            "🌐 เว็บไซต์ช่วยเหลือ:\n"
            "https://www.pmnidat.com"
        )
    
    elif command == '/feedback':
        response_text = (
            "🌟 ความคิดเห็นของคุณมีค่าสำหรับเรา\n\n"
            "กรุณาแสดงความคิดเห็นผ่านแบบฟอร์มนี้:\n"
            "https://forms.gle/7K2y21gomWHGcWpq9\n\n"
            "ขอบคุณที่ช่วยพัฒนาน้องใจดีค่ะ 🙏"
        )
    
    elif command == '/progress':
        response_text = generate_progress_report(user_id)
    
    else:
        response_text = "คำสั่งไม่ถูกต้อง ลองพิมพ์ /help เพื่อดูคำสั่งทั้งหมด"

    if response_text:
        send_final_response(user_id, response_text)

# Initialize scheduler
scheduler = BackgroundScheduler()

# Add scheduler jobs
def init_scheduler():
    scheduler.add_job(check_and_send_follow_ups, 'interval', minutes=30)
    scheduler.start()
    logging.info("Scheduler started, checking follow-ups every 30 minutes")
    
    # Proper shutdown handling
    atexit.register(lambda: scheduler.shutdown())
    
# Graceful shutdown handler
def handle_shutdown(sig, frame):
    logging.info("Shutting down application...")
    scheduler.shutdown()
    # Close redis connection
    redis_client.close()
    exit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)

if __name__ == "__main__":
    # Initialize the scheduler before starting the server
    init_scheduler()
    # Start the server
    serve(app, host='0.0.0.0', port=5000)