# NORTHSTAR

The concrete product vision. Every architectural and design decision goes through this
lens. This file is the living reference; iterate here. It supersedes
`~/.mdx/projects/transport-matters-north-star.md` (2026-06-18), whose API-first lens
survives below.

## The product in one paragraph

Transport Matters is the operating surface for agent fleets. A human speaks an intent;
a tree of agents decomposes and executes it; the human watches, steers, and judges from
a canvas that renders the tree faithfully at every depth. TM owns the substrate that
makes this trustworthy: wire-level capture of every agent, controlled agent homes,
scoped context delivery, and evals grounded in evidence rather than vibes.

## Three goals

1. **World-class context management.** The capture substrate: wire and transcript
   streams, never collapsed; overlays; ephemeral homes. Context is a scarce, scoped,
   auditable resource.
2. **Built-in extensible workflow orchestration as a first-class citizen.** Mixture of
   Agents out of the box. Orchestration is the product, with a launcher attached, and
   not the other way round.
3. **Premium UX at two altitudes.** A total beginner with zero coding knowledge and a
   seasoned engineer use the same surfaces. The beginner sees artifacts and taps
   preferences; the engineer drills to the wire. Neither is condescended to.

## Positioning and price

Think $199 off the shelf, possibly $19.99/month. Aimed at people already paying $400
to $1000 a month for agent subscriptions. The pitch: the thing that makes your
expensive agent spend actually pay off. Seats scale the subscription; the $199 box
stays the single-player door; enterprise is the tier above.

## The architecture thesis: need-to-know, layers of inversion

No single agent can ever know everything. The system is designed so this falls out of
the structure rather than discipline.

**Content never flows down the tree; authority does.** Every edge carries references
("the utterance is at X", "the report is at Y") and spawn authority. Each node pulls
only what its role entitles it to, at the point of need. Contexts stay focused because
nothing is pushed into them.

The recursive cell, repeated at every layer:

- **Director**: route-only. Never sees content. Owns lifecycle and spawn authority.
- **Orchestrator**: pulls its scoped context, classifies, decomposes, spawns.
- **Specialists**: do the work. Any specialist can open a new cell beneath it.

Worked example ("build a 3D space invader game, no questions asked"):

```
Human (voice) ── utterance → captured + persisted (an addressable artifact, not a message)
└─ Director            route-only; spawns without reading
   └─ Orchestrator     pulls the utterance; classifies; decomposes
      └─ Creative Director            a domain lead, itself a new cell
         └─ Creative Orchestrator
            ├─ Research Scout         → report (another addressable artifact)
            ├─ Agent Resource agent   reads report → ensures homes/skills exist
            ├─ UX agent
            ├─ Audio agent
            ├─ 3D agent
            └─ Gameplay agent
```

The Agent Resource agent is the runtime-home/template machinery as a product surface:
curated homes and skills materialized per specialist, credentials rejected, writes
contained.

## The cost thesis

Focused contexts never bloat. The thesis is that this architecture saves tokens net
and extends the user's subscriptions: a router that knows nothing costs nothing, and a
specialist briefed by reference reads only its slice. Depth is cheaper than breadth
done badly.

Even so, two things are first-class out of the box:

