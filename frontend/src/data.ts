// Bursar frontend — contract types and demo fixtures.
// The shapes mirror docs/BURSAR-BUILD-CONTRACT.md. Amounts are USDC micro-units (6 dp).

export type Mode = "base-sepolia" | "anvil";

export type VerifyState = "ok" | "bad" | undefined;

export type AttemptStatus =
  | "planned"
  | "pending_approval"
  | "allowed"
  | "refused"
  | "dispatched"
  | "settled"
  | "ambiguous"
  | "failed";

export interface Payee {
  id: string;
  name: string;
  address: string;
  frozen: boolean;
  new: boolean;
}

export interface AttemptDecision {
  allow: boolean;
  source: "rigorix-plan" | "rigorix-dispatch" | "authority" | "contract";
  rule?: string;
  reason?: string;
  decisionDigest?: string;
}

export interface Attempt {
  id: string;
  invoiceId: string;
  payee: Payee;
  amountUsdc: string;
  status: AttemptStatus;
  createdAt: string;
  decision?: AttemptDecision;
  rigorix?: {
    executionId: string;
    envelopeHash?: string;
    envelopeUri?: string;
    anchoredTx?: string;
  };
  settlement?: { txHash?: string; block?: number; receipt?: string };
  narrative: string;
  /** True for rows read from the live console (they count toward the live cap). */
  live?: boolean;
  /** Console API: the approval this attempt is waiting on. */
  approvalId?: string;
  /** Console API: the Evidence envelope linked to this attempt. */
  evidenceId?: string;
  evidenceEvent?: string;
  evidenceResult?: string;
  evidenceAt?: string;
  anchorTx?: string;
}

export interface Policy {
  dailyCapUsdc: string;
  perPayeeCapUsdc: string;
  approvalThresholdUsdc: string;
  allowlist: Payee[];
  quarantineOnBankChange: boolean;
  frozenPayeeIds: string[];
}

export interface ApprovalRequest {
  approvalId?: string;
  /** Console/Authority: the intent the settlement dispatch names. */
  intentId?: string;
  attemptId: string;
  intentDigest: string;
  invoiceId: string;
  payee: Payee;
  amountUsdc: string;
  nonce: string;
  deadline: string;
  eip712: {
    domain: Record<string, unknown>;
    types: Record<string, unknown>;
    message: Record<string, unknown>;
  };
}

export interface ChainState {
  mode: Mode;
  block: number;
  router: string;
  anchor: string;
  sealed: number;
}

// ── payees ────────────────────────────────────────────────────────────────

const payee = (
  id: string,
  name: string,
  address: string,
  opts: Partial<Payee> = {},
): Payee => ({ id, name, address, frozen: false, new: false, ...opts });

export const WIEN = payee("wien-energie", "Wien Energie", "0x2f8a9c1e0b4d7a6f3e2c1b0a9d8e7f6a5c4b3d21");
export const APOTHEKE = payee("apotheke", "Apotheke zum Heiligen Geist", "0x8b1d4f2a6c9e0d3b7a5f1e8c2d6b4a9f3e7c1d05");
export const ZAHNARZT = payee("zahnarzt-keller", "Zahnarzt Dr. Keller", "0x2f8a4c11e9b2a7d3c6f0b8e5a1d9c4b7f2e6a308", { new: true });
export const SPLIT = payee("split-batch", "Split invoice · 6 suppliers", "0x6c3a9e1d4b7f2a8d5c0e3b6a9f1d4c7e2b8a5f09", { new: false });
export const HAUSMEISTER = payee("hausmeister", "Hausmeister service", "0x9d2e5b8a1c4f7e0d3a6b9c2f5e8a1d4b7c0f3e69");

export const PAYEES = [WIEN, APOTHEKE, ZAHNARZT, HAUSMEISTER, SPLIT];

// ── policy + chain ────────────────────────────────────────────────────────

