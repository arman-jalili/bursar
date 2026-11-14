// Compile the settlement contracts with solc-js so the artifact is architecture-independent.
// Native solc binaries are x86_64-only; solc-js runs on any Node platform (the demo host is arm64).
import fs from "node:fs";
import solc from "solc";

const files = ["TestUsdc.sol", "PaymentRouter.sol"];
const sources = Object.fromEntries(
  files.map((name) => [name, { content: fs.readFileSync(`/contracts/src/${name}`, "utf8") }]),
);

const input = {
  language: "Solidity",
  sources,
  settings: {
    optimizer: { enabled: true, runs: 200 },
    evmVersion: "paris",
    outputSelection: { "*": { "*": ["abi", "evm.bytecode.object"] } },
  },
};

const output = JSON.parse(solc.compile(JSON.stringify(input)));
for (const error of output.errors ?? []) {
  if (error.severity === "error") throw new Error(error.formattedMessage);
}

const artifacts = {};
for (const contracts of Object.values(output.contracts)) {
  for (const [name, contract] of Object.entries(contracts)) {
    artifacts[name] = { abi: contract.abi, bin: contract.evm.bytecode.object };
  }
}

fs.mkdirSync("/out", { recursive: true });
fs.writeFileSync("/out/contracts.json", JSON.stringify(artifacts, null, 2));
console.log(`compiled: ${Object.keys(artifacts).join(", ")}`);
