import subprocess


def backup_database(db_name: str, dest_dir: str) -> None:
    cmd = f"pg_dump {db_name} > {dest_dir}/{db_name}.sql"
    subprocess.run(cmd, shell=True, check=True)
