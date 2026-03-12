"""
Baza Mops – Discord Bot z systemem rang i dashboardem.
Uruchom przez: python main.py
"""
import os
import threading
import asyncio
from dotenv import load_dotenv

load_dotenv()

import database as db


def run_dashboard():
    """Run Flask dashboard in a background thread."""
    from dashboard.app import app
    port = int(os.environ.get('PORT', 5000))
    print(f'🌐 Dashboard startuje na porcie {port}')
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)


async def run_bot():
    """Run Discord bot."""
    from discord_bot import bot
    token = os.environ.get('DISCORD_TOKEN')
    if not token:
        print('⚠️  Brak DISCORD_TOKEN – bot Discord nie wystartuje. Tylko dashboard będzie aktywny.')
        # Keep the coroutine alive so the dashboard thread keeps running
        while True:
            await asyncio.sleep(3600)
    print('🤖 Bot startuje...')
    await bot.start(token)


def main():
    db.init_db()
    print('✅ Baza danych zainicjowana')

    # Start dashboard in daemon thread
    dash_thread = threading.Thread(target=run_dashboard, daemon=True, name='Dashboard')
    dash_thread.start()

    # Run bot in main event loop
    asyncio.run(run_bot())


if __name__ == '__main__':
    main()
