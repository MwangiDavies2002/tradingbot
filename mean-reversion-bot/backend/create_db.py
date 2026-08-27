import asyncio
import aiomysql
from app.config import settings

async def create_db():
    print("Attempting to create database 'meanrevbot'...")
    try:
        # Connect without specifying a database
        conn = await aiomysql.connect(
            host='localhost',
            port=3306,
            user='root',
            password='',
            autocommit=True
        )
        async with conn.cursor() as cur:
            await cur.execute("CREATE DATABASE IF NOT EXISTS meanrevbot")
        conn.close()
        print("Database 'meanrevbot' created or already exists.")
    except Exception as e:
        print(f"Error creating database: {e}")

if __name__ == "__main__":
    asyncio.run(create_db())