export const INITIAL_POLICY: Policy = {
  dailyCapUsdc: "500000000", // €500 / USDC 500
  perPayeeCapUsdc: "400000000",
  approvalThresholdUsdc: "100000000",
  allowlist: [WIEN, APOTHEKE, ZAHNARZT, HAUSMEISTER],
  quarantineOnBankChange: true,
  frozenPayeeIds: [],
};

export const CHAIN: ChainState = {
  mode: "base-sepolia",
  block: 18442901,
  router: "0x4a2f9c1e0b4d7a6f3e2c1b0a9d8e7f6a5c4b3d01",
  anchor: "0x9e11c4a7b2d6f0e3a8c1b5d9f2a6c0e4b7d1f8bd",
  sealed: 3,
};

// ── demo attempts ─────────────────────────────────────────────────────────

const t = (minutesAgo: number) => {
  const d = new Date("2026-11-14T14:09:00+01:00");
  d.setMinutes(d.getMinutes() - minutesAgo);
  return d.toISOString();
};

export const INITIAL_ATTEMPTS: Attempt[] = [
  {
    id: "att-01",
    invoiceId: "INV-2026-0304",
    payee: WIEN,
    amountUsdc: "84200000",
    status: "settled",
    createdAt: t(5),
    decision: {
      allow: true,
      source: "rigorix-dispatch",
      rule: "standing-record",
      reason: "Payee, amount and invoice digest match the standing record.",
    },
    rigorix: {
      executionId: "01a1d567-36e8-7d40-84a4-2c79048aa01a",
      envelopeHash: "0x4c8a9d2e6b1f0a3c7e5d8b2a9f4c1e6d0b7a3f5c",
      envelopeUri: "/api/attempts/att-01/envelope",
      anchoredTx: "0x9e11c4a7b2d6f0e3a8c1b5d9f2a6c0e4b7d1f8bd",
    },
    settlement: {
      txHash: "0x8f2a1c4e7b0d3f6a9c2e5b8d1f4a7c0e3b6d9f2a1c4e7b0d3f6a9c2e5b8d1f4a",
      block: 18442901,
      receipt: "0x8f2a…c41e",
    },
    narrative: "Matched the March bill on file. Paid from the household account.",
  },
  {
    id: "att-02",
    invoiceId: "INV-2026-0305",
    payee: APOTHEKE,
    amountUsdc: "32100000",
    status: "settled",
    createdAt: t(11),
    decision: {
      allow: true,
      source: "rigorix-dispatch",
      rule: "standing-record",
      reason: "Recurring prescription; payee and amount match the standing record.",
    },
    rigorix: {
      executionId: "01a1d567-5a86-7522-80d8-a21f46735d6d",
      envelopeHash: "0x92e1b7c4a0d3f6e9b2c5a8d1f4e7b0c3a6d9f2e5b8c1a4d7f0e3b6c9a2d5f8e1",
      envelopeUri: "/api/attempts/att-02/envelope",
    },
    settlement: {
      txHash: "0x12bd5e8a1c4f7b0d3e6a9c2f5b8d1e4a7c0f3b6d9e2a5c8f1b4d7e0a3c6f9b2d",
      block: 18442868,
      receipt: "0x12bd…77a0",
    },
    narrative: "A recurring prescription. The payee and amount match the standing record.",
  },
  {
    id: "att-03",
    invoiceId: "INV-2026-0311",
    payee: ZAHNARZT,
    amountUsdc: "240000000",
    status: "pending_approval",
    createdAt: t(1),
    decision: {
      allow: false,
      source: "rigorix-plan",
      rule: "new_payee",
      reason: "The payee is new and the amount is above the €100 approval line.",
    },
    narrative: "A new payee, above your €100 line. I have not paid it.",
  },
  {
    id: "att-04",
    invoiceId: "INV-2026-0998",
    payee: WIEN,
    amountUsdc: "1240000000",
    status: "refused",
    createdAt: t(3),
    decision: {
      allow: false,
      source: "rigorix-dispatch",
      rule: "bank_digest_mismatch",
      reason:
        "The invoice presents a different bank digest than the verified one. The payee is quarantined and no transaction was sent.",
    },
    rigorix: {
      executionId: "01a1d567-6759-7183-b563-ed0530d29d45",
      envelopeHash: "0x77a0c4e1b8d2f5a9c3e6b0d4f7a1c8e2b5d9f3a6c0e4b7d1f8a2c5e9b3d6f0a4",
      envelopeUri: "/api/attempts/att-04/envelope",
    },
    narrative:
      "The invoice says the bank details changed. The verified digest does not match. No transaction was sent.",
  },
  {
    id: "att-05",
    invoiceId: "INV-2026-0412",
    payee: SPLIT,
    amountUsdc: "90000000",
    status: "refused",
    createdAt: t(2),
    decision: {
      allow: false,
      source: "authority",
      rule: "daily_cap",
      reason:
        "The fifth of six split invoices. Paying it would make €566.30 today; the daily cap is €500.00.",
    },
    rigorix: {
      executionId: "01a1d567-7a10-7c11-8f22-2c79048aa01b",
      envelopeHash: "0x5b1e9c4a7d2f0b3e6a8c1d5f7b2e4a9c0d3f6b8e1a5c7d9f2b4e6a8c0d3f5b7e",
      envelopeUri: "/api/attempts/att-05/envelope",
    },
    narrative:
      "The fifth of six split invoices from different suppliers. Paying it would make €566.30 today. Your daily cap is €500.00.",
  },
];