- **Spend dials.** Visible per dispatch and per policy ("race the important slices,
  single-shot the mechanical ones"). Spend policy is an orchestration primitive.
- **Metrics and instrumentation.** Tokens, latency, tool calls, gate outcomes, per
  node and per subtree. Currently missing; must ship as a default surface, never an
  add-on.

## MoA and eval are one feature

Every fan-out is an experiment; every choice anyone makes about the results is a
label. Dispatching a task to three candidates is Mixture of Agents; picking the winner
(by human tap or judge agent) is eval data. Using the product is the harness.

TM makes the data trustworthy where nobody else can:

- **Controlled start states.** Ephemeral homes give candidates identical homes,
  skills, and briefs, varying only model or approach.
- **Wire-level evidence.** The proxy captures what each candidate actually did.
- **The judge is just another agent** in the tree, entitled to pull the candidates'
  artifacts and gate results, never their full contexts. Eval sophistication lives in
  judge briefs and entitlements, never in a separate eval system.
- **Compare is a canvas primitive.** Any two panes, including historical runs from the
  session store, drop into a versus surface. Fresh MoA races are the automatic case.
- **Labels persist and compound.** "For 3D tasks, family X wins 68% at 2.3x cost" is
  queryable state that routing orchestrators consult. Usage makes the router smarter.

## Team seats and social dynamics

A seat is an identity with entitlements, on the same substrate that scopes agents.
The need-to-know model generalizes to humans without a second system: a junior seat
sees artifacts and taps preferences, a lead seat drills to the wire, an ops seat
holds spend dials and merge gates.

Three layers, all in scope:

- **Human collaboration.** Presence on the canvas, multiple seats judging the same
  versus surface, subtree handoffs, shared history. Labels carry who judged, so
  taste is per person and aggregates per team.
- **Agent reputation.** Track records compound from the label store; routing becomes
  reputation-weighted per team: our 3D tasks go to X because X earns it here.
- **Sharing as a social object.** A run, a race, a replay is a shareable artifact
  beyond the team, and the growth loop. Replay/fork/share/eval sit parked in NOW.md
  as deferred, not dropped; this is their destination.

**Enterprise is the early capture.** TM sits on the wire by construction, and the
built-in reverse proxy is the security story an org can bolt onto: full audit of
every byte agents send, redaction and policy overlays, egress control, credential
hygiene (template credential rejection already ships). Every seat generates data
that matters beyond the seat: labels, runs, metrics, and reputation must be
accessible across teams and orgs, so everything the product records is attributed
and scoped seat → team → org from day one.

Open decision: the roster model. Either humans and agents are peers on one roster (a
seat is a seat; some seats are silicon), or seats are strictly human with agents
beneath them. The mixed roster is the bolder read of the thesis; undecided.

## The UX

The user navigates the supervision tree itself. Pane = agent. Drill-in = zoom into
that agent's cell. Canvas = the interior of a delegation.

- **Tri-tab pane.** Default is a beautifully rendered transcript; tabs switch to TUI
  mode or the HTTP wire within the same pane. These are the two captured streams plus
  the PTY bridge, unified as one pane anatomy.
- **Versus surface.** A dispatch node expands into N candidate panes under one shared
  comparison rail carrying the live race: tokens, latency, tool calls, gates.
- **Artifact-first.** The topmost thing in a candidate pane is the artifact (for a
  game: the running game), never the transcript.
- **Two altitudes, one substrate.** The beginner taps the result they like and never
  learns what a token is; the engineer flips to wire view and diffs tool-call
  timelines. The tap and the diff feed the same label store.

## Decision lens

Ship-gate questions for every feature:

1. **API-first.** Is it a director-callable API, or trapped in the UI? The control
   plane has four verbs: observe, launch, manage, prompt. The human UI and the
   director are twin clients of the same operations.
2. **Need-to-know.** Does any content leak down the tree, or does the edge carry only
   references and authority?
3. **Eval-ready.** Does the action produce a persistable label or metric?
4. **Two altitudes.** Does the surface read for the beginner (artifact, preference)
   and the engineer (evidence, wire) without forking the UX?
5. **Spend-aware.** Is the token cost visible and steerable where the action happens?
6. **Attributed.** Is the data this action produces stamped with seat, team, and org
   scope so it can travel across the org?

## Boundaries

TM owns: capture (wire + transcript), the control plane, agent homes and skill
materialization, the addressable artifact store and its entitlements, the eval and
label substrate scoped seat → team → org, metrics.

TM does not own: agent cognition, the vendors' CLIs, model quality. TM measures;
models compete.

## Stepping stones

Current work read in this light: the www/ separation (plan v5) makes canvas the
premium product shell the tree renders in; the launch-domain extraction makes launch a
service the director calls; ephemeral homes become the Agent Resource agent;
onboarding and embedded Postgres serve the beginner altitude. Voice intake remains a
later adapter; the ⌘K palette is client number one of the same control plane.
