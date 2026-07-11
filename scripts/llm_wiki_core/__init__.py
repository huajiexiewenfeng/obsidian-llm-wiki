from .root import (
    ConfigureResult,
    DiscoveryResult,
    ResolvedRoot,
    RootIssue,
    configure_user_default,
    default_obsidian_metadata_path,
    discover_recent_vaults,
    resolve_explicit_root,
    resolve_root,
)
from .state import OperationRecord, PageRecord, SourceRecord, StateValidationError
from .writer import LockTimeout, SnapshotConflict, VaultLock, classify_lock

__all__ = [
    "ConfigureResult",
    "DiscoveryResult",
    "ResolvedRoot",
    "RootIssue",
    "PageRecord",
    "OperationRecord",
    "SourceRecord",
    "StateValidationError",
    "LockTimeout",
    "SnapshotConflict",
    "VaultLock",
    "classify_lock",
    "configure_user_default",
    "default_obsidian_metadata_path",
    "discover_recent_vaults",
    "resolve_explicit_root",
    "resolve_root",
]
