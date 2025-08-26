from agents.echo.core import echo_agent
from shared import time
import uuid
import asyncio
import time as pytime
from shared.result import getAgentMessage

USER_PROMPT = """
Context:
Now is: {now}

User message:
{user_message}

"""

async def run_action_agent(userMessage: str, config: dict):
    userPrompt = USER_PROMPT.format(
        now=time.to_user_timezone(time.utcnow()).strftime('%Y-%m-%d %H:%M:%S'),
        user_message=userMessage
    )

    input = {"messages":[
        {"content": userPrompt, "role": "user"},
    ]}

    return await echo_agent.ainvoke(input, config)

if __name__ == "__main__":
    async def test(userMessage: str, threadId: str):
        start_time = pytime.perf_counter()
        result = await run_action_agent(userMessage, {
            "configurable": {
                "user_id": "12sdffsdf3",
                "user_name": "test",
                "thread_id": threadId,
                "chat_id": "123",
            }
        })
        duration = pytime.perf_counter() - start_time
        print(f"[DURATION] Agent completed in {duration:.2f} seconds")
        print("result: ", getAgentMessage(result))

    from datetime import datetime, time as dtime, timedelta
    from zoneinfo import ZoneInfo

    def get_tomorrow_at_8am() -> datetime:
        tz = ZoneInfo("Asia/Jerusalem")
        today_local = datetime.now(tz)
        tomorrow = today_local + timedelta(days=1)
        tomorrow_8am = datetime.combine(tomorrow.date(), dtime(8, 0), tzinfo=tz)
        return tomorrow_8am

    threadId = uuid.uuid4().hex
    message = "תזכיר לי להתקשר לחיים מחר ב8"
    asyncio.run(test(message, threadId))
    now = get_tomorrow_at_8am()
    
    threadId = uuid.uuid4().hex
    message = "תזכיר לי להתקשר לחיים מחר ב8"
    asyncio.run(test(message, threadId))

    message = "תזיז את חיים לתשע"
    asyncio.run(test(message, threadId))

    message = "תבטל את החיים"
    asyncio.run(test(message, threadId))


    threadId = uuid.uuid4().hex
    message = "תשלח עכשיו הודעה לעירית שאני אוהב אותה"
    asyncio.run(test(message, threadId))

    message = "972522486836"
    asyncio.run(test(message, threadId))