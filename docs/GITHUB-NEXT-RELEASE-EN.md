# GitHub register — version 1.0.0

Numbered stable release, November 22, 2026. Italiano: [GITHUB-NEXT-RELEASE-IT.md](GITHUB-NEXT-RELEASE-IT.md).

After the Mac backend restart, the user confirmed from the Windows PC that
Discard works and fresh character-sheet analysis no longer mentions panels.
The user then authorized consolidation without a preview suffix on the current
version. Earlier versions remain unchanged.

## Changes to integrate

- Shared descriptions by UUID between compatible drafts in the same open scene.
- Library access with unsaved edits, selective reload and a sticky toolbar.
- Character sheet v6 with unified description, view checks and separate cache.
- One Analyze action, explicit type selector, one proposal and closed history.
- Persistent discard through dismiss, immediate removal and rollback on failure.
- Three analyses per cut/Picture, including translations and failed attempts;
  previously authorized deletion of older entries while protecting files/text.
- IT/EN guides and [RELEASE-1.0.0-EN.md](RELEASE-1.0.0-EN.md).

## Validation and delivery

421 Python tests ran (one skipped on Mac); 111 JavaScript tests passed.
Discard was verified on the real backend, over LAN and after a second restart:
cut data unchanged except revision, versions/snapshots preserved and media hashes
unchanged. User acceptance concerns a Windows browser connected to the Mac
backend; no fresh native installation of the numbered ZIP is claimed.

The publishable recipe is standalone, with updated allowlist/runtime reference
and no dependence on old ZIPs or private history. The stable Windows package
preserves the accepted runtime and previously tested launchers/dependencies.
Its manifest records hashes/provenance; validation reports accompany delivery.
MIT, copyright aledige, operating documentation in both languages.

## Publication remains separate

**No GitHub push or publication performed.** Local consolidation and Drive
handoff do not authorize publication. Public baseline verified read-only:
`aledige63/MiniMax-H3-Compiler-Lite`, main,
`5e7d59cd02fe71666063a401144821f7ca780036`. Reviewed patch, sources and manifests
are prepared for a later publication instruction.

Exclude private history, local handoff, user data, media, keys, models,
inference reports and external materials. Preserve all previous ZIPs/tags.
Stage remains future work. Linux excluded; no new Mac installer requested.
