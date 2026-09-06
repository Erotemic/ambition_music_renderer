"""Optional render/effect backends for ambition_music_renderer.

The core renderer must remain usable without these modules' runtime tools.  Each
backend is imported lazily only when YAML or CLI settings request it.
"""
