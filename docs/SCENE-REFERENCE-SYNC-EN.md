# Shared references within a scene

Fix dated November 21, 2026, following a Subject 4 conflict between cuts 1 and 2
in the same scene. Reproduced with synthetic data; the user's Windows archive
has not been accessed or modified.

Saving a Subject or Picture description updates drafts in other cuts of the same
open scene using the same UUID. This supersedes the earlier explicit-reload-only
rule. Reading an older stale draft also reconciles it when a cut in that same
scene holds the current library reference. An update originating only from
another scene is insufficient.

Requests, dialogue, exclusions, Picture slots, guidance and H3 linkage declarations
remain local. Synchronization does not add missing pictures, change roles or
sources, or relink files/proxies. Subjects using historical continuity and closed
scenes keep their own data. Missing confirmations are never granted automatically.
Saving makes no model calls.

Saved text, versions, snapshots, manual bases, results and existing job inputs
remain unchanged. Recompile the updated draft to obtain a new prompt. Other cuts
may return to draft state while retaining their previously confirmed version.

Before saving, the browser fetches the current revision and merges compatible
description updates with local edits. Different edits to the same field remain
a recoverable conflict. Genuine concurrent edits of the same cut stay protected.

The project library now opens without first saving the draft. Explicit reload
replaces the selected reference while preserving other local fields and unsaved
manual text. Before reloading a conflicting field, copy any local text to retain.
The library button appears in both Images and Subjects, in a dedicated toolbar
separate from creation controls that stays at the top while either section scrolls.

The Windows delivery is stable version 1.0.0. GitHub publication is separate;
earlier ZIPs remain unchanged. See `WINDOWS-CHECK-EN.txt`
inside the new ZIP for backup, testing and recovery.

[Italiano](SCENE-REFERENCE-SYNC-IT.md).
