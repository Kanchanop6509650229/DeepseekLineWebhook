import re
from typing import Union, List, Dict
import regex  # ใช้ regex แทน re เพื่อรองรับ Unicode ได้ดีกว่า

class TokenCounter:
    def __init__(self):
        self.adjustment_factor = 1.3
        self.history: Dict[str, int] = {}
        
    def count_tokens(self, text: Union[str, List[str]]) -> Union[int, List[int]]:
        if isinstance(text, list):
            return [self._count_single_text(t) for t in text]
        return self._count_single_text(text)
    
    def _count_single_text(self, text: str) -> int:
        # ลบช่องว่างที่ไม่จำเป็น
        text = regex.sub(r'\s+', ' ', text.strip())
        
        # แยกโทเค็นสำหรับภาษาไทยและภาษาอังกฤษ
        # \p{Thai} จับตัวอักษรไทย
        # \p{Latin} จับตัวอักษรอังกฤษ
        # \d จับตัวเลข
        # [^\p{Thai}\p{Latin}\d\s] จับเครื่องหมายต่างๆ
        tokens = regex.findall(r'\p{Thai}+|\p{Latin}+|\d+|[^\p{Thai}\p{Latin}\d\s]', text)
        
        # คำนวณจำนวนโทเค็นโดยประมาณ
        estimated_tokens = int(len(tokens) * self.adjustment_factor)
        
        # เก็บประวัติ
        self.history[text[:50]] = estimated_tokens
        
        return estimated_tokens
    
    def set_adjustment_factor(self, factor: float) -> None:
        if factor <= 0:
            raise ValueError("Adjustment factor ต้องมีค่ามากกว่า 0")
        self.adjustment_factor = factor
    
    def get_history(self) -> Dict[str, int]:
        return self.history
    
    def clear_history(self) -> None:
        self.history = {}
    
    def estimate_cost(self, text: str, price_per_1k_tokens: float = 0.001) -> float:
        token_count = self.count_tokens(text)
        return (token_count / 1000) * price_per_1k_tokens