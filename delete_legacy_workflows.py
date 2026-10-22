import asyncio
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.db.session import AsyncSessionLocal
from backend.services.workflow_seed import seed_default_workflows


async def main():
    async with AsyncSessionLocal() as session:
        await seed_default_workflows(session)
        print("Database updated successfully:")
        print(" - Legacy inactive workflows deleted.")
        print(" - Step_4 body fields updated to dynamic.")


if __name__ == "__main__":
    asyncio.run(main())
