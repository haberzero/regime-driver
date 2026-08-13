// regime-dialog-control plugin: expose the regime-driver CLI contract as native opencode tools.
// The Dialog Control (opencode `dialog-control` agent) calls these instead of raw bash for reliability.
// Each tool shells out to the regime CLI (conda env) and returns its --json output.
import { tool } from "@opencode-ai/plugin"

// Invoke the regime CLI entry point DIRECTLY (no `conda run` wrapper): conda run's
// subprocess output capture is lost when spawned from the tool process, which makes
// the tool return empty. The `regime` binary (pip-installed) is on PATH.
//
// Portability (WORK_PLAN6 III + deployment UX): the `regime` binary is resolved at
// load time as REGIME_BIN env -> `regime` on PATH. The worker base URL is
// REGIME_WORKER_BASE env -> localhost:4097, so a host-installed dialog control can
// drive a remote / docker worker by setting the env var. No container-specific
// fallback path: this plugin is distributed via pip and runs on the host, where a
// pip-installed regime-driver always provides `regime` on PATH.
const REGIME = [process.env.REGIME_BIN || "regime"]
const BASE = process.env.REGIME_WORKER_BASE || "http://127.0.0.1:4097"

// Run a regime command and return trimmed output (JSON). Throws on non-zero exit.
// Each arg is passed as its own shell word via Bun's template-array escaping, so
// user-controlled context/messages cannot inject shell metacharacters.
// Bun's `$` proc: `await proc.text()` returns the captured stdout string.
async function run($, args) {
  const proc = await $`${[...REGIME, ...args]}`.quiet()
  if (proc.exitCode !== 0) {
    const err = await proc.text().catch(() => "")
    throw new Error(`regime failed (${proc.exitCode}): ${String(err).trim()}`)
  }
  return String(await proc.text()).trim()
}

// Null-safe arg accessor: an all-optional tool may be invoked with null args,
// so execute() must never deref args.* directly.
function A(args) { return args || {} }