// ── approval request ──────────────────────────────────────────────────────

export const INITIAL_APPROVAL: ApprovalRequest = {
  attemptId: "att-03",
  intentDigest: "0x7a3c5e8b1d4f0a6c9e2b5d8f1a4c7e0b3d6a9f2c5e8b1d4f0a6c9e2b5d8f1a4c",
  invoiceId: "INV-2026-0311",
  payee: ZAHNARZT,
  amountUsdc: "240000000",
  nonce: "7",
  deadline: "2026-11-14T14:38:00+01:00",
  eip712: {
    domain: { name: "Bursar", version: "1", chainId: 84532, verifyingContract: "0x4a2f9c1e0b4d7a6f3e2c1b0a9d8e7f6a5c4b3d01" },
    types: {
      PaymentApproval: [
        { name: "intentDigest", type: "bytes32" },
        { name: "invoiceId", type: "bytes32" },
        { name: "payee", type: "address" },
        { name: "amount", type: "uint256" },
        { name: "nonce", type: "uint256" },
        { name: "deadline", type: "uint256" },
      ],
    },
    message: {
      intentDigest: "0x7a3c5e8b1d4f0a6c9e2b5d8f1a4c7e0b3d6a9f2c5e8b1d4f0a6c9e2b5d8f1a4c",
      invoiceId: "0x8c1f0e2d4a6b8c0e2f4a6d8b0c2e4f6a8b0d2e4f6a8c0b2d4e6f8a0c2d4e6f8a",
      payee: "0x2f8a4c11e9b2a7d3c6f0b8e5a1d9c4b7f2e6a308",
      amount: "240000000",
      nonce: "7",
      deadline: "1794644280",
    },
  },
};

// ── presentation ──────────────────────────────────────────────────────────

export interface Visual {
  cover: string;
  big: string;
  glyph: string;
  tag: string;
}

export const VISUALS: Record<string, Visual> = {
  "wien-energie": { cover: "pink", big: "WIEN<br>ENERGIE", glyph: "⚡", tag: "Electricity · March" },
  apotheke: { cover: "green", big: "APOTHEKE<br>HEILIGEN", glyph: "✚", tag: "Pharmacy · today" },
  "zahnarzt-keller": { cover: "blue", big: "ZAHNARZT<br>DR KELLER", glyph: "✳", tag: "New payee · needs you" },
  "split-batch": { cover: "cream", big: "SPLIT<br>INVOICES", glyph: "⌗", tag: "5 of 6 · daily cap" },
  hausmeister: { cover: "cream", big: "HAUSMEISTER<br>SERVICE", glyph: "✳", tag: "Home service · today" },
};

