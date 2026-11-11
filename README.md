MY store inventory automation starter
======================================

FILES
- mystore_inventory_schema.sql: Supabase tables, sample data, and atomic RPC function.
- n8n_inventory_workflow.json: Importable n8n workflow.
- sample_webhook_payload.json: Example webhook request.

SUPABASE
1. Open Supabase Dashboard > SQL Editor.
2. Paste/run mystore_inventory_schema.sql.
3. Confirm sample warehouse MAIN and sample SKUs exist.
4. Copy your Project URL and service_role key from Project Settings > API.

N8N
1. Import n8n_inventory_workflow.json in n8n.
2. In the HTTP Request node, replace YOUR_PROJECT_REF and both
   YOUR_SUPABASE_SERVICE_ROLE_KEY placeholders. The Authorization value must
   be `Bearer <service_role_key>`; the apikey value is the key itself.
3. Keep the workflow inactive while testing; save, then activate when ready.
4. Copy the Webhook node's Production URL.
5. POST sample_webhook_payload.json to that URL.

STREAMLIT APP
1. Run `python -m streamlit run app.py` from this folder.
2. Set `N8N_INVENTORY_WEBHOOK_URL` to the Production URL from n8n, then restart
   Streamlit. The Inventory Automation page submits requests to that webhook.
3. Keep the Supabase service_role key in n8n credentials/secrets; never add it
   to this app or expose it in browser code.
4. The bundled sample request asks for 2 Dell and 6 HP laptops. With the
   included Supabase seed data (10 Dell, 4 HP), the expected result is a
   shortage and no stock reservation. Change external_request_id for a new
   request; repeated IDs are intentionally idempotent.

EXPECTED LOGIC
- Sufficient stock for every requested line: reserve all lines, status=reserved.
- Any shortage: create stock_alerts and reserve nothing, status=shortage.
- Repeated external_request_id: return stored result to avoid duplicate reservation.
- Reservation increases quantity_reserved; quantity_on_hand changes only at fulfillment.

SECURITY / PRODUCTION
- Protect the n8n webhook with authentication before exposing it publicly.
- Never put the Supabase service_role key in frontend/browser code or public Git.
- Prefer n8n credentials/secrets over hardcoded keys in workflow nodes.
- Add staff authentication, RLS policies for dashboard users, backups, and audit review.
- This is deterministic inventory automation, not an LLM. Add an AI node only if you
  want natural-language product requests parsed into SKU/quantity records.
- Test using sample data before connecting real orders.
