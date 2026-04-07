import structlog
from config import settings

logger = structlog.get_logger()

class PositionManager:
    def __init__(self):
        self.current_position: float = 0.0
    
    def process_fill(self, fill_data: dict):
        """
        HyperLiquid fill event dict updates the current position mathematically.
        """
        side = fill_data.get("side", "")
        sz = float(fill_data.get("sz", 0.0))
        sign = 1 if side.upper() in ["B", "BUY"] else -1
        
        self.current_position += sz * sign
        logger.info("Position internal state updated", position=self.current_position, fill_sz=sz, fill_side=side)
        
    def get_child_orders(self, target: float) -> list:
        """
        Splits the desired delta into child chunks respecting max_order_size config value.
        Outputs a list of signed sizes: positive for buys, negative for sells.
        """
        delta = target - self.current_position
        
        if abs(delta) < 1e-4: # Tolerance margin
            return []
            
        sign = 1 if delta > 0 else -1
        abs_delta = abs(delta)
        max_sz = settings.MAX_ORDER_SIZE
        
        orders = []
        while abs_delta > 1e-4:
            chunk = min(abs_delta, max_sz)
            orders.append(chunk * sign)
            abs_delta -= chunk
            
        return orders
