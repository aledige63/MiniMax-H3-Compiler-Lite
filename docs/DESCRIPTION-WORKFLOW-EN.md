# Picture description: simplified workflow

Stable version **1.0.0**, November 22, 2026. The user confirmed Discard and
character-sheet behavior from Windows after the Mac backend was aligned.

## What changes

Each Picture has one **Description** area. Its editable text is the current
description; manual editing remains available. A proposal is separate and never
replaces the current text automatically.

Next to **Analyze**, explicitly choose **Single image** or **Character sheet**.
The latter requires Identity/Appearance, the Character category and an uploaded
original file; a proxy cannot replace it. This interface choice does not change
the Picture's H3 role or associations. Category, detail level, attribute and view
are under **Analysis options**, initially closed. The current profile is summarized
beside the controls.

Every Analyze click explicitly requests a fresh analysis, bypassing cached
responses. There are no separate buttons tied to old results: the visible type
always controls the new request. While work for the Picture is queued or running,
Analyze and its type selector are disabled; description and manual text remain editable.

## One current proposal

At most one current proposal is shown per Picture. **Use this description**
applies it, clears the Picture's confirmation and moves the proposal to history.
Review and reconfirm the applied description. The cut's manual text stays intact.

**Discard** immediately removes the proposal from view and shows a message beside
the description while saving. If saving fails, the proposal returns with an
inline error. Discard moves the proposal to history without changing descriptions, media,
versions or snapshots. The decision is saved in the archive and survives restart.
It does not delete the result. Other unsaved local fields remain intact. A discarded
proposal can no longer be applied through the old API command.

Using or discarding a proposal never promotes an older one. Changes to the
reference, analysis type or profile leave the old proposal in history. Active
work remains visible and cancellable. Errors show their message without replacing
the current description or promoting an earlier result. Retry through Analyze.

## History and translation

**Proposal history** is initially closed. It retains earlier results, different
profiles, used/discarded proposals and historical receipts. Reading it never starts
analysis, changes fields or offers buttons to apply older results. **At most three
analyses are retained per cut/Picture, including the current proposal.** Image
analyses, character sheets, translations and failed attempts share this limit.
Older analyses are deleted from the record, rather than merely hidden, and can no
longer be consulted. Cleanup also runs at startup on existing archives. Retained
receipt text, warnings and metrics stay intact. Live work is never deleted and
returns within the limit on completion. Vision trials, ASR, files, saved descriptions,
prompts and snapshots are not deleted.

**Translate into English** appears only when the description language is not
English. Translation also produces a proposal to use or discard and requires
an available text model selected in Settings.

## Test on the PC

1. Follow `WINDOWS-CHECK-EN.txt` to create a verified backup and restored test copy.
2. Open a Picture with earlier analyses. Expect one current proposal and a closed
   history. Obsolete proposals should remain in history.
3. Edit the description and manual text without saving. Discard the current
   proposal: both edits must remain. Save and restart: it should stay in history,
   without an earlier proposal appearing in its place. It must disappear
   immediately even when the server takes time to respond.
4. Select Character sheet, check the Character category, and press Analyze.
   Verify the proposal's type and unified character description. This click calls
   the vision model; selecting a type or opening history does not.
5. Use this description: only the Picture description changes and needs
   reconfirmation. Check that the cut's manual text stays intact.
6. Try Single image and verify the corresponding type on the new proposal.
7. Switch the description language from English to Italian: Translate into
   English should appear. Switching back hides it without automatic translation.
8. Change detail level in options: the old proposal goes into history. Opening
   history/options must not save data or call the model.
9. Open a Picture with many older analyses: after startup only three should remain,
   including the current proposal. Earlier ones cannot be recovered through the
   app; first back up using the old installation as described in the Windows guide.

Late-result protection, local drafts, closed scenes and revision checks remain
active. No SQLite migration or rewriting of saved prompts occurs. Functional browser acceptance is confirmed. A fresh native installation of
the ZIP is not claimed; review each description against its reference.
