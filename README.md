# defense-logistics

Operational Observability for Defense Resource Networks

Logistics reports from people, sensors, and warehouses are messy, stale, duplicated, or wrong. This project turns those reports (various file types) into one view of the network: what the recovered state is, which reports are inconsistent, and when there is not enough information to know.

## Status

Early port. Currently includes:

- `world.json` — a small synthetic supply network (sites, transfers, true final stock)
- `claims.py` — generates `claims.json` from the world, with honest noise and `k` planted corruptions

```bash
pip install -r requirements.txt
cp .env.example .env
python claims.py 2 0     # k=2 corrupted claims, seed 0
```
