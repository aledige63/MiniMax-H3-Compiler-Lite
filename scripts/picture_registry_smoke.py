"""Collaudo del catalogo Picture con Ollama reale e archivi temporanei."""
import argparse
import hashlib
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api import create_app
from app.interpreter import SYSTEM_PROMPT
from scripts.m1_smoke import CountingOllama, checked, command


def run_case(raw, expect_conflict=False):
    client = CountingOllama()
    with tempfile.TemporaryDirectory(prefix="h3-picture-proof-") as directory:
        with TestClient(create_app(data_dir=Path(directory), client=client), base_url="http://127.0.0.1") as http:
            cut = checked(http.get("/api/workspace"))
            prefix = f"/api/cuts/{cut['id']}"
            mapping = {}
            for picture in raw["pictures"]:
                cut = checked(http.post(prefix + "/items", json=command(cut, kind="picture")))
                mapping[picture["id"]] = cut["draft_input"]["pictures"][-1]["id"]
            for unit in raw["active_units"]:
                cut = checked(http.post(prefix + "/items", json=command(cut, kind="unit")))
                assert cut["draft_input"]["active_units"][-1]["subject"] == unit["subject"]
            raw = json.loads(json.dumps(raw))
            for picture in raw["pictures"]:
                picture["id"] = mapping[picture["id"]]
            for unit in raw["active_units"]:
                for source in unit["sources"]:
                    source["picture_id"] = mapping[source["picture_id"]]
            cut = checked(http.put(prefix + "/draft", json=command(cut, input=raw)))
            payload = command(cut, cut_id=cut["id"], input=raw)
            response = http.post(prefix + "/compile", json=payload)
            if expect_conflict:
                assert response.status_code == 422, response.text
                assert client.compile_calls == 0
                return {"input": raw, "blocked_before_inference": True, "response": response.json()}
            job = checked(response, 202)
            repeat = checked(http.post(prefix + "/compile", json=payload), 202)
            assert repeat["id"] == job["id"]
            deadline = time.monotonic() + 150
            while job["status"] in {"queued", "running"}:
                if time.monotonic() > deadline:
                    raise RuntimeError("Collaudo scaduto")
                time.sleep(.05)
                job = checked(http.get(f"/api/jobs/{job['id']}"))
            assert job["result"]["status"] == "proposal", job
            assert job["result"]["confirmation_allowed"], job
            assert client.compile_calls == 1
            result = job["result"]
            return {"input": raw, "result": result, "compile_calls_including_http_retry": client.compile_calls}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("benchmark-runs/picture-registry.json"))
    args = parser.parse_args()
    pictures = [{"id": "face", "slot": 1, "name": "Ann", "role": "identity",
                 "description_en": "a young woman with long brown hair", "confirmed": True, "linked_to_h3": True},
                {"id": "skirt", "slot": 2, "name": "Gonna", "role": "outfit",
                 "description_en": "a black miniskirt", "confirmed": True, "linked_to_h3": True}]
    unit = {"subject": 1, "name": "Ann", "role": "character", "description_en": "Ann", "confirmed": True,
            "sources": [{"picture_id": "face", "attribute": "identity"}, {"picture_id": "skirt", "attribute": "outfit"}]}
    ann = {"request": "<Subject 1> entra e si ferma.", "pictures": pictures, "active_units": [unit], "declared_duration_s": 5.0}
    shared = {"request": "<Subject 2> saluta con la mano. <Subject 1> rimane immobile.",
              "pictures": [{**pictures[0], "description_en": "two women standing side by side"}], "declared_duration_s": 5.0,
              "active_units": [{**unit, "description_en": "Ann, the woman on the left", "sources": unit["sources"][:1]},
                               {**unit, "subject": 2, "name": "Beth", "description_en": "Beth, the woman on the right", "sources": unit["sources"][:1]}]}
    conflict = json.loads(json.dumps(ann))
    conflict["pictures"][1]["slot"] = 1
    report = {"started_utc": datetime.now(timezone.utc).isoformat(),
              "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(), "runs": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for label, raw, blocked in [("A07-Ann-and-skirt", ann, False), ("shared-picture-two-subjects", shared, False),
                                ("distinct-images-same-slot", conflict, True)]:
        result = run_case(raw, blocked)
        report["runs"].append({"case": label, **result})
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(label, "blocked before LLM" if blocked else result["result"]["interpretation"], flush=True)
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
