import re
import json
from typing import Union, List, Dict

class TokenCounter:
    def __init__(self, model_name="deepseek-chat"):
        self.model_name = model_name
        self.history = {}
        
        # Try to load tiktoken for accurate counting
        try:
            import tiktoken
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
            self.use_tiktoken = True
            print("Using tiktoken for accurate token counting")
        except (ImportError, ModuleNotFoundError):
            self.use_tiktoken = False
            print("Tiktoken not found, using approximate token counting")
    
    def count_tokens(self, text: Union[str, List[str]]) -> Union[int, List[int]]:
        """Count tokens in text or list of texts"""
        if isinstance(text, list):
            return [self._count_single_text(t) for t in text]
        return self._count_single_text(text)
    
    def _count_single_text(self, text: str) -> int:
        """Count tokens in a single text string"""
        if not text:
            return 0
            
        # Use cached value if available
        text_hash = hash(text[:100])
        if text_hash in self.history:
            return self.history[text_hash]
            
        # Use tiktoken if available
        if self.use_tiktoken:
            token_count = len(self.tokenizer.encode(text))
        else:
            # Advanced multi-language token estimator
            # Remove excess whitespace
            text = re.sub(r'\s+', ' ', text.strip())
            
            # Handle Thai, English, and other characters
            thai_chars = len(re.findall(r'[\u0E00-\u0E7F]', text))
            english_words = len(re.findall(r'[a-zA-Z]+', text))
            numbers = len(re.findall(r'[0-9]+', text))
            symbols = len(re.findall(r'[^\w\s\u0E00-\u0E7F]', text))
            
            # Thai is approximately 1 token per character
            # English is approximately 0.75 tokens per word
            # Numbers and symbols count as approximately 1 token per group
            token_count = int(thai_chars + (english_words * 0.75) + numbers + symbols)
            token_count = max(1, token_count)  # Ensure at least 1 token
        
        # Cache result (limited to 1000 items)
        if len(self.history) > 1000:
            self.history.clear()
        self.history[text_hash] = token_count
        
        return token_count
    
    def count_message_tokens(self, messages):
        """Count tokens in a complete message array for API calls"""
        if not messages:
            return 0
            
        # Each message has 4 tokens overhead (+2 for the conversation)
        base_tokens = 2
        
        for message in messages:
            # Add content tokens
            content = message.get("content", "")
            base_tokens += self.count_tokens(content)
            
            # Add role tokens (~4 per message)
            base_tokens += 4
            
        return base_tokens