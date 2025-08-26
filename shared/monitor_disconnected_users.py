import asyncio
from adapters.whatsapp.wwebjs.wwebjs_adapter import get_status

async def monitor_disconnected_users():
    users = get_status()
    for user in users:
        if user["ready"] == False:
            print(f"User {user['userId']} is disconnected")
            
async def monitor_disconnected_users_loop():
    while True:
        try:
            await monitor_disconnected_users()
        except Exception as e:
            print(f"Loop error: {e}")
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(monitor_disconnected_users_loop())
