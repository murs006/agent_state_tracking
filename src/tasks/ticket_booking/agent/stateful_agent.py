from __future__ import annotations
import json
from typing import List, Dict, TypedDict, Any
from copy import deepcopy

from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

from ..tools.flight_tool import list_flights
from ..tools.hotel_tool import list_hotels
from ..tools.weather_tool import get_weather_summary
from ..tools.booking_tool import book_hotel, book_flight
from ..tools.currency_tool import convert_currency
from .prompts import STATEFUL_SYSTEM_PROMPT, CONSTRAINTS, USER_PROMPT
from ..utils import _is_correct_span_for_tool, _span_suffix, SPAN_MAP


class State(TypedDict, total=False):
    weather_checks: List[Dict[str, Any]]
    selected_city: str | None
    flights_01_08: List[Dict[str, Any]]
    hotels_01_08: List[Dict[str, Any]]
    flights_02_09: List[Dict[str, Any]]
    hotels_02_09: List[Dict[str, Any]]
    flights_03_10: List[Dict[str, Any]]
    hotels_03_10: List[Dict[str, Any]]
    flight_booking: Dict[str, Any] | None
    hotel_booking: Dict[str, Any] | None


class GraphState(TypedDict):
    state: State
    messages: List[Any]


TOOLS = [
    get_weather_summary,
    list_flights,
    list_hotels,
    convert_currency,
    book_flight,
    book_hotel,
]
CITY_CODE_BY_NAME = {"Bangkok": "BKK", "Dubai": "DXB", "Reykjavik": "REK"}


def assistant(gs: GraphState):
    st = gs["state"].copy()

    sys = SystemMessage(
        content=(
            STATEFUL_SYSTEM_PROMPT
            + "\n"
            + json.dumps(st, ensure_ascii=False)
            + "\n"
            + CONSTRAINTS
        )
    )

    context = gs["messages"][-10:] if len(gs["messages"]) >= 10 else gs["messages"]
    reply = llm.invoke([sys] + context)

    return {"state": st, "messages": gs["messages"] + [reply]}


llm = ChatOpenAI(
    base_url="http://localhost:8000/v1",
    api_key="EMPTY",
    model="Qwen/Qwen3-32B",
).bind_tools(TOOLS, parallel_tool_calls=False)


def pre_tool_update(gs: GraphState):
    last_msg = gs["messages"][-1]
    new_state = gs["state"].copy()

    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        for tc in last_msg.tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            tool_id = tc["id"]

            if tool_name == "get_weather_summary":
                city = tool_args.get("city")
                if isinstance(city, str) and city:
                    new_state.setdefault("weather_checks", []).append(
                        {"city": city, "id": tool_id, "summary": None}
                    )

            elif tool_name == "list_flights":
                dest = tool_args.get("dest")
                dep = tool_args.get("dep")
                ret = tool_args.get("ret")

                suf = _span_suffix(dep, ret)
                if suf:
                    key = f"flights{suf}"
                    new_state.setdefault(key, []).append(
                        {
                            "destination": dest,
                            "departure": dep,
                            "return": ret,
                            "id": tool_id,
                            "result": None,
                        }
                    )

                if (
                    isinstance(dest, str)
                    and dest in CITY_CODE_BY_NAME.values()
                    and not new_state.get("selected_city")
                ):
                    new_state["selected_city"] = dest

            elif tool_name == "list_hotels":
                city = tool_args.get("city")
                checkin = tool_args.get("checkin")
                checkout = tool_args.get("checkout")
                suf = _span_suffix(checkin, checkout)

                if suf:
                    key = f"hotels{suf}"
                    new_state.setdefault(key, []).append(
                        {
                            "city": city,
                            "checkin": checkin,
                            "checkout": checkout,
                            "id": tool_id,
                            "result": None,
                        }
                    )

                if (
                    isinstance(city, str)
                    and city in CITY_CODE_BY_NAME.values()
                    and not new_state.get("selected_city")
                ):
                    new_state["selected_city"] = city

    return {"state": new_state}


