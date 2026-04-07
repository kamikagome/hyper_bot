def calculate_hedging_slippage(fill_price: float, binance_microprice: float, side: str) -> float:
    """
    Slippage against Binance exact microprice.
    For a BUY, true cost is fill_price - microprice. (positive if we paid more)
    For a SELL, true cost is microprice - fill_price.
    """
    sign = 1 if side.upper() == "BUY" else -1
    return float((fill_price - binance_microprice) * sign)

def calculate_implementation_shortfall(fill_price: float, binance_ewma_adjusted: float, side: str) -> float:
    """
    Cost of execution relative to our theoretical target placement price at decision time.
    """
    sign = 1 if side.upper() == "BUY" else -1
    return float((fill_price - binance_ewma_adjusted) * sign)

def beta_adjusted_pnl(raw_pnl: float, btc_return_in_window: float, btc_beta: float, position_size: float) -> float:
    """
    Subtract market directional effect from our PnL.
    If we are long (position_size > 0), and BTC goes up, we deduct the expected market gain.
    """
    return float(raw_pnl - (btc_return_in_window * btc_beta * position_size))
