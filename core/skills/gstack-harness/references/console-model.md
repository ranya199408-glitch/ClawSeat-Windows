# Console Model

The v1 console is a CLI summary view.

It is intentionally read-only and does not replace seat decisions.

## Window layout

The default operator layout is:

- one project per iTerm window
- one monitor seat per tab inside that window
- tab order follows the project's canonical seat order as materialized into
  `monitor_engineers`
- only seats that are already running should appear as tabs
- stopped seats are opened on demand, then the project window is refreshed into
  canonical order

The frontstage-supervisor seat owns this layout operationally:

- it decides when to launch an additional seat
- after a new seat is launched, it is responsible for refreshing the project
  window so the new tab lands in canonical project order
- specialists should not ad hoc rearrange or fork the operator window layout

For projects using `window_mode = "tabs-1up"`, opening the project monitor
should attach the currently running monitor seats into tabs in the same window
rather than building a pane mosaic or starting every seat eagerly.

## Required sections

- seat status summary
- active loop owner
- current task chain position
- handoff health (`assigned / notified / consumed`)
- heartbeat state for the frontstage seat
- reminder candidates / blockers

## Evidence sources

- project docs
- machine-readable handoff receipts
- heartbeat receipt / manifest
- status checker output
- patrol supervisor output

## Non-goals

- no Web UI in v1
- no hidden state outside docs + receipts
- no planner/frontstage decision automation beyond the accepted boundaries
