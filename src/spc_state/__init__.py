"""SPC Shared Semantic State Engine — pilot v0.1.

See PILOT_SPEC.md for the authoritative specification and AGENTS.md for the
architectural invariants every contributor must respect. The hard rule:

    No operator may directly mutate SemanticState. All changes must be
    proposed as a SemanticPatch and committed by the runtime.
"""

__version__ = "0.1.0"
