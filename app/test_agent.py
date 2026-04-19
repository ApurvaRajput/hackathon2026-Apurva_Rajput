from app.data_loader import load_all_data
from app.agent import process_ticket

def run_agent_tests():
    try:
        data = load_all_data()
        tickets = data.tickets

        print(f"\n🚀 Starting Agent Test on {len(tickets[:5])} tickets...\n")

        for i, ticket in enumerate(tickets[:5], start=1):
            print("=" * 50)
            print(f"🧠 Processing Ticket {i}: {ticket.ticket_id}")

            ticket_dict = ticket.model_dump()

            try:
                # ✅ Retry mechanism (important due to failure simulation)
                for attempt in range(2):  # retry once
                    result = process_ticket(ticket_dict)

                    # If your agent returns structured response
                    if isinstance(result, dict):
                        if result.get("status") == "error" and "timeout" in result.get("message", "").lower():
                            print("⚠️ Timeout occurred, retrying...")
                            continue

                    break  # success or non-timeout error → stop retry

            except Exception as e:
                print(f"❌ Error processing ticket {ticket.ticket_id}: {str(e)}")

        print("\n✅ Agent testing completed.\n")

    except Exception as e:
        print(f"🔥 Critical error: {str(e)}")


if __name__ == "__main__":
    run_agent_tests()