"""Server administration commands (not exposed in the app).

  python manage.py backup                 make a full backup now
  python manage.py backups                list backups
  python manage.py restore FILE           restore a full backup (with the server STOPPED)
  python manage.py users                  list users and families
"""
import os
import shutil
import sqlite3
import sys

import backup
import db


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == 'backup':
        print('Created:', backup.create_backup('manual'))
    elif cmd == 'backups':
        for b in backup.list_backups():
            print(f"{b['created_at']}  {b['size'] // 1024:>6} KB  {b['name']}")
    elif cmd == 'restore' and len(argv) == 3:
        source = backup.backup_path(argv[2]) or argv[2]
        # Fails early if the file is not an SQLite database
        sqlite3.connect(f'file:{source}?mode=ro', uri=True).execute('SELECT name FROM sqlite_master LIMIT 1')
        print('Safety copy:', backup.create_backup('pre-restore'))
        shutil.copyfile(source, db.DB_PATH)
        for ext in ('-wal', '-shm'):
            try:
                os.remove(db.DB_PATH + ext)
            except FileNotFoundError:
                pass
        db.init_db()  # also upgrades backups made with older versions
        print('Restored from', source)
    elif cmd == 'users':
        conn = db.connect()
        for r in conn.execute('''SELECT u.email, u.name, u.email_verified, f.name AS family, m.role FROM users u
                                 LEFT JOIN members m ON m.user_id = u.id LEFT JOIN families f ON f.id = m.family_id ORDER BY f.id'''):
            print(f"{r['email']:<35} {r['name']:<20} {'✓' if r['email_verified'] else ' '}  {r['family'] or '-'} ({r['role'] or '-'})")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