def post_tool_update(gs: GraphState):
    msgs = gs["messages"]
    new_state = gs["state"].copy()

    # collect all ToolMessages appended in this tools step
    tail = []
    i = len(msgs) - 1
    while i >= 0 and isinstance(msgs[i], ToolMessage):
        tail.append(msgs[i])
        i -= 1
    tail.reverse()

    def _parse(c):
        if isinstance(c, (dict, list)):
            return c
        try:
            return json.loads(c)
        except Exception:
            return None

    for tm in tail:
        parsed = _parse(tm.content)
        tool_id = tm.tool_call_id

        if tm.name == "get_weather_summary":
            summ = parsed.get("summary") if isinstance(parsed, dict) else None
            if isinstance(summ, str):
                for e in new_state.get("weather_checks", []):
                    if e.get("id") == tool_id and e.get("summary") is None:
                        e["summary"] = summ
                        break

        if tm.name == "list_flights":
            for suf in SPAN_MAP.values():
                key = f"flights{suf}"
                for e in new_state.get(key, []):
                    if e["id"] == tool_id and e["result"] is None:
                        e["result"] = "No flights found" if not parsed else parsed[0]
                        break

        elif tm.name == "list_hotels":
            for suf in SPAN_MAP.values():
                key = f"hotels{suf}"
                for e in new_state.get(key, []):
                    if e["id"] == tool_id and e["result"] is None:
                        e["result"] = "No hotels found" if not parsed else parsed[0]
                        break

        if tm.name == "book_flight" and _is_correct_span_for_tool(
            "book_flight", parsed
        ):
            new_state["flight_booking"] = parsed

        elif tm.name == "book_hotel" and _is_correct_span_for_tool(
            "book_hotel", parsed
        ):
            new_state["hotel_booking"] = parsed

    return {"state": new_state}


def custom_tools_condition(gs: GraphState) -> str:
    last_msg = gs["messages"][-1]
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        return "pre_tool"
    return "__end__"


g = StateGraph(GraphState)
g.add_node("assistant", assistant)
g.add_node("pre_tool", pre_tool_update)
g.add_node("tools", ToolNode(TOOLS))
g.add_node("post_tool", post_tool_update)

g.add_edge(START, "assistant")
g.add_conditional_edges(
    "assistant", custom_tools_condition, {"pre_tool": "pre_tool", "__end__": END}
)
g.add_edge("pre_tool", "tools")
g.add_edge("tools", "post_tool")
g.add_edge("post_tool", "assistant")

graph = g.compile()


initial_state = {
    "weather_checks": [],
    "selected_city": None,
    "flights_01_08": [],
    "hotels_01_08": [],
    "flights_02_09": [],
    "hotels_02_09": [],
    "flights_03_10": [],
    "hotels_03_10": [],
    "flight_booking": None,
    "hotel_booking": None,
}


def run_stateful_trial(
    user_prompt: str | None = None, recursion_limit: int = 40, live: bool = False
):
    gs: GraphState = {
        "messages": [HumanMessage(content=user_prompt or USER_PROMPT)],
        "state": deepcopy(initial_state),
    }

    # Accumulate all messages observed during streaming
    all_messages = list(gs["messages"])
    final_state: Dict[str, Any] | None = None

    def _msg_sig(m):
        # avoid dupes when LangGraph re-emits windows
        return (
            getattr(m, "type", type(m).__name__),
            getattr(m, "tool_call_id", None),
            getattr(m, "name", None),
            getattr(m, "id", None),
            repr(getattr(m, "content", ""))[:2048],
        )

    seen = {_msg_sig(m) for m in all_messages}

    for update in graph.stream(
        gs, {"recursion_limit": recursion_limit}, stream_mode="updates"
    ):
        node_payload = next(iter(update.values()))
        if isinstance(node_payload, dict) and "messages" in node_payload:
            for msg in node_payload["messages"]:
                sig = _msg_sig(msg)
                if sig not in seen:
                    all_messages.append(msg)
                    seen.add(sig)
            final_state = node_payload

            if live:
                last = node_payload["messages"][-1]
                try:
                    last.pretty_print()
                except Exception:
                    print(last)

    # Fallback if nothing streamed
    if final_state is None:
        final_state = graph.invoke(gs, {"recursion_limit": recursion_limit})

    out = dict(final_state)
    out["messages"] = all_messages
    return out


if __name__ == "__main__":
    res = run_stateful_trial(recursion_limit=40, live=True)
    print("\n── Final structured state ──")
    print(json.dumps(res["state"], indent=2))