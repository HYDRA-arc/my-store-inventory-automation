
import streamlit as st
import sqlite3
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import re

from inventory_client import InventoryWebhookError, send_inventory_request

APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "mystore_support.db"

st.set_page_config(page_title="MY store | Support & Automation", page_icon="💻", layout="wide")

BUSINESS_NAME = "MY store"
SUPPORT_EMAIL = "Mystore@example.com"

DEFAULT_FAQS = [
    ("What laptops do you sell?", "MY store sells laptops. Tell us your preferred use (work, study, gaming, or general use) and budget, and our sales team can help you choose. Current models, stock, and prices must be confirmed by our sales team."),
    ("How do I buy a laptop?", "You can contact our sales team at Mystore@example.com with the laptop model or your requirements. They can confirm current availability, pricing, and purchase options."),
    ("Can I get help choosing a laptop?", "Yes. Share your intended use, preferred screen size, performance needs, and budget. Please do not share passwords or payment-card details."),
    ("My laptop is not turning on", "Try connecting the original or manufacturer-approved charger and checking the power outlet. If it still does not turn on, create a service request with the model and a short description. Do not open the device if it may affect your warranty."),
    ("How do I request laptop service?", "Create a service request from the Service Requests section of this dashboard, or email Mystore@example.com. Include the laptop model and a description of the issue. Our team will follow up."),
    ("Can I check my repair status?", "Repair-status information is not connected to this demo app yet. Please contact Mystore@example.com with your service-request reference. Do not send passwords."),
    ("How can I check my order or delivery?", "Live order and delivery tracking is not connected yet. Please contact Mystore@example.com with your order reference. Never send payment-card details or account passwords."),
    ("What is your return or refund policy?", "The current return and refund policy has not been configured in this chatbot. Please contact Mystore@example.com so a support representative can confirm the applicable terms."),
    ("What is the warranty?", "Warranty coverage depends on the product and its terms. Please email Mystore@example.com with the laptop model and purchase date so our team can confirm the details."),
    ("How do I contact support?", "Email our support team at Mystore@example.com. You can also submit a service request in this dashboard.")
]

def connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

