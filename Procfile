web: uvicorn src.app:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers --forwarded-allow-ips=*
migrate: python -m src.db.migrate
resync: python -m src.jobs.account_resync
backup: python -m src.jobs.backup
