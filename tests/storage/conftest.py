import os

import pytest_asyncio
from dotenv import load_dotenv

from app.storage.database import Database

load_dotenv()


@pytest_asyncio.fixture
async def db():
    dsn = os.environ["CRAWLER_DATABASE_URL"]
    database = await Database.connect(dsn, min_size=1, max_size=2)
    await database.apply_migrations()
    await database.truncate_all()
    yield database
    await database.truncate_all()
    await database.close()
