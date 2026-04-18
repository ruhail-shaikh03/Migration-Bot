TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_row",
            "description": "Read the current values of a WRICEF object by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ricefw_id": {
                        "type": "string",
                        "description": "The RICEFW ID, e.g. SD-045, FI-012, PM-161.",
                        "pattern": "^[A-Z]{2,3}-[0-9]{3}$"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific field names to return. Empty = return all."
                    }
                },
                "required": ["ricefw_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_cell",
            "description": "Update one or more field values for a WRICEF object.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ricefw_id": {"type": "string"},
                    "updates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field":  {"type": "string"},
                                "value": {"type": "string"}
                            },
                            "required": ["field", "value"]
                        }
                    }
                },
                "required": ["ricefw_id", "updates"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "format_row",
            "description": "Apply background color to a row or specific cells.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ricefw_id": {"type": "string"},
                    "color": {
                        "type": "string",
                        "enum": ["red", "green", "amber", "blue", "white"]
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["entire_row", "color_column_only"],
                        "default": "color_column_only"
                    }
                },
                "required": ["ricefw_id", "color"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_row",
            "description": "Append a new WRICEF object to the migration tracker.",
            "parameters": {
                "type": "object",
                "properties": {
                    "module": {
                        "type": "string",
                        "enum": ["FI","MM","SD","PM","QM","PP","TRM","HCM","IM","CO","FM","PS"]
                    },
                    "type": {
                        "type": "string",
                        "enum": ["R","I","C","E","F","W"]
                    },
                    "description": {"type": "string"},
                    "assigned_to":  {"type": "string"},
                    "fields": {
                        "type": "object",
                        "additionalProperties": {"type": "string"}
                    }
                },
                "required": ["module", "type", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bulk_update",
            "description": (
                "Update one field to one value across multiple RICEFW objects at once. "
                "Use this when the user says things like 'mark all of these as done', "
                "'set everyone on this list to Ready for Dev', or "
                "'update SD-001 through SD-005 status to In Progress'. "
                "Can also accept a filter (e.g. module + current field value) instead "
                "of an explicit list of IDs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ricefw_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Explicit list of RICEFW IDs to update. "
                            "Provide either this OR filter_by, not both."
                        )
                    },
                    "filter_by": {
                        "type": "object",
                        "description": (
                            "Instead of listing IDs, describe which rows to target. "
                            "E.g. {\"module\": \"SD\", \"field\": \"Dev Status\", "
                            "\"value\": \"In Progress\"}. "
                            "All three sub-keys are required if filter_by is used."
                        ),
                        "properties": {
                            "module": {
                                "type": "string",
                                "enum": ["FI","MM","SD","PM","QM","PP",
                                         "TRM","HCM","IM","CO","FM","PS"]
                            },
                            "field": {
                                "type": "string",
                                "description": "Column name to filter on."
                            },
                            "value": {
                                "type": "string",
                                "description": "Current cell value to match."
                            }
                        }
                    },
                    "set_field": {
                        "type": "string",
                        "description": "The column to update on every matched row."
                    },
                    "set_value": {
                        "type": "string",
                        "description": "The value to write into set_field."
                    }
                },
                "required": ["set_field", "set_value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_rows",
            "description": (
                "Search the migration tracker and return all RICEFW objects that match "
                "one or more field criteria. Supports single-field and multi-field "
                "filters. Use this when the user asks things like 'show me all SD "
                "objects owned by Ahmed', 'which items are still not migrated?', "
                "'find all FI reports with no dev status', or 'list everything "
                "assigned to Sara'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filters": {
                        "type": "array",
                        "description": (
                            "List of field/value pairs that all must match "
                            "(AND logic). Use an empty string value to find "
                            "rows where that field is blank."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {
                                    "type": "string",
                                    "description": "Column name to filter on."
                                },
                                "value": {
                                    "type": "string",
                                    "description": (
                                        "Value to match. Case-insensitive. "
                                        "Use empty string \"\" to find blank cells."
                                    )
                                },
                                "match_type": {
                                    "type": "string",
                                    "enum": ["exact", "contains", "blank"],
                                    "default": "exact",
                                    "description": (
                                        "'exact': cell equals value. "
                                        "'contains': cell contains value as substring. "
                                        "'blank': cell is empty (value is ignored)."
                                    )
                                }
                            },
                            "required": ["field", "value"]
                        },
                        "minItems": 1
                    },
                    "return_fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Which columns to include in each result row. "
                            "If omitted, returns RICEFW ID, Module, Type, "
                            "Description, Dev Status, and Assigned To."
                        )
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return. Default 20.",
                        "default": 20
                    }
                },
                "required": ["filters"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "summarize",
            "description": (
                "Aggregate and count data across the migration tracker. Use this for "
                "questions like 'how many items are in each status?', 'what's our "
                "overall completion rate?', 'how many SD objects are assigned to each "
                "person?', 'which items have no dev status?', or "
                "'how many are past their go-live date?'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "report_type": {
                        "type": "string",
                        "enum": [
                            "count_by_field",
                            "completion_rate",
                            "blank_fields",
                            "overdue"
                        ],
                        "description": (
                            "'count_by_field': group rows by a field's values and count each group. "
                            "'completion_rate': what % of rows have a specific field set to a "
                            "target value (e.g. Migrate? = Yes). "
                            "'blank_fields': count rows where a field is empty. "
                            "'overdue': rows where Go-Live Date is in the past and "
                            "Dev Status is not a completion value."
                        )
                    },
                    "group_by_field": {
                        "type": "string",
                        "description": (
                            "Required for count_by_field. The column to group rows by. "
                            "E.g. 'Dev Status', 'Module', 'Assigned To'."
                        )
                    },
                    "scope_module": {
                        "type": "string",
                        "enum": ["FI","MM","SD","PM","QM","PP",
                                 "TRM","HCM","IM","CO","FM","PS"],
                        "description": (
                            "Optional. Restrict the report to one SAP module. "
                            "Omit to report across all modules."
                        )
                    },
                    "completion_field": {
                        "type": "string",
                        "description": (
                            "Required for completion_rate. The column to measure. "
                            "E.g. 'Migrate?'."
                        )
                    },
                    "completion_value": {
                        "type": "string",
                        "description": (
                            "Required for completion_rate. The value that counts as "
                            "'complete'. E.g. 'Yes', 'Done', 'Ready for Dev'."
                        )
                    },
                    "blank_field": {
                        "type": "string",
                        "description": "Required for blank_fields. Column to check for blanks."
                    },
                    "overdue_status_exclusions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "For overdue report: Dev Status values that mean 'done' and "
                            "should be excluded. Defaults to ['Complete', 'Done', 'Closed', "
                            "'Go-Live', 'Retired']."
                        )
                    }
                },
                "required": ["report_type"]
            }
        }
    },
]

