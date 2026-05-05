"""
pages/admin.py  —  MigrationBot Admin Panel  (F13)
"""


import json
import base64
import pandas as pd
import streamlit as st
from src.permissions import (
    save_permissions, PermissionChecker,
    WRITE_TOOLS, READ_ONLY_TOOLS,
)
from src.sheets.column_map import COLUMN_ALIASES
from src.audit import AuditLogger

st.set_page_config(page_title="MigrationBot Admin", page_icon="🔧", layout="wide")

# ── Auth guard ────────────────────────────────────────────────────────────────

if "token_dict" not in st.session_state:
    st.warning("Please sign in from the main page first.")
    st.page_link("app.py", label="← Go to MigrationBot", icon="🤖")
    st.stop()


def _get_email(token_dict: dict) -> str:
    try:
        payload  = token_dict.get("id_token", "").split(".")[1]
        payload += "=" * ((4 - len(payload) % 4) % 4)
        return json.loads(
            base64.urlsafe_b64decode(payload).decode("utf-8")
        ).get("email", "unknown").lower()
    except Exception:
        return "unknown"


user_email = _get_email(st.session_state.token_dict)
admins     = [a.lower() for a in st.secrets.get("app", {}).get("admins", [])]

if user_email not in admins:
    st.error(f"Access denied — `{user_email}` is not an admin.")
    st.page_link("app.py", label="← Go to MigrationBot", icon="🤖")
    st.stop()

# ── Helpers ───────────────────────────────────────────────────────────────────

ALL_TOOLS       = sorted(WRITE_TOOLS | READ_ONLY_TOOLS)
WRITE_TOOL_LIST = sorted(WRITE_TOOLS)

def _get_column_options() -> list[str]:
    """
    Return the live column list from the session-level column map (F11)
    if available, otherwise fall back to the static COLUMN_ALIASES keys.
    Strips trailing spaces for display but preserves originals for storage.
    """
    active_map = st.session_state.get("column_map", COLUMN_ALIASES)
    return sorted(active_map.keys())

# ── Page header ───────────────────────────────────────────────────────────────

st.title("🔧 MigrationBot Admin")
st.caption(f"Signed in as **{user_email}**")
st.page_link("app.py", label="← Back to MigrationBot", icon="🤖")

if not st.secrets.get("app", {}).get("config_sheet_id"):
    st.warning(
        "No `config_sheet_id` in secrets. "
        "Permissions will only persist for this session — add it to enable durable storage."
    )

tab_perms, tab_audit, tab_cache = st.tabs(["👥 User Permissions", "📋 Audit Log", "🗄️ Cache & Debug"])

# ══════════════════════════════════════════════════════════════════════════════
# Tab 1 — User Permissions
# ══════════════════════════════════════════════════════════════════════════════

