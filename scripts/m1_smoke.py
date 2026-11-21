"""Collaudo HTTP reale M1 in archivi temporanei, senza toccare il cut dell'utente."""
import argparse
import hashlib
import json
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api import create_app
from app.interpreter import DEFAULT_TEXT_MODEL, SYSTEM_PROMPT, OllamaClient


class CountingOllama(OllamaClient):
    def __init__(self):
        super().__init__()
        self.compile_calls = 0

    def compile(self, *args, **kwargs):
        self.compile_calls += 1
        return super().compile(*args, **kwargs)


def checked(response, status=200):
    if response.status_code != status:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:400]}")
    return response.json()


def command(cut, **fields):
    return {"command_id": str(uuid4()), "expected_revision": cut["revision"], **fields}


def run_case(case, model):
    client = CountingOllama()
    with tempfile.TemporaryDirectory(prefix="minimax-m1-proof-") as directory:
        path = Path(directory)
        with TestClient(create_app(data_dir=path, client=client), base_url="http://127.0.0.1") as http:
            cut = checked(http.get("/api/workspace"))
            prefix = f"/api/cuts/{cut['id']}"
            units = []
            mapping = {}
            pictures = []
            picture_ids = {}
            for supplied in case["input"]["active_units"]:
                for source in supplied["sources"]:
                    if source["picture_slot"] in picture_ids:
                        continue
                    cut = checked(http.post(prefix + "/items", json=command(cut, kind="picture")))
                    picture_id = cut["draft_input"]["pictures"][-1]["id"]
                    picture_ids[source["picture_slot"]] = picture_id
                    description = {"outfit": "the supplied outfit", "shoes": "the supplied footwear"}.get(source["attribute"], supplied["description_en"])
                    pictures.append({"id": picture_id, "slot": source["picture_slot"], "name": f"Picture {source['picture_slot']}",
                                     "role": source["attribute"], "description_en": description, "confirmed": True, "linked_to_h3": True})
                cut = checked(http.post(prefix + "/items", json=command(cut, kind="unit")))
                allocated = cut["draft_input"]["active_units"][-1]["subject"]
                mapping[supplied["subject"]] = allocated
                units.append({**supplied, "subject": allocated, "sources": [
                    {"picture_id": picture_ids[s["picture_slot"]], "attribute": s["attribute"]} for s in supplied["sources"]]})
            dialogues = []
            ids = {}
            for supplied in case["input"].get("dialogues", []):
                cut = checked(http.post(prefix + "/items", json=command(cut, kind="dialogue")))
                allocated = cut["draft_input"]["dialogues"][-1]["id"]
                ids[supplied["id"]] = allocated
                dialogues.append({**supplied, "id": allocated,
                                  "speaker_subject": mapping[supplied["speaker_subject"]]})
            request = re.sub(r"<Subject (\d+)>", lambda m: f"<Subject {mapping[int(m[1])]}>" , case["input"]["request"])
            # Gli ID vengono allocati dal server; nel set dichiarato restano d1/d2.
            assert all(key == value for key, value in ids.items())
            draft = {**case["input"], "request": request, "pictures": pictures, "active_units": units, "dialogues": dialogues}
            cut = checked(http.put(prefix + "/draft", json=command(cut, input=draft)))
            payload = command(cut, cut_id=cut["id"], input=draft, model=model)
            job = checked(http.post(prefix + "/compile", json=payload), 202)
            duplicate = checked(http.post(prefix + "/compile", json=payload), 202)
            assert duplicate["id"] == job["id"], "Retry HTTP non idempotente"
            deadline = time.monotonic() + 150
            while job["status"] in {"queued", "running"}:
                if time.monotonic() > deadline:
                    raise RuntimeError("Job non completato entro il limite di collaudo")
                time.sleep(.05)
                job = checked(http.get(f"/api/jobs/{job['id']}"))
            assert job["result"]["status"] == "proposal", job["result"]
            assert job["result"]["confirmation_allowed"], job["result"]["issues"]
            cut = checked(http.get("/api/workspace"))
            generated = next(v for v in cut["versions"] if v["id"] == job["candidate_id"])
            original = http.get(prefix + "/text", params={"version_id": generated["id"]}).text
            assert original == generated["text"]
            manual_text = generated["text"] + "\n\n  "
            cut = checked(http.put(prefix + "/manual", json=command(
                cut, text=manual_text, base_candidate_id=generated["id"])))
            manual_id = cut["manual_version_id"]
            copied = http.get(prefix + "/text", params={"version_id": manual_id})
            assert copied.status_code == 200 and copied.text == manual_text, "Testo manuale modificato"
            assert client.compile_calls == 1, "Operazione non AI ha chiamato il compilatore"
        with TestClient(create_app(data_dir=path, client=client), base_url="http://127.0.0.1") as reopened:
            saved = checked(reopened.get("/api/workspace"))
            assert saved["manual_version_id"] == manual_id
            text = reopened.get(prefix + "/text", params={"version_id": manual_id}).text
            assert text == manual_text
            assert client.compile_calls == 1
        return {"case": case["id"], "input": draft, "job": job,
                "workflow_checks": {"http_duplicate_same_job": True, "manual_text_exact": True,
                                    "copy_and_reopen_exact": True, "total_compile_calls": client.compile_calls}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_TEXT_MODEL)
    parser.add_argument("--output", type=Path, default=Path("benchmark-runs/m1-http.json"))
    args = parser.parse_args()
    fixtures = json.loads(Path("tests/fixtures/m0_cases.json").read_text())
    a01 = fixtures[0]
    units = fixtures[2]["input"]["active_units"]
    d1 = {**fixtures[0]["input"]["dialogues"][0], "text": "Ho finito."}
    cases = [a01, {"id": "A02", "input": {"request": "<Subject 1> pronuncia d1. Solo dopo la fine della battuta, sorride e guarda verso la porta.",
                                          "active_units": units, "dialogues": [d1]}},
             {"id": "A04", "input": {"request": "<Subject 2> pronuncia d2 per primo. Dopo la fine della sua battuta, <Subject 1> risponde con d1. Nessun altro gesto.",
                                      "active_units": a01["input"]["active_units"],
                                      "dialogues": [d1, {**d1, "id": "d2", "speaker_subject": 2, "text": "Tocca a te."}]}}]
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "model": args.model,
              "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(), "runs": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        run = run_case(case, args.model)
        report["runs"].append(run)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        m = run["job"]["result"]["metrics"]
        print(f"{case['id']}: HTTP/edit/copia/riapertura OK, {m['wall_s']:.2f}s, {m['prompt_tokens']} token input", flush=True)
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
