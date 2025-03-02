import mysql.connector
from datetime import datetime
import logging
from token_counter import TokenCounter
import json

class ChatHistoryDB:
    def __init__(self, connection_pool):
        self.pool = connection_pool
        self.init_db()
        self.counter = TokenCounter()

    def init_db(self):
        """Initialize database tables"""
        conn = self.pool.get_connection()
        cursor = conn.cursor()
        try:
            # ตารางเดิม
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id VARCHAR(255),
                timestamp TIMESTAMP,
                user_message TEXT,
                bot_response TEXT,
                token_count INT,
                important_flag BOOLEAN DEFAULT FALSE,
                INDEX user_idx (user_id)
            )
            ''')

            # เพิ่มตารางใหม่สำหรับเก็บข้อมูลความเสี่ยง
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS risk_assessments (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id VARCHAR(255),
                timestamp TIMESTAMP,
                risk_level ENUM('low', 'medium', 'high'),
                keywords JSON,
                conversation_id INT,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id),
                INDEX user_risk_idx (user_id, risk_level)
            )
            ''')

            # เพิ่มตารางใหม่สำหรับการติดตามผล
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS follow_ups (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id VARCHAR(255),
                scheduled_date TIMESTAMP,
                status ENUM('pending', 'sent', 'failed') DEFAULT 'pending',
                follow_up_type VARCHAR(50),
                sent_date TIMESTAMP NULL,
                INDEX follow_up_idx (user_id, scheduled_date)
            )
            ''')

            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def get_connection(self):
        return self.pool.get_connection()

    def _check_message_importance(self, user_message, bot_response):
        """ตรวจสอบความสำคัญของข้อความ"""
        important_indicators = [
            # การประเมิน
            "ผลการประเมิน",
            "คะแนนการประเมิน",
            
            # ข้อมูลสำคัญ
            "หมายเลขโทรศัพท์",
            "สายด่วน",
            "โรงพยาบาล",
            
            # สัญญาณอันตราย
            "ฆ่าตัวตาย",
            "ทำร้ายตัวเอง",
            "อยากตาย",
            
            # การรักษา
            "การรักษา",
            "จิตแพทย์",
            "นัดหมาย"
        ]
        
        return any(indicator in user_message or indicator in bot_response 
                  for indicator in important_indicators)

    def save_conversation(self, user_id, user_message, bot_response, token_count=None):
        """Save conversation with connection pool"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            important = self._check_message_importance(user_message, bot_response)
            cursor.execute('''
            INSERT INTO conversations 
            (user_id, timestamp, user_message, bot_response, token_count, important_flag)
            VALUES (%s, %s, %s, %s, %s, %s)
            ''', (user_id, datetime.now(), user_message, bot_response, token_count, important))
            conn.commit()
        except Exception as e:
            logging.error(f"Database error: {str(e)}")
            conn.rollback()
        finally:
            cursor.close()
            conn.close()

    def get_user_history(self, user_id, max_tokens=1000):
        """Get optimized conversation history within token limit"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # ดึงประวัติทั้งหมดเรียงจากใหม่ไปเก่า
        cursor.execute('''
        SELECT id, user_message, bot_response 
        FROM conversations
        WHERE user_id = %s
        ORDER BY timestamp DESC
        ''', (user_id,))
        
        all_history = cursor.fetchall()
        
        selected_history = []
        total_tokens = 0
        
        # เลือกข้อความสำคัญก่อน
        for msg in all_history:
            msg_tokens = self.counter.count_tokens(msg[1] + msg[2])
            if total_tokens + msg_tokens > max_tokens:
                break
            if self._check_message_importance(msg[1], msg[2]):
                selected_history.append(msg)
                total_tokens += msg_tokens
        
        # เติมข้อความล่าสุดที่เหลือ
        for msg in all_history:
            if msg in selected_history:
                continue
            msg_tokens = self.counter.count_tokens(msg[1] + msg[2])
            if total_tokens + msg_tokens > max_tokens:
                break
            selected_history.append(msg)
            total_tokens += msg_tokens
        
        conn.close()
        cursor.close()
        return selected_history

    def clear_user_history(self, user_id):
        """ลบประวัติทั้งหมดของผู้ใช้"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM conversations WHERE user_id = %s', (user_id,))
        conn.commit()
        cursor.close()
        conn.close()

    def get_user_history_count(self, user_id):
        """นับจำนวนประวัติของผู้ใช้"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM conversations WHERE user_id = %s', (user_id,))
        count = cursor.fetchone()[0]
        conn.close()
        cursor.close()
        return count
    
    def get_last_interaction(self, user_id):
        """ดึงวันที่สนทนาล่าสุดของผู้ใช้"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT MAX(timestamp) 
                FROM conversations 
                WHERE user_id = %s
            ''', (user_id,))
            result = cursor.fetchone()[0]
            return result.strftime("%Y-%m-%d %H:%M:%S") if result else "ยังไม่มีประวัติ"
        finally:
            cursor.close()
            conn.close()

    def get_important_message_count(self, user_id):
        """นับจำนวนข้อความสำคัญของผู้ใช้"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT COUNT(*) 
                FROM conversations 
                WHERE user_id = %s AND important_flag = TRUE
            ''', (user_id,))
            return cursor.fetchone()[0]
        finally:
            cursor.close()
            conn.close()

    def get_total_tokens(self, user_id):
        try:
            conn = self.pool.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(token_count) FROM conversations WHERE user_id = %s", (user_id,))  
            total = cursor.fetchone()[0]
            return total if total else 0
        except Exception as e:
            logging.error(f"Error fetching total tokens: {e}")
            return 0
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    def save_risk_assessment(self, user_id, risk_level, keywords, conversation_id):
        """บันทึกผลการประเมินความเสี่ยง"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO risk_assessments 
            (user_id, timestamp, risk_level, keywords, conversation_id)
            VALUES (%s, NOW(), %s, %s, %s)
            ''', (user_id, risk_level, json.dumps(keywords), conversation_id))
            conn.commit()
        except Exception as e:
            logging.error(f"Error saving risk assessment: {str(e)}")
            conn.rollback()
        finally:
            cursor.close()
            conn.close()

    def save_follow_up(self, user_id, scheduled_date, follow_up_type):
        """บันทึกการนัดติดตามผล"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO follow_ups 
            (user_id, scheduled_date, follow_up_type)
            VALUES (%s, %s, %s)
            ''', (user_id, scheduled_date, follow_up_type))
            conn.commit()
        except Exception as e:
            logging.error(f"Error saving follow-up: {str(e)}")
            conn.rollback()
        finally:
            cursor.close()
            conn.close()

    def update_follow_up_status(self, follow_up_id, status, sent_date=None):
        """อัพเดทสถานะการติดตามผล"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            if sent_date:
                cursor.execute('''
                UPDATE follow_ups 
                SET status = %s, sent_date = %s
                WHERE id = %s
                ''', (status, sent_date, follow_up_id))
            else:
                cursor.execute('''
                UPDATE follow_ups 
                SET status = %s
                WHERE id = %s
                ''', (status, follow_up_id))
            conn.commit()
        except Exception as e:
            logging.error(f"Error updating follow-up status: {str(e)}")
            conn.rollback()
        finally:
            cursor.close()
            conn.close()

    def get_risk_statistics(self, user_id, days=30):
        """ดึงสถิติความเสี่ยงย้อนหลัง"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT risk_level, COUNT(*) as count
            FROM risk_assessments
            WHERE user_id = %s 
            AND timestamp >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY risk_level
            ''', (user_id, days))
            return dict(cursor.fetchall())
        finally:
            cursor.close()
            conn.close()

    def get_pending_follow_ups(self):
        """ดึงรายการติดตามผลที่ยังไม่ได้ส่ง"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT id, user_id, scheduled_date, follow_up_type
            FROM follow_ups
            WHERE status = 'pending'
            AND scheduled_date <= NOW()
            ''')
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()