VALID_MODULES = "FI,MM,SD,PM,QM,PP,TRM,HCM,IM,CO,FM,PS"

SYSTEM_PROMPT = """
You are MigrationBot, an assistant for managing the S/4HANA WRICEF Migration
Control Sheet in Google Sheets. You have four tools: get_row, update_cell,
format_row, and add_row.

RULES:
1. Always extract the RICEFW ID from the user's message first. It follows the
   pattern MODULE-NNN (e.g. SD-045, FI-012). Valid modules: {valid_modules}.
2. Map natural-language field references to column names semantically:
   "status" or "dev status"         → "Dev Status"
   "migrate" or "should we migrate" → "Migrate?"
   "flag it" / "color column"       → format_row with color_column_only scope
   "highlight green"                → format_row, color=green, scope=entire_row
   "job frequency" / "batch schedule" → "Job Frequency"
3. If the RICEFW ID is ambiguous or missing, ask for clarification. Do NOT guess.
4. Conditional commands ("if PM-161 is marked for migration, set frequency to Monthly"):
   call get_row first, evaluate the result, then conditionally call update_cell.
5. For add_row, find the next RICEFW ID in sequence by scanning existing IDs first.
6. Never invent column names. If ambiguous, list three closest matches and ask.
7. Confirmations: one sentence. Reads: compact key-value list.
8. BULK OPERATIONS — use bulk_update when the user provides a list of IDs or
   says "all [module] items where [condition]". Always confirm how many rows
   will be affected before summarising results. Use filter_by when the user
   describes a condition rather than listing IDs explicitly.
9. SEARCH — use search_rows when the user asks "show me", "find", "list", or
   "which items". If they don't specify return_fields, use the default set.
   For partial-name searches on people ("find Sara's items") use match_type=contains.
   For "items with no dev status" use match_type=blank.
10. REPORTING — use summarize when the user asks "how many", "what percentage",
    "completion rate", "overdue", or "which fields are empty". Always pick the
    most specific report_type. For "how complete is the SD workstream?" use
    completion_rate. For "who has the most items?" use count_by_field on
    Assigned To with scope_module omitted.
11. Never call bulk_update without confirming the target set of rows in your
    reply. State "Updated X rows" in the confirmation sentence.

Column reference guide:
{column_map_json}
"""