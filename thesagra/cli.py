import argparse
import os

from .query.engine import RelationalEngine, QueryError
from .query.parser import ParseError, parse, split_sql_statements
from .storage.database import DatabaseFile


def execute_script(engine: RelationalEngine, script: str):
    result = None
    for statement_text in split_sql_statements(script):
        statement = parse(statement_text)
        result = engine.execute(statement)
    return result


def print_result(result):
    if result.columns:
        print(" | ".join(result.columns))
        print("-+-".join("-" * len(column) for column in result.columns))
    for row in result.rows:
        print(" | ".join("" if value is None else str(value) for value in row))
    if not result.columns and result.rowcount:
        print(f"{result.rowcount} row(s)")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="thesagra",
        description="THESAGRA local SQL prototype",
    )
    parser.add_argument(
        "database",
        nargs="?",
        default="thesagra.db",
        help="database file path",
    )
    parser.add_argument(
        "-c",
        "--command",
        help="execute one SQL statement and exit",
    )
    parser.add_argument(
        "-f",
        "--file",
        help="execute SQL statements from a file",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="start a THESAGRA TCP server",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5439)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--password-hash")
    parser.add_argument(
        "--hash-password",
        metavar="PASSWORD",
        help="print a PBKDF2 password hash and exit",
    )
    parser.add_argument("--tls-cert")
    parser.add_argument("--tls-key")
    parser.add_argument(
        "--data-dir",
        help=(
            "enable named multi-database mode using this directory "
            "for system metadata and database files"
        ),
    )
    parser.add_argument("--backup", metavar="DESTINATION")
    parser.add_argument("--restore", metavar="BACKUP")
    parser.add_argument("--integrity", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument(
        "--gui",
        action="store_true",
        help="open the Tkinter SQL console",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="start the browser Web GUI",
    )
    parser.add_argument("--web-port", type=int, default=8080)
    args = parser.parse_args(argv)
    if args.data_dir and not args.serve:
        parser.error("--data-dir is currently supported with --serve only")

    if args.hash_password:
        from .security import hash_password

        print(hash_password(args.hash_password))
        return

    if args.web:
        from .web import THESAGRAWebServer

        with THESAGRAWebServer(
            args.database,
            host=args.host,
            port=args.web_port,
            username=args.username,
            password=args.password,
            password_hash=args.password_hash,
            tls_cert=args.tls_cert,
            tls_key=args.tls_key,
        ) as server:
            print(
                f"THESAGRA Web GUI at "
                f"http://{args.host}:{args.web_port}/"
            )
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
        return

    if args.gui:
        from .gui import main as gui_main

        gui_main()
        return

    if args.backup:
        from .operations import backup_database

        print(backup_database(args.database, args.backup))
        return
    if args.restore:
        from .operations import restore_database

        print(restore_database(args.restore, args.database))
        return
    if args.integrity:
        from .operations import integrity_check

        print(integrity_check(args.database))
        return

    if args.serve:
        from .server.server import THESAGRAServer

        with THESAGRAServer(
            args.database,
            host=args.host,
            port=args.port,
            username=args.username,
            password=args.password,
            password_hash=args.password_hash,
            tls_cert=args.tls_cert,
            tls_key=args.tls_key,
            database_directory=args.data_dir,
        ) as server:
            print(
                f"THESAGRA listening on "
                f"{server.server_address[0]}:{server.server_address[1]}"
            )
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
        return

    exists = os.path.isfile(args.database)
    database = (
        DatabaseFile.open(args.database)
        if exists
        else DatabaseFile.create(args.database)
    )
    engine = RelationalEngine(database)
    if args.worker:
        from .workers.worker import Worker

        worker = Worker(engine)
        worker.start()
        print("THESAGRA worker started.")
        try:
            import time

            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            worker.stop()
        return

    try:
        if args.command:
            print_result(engine.execute(parse(args.command)))
            return
        if args.file:
            with open(args.file, "r", encoding="utf-8") as sql_file:
                result = execute_script(engine, sql_file.read())
            if result is not None:
                print_result(result)
            return

        print("THESAGRA local prototype. Enter SQL; use .exit to quit.")
        while True:
            try:
                sql = input("thesagra> ").strip()
            except EOFError:
                break
            if sql.lower() in (".exit", ".quit"):
                break
            if not sql:
                continue
            try:
                result = execute_script(engine, sql)
                if result is not None:
                    print_result(result)
            except (ParseError, QueryError) as exc:
                print(f"Error: {exc}")
    except (ParseError, QueryError, OSError) as exc:
        print(f"Error: {exc}")


if __name__ == "__main__":
    main()
