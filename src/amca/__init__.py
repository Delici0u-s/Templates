"""amca — directory-aware auto-executer.

Importing this package has no side effects: no config is read, no directory is
scanned, no prompt is shown. Everything that touches the filesystem happens
inside an explicitly constructed :class:`amca.core.context.AmcaContext`.

That is a deliberate constraint, not an accident. In the previous version,
importing ``impl.util.globals`` walked the directory tree and could block on an
interactive y/n prompt, which meant ``amca --help`` prompted you before it
printed help. Keep this module free of work.
"""

from __future__ import annotations

__version__ = "3.0.0"

__all__ = ["__version__"]
