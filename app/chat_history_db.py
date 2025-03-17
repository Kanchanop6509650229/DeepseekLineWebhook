"""
โมดูลฐานข้อมูลประวัติการแชทสำหรับแชทบอท 'ใจดี'
"""
from datetime import datetime
import psycopg2
import logging
from .utils import safe_db_operation
from .token_counter import TokenCounter

@safe_db_operation
def get_user_history(self, user_id, max_tokens=10000):
    """Optimized query for fetching user history"""
    conn = self.get_connection()
    try:
        cursor = conn.cursor()
        
        # First get important messages using a single query with indexing
        cursor.execute('''
            SELECT c.id, c.timestamp, c.user_message, c.bot_response, c.token_count 
            FROM conversations c
            WHERE c.user_id = %s
            ORDER BY 
                c.important_flag DESC, -- Important messages first
                c.timestamp DESC -- Then most recent
            LIMIT 50 -- Reasonable limit to process
        ''', (user_id,))
        
        all_messages = cursor.fetchall()
        
        # Apply token limit
        selected_history = []
        total_tokens = 0
        
        for msg in all_messages:
            msg_tokens = msg[4] or self.counter.count_tokens(msg[2] + msg[3])
            if total_tokens + msg_tokens <= max_tokens:
                selected_history.append((msg[0], msg[2], msg[3]))
                total_tokens += msg_tokens
            else:
                break
                
        return selected_history
    finally:
        cursor.close()
        conn.close()

@safe_db_operation
def save_batch_conversations(self, conversations):
    """Batch save multiple conversations for performance"""
    if not conversations:
        return True
        
    conn = self.get_connection()
    try:
        cursor = conn.cursor()
        
        # Prepare batch values
        values = []
        for conv in conversations:
            important = self._check_message_importance(
                conv['user_message'], conv['bot_response']
            )
            
            values.append((
                conv['user_id'],
                conv.get('timestamp', datetime.now()),
                conv['user_message'],
                conv['bot_response'],
                conv.get('token_count', 0),
                important
            ))
        
        # Execute batch insert
        cursor.executemany('''
            INSERT INTO conversations 
            (user_id, timestamp, user_message, bot_response, token_count, important_flag)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', values)
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()