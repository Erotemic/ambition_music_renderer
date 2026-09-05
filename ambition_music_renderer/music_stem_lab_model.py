"""Pure state model for the standalone Stem Lab.

Qt is intentionally kept out of this module.  Loading versions, choosing a
reference, and routing stems remain testable domain operations so the UI can grow
into a richer read-only/editor frontend without making widgets the source of
truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .music_audition import StemAsset, StemVersion, discover_stem_assets, preferred_reference


@dataclass
class StemRoute:
    enabled: bool
    version_key: str | None


@dataclass
class StemLabSession:
    versions: dict[str, StemVersion]
    current_cue: str | None = None
    loaded_keys: list[str] = field(default_factory=list)
    reference_key: str | None = None
    assets: dict[str, dict[str, StemAsset]] = field(default_factory=dict)
    routes: dict[str, StemRoute] = field(default_factory=dict)

    @classmethod
    def from_versions(cls, versions: Iterable[StemVersion]) -> "StemLabSession":
        return cls({version.key: version for version in versions})

    def replace_versions(self, versions: Iterable[StemVersion]) -> None:
        previous_loaded = list(self.loaded_keys)
        previous_reference = self.reference_key
        self.versions = {version.key: version for version in versions}
        self.assets = {key: value for key, value in self.assets.items() if key in self.versions}
        self.loaded_keys = [
            key
            for key in previous_loaded
            if key in self.versions and self.versions[key].cue_id == self.current_cue
        ]
        self.reference_key = previous_reference if previous_reference in self.loaded_keys else None
        self._sync_routes()

    def add_versions(self, versions: Iterable[StemVersion]) -> None:
        for version in versions:
            self.versions[version.key] = version

    def versions_for_cue(self, cue_id: str | None = None) -> list[StemVersion]:
        cue = cue_id or self.current_cue
        return sorted(
            [version for version in self.versions.values() if version.cue_id == cue],
            key=lambda version: (-version.generated_at, version.label.lower()),
        )

    def select_cue(self, cue_id: str | None) -> None:
        if cue_id == self.current_cue:
            self._sync_routes()
            return
        self.current_cue = cue_id
        self.loaded_keys.clear()
        self.assets.clear()
        self.routes.clear()
        self.reference_key = None
        versions = self.versions_for_cue(cue_id)
        reference = preferred_reference(versions)
        newest = versions[0] if versions else None
        if reference is not None:
            self.load(reference.key)
            self.reference_key = reference.key
        if newest is not None and newest.key not in self.loaded_keys:
            self.load(newest.key)
        self._sync_routes()
        if newest is not None:
            # The newest/current variant is the natural initial audition source.
            # Reference remains the fallback for groups the current variant lacks.
            self.route_all(newest.key)

    def assets_for(self, key: str) -> dict[str, StemAsset]:
        if key not in self.assets:
            version = self.versions.get(key)
            self.assets[key] = discover_stem_assets(version) if version is not None else {}
        return self.assets[key]

    def load(self, key: str) -> bool:
        version = self.versions.get(key)
        if version is None or version.cue_id != self.current_cue:
            return False
        self.assets_for(key)
        if key not in self.loaded_keys:
            self.loaded_keys.append(key)
            self.loaded_keys.sort(
                key=lambda item: (-self.versions[item].generated_at, self.versions[item].label.lower())
            )
        self._sync_routes()
        return True

    def unload(self, key: str) -> bool:
        if key not in self.loaded_keys:
            return False
        self.loaded_keys.remove(key)
        if self.reference_key == key:
            self.reference_key = None
        self._sync_routes()
        return True

    def set_reference(self, key: str | None) -> None:
        if key is not None and key not in self.loaded_keys:
            raise ValueError("reference must be one of the loaded versions")
        self.reference_key = key

    @property
    def groups(self) -> tuple[str, ...]:
        return tuple(sorted({group for key in self.loaded_keys for group in self.assets_for(key)}))

    def candidates_for_group(self, group: str) -> list[str]:
        return [key for key in self.loaded_keys if group in self.assets_for(key)]

    def routed_source_for_group(self, group: str) -> str | None:
        """Return the version currently designated as the main source for a stem."""
        route = self.routes.get(group)
        if route is None or route.version_key not in self.candidates_for_group(group):
            return None
        return route.version_key

    def comparison_candidates_for_group(self, group: str) -> list[str]:
        """Loaded versions for a stem other than its currently routed source."""
        main = self.routed_source_for_group(group)
        return [key for key in self.candidates_for_group(group) if key != main]

    def _default_source_for_group(self, group: str) -> str | None:
        candidates = self.candidates_for_group(group)
        if not candidates:
            return None
        return max(candidates, key=lambda key: self.versions[key].generated_at)

    def _sync_routes(self) -> None:
        active = set(self.groups)
        for group in list(self.routes):
            if group not in active:
                del self.routes[group]
        for group in active:
            route = self.routes.get(group)
            candidates = self.candidates_for_group(group)
            if route is None:
                self.routes[group] = StemRoute(True, self._default_source_for_group(group))
            elif route.version_key not in candidates:
                route.version_key = self._default_source_for_group(group)

    def set_route_enabled(self, group: str, enabled: bool) -> None:
        if group not in self.routes:
            self._sync_routes()
        if group in self.routes:
            self.routes[group].enabled = bool(enabled)

    def set_all_routes_enabled(self, enabled: bool) -> None:
        """Enable or disable every currently routable stem."""
        self._sync_routes()
        value = bool(enabled)
        for route in self.routes.values():
            route.enabled = value

    def set_route_source(self, group: str, key: str) -> None:
        if key not in self.candidates_for_group(group):
            raise ValueError(f"version {key!r} has no {group!r} stem")
        if group not in self.routes:
            self._sync_routes()
        self.routes[group].version_key = key

    def route_all(self, key: str) -> None:
        if key not in self.loaded_keys:
            return
        for group in self.groups:
            if group in self.assets_for(key):
                self.routes[group].version_key = key

    def route_reference(self) -> bool:
        if self.reference_key is None:
            return False
        self.route_all(self.reference_key)
        return True

    def selections(self) -> dict[str, tuple[StemVersion, StemAsset]]:
        selected: dict[str, tuple[StemVersion, StemAsset]] = {}
        for group, route in self.routes.items():
            if not route.enabled or route.version_key is None:
                continue
            version = self.versions.get(route.version_key)
            asset = self.assets_for(route.version_key).get(group)
            if version is not None and asset is not None:
                selected[group] = (version, asset)
        return selected
