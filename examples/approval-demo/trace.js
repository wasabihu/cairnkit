window.CAIRNKIT_DEMO = {
  "mode": "Offline ScriptedModel \u00b7 fictional data",
  "decision_source": "scripted CLI choice",
  "ticket_id": "TICKET-1042",
  "source_text": "Please send future invoices to billing@example.com.",
  "tools": [
    "propose_invoice_email",
    "read_ticket"
  ],
  "events": [
    {
      "stage": "request",
      "actor": "Sam",
      "record": {
        "invoice_email": "accounts@example.com",
        "version": 1
      },
      "draft": null
    },
    {
      "stage": "read",
      "actor": "Sam",
      "record": {
        "invoice_email": "accounts@example.com",
        "version": 1
      },
      "draft": null
    },
    {
      "stage": "draft",
      "actor": "Sam",
      "record": {
        "invoice_email": "accounts@example.com",
        "version": 1
      },
      "draft": {
        "id": "DRAFT-01",
        "source": "TICKET-1042",
        "proposed_by": "support-01",
        "before": "accounts@example.com",
        "after": "billing@example.com",
        "base_version": 1,
        "status": "pending",
        "reviewed_by": null
      }
    },
    {
      "stage": "review",
      "actor": "Alex",
      "record": {
        "invoice_email": "accounts@example.com",
        "version": 1
      },
      "draft": {
        "id": "DRAFT-01",
        "source": "TICKET-1042",
        "proposed_by": "support-01",
        "before": "accounts@example.com",
        "after": "billing@example.com",
        "base_version": 1,
        "status": "pending",
        "reviewed_by": null
      }
    },
    {
      "stage": "saved",
      "actor": "Alex",
      "record": {
        "invoice_email": "billing@example.com",
        "version": 2
      },
      "draft": {
        "id": "DRAFT-01",
        "source": "TICKET-1042",
        "proposed_by": "support-01",
        "before": "accounts@example.com",
        "after": "billing@example.com",
        "base_version": 1,
        "status": "approved",
        "reviewed_by": "reviewer-01"
      }
    }
  ]
};
