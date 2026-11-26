# Object sheets: one description from multiple views

Available from release **1.1.0**. [Italiano](OBJECT-SHEET-IT.md).

A Picture can contain repeated depictions of the same object, such as a vehicle
seen from the front, rear, sides, above and in detail. **Object sheet · multiple
views** integrates the whole image into one English object description without
listing views, panels or page layout. Repeated depictions do not create multiple
vehicles or new Subjects.

## Usage

1. Upload the complete sheet as the Picture’s original file.
2. Choose the **Object** role and keep **From the image role**, or explicitly
   select the **Object / held item** category. The **Appearance** role also works
   when this category is selected explicitly.
3. Choose Compact, Medium or Full in the analysis options.
4. Select **Analysis type → Object sheet · multiple views**, then **Analyze**.
   A previously verified vision model must be selected. Changing a menu does
   not run inference; each Analyze requests a fresh call.
5. Review the proposal and select **Use this description** only when correct,
   then reconfirm it. Association with an Object Subject remains explicit.

Analysis uses the complete original image, reduced only for the vision request
to at most 1280 px per side, and ignores proxies. Original and H3 files stay
intact. No first-view crop, fixed view count or particular layout is required.

Instructions prioritize silhouette, proportions, colour, visible materials,
components and distinctive details. For vehicles these include visible bodywork,
doors, windows, roof, wheels, lights, grille and trim. Actual object logos and
lettering can be described; template captions and numbered labels are excluded.
No make, model, year, dimensions or hidden parts are invented.

Recognized view or layout commentary returns an error without applicable text,
rewriting or automatic retries. Physical parts such as rear lights, roof and
rear-view mirrors remain valid. Lexical checking does not guarantee fidelity
or completeness; users must still review small details and lettering.

Task `image_object_sheet` and cache `vision-object-sheet-v1-unified-1280` are
separate from ordinary analysis and character sheet v6. Discard, explicit apply
and protection against late results follow the existing workflow. Object sheets
share the limit of three recent analyses per cut/Picture. Saved descriptions,
prompts, snapshots, associations and files are preserved; no SQLite migration
is required.

Checks use synthetic images and simulated responses: no real inference on the
attached image and no H3 trial. Do not use this mode to automatically recognize
or associate different objects appearing in the same sheet.

[Description workflow](DESCRIPTION-WORKFLOW-EN.md) · [Character sheets](CHARACTER-SHEET-EN.md)
