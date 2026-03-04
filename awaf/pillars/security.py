from __future__ import annotations

from awaf.pillars.base import PillarAgent

_WHAT = """\
- Are trust tiers enforced at the tool or MCP layer in code, not via prompt instructions?
- Are credentials stored outside agent context (env vars, secrets manager, vault)?
- Is the blast radius of a compromised agent explicitly bounded?
- Is a kill switch or emergency stop implemented in code?
- Is external input sanitized before entering agent context?
- Is least-privilege applied to tool and API access?

NOTE: "Don't do X" in a system prompt is merely a suggestion — not a security control.
Only code-level enforcement counts as verified for this pillar.
"""

_EVIDENCE = """\
IAM policies, secrets manager configs (AWS Secrets Manager, HashiCorp Vault, Azure Key Vault),
network configs (VPC, security groups, NACLs), RBAC definitions, code-level trust tier
implementation, Snyk or security scanner output, penetration test results, AWS Security Hub
findings.
"""


class SecurityAgent(PillarAgent):
    """Tier 1: Security."""

    @property
    def name(self) -> str:
        return "Security"

    @property
    def system_prompt(self) -> str:
        return self._build_system_prompt("Security", _WHAT, _EVIDENCE)
