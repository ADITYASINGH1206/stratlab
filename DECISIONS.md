# StratLab Architectural Decisions Log (ADR)

This document records architectural decisions made during development when choices are taken or the plan is silent.

---

## ADR-001: Initial Repository & CI/CD Structure
- **Date**: 2026-11-06
- **Context**: Project initialization for Track 2 Flip the Switch Hackathon.
- **Decision**: Public repository `ADITYASINGH1206/stratlab` created with `main` branch protection. All development proceeds strictly through phased feature branches and Pull Requests.
- **Consequences**: Direct pushes to `main` are prevented, establishing clean auditability and code review discipline.