@st.cache_resource(show_spinner=False)
def init_db():
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS faqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL UNIQUE,
            answer TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            email TEXT NOT NULL,
            category TEXT NOT NULL,
            laptop_model TEXT,
            reference TEXT,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open'
        )""")
        count = conn.execute("SELECT COUNT(*) FROM faqs").fetchone()[0]
        if count == 0:
            conn.executemany("INSERT INTO faqs(question, answer) VALUES (?, ?)", DEFAULT_FAQS)
    return True

@st.cache_data(show_spinner=False)
def get_faqs():
    with connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM faqs ORDER BY id DESC")]

@st.cache_data(show_spinner=False)
def get_faq_search_index():
    stop = {"what", "how", "can", "i", "my", "the", "is", "do", "you", "your", "a", "an", "to", "for", "of", "and", "in", "on", "please"}
    return [
        (
            row,
            set(re.findall(r"[a-z0-9]+", row["question"].lower())) - stop,
            set(re.findall(r"[a-z0-9]+", row["answer"].lower())) - stop,
            row["question"].lower().strip(" ?"),
        )
        for row in get_faqs()
    ]

@st.cache_data(show_spinner=False)
def get_sample_inventory_payload():
    return json.loads(
        (APP_DIR / "sample_webhook_payload.json").read_text(encoding="utf-8")
    )

def add_ticket(name, email, category, model, reference, description):
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO tickets(created_at, customer_name, email, category, laptop_model, reference, description)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now().strftime("%Y-%m-%d %H:%M"), name, email, category, model, reference, description)
        )
        return cur.lastrowid

def answer_question(message):
    text = message.lower().strip()
    if any(x in text for x in ["password", "credit card", "debit card", "cvv", "otp", "one-time password"]):
        return "For your security, please do not share passwords, OTPs, or payment-card details here. A support representative can help through Mystore@example.com."
    words = set(re.findall(r"[a-z0-9]+", text))
    best_row, best_score = None, 0
    for row, qwords, awords, question_text in get_faq_search_index():
        score = len(words & qwords) * 2 + len(words & awords) * 0.15
        if question_text in text:
            score += 5
        if score > best_score:
            best_row, best_score = row, score
    if best_row and best_score >= 1.8:
        return best_row["answer"]
    return f"I’m sorry, I don’t have a confirmed answer for that yet. Please contact a human support representative at {SUPPORT_EMAIL}. I won’t guess about prices, stock, policies, orders, or repair status."

init_db()

st.sidebar.title("💻 MY store")
st.sidebar.caption("Laptop sales & service support")
page = st.sidebar.radio("Navigate", ["Customer Chat", "Service Requests", "Inventory Automation", "Business Dashboard", "Manage FAQs"])
st.sidebar.divider()
st.sidebar.write(f"**Support:** {SUPPORT_EMAIL}")
st.sidebar.caption("Demo version • Data is stored locally in mystore_support.db")

st.title("MY store — Laptop Support & Business Automation")
st.caption("A starter customer-support dashboard for laptop sales, troubleshooting, service requests, and support operations.")

if page == "Customer Chat":
    st.subheader("Customer support assistant")
    st.write("Ask about laptop sales, choosing a device, service, warranty, orders, delivery, returns, or refunds.")
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            {"role": "assistant", "content": "Hello! Welcome to MY store. I can help with laptop sales and service. What can I help you with today?"}
        ]
    for item in st.session_state.chat_history:
        with st.chat_message(item["role"]):
            st.markdown(item["content"])
    prompt = st.chat_input("Type your question...")
    if prompt:
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        response = answer_question(prompt)
        st.session_state.chat_history.append({"role": "assistant", "content": response})
        st.rerun()
    with st.expander("Example questions"):
        st.markdown("- Which laptop is suitable for office work?\n- My laptop is not turning on\n- How do I request a repair?\n- What is your return policy?\n- How can I check delivery?")
    st.info("The chat uses FAQ keyword matching. Live stock checks are available under Inventory Automation; order, delivery, and repair systems are not connected.")

elif page == "Service Requests":
    st.subheader("Create a service or support request")
    st.write("Use this form for laptop faults, diagnostics, warranty questions, or sales assistance.")
    with st.form("ticket_form", clear_on_submit=True):
        name = st.text_input("Customer name *")
        email = st.text_input("Email address *")
        category = st.selectbox("Request type", ["Laptop repair / technical issue", "Warranty question", "Sales enquiry", "Order / delivery enquiry", "Other"])
        model = st.text_input("Laptop model (if known)")
        reference = st.text_input("Order or service reference (optional)")
        description = st.text_area("Describe how we can help *", placeholder="Describe the issue. Do not include passwords, OTPs, or payment-card details.")
        submitted = st.form_submit_button("Submit request", type="primary")
        if submitted:
            if not name.strip() or not email.strip() or not description.strip():
                st.error("Please complete the required fields.")
            elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()):
                st.error("Please enter a valid email address.")
            else:
                ticket_id = add_ticket(name.strip(), email.strip(), category, model.strip(), reference.strip(), description.strip())
                st.success(f"Request submitted. Your reference number is MY-{ticket_id:05d}. Our team can follow up at the email you provided.")
                st.caption(f"Support email: {SUPPORT_EMAIL}")

elif page == "Inventory Automation":
    st.subheader("Inventory stock check and reservation")
    st.write("Submit a stock request through the configured n8n workflow and Supabase function.")
    webhook_url = os.getenv("N8N_INVENTORY_WEBHOOK_URL", "").strip()
    if webhook_url:
        st.success("n8n webhook is configured.")
    else:
        st.warning(
            "Inventory automation is not connected yet. Set "
            "N8N_INVENTORY_WEBHOOK_URL to your n8n production webhook URL, then restart the app."
        )

    sample_payload = get_sample_inventory_payload()
    request_json = st.text_area(
        "Inventory request JSON",
        value=json.dumps(sample_payload, indent=2),
        height=300,
    )
    if st.button("Check and reserve stock", type="primary", disabled=not webhook_url):
        try:
            payload = json.loads(request_json)
        except json.JSONDecodeError as exc:
            st.error(f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")
        else:
            try:
                result = send_inventory_request(payload, webhook_url)
            except InventoryWebhookError as exc:
                st.error(f"Inventory request failed: {exc}")
            else:
                status = result.get("status")
                if status == "reserved":
                    st.success(result.get("message", "All requested items were reserved."))
                elif status == "shortage":
                    st.warning(result.get("message", "There is not enough stock; nothing was reserved."))
                else:
                    st.info(result.get("message", "Inventory request completed."))
                st.json(result)

elif page == "Business Dashboard":
    st.markdown(
        """
        <style>
        .support-hero {
            padding: 1.4rem 1.6rem;
            border: 1px solid rgba(120, 140, 180, 0.25);
            border-radius: 18px;
            background: linear-gradient(115deg, rgba(28, 73, 125, 0.55), rgba(71, 48, 112, 0.38));
            margin: 0.2rem 0 1.25rem 0;
        }
        .support-hero-kicker {
            color: #8bd5ff;
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }
        .support-hero h2 {
            margin: 0.3rem 0;
            font-size: 2rem;
        }
        .support-hero p {
            margin: 0;
            opacity: 0.82;
        }
        </style>
        <div class="support-hero">
            <div class="support-hero-kicker">MY store · Support pulse</div>
            <h2>Your service desk, at a glance.</h2>
            <p>Track incoming requests, spot the workload trend, and keep every customer moving.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    filter_col, update_col = st.columns([1, 3])
    with filter_col:
        period_days = st.selectbox(
            "Activity window",
            [7, 30, 90],
            index=1,
            format_func=lambda days: f"Last {days} days",
        )
    with update_col:
        st.caption(f"Local support data · Updated {datetime.now().strftime('%b %d, %Y at %H:%M')}")

    today = datetime.now().date()
    period_start = today - timedelta(days=period_days - 1)
    previous_start = today - timedelta(days=(period_days * 2) - 1)
    period_start_text = period_start.isoformat()
    previous_start_text = previous_start.isoformat()
    with connect() as conn:
        total, open_count, progress_count, closed_count = conn.execute(
            """SELECT COUNT(*),
                      COALESCE(SUM(CASE WHEN status='Open' THEN 1 ELSE 0 END), 0),
                      COALESCE(SUM(CASE WHEN status='In Progress' THEN 1 ELSE 0 END), 0),
                      COALESCE(SUM(CASE WHEN status='Closed' THEN 1 ELSE 0 END), 0)
               FROM tickets"""
        ).fetchone()
        new_requests = conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE date(created_at) >= ?",
            (period_start_text,),
        ).fetchone()[0]
        previous_requests = conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE date(created_at) >= ? AND date(created_at) < ?",
            (previous_start_text, period_start_text),
        ).fetchone()[0]
        daily_counts = dict(
            conn.execute(
                """SELECT date(created_at), COUNT(*)
                   FROM tickets WHERE date(created_at) >= ?
                   GROUP BY date(created_at)""",
                (period_start_text,),
            ).fetchall()
        )
        category_counts = conn.execute(
            """SELECT category, COUNT(*) AS requests
               FROM tickets WHERE date(created_at) >= ?
               GROUP BY category ORDER BY requests DESC, category""",
            (period_start_text,),
        ).fetchall()
        recent_tickets = conn.execute(
            "SELECT id, created_at, customer_name, category, status FROM tickets ORDER BY id DESC LIMIT 5"
        ).fetchall()

    request_change = new_requests - previous_requests
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "New requests",
        new_requests,
        delta=f"{request_change:+} vs prior {period_days} days",
        delta_color="off",
        help=f"Requests created in the last {period_days} days compared with the previous period.",
        border=True,
    )
    c2.metric("Open queue", open_count, help="Requests waiting for a team response.", border=True)
    c3.metric("In progress", progress_count, help="Requests currently being handled.", border=True)
    c4.metric("Resolved", closed_count, help="All requests marked Closed.", border=True)

    trend_col, category_col = st.columns([1.6, 1])
    with trend_col:
        st.markdown("#### Request activity")
        if total:
            dates = [period_start + timedelta(days=offset) for offset in range(period_days)]
            trend_data = {
                "Date": [day.strftime("%b %d") for day in dates],
                "Requests": [daily_counts.get(day.isoformat(), 0) for day in dates],
            }
            st.area_chart(trend_data, x="Date", y="Requests", color="#55B8FF")
        else:
            st.info("Your activity chart will come alive when the first customer request arrives.")

    with category_col:
        st.markdown("#### What customers need")
        if category_counts:
            st.bar_chart(
                {
                    "Request type": [row["category"] for row in category_counts],
                    "Requests": [row["requests"] for row in category_counts],
                },
                x="Request type",
                y="Requests",
                color="#A78BFA",
            )
        else:
            st.info("No request categories to show for this period yet.")

    st.markdown("#### Queue health")
    if total:
        st.progress(closed_count / total, text=f"{closed_count} of {total} requests resolved")
    else:
        st.progress(0.0, text="Ready for your first customer request")

    st.markdown("#### Latest arrivals")
    if recent_tickets:
        st.dataframe(
            [
                {
                    "Reference": f"MY-{ticket['id']:05d}",
                    "Customer": ticket["customer_name"],
                    "Request type": ticket["category"],
                    "Status": ticket["status"],
                    "Received": ticket["created_at"],
                }
                for ticket in recent_tickets
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("No requests yet. New customer submissions will appear here automatically.")

    with st.expander("Manage requests"):
        page_size = 50
        page_count = max(1, (total + page_size - 1) // page_size)
        selected_page = st.selectbox(
            "Request page",
            range(1, page_count + 1),
            format_func=lambda value: f"Page {value} of {page_count}",
        )
        with connect() as conn:
            tickets = conn.execute(
                "SELECT * FROM tickets ORDER BY id DESC LIMIT ? OFFSET ?",
                (page_size, (selected_page - 1) * page_size),
            ).fetchall()
        if tickets:
            for t in tickets:
                with st.expander(f"MY-{t['id']:05d} · {t['category']} · {t['status']} · {t['created_at']}"):
                    st.write(f"**Customer:** {t['customer_name']} ({t['email']})")
                    st.write(f"**Laptop model:** {t['laptop_model'] or 'Not provided'}")
                    st.write(f"**Order/service reference:** {t['reference'] or 'Not provided'}")
                    st.write(f"**Description:** {t['description']}")
                    statuses = ["Open", "In Progress", "Closed"]
                    new_status = st.selectbox("Update status", statuses, index=statuses.index(t["status"]), key=f"status_{t['id']}")
                    if st.button("Save status", key=f"save_{t['id']}"):
                        with connect() as conn:
                            conn.execute("UPDATE tickets SET status=? WHERE id=?", (new_status, t["id"]))
                        st.success("Status updated.")
                        st.rerun()
        else:
            st.caption("There are no requests to manage yet.")

    st.caption("For a live business deployment, add staff login, role permissions, backups, and email notifications.")

elif page == "Manage FAQs":
    st.subheader("Manage chatbot knowledge")
    st.write("Update answers here so the chatbot uses your confirmed business information.")
    with st.form("add_faq", clear_on_submit=True):
        question = st.text_input("FAQ question")
        answer = st.text_area("Approved answer")
        save_faq = st.form_submit_button("Add FAQ")
        if save_faq:
            if question.strip() and answer.strip():
                try:
                    with connect() as conn:
                        conn.execute("INSERT INTO faqs(question, answer) VALUES (?, ?)", (question.strip(), answer.strip()))
                    get_faqs.clear()
                    get_faq_search_index.clear()
                    st.success("FAQ added.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("That question already exists. Edit or remove the existing FAQ first.")
            else:
                st.error("Enter both a question and an answer.")
    st.divider()
    for faq in get_faqs():
        with st.expander(faq["question"]):
            edited_answer = st.text_area("Answer", value=faq["answer"], key=f"faq_answer_{faq['id']}")
            a, b = st.columns(2)
            if a.button("Save answer", key=f"faq_save_{faq['id']}"):
                with connect() as conn:
                    conn.execute("UPDATE faqs SET answer=? WHERE id=?", (edited_answer.strip(), faq["id"]))
                get_faqs.clear()
                get_faq_search_index.clear()
                st.success("Answer updated.")
                st.rerun()
            if b.button("Delete FAQ", key=f"faq_delete_{faq['id']}"):
                with connect() as conn:
                    conn.execute("DELETE FROM faqs WHERE id=?", (faq["id"],))
                get_faqs.clear()
                get_faq_search_index.clear()
                st.warning("FAQ deleted.")
                st.rerun()

st.sidebar.divider()
st.sidebar.caption("Before launch: configure verified prices, stock, warranty, returns/refunds, and connect real order/repair systems.")
