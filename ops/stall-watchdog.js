// stall-watchdog: in-process thinking-stall guard for opencode.
//
// Why it exists (see docs/RESEARCH-thinking-timeout.md):
//   - opencode has only transport-level timeouts (provider timeout / chunkTimeout).
//   - goal-plugin deliberately excludes reasoning-only turns from its no-progress
//     stall gate, and supervisor.py's T3 fingerprint counts reasoning growth as
//     progress — so neither detects a model that emits reasoning forever but
//     never produces text or tool calls ("thinking deadlock").
//
// What it does:
//   - Learns part types from message.part.updated (fires at part start/end with
//     the full part, e.g. reasoning-start / text-start / tool-start).
//   - Watches message.part.delta (the frequent per-token stream event; carries
//     NO part type) and classifies it via the learned type:
//       "reasoning"      -> activity, but NO output progress.
//       "text"/"tool"    -> output progress (clock resets).
//   - While a session is busy:
//       * no event at all for turnStallSec        -> silent stall -> abort
//       * only-reasoning for thinkingStallSec      -> thinking stall -> abort
//   - After abort the session goes idle, goal-plugin resumes the goal.
//   - Only observes + aborts. Never injects prompts, never modifies goals.
//
// Config (second element of the plugin array entry in opencode.json):
//   { thinkingStallSec, turnStallSec, pollSec, abortCooldownMs, ledgerPath, enabled }
//
// Exported pure functions (observe/checkStall) for deterministic unit tests.

import { appendFileSync } from "node:fs"

export function defaultOptions(overrides = {}) {
  return {
    enabled: true,
    thinkingStallSec: 120,
    turnStallSec: 300,
    pollSec: 5,
    abortCooldownMs: 30_000,
    maxConsecutiveAborts: 3,
    giveUpWindowMs: 45 * 60 * 1000,
    resumeDelayMs: 3000,
    ledgerPath: "/root/control/run-ledger.jsonl",
    ...overrides,
  }
}

export function eventSessionID(event) {
  return (
    event?.properties?.sessionID ||
    event?.properties?.info?.sessionID ||
    event?.data?.sessionID ||
    event?.data?.info?.sessionID ||
    null
  )
}

export function newSessionState(now = Date.now()) {
  return {
    status: "busy",
    lastActivityAt: now,
    lastOutputAt: now,
    lastAbortAt: 0,
  }
}

const OUTPUT_PART_TYPES = new Set(["text", "tool"])

function recordPartType(partTypes, part, sid, now) {
  if (!part?.id || !part?.type) return
  partTypes.set(part.id, { type: part.type, sessionID: sid, at: now })
  // Bounded memory: drop the oldest learned type once we exceed the cap.
  if (partTypes.size > 1024) {
    const oldestKey = partTypes.keys().next().value
    if (oldestKey !== undefined) partTypes.delete(oldestKey)
  }
}

// Update watchdog state from a host event. Pure; operates on a context object
// ctx = { sessions: Map, partTypes: Map }.
export function observe(ctx, event, now = Date.now()) {
  const { sessions, partTypes } = ctx
  const type = event?.type
  if (type === "session.status") {
    const sid = eventSessionID(event)
    if (!sid) return null
    const status = event?.properties?.status?.type
    if (status === "busy" || status === "retry") {
      // Fresh turn: reset both clocks so a long lead-in reasoning phase is
      // measured from turn start, not from the previous turn.
      sessions.set(sid, newSessionState(now))
      sessions.get(sid).status = status
    } else {
      // idle or any other/unknown status: no active turn to guard.
      sessions.delete(sid)
    }
    return sessions.get(sid) ?? null
  }

  if (type === "session.idle") {
    const sid = eventSessionID(event)
    if (sid) sessions.delete(sid)
    return null
  }

  if (type === "message.part.updated") {
    const sid = eventSessionID(event)
    const part = event?.properties?.part
    if (part?.type) recordPartType(partTypes, part, sid, now)
    if (!sid) return null
    const s = sessions.get(sid) || (sessions.set(sid, newSessionState(now)), sessions.get(sid))
    s.lastActivityAt = now
    if (part?.type && OUTPUT_PART_TYPES.has(part.type)) s.lastOutputAt = now
    return s
  }

  if (type === "message.part.delta") {
    const sid = eventSessionID(event)
    const pid = event?.properties?.partID
    if (!sid || !pid) return null
    const s = sessions.get(sid) || (sessions.set(sid, newSessionState(now)), sessions.get(sid))
    s.lastActivityAt = now
    const ptype = partTypes.get(pid)?.type
    if (OUTPUT_PART_TYPES.has(ptype)) s.lastOutputAt = now
    return s
  }

  if (type === "message.updated") {
    const sid = eventSessionID(event)
    if (!sid) return null
    const s = sessions.get(sid) || (sessions.set(sid, newSessionState(now)), sessions.get(sid))
    s.lastActivityAt = now
    return s
  }

  return null
}

// Decide whether a session should be aborted. Pure.
// opts: { thinkingStallSec, turnStallSec }
// Returns { kind: "silent" | "thinking", sec } or null.
export function checkStall(state, now = Date.now(), opts = {}) {
  const turnStallSec = opts.turnStallSec ?? 300
  const thinkingStallSec = opts.thinkingStallSec ?? 120
  if (state.status !== "busy" && state.status !== "retry") return null
  const silentSec = (now - state.lastActivityAt) / 1000
  if (state.lastActivityAt && silentSec >= turnStallSec) {
    return { kind: "silent", sec: Math.round(silentSec) }
  }
  const thinkingSec = (now - state.lastOutputAt) / 1000
  if (state.lastOutputAt && thinkingSec >= thinkingStallSec) {
    return { kind: "thinking", sec: Math.round(thinkingSec) }
  }
  return null
}

// Compute the stall-history slice within the give-up window and append `now`.
// Pure. Returns the updated history array; its length is the running count.
export function countStall(history, now, opts = {}) {
  const windowMs = opts.giveUpWindowMs ?? 45 * 60 * 1000
  const fresh = (history || []).filter((t) => now - t <= windowMs)
  fresh.push(now)
  return fresh
}

// Decide the response to a stall given the count of stalls in the give-up
// window. Pure. Returns "abort" (abort then resume) or "giveup" (leave paused,
// escalate). The count is window-based (see giveUpWindowMs) so intermediate
// command-turn bookkeeping text cannot mask a repeated stuck loop.
export function abortDecision(count, opts = {}) {
  const max = opts.maxConsecutiveAborts ?? 3
  return count > max ? "giveup" : "abort"
}

export default {
  id: "stall-watchdog",
  server: async (ctx = {}, options = {}) => {
    const opts = defaultOptions(options)
    const client = ctx?.client
    const sessions = new Map()
    const partTypes = new Map()
    const recentStalls = new Map()
    const givenUp = new Set()
    const watchdog = { sessions, partTypes }
    const ledger = { path: opts.ledgerPath }

    function log(event, extra = {}) {
      const rec = { event, ts: new Date().toISOString(), plugin: "stall-watchdog", ...extra }
      try {
        appendFileSync(ledger.path, JSON.stringify(rec) + "\n")
      } catch (err) {
        // Best-effort: ledger write must never crash the plugin host.
      }
      return rec
    }

    // Shape-agnostic abort (opencode 1.18.x SDK uses { path: { id } } legacy
    // shape; newer SDKs use { sessionID } flat shape). Only fall back when the
    // first call failed validation BEFORE reaching the host, so we never
    // double-abort a session that the first call already aborted.
    const SHAPE_ERROR = /(?:missing|required|unknown|invalid).*(?:sessionID|path|body|query)/i
    async function abortSession(sid) {
      const method = client?.session?.abort
      if (typeof method !== "function") {
        log("watchdog_abort_error", { session: sid, err: "client.session.abort unavailable" })
        return false
      }
      const attempts = [
        () => method.call(client.session, { path: { id: sid } }),
        () => method.call(client.session, { sessionID: sid }),
      ]
      let lastErr = null
      let ok = false
      for (let i = 0; i < attempts.length; i++) {
        // Abort can stay pending while the host is wedged; only needing it to
        // reach the server, race it against a short timeout so the watchdog
        // never blocks on a hung abort (and so give-up actually sticks).
        const settled = await Promise.race([
          attempts[i]().then(() => "ok", (err) => { lastErr = err; return "err" }),
          new Promise((resolve) => setTimeout(() => resolve("sent"), 10000)),
        ])
        if (settled === "ok" || settled === "sent") {
          ok = true
          break
        }
        const msg = String(lastErr?.message || lastErr)
        if (!SHAPE_ERROR.test(msg)) break
      }
      if (ok) {
        log("watchdog_aborted", { session: sid })
      } else {
        log("watchdog_abort_error", { session: sid, err: String(lastErr?.message || lastErr) })
      }
      return ok
    }

    // Resume a goal the goal-plugin paused (its abort handler treats an aborted
    // turn as "user interrupted" and pauses). Sending `goal resume` re-arms the
    // goal-plugin's idle-driven auto-continue. We only do this for a limited
    // number of consecutive stall-aborts so a genuinely stuck goal livelocks
    // bounded-ly and eventually hands control back to the supervisor/human.
    async function resumeGoal(sid) {
      const method = client?.session?.command
      if (typeof method !== "function") {
        log("watchdog_resume_error", { session: sid, err: "client.session.command unavailable" })
        return false
      }
      const body = { command: "goal", arguments: "resume", agent: "build" }
      const attempts = [
        () => method.call(client.session, { path: { id: sid }, body }),
        () => method.call(client.session, { sessionID: sid, ...body }),
      ]
      let lastErr = null
      let ok = false
      for (let i = 0; i < attempts.length; i++) {
        // The command may stay pending until the resumed goal finishes its next
        // (possibly infinite) turn. We only need it to reach the server, so race
        // the call against a short timeout and treat a send as success.
        const settled = await Promise.race([
          attempts[i]().then(() => "ok", (err) => { lastErr = err; return "err" }),
          new Promise((resolve) => setTimeout(() => resolve("sent"), 5000)),
        ])
        if (settled === "ok" || settled === "sent") {
          ok = true
          break
        }
        const msg = String(lastErr?.message || lastErr)
        if (!SHAPE_ERROR.test(msg)) break
      }
      if (ok) {
        log("watchdog_resumed", { session: sid })
      } else {
        log("watchdog_resume_error", { session: sid, err: String(lastErr?.message || lastErr) })
      }
      return ok
    }

    const timer = setInterval(() => {
      if (!opts.enabled) return
      const now = Date.now()
      for (const [sid, st] of sessions) {
        if (givenUp.has(sid)) continue
        if (now - st.lastAbortAt < opts.abortCooldownMs) continue
        const verdict = checkStall(st, now, opts)
        if (!verdict) continue
        st.lastAbortAt = now

        const history = countStall(recentStalls.get(sid), now, opts)
        recentStalls.set(sid, history)
        const count = history.length
        log(`watchdog_${verdict.kind}_stall`, {
          session: sid,
          sec: verdict.sec,
          status: st.status,
          consecutive: count,
          thinkingStallSec: opts.thinkingStallSec,
          turnStallSec: opts.turnStallSec,
        })

        if (abortDecision(count, opts) === "giveup") {
          // Bounded give-up: stop the runaway stream (abort) but DO NOT resume,
          // leaving the goal paused for the supervisor/human to handle (model
          // fallback, escalation, etc.). A paused goal + this ledger event is a
          // deterministic hand-off point. Give-up is STICKY: the session is
          // blacklisted (givenUp) so the watchdog stops acting on it until a
          // genuinely new turn starts — a fresh session.status busy clears it.
          recentStalls.delete(sid)
          givenUp.add(sid)
          log("watchdog_gave_up", { session: sid, consecutive: count - 1 })
          void abortSession(sid)
          continue
        }

        void abortSession(sid).then((ok) => {
          if (ok) setTimeout(() => void resumeGoal(sid), opts.resumeDelayMs)
        })
      }
    }, opts.pollSec * 1000)
    if (typeof timer?.unref === "function") timer.unref()

    log("watchdog_ready", {
      enabled: opts.enabled,
      thinkingStallSec: opts.thinkingStallSec,
      turnStallSec: opts.turnStallSec,
      pollSec: opts.pollSec,
    })

    const event = async ({ event: evt }) => {
      if (!opts.enabled) return
      try {
        const t = evt?.type
        if (t === "session.status") {
          const status = evt?.properties?.status?.type
          const sid = eventSessionID(evt)
          if (status === "busy" || status === "retry") {
            if (sid) givenUp.delete(sid) // genuinely new turn -> fresh chance
          }
        }
        observe(watchdog, evt)
      } catch (err) {
        log("watchdog_observe_error", { err: String(err?.message || err) })
      }
    }

    const dispose = () => {
      clearInterval(timer)
      log("watchdog_disposed", {})
    }

    return { event, dispose }
  },
}
