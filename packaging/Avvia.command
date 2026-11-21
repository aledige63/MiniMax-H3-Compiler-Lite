#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
for candidate in python3.12 /opt/homebrew/bin/python3.12 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12; do
    if command -v "$candidate" >/dev/null 2>&1; then
        "$candidate" -X utf8 start.py "$@"
        result=$?
        printf '\nProgramma terminato. Premi Invio per chiudere.\n'
        read -r answer
        exit "$result"
    fi
done
printf 'Python 3.12 non trovato. Installa Python 3.12 per macOS da https://www.python.org/downloads/ e riprova.\n'
read -r -p 'Premi Invio per chiudere. ' answer
exit 1
