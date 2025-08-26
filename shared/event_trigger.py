from shared import time
from datetime import timedelta
import asyncio
from green_api.send import send_message_from_me
from adapters.whatsapp.dialog360.webhook import adapter
from store.action_item_store import ActionItemStore
from store.scheduled_messages_store import ScheduledMessageStore
from store.delivery_mng_store import SendingStatusStore

''' echo chat id = '972552534936@c.us' '''

MAX_RETRIES = 5
ECHO_CHAT_ID = "972552534936@c.us"


async def trigger_events():
    now = time.utcnow()
    start = now - timedelta(minutes=10)
    end = now

    # --- ActionItem handling ---
    action_store = ActionItemStore()
    action_triggerables = action_store.query_action_items(start, end)

    print(f"🔔 Found {len(action_triggerables)} actions due between {start.isoformat()} and {end.isoformat()}")

    for trig in action_triggerables:
        status_store = SendingStatusStore(trig['user_id'])
        status_store.create_or_get(trig['item_id'], "action_item")
        status_store.update(trig['item_id'], "action_item", last_status="sending")

        try:
            success = await adapter.send_message_360dialog(trig['user_id'], trig['title'])
        except Exception as e:
            print(f"❌ ActionItem send exception for {trig['item_id']}: {e}")
            success = False

        if success:
            status_store.reset_retry(trig['item_id'], "action_item")
            status_store.update(trig['item_id'], "action_item", last_status="completed")
            action_store.update_status(trig['user_id'], trig['item_id'], "completed")
        else:
            retries = status_store.increment_retry(trig['item_id'], "action_item")
            status_store.update(trig['item_id'], "action_item", last_status="failed")
            action_store.update_status(trig['user_id'], trig['item_id'], "failed")

        await asyncio.sleep(0.2)

    # --- ScheduledMessage handling ---
    sched_store = ScheduledMessageStore()
    sched_triggerables = sched_store.query_scheduled_messages(start, end)

    print(f"🔔 Found {len(sched_triggerables)} scheduled messages due between {start.isoformat()} and {end.isoformat()}")

    for trig in sched_triggerables:
        status_store = SendingStatusStore(trig['user_id'])
        status_store.create_or_get(trig['item_id'], "scheduled_message")
        status_store.update(trig['item_id'], "scheduled_message", last_status="sending")

        try:
            success = send_message_from_me(trig['user_id'], trig['recipient_chat_id'], trig['message'])
        except Exception as e:
            print(f"❌ ScheduledMessage send exception for {trig['item_id']}: {e}")
            success = False

        if success:
            status_store.reset_retry(trig['item_id'], "scheduled_message")
            status_store.update(trig['item_id'], "scheduled_message", last_status="completed")
            sched_store.update_status(trig['item_id'], "completed")
        else:
            retries = status_store.increment_retry(trig['item_id'], "scheduled_message")
            if retries >= MAX_RETRIES:
                msg = (
                    "הודעה זו לא נשלחה בהצלחה מחשבונך לאחר מספר ניסיונות.\n\n"
                    f"נמען: {trig.get('recipient_name', 'לא ידוע')} ({trig.get('recipient_chat_id')})\n"
                    f"טקסט ההודעה:\n{trig['message']}\n\n"
                    "אנא שלח את ההודעה ידנית או עדכן אותנו אם תרצה לנסות שוב."
                )
                try:
                    await adapter.send_message_360dialog(trig['user_id'], msg)

                    print(f"⚠️ Escalated scheduled message {trig['item_id']} to Echo after {retries} retries")
                except Exception as e:
                    print(f"❌ Echo fallback send failed for {trig['item_id']}: {e}")
                status_store.update(
                    trig['item_id'],
                    "scheduled_message",
                    last_status="failed_echo",
                    last_error="max retries exceeded"
                )
                sched_store.update_status(trig['item_id'], "failed_echo")
            else:
                status_store.update(trig['item_id'], "scheduled_message", last_status="failed")
                sched_store.update_status(trig['item_id'], "failed")

        await asyncio.sleep(0.2)


async def trigger_events_loop():
    while True:
        try:
            await trigger_events()
        except Exception as e:
            print(f"Loop error: {e}")
        await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(trigger_events())