with tab_perms:

    permissions: dict = st.session_state.get("permissions_raw", {})

    # ── Role reference ────────────────────────────────────────────────────────
    with st.expander("📖 Role reference", expanded=False):
        c1, c2, c3 = st.columns(3)
        c1.markdown("**admin**  \nFull access to everything. Set in `secrets.toml`.")
        c2.markdown(
            "**editor** *(default)*  \n"
            "Read + write. Restrict fields or block specific tools below."
        )
        c3.markdown("**viewer**  \nRead-only: `get_row`, `search_rows`, `summarize`.")
        st.markdown(
            f"**Write tools:** {', '.join(f'`{t}`' for t in WRITE_TOOL_LIST)}  \n"
            f"**Read tools:** {', '.join(f'`{t}`' for t in sorted(READ_ONLY_TOOLS))}"
        )

    # ── Current rules table ───────────────────────────────────────────────────
    st.subheader("Current rules")

    if not permissions:
        st.info(
            "No rules yet. All authenticated users get the default editor policy "
            "(full write access). Add rows below to restrict access."
        )
    else:
        rows = [
            {
                "Email":             email,
                "Role":              p["role"],
                "Allowed Fields":    "*" if p["allowed_fields"] == ["*"]
                                     else ", ".join(p["allowed_fields"]),
                "Denied Operations": ", ".join(p.get("denied_operations", [])) or "—",
            }
            for email, p in permissions.items()
        ]
        df = pd.DataFrame(rows)

        def _highlight(row):
            colours = {"admin": "#d4edda", "viewer": "#fff3cd"}
            bg = colours.get(row["Role"], "")
            return [f"background-color: {bg}" if bg else ""] * len(row)

        st.dataframe(
            df.style.apply(_highlight, axis=1),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # ── Add / Edit ────────────────────────────────────────────────────────────
    st.subheader("Add or edit a user")

    col_options = _get_column_options()

    with st.form("add_edit_user", clear_on_submit=True):
        r1c1, r1c2 = st.columns([3, 1])
        new_email = r1c1.text_input(
            "Email (or group: prefix)",
            placeholder="user@tmcltd.ai  or  group:fi",
        )
        new_role = r1c2.selectbox("Role", ["editor", "viewer"])

        st.markdown("**Allowed fields** — which columns this user may write to")
        all_fields_toggle = st.checkbox("Allow all fields (*)", value=True, key="all_fields")

        if not all_fields_toggle:
            allowed_fields_sel = st.multiselect(
                "Select allowed columns",
                options=col_options,
                help="Only these columns will be writable by this user.",
            )
        else:
            allowed_fields_sel = ["*"]

        st.markdown("**Denied operations** — tools to block entirely for this user")
        denied_ops_sel = st.multiselect(
            "Select tools to deny",
            options=WRITE_TOOL_LIST,
            help="These tools will be blocked even if the user has editor role.",
        )

        submitted = st.form_submit_button("💾 Save rule", type="primary")

        if submitted:
            if not new_email.strip():
                st.error("Email is required.")
            else:
                key = new_email.strip().lower()
                af  = allowed_fields_sel if allowed_fields_sel else ["*"]
                permissions[key] = {
                    "role":              new_role,
                    "allowed_fields":    af,
                    "denied_operations": denied_ops_sel,
                }
                st.session_state["permissions_raw"] = permissions
                st.session_state["checker"] = PermissionChecker(user_email, permissions)

                if save_permissions(st.session_state.token_dict, permissions):
                    st.success(f"✅ Saved rule for **{key}**.")
                else:
                    st.warning("Saved in session but could not write to config sheet.")
                st.rerun()

    st.divider()

    # ── Edit existing inline ──────────────────────────────────────────────────
    if permissions:
        st.subheader("Edit existing rule")

        edit_email = st.selectbox(
            "Select user to edit",
            options=list(permissions.keys()),
            key="edit_select",
        )

        if edit_email:
            existing = permissions[edit_email]
            ex_role  = existing.get("role", "editor")
            ex_af    = existing.get("allowed_fields", ["*"])
            ex_do    = existing.get("denied_operations", [])
            ex_all   = ex_af == ["*"]

            with st.form("edit_user"):
                edit_role = st.selectbox(
                    "Role",
                    ["editor", "viewer"],
                    index=["editor", "viewer"].index(ex_role) if ex_role in ["editor","viewer"] else 0,
                )
                edit_all = st.checkbox("Allow all fields (*)", value=ex_all, key="edit_all")
                if not edit_all:
                    edit_af = st.multiselect(
                        "Allowed columns",
                        options=col_options,
                        default=[c for c in ex_af if c in col_options],
                    )
                else:
                    edit_af = ["*"]

                edit_do = st.multiselect(
                    "Denied operations",
                    options=WRITE_TOOL_LIST,
                    default=[op for op in ex_do if op in WRITE_TOOL_LIST],
                )

                c1, c2 = st.columns(2)
                save_edit   = c1.form_submit_button("💾 Save changes", type="primary")
                delete_rule = c2.form_submit_button("🗑️ Delete rule",  type="secondary")

            if save_edit:
                permissions[edit_email] = {
                    "role":              edit_role,
                    "allowed_fields":    edit_af,
                    "denied_operations": edit_do,
                }
                st.session_state["permissions_raw"] = permissions
                st.session_state["checker"] = PermissionChecker(user_email, permissions)
                if save_permissions(st.session_state.token_dict, permissions):
                    st.success(f"✅ Updated **{edit_email}**.")
                else:
                    st.warning("Saved in session only — config sheet write failed.")
                st.rerun()

            if delete_rule:
                del permissions[edit_email]
                st.session_state["permissions_raw"] = permissions
                st.session_state["checker"] = PermissionChecker(user_email, permissions)
                if save_permissions(st.session_state.token_dict, permissions):
                    st.success(f"Deleted rule for **{edit_email}**.")
                else:
                    st.warning("Deleted from session only — config sheet write failed.")
                st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# Tab 2 — Audit Log (F15)
# ══════════════════════════════════════════════════════════════════════════════

with tab_audit:
    st.subheader("Audit Log")
    st.markdown(
        "Every write operation made by MigrationBot — cell updates, bulk changes, "
        "row additions, and formatting — is recorded here."
    )

    config_sheet_id = st.secrets.get("app", {}).get("config_sheet_id")
    if not config_sheet_id:
        st.info("Configure `config_sheet_id` in secrets to enable the audit log.")
    else:
        # Reuse the session audit logger if available, otherwise build one
        audit_logger = st.session_state.get("audit_logger")
        if audit_logger is None:
            audit_logger = AuditLogger(st.session_state.token_dict, config_sheet_id)

        # ── Controls ─────────────────────────────────────────────────────────
        fc1, fc2, fc3, fc4 = st.columns([2, 2, 2, 1])

        filter_user  = fc1.text_input("Filter by user email", placeholder="all users")
        filter_tool  = fc2.selectbox(
            "Filter by tool",
            ["All"] + sorted(["update_cell", "bulk_update", "format_row", "add_row"]),
        )
        filter_id    = fc3.text_input("Filter by RICEFW ID", placeholder="e.g. SD-045")
        max_rows_sel = fc4.selectbox("Show", [100, 250, 500], index=0)

        if st.button("🔄 Refresh log", use_container_width=False):
            st.cache_data.clear()

        # ── Fetch ─────────────────────────────────────────────────────────────
        with st.spinner("Loading audit log…"):
            rows = audit_logger.fetch_log(max_rows=max_rows_sel)

        if not rows:
            st.info("No audit entries yet. Write operations will appear here.")
        else:
            import pandas as _pd

            df = _pd.DataFrame(rows)

            # Apply filters
            if filter_user.strip():
                df = df[df["user_email"].str.contains(filter_user.strip(), case=False, na=False)]
            if filter_tool != "All":
                df = df[df["tool_name"] == filter_tool]
            if filter_id.strip():
                df = df[df["ricefw_id"].str.contains(filter_id.strip(), case=False, na=False)]

            # ── Summary metrics ───────────────────────────────────────────────
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total mutations",    len(df))
            m2.metric("Unique users",       df["user_email"].nunique() if len(df) else 0)
            failed = len(df[df["result_ok"] == "False"]) if len(df) else 0
            m3.metric("Failed operations",  failed)
            if len(df):
                top_user = df["user_email"].value_counts().idxmax()
                m4.metric("Most active user", top_user.split("@")[0])

            # ── Log table ─────────────────────────────────────────────────────
            display_cols = [
                "timestamp", "user_email", "tool_name", "ricefw_id",
                "field", "old_value", "new_value", "result_ok", "error",
            ]
            display_df = df[[c for c in display_cols if c in df.columns]].copy()

            def _colour_rows(row):
                if row.get("result_ok") == "False":
                    return ["background-color: #f8d7da"] * len(row)
                if row.get("tool_name") == "bulk_update":
                    return ["background-color: #fff3cd"] * len(row)
                return [""] * len(row)

            st.dataframe(
                display_df.style.apply(_colour_rows, axis=1),
                use_container_width=True,
                hide_index=True,
            )

            # ── Rollback helper ───────────────────────────────────────────────
            st.divider()
            st.markdown("**Rollback helper**")
            st.caption(
                "Select a row to pre-fill a revert command in the chat. "
                "You will still need to confirm it on the main page."
            )
            rb_idx = st.number_input(
                "Row index (0 = newest)",
                min_value=0,
                max_value=max(0, len(display_df) - 1),
                value=0,
            )
            if st.button("⬅️ Generate revert command"):
                if rb_idx < len(display_df):
                    row_data = display_df.iloc[rb_idx]
                    rid   = row_data.get("ricefw_id", "")
                    field = row_data.get("field", "")
                    old   = row_data.get("old_value", "")
                    if rid and field and old:
                        cmd = f"Set {rid} {field} to {old}"
                        st.success(f"Copy this into MigrationBot: **{cmd}**")
                        st.code(cmd)
                    else:
                        st.warning("Not enough data to generate a revert command for this row.")

            # ── Export ────────────────────────────────────────────────────────
            st.download_button(
                label="📥 Download as CSV",
                data=display_df.to_csv(index=False).encode("utf-8"),
                file_name="migrationbot_audit_log.csv",
                mime="text/csv",
            )


# ══════════════════════════════════════════════════════════════════════════════
# Tab 3 — Cache & Debug
# ══════════════════════════════════════════════════════════════════════════════

with tab_cache:
    st.subheader("Cache Management")
    st.markdown(
        "Force-refresh individual caches without signing out. "
        "Useful after adding columns to the sheet or editing permissions externally."
    )

    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("**Column Map (F11)**")
        st.caption("Re-runs the two-pass LLM analysis on next chat load.")
        if st.button("🔄 Refresh column map", use_container_width=True):
            st.session_state.pop("column_map",           None)
            st.session_state.pop("column_map_sheet_id",  None)
            st.success("Cleared. Will rebuild on next load.")

    with c2:
        st.markdown("**Permissions (F13)**")
        st.caption("Reloads the config sheet permissions table.")
        if st.button("🔄 Refresh permissions", use_container_width=True):
            st.session_state.pop("checker",         None)
            st.session_state.pop("permissions_raw", None)
            from src.permissions import ensure_permissions
            ensure_permissions(st.session_state.token_dict, user_email)
            st.success("Permissions reloaded.")

    with c3:
        st.markdown("**Executor cache**")
        st.caption("Clears cached row positions and headers. Safe to run any time.")
        if st.button("🔄 Clear executor cache", use_container_width=True):
            ex = st.session_state.get("executor")
            if ex:
                ex._header_cache   = None
                ex._col_idx_cache  = {}
                ex._id_row_cache   = {}
                ex._sheet_id_cache = None
            st.success("Executor cache cleared.")

    st.divider()
    with st.expander("🔍 Session state inspector"):
        safe = {k: v for k, v in st.session_state.items() if k != "token_dict"}
        st.json(safe, expanded=False)