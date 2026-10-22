import asyncio
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.db.session import AsyncSessionLocal
from backend.services.workflow_seed import seed_default_workflows


async def update_all():
    print("Connecting to database...")
    async with AsyncSessionLocal() as session:
        await seed_default_workflows(session)
        print("Successfully updated workflows in database:")
        print(" - Deleted deprecated legacy workflows if present.")
        print(" - Updated 'create-ticket' and 'w' step_4 body with dynamic fields:")
        print("     notes: {{trigger.default_payload.notes}}")
        print("     category: {{trigger.default_payload.category}}")
        print("     benef_cnic: {{trigger.default_payload.benef_cnic}}")
        print("     program_id: {{trigger.default_payload.program_id}}")
        print("     description: {{trigger.default_payload.description}}")
        print("     subcategory: {{trigger.default_payload.subcategory}}")
        print("     complaint_type: {{trigger.default_payload.complaint_type}}")
        print("     complainant_name: {{trigger.default_payload.complainant_name}}")
        print("     source_ticket_id: {{trigger.default_payload.source_ticket_id}}")
        print("     complainant_phone: {{trigger.default_payload.complainant_phone}}")


if __name__ == "__main__":
    asyncio.run(update_all())
