# Video guide bindings and a consistent opening

Available from release **1.1.0**. [Italiano](GUIDE-MAPPING-IT.md).

An external Stage/H3 experiment retained a white box beside the vehicle.
The original prompt had a mapping focused on motion and a generated sentence
that introduced a second opening with the character already present. The user’s
trial with a corrected prompt removed the box. This was not a comparison with
controlled seed/settings and does not establish universal H3 fidelity.

## New compilations

- Mapped Subject definitions separate sources: appearance and identity come from
  Pictures or confirmed continuity context; position, orientation and motion
  come from the declared Video figure. Proxies do not create new Subjects.
- Guide instructions replace each proxy in place from its first appearance,
  using the assigned Subject’s appearance. Proxy shapes are not extra scene
  objects. The application does not semantically analyze the video.
- The English guide text stays verbatim and appears once; the model does not
  rewrite it. Subject numbers and Video slots come from the cut’s mappings.
- An explicit `Opening:`, `Opening frame:` or `Opening composition:` line in
  a Subject-motion/combined guide is provided to the model as authoritative.
  No narrative parser infers presence or timestamps; proxy appearance is not
  transferred.
- The model must not add another opening for those Subjects in actions or the
  summary. When a guide covers the request, its event can be the entire plan.
  Additional actions, dialogues and shots remain explicit events. Essential
  conflicts require a question without a partial proposal.
- A lexical check rejects recognized second openings in generated text, even
  after the guide event. No sentence removal, rewriting or automatic retry
  occurs. Quoted visible lettering and dialogue remain authoritative data.
  The check does not certify every response’s semantic coherence.

Camera-only guides, Picture guides, inactive guides and Videos without an
opening line retain their paths. Motion bindings receive explicit source
instructions; second-opening checks apply only when a motion guide declares
its own opening.

## Preservation and checks

No SQLite migration is required. Rendering applies to new versions; reading,
copying and exporting earlier prompts uses their stored text. Snapshots, manual
versions, associations and files are not recomputed from the current state.
Opening a cut does not compile it automatically.

To obtain a new proposal, open the cut and select **Compile/Recompile**. Review
the result before H3 testing; the earlier version remains in history.
