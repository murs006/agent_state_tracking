CONSTRAINTS = """Constraints:
- Trip window: Oct 1-10, 2025. Valid 7-night spans (try in order until one works):
  • 2025-10-01 → 2025-10-08
  • 2025-10-02 → 2025-10-09
  • 2025-10-03 → 2025-10-10
- Candidate cities: Bangkok (BKK), Dubai (DXB), Reykjavik (REK).
- City choice: check weather for all cities, then select the one that best matches the user preference (warm + rainy).
- Search order per span:
  1. Search flights first. If none then skip to next span.
  2. If flights found, search hotels for the same span.
  3. If both flight and hotel are found and within budget, book them back-to-back in the same turn.
  4. Otherwise move to the next span.
- Span atomicity: never mix flight from one span with hotel from another.
- Stop after one successful booking; otherwise report that nothing fits."""


USER_PROMPT = """Goal: find and, if possible, book a 7-night trip in Oct 2025 that fits the budget and favors warm with lots of rain.

Budget (USD):
- Total max: 1500
- Flight max: 1000
- Hotel max: 500

What to do:
1) Weather check
- Call get_weather_summary for each city (Bangkok, Dubai, Reykjavik) for the entire trip window (2025-10-01 to 2025-10-10).
- The user preferes "warmer weather with lots of rain" and pick the best city based on this criteria.

2) Search and compare (chosen city; try each span in order: 2025-10-01 to 2025-10-08, 2025-10-02 to 2025-10-09, 2025-10-03 to 2025-10-10)
- Flights: list_flights(dest=<CODE>, dep=<START>, ret=<END>). Only use returned id values.
- Hotels: list_hotels(city=<CODE>, checkin=<START>, checkout=<END>). Use hotelId and offerId exactly as returned.
- If a price isn't USD, convert_currency(amount, from_currency, "USD").
- Check budget: flight ≤ 1000, hotel ≤ 500, and flight+hotel ≤ 1500.
- Treat each span independently (no mixing). Only proceed to booking if BOTH a flight and a hotel for the SAME span meet the budget.
- If either flights or hotels are missing for a span, continue to the next span.

3) Book when both fit
- book_flight(flight_id=<id>, departure=<START>, return_date=<END>, dest=<CODE>).
- book_hotel(hotel_id=<hotelId>, offer_id=<offerId>, check_in=<START>, check_out=<END>, city=<CODE>).
- Issue BOTH booking calls for the SAME span in the SAME assistant turn (no single-booking calls).
- Success only if both tools return confirmation_id. If one fails, mark this span as failed and continue to the next span without reusing any booking from this span.

Finish with a short summary (city, dates, and any confirmation_ids)."""


BASELINE_SYSTEM_PROMPT = """You're a vacation planner. Use the tools exactly as defined. Don't invent IDs or data. Keep replies short and only call a tool if it makes progress.\n""" + CONSTRAINTS

STATEFUL_SYSTEM_PROMPT = """You're a vacation planner. Use the tools exactly as defined. Never invent IDs or data. Keep replies short and only call a tool if it makes progress.

- Always check state first.
- weather_checks: prior get_weather_summary calls (records with city, id, summary).
- flights_XX_YY / hotels_XX_YY: record of past list_flights / list_hotels attempts.
  • If the record is empty, you haven't tried that span yet.
  • The result field of the record contains return value of tool call.
  • result == null means no options found. DO NOT retry with same parameters.
- flight_booking / hotel_booking: log successful bookings.

Repeat guard: before any call, check if the same date was already tried. If so, skip unless it was an error and you haven't retried yet.
Goal: find one valid flight+hotel pair for the same span within budget, then book both in the same turn. Never mix spans. If a span fails, move on.

Current States:"""