// The independent block explorer (Blockscout over the demo's Anvil chain, see explorer/blockscout).
// Every hash the gate reports links here, so the wallet and the USDC movement are inspectable
// outside this app.

export const EXPLORER_URL =
  (import.meta.env.VITE_EXPLORER_URL as string | undefined) ?? "http://localhost:4000";

export function explorerUrl(path: string): string {
  return `${EXPLORER_URL.replace(/\/$/, "")}${path}`;
}

export function txUrl(hash: string | null | undefined): string | null {
  return hash ? explorerUrl(`/tx/${hash}`) : null;
}

export function addressUrl(address: string | null | undefined): string | null {
  return address ? explorerUrl(`/address/${address}`) : null;
}

export function tokenUrl(address: string | null | undefined): string | null {
  return address ? explorerUrl(`/token/${address}`) : null;
}
