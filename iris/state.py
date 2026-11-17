"""Šifrovanje stanja za javni GitHub repo (razgovor ne sme da bude čitljiv).

  python3 -m iris.state unpack   # pre pokretanja: iris.db.enc -> iris.db
  python3 -m iris.state pack     # posle: iris.db -> iris.db.enc
  python3 -m iris.state keygen   # novi ključ za STATE_KEY
"""
from __future__ import annotations

import sys

from cryptography.fernet import Fernet, InvalidToken

from . import config

ENC = config.BASE / "iris.db.enc"


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "keygen":
        print(Fernet.generate_key().decode())
        return
    if not config.STATE_KEY:
        raise SystemExit("STATE_KEY nije podešen - stanje se ne čuva")
    f = Fernet(config.STATE_KEY.encode())
    if cmd == "pack" and config.DB_PATH.exists():
        ENC.write_bytes(f.encrypt(config.DB_PATH.read_bytes()))
        print("stanje sačuvano")
    elif cmd == "unpack" and ENC.exists():
        try:
            config.DB_PATH.write_bytes(f.decrypt(ENC.read_bytes()))
            print("stanje učitano")
        except InvalidToken:  # pogrešan ključ: počinjemo prazno umesto da obaramo ceo ciklus
            print("UPOZORENJE: stanje se ne može dešifrovati (pogrešan STATE_KEY?), počinjem prazno")
    else:
        print("nema šta da se radi")


if __name__ == "__main__":
    main()
