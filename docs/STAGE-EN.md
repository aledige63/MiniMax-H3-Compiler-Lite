# Using Stage exports with Compiler

Available in Compiler **1.1.0** with output from **Stage 0.9.0** and later
versions retaining this format. [Italiano](STAGE-IT.md).
Stage: https://github.com/aledige63/Stage/releases/tag/v0.9.0.

1. Export the MP4 and **Prompt for MiniMax Compiler** (`_compiler.txt`) in Stage.
2. Define the final Subjects and their Pictures in Compiler. For a vehicle sheet
   containing multiple views, select **Object sheet · multiple views**.
3. Add the MP4 under Video, choose **Camera + Subject guide** for combined motion
   and enable the guide. Use **Camera-only guide** when Subject placement/motion
   should not be transferred.
4. Map each figure separately: for example `the red mannequin` to the person
   and `the white box` to the vehicle. Use the actual Subject/Video numbers in
   the cut; they do not need to be 1 and 2.
5. Paste only the `_compiler.txt` narrative into **Guide prompt · English**, up
   to 2,500 characters. Do not paste the sections from the Ref2VA example.
6. Confirm description, role, duration, mappings and H3 connection. Set a matching
   cut duration. Each active Video must be 2–15 s; all active Videos total at
   most 15 s.
7. Leave the Direction menu’s camera movement unspecified when the Video guides
   it. Write the narrative request, compile and review the proposal.
8. Connect Pictures and MP4 to the matching slots in the external MiniMax H3
   workflow and use Compiler’s complete six-section prompt.

Subject Pictures provide appearance and identity. The mapped guide proxy
provides placement, orientation, trajectory and timing. The Subject replaces
the proxy rather than adding its shape as a separate object. Figure descriptions,
colours or shapes must distinguish the mappings.
A third Picture can define an **Environment** Subject. It needs no Video mapping
when the guide does not contain a separate figure for that environment.

Guide text stays verbatim and appears once. Its declared opening governs mapped
Subjects; recognized second openings are rejected without repairs or automatic
retries. The model may ask a question when the request conflicts with the guide.
Review H3 fidelity and trajectories: prompts are not certified geometry constraints.

Compiler archives the MP4 for review but does not send it to the chat model,
run H3 or automatically import a combined MP4/TXT/JSON package. Uploads and menu
changes do not run inference. Saved versions stay intact; a fresh proposal
requires Compile/Recompile.
