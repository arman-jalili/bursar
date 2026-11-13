// Canonical Reference: .pi/architecture/modules/epic-parallel.md#epic-command
/**
 * /epic — parallel epic scale-out (companion to /architect --epic).
 *
 * One module -> one epic branch -> one worktree -> one PR. The command shares
 * the same registry + contract-freeze gate as /architect --parallel so both
 * entry points behave identically.
 *
 *   /epic parallel "<Module>"     create worktree + branch (gated)
 *   /epic freeze "<Module>"       record that contracts are frozen
 *   /epic status                  list registered epics (all worktrees)
 *   /epic prompt                  show the scale-out procedure
 */
import { execSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

type ExtensionContext = { cwd: string; ui: { notify(message: string, level?: string): void } };
type ExtensionAPI = {
	registerCommand(
		name: string,
		options: { description: string; handler(args: unknown, ctx: ExtensionContext): unknown },
	): void;
};

function unquote(s: string): string {
	return s.trim().replace(/^["']|["']$/g, "");
}

function run(cwd: string, cmd: string): { code: number; out: string } {
	try {
		const out = execSync(cmd, { cwd, encoding: "utf-8", stdio: ["pipe", "pipe", "pipe"] });
		return { code: 0, out };
	} catch (e) {
		const err = e as { status?: number; stdout?: string; stderr?: string };
		return { code: err.status ?? 1, out: `${err.stdout ?? ""}${err.stderr ?? ""}` };
	}
}

export default function epicExtension(pi: ExtensionAPI) {
	pi.registerCommand("epic", {
		description: "Parallel epics: one worktree per module, gated on frozen contracts",
		handler: async (args: unknown, ctx: ExtensionContext) => {
			const raw = String(args ?? "").trim();
			const [action, ...rest] = raw.split(/\s+/);
			const moduleName = unquote(rest.join(" "));

			if (!action) {
				ctx.ui.notify(
					[
						"Usage:",
						'  /epic parallel "<Module>"   create worktree + epic branch (requires frozen contracts)',
						'  /epic freeze "<Module>"     record that shared contracts are frozen',
						"  /epic status                list registered epics across worktrees",
						"  /epic prompt                show the scale-out procedure",
					].join("\n"),
					"info",
				);
				return;
			}

			if (action === "freeze") {
				if (!moduleName) {
					ctx.ui.notify('Usage: /epic freeze "<Module>"', "error");
					return;
				}
				const r = run(ctx.cwd, `bash .pi/scripts/epic-registry.sh freeze "${moduleName}" --frozen`);
				ctx.ui.notify(r.code === 0 ? `Contracts frozen for "${moduleName}"` : r.out.slice(0, 300), r.code === 0 ? "success" : "error");
				return;
			}

			if (action === "parallel") {
				if (!moduleName) {
					ctx.ui.notify('Usage: /epic parallel "<Module>"', "error");
					return;
				}
				const r = run(ctx.cwd, `bash .pi/scripts/epic-parallel.sh "${moduleName}"`);
				if (r.code === 2) {
					ctx.ui.notify(
						`Blocked: contracts for "${moduleName}" are not frozen. Merge the Contract Freeze issue, then /epic freeze "${moduleName}".`,
						"error",
					);
					return;
				}
				ctx.ui.notify(
					r.code === 0
						? `Worktree ready for "${moduleName}". Next: cd into it and run /architect --epic "${moduleName}"`
						: r.out.slice(0, 400),
					r.code === 0 ? "success" : "error",
				);
				return;
			}

			if (action === "status") {
				const r = run(ctx.cwd, "bash .pi/scripts/epic-registry.sh list");
				ctx.ui.notify(r.out || "(no epics registered)", "info");
				return;
			}

			if (action === "prompt") {
				const p = join(ctx.cwd, ".pi", "prompts", "epic-parallel.md");
				if (existsSync(p)) {
					ctx.ui.notify(`Procedure: ${p}`, "info");
					return readFileSync(p, "utf-8");
				}
				ctx.ui.notify("Run `bash .pi/scripts/epic-parallel.sh <Module>` after freezing contracts.", "info");
				return;
			}

			ctx.ui.notify(`Unknown /epic action "${action}". Try /epic for usage.`, "error");
		},
	});
}
