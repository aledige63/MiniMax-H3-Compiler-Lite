# Character sheets: one unified character description

Stable version **1.0.0**, November 22, 2026. The user confirmed from the PC
that fresh analysis no longer mentions panels. Review every proposal for fidelity
and detail; this confirmation does not guarantee all images.

Analysis should directly describe one character: face, hair, visible build,
clothing, footwear, accessories and distinctive marks. Every image region
contributes, including small details and lower regions, but the output is one
coherent English paragraph at the selected Compact/Medium/Full detail level.
Mention each feature once; do not invent hidden details or arbitrarily resolve
contradictory evidence.

Instructions no longer enumerate possible layouts. They prioritize the person
and their clothing. Output should omit panel numbers, front/side views, poses,
borders, template captions and commentary about the sheet. “A logo on the back
of the jacket” and “a scar on the left forearm” remain valid: these locate features
on the person, rather than within the image. Preserve actual lettering on clothing.

Recognized panel or view commentary returns an error with no applicable text.
The current description stays intact. No sentences are removed, no response is
rewritten and no automatic retry occurs. This lexical check does not certify
semantic accuracy or completeness. Users must still review a valid proposal.

## How to test

1. In Windows version 1.0.0, open Images and the Picture containing the sheet.
2. Select Identity or Appearance, the Character category (including an Auto
   setting that resolves to Character) and the desired detail level. Upload
   the original image and select a previously verified vision model. Sheet
   analysis uses the original rather than a proxy.
3. In the new Description area, select **Analysis type → Character sheet** and
   press **Analyze**. Every click requests a fresh vision call, bypassing cache.
   The proposal must indicate **Character sheet**. Earlier per-receipt retry
   commands are replaced by the explicit selector and one Analyze button.
4. Verify that the proposal describes one person in one paragraph, integrates
   details from different parts of the image and never mentions its panels.
   Manually check fidelity, colors and lettering.
5. Use **Use this description** only when correct; edit if necessary,
   reconfirm and save. Analysis alone does not change fields.
6. If panel/view commentary is still detected, the existing description is
   preserved. Explicitly retry or enter a manual description.

Sheet cache version: `vision-character-sheet-v6-unified-1280`. Ordinary image
analysis retains its cache. Previously applied descriptions, manual corrections,
receipts with warnings, saved prompts and historical snapshots are not rewritten.

Local checks use six synthetic layouts and simulated responses: whole-image
input, one call, rejection of commentary, preservation of lettering and body
locations, separate cache and explicit application. A real Medium comparison and the user’s subsequent Windows browser confirmation
were recorded on November 22. A fresh native Windows installation of the ZIP was not repeated.

[Italiano](CHARACTER-SHEET-IT.md).

Complete workflow, Discard and history: [DESCRIPTION-WORKFLOW-EN.md](DESCRIPTION-WORKFLOW-EN.md).
