"""Composable business-agent facade for the independent Research Workflow."""

from __future__ import annotations

from app.research.models import ResearchProfile


class KnowledgeResearchAgent:
    """Delegate to a staged workflow without inheriting or overriding Manus."""

    def __init__(self, workflow):
        self.workflow = workflow

    async def run_research(self, profile: ResearchProfile):
        return await self.workflow.run(profile)

