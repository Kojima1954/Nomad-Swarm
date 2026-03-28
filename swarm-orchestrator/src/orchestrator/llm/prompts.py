"""Prompt templates for the LLM summarizer."""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are an Observer Agent in a Conversational Swarm Intelligence (CSI) network \
called N.O.M.A.D. Swarm.

Your role is to:
1. Faithfully distill the local group's deliberation without editorialising \
or adding opinions.
2. Integrate context from other Nodes' prior summaries (Swarm Signals) that \
have been injected into the conversation.
3. Identify emerging consensus, points of dissent, and open questions.
4. Be concise but complete.
5. Output ONLY valid JSON matching the provided schema — no prose before or \
after the JSON block.

You must NEVER invent positions, participants, or topics not present in the \
transcript.
"""

NATURAL_LANGUAGE_SUMMARY_PROMPT = """\
Below is the transcript of a local deliberation session and any inbound Swarm \
Signals from adjacent nodes.

--- TRANSCRIPT ---
{transcript}
--- END TRANSCRIPT ---

{swarm_signals_section}
{rag_context_section}

Write a concise natural-language summary (3-5 paragraphs) that:
- Describes what the group was discussing (topic).
- Lists the main positions or arguments raised.
- Identifies where consensus is forming.
- Notes significant dissent or minority views.
- Highlights unanswered questions.

Do NOT output JSON yet.
"""

STRUCTURE_SUMMARY_PROMPT = """\
You have produced the following natural-language summary of a deliberation:

--- SUMMARY ---
{natural_language_summary}
--- END SUMMARY ---

Now convert that summary into a JSON object that strictly matches this schema:

{schema}

Rules:
- "swarm:roundNumber" must be the integer {round_number}.
- "swarm:sourceNodeId" must be "{source_node_id}".
- "swarm:keyPositions" must be a non-empty list of strings.
- "swarm:emergingConsensus" must be a single string.
- "swarm:dissentingViews" may be an empty list.
- "swarm:openQuestions" may be an empty list.
- "swarm:parentSummaryIds" should list the IDs of any inbound Swarm Signals \
  used as context: {parent_summary_ids}.
- "swarm:participantCount" is {participant_count}.
- "swarm:messageCount" is {message_count}.
- "published" must be an ISO-8601 UTC datetime string.
- Output ONLY the JSON object — no markdown fences, no extra text.
"""

SWARM_SIGNALS_SECTION_TEMPLATE = """\
--- INBOUND SWARM SIGNALS (context from adjacent nodes) ---
{signals}
--- END SWARM SIGNALS ---
"""

RAG_CONTEXT_SECTION_TEMPLATE = """\
--- RELEVANT PRIOR CONTEXT (from vector store) ---
{rag_context}
--- END CONTEXT ---
"""

# The JSON schema shown to the LLM when asking it to structure the summary.
SUMMARY_JSON_SCHEMA = """\
{
  "@context": [...],
  "type": "swarm:SwarmSummary",
  "swarm:roundNumber": <integer, >= 1>,
  "swarm:topic": "<string describing the main deliberation topic>",
  "swarm:sourceNodeId": "<string>",
  "published": "<ISO-8601 UTC datetime>",
  "swarm:participantCount": <integer>,
  "swarm:messageCount": <integer>,
  "swarm:keyPositions": ["<string>", ...],
  "swarm:emergingConsensus": "<string>",
  "swarm:dissentingViews": ["<string>", ...],
  "swarm:openQuestions": ["<string>", ...],
  "swarm:parentSummaryIds": ["<string>", ...]
}
"""
