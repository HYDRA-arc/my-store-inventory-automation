-- MY store inventory automation schema for Supabase.
-- Run in Supabase Dashboard > SQL Editor.
-- Atomic all-or-nothing reservation: if any requested SKU is short, no stock is reserved.

create extension if not exists pgcrypto;

create table if not exists public.products (
 id uuid primary key default gen_random_uuid(),
 sku text not null unique,
 name text not null,
 brand text,
 category text,
 description text,
 reorder_level integer not null default 0 check (reorder_level >= 0),
 active boolean not null default true,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);

create table if not exists public.warehouses (
 id uuid primary key default gen_random_uuid(),
 code text not null unique,
 name text not null,
 address text,
 active boolean not null default true,
 created_at timestamptz not null default now()
);

create table if not exists public.inventory (
 id uuid primary key default gen_random_uuid(),
 product_id uuid not null references public.products(id),
 warehouse_id uuid not null references public.warehouses(id),
 quantity_on_hand integer not null default 0 check (quantity_on_hand >= 0),
 quantity_reserved integer not null default 0 check (quantity_reserved >= 0),
 updated_at timestamptz not null default now(),
 unique(product_id, warehouse_id),
 check(quantity_reserved <= quantity_on_hand)
);

create table if not exists public.stock_requests (
 id uuid primary key default gen_random_uuid(),
 external_request_id text not null unique,
 source text not null default 'n8n-webhook',
 warehouse_id uuid references public.warehouses(id),
 status text not null default 'pending'
   check(status in ('pending','reserved','shortage','rejected','cancelled')),
 requested_by text,
 notes text,
 result jsonb,
 created_at timestamptz not null default now(),
 processed_at timestamptz
);

create table if not exists public.stock_request_items (
 id uuid primary key default gen_random_uuid(),
 request_id uuid not null references public.stock_requests(id) on delete cascade,
 product_id uuid not null references public.products(id),
 requested_quantity integer not null check(requested_quantity > 0),
 available_quantity integer not null default 0 check(available_quantity >= 0),
 shortage_quantity integer not null default 0 check(shortage_quantity >= 0),
 unique(request_id, product_id)
);

create table if not exists public.inventory_movements (
 id uuid primary key default gen_random_uuid(),
 product_id uuid not null references public.products(id),
 warehouse_id uuid not null references public.warehouses(id),
 request_id uuid references public.stock_requests(id),
 movement_type text not null check(movement_type in ('receipt','reservation','release','adjustment','sale','return')),
 quantity_change integer not null,
 note text,
 created_at timestamptz not null default now()
);

create table if not exists public.stock_alerts (
 id uuid primary key default gen_random_uuid(),
 request_id uuid references public.stock_requests(id) on delete set null,
 product_id uuid not null references public.products(id),
 warehouse_id uuid references public.warehouses(id),
 alert_type text not null default 'shortage',
 requested_quantity integer not null,
 available_quantity integer not null,
 shortage_quantity integer not null,
 status text not null default 'open' check(status in ('open','acknowledged','resolved')),
 created_at timestamptz not null default now()
);

create table if not exists public.automation_events (
 id bigint generated always as identity primary key,
 event_type text not null,
 external_request_id text,
 payload jsonb not null default '{}'::jsonb,
 outcome jsonb,
 created_at timestamptz not null default now()
);

create index if not exists inventory_product_idx on public.inventory(product_id);
create index if not exists inventory_warehouse_idx on public.inventory(warehouse_id);
create index if not exists stock_requests_status_idx on public.stock_requests(status, created_at desc);
create index if not exists stock_alerts_status_idx on public.stock_alerts(status, created_at desc);
create index if not exists inventory_movements_product_idx on public.inventory_movements(product_id, created_at desc);

