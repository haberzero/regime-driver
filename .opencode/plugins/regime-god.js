// regime-god plugin: expose the regime-driver CLI contract as native opencode tools.
// The God Dialog (opencode `god` agent) calls these instead of raw bash for reliability.
// Each tool shells out to the regime CLI (conda env) and returns its --json output.
import { tool } from "@opencode-ai/plugin"

const REGIME = "conda run -n regime-driver regime"
const BASE = "http://127.0.0.1:4097"

// Run a regime command and return trimmed stdout (JSON). Throws on non-zero exit.
async function run($, args) {
  const cmd = [REGIME, ...args].join(" ")
  const proc = await $`${cmd}`.quiet()
  if (proc.exitCode !== 0) {
    throw new Error(`regime failed (${proc.exitCode}): ${proc.stderr?.text?.() || ""}`)
  }
  return (proc.stdout?.text?.() || "").trim()
}

export const RegimeGod = async ({ $ }) => {
  return {
    tool: {
      regime_status: tool({
        description: "Check the regime-driver worker health. Returns {healthy, base} JSON.",
        args: { base: tool.schema.string().optional().default(BASE) },
        async execute(args) { return await run($, ["status", "--json", "--base", args.base]) },
      }),

      regime_sessions: tool({
        description: "List all opencode sessions with {id,title,agent,status,tokens}. " +
                     "Options: clean=abort all, kill=abort a session id.",
        args: {
          base: tool.schema.string().optional().default(BASE),
          clean: tool.schema.boolean().optional().default(false),
          kill: tool.schema.string().optional(),
        },
        async execute(args) {
          const opts = ["sessions", "--json", "--base", args.base]
          if (args.clean) opts.push("--clean")
          if (args.kill) opts.push("--kill", args.kill)
          return await run($, opts)
        },
      }),

      regime_events: tool({
        description: "Read the JSONL event ledger (node_enter/node_done/reviewer_verdict...). " +
                     "Returns one JSON event per line. follow=false reads what exists.",
        args: { ledger: tool.schema.string(), follow: tool.schema.boolean().optional().default(false) },
        async execute(args) {
          const opts = ["events", "--ledger", args.ledger]
          if (args.follow) opts.push("--follow")
          return await run($, opts)
        },
      }),

      regime_run: tool({
        description: "Run ONE task through the regime flow to completion (BLOCKING, can take minutes). " +
                     "Returns {outcome,end,detail,elapsed_sec} JSON. Provide a clear, self-contained task context. " +
                     "Set async=true to submit as a background job and return a handle immediately.",
        args: {
          context: tool.schema.string(),
          base: tool.schema.string().optional().default(BASE),
          ledger: tool.schema.string().optional(),
          async: tool.schema.boolean().optional().default(false),
        },
        async execute(args) {
          const opts = ["run", args.context, "--json", "--base", args.base]
          if (args.ledger) opts.push("--ledger", args.ledger)
          if (args.async) opts.push("--async")
          return await run($, opts)
        },
      }),

      regime_run_many: tool({
        description: "Run several tasks as concurrent workflows (BLOCKING). " +
                     "Returns {elapsed_sec, results:{wid:{outcome,end,detail}}} JSON. " +
                     "Set async=true to submit as a background job and return a handle immediately.",
        args: {
          contexts: tool.schema.array(tool.schema.string()),
          base: tool.schema.string().optional().default(BASE),
          async: tool.schema.boolean().optional().default(false),
        },
        async execute(args) {
          const opts = ["run-many", ...args.contexts, "--json", "--base", args.base]
          if (args.async) opts.push("--async")
          return await run($, opts)
        },
      }),

      regime_job_list: tool({
        description: "List submitted background jobs (run/run-many --async) with their live status. " +
                     "running=true lists only running jobs. Returns {jobs:[...]} JSON.",
        args: { running: tool.schema.boolean().optional().default(false) },
        async execute(args) {
          const opts = ["job", "list", "--json"]
          if (args.running) opts.push("--running")
          return await run($, opts)
        },
      }),

      regime_job_status: tool({
        description: "Show the status and (if finished) the result of a background job. " +
                     "Returns {id,type,status,pid,result,...} JSON. status is running|done|failed.",
        args: { job_id: tool.schema.string() },
        async execute(args) {
          return await run($, ["job", "status", args.job_id, "--json"])
        },
      }),

      regime_session_send: tool({
        description: "Send a message to a specific opencode session (independent interaction). " +
                     "reply=true also returns the assistant's newest reply.",
        args: {
          session_id: tool.schema.string(),
          message: tool.schema.string(),
          reply: tool.schema.boolean().optional().default(false),
          base: tool.schema.string().optional().default(BASE),
        },
        async execute(args) {
          const opts = ["session", "send", args.session_id, args.message, "--json", "--base", args.base]
          if (args.reply) opts.push("--reply")
          return await run($, opts)
        },
      }),

      regime_session_reply: tool({
        description: "Read a session's newest assistant reply.",
        args: { session_id: tool.schema.string(), base: tool.schema.string().optional().default(BASE) },
        async execute(args) {
          return await run($, ["session", "reply", args.session_id, "--json", "--base", args.base])
        },
      }),

      regime_validate: tool({
        description: "Validate the regime flow descriptor. Returns {ok, flow, nodes, path, flows, unreachable} JSON.",
        args: { regime: tool.schema.string().optional() },
        async execute(args) {
          const opts = ["validate", "--json"]
          if (args.regime) opts.push("--regime", args.regime)
          return await run($, opts)
        },
      }),
    },
  }
}
