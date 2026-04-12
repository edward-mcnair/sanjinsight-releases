# Measurement Dashboard and Setup Flow — Review Prompt

You are reviewing a proposed product direction for a desktop scientific instrument control application (PyQt5). The application controls thermal imaging hardware — cameras, TEC controllers, bias sources, stages — and supports both repeatable validated measurements and exploratory manual measurements.

I want a serious product, UX, and architecture critique. Be critical, practical, and specific. Do not give generic praise. Pressure-test the proposal, identify weaknesses, and suggest improvements.

---

## Product context

This is a professional laboratory instrument. Users range from technicians running the same validated measurement hundreds of times to researchers exploring new materials and device configurations for the first time.

The application currently has:
- A sidebar navigation with hardware tabs (Camera, Stage, Temperature, Stimulus, etc.)
- A guided mode with step-by-step workflow phases
- A manual mode where the user configures everything themselves
- A "Scan Profile" concept (saved measurement configuration bundles)
- Material Profiles (thermal/optical properties of the material under test)
- Session management for saved measurements

We are now designing the **Measurement section** — the primary workflow for setting up and running a measurement.

---

## Core product direction

### Entry flow: File menu, not dashboard actions

We have decided that measurement setup should be initiated from the **File menu**, not from action buttons on a dashboard.

Two primary menu entries:

- **New Scan...** — Opens a setup dialog asking:
  1. What camera are we using? (pre-filled if only one is connected)
  2. What material are you working with?
  3. What are you trying to accomplish? (Measurement Goal)
  4. Proceed into the capture workflow with that context

- **New Scan from Profile...** — Opens a Scan Profile picker dialog, validates hardware readiness, and either launches or shows what is missing.

The ellipsis in both menu items signals "a dialog will open."

This pattern gives us:
- Discoverable, standard entry points
- Modal dialogs that ask only the questions relevant to each path
- Keyboard shortcuts for power users (Cmd+N, Cmd+Shift+N)
- Clean separation between "launching a measurement" and "viewing status"

### Dashboard role: context and status, not action launcher

With entry actions moved to the File menu, the Measurement Dashboard becomes an **information surface**, not an action launcher.

The dashboard shows:
- **Current Context** — selected camera, material, measurement goal, selected scan profile, bias/stimulus, TEC devices
- **Device Status** — hardware connectivity and readiness
- **Recent and Useful** — recent scan profiles, recent measurements
- **Recommended Next Step** — if the system has enough context, a suggested action (e.g., "ready to run," "missing hardware")

Post-run actions also live in the File menu:
- **Save as Scan Profile...**
- Results actions appear on the results surface, not the dashboard

---

## Important conceptual decisions to evaluate

### 1. Profile vs. Recipe

We audited the codebase and found:
- `MaterialProfile` is a real declarative profile (thermal/optical properties)
- The current `Recipe` class is actually a saved configuration bundle — it contains no procedural fields (no steps, no sequencing, no branching, no conditional logic)
- The UI had previously renamed Recipe to "Scan Profile"
- Newer code accidentally reintroduced "Recipe" terminology

Working rule:
- **Profiles** define *how to measure* (parameters, settings, hardware configuration)
- True **Recipes** would define *how to run* (authored procedural steps), but that concept is not meaningfully implemented
- Therefore, the user-facing concept should be **Scan Profile**, not Recipe
- If true procedural recipes are needed later, they get their own concept and their own UI

A Scan Profile contains:
- Camera selection
- Material reference
- Measurement goal
- Voltage / bias settings
- TEC settings
- Acquisition parameters
- Analysis defaults
- Approval state
- Intended use notes

Please evaluate whether this terminology decision is correct, and whether the Profile/Recipe boundary is drawn in the right place.

### 2. Measurement Goal as a separate concept

We believe these are four distinct setup questions:
1. What camera are we using?
2. What material are you working with?
3. What are you trying to accomplish? (Measurement Goal)
4. How would you like to proceed? (addressed by the two File menu paths)

We do **not** want "Measurement Goal" and "Scan Profile" to collapse into the same thing. A Scan Profile may encode a goal, but the goal should exist as an independent selection that:
- Filters which scan profiles are relevant
- Constrains downstream parameter choices
- Provides context for recommendations and quality scoring

However, we have not yet enumerated the specific goals. Likely candidates: Thermal Resistance, Transient Response, Steady-State Imaging, Die Attach Quality, Hotspot Detection.

