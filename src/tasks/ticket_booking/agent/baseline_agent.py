from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import MessagesState, StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition

from ..tools.flight_tool import list_flights
from ..tools.hotel_tool import list_hotels
from ..tools.weather_tool import get_weather_summary
from ..tools.booking_tool import book_hotel, book_flight
from ..tools.currency_tool import convert_currency
from .prompts import BASELINE_SYSTEM_PROMPT, USER_PROMPT

llm = ChatOpenAI(
    base_url="http://localhost:8000/v1",
    api_key="EMPTY",
    model="Qwen/Qwen3-32B",
)

tools = [list_flights, list_hotels, get_weather_summary, book_hotel, book_flight, convert_currency]
llm = llm.bind_tools(tools, parallel_tool_calls=False)

sys_msg = SystemMessage(content=BASELINE_SYSTEM_PROMPT)


def _build_graph():
    """Compile and cache the baseline graph"""
    builder = StateGraph(MessagesState)
    
    def assistant(state: MessagesState):
        return {"messages": [llm.invoke([sys_msg] + state["messages"])]}

    builder.add_node("assistant", assistant)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "assistant")
    builder.add_conditional_edges("assistant", tools_condition)
    builder.add_edge("tools", "assistant")
    return builder.compile()


graph = _build_graph()


def run_baseline_trial(user_prompt: str | None = None, recursion_limit: int = 50, live: bool = False):
    messages = [HumanMessage(content=user_prompt or USER_PROMPT)]
    if not live:
        return graph.invoke({"messages": messages}, {"recursion_limit": recursion_limit})

    # Stream node updates as they occur
    final = None
    for update in graph.stream(
        {"messages": messages},
        {"recursion_limit": recursion_limit},
        stream_mode="updates",
    ):
        # Each update is a dict keyed by node name
        node_name = next(iter(update.keys()))
        node_payload = update[node_name]

        if "messages" in node_payload and node_payload["messages"]:
            last = node_payload["messages"][-1]
            try:
                last.pretty_print()
            except AttributeError:
                print(last)

        if "messages" in node_payload:
            final = node_payload

    return final if final is not None else {"messages": []}

if __name__ == "__main__":
    res = run_baseline_trial(recursion_limit=50, live=True)
