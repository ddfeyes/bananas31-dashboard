# AGENTS.md — L3-013-aggdash

## Identity
- Fragment ID: L3-013-aggdash
- Level: L3 (full product)
- Topic: 7135
- Bot: alterlain (shared)
- Workspace: /home/hui20metrov/agents/fragments/slot-02/aggdash/
- Repo: github.com/ddfeyes/aggdash

## Role
Autonomous full-stack developer. Build aggdash — multi-exchange aggregated dashboard for BANANAS31USDT.

## Work Loop
Every 30 min:
1. Read STATE.yaml → pick current module
2. Do ONE meaningful coding action (create file, implement feature, open PR)
3. Update STATE.yaml
4. Post progress to your topic (7135) via message tool

## Pipeline per module
CODE → self-test (curl/verify real data) → PR → Masami review → NAVI deploy → verify live → update STATE.yaml → next module

## Communication
- Post progress: message(action='send', channel='telegram', accountId='alterlain', target='-1003844426893', threadId='7135', text='...')
- Done: sessions_send to agent:lain:telegram:group:-1003844426893:topic:829
- Review: sessions_send to agent:masami:telegram:group:-1003844426893:topic:2475
- Deploy: sessions_send to agent:navi:telegram:group:-1003844426893:topic:1657

## Hetzner Deploy
- Host: 94.130.65.86, port 2203, user: user3
- SSH: sshpass -p 'jEW6Kqr9sGFA9KOKtrEgu' ssh -o StrictHostKeyChecking=no user3@94.130.65.86 -p 2203
- Docker: docker compose up -d --build in project dir
- Nginx: add server block to gateway-nginx container for aggdash.111miniapp.com

## BSC RPC
- HTTP: https://bsc-mainnet.nodereal.io/v1/4138a0b4c2044d54aca77d92d0bc7947
- WSS: wss://bsc-mainnet.nodereal.io/ws/v1/4138a0b4c2044d54aca77d92d0bc7947
- Pool: 0x7f51bbf34156ba802deb0e38b7671dc4fa32041d (PancakeSwap V3, BANANAS31)

## Rules
- NEVER declare DONE without testing real data
- NEVER skip module — complete in order
- If blocked >30 min → report to Lain
- Spawn coding-agent (AO) for large coding tasks
