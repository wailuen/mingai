"""v055 — Agent Studio: Seed built-in tools and platform skills

Revision ID: 055
Revises: 054
Create Date: 2026-03-22

Data migration (no schema changes). Inserts:
  - 6 built-in tools: web_search, document_ocr, calculator, data_formatter,
    file_reader, text_translator
  - 11 platform skills: Summarization, Entity Extraction, Sentiment Analysis,
    Document Q&A, Comparison, Citation Formatter, Translation, Risk Assessment,
    Market Research, Financial Summary, Company Intelligence
  - skill_tool_dependencies rows for the 3 tool-dependent skills

All tools: executor_type='builtin', scope='platform', is_active=true, created_by=NULL
All skills: scope='platform', status='published', mandatory=false

Uses ON CONFLICT DO NOTHING so re-running is idempotent.
"""
from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # Built-in tools
    # Tool names serve as stable identifiers for the BuiltinExecutor registry.
    # -------------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO tool_catalog (
            id, name, provider, mcp_endpoint, auth_type, capabilities,
            safety_classification, health_status,
            executor_type, rate_limit_rpm, credential_source,
            input_schema, output_schema, scope, is_active
        ) VALUES
        (
            '00000000-0000-0000-0001-000000000001',
            'web_search',
            'builtin',
            '',
            'none',
            '["web_search"]',
            'ReadOnly',
            'healthy',
            'builtin',
            60,
            'none',
            '{"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 5}}, "required": ["query"]}',
            '{"type": "object", "properties": {"results": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "url": {"type": "string"}, "snippet": {"type": "string"}}}}}}',
            'platform',
            true
        ),
        (
            '00000000-0000-0000-0001-000000000002',
            'document_ocr',
            'builtin',
            '',
            'none',
            '["document_ocr"]',
            'ReadOnly',
            'healthy',
            'builtin',
            30,
            'none',
            '{"type": "object", "properties": {"document_url": {"type": "string"}, "page_range": {"type": "string"}}, "required": ["document_url"]}',
            '{"type": "object", "properties": {"text": {"type": "string"}, "page_count": {"type": "integer"}}}',
            'platform',
            true
        ),
        (
            '00000000-0000-0000-0001-000000000003',
            'calculator',
            'builtin',
            '',
            'none',
            '["calculator"]',
            'ReadOnly',
            'healthy',
            'builtin',
            120,
            'none',
            '{"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}',
            '{"type": "object", "properties": {"result": {"type": "number"}, "expression_parsed": {"type": "string"}}}',
            'platform',
            true
        ),
        (
            '00000000-0000-0000-0001-000000000004',
            'data_formatter',
            'builtin',
            '',
            'none',
            '["data_formatter"]',
            'ReadOnly',
            'healthy',
            'builtin',
            120,
            'none',
            '{"type": "object", "properties": {"data": {}, "input_format": {"type": "string", "enum": ["json", "csv", "markdown_table"]}, "output_format": {"type": "string", "enum": ["json", "csv", "markdown_table"]}}, "required": ["data", "input_format", "output_format"]}',
            '{"type": "object", "properties": {"formatted": {"type": "string"}}}',
            'platform',
            true
        ),
        (
            '00000000-0000-0000-0001-000000000005',
            'file_reader',
            'builtin',
            '',
            'none',
            '["file_reader"]',
            'ReadOnly',
            'healthy',
            'builtin',
            60,
            'none',
            '{"type": "object", "properties": {"file_url": {"type": "string"}}, "required": ["file_url"]}',
            '{"type": "object", "properties": {"content": {"type": "string"}, "char_count": {"type": "integer"}}}',
            'platform',
            true
        ),
        (
            '00000000-0000-0000-0001-000000000006',
            'text_translator',
            'builtin',
            '',
            'none',
            '["text_translator"]',
            'ReadOnly',
            'healthy',
            'builtin',
            60,
            'none',
            '{"type": "object", "properties": {"text": {"type": "string"}, "target_language": {"type": "string"}, "source_language": {"type": "string"}}, "required": ["text", "target_language"]}',
            '{"type": "object", "properties": {"translated": {"type": "string"}, "detected_source_language": {"type": "string"}}}',
            'platform',
            true
        )
        ON CONFLICT (name) DO NOTHING
        """
    )

    # -------------------------------------------------------------------------
    # Platform skills
    # -------------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO skills (
            id, name, description, category, version, execution_pattern,
            invocation_mode, prompt_template, input_schema, output_schema,
            scope, status, mandatory, is_active, published_at
        ) VALUES
        (
            '00000000-0000-0000-0002-000000000001',
            'Summarization',
            'Condenses long text into a concise summary of a specified length.',
            'Content Processing',
            '1.0.0',
            'prompt',
            'llm_invoked',
            'Summarise the following text into exactly {{input.max_sentences}} sentences. Be concise and preserve the key points. Do not add commentary or opinions.

Text to summarise:
{{input.text}}

Provide only the summary, no preamble.',
            '{"type": "object", "properties": {"text": {"type": "string", "description": "Text to summarise"}, "max_sentences": {"type": "integer", "default": 3, "description": "Maximum number of sentences in the summary"}}, "required": ["text"]}',
            '{"type": "object", "properties": {"summary": {"type": "string"}}}',
            'platform',
            'published',
            false,
            true,
            NOW()
        ),
        (
            '00000000-0000-0000-0002-000000000002',
            'Entity Extraction',
            'Extracts named entities (persons, organisations, locations, dates) from text.',
            'Information Extraction',
            '1.0.0',
            'prompt',
            'llm_invoked',
            'Extract all named entities from the following text. Categorise each entity as one of: PERSON, ORGANISATION, LOCATION, DATE, or OTHER.

Return the result as a JSON array of objects with fields: entity, type, context (a short excerpt showing where the entity appears).

Text:
{{input.text}}

Return only valid JSON, no explanation.',
            '{"type": "object", "properties": {"text": {"type": "string", "description": "Text to extract entities from"}}, "required": ["text"]}',
            '{"type": "object", "properties": {"entities": {"type": "array", "items": {"type": "object", "properties": {"entity": {"type": "string"}, "type": {"type": "string"}, "context": {"type": "string"}}}}}}',
            'platform',
            'published',
            false,
            true,
            NOW()
        ),
        (
            '00000000-0000-0000-0002-000000000003',
            'Sentiment Analysis',
            'Classifies the sentiment of text as positive, negative, or neutral with a confidence score.',
            'Analysis',
            '1.0.0',
            'prompt',
            'llm_invoked',
            'Analyse the sentiment of the following text. Classify it as positive, negative, or neutral. Provide a confidence score from 0.0 to 1.0 and a brief explanation.

Return JSON with fields: sentiment (positive|negative|neutral), confidence (0.0-1.0), explanation.

Text:
{{input.text}}

Return only valid JSON.',
            '{"type": "object", "properties": {"text": {"type": "string", "description": "Text to analyse"}}, "required": ["text"]}',
            '{"type": "object", "properties": {"sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]}, "confidence": {"type": "number"}, "explanation": {"type": "string"}}}',
            'platform',
            'published',
            false,
            true,
            NOW()
        ),
        (
            '00000000-0000-0000-0002-000000000004',
            'Document Q&A',
            'Answers a question using only information from the provided context document.',
            'Knowledge',
            '1.0.0',
            'prompt',
            'llm_invoked',
            'Answer the following question using ONLY the information in the provided context. Do not use any external knowledge. If the answer is not in the context, say "I cannot find the answer in the provided document."

Question: {{input.question}}

Context:
{{input.context}}

Provide a direct answer followed by the specific passage from the context that supports your answer.',
            '{"type": "object", "properties": {"question": {"type": "string", "description": "The question to answer"}, "context": {"type": "string", "description": "The document context to use for answering"}}, "required": ["question", "context"]}',
            '{"type": "object", "properties": {"answer": {"type": "string"}, "supporting_passage": {"type": "string"}}}',
            'platform',
            'published',
            false,
            true,
            NOW()
        ),
        (
            '00000000-0000-0000-0002-000000000005',
            'Comparison',
            'Compares two items across specified dimensions and produces a structured analysis.',
            'Analysis',
            '1.0.0',
            'prompt',
            'llm_invoked',
            'Compare the following two items across the specified dimensions. For each dimension, identify which item is stronger and explain why. Conclude with an overall recommendation.

Item A: {{input.item_a}}
Item B: {{input.item_b}}
Dimensions to compare: {{input.dimensions}}

Return a structured analysis with a section per dimension and a final recommendation.',
            '{"type": "object", "properties": {"item_a": {"type": "string", "description": "First item to compare"}, "item_b": {"type": "string", "description": "Second item to compare"}, "dimensions": {"type": "string", "description": "Comma-separated list of dimensions to compare"}}, "required": ["item_a", "item_b", "dimensions"]}',
            '{"type": "object", "properties": {"comparison": {"type": "string"}, "recommendation": {"type": "string"}}}',
            'platform',
            'published',
            false,
            true,
            NOW()
        ),
        (
            '00000000-0000-0000-0002-000000000006',
            'Citation Formatter',
            'Formats citation data into standard academic or legal citation styles.',
            'Content Processing',
            '1.0.0',
            'prompt',
            'llm_invoked',
            'Format the following citation data in {{input.citation_style}} style. Ensure all required fields are present. If any required field is missing, note it clearly.

Citation data:
{{input.citation_data}}

Citation style: {{input.citation_style}} (e.g., APA 7th, MLA 9th, Chicago 17th, Vancouver, Harvard)

Return the formatted citation as a single string.',
            '{"type": "object", "properties": {"citation_data": {"type": "string", "description": "Raw citation information"}, "citation_style": {"type": "string", "description": "Target citation style (e.g., APA, MLA, Chicago)"}}, "required": ["citation_data", "citation_style"]}',
            '{"type": "object", "properties": {"formatted_citation": {"type": "string"}}}',
            'platform',
            'published',
            false,
            true,
            NOW()
        ),
        (
            '00000000-0000-0000-0002-000000000007',
            'Translation',
            'Translates text between languages with optional source language detection.',
            'Language',
            '1.0.0',
            'prompt',
            'llm_invoked',
            'Translate the following text from {{input.source_language}} to {{input.target_language}}. Preserve the original tone, formatting, and meaning. Do not add explanations or commentary.

Text to translate:
{{input.text}}

Provide only the translated text.',
            '{"type": "object", "properties": {"text": {"type": "string", "description": "Text to translate"}, "target_language": {"type": "string", "description": "Target language name or code"}, "source_language": {"type": "string", "default": "auto", "description": "Source language (auto for detection)"}}, "required": ["text", "target_language"]}',
            '{"type": "object", "properties": {"translated": {"type": "string"}, "detected_source": {"type": "string"}}}',
            'platform',
            'published',
            false,
            true,
            NOW()
        ),
        (
            '00000000-0000-0000-0002-000000000008',
            'Risk Assessment',
            'Identifies key risks in a scenario and rates their likelihood and impact.',
            'Analysis',
            '1.0.0',
            'prompt',
            'llm_invoked',
            'Identify and assess the key risks in the following scenario. For each risk, provide: risk name, description, likelihood (High/Medium/Low), impact (High/Medium/Low), and a brief mitigation recommendation.

Scenario:
{{input.scenario}}

Return a structured list of up to 10 key risks, ordered by combined likelihood × impact (highest first). Include an executive summary at the end.',
            '{"type": "object", "properties": {"scenario": {"type": "string", "description": "Description of the situation or plan to assess for risks"}}, "required": ["scenario"]}',
            '{"type": "object", "properties": {"risks": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}, "likelihood": {"type": "string"}, "impact": {"type": "string"}, "mitigation": {"type": "string"}}}}, "executive_summary": {"type": "string"}}}',
            'platform',
            'published',
            false,
            true,
            NOW()
        ),
        (
            '00000000-0000-0000-0002-000000000009',
            'Market Research',
            'Researches a market topic using web search and returns a structured market overview.',
            'Research',
            '1.0.0',
            'tool_composing',
            'llm_invoked',
            'You are a market research analyst. Research the following topic using the web search tool to gather current information. Synthesise the results into a structured market overview.

Topic: {{input.topic}}

Use the web_search tool to find:
1. Market size and growth rate
2. Key players and market share
3. Recent trends and developments
4. Key challenges and opportunities

Compile a structured report with sections for each area. Cite sources using [1], [2] etc. notation.',
            '{"type": "object", "properties": {"topic": {"type": "string", "description": "Market or industry to research"}}, "required": ["topic"]}',
            '{"type": "object", "properties": {"market_overview": {"type": "string"}, "sources": {"type": "array", "items": {"type": "string"}}}}',
            'platform',
            'published',
            false,
            true,
            NOW()
        ),
        (
            '00000000-0000-0000-0002-000000000010',
            'Financial Summary',
            'Calculates financial expressions and summarises financial data into a structured report.',
            'Finance',
            '1.0.0',
            'tool_composing',
            'llm_invoked',
            'You are a financial analyst. Use the calculator tool to compute the required figures, then summarise the financial data provided.

Expression to calculate: {{input.expression}}
Financial data to summarise:
{{input.financial_data}}

Steps:
1. Use the calculator tool to evaluate the expression
2. Interpret the result in context of the financial data
3. Produce a concise financial summary with: key metrics, calculated result, interpretation, and any notable trends or concerns.',
            '{"type": "object", "properties": {"expression": {"type": "string", "description": "Mathematical expression to evaluate (e.g., revenue - costs)"}, "financial_data": {"type": "string", "description": "Financial data to summarise"}}, "required": ["expression", "financial_data"]}',
            '{"type": "object", "properties": {"calculated_result": {"type": "number"}, "summary": {"type": "string"}, "key_metrics": {"type": "object"}}}',
            'platform',
            'published',
            false,
            true,
            NOW()
        ),
        (
            '00000000-0000-0000-0002-000000000011',
            'Company Intelligence',
            'Researches a company and returns a structured intelligence brief using web search.',
            'Research',
            '1.0.0',
            'tool_composing',
            'llm_invoked',
            'You are a business intelligence analyst. Research the specified company using web search and compile a structured intelligence brief.

Company: {{input.company_name}}

Use the web_search tool to research:
1. Company overview (founded, HQ, size, industry)
2. Products/services and value proposition
3. Key executives and leadership
4. Recent news and developments (last 6 months)
5. Financial highlights (if public)
6. Competitive positioning

Compile all findings into a structured intelligence brief. Cite sources using [1], [2] notation.',
            '{"type": "object", "properties": {"company_name": {"type": "string", "description": "Name of the company to research"}}, "required": ["company_name"]}',
            '{"type": "object", "properties": {"intelligence_brief": {"type": "string"}, "sources": {"type": "array", "items": {"type": "string"}}}}',
            'platform',
            'published',
            false,
            true,
            NOW()
        )
        ON CONFLICT (id) DO NOTHING
        """
    )

    # -------------------------------------------------------------------------
    # skill_tool_dependencies — link tool-dependent skills to their tools
    # Market Research → web_search
    # Financial Summary → calculator
    # Company Intelligence → web_search
    # -------------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO skill_tool_dependencies (skill_id, tool_id, required)
        SELECT
            '00000000-0000-0000-0002-000000000009',
            id,
            true
        FROM tool_catalog WHERE name = 'web_search'
        ON CONFLICT (skill_id, tool_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO skill_tool_dependencies (skill_id, tool_id, required)
        SELECT
            '00000000-0000-0000-0002-000000000010',
            id,
            true
        FROM tool_catalog WHERE name = 'calculator'
        ON CONFLICT (skill_id, tool_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO skill_tool_dependencies (skill_id, tool_id, required)
        SELECT
            '00000000-0000-0000-0002-000000000011',
            id,
            true
        FROM tool_catalog WHERE name = 'web_search'
        ON CONFLICT (skill_id, tool_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM skill_tool_dependencies WHERE skill_id IN ("
               "  '00000000-0000-0000-0002-000000000009',"
               "  '00000000-0000-0000-0002-000000000010',"
               "  '00000000-0000-0000-0002-000000000011'"
               ")")
    op.execute(
        "DELETE FROM skills WHERE id LIKE '00000000-0000-0000-0002-%'"
    )
    op.execute(
        "DELETE FROM tool_catalog WHERE id LIKE '00000000-0000-0000-0001-%'"
    )
