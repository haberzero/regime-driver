// regime-god plugin: expose the regime-driver CLI contract as native opencode tools.
// The God Dialog (opencode `god` agent) calls these instead of raw bash for reliability.
// Each tool shells out to the regime CLI (conda env) and returns its --json output.
import { tool } from "@opencode-ai/plugin"

// Invoke the regime CLI entry point DIRECTLY (no `conda run` wrapper): conda run's
// subprocess output capture is lost when spawned from the tool process, which makes
// the tool return empty. The env's `regime` binary streams output reliably.
const REGIME = ["/opt/miniconda3/envs/regime-driver/bin/regime"]
const BASE = "http://127.0.0.1:4097"

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

export const RegimeGod = async ({ $ }) => {
  return {
    tool: {
      regime_status: tool({
        description: "Check the regime-driver worker health. Returns {healthy, base} JSON.",
        args: { base: tool.schema.string().optional() },
        async execute(args) {
          const a = A(args)
          return await run($, ["status", "--json", "--base", a.base ?? BASE])
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

      regime_run: tool({
        description: "Run ONE task through the regime flow to completion (BLOCKING, can take minutes). " +
                     "Returns {outcome,end,detail,elapsed_sec} JSON. Provide a clear, self-contained task context. " +
                     "Set async=true to submit as a background job and return a handle immediately.",
        args: {
          context: tool.schema.string(),
          base: tool.schema.string().optional(),
          ledger: tool.schema.string().optional(),
          async: tool.schema.boolean().optional(),
          perm: tool.schema.string().optional(),
        },
        async execute(args) {
          const a = A(args)
          const opts = ["run", a.context, "--json", "--base", a.base ?? BASE,
                        "--perm", a.perm ?? "run"]
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
    },
  }
}
