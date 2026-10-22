import asyncio
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import delete, select
from backend.db.session import AsyncSessionLocal
from backend.models.workflow import Workflow


async def delete_legacy():
    slugs = ["sspa-complaint-intake", "sspa-complaint-resolve"]
    async with AsyncSessionLocal() as session:
        # Check existing
        stmt = select(Workflow).where(Workflow.slug.in_(slugs))
        result = await session.execute(stmt)
        existing = result.scalars().all()

        if not existing:
            print("No legacy workflows found in database (already deleted).")
            return

        for wf in existing:
            await session.delete(wf)
            print(f"Deleted workflow: {wf.name} (slug: {wf.slug})")

        await session.commit()
        print(f"Successfully removed {len(existing)} inactive workflow(s).")


if __name__ == "__main__":
    asyncio.run(delete_legacy())