export const DEFAULT_VISUAL: Visual = {
  cover: "cream",
  big: "NEW<br>BILL",
  glyph: "✳",
  tag: "Invoice · today",
};

// ── helpers ───────────────────────────────────────────────────────────────

export const USDC_DP = 6;

export function toUnits(amountUsdc: string): number {
  return Number(amountUsdc) / 10 ** USDC_DP;
}

export function formatAmount(amountUsdc: string, currency: "EUR" | "USDC" = "EUR"): string {
  const n = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(toUnits(amountUsdc));
  return currency === "EUR" ? `€${n}` : `${n} USDC`;
}

export function usdc(amountUsdc: string): string {
  return `${new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(
    toUnits(amountUsdc),
  )} USDC`;
}

export function shortHash(hash: string, head = 6, tail = 4): string {
  if (!hash) return "";
  return `${hash.slice(0, head)}…${hash.slice(-tail)}`;
}

export function sumSettled(attempts: Attempt[]): number {
  return attempts
    .filter((a) => a.status === "settled")
    .reduce((n, a) => n + Number(a.amountUsdc), 0);
}

export function sumCommitted(attempts: Attempt[]): number {
  return attempts
    .filter((a) => a.status === "settled" || a.status === "dispatched")
    .reduce((n, a) => n + Number(a.amountUsdc), 0);
}

export function leftToday(policy: Policy, attempts: Attempt[]): number {
  return Math.max(0, Number(policy.dailyCapUsdc) - sumCommitted(attempts));
}

export function isOpen(attempt: Attempt): boolean {
  return attempt.status === "pending_approval" || attempt.status === "planned" || attempt.status === "allowed";
}

export function timeLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString("de-AT", { hour: "2-digit", minute: "2-digit" });
}

// A representative Rigorix envelope for the demo drawer. The live console
// returns the real bytes from /api/attempts/:id/envelope; this keeps the
// evidence interaction inspectable before the backend is wired.
export function envelopePreview(attempt: Attempt): Record<string, unknown> {
  return {
    execution_id: attempt.rigorix?.executionId ?? "demo-execution",
    producer_id: "rigorix-server",
    timestamp: attempt.createdAt,
    template_id: `pay_${attempt.payee.id}`,
    history_integrity: "local_unanchored",
    precondition_findings: attempt.decision
      ? [
          {
            precondition_id: "payment-authority",
            step: "pay",
            outcome: attempt.decision.allow ? "passed" : "failed",
            inputs_hash: "sha256:56e2956b22e936e7cf155986a2ec916b4ad4302623d1db2d61e7111a1c8a8aa2",
            check_digest: "sha256:91f2a460856849ba22185902392511fd78996126ab6f41bf35a2e2be4a590b7e",
            summary: attempt.decision.reason,
          },
        ]
      : [],
    sequence_findings:
      attempt.decision?.source === "rigorix-plan"
        ? [{ rule_id: attempt.decision.rule, outcome: "denied", step: "pay" }]
        : [],
    signature: "9f2c4a7e1b8d0f3a6c5e2b9d4f7a0c3e6b8d1f5a2c9e4b7d0f3a6c8e1b5d2f4a",
    evidence_degraded: false,
  };
}

export const EMPTY_RESPONSE = {
  household: { name: "The Weiss household", city: "Vienna" },
  mode: CHAIN.mode,
  policy: INITIAL_POLICY,
  attempts: INITIAL_ATTEMPTS,
  chain: CHAIN,
  approval: INITIAL_APPROVAL,
};
