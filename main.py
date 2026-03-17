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
    try:
        from waitress import serve
        serve(app, host='0.0.0.0', port=port, threads=4)
    except ImportError:
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)


async def run_bot():
    """Run Discord bot + device bots."""
    # Expose the event loop to device_manager so Flask threads can schedule coroutines
    try:
        from device_manager import device_manager, set_loop
        set_loop(asyncio.get_running_loop())
        asyncio.create_task(device_manager.start_all())
        print('📻 Device manager uruchomiony')
    except Exception as e:
        print(f'⚠️  Device manager nie wystartował: {e}')

    try:
        from discord_bot import bot
    except Exception as e:
        print(f'⚠️  Nie można załadować bota Discord: {e}')
        print('💡 Dashboard jest aktywny na porcie 5000.')
        while True:
            await asyncio.sleep(3600)

    token = os.environ.get('DISCORD_TOKEN')
    if not token:
        print('⚠️  Brak DISCORD_TOKEN – bot Discord nie wystartuje. Tylko dashboard będzie aktywny.')
        # Keep the coroutine alive so the dashboard thread keeps running
        while True:
            await asyncio.sleep(3600)
    
    print('🤖 Bot startuje...')
    try:
        await bot.start(token)
    except Exception as e:
        print(f'❌ Błąd uruchamiania bota: {e}')
        print('💡 Aby naprawić:')
        print('1. Wejdź na: https://discord.com/developers/applications')
        print('2. Kliknij swoją aplikację → Bot → Scroll do "Privileged Gateway Intents"')
        print('3. Włącz: Message Content Intent, Server Members Intent, Presence Intent')
        print('4. Kliknij Save Changes')
        print('⏳ Dashboard jest aktywny – spróbuj ponownie po włączeniu uprawnień.')
        # Keep running the dashboard
        while True:
            await asyncio.sleep(3600)


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