export const DialogControlPlugin = async ({ $ }) => {
  return {
    tool: {
      regime_status: tool({
        description: "Check the regime-driver worker health. Returns {healthy, base} JSON. " +
                     "Use regime_summary for the full situational picture.",
        args: { base: tool.schema.string().optional() },
        async execute(args) {
          const a = A(args)
          return await run($, ["status", "--json", "--base", a.base ?? BASE])
        },
      }),

      regime_summary: tool({
        description: "Aggregate situational summary in ONE call (read-only): worker health, " +
                     "live sessions with busy count + tokens, registered flows, supervised tasks, " +
                     "and (if reporter given) the report-bus rollup. Returns {healthy, sessions, " +
                     "busy_sessions, flows, tasks, reporter?} JSON. Use this to judge global state " +
                     "instead of piecing together status/sessions/flow-list manually.",
        args: {
          base: tool.schema.string().optional(),
          reporter: tool.schema.string().optional(),
          tasks_dir: tool.schema.string().optional(),
        },
        async execute(args) {
          const a = A(args)
          const opts = ["status", "--deep", "--json", "--base", a.base ?? BASE]
          if (a.reporter) opts.push("--reporter", a.reporter)
          if (a.tasks_dir) opts.push("--tasks-dir", a.tasks_dir)
          return await run($, opts)
        },
      }),

      regime_sessions: tool({
        description: "List all opencode sessions with {id,title,agent,status,tokens}. " +
                     "Options: clean=abort all, kill=abort a session id.",
        args: {
          base: tool.schema.string().optional(),
          clean: tool.schema.boolean().optional(),
          kill: tool.schema.string().optional(),
          perm: tool.schema.string().optional(),
        },
        async execute(args) {
          const a = A(args)
          const opts = ["sessions", "--json", "--base", a.base ?? BASE,
                        "--perm", a.perm ?? "clean"]
          if (a.clean) opts.push("--clean")
          if (a.kill) opts.push("--kill", a.kill)
          return await run($, opts)
        },
      }),

      regime_events: tool({
        description: "Read the JSONL event ledger (node_enter/node_done/reviewer_verdict...). " +
                     "Returns one JSON event per line. follow=false reads what exists.",
        args: { ledger: tool.schema.string(), follow: tool.schema.boolean().optional() },
        async execute(args) {
          const a = A(args)
          const opts = ["events", "--ledger", a.ledger]
          if (a.follow) opts.push("--follow")
          return await run($, opts)
        },
      }),

      regime_report: tool({
        description: "Read the report bus from an append-only journal: global rollup board " +
                     "(O(1) counters), journal history, or a templated report. Use this to see " +
                     "workflow outcomes, supervisor ladder actions, and per-workflow progress. " +
                     "Options: --wf <id> filter, --trace (causal chain for an object), " +
                     "--template milestone|blocker|period|activity, --since <ts>, --history.",
        args: {
          journal: tool.schema.string(),
          wf: tool.schema.string().optional(),
          history: tool.schema.boolean().optional(),
          object: tool.schema.string().optional().describe("object id to trace (with trace=true)"),
          trace: tool.schema.boolean().optional(),
          template: tool.schema.string().optional(),
          since: tool.schema.number().optional(),
          limit: tool.schema.number().optional(),
        },
        async execute(args) {
          const a = A(args)
          const opts = ["report", "--journal", a.journal, "--json"]
          if (a.wf) opts.push("--wf", a.wf)
          if (a.history) opts.push("--history")
          if (a.object) opts.push(a.object)
          if (a.trace) opts.push("--trace")
          if (a.template) opts.push("--template", a.template)
          if (a.since) opts.push("--since", String(a.since))
          if (a.limit) opts.push("--limit", String(a.limit))
          return await run($, opts)
        },
      }),

      regime_run: tool({
        description: "Run ONE task through the regime flow to completion (BLOCKING, can take minutes). " +
                     "Returns {outcome,end,detail,elapsed_sec} JSON. Provide a clear, self-contained task context. " +
                     "Set async=true to submit as a background job and return a handle immediately. " +
                     "Optionally set flow=<name> to run a Dialog-Control-designed registry flow instead of the builtin.",
        args: {
          context: tool.schema.string(),
          base: tool.schema.string().optional(),
          ledger: tool.schema.string().optional(),
          flow: tool.schema.string().optional(),
          async: tool.schema.boolean().optional(),
          perm: tool.schema.string().optional(),
        },
        async execute(args) {
          const a = A(args)
          const opts = ["run", a.context, "--json", "--base", a.base ?? BASE,
                        "--perm", a.perm ?? "run"]
          if (a.flow) opts.push("--flow", a.flow)
          if (a.ledger) opts.push("--ledger", a.ledger)
          if (a.async) opts.push("--async")
          return await run($, opts)
        },
      }),

      regime_run_many: tool({
        description: "Run several tasks as concurrent workflows (BLOCKING). " +
                     "Returns {elapsed_sec, results:{wid:{outcome,end,detail}}} JSON. " +
                     "Set async=true to submit as a background job and return a handle immediately.",
        args: {
          contexts: tool.schema.array(tool.schema.string()),
          base: tool.schema.string().optional(),
          async: tool.schema.boolean().optional(),
          perm: tool.schema.string().optional(),
        },
        async execute(args) {
          const a = A(args)
          const opts = ["run-many", ...(a.contexts || []), "--json", "--base", a.base ?? BASE,
                        "--perm", a.perm ?? "run"]
          if (a.async) opts.push("--async")
          return await run($, opts)
        },
      }),

      regime_job_list: tool({
        description: "List submitted background jobs (run/run-many --async) with their live status. " +
                     "running=true lists only running jobs. Returns {jobs:[...]} JSON.",
        args: { running: tool.schema.boolean().optional() },
        async execute(args) {
          const a = A(args)
          const opts = ["job", "list", "--json"]
          if (a.running) opts.push("--running")
          return await run($, opts)
        },
      }),

      regime_job_status: tool({
        description: "Show the status and (if finished) the result of a background job. " +
                     "Returns {id,type,status,pid,result,...} JSON. status is running|done|failed.",
        args: { job_id: tool.schema.string() },
        async execute(args) {
          const a = A(args)
          return await run($, ["job", "status", a.job_id, "--json"])
        },
      }),

      regime_session_send: tool({
        description: "Send a message to a specific opencode session (independent interaction). " +
                     "reply=true also returns the assistant's newest reply.",
        args: {
          session_id: tool.schema.string(),
          message: tool.schema.string(),
          reply: tool.schema.boolean().optional(),
          base: tool.schema.string().optional(),
          perm: tool.schema.string().optional(),
        },
        async execute(args) {
          const a = A(args)
          const opts = ["session", "send", a.session_id, a.message, "--json",
                        "--base", a.base ?? BASE, "--perm", a.perm ?? "interact"]
          if (a.reply) opts.push("--reply")
          return await run($, opts)
        },
      }),

      regime_session_reply: tool({
        description: "Read a session's newest assistant reply.",
        args: { session_id: tool.schema.string(), base: tool.schema.string().optional() },
        async execute(args) {
          const a = A(args)
          return await run($, ["session", "reply", a.session_id, "--json",
                               "--base", a.base ?? BASE])
        },
      }),

      regime_validate: tool({
        description: "Validate the regime flow descriptor. Returns {ok, flow, nodes, path, flows, unreachable} JSON.",
        args: { regime: tool.schema.string().optional() },
        async execute(args) {
          const a = A(args)
          const opts = ["validate", "--json"]
          if (a.regime) opts.push("--regime", a.regime)
          return await run($, opts)
        },
      }),

      regime_flow_list: tool({
        description: "List named flows in the FlowRegistry (builtin + designed + loaded). " +
                     "Returns {flows:[{name,version,source,nodes,path}]} JSON.",
        args: {},
        async execute(args) {
          return await run($, ["flow", "list", "--json"])
        },
      }),

      regime_flow_validate: tool({
        description: "Hot-validate a flow file (compile + structural + deep checks). " +
                     "Returns {ok, flow, nodes, errors, warnings} JSON. " +
                     "Rejects bad roles/cycles/tools BEFORE touching a worker.",
        args: { regime: tool.schema.string(), skills_dir: tool.schema.string().optional() },
        async execute(args) {
          const a = A(args)
          const opts = ["flow", "validate", a.regime, "--json"]
          if (a.skills_dir) opts.push("--skills-dir", a.skills_dir)
          return await run($, opts)
        },
      }),

      regime_flow_reload: tool({
        description: "Atomically hot-reload a file-backed named flow (deep-validated before swap). " +
                     "Running workflows keep their old snapshot. Returns {ok, name, version, ...} JSON.",
        args: { name: tool.schema.string(), perm: tool.schema.string().optional() },
        async execute(args) {
          const a = A(args)
          return await run($, ["flow", "reload", a.name, "--json", "--perm", a.perm ?? "run"])
        },
      }),

      regime_flow_design: tool({
        description: "Design AND register a new flow from an inline spec (full regime JSON or " +
                     "compact {\"entry\":\"a\",\"nodes\":[{id,desc,role,type,next}]}). No file needed. " +
                     "Compiles + deep-validates + registers into the persistent FlowRegistry. " +
                     "This is how the Dialog Control designs institutional workflows. Returns {ok, name, version, nodes, path} JSON.",
        args: {
          name: tool.schema.string().describe("flow name to register under"),
          spec: tool.schema.string().describe("inline flow spec JSON (compact or full regime)"),
          preflight: tool.schema.boolean().optional(),
          perm: tool.schema.string().optional(),
        },
        async execute(args) {
          const a = A(args)
          const opts = ["flow", "design", a.name, a.spec, "--json", "--perm", a.perm ?? "run"]
          if (a.preflight) opts.push("--preflight")
          return await run($, opts)
        },
      }),

      regime_flow_load: tool({
        description: "Register a full regime.json flow from its JSON CONTENT (a string, not a file path). " +
                     "Delegates to `flow design` so no temp file is created and no dead file pointer is " +
                     "persisted (reload-safe). Returns {ok, name, version, nodes} JSON.",
        args: {
          name: tool.schema.string().describe("flow name to register under"),
          content: tool.schema.string().describe("full regime.json content"),
          perm: tool.schema.string().optional(),
        },
        async execute(args) {
          const a = A(args)
          const opts = ["flow", "design", a.name, a.content, "--json", "--perm", a.perm ?? "run"]
          return await run($, opts)
        },
      }),
    },
  }
}
