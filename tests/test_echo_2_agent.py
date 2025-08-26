import time
from collections import defaultdict
from agents.echo_2.core import echo_2_agent

# Sample test messages in Hebrew
TEST_CASES = [
    ("תזכיר לי להתקשר למרפאה מחר בבוקר", "process_self_action"),
    ("קבע משימה לסיים את המצגת עד יום שני", "process_self_action"),
    ("צור אירוע לשיעור יוגה ביום שישי בשש בערב. בלי מיקום.בלי משתתפים", "process_event"),
    ("הוסף תזכורת לקנות מצרכים הערב", "process_self_action"),
    ("תכנון משימה לבדוק את החוזה בשבוע הבא", "process_self_action"),

    ("שלח לנועה הודעה מחר ב-8: 'בהצלחה במבחן!'", "process_contact_message"),
    ("תזמן הודעה לקבוצת הצוות: 'הפגישה מתחילה בעוד 10 דקות'", "process_contact_message"),
    ("תגיד לדניאל יום הולדת שמח ביום שישי הבא", "process_contact_message"),
    ("תזכיר לתמר על הסדנה בשבוע הבא", "process_contact_message"),
    ("שלח הודעה לאמא ביום ראשון בבוקר: 'אוהב אותך!'", "process_contact_message"),

    ("מה אמרתי לאייל לגבי התקציב?", "search_chat_history"),
    ("תזכיר לי מה הבטחתי בקבוצת משפחה", "search_chat_history"),
    ("מה הייתה השיחה האחרונה שלנו עם אמיר?", "search_chat_history"),
    ("מה שאלתי על ההופעה בשבוע שעבר?", "search_chat_history"),
    ("מה היה השם של המקום שדיברנו עליו בצ'אט הזה?", "search_chat_history"),

    ("ספר לי בדיחה על פינגווינים", "fallback"),
]


from langchain_core.messages import AIMessage, HumanMessage

def extract_tool_and_command(messages):
    tool_used = None
    command_used = None
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for call in msg.tool_calls:
                tool_used = call.get("name")
                args = call.get("args", {})
                command_used = args.get("command")
    return tool_used, command_used

USER_PROMPT = """
Context:
Now is: {now}
Input source: {input_source}

User message:
{user_message}
"""


def run_tests():
    agent = echo_2_agent

    cold_start = time.time()
    agent.invoke(
        {"messages": [{"role": "user", "content": "test"}]},
        {"configurable": {
            "user_id": "test",
            "user_name": "tester",
            "recent_chats": {},
            "contacts": {},
            "name2chat_id": {},
            "thread_id": "coldstart"
        }}
    )
    cold_duration = time.time() - cold_start
    print(f"Cold start duration: {cold_duration:.2f}s\n")

    passed = 0
    failed = 0
    total_duration = 0.0

    tool_durations = defaultdict(list)

    for idx, (message, expected_tool) in enumerate(TEST_CASES[2:3]):
        start = time.time()
        # First turn
        # ---- Build prompt with input_source ----
        import datetime
        userPrompt = USER_PROMPT.format(
            now=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            user_message=message,
            input_source="text",   # 👈 include in SYSTEM_PROMPT context
        )

        input = {
            "messages": [
                {"content": userPrompt, "role": "user"},
            ]
        }

        result = agent.invoke(
            input,
            config={"configurable": {
                "user_id": "123",
                "user_name": "test",
                "thread_id": "threadId",
                "name2chat_id": {},
                "recent_chats": {},
                "contacts": {},
                "chat_id": "123",
            }}
        )
        print(result)
        tool_used, command_used = extract_tool_and_command(result["messages"])

        # If no tool yet but confirmation asked → simulate "כן" 
        if not tool_used:
            assistant_texts = [m.content for m in result.get("messages", []) if isinstance(m, AIMessage)]
            if any(t and "לאשר" in t for t in assistant_texts):
                second = agent.invoke(
                    {"messages": [
                        {"role": "user", "content": message},
                        {"role": "assistant", "content": assistant_texts[-1]},
                        {"role": "user", "content": "כן"}
                    ]},
                    {"configurable": {
                        "user_id": "123",
                        "user_name": "test",
                        "thread_id": "threadId",
                        "name2chat_id": {},
                        "contacts": {},
                        "recent_chats": {},
                        "chat_id": "123",
                    }}
                )
                tool_used, command_used = extract_tool_and_command(second.get("messages", []))

        duration = time.time() - start
        total_duration += duration
        tool_durations[tool_used or "none"].append(duration)

        if tool_used == expected_tool:
            print(f"✅ [{idx+1}] PASS | {tool_used} | {message} ({duration:.2f}s) | command={command_used}")
            passed += 1
        else:
            print(f"❌ [{idx+1}] FAIL | Expected: {expected_tool}, Got: {tool_used} | {message} ({duration:.2f}s)")
            failed += 1
            print(result["messages"])

        result = agent.invoke(
            {"messages": [{"role": "user", "content": "כן"}]},
            config={"configurable": {
                "user_id": "123",
                "user_name": "test",
                "thread_id": "threadId",
                "name2chat_id": {},
                "contacts": {},
                "recent_chats": {},
                "chat_id": "123",
            }}
        )
        print(result)

    print(f"\nSummary: {passed} passed, {failed} failed")
    print(f"Overall Avg duration: {total_duration / len(TEST_CASES):.2f}s")

    print("\nAverage duration per tool:")
    for tool, durations in tool_durations.items():
        avg = sum(durations) / len(durations)
        print(f"  {tool:20}: {avg:.2f}s")


if __name__ == "__main__":
    run_tests()
