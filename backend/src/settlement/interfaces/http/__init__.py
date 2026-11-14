"""HTTP binding for the Settlement context (FastAPI router + request/response schemas).

The handlers are concrete by design (see `docs/contracts/settlement-contract-freeze.md` §2.11): there is
no "controller interface" file, because an interface over a router is a second contract that can drift
from the one clients actually call.
"""
