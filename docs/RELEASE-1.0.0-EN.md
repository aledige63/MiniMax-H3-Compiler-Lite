# MiniMax H3 Compiler Lite 1.0.0

Stable release, November 22, 2026. Italiano: [RELEASE-1.0.0-IT.md](RELEASE-1.0.0-IT.md).
MIT — Copyright (c) 2026 aledige.

## Consolidated behavior

- One Description per Picture, an explicit Single image / Character sheet
  selector and one Analyze action. Every click requests fresh work; changing
  the selector or opening options/history never calls the model.
- Discard immediately removes the proposal and persists without changing the
  description, other cut fields or manual text. A failed server command restores
  the proposal with its error. Older proposals are never promoted automatically.
- At most three analyses per cut/Picture, including the current one. Image
  analyses, sheets, translations and failed attempts share this limit. Older
  entries are deleted at first startup as well; live work remains protected.
- Character sheet v6 describes one person using the whole image, without panel
  commentary. Application is explicit and manual edits remain authoritative.
  Invalid proposals are rejected without rewriting or automatic retries.
- Shared Picture/Subject descriptions synchronize by UUID between compatible
  drafts in the same open scene. Local fields, files/proxies, exclusions,
  saved prompts, versions and snapshots remain protected.
- The library opens with unsaved edits, offers selective reload and has a
  dedicated sticky toolbar in Images and Subjects, separate from creation.

## Acceptance and scope

On November 22 the user confirmed from the Windows PC that Discard works and
fresh character-sheet analysis no longer mentions panels after the Mac backend
was aligned. Persistence across two controlled restarts, idempotency, preservation
of text/versions/snapshots and media file hashes were also verified.

Functional acceptance concerns a Windows browser connected to the Mac backend.
The new Windows ZIP preserves launchers and pinned dependencies from the tested
base; a fresh native Windows installation of this ZIP is not claimed.
Review descriptions against your own reference. The numbered delivery targets
Windows x64. The existing Mac service stays active; no new Mac installer is
delivered. Linux is excluded.

## Updating

Create a verified backup from the old installation before first startup: the
three-entry limit deletes older analyses. Saved descriptions, originals, prompts,
versions and snapshots are not deleted. Extract into a new folder, keep the same
selected data archive and restart the backend as well as the browser. See
`UPDATE-EN.txt` and `WINDOWS-CHECK-EN.txt` inside the package.

Earlier ZIPs, checksums and tags remain unchanged. Versioning starts at 1.0.0;
subsequent fixes use 1.0.x and compatible features 1.x.0. The current release
has no preview suffix. [GITHUB-NEXT-RELEASE-EN.md](GITHUB-NEXT-RELEASE-EN.md)
tracks GitHub preparation; publication requires a separate instruction.
