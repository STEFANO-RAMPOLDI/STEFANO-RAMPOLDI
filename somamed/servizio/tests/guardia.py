"""I collaudi scrivono dati inventati: girano solo su un database di prova, mai su quello vero."""
import os, sys
dsn = os.environ.get("CRM_DSN", "")
if not dsn or dsn.rstrip("/").endswith("/somamed_crm"):
    sys.exit("I collaudi vanno lanciati su un database di prova, es.: "
             "CRM_DSN=postgresql://crm:crm@localhost:5433/somamed_test python3 tests/test_mcp.py")
