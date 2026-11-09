import asyncio


async def send_email(to: str, subject: str) -> None:
    await asyncio.sleep(0.1)  # stand-in for the real SMTP call
    print(f"sent {subject} to {to}")


async def notify_all(users: list[str], subject: str) -> int:
    for u in users:
        send_email(u, subject)
    return len(users)
