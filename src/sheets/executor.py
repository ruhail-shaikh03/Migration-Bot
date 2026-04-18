import asyncio
import streamlit as st
from googleapiclient.errors import HttpError
from src.sheets_auth import build_sheets_service

class SheetsExecutor:
    SHEET_NAME     = None   # loaded from secrets at runtime
    DATA_START_ROW = 3      # Row 1 = section headers, Row 2 = column headers
    COLOR_INDEX    = 50     # 0-based index of your Color column — adjust if needed

    COLOR_MAP = {
        "red":   {"red": 0.96, "green": 0.80, "blue": 0.80},
        "green": {"red": 0.78, "green": 0.93, "blue": 0.78},
        "amber": {"red": 1.0,  "green": 0.90, "blue": 0.60},
        "blue":  {"red": 0.78, "green": 0.87, "blue": 0.96},
        "white": {"red": 1.0,  "green": 1.0,  "blue": 1.0 },
    }

        # AFTER — add _header_cache and _id_index_cache
    def __init__(self, access_token: str):
        self.service        = build_sheets_service(access_token)
        self.spreadsheet_id = st.secrets["app"]["spreadsheet_id"]
        self.SHEET_NAME     = st.secrets["app"]["sheet_tab_name"]
        self._sheet_id_cache:   int | None       = None
        self._header_cache:     list[str] | None = None   # ← new
        self._col_idx_cache:    dict[str, int]   = {}     # ← new
        self._id_row_cache:     dict[str, int]   = {}     # ← new (ricefw_id → row number)

    # ── Internal helpers ────────────────────────────────────────────

    def _get_sheet_id(self) -> int:
        if self._sheet_id_cache is not None:
            return self._sheet_id_cache
        meta = self.service.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id
        ).execute()
        for sheet in meta["sheets"]:
            if sheet["properties"]["title"] == self.SHEET_NAME:
                self._sheet_id_cache = sheet["properties"]["sheetId"]
                return self._sheet_id_cache
        raise ValueError(f"Sheet tab '{self.SHEET_NAME}' not found. "
                         f"Check sheet_tab_name in secrets.toml.")

    def _idx_to_col_letter(self, idx: int) -> str:
        result = ""
        while idx >= 0:
            result = chr(idx % 26 + ord("A")) + result
            idx = idx // 26 - 1
        return result

        # AFTER — cached for the lifetime of the session
    def _get_header_row(self) -> list[str]:
        if self._header_cache is not None:
            return self._header_cache
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.SHEET_NAME}!2:2"
        ).execute()
        self._header_cache = result.get("values", [[]])[0]
        return self._header_cache

    # AFTER — uses a pre-built dict, O(1) lookup
    def _resolve_col_index(self, field: str) -> int | None:
        if not self._col_idx_cache:
            headers = self._get_header_row()
            self._col_idx_cache = {h.lower().strip(): i for i, h in enumerate(headers)}
        return self._col_idx_cache.get(field.lower().strip())

    # ── Public API ──────────────────────────────────────────────────

    # AFTER — cache hit avoids the API call on repeated lookups in the same session
    def find_row(self, ricefw_id: str) -> int | None:
        key = ricefw_id.strip().upper()
        if key in self._id_row_cache:
            return self._id_row_cache[key]

        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.SHEET_NAME}!B{self.DATA_START_ROW}:B"
        ).execute()
        # Populate the full cache while we have the data — avoids future misses
        for i, row in enumerate(result.get("values", [])):
            if row and row[0].strip():
                cached_key = row[0].strip().upper()
                self._id_row_cache[cached_key] = self.DATA_START_ROW + i

        return self._id_row_cache.get(key)

    def get_all_ids(self) -> list[str]:
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.SHEET_NAME}!B{self.DATA_START_ROW}:B"
        ).execute()
        return [r[0] for r in result.get("values", []) if r]

    def get_row(self, ricefw_id: str, fields: list[str] | None = None) -> dict:
        row_num = self.find_row(ricefw_id)
        if row_num is None:
            return {"ok": False, "error": f"{ricefw_id} not found in sheet"}
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.SHEET_NAME}!{row_num}:{row_num}"
        ).execute()
        headers  = self._get_header_row()
        values   = result.get("values", [[]])[0]
        row_data = {h: (values[i] if i < len(values) else "") for i, h in enumerate(headers)}
        if fields:
            row_data = {k: v for k, v in row_data.items() if k in fields}
        return {"ok": True, "ricefw_id": ricefw_id, "data": row_data}

    def update_cell(self, ricefw_id: str, field: str, value: str) -> dict:
        row_num = self.find_row(ricefw_id)
        if row_num is None:
            return {"ok": False, "error": f"{ricefw_id} not found"}
        col_idx = self._resolve_col_index(field)
        if col_idx is None:
            return {"ok": False, "error": f"Column '{field}' not found in header row"}
        col_letter = self._idx_to_col_letter(col_idx)
        cell_range = f"{self.SHEET_NAME}!{col_letter}{row_num}"
        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=cell_range,
            valueInputOption="USER_ENTERED",
            body={"values": [[value]]}
        ).execute()
        return {"ok": True, "updated_range": cell_range, "value": value}

    def format_row(self, ricefw_id: str, color: str,
                   scope: str = "color_column_only") -> dict:
        row_num = self.find_row(ricefw_id)
        if row_num is None:
            return {"ok": False, "error": f"{ricefw_id} not found"}
        rgb = self.COLOR_MAP.get(color, self.COLOR_MAP["white"])
        start_col, end_col = (0, 51) if scope == "entire_row" \
                              else (self.COLOR_INDEX, self.COLOR_INDEX)
        body = {"requests": [{
            "repeatCell": {
                "range": {
                    "sheetId": self._get_sheet_id(),
                    "startRowIndex": row_num - 1,
                    "endRowIndex":   row_num,
                    "startColumnIndex": start_col,
                    "endColumnIndex":   end_col + 1
                },
                "cell":   {"userEnteredFormat": {"backgroundColor": rgb}},
                "fields": "userEnteredFormat.backgroundColor"
            }
        }]}
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id, body=body
        ).execute()
        return {"ok": True, "formatted": ricefw_id, "color": color, "scope": scope}

    def next_ricefw_id(self, module: str) -> str:
        all_ids = self.get_all_ids()
        nums = []
        for i in all_ids:
            parts = i.split("-")
            if len(parts) == 2 and parts[0] == module and parts[1].isdigit():
                nums.append(int(parts[1]))
        return f"{module}-{(max(nums) + 1) if nums else 1:03d}"
    
    def _invalidate_row_cache(self, ricefw_id: str | None = None) -> None:
        """
        Call after any write that changes row positions or adds new IDs.
        Pass ricefw_id to evict just one entry, or None to clear entirely.
        """
        if ricefw_id:
            self._id_row_cache.pop(ricefw_id.strip().upper(), None)
        else:
            self._id_row_cache.clear()

    def add_row(self, ricefw_id: str, module: str, type: str,
                description: str, assigned_to: str = "",
                fields: dict | None = None) -> dict:
        headers = self._get_header_row()
        row = [""] * len(headers)
        field_map = {
            "RICEFW ID": ricefw_id,
            "Module": module,
            "Type": type,
            "Description": description,
            "Assigned To": assigned_to,
        }
        if fields:
            field_map.update(fields)
        for col_name, val in field_map.items():
            if col_name in headers:
                row[headers.index(col_name)] = val
        self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.SHEET_NAME}!A:A",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]}
        ).execute()
        self._invalidate_row_cache()
        return {"ok": True, "added": ricefw_id}
    # ── New: search_rows ─────────────────────────────────────────────────────

    def search_rows(
        self,
        filters: list[dict],
        return_fields: list[str] | None = None,
        limit: int = 20,
    ) -> dict:
        """
        Return all rows that match ALL supplied filter criteria (AND logic).

        Each filter is: {"field": str, "value": str, "match_type": "exact"|"contains"|"blank"}
        """
        from src.sheets.column_map import resolve_column

        headers = self._get_header_row()

        # Default return fields if caller didn't specify
        default_fields = [
            "RICEFW ID", "Module", "Type",
            "Description", "Dev Status", "Assigned To"
        ]
        return_fields = return_fields or [
            f for f in default_fields if f in headers
        ]

        # Resolve semantic field names in the filters to canonical header names
        resolved_filters = []
        for f in filters:
            canonical = resolve_column(f["field"]) or f["field"]
            resolved_filters.append({
                "field":      canonical,
                "value":      f.get("value", ""),
                "match_type": f.get("match_type", "exact"),
            })

        # Verify all filter columns exist
        for rf in resolved_filters:
            if rf["field"] not in headers:
                return {
                    "ok": False,
                    "error": f"Column '{rf['field']}' not found in sheet headers."
                }

        # Fetch all data rows in one API call
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.SHEET_NAME}!{self.DATA_START_ROW}:"
                  f"{self.DATA_START_ROW + 2000}"   # generous upper bound
        ).execute()
        all_rows = result.get("values", [])

        # Build column-index lookup
        col_idx = {h: i for i, h in enumerate(headers)}

        matches = []
        for row in all_rows:
            # Pad short rows with empty strings
            padded = row + [""] * (len(headers) - len(row))

            if not _row_matches(padded, resolved_filters, col_idx):
                continue

            # Build result dict for this row
            row_dict = {
                field: padded[col_idx[field]]
                for field in return_fields
                if field in col_idx
            }
            matches.append(row_dict)

            if len(matches) >= limit:
                break

        return {
            "ok":     True,
            "count":  len(matches),
            "rows":   matches,
            "capped": len(matches) == limit,
        }


    # ── New: bulk_update ─────────────────────────────────────────────────────

    def bulk_update(
        self,
        set_field: str,
        set_value: str,
        ricefw_ids: list[str] | None = None,
        filter_by:  dict | None = None,
    ) -> dict:
        """
        Update set_field = set_value on every row in ricefw_ids,
        OR on every row that matches filter_by criteria.

        filter_by shape: {"module": str, "field": str, "value": str}
        """
        from src.sheets.column_map import resolve_column

        headers = self._get_header_row()
        col_idx = {h: i for i, h in enumerate(headers)}

        # Resolve the target column name
        resolved_set_field = resolve_column(set_field) or set_field
        if resolved_set_field not in col_idx:
            return {"ok": False, "error": f"Column '{set_field}' not found."}

        # --- Determine the list of target IDs ---
        if ricefw_ids:
            target_ids = [r.strip().upper() for r in ricefw_ids]

        elif filter_by:
            # Resolve the filter column
            filter_col = resolve_column(filter_by["field"]) or filter_by["field"]
            if filter_col not in col_idx:
                return {
                    "ok": False,
                    "error": f"Filter column '{filter_by['field']}' not found."
                }

            # Fetch all rows and find matches
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.SHEET_NAME}!{self.DATA_START_ROW}:{self.DATA_START_ROW + 2000}"
            ).execute()
            all_rows = result.get("values", [])

            id_col_idx  = col_idx.get("RICEFW ID", col_idx.get("B", 1))
            mod_col_idx = col_idx.get("Module", 0)

            target_ids = []
            for row in all_rows:
                padded = row + [""] * (len(headers) - len(row))
                module_match = (
                    not filter_by.get("module") or
                    padded[mod_col_idx].strip().upper() == filter_by["module"].upper()
                )
                field_match = (
                    padded[col_idx[filter_col]].strip().lower() ==
                    filter_by["value"].strip().lower()
                )
                if module_match and field_match:
                    ricefw_id = padded[id_col_idx].strip()
                    if ricefw_id:
                        target_ids.append(ricefw_id.upper())
        else:
            return {
                "ok": False,
                "error": "Provide either ricefw_ids or filter_by."
            }

        if not target_ids:
            return {"ok": True, "updated": 0, "message": "No matching rows found."}

        # --- Execute individual updates ---
        succeeded, failed = [], []
        for rid in target_ids:
            result = self.update_cell(rid, resolved_set_field, set_value)
            if result.get("ok"):
                succeeded.append(rid)
            else:
                failed.append({"id": rid, "error": result.get("error")})

        return {
            "ok":        len(failed) == 0,
            "updated":   len(succeeded),
            "succeeded": succeeded,
            "failed":    failed,
        }


    # ── New: summarize ───────────────────────────────────────────────────────

    def summarize(
        self,
        report_type: str,
        group_by_field:             str | None = None,
        scope_module:               str | None = None,
        completion_field:           str | None = None,
        completion_value:           str | None = None,
        blank_field:                str | None = None,
        overdue_status_exclusions: list[str] | None = None,
    ) -> dict:
        """
        Produce aggregated statistics from the sheet.

        report_type options:
          count_by_field  — group rows by a column's values, count each group
          completion_rate — % of rows where completion_field == completion_value
          blank_fields    — count rows where blank_field is empty
          overdue         — rows past Go-Live Date and not in a done status
        """
        from datetime import datetime
        from src.sheets.column_map import resolve_column

        headers = self._get_header_row()
        col_idx = {h: i for i, h in enumerate(headers)}

        # Fetch all data rows once
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.SHEET_NAME}!{self.DATA_START_ROW}:{self.DATA_START_ROW + 2000}"
        ).execute()
        all_rows = result.get("values", [])

        # Scope to one module if requested
        mod_col = col_idx.get("Module")
        def in_scope(padded_row):
            if not scope_module or mod_col is None:
                return True
            return padded_row[mod_col].strip().upper() == scope_module.upper()

        rows = []
        for row in all_rows:
            padded = row + [""] * (len(headers) - len(row))
            if in_scope(padded):
                rows.append(padded)

        total = len(rows)

        # ── count_by_field ──────────────────────────────────────────────────
        if report_type == "count_by_field":
            if not group_by_field:
                return {"ok": False, "error": "group_by_field is required."}
            canonical = resolve_column(group_by_field) or group_by_field
            if canonical not in col_idx:
                return {"ok": False, "error": f"Column '{group_by_field}' not found."}

            idx = col_idx[canonical]
            counts: dict[str, int] = {}
            for row in rows:
                val = row[idx].strip() or "(blank)"
                counts[val] = counts.get(val, 0) + 1

            # Sort by count descending
            sorted_counts = sorted(counts.items(), key=lambda x: -x[1])

            return {
                "ok":        True,
                "report":    "count_by_field",
                "field":     canonical,
                "scope":     scope_module or "all modules",
                "total_rows": total,
                "breakdown": [{"value": v, "count": c} for v, c in sorted_counts],
            }

        # ── completion_rate ─────────────────────────────────────────────────
        elif report_type == "completion_rate":
            if not completion_field or not completion_value:
                return {
                    "ok": False,
                    "error": "completion_field and completion_value are required."
                }
            canonical = resolve_column(completion_field) or completion_field
            if canonical not in col_idx:
                return {"ok": False, "error": f"Column '{completion_field}' not found."}

            idx = col_idx[canonical]
            done  = sum(
                1 for row in rows
                if row[idx].strip().lower() == completion_value.strip().lower()
            )
            blank = sum(1 for row in rows if not row[idx].strip())
            pct   = round((done / total * 100), 1) if total else 0

            return {
                "ok":               True,
                "report":           "completion_rate",
                "field":            canonical,
                "target_value":     completion_value,
                "scope":            scope_module or "all modules",
                "total_rows":       total,
                "completed":        done,
                "not_completed":    total - done,
                "blank":            blank,
                "completion_pct":   pct,
            }

        # ── blank_fields ────────────────────────────────────────────────────
        elif report_type == "blank_fields":
            if not blank_field:
                return {"ok": False, "error": "blank_field is required."}
            canonical = resolve_column(blank_field) or blank_field
            if canonical not in col_idx:
                return {"ok": False, "error": f"Column '{blank_field}' not found."}

            idx    = col_idx[canonical]
            blanks = [
                row[col_idx.get("RICEFW ID", 1)].strip()
                for row in rows
                if not row[idx].strip()
            ]

            return {
                "ok":          True,
                "report":      "blank_fields",
                "field":       canonical,
                "scope":       scope_module or "all modules",
                "total_rows":  total,
                "blank_count": len(blanks),
                "blank_pct":   round(len(blanks) / total * 100, 1) if total else 0,
                "ids":         blanks[:50],  # cap list at 50 for readability
            }

        # ── overdue ─────────────────────────────────────────────────────────
        elif report_type == "overdue":
            done_statuses = set(
                s.lower() for s in
                (overdue_status_exclusions or
                 ["Complete", "Done", "Closed", "Go-Live", "Retired"])
            )

            date_col   = col_idx.get("Go-Live Date")
            status_col = col_idx.get("Dev Status")
            id_col     = col_idx.get("RICEFW ID", 1)

            if date_col is None:
                return {
                    "ok": False,
                    "error": "No 'Go-Live Date' column found. Check column name."
                }

            today = datetime.today().date()
            overdue = []

            for row in rows:
                status = row[status_col].strip().lower() if status_col else ""
                if status in done_statuses:
                    continue
                raw_date = row[date_col].strip()
                if not raw_date:
                    continue
                # Try common date formats
                for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y"):
                    try:
                        go_live = datetime.strptime(raw_date, fmt).date()
                        if go_live < today:
                            overdue.append({
                                "id":          row[id_col].strip(),
                                "go_live_date": raw_date,
                                "dev_status":  row[status_col].strip() if status_col else "",
                                "days_overdue": (today - go_live).days,
                            })
                        break
                    except ValueError:
                        continue

            overdue.sort(key=lambda x: -x["days_overdue"])

            return {
                "ok":          True,
                "report":      "overdue",
                "scope":       scope_module or "all modules",
                "total_rows":  total,
                "overdue_count": len(overdue),
                "items":       overdue[:30],  # cap at 30
            }

        return {"ok": False, "error": f"Unknown report_type: {report_type}"}


# ── Helper (module-level, not a class method) ─────────────────────────────────

def _row_matches(padded_row: list, filters: list[dict], col_idx: dict) -> bool:
    """Return True if the row satisfies all filter conditions (AND logic)."""
    for f in filters:
        idx = col_idx.get(f["field"])
        if idx is None:
            return False
        cell = padded_row[idx].strip()
        match_type = f.get("match_type", "exact")

        if match_type == "blank":
            if cell != "":
                return False
        elif match_type == "contains":
            if f["value"].lower() not in cell.lower():
                return False
        else:  # exact
            if cell.lower() != f["value"].lower():
                return False
    return True