"""SMF Praxis Homeschool vertical — registration module.

This package is the SMF Praxis homeschool compliance pack.
It depends on the open-core ``smf-praxis`` base and registers the
homeschool vertical's spec and eval cases with the base's
:mod:`hybridagent.verticals.registry` on import.

Installation::

    pip install praxis-agent            # open-core base (public, MIT)
    pip install praxis-homeschool       # SMF Praxis homeschool compliance pack

Activating the vertical lights up:

  * the ``homeschool`` vertical pack (parent-operated household education:
    persona + knowledge + route + compliance + assessment + portfolio +
    transcript + funding + collaboration + support + child-safe tutoring +
    household privacy modules),
  * the ``vertical.homeschool.*`` eval cases (route gate, attendance,
    child-safe tutor, private collaboration, transcript provenance).

Compliance mode: ``enforced``. READ + DRAFT autonomous; SEND + DESTRUCTIVE
held for human approval. The Homeschool persona carries parent-operated
household education governance across 13 states, distinct from the
institutional ``school_system`` vertical.
"""

from __future__ import annotations

from .registration import register

__version__ = "0.2.0"

__all__ = ["__version__", "register"]

register()