#!/usr/bin/env node
/**
 * epic-runner.mjs — run one Guardian command in a headless pi session.
 *
 * Why this exists: `pi -p "/architect ..."` does NOT dispatch extension
 * commands (the text is sent to the model instead). RPC mode does — a
 * `prompt` whose message is an extension command "executes immediately"
 * (pi docs, rpc-commands.md#prompt), and reports
 * `data.disposition: "handled"`.
 *
 * So we spawn `pi --mode rpc`, send the command as a prompt, mirror every
 * JSONL event into a log, and exit when pi settles.
 *
 * Usage:
 *   epic-runner.mjs "<command>" [--log <path>] [--cwd <dir>]
 *                               [--timeout-ms N] [--session <id>]
 *
 * Exit codes:
 *   0  command handled and session settled
 *   1  failure (spawn error, rejected prompt, aborted, timeout)
 *   3  command was NOT an extension command (fell through to the model)
 */
import { spawn } from "node:child_process";
import { createWriteStream, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";

function parseArgs(argv) {
	const out = { command: null, log: null, cwd: process.cwd(), timeoutMs: 0, session: null };
	const rest = [];
	for (let i = 0; i < argv.length; i++) {
		const a = argv[i];
		if (a === "--log") out.log = argv[++i];
		else if (a === "--cwd") out.cwd = resolve(argv[++i]);
		else if (a === "--timeout-ms") out.timeoutMs = Number(argv[++i]) || 0;
		else if (a === "--session") out.session = argv[++i];
		else rest.push(a);
	}
	out.command = rest.join(" ").trim();
	return out;
}

const opts = parseArgs(process.argv.slice(2));
if (!opts.command) {
	console.error('usage: epic-runner.mjs "<command>" [--log path] [--cwd dir] [--timeout-ms N]');
	process.exit(1);
}

let logStream = null;
if (opts.log) {
	mkdirSync(dirname(opts.log), { recursive: true });
	logStream = createWriteStream(opts.log, { flags: "a" });
}

function emit(line) {
	if (logStream) logStream.write(`${line}\n`);
	process.stdout.write(`${line}\n`);
}

const args = ["--mode", "rpc"];
// A dedicated session per runner keeps parallel agents isolated; --no-session
// keeps the repo clean. Prefer a session when one is named.
if (opts.session) args.push("--session-id", opts.session);
else args.push("--no-session");

const child = spawn("pi", args, {
	cwd: opts.cwd,
	stdio: ["pipe", "pipe", "pipe"],
	env: process.env,
});

let settled = false;
let handled = false;
let failed = false;
let buffered = "";

const timer = opts.timeoutMs
	? setTimeout(() => {
			emit(JSON.stringify({ type: "runner_timeout", timeoutMs: opts.timeoutMs }));
			failed = true;
			finish(1);
		}, opts.timeoutMs)
	: null;

function finish(code) {
	if (settled) return;
	settled = true;
	if (timer) clearTimeout(timer);
	if (typeof cancelGrace === "function") cancelGrace();
	try {
		child.stdin.end();
	} catch {
		/* ignore */
	}
	// give the child a moment to flush, then stop it
	setTimeout(() => {
		try {
			child.kill("SIGTERM");
		} catch {
			/* ignore */
		}
		logStream?.end();
		process.exit(code);
	}, 250);
}

function handleLine(line) {
	if (!line.trim()) return;
	emit(line);
	let msg;
	try {
		msg = JSON.parse(line);
	} catch {
		return;
	}
	// The prompt was accepted by an extension command?
	if (msg.type === "response" && msg.command === "prompt" && msg.success === true) {
		const d = msg.data?.disposition;
		if (d === "handled") handled = true;
		else if (d === "started" || d === "queued") handled = true;
		if (handled) armGrace();
	}
	if (msg.type === "response" && msg.command === "prompt" && msg.success === false) {
		emit(JSON.stringify({ type: "runner_error", reason: "prompt rejected" }));
		failed = true;
		finish(1);
	}
	// A low-level run started: the command is doing real work, so wait for the
	// settle event instead of using the grace timer.
	if (msg.type === "agent_start") {
		sawRun = true;
		cancelGrace();
	}
	if (msg.type === "agent_settled") {
		finish(msg.aborted ? 1 : 0);
	}
}

// A "handled" extension command may start no LLM run at all (e.g. /architect
// status), in which case `agent_settled` never fires and stdin stays open. If
// no run activity appears within the grace window, treat the command as done.
// pi docs (rpc.md#prompt): with disposition "handled", don't wait for
// agent_settled unless the extension itself starts work.
const GRACE_MS = Number(process.env.GUARDIAN_RUNNER_GRACE_MS || 5000);
let graceTimer = null;
let sawRun = false;

function cancelGrace() {
	if (graceTimer) {
		clearTimeout(graceTimer);
		graceTimer = null;
	}
}

function armGrace() {
	cancelGrace();
	graceTimer = setTimeout(() => {
		if (!sawRun) {
			emit(JSON.stringify({ type: "runner_done", reason: "handled, no run started" }));
			finish(0);
		}
	}, GRACE_MS);
}

child.stdout.on("data", (buf) => {
	buffered += buf.toString();
	let idx = buffered.indexOf("\n");
	while (idx !== -1) {
		handleLine(buffered.slice(0, idx));
		buffered = buffered.slice(idx + 1);
		idx = buffered.indexOf("\n");
	}
});

child.stderr.on("data", (buf) => {
	for (const line of buf.toString().split("\n")) {
		if (line.trim()) emit(JSON.stringify({ type: "stderr", line }));
	}
});

child.on("error", (err) => {
	emit(JSON.stringify({ type: "runner_error", reason: String(err) }));
	failed = true;
	finish(1);
});

child.on("exit", (code) => {
	if (buffered.trim()) handleLine(buffered);
	if (settled) return;
	// Settle on exit: a handled command that ended cleanly is a success.
	finish(failed ? 1 : handled && code === 0 ? 0 : handled ? 0 : 3);
});

// Send the prompt once the session is up. pi reads JSONL from stdin.
child.stdin.write(`${JSON.stringify({ id: "1", type: "prompt", message: opts.command })}\n`);