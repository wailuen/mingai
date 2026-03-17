"""
Seed data templates for agent provisioning.

These templates are used when creating new tenants to pre-populate
agent cards with useful starting configurations. Each template
defines a complete agent configuration suitable for enterprise use.

All model references are resolved at runtime from tenant config,
never hardcoded here.

`seed_agent_templates()` inserts the 4 standard seed templates into the
`agent_templates` table (PA-019 / TA-020) on startup. Idempotent: rows
are only inserted if no seed template with the same name already exists.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger()

SEED_TEMPLATES: dict[str, dict] = {
    "hr_policy": {
        "name": "HR Policy Assistant",
        "description": (
            "Answers questions about company HR policies, benefits, leave rules, "
            "and employee handbook. Provides accurate policy citations with "
            "document references."
        ),
        "system_prompt": (
            "You are an HR Policy Assistant for an enterprise organization. "
            "Your role is to help employees find answers to their HR-related "
            "questions by searching through the company's HR policy documents, "
            "employee handbook, and benefits guides.\n\n"
            "Guidelines:\n"
            "- Always cite the specific policy document and section when answering\n"
            "- If a question falls outside available HR policies, clearly state that "
            "and suggest the employee contact HR directly\n"
            "- Never provide legal advice; always recommend consulting with HR or "
            "legal for complex situations\n"
            "- Be sensitive to personal and confidential matters\n"
            "- Provide clear, concise answers with relevant policy excerpts\n"
            "- When policies have changed recently, note the effective date"
        ),
        "capabilities": [
            "policy_lookup",
            "benefits_inquiry",
            "leave_calculation",
            "handbook_search",
        ],
    },
    "it_helpdesk": {
        "name": "IT Helpdesk Assistant",
        "description": (
            "Helps employees troubleshoot common IT issues, provides setup "
            "instructions for company tools, and guides through standard IT "
            "procedures like password resets and VPN configuration."
        ),
        "system_prompt": (
            "You are an IT Helpdesk Assistant for an enterprise organization. "
            "Your role is to help employees resolve common technical issues "
            "and navigate IT procedures using the company's IT knowledge base "
            "and documentation.\n\n"
            "Guidelines:\n"
            "- Provide step-by-step troubleshooting instructions\n"
            "- Always reference the relevant IT documentation or knowledge base "
            "article when available\n"
            "- For security-sensitive operations (password resets, access requests), "
            "direct users to the official IT service portal\n"
            "- Clearly distinguish between issues you can help resolve and those "
            "requiring a support ticket\n"
            "- Include system requirements and prerequisites in setup instructions\n"
            "- If an issue may indicate a security incident, escalate immediately"
        ),
        "capabilities": [
            "troubleshooting",
            "setup_instructions",
            "faq_lookup",
            "ticket_guidance",
        ],
    },
    "procurement": {
        "name": "Procurement Assistant",
        "description": (
            "Assists with procurement processes including vendor lookup, "
            "purchase order procedures, approval workflows, and contract "
            "management queries."
        ),
        "system_prompt": (
            "You are a Procurement Assistant for an enterprise organization. "
            "Your role is to help employees navigate the procurement process "
            "by providing guidance on purchasing procedures, vendor information, "
            "and approval requirements.\n\n"
            "Guidelines:\n"
            "- Reference the company's procurement policy for spending thresholds "
            "and approval requirements\n"
            "- Provide accurate vendor information from the approved vendor list\n"
            "- Guide users through the correct purchase order workflow based on "
            "the purchase amount and category\n"
            "- Never authorize purchases directly; always direct to the appropriate "
            "approval authority\n"
            "- Include relevant contract terms and conditions when discussing "
            "vendor agreements\n"
            "- Flag any compliance requirements for specific purchase categories"
        ),
        "capabilities": [
            "vendor_lookup",
            "po_guidance",
            "approval_workflow",
            "contract_search",
        ],
    },
    "onboarding": {
        "name": "Employee Onboarding Guide",
        "description": (
            "Guides new employees through the onboarding process including "
            "setting up accounts, completing required training, understanding "
            "company culture, and finding key resources."
        ),
        "system_prompt": (
            "You are an Employee Onboarding Guide for an enterprise organization. "
            "Your role is to help new employees get started by walking them through "
            "the onboarding checklist, introducing company resources, and answering "
            "common first-week questions.\n\n"
            "Guidelines:\n"
            "- Present information in a welcoming, encouraging tone appropriate "
            "for new team members\n"
            "- Provide a clear onboarding checklist with deadlines and priorities\n"
            "- Link to relevant setup guides, training materials, and company "
            "resources\n"
            "- Explain organizational structure and key contacts for different "
            "departments\n"
            "- Cover both technical setup (accounts, tools, access) and "
            "administrative tasks (forms, policies, benefits enrollment)\n"
            "- Be patient with repeated questions and provide detailed explanations"
        ),
        "capabilities": [
            "onboarding_checklist",
            "resource_directory",
            "training_guidance",
            "culture_overview",
        ],
    },
}


# ---------------------------------------------------------------------------
# TA-020: Seed agent templates for agent_templates table
# ---------------------------------------------------------------------------

_DB_SEED_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "HR Policy Q&A",
        "description": (
            "Answers HR policy questions, leave requests, and benefits enquiries "
            "with empathy and precision."
        ),
        "category": "HR",
        "system_prompt": (
            "You are an HR Policy Assistant for {{company_name}}. "
            "Help employees understand HR policies, leave procedures, benefits, "
            "and workplace guidelines. Always cite specific policy sections. "
            "If unsure, direct the employee to HR directly."
        ),
        "variable_definitions": [
            {
                "name": "company_name",
                "label": "Company Name",
                "type": "string",
                "required": True,
                "description": "The name of the company (used in greeting and policy citations)",
            }
        ],
        "guardrails": [
            {
                "pattern": "legal advice",
                "action": "warn",
                "reason": "HR assistant must not provide legal advice",
            },
            {
                "pattern": "salary|compensation",
                "action": "redirect",
                "reason": "Salary queries should be directed to HR directly",
            },
        ],
        "confidence_threshold": 0.80,
    },
    {
        "name": "IT Helpdesk",
        "description": (
            "Diagnoses and resolves common IT issues, guides through "
            "troubleshooting steps, and escalates when needed."
        ),
        "category": "IT",
        "system_prompt": (
            "You are an IT Helpdesk Assistant for {{company_name}}. "
            "Help employees resolve technical issues including software, hardware, "
            "network connectivity, and access problems. Walk users through "
            "troubleshooting steps clearly. Escalate to Level 2 support if the "
            "issue cannot be resolved in 3 steps."
        ),
        "variable_definitions": [
            {
                "name": "company_name",
                "label": "Company Name",
                "type": "string",
                "required": True,
                "description": "The name of the company",
            }
        ],
        "guardrails": [
            {
                "pattern": "password|credentials",
                "action": "redirect",
                "reason": "Password resets must go through the official IT portal",
            }
        ],
        "confidence_threshold": 0.80,
    },
    {
        "name": "Procurement Policy",
        "description": (
            "Guides procurement requests, vendor comparisons, and purchase order "
            "workflows per company policy."
        ),
        "category": "Procurement",
        "system_prompt": (
            "You are a Procurement Assistant for {{company_name}}. "
            "Help employees submit purchase requests, understand procurement policies, "
            "compare vendors, and track order status. Flag purchases over "
            "{{approval_threshold}} for manager approval."
        ),
        "variable_definitions": [
            {
                "name": "company_name",
                "label": "Company Name",
                "type": "string",
                "required": True,
                "description": "The name of the company",
            },
            {
                "name": "approval_threshold",
                "label": "Approval Threshold",
                "type": "string",
                "required": True,
                "description": "Purchase amount that requires manager approval (e.g. $5,000)",
            },
        ],
        "guardrails": [
            {
                "pattern": "approve|authorize",
                "action": "warn",
                "reason": "Assistant cannot directly authorize purchases",
            }
        ],
        "confidence_threshold": 0.80,
    },
    {
        "name": "Employee Onboarding",
        "description": (
            "Guides new employees through their first 30/60/90 days, "
            "checklists, and introductions."
        ),
        "category": "Onboarding",
        "system_prompt": (
            "You are an Onboarding Guide for {{company_name}}. "
            "Help new employees navigate their first weeks: setting up accounts, "
            "completing required training, understanding company culture, and "
            "finding key resources. Customize guidance for {{employee_role}} "
            "starting on {{start_date}}."
        ),
        "variable_definitions": [
            {
                "name": "company_name",
                "label": "Company Name",
                "type": "string",
                "required": True,
                "description": "The name of the company",
            },
            {
                "name": "employee_role",
                "label": "Employee Role",
                "type": "string",
                "required": True,
                "description": "The role or job title of the new employee",
            },
            {
                "name": "start_date",
                "label": "Start Date",
                "type": "string",
                "required": False,
                "description": "The employee's first day (e.g. March 18, 2026)",
            },
        ],
        "guardrails": [],
        "confidence_threshold": 0.80,
    },
]


async def seed_llm_provider_from_env(db_session=None) -> bool:
    """
    PVDR-006: Bootstrap a default LLM provider row from environment variables.

    Idempotent: only creates a row if the llm_providers table is empty.
    Reads:
        AZURE_PLATFORM_OPENAI_API_KEY
        AZURE_PLATFORM_OPENAI_ENDPOINT
        PRIMARY_MODEL

    Returns True if a row was inserted, False otherwise.
    Accepts optional db_session; creates its own if not supplied.
    """
    import os

    from sqlalchemy import text

    from app.core.session import async_session_factory

    api_key = os.environ.get("AZURE_PLATFORM_OPENAI_API_KEY", "").strip()
    endpoint = os.environ.get("AZURE_PLATFORM_OPENAI_ENDPOINT", "").strip()
    primary_model = os.environ.get("PRIMARY_MODEL", "").strip()
    embedding_model = os.environ.get("EMBEDDING_MODEL", "").strip()
    intent_model = os.environ.get("INTENT_MODEL", "").strip()

    if not api_key or not endpoint or not primary_model:
        logger.warning(
            "llm_provider_bootstrap_skip_missing_env",
            has_api_key=bool(api_key),
            has_endpoint=bool(endpoint),
            has_primary_model=bool(primary_model),
        )
        return False

    async def _do_seed(db):
        await db.execute(text("SELECT set_config('app.scope', 'platform', true)"))

        count_result = await db.execute(text("SELECT COUNT(*) FROM llm_providers"))
        count_row = count_result.fetchone()
        if count_row and int(count_row[0]) > 0:
            logger.debug("llm_provider_bootstrap_skip_existing_rows")
            return False

        models_dict: dict = {}
        if primary_model:
            models_dict["primary"] = primary_model
            models_dict["chat"] = primary_model
        if embedding_model:
            models_dict["doc_embedding"] = embedding_model
            models_dict["kb_embedding"] = embedding_model
        if intent_model:
            models_dict["intent"] = intent_model

        from app.core.llm.provider_service import ProviderService

        svc = ProviderService()
        encrypted_key = svc.encrypt_api_key(api_key)

        await db.execute(
            text(
                "INSERT INTO llm_providers "
                "(id, provider_type, display_name, description, endpoint, "
                " api_key_encrypted, models, options, is_enabled, is_default, "
                " provider_status, created_at, updated_at) "
                "VALUES "
                "(:id, 'azure_openai', 'Platform Azure OpenAI (auto-seeded)', "
                " 'Auto-seeded from environment variables at startup', "
                " :endpoint, :api_key_encrypted, CAST(:models AS jsonb), "
                " CAST(:options AS jsonb), true, true, 'unchecked', NOW(), NOW())"
            ),
            {
                "id": str(uuid.uuid4()),
                "endpoint": endpoint,
                "api_key_encrypted": encrypted_key,
                "models": json.dumps(models_dict),
                "options": json.dumps({}),
            },
        )
        await db.commit()

        slot_count = len(models_dict)
        logger.info(
            "llm_provider_seeded_from_env",
            slot_count=slot_count,
            provider_type="azure_openai",
        )
        return True

    if db_session is not None:
        return await _do_seed(db_session)

    async with async_session_factory() as db:
        return await _do_seed(db)


async def seed_agent_templates() -> int:
    """
    TA-020: Insert the 4 standard seed templates into agent_templates table.

    Idempotent: each template is only inserted if no seed template with
    the same name already exists. Uses platform scope to bypass RLS.

    Returns the number of templates inserted (0 if already seeded).
    """
    from sqlalchemy import text

    from app.core.session import async_session_factory

    inserted = 0
    now = datetime.now(timezone.utc)

    async with async_session_factory() as db:
        # Use platform scope to bypass RLS on agent_templates
        await db.execute(text("SET LOCAL app.current_scope = 'platform'"))

        for template in _DB_SEED_TEMPLATES:
            # Idempotent check: skip if a seed template with this name already exists
            exists_result = await db.execute(
                text(
                    "SELECT 1 FROM agent_templates "
                    "WHERE name = :name AND status = 'seed' LIMIT 1"
                ),
                {"name": template["name"]},
            )
            if exists_result.fetchone() is not None:
                continue

            template_id = str(uuid.uuid4())
            await db.execute(
                text(
                    "INSERT INTO agent_templates "
                    "(id, name, description, category, system_prompt, "
                    " variable_definitions, guardrails, confidence_threshold, "
                    " version, status, created_at, updated_at) "
                    "VALUES (:id, :name, :description, :category, :system_prompt, "
                    "CAST(:variable_definitions AS jsonb), CAST(:guardrails AS jsonb), "
                    ":confidence_threshold, 1, 'seed', :now, :now)"
                ),
                {
                    "id": template_id,
                    "name": template["name"],
                    "description": template["description"],
                    "category": template["category"],
                    "system_prompt": template["system_prompt"],
                    "variable_definitions": json.dumps(
                        template["variable_definitions"]
                    ),
                    "guardrails": json.dumps(template["guardrails"]),
                    "confidence_threshold": template["confidence_threshold"],
                    "now": now,
                },
            )
            inserted += 1

        if inserted > 0:
            await db.commit()
            logger.info("agent_templates_seeded", count=inserted)
        else:
            logger.debug("agent_templates_already_seeded")

    return inserted
