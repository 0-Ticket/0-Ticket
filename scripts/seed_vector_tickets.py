"""Index the hand-authored closed Ticket fixtures into the configured vector store."""

import json
from pathlib import Path

from soc.config import load_config
from soc.store.vectors.tickets import VectorTicketService


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    fixtures = root / "tests" / "fixtures" / "vectors" / "decided_tickets.json"
    tickets = json.loads(fixtures.read_text(encoding="utf-8"))
    service = VectorTicketService.from_settings(load_config())
    try:
        for ticket in tickets:
            service.add_decided_ticket(ticket)
    finally:
        service.close()
    print(f"Indexed {len(tickets)} decided Ticket samples.")


if __name__ == "__main__":
    main()
