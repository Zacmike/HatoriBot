from __future__ import annotations
import asyncio
import logging
from HatoriBotPy.cogs.custom_game import ACTIVE_GAMES

log = logging.getLogger(__name__)


async def scheduler_loop(bot):
    while True:
        try:
            await check_active_games(bot)
        except Exception as e:
            log.error(f'Scheduler loop error: {e}')
        await asyncio.sleep(30)
        
        
#Проверка активных игр и выполнение необходимых действий        
async def check_active_games(bot):
    pass


#Запуск фоновой задачи
async def start_scheduler(bot):
    pass

    asyncio.create_task(scheduler_loop(bot))