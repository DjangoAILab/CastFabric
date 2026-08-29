# CastFabric UI design: Acoustic Weave

## Dawn revision

The first dark-room implementation established the correct product hierarchy,
but visual review showed that it felt too dim and that protocol labels appeared
mechanically attached to paths at some aspect ratios. The accepted revision is
**Acoustic Weave / Dawn**:

- use an ivory daylight field, soft botanical green structure and a warm coral
  signal accent;
- separate protocol labels from the animated geometry;
- animate particles along continuous Bezier waves so motion remains registered
  to the path at every viewport size;
- keep the landing surface focused on route health, targets and playback;
- move playback, network and extension preferences into a dedicated modal.

This revision retains the underlying information architecture and API contracts
while making the interface calmer, brighter and less dashboard-like.

## Intent

CastFabric is not a device-control dashboard and should not look like one. It is
a quiet routing layer that lets different casting protocols arrive at the same
speaker. The interface should make that invisible infrastructure legible in one
glance, then get out of the way.

The selected direction is **Acoustic Weave**: a dark, restrained listening room
with fine signal threads, warm type and one luminous output field. DLNA,
AirPlay and MiPlay appear as incoming strands rather than unrelated feature
cards. Their convergence is the memorable product gesture and will later become
the visual foundation of the public website.

Two alternatives were considered and rejected for the first iteration:

- A light editorial system would communicate openness well, but loses the
  atmospheric quality of audio playback and makes live status feel secondary.
- A hardware-style hi-fi console would feel precise, but overstates transport
  controls that CastFabric does not own and risks looking like an audio player.

## Information architecture

The page has three layers:

1. **Signal stage** — product identity, overall health, three ingress protocols,
   the active CastFabric fabric and the selected DLNA output.
2. **Daily operation** — output-target selection and current renderer/media
   state. These are the only persistent work surfaces.
3. **System detail** — collapsed configuration for behavior, ports and the
   optional Xiaomi extension. Advanced controls stay available without defining
   the product.

No unfinished pairing-code surface is introduced. Xiaomi account configuration
remains explicitly optional and visually subordinate.

## Visual system

- Near-black blue-green background with warm ivory foreground.
- Jade indicates a healthy local route; amber marks attention or a compatibility
  path; protocol colors are subtle identifiers rather than competing themes.
- Fine one-pixel rules, large negative space and low-opacity grain provide depth.
- Display typography uses a high-contrast editorial face where available;
  interface text uses a humanist sans with Chinese system fallbacks.
- Motion is slow and causal: strands travel toward the output, the central field
  breathes, and content reveals in sequence. `prefers-reduced-motion` disables
  non-essential movement.

## Interaction and responsive behavior

Output targets remain selectable with the existing API and apply action. The
now-playing panel refreshes from the existing renderer endpoint. The settings
surface uses a native disclosure element so keyboard and mobile behavior remain
predictable. Status text and protocol chips are updated from live diagnostics.

On narrow screens the signal topology becomes vertical, touch targets grow to at
least 44 px, and the two operational panels stack. The hero preserves the same
protocol-to-output story rather than becoming a decorative banner.

## Verification gates

- Existing setting, target selection, Xiaomi extension and update flows retain
  every required DOM hook.
- JavaScript parses independently and the Python suite stays green.
- Desktop and mobile screenshots are reviewed at 1440×1000 and 390×844.
- Reduced-motion and narrow-width layouts have no clipped controls or horizontal
  overflow.
- Home Server health, SSDP, AirPlay and MiPlay services remain unchanged after
  deployment.
