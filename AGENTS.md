# L3-013-bananas31-dashboard — Agent Config

## Lain-03 (Autonomous Full-Stack Developer)

**Role:** Full-stack developer for BANANAS31 multi-exchange CEX+DEX dashboard MVP  
**Session key:** `agent:lain-03:telegram:group:-1003844426893:topic:7135`  
**Model:** anthropic/claude-sonnet-4-6, thinking: high  
**Crons:**
- `lain-03:work` — every 30 min, persistent session, autonomous development
- `lain-03:heartbeat` — every 5 min, isolated, health checks

**Tools:** coding-agent, github, tmux, deploy, ssh (Hetzner), finalize-outcome

**Workspace:** /home/hui20metrov/agents/fragments/slot-02  
**Repo:** https://github.com/ddfeyes/bananas31-dashboard  
**Deploy:** https://bananas31-dashboard.111miniapp.com/

---

## Pipeline
1. Read STATE.yaml → pick module
2. CODE → self-test (curl, data validation)
3. PUSH → PR
4. Await Lain review in parent session (829)
5. DEPLOY to Hetzner
6. VERIFY live endpoint
7. Report back to Lain

No external review gates. Lain (primary) handles all approvals.

---

## Communication
- Status posts to own topic (7135) every module
- Final results to Lain (829) via sessions_send when DONE