Please evaluate:
- Is this separation correct?
- Does it add clarity or redundancy?
- What happens when a selected goal and a selected scan profile disagree?

### 3. Saved measurement reuse

We want users to be able to:
- Create a new scan profile from scratch (via manual configuration)
- Save a successful measurement as a new scan profile (via File menu after a run)
- Update an existing scan profile when settings have been refined

A selected scan profile may answer many setup questions automatically. But we do not want every user forced to start with a scan profile — "New Scan..." exists specifically for users who don't have or don't want a profile.

Please evaluate whether this balance is right.

---

## Proposed dashboard shape (revised)

The dashboard is now an **information and status surface**, not an action launcher.

### A. Current Context
Show what is currently selected and ready:
- Camera
- Material
- Measurement Goal
- Selected Scan Profile (if any)
- Bias / Stimulus
- TEC Devices / Hardware Readiness

### B. Device Status
Show hardware connectivity and readiness:
- Camera connection
- TEC controllers
- Bias source
- Other measurement devices

### C. Recent and Useful
Fast access to:
- Recent Scan Profiles
- Recent Measurements

### D. Recommended Next Step
If the system has enough context, show a suggested action:
- Ready to run selected scan profile
- Review settings before run
- Missing hardware or missing required context

The dashboard should be **state-adaptive**:
- **Cold start** (no context): show device status and "get started" guidance
- **Profile selected**: show profile summary + readiness
- **Ready to run**: emphasize Run action
- **Post-run**: this state is handled by the results surface, not the dashboard

---

## Additional UX decisions to evaluate

### Tab consistency

We are standardizing tab design across the application:
- No leading bullets or dots in tab labels
- Consistent typography and active/inactive treatment
- Explicit distinction between tabs (content switching) and segmented controls (mode switching)
- Status indicators (attention badges) overlay the tab icon position, not a separate location

Please evaluate whether this is the right standard.

### Device naming

Selectors and tab labels should identify the real device:
- "TEC-1089" or "Meerstetter TEC-1089", not "TEC 1"
- "ATEC-302", not "TEC 2"

Principle: labels should identify the real device, not arbitrary numbered slots, unless slot identity is genuinely what the user needs.

Please evaluate this principle.

---

## What I want from you

Review this proposal across three levels:

### 1. Product logic
- Does the File menu entry pattern make sense for this type of application?
- Is the dashboard's reduced role (information, not actions) the right call?
- Are the concepts separated cleanly enough?
- Is the Profile/Recipe boundary correct?
- Is the Measurement Goal separation adding value or creating redundancy?

### 2. UX / information architecture
- Will users understand how to begin a measurement?
- Will experienced users move fast?
- Will new users feel guided without being trapped?
- Is the mental model clean?
- What parts are likely to confuse users?
- Does the File menu pattern work for a scientific instrument app, or do these users expect a different interaction model?

### 3. Architecture / implementation implications
- Will this scale cleanly?
- What domain concepts need to stay separate?
- What should be centralized now before the UI hardens?
- What fragile coupling or terminology drift should be prevented?
- What state management is implied but not yet built?

---

## Organize your response exactly as follows

1. **Overall Verdict** — Choose one: Strong direction / Promising but needs refinement / Risky and needs restructuring
2. **What Is Strong** — Identify what is working
3. **Primary Weaknesses** — The most important weaknesses or risks
4. **Conceptual Problems** — Blurred concepts, bad assumptions, or terminology issues
5. **UX Risks** — Confusion points, overload risks, or workflow problems
6. **Architecture Risks** — Structural or implementation concerns to address now
7. **Specific Recommendations** — Practical, priority-ordered recommendations
8. **Things That Should Be Decided Before Implementation** — Decisions to lock down first
9. **Anything Missing** — Important elements this proposal has not accounted for

---

## Important instructions

Do not just agree with the proposal. Stress-test it.

Be skeptical of:
- Concepts that sound good but blur under use
- Entry flows that work for one type of user but fail another
- Labels that are internally logical but not user-clear
- Dashboards that risk becoming cluttered status walls even without action buttons
- File menu patterns that might feel buried or undiscoverable for some user populations
- Features trying to solve both novice and expert use cases with one pattern

If something is directionally right but still weak, say so clearly.

I am not asking for code. I am asking for a deep product and UX critique of this proposed direction.