-- n8n calls POST /rest/v1/rpc/process_inventory_request with {"p_payload": {...}}.
-- Payload: external_request_id, warehouse_code, items:[{sku,requested_quantity}]
create or replace function public.process_inventory_request(p_payload jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
 v_external_id text := nullif(trim(p_payload->>'external_request_id'), '');
 v_warehouse_code text := nullif(trim(p_payload->>'warehouse_code'), '');
 v_warehouse_id uuid;
 v_request_id uuid;
 v_item jsonb;
 v_sku text;
 v_qty integer;
 v_product_id uuid;
 v_on_hand integer;
 v_reserved integer;
 v_available integer;
 v_shortage integer;
 v_has_shortage boolean := false;
 v_items jsonb := '[]'::jsonb;
 v_result jsonb;
 v_existing public.stock_requests%rowtype;
begin
 if v_external_id is null then raise exception 'external_request_id is required'; end if;
 if v_warehouse_code is null then raise exception 'warehouse_code is required'; end if;
 if jsonb_typeof(p_payload->'items') <> 'array' or jsonb_array_length(p_payload->'items') = 0
 then raise exception 'items must be a non-empty array'; end if;

 select id into v_warehouse_id from public.warehouses
 where code = v_warehouse_code and active = true;
 if v_warehouse_id is null then raise exception 'Unknown or inactive warehouse_code: %', v_warehouse_code; end if;

 -- Idempotency for webhook retries.
 select * into v_existing from public.stock_requests where external_request_id = v_external_id;
 if found then
   return coalesce(v_existing.result, jsonb_build_object('request_id',v_existing.id,'status',v_existing.status));
 end if;

 insert into public.stock_requests(external_request_id, warehouse_id, requested_by, notes)
 values(v_external_id, v_warehouse_id, p_payload->>'requested_by', p_payload->>'notes')
 returning id into v_request_id;

 -- Check and lock all inventory rows first.
 for v_item in select value from jsonb_array_elements(p_payload->'items') loop
   v_sku := nullif(trim(v_item->>'sku'),'');
   v_qty := (v_item->>'requested_quantity')::integer;
   if v_sku is null or v_qty is null or v_qty <= 0 then
     raise exception 'Each item needs sku and positive requested_quantity';
   end if;

   select id into v_product_id from public.products where sku=v_sku and active=true;
   if v_product_id is null then raise exception 'Unknown or inactive SKU: %', v_sku; end if;

   select quantity_on_hand, quantity_reserved into v_on_hand, v_reserved
   from public.inventory where product_id=v_product_id and warehouse_id=v_warehouse_id
   for update;
   if not found then v_on_hand := 0; v_reserved := 0; end if;

   v_available := greatest(v_on_hand-v_reserved,0);
   v_shortage := greatest(v_qty-v_available,0);
   if v_shortage > 0 then v_has_shortage := true; end if;

   insert into public.stock_request_items(request_id,product_id,requested_quantity,available_quantity,shortage_quantity)
   values(v_request_id,v_product_id,v_qty,v_available,v_shortage);

   v_items := v_items || jsonb_build_array(jsonb_build_object(
     'sku',v_sku,'requested_quantity',v_qty,'available_quantity',v_available,'shortage_quantity',v_shortage));
 end loop;

 if v_has_shortage then
   update public.stock_requests set status='shortage', processed_at=now() where id=v_request_id;
   insert into public.stock_alerts(request_id,product_id,warehouse_id,requested_quantity,available_quantity,shortage_quantity)
   select request_id, product_id, v_warehouse_id, requested_quantity, available_quantity, shortage_quantity
   from public.stock_request_items where request_id=v_request_id and shortage_quantity>0;

   v_result := jsonb_build_object('request_id',v_request_id,'external_request_id',v_external_id,
     'status','shortage','stock_reserved',false,'items',v_items,
     'message','One or more items have insufficient stock. No items were reserved.');
 else
   -- Reserve all items only if every item is available.
   for v_item in select value from jsonb_array_elements(p_payload->'items') loop
     v_sku := trim(v_item->>'sku');
     v_qty := (v_item->>'requested_quantity')::integer;
     select id into v_product_id from public.products where sku=v_sku;
     update public.inventory set quantity_reserved=quantity_reserved+v_qty, updated_at=now()
     where product_id=v_product_id and warehouse_id=v_warehouse_id;
     insert into public.inventory_movements(product_id,warehouse_id,request_id,movement_type,quantity_change,note)
     values(v_product_id,v_warehouse_id,v_request_id,'reservation',-v_qty,
       'Reserved by automated request '||v_external_id);
   end loop;

   update public.stock_requests set status='reserved', processed_at=now() where id=v_request_id;
   v_result := jsonb_build_object('request_id',v_request_id,'external_request_id',v_external_id,
     'status','reserved','stock_reserved',true,'items',v_items,
     'message','All requested items are available and have been reserved.');
 end if;

 update public.stock_requests set result=v_result where id=v_request_id;
 insert into public.automation_events(event_type,external_request_id,payload,outcome)
 values('inventory_request_processed',v_external_id,p_payload,v_result);
 return v_result;
end;
$$;

revoke all on function public.process_inventory_request(jsonb) from public, anon, authenticated;
grant execute on function public.process_inventory_request(jsonb) to service_role;

-- Demo warehouse/products/stock. Change these to match MY store's real catalogue.
insert into public.warehouses(code,name) values('MAIN','Main Warehouse') on conflict(code) do nothing;
insert into public.products(sku,name,brand,category,reorder_level) values
 ('LAP-DELL-001','Dell business laptop','Dell','Laptop',5),
 ('LAP-HP-001','HP business laptop','HP','Laptop',5),
 ('LAP-LEN-001','Lenovo business laptop','Lenovo','Laptop',5)
on conflict(sku) do nothing;
insert into public.inventory(product_id,warehouse_id,quantity_on_hand,quantity_reserved)
select p.id,w.id,case p.sku when 'LAP-DELL-001' then 10 when 'LAP-HP-001' then 4 else 8 end,0
from public.products p cross join public.warehouses w where w.code='MAIN'
on conflict(product_id,warehouse_id) do nothing;

-- SECURITY: never expose the Supabase service_role key in browser/client code.
-- n8n should store it in a credential/secret. Add staff RLS policies before production.
-- This function reserves stock (quantity_reserved); fulfillment must separately
-- decrement quantity_on_hand and quantity_reserved in a controlled transaction.
