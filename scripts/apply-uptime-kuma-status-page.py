#!/usr/bin/env python3
"""Apply Socrat Uptime Kuma public status page branding to a kuma.db file.

Usage on the Uptime Kuma host:
  sudo python3 scripts/apply-uptime-kuma-status-page.py \
    --db /srv/uptime-kuma/kuma.db \
    --css charts/uptime-kuma/status-page/socrat-status.css \
    --icon charts/uptime-kuma/status-page/socrat-avatar.png
"""

from __future__ import annotations

import argparse
import base64
import pathlib
import sqlite3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="/srv/uptime-kuma/kuma.db")
    parser.add_argument("--slug", default="socrat")
    parser.add_argument("--title", default="Socrat Status")
    parser.add_argument("--domain", default="status.alchemmist.xyz")
    parser.add_argument("--css", required=True)
    parser.add_argument("--icon", required=True)
    args = parser.parse_args()

    css = pathlib.Path(args.css).read_text()
    icon_bytes = pathlib.Path(args.icon).read_bytes()
    icon_data_uri = "data:image/png;base64," + base64.b64encode(icon_bytes).decode()

    con = sqlite3.connect(args.db)
    try:
        con.execute(
            """
            UPDATE status_page
               SET title = ?,
                   description = '',
                   icon = ?,
                   theme = 'light',
                   show_powered_by = 0,
                   footer_text = '',
                   custom_css = ?,
                   modified_date = CURRENT_TIMESTAMP
             WHERE slug = ?
            """,
            (args.title, icon_data_uri, css, args.slug),
        )
        status_page_id = con.execute("SELECT id FROM status_page WHERE slug = ?", (args.slug,)).fetchone()[0]
        con.execute(
            """
            INSERT INTO status_page_cname(status_page_id, domain)
            VALUES(?, ?)
            ON CONFLICT(domain) DO UPDATE SET status_page_id = excluded.status_page_id
            """,
            (status_page_id, args.domain),
        )
        con.commit()
        row = con.execute(
            "SELECT slug, title, length(icon), theme, show_powered_by, length(custom_css) FROM status_page WHERE slug = ?",
            (args.slug,),
        ).fetchone()
        cname = con.execute(
            "SELECT domain FROM status_page_cname WHERE status_page_id = ? ORDER BY domain",
            (status_page_id,),
        ).fetchall()
        print(row)
        print(cname)
    finally:
        con.close()


if __name__ == "__main__":
    main()
