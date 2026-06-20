# Channels

Transport Matters has two runnable channels.

| Channel | Purpose | Launch shape |
| --- | --- | --- |
| `stable` | Daily driver. This is the default for `transport-matters desktop`. | Installed tool, canonical home, no badge. |
| `preview` | In development dogfood build from the working tree. | `just channel-restart preview`, isolated state, amber `PREVIEW` badge. |

## Run preview beside stable

```bash
just channel-restart preview
```

The recipe builds the web and desktop bundles from the working tree, runs
`transport-matters channel ensure-db preview`, then launches
`transport-matters desktop --channel preview`.

The backend still requires an explicit Postgres server URL through
`TRANSPORT_MATTERS_DATABASE_URL` or settings. The channel selects the database
name on that server.

## Running and managing instances

`transport-matters desktop` launches detached by default, waits until the
backend accepts connections, opens Electron, then returns. Pass `--foreground`
to keep the backend attached and stream logs in the terminal.

Use `transport-matters channel list` to see channel ports and the PID for each
live detached backend. Use `transport-matters tail [channel]` to read that
channel's `desktop.log`; add `-f` to follow or `-n <lines>` to choose the
history window. Stop an instance with `kill <PID>`. There is no separate stop
command.

Accepted edges:

- Instances launched with `--storage-dir` sit outside the channel scoped
  `list` and `tail` view.
- Instances launched with `TRANSPORT_MATTERS_HOME` set also sit outside that
  view. With `TRANSPORT_MATTERS_HOME`, all channels collapse to one shared
  runtime record path.
- PID reuse can briefly make a stale record look live.

## Isolation

One channel id fans out to every local state boundary.

| Boundary | `stable` | `preview` |
| --- | --- | --- |
| Home | `~/.transport-matters` | `~/.transport-matters-preview` |
| Database | `transport_matters` | `transport_matters_preview` |
| Proxy port | `8787` | `8797` |
| Web port | `8788` | `8798` |
| Electron name | `Transport Matters` | `Transport Matters Preview` |
| Electron app id | `io.helioy.transport-matters` | `io.helioy.transport-matters.preview` |
| Electron user data | default | `~/.transport-matters-preview/electron-user-data` |
| Badge | none | amber `PREVIEW` |

Stable and preview can run at the same time because their homes, databases,
ports, Electron identity, user data, and dock identity are separate.

## Commands

```bash
transport-matters channel list
transport-matters channel ensure-db stable
transport-matters channel ensure-db preview
```

`channel list` prints the committed channel table. `ensure-db` creates the
channel database if needed and applies migrations.

## Promote preview to stable

```bash
transport-matters channel promote preview stable
```

Promotion is code only. It runs the local install path for the current repo and
prints the stable launch command. It never moves preview session data, never
copies `~/.transport-matters-preview`, and never rewrites
`transport_matters_preview` into `transport_matters`.
