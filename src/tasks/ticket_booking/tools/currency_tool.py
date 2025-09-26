import random
from typing import Dict, Any

def convert_currency(amount: float, from_currency: str, to_currency: str) -> Dict[str, Any]:
    """
    Converts amount from one currency to another.
    
    Args:
        amount: The amount to convert
        from_currency: Source currency code (e.g., "THB")
        to_currency: Target currency code (e.g., "USD")
    
    Returns:
        Dictionary with converted amount and exchange rate
    """
    # Base exchange rates
    rates = {
        "THB_USD": 0.028,
        "USD_THB": 35.71,
        "USD_USD": 1.0,
        "THB_THB": 1.0,
        # Dubai (AED) conversions
        "AED_USD": 0.272,
        "USD_AED": 3.67,
        "AED_THB": 9.72,
        "THB_AED": 0.103,
        "AED_EUR": 0.249,
        "EUR_AED": 4.02,
        "AED_AED": 1.0,
        # Ireland (EUR) conversions
        "EUR_USD": 1.09,
        "USD_EUR": 0.918,
        "EUR_THB": 38.92,
        "THB_EUR": 0.026,
        "EUR_EUR": 1.0,
    }
    
    rate_key = f"{from_currency}_{to_currency}"
    if rate_key not in rates:
        return {"error": f"Conversion rate not available for {from_currency} to {to_currency}"}
    
    # Simulate dynamic pricing: fluctuate rate by +/- 5%
    base_rate = rates[rate_key]
    fluctuation = random.uniform(-0.05, 0.05)
    dynamic_rate = round(base_rate * (1 + fluctuation), 4)
    
    converted_amount = round(amount * dynamic_rate, 2)
    
    return {
        "original_amount": amount,
        "original_currency": from_currency,
        "converted_amount": converted_amount,
        "target_currency": to_currency,
        "exchange_rate": dynamic_rate
    }