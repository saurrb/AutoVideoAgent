from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / 'src'
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autovideo.services.state_store import connect
from autovideo.services.content_provider import import_excel_to_db


def main() -> None:
    ap = argparse.ArgumentParser(description='Import content Excel into SQLite content_bank_rows table.')
    ap.add_argument('--page', required=True)
    ap.add_argument('--xlsx', required=True)
    ap.add_argument('--sheet', default='Sheet1')
    ap.add_argument('--db', default='')
    args = ap.parse_args()

    root = PROJECT_ROOT
    xlsx = Path(args.xlsx)
    if not xlsx.is_absolute():
        xlsx = (root / xlsx).resolve()

    db_path = Path(args.db).resolve() if args.db else (root / 'pages' / args.page / 'data' / 'state.sqlite3')
    conn = connect(db_path)
    count = import_excel_to_db(conn=conn, page_key=args.page, xlsx_path=xlsx, sheet_name=args.sheet)
    print(f'PAGE={args.page}')
    print(f'DB={db_path}')
    print(f'XLSX={xlsx}')
    print(f'IMPORTED_ROWS={count}')


if __name__ == '__main__':
    main()
