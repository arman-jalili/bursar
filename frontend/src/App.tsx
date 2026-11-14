import { useEffect, useState } from "react";
import { Gate } from "./Gate";
import { Precondition } from "./Precondition";
import { clearTrail } from "./agentApi";

type Capability = "capacity" | "precondition";

function currentCapability(): Capability {
  const name = window.location.hash.replace(/^#/, "").split("?")[0];
  return name === "precondition" ? "precondition" : "capacity";
}

export default function App() {
  const [capability, setCapability] = useState<Capability>(currentCapability);
  // A refresh starts a fresh chain: the previous session's evidence is deleted before the page
  // reads the trail, so what you see always belongs to this session. Switching capability in the
  // page (hash change) does not reload the document and keeps the chain.
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let alive = true;
    clearTrail()
      .catch(() => null)
      .finally(() => {
        if (alive) setReady(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const onHash = () => setCapability(currentCapability());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (!ready) return null;
  return capability === "precondition" ? <Precondition /> : <Gate />;
}
