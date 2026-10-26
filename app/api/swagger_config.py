from typing import Dict, Any
from flasgger import Swagger
from flask import Flask, redirect

SWAGGER_TEMPLATE: Dict[str, Any] = {
    "swagger": "2.0",
    "info": {
        "title": "Agent 34: Merchant & User Fraud Investigation Agent API",
        "description": (
            "Complete forensic fraud investigation platform API.\n\n"
            "Features include:\n"
            "- Multi-threaded external fraud signal ingestion with distributed Redis idempotency locks\n"
            "- Read-only evidence gathering (Users, Orders, Payments, Chargebacks)\n"
            "- Multi-hop entity graph network correlation (ArangoDB / Relational graph traversal)\n"
            "- Approved SOP Policy retrieval (ChromaDB RAG)\n"
            "- Multi-provider AI reasoning (Gemini, Local Mistral, OpenAI, Claude, Azure OpenAI)\n"
            "- Deterministic Decision Gateway & Action Service"
        ),
        "version": "1.0.0",
        "contact": {
            "name": "Fraud Investigation Engineering Team",
            "url": "http://localhost:5173"
        }
    },
    "basePath": "/api/v1",
    "schemes": ["http", "https"],
    "consumes": ["application/json"],
    "produces": ["application/json"],
    "tags": [
        {"name": "Health", "description": "Liveness and dependency readiness probes"},
        {"name": "Investigations", "description": "External fraud signal intake, case tracking, and analyst review"},
        {"name": "Dashboard", "description": "Operational KPIs and case statistics"},
        {"name": "Actions", "description": "Authorized risk mitigation and enforcement execution"},
        {"name": "Audit", "description": "Immutable tamper-evident audit trail events"},
        {"name": "Integrations", "description": "Infrastructure and active LLM provider health"}
    ],
    "paths": {
        "/health/live": {
            "get": {
                "tags": ["Health"],
                "summary": "Process Liveness Probe",
                "description": "Returns HTTP 200 UP if Flask server is responsive.",
                "responses": {
                    "200": {
                        "description": "Server is alive",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "status": {"type": "string", "example": "UP"},
                                "service": {"type": "string", "example": "FraudInvestigationAgent"},
                                "timestamp": {"type": "string", "example": "OK"}
                            }
                        }
                    }
                }
            }
        },
        "/health/ready": {
            "get": {
                "tags": ["Health"],
                "summary": "Dependency Readiness Probe",
                "description": "Inspects real connectivity to MySQL, Redis, ChromaDB, ArangoDB, and the active LLM Provider.",
                "responses": {
                    "200": {
                        "description": "System ready",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "status": {"type": "string", "example": "READY"},
                                "dependencies": {"type": "object"}
                            }
                        }
                    },
                    "503": {
                        "description": "Critical dependency unavailable"
                    }
                }
            }
        },
        "/investigations": {
            "post": {
                "tags": ["Investigations"],
                "summary": "Ingest External Fraud Signal",
                "description": "Ingests a fraud signal, acquires a Redis distributed lock, creates an investigation case, and launches LangGraph reasoning workflow.",
                "parameters": [
                    {
                        "name": "body",
                        "in": "body",
                        "required": True,
                        "schema": {
                            "$ref": "#/definitions/TriggerRequest"
                        }
                    }
                ],
                "responses": {
                    "201": {
                        "description": "Investigation case created and processed",
                        "schema": {
                            "$ref": "#/definitions/TriggerResponse"
                        }
                    },
                    "200": {
                        "description": "Duplicate signal safely handled via idempotency key (existing case returned)",
                        "schema": {
                            "$ref": "#/definitions/TriggerResponse"
                        }
                    },
                    "422": {
                        "description": "Validation Error (invalid payload)"
                    }
                }
            },
            "get": {
                "tags": ["Investigations"],
                "summary": "List Paginated Investigations",
                "description": "Retrieves investigation cases with status, priority, and search filtering.",
                "parameters": [
                    {"name": "status", "in": "query", "type": "string", "description": "Filter by status (e.g. RECEIVED, UNDER_INVESTIGATION, REQUIRES_REVIEW, CLOSED, ESCALATED)"},
                    {"name": "priority", "in": "query", "type": "string", "description": "Filter by priority (LOW, MEDIUM, HIGH, CRITICAL)"},
                    {"name": "search", "in": "query", "type": "string", "description": "Search keyword in reason, merchant, user, or transaction"},
                    {"name": "page", "in": "query", "type": "integer", "default": 1},
                    {"name": "page_size", "in": "query", "type": "integer", "default": 20}
                ],
                "responses": {
                    "200": {
                        "description": "Paginated list of investigation cases",
                        "schema": {
                            "$ref": "#/definitions/PaginatedCases"
                        }
                    }
                }
            }
        },
        "/investigations/{case_id}": {
            "get": {
                "tags": ["Investigations"],
                "summary": "Get Case Details",
                "description": "Returns complete details, timeline, and associated entity references for a case.",
                "parameters": [
                    {"name": "case_id", "in": "path", "type": "string", "required": True, "description": "Unique UUID of the investigation case"}
                ],
                "responses": {
                    "200": {"description": "Case details retrieved"},
                    "404": {"description": "Case not found"}
                }
            }
        },
        "/investigations/{case_id}/evidence": {
            "get": {
                "tags": ["Investigations"],
                "summary": "Get Case Evidence Inventory",
                "description": "Retrieves normalized forensic evidence gathered for the case.",
                "parameters": [
                    {"name": "case_id", "in": "path", "type": "string", "required": True}
                ],
                "responses": {
                    "200": {"description": "Evidence items list"},
                    "404": {"description": "Case not found"}
                }
            }
        },
        "/investigations/{case_id}/recommendation": {
            "get": {
                "tags": ["Investigations"],
                "summary": "Get AI Structured Recommendation",
                "description": "Returns the latest LLM-synthesized fraud assessment, risk indicators, counter signals, and policy citations.",
                "parameters": [
                    {"name": "case_id", "in": "path", "type": "string", "required": True}
                ],
                "responses": {
                    "200": {"description": "Structured recommendation object"},
                    "404": {"description": "Case not found"}
                }
            }
        },
        "/investigations/{case_id}/decisions": {
            "post": {
                "tags": ["Investigations"],
                "summary": "Submit Analyst Review Decision",
                "description": "Records an analyst's decision and triggers authorized action if approved.",
                "parameters": [
                    {"name": "case_id", "in": "path", "type": "string", "required": True},
                    {
                        "name": "body",
                        "in": "body",
                        "required": True,
                        "schema": {
                            "$ref": "#/definitions/ReviewDecisionRequest"
                        }
                    }
                ],
                "responses": {
                    "200": {"description": "Decision successfully recorded"},
                    "404": {"description": "Case not found"}
                }
            }
        },
        "/dashboard/summary": {
            "get": {
                "tags": ["Dashboard"],
                "summary": "Get KPI Dashboard Summary",
                "description": "Computes aggregated case counts, priority distribution, pending review counts, and recent activity log.",
                "responses": {
                    "200": {
                        "description": "Dashboard summary statistics",
                        "schema": {
                            "$ref": "#/definitions/DashboardSummary"
                        }
                    }
                }
            }
        },
        "/actions/execute": {
            "post": {
                "tags": ["Actions"],
                "summary": "Execute Risk Mitigation Action",
                "description": "Executes an authorized mutation (e.g. HOLD_TRANSACTION, BLOCK_USER, TEMPORARY_RESTRICTION) with idempotency protection and audit logging.",
                "parameters": [
                    {
                        "name": "body",
                        "in": "body",
                        "required": True,
                        "schema": {
                            "$ref": "#/definitions/ActionExecutionRequest"
                        }
                    }
                ],
                "responses": {
                    "200": {"description": "Action executed successfully"},
                    "404": {"description": "Case not found"}
                }
            }
        },
        "/actions/history": {
            "get": {
                "tags": ["Actions"],
                "summary": "Get Action Execution History",
                "description": "Returns log of authorized actions with execution statuses and downstream confirmation references.",
                "responses": {
                    "200": {"description": "List of executed actions"}
                }
            }
        },
        "/audit/events": {
            "get": {
                "tags": ["Audit"],
                "summary": "Search Audit Trail Events",
                "description": "Filterable tamper-evident operational event logs with SHA-256 hashes.",
                "parameters": [
                    {"name": "case_id", "in": "query", "type": "string"},
                    {"name": "event_type", "in": "query", "type": "string"},
                    {"name": "page", "in": "query", "type": "integer", "default": 1},
                    {"name": "page_size", "in": "query", "type": "integer", "default": 50}
                ],
                "responses": {
                    "200": {"description": "List of audit trail records"}
                }
            }
        },
        "/integrations/status": {
            "get": {
                "tags": ["Integrations"],
                "summary": "Get Infrastructure & LLM Provider Status",
                "description": "Reports operational status of MySQL, Redis, ChromaDB, ArangoDB, and the active LLM Provider (Gemini / Mistral / OpenAI / Claude / Azure OpenAI).",
                "responses": {
                    "200": {"description": "Integrations operational health"}
                }
            }
        }
    },
    "definitions": {
        "TriggerRequest": {
            "type": "object",
            "required": ["trigger_type", "trigger_source", "trigger_reason", "priority", "idempotency_key"],
            "properties": {
                "trigger_type": {
                    "type": "string",
                    "enum": [
                        "TRANSACTION_INVESTIGATION",
                        "MERCHANT_DISPUTE_SPIKE",
                        "USER_TAKEOVER_ALERT",
                        "VELOCITY_BURST",
                        "REFUND_ABUSE"
                    ],
                    "example": "MERCHANT_DISPUTE_SPIKE"
                },
                "trigger_source": {
                    "type": "string",
                    "example": "RISK_RULES_ENGINE"
                },
                "trigger_reason": {
                    "type": "string",
                    "example": "Chargeback velocity exceeded 2.5% threshold within 1 hour"
                },
                "priority": {
                    "type": "string",
                    "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
                    "example": "HIGH"
                },
                "merchant_id": {
                    "type": "string",
                    "example": "merch_demo_101"
                },
                "user_id": {
                    "type": "string",
                    "example": "usr_demo_202"
                },
                "transaction_id": {
                    "type": "string",
                    "example": "tx_demo_303"
                },
                "idempotency_key": {
                    "type": "string",
                    "example": "idem_trigger_987654321"
                }
            }
        },
        "TriggerResponse": {
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "example": "fa24fa4f-80cc-42f5-aab1-0e87feffaccd"},
                "status": {"type": "string", "example": "REQUIRES_REVIEW"},
                "priority": {"type": "string", "example": "HIGH"},
                "idempotency_key": {"type": "string", "example": "idem_trigger_987654321"},
                "is_duplicate": {"type": "boolean", "example": False},
                "message": {"type": "string", "example": "Investigation completed and routed."},
                "created_at": {"type": "string", "example": "2026-10-26T06:04:28"}
            }
        },
        "ReviewDecisionRequest": {
            "type": "object",
            "required": ["decision", "reviewer_id", "decision_rationale"],
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": ["APPROVE_RECOMMENDATION", "MODIFY_ACTION", "OVERRIDE_CLOSE", "ESCALATE"],
                    "example": "APPROVE_RECOMMENDATION"
                },
                "reviewer_id": {
                    "type": "string",
                    "example": "analyst_sarah_01"
                },
                "modified_action": {
                    "type": "string",
                    "enum": ["NO_ACTION", "MONITOR", "HOLD_TRANSACTION", "TEMPORARY_RESTRICTION", "BLOCK_USER", "BLOCK_MERCHANT", "ESCALATE"],
                    "example": "HOLD_TRANSACTION"
                },
                "decision_rationale": {
                    "type": "string",
                    "example": "Confirmed repeated dispute spikes without customer response. Approved temporary hold."
                },
                "policy_reference": {
                    "type": "string",
                    "example": "SOP-FRAUD-SEC-4.2"
                }
            }
        },
        "ActionExecutionRequest": {
            "type": "object",
            "required": ["case_id", "action_type", "requested_by", "target_reference", "idempotency_key"],
            "properties": {
                "case_id": {"type": "string", "example": "fa24fa4f-80cc-42f5-aab1-0e87feffaccd"},
                "action_type": {
                    "type": "string",
                    "enum": ["NO_ACTION", "MONITOR", "HOLD_TRANSACTION", "TEMPORARY_RESTRICTION", "BLOCK_USER", "BLOCK_MERCHANT", "ESCALATE"],
                    "example": "HOLD_TRANSACTION"
                },
                "requested_by": {"type": "string", "example": "ANALYST_01"},
                "target_reference": {"type": "string", "example": "tx_demo_303"},
                "idempotency_key": {"type": "string", "example": "act_idem_12345"},
                "policy_reference": {"type": "string", "example": "SOP-SEC-4.2"}
            }
        },
        "DashboardSummary": {
            "type": "object",
            "properties": {
                "total_investigations": {"type": "integer", "example": 25},
                "pending_review_count": {"type": "integer", "example": 10},
                "actions_executed_count": {"type": "integer", "example": 5},
                "status_distribution": {"type": "object", "example": {"REQUIRES_REVIEW": 10, "CLOSED": 15}},
                "priority_distribution": {"type": "object", "example": {"HIGH": 12, "MEDIUM": 8, "CRITICAL": 5}},
                "recent_activity": {"type": "array", "items": {"type": "object"}},
                "is_empty": {"type": "boolean", "example": False}
            }
        },
        "PaginatedCases": {
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": {"type": "object"}},
                "total": {"type": "integer", "example": 25},
                "page": {"type": "integer", "example": 1},
                "page_size": {"type": "integer", "example": 20},
                "total_pages": {"type": "integer", "example": 2}
            }
        }
    }
}

SWAGGER_CONFIG: Dict[str, Any] = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/api/v1/swagger.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/api/docs"
}

def init_swagger(app: Flask) -> Swagger:
    """Initializes Flasgger Swagger UI on Flask application."""
    swagger = Swagger(app, config=SWAGGER_CONFIG, template=SWAGGER_TEMPLATE)

    # Convenient root redirects for /docs and /swagger
    @app.route("/docs")
    def docs_redirect():
        return redirect("/api/docs")

    @app.route("/swagger")
    def swagger_redirect():
        return redirect("/api/docs")

    return swagger
