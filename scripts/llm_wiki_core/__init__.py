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
from .state import (
    OperationRecord,
    PageRecord,
    SourceRecord,
    StateInitPlan,
    StateValidationError,
    plan_state_init,
)
from .writer import (
    LockTimeout,
    SnapshotConflict,
    VaultLock,
    apply_state_init,
    classify_lock,
)

__all__ = [
    "ConfigureResult",
    "DiscoveryResult",
    "ResolvedRoot",
    "RootIssue",
    "PageRecord",
    "OperationRecord",
    "SourceRecord",
    "StateValidationError",
    "StateInitPlan",
    "plan_state_init",
    "LockTimeout",
    "SnapshotConflict",
    "VaultLock",
    "classify_lock",
    "apply_state_init",
    "configure_user_default",
    "default_obsidian_metadata_path",
    "discover_recent_vaults",
    "resolve_explicit_root",
    "resolve_root",
]
