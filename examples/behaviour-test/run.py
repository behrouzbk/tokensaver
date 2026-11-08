"""Behaviour test: does the cleaned support-bot prompt behave like the original?

Runs every case in cases.json against two system prompts (A = original, B = cleaned)
with the same tools and model, several times each, and reports pass rates per case.

    pip install anthropic
    python run.py --dry-run          # no API calls: checks cases, tools and graders
    python run.py                    # the real run (calls the Anthropic API)

This script calls a model API, so it lives outside the tokensaver package: tokensaver
itself never makes network calls. Credentials come from ANTHROPIC_API_KEY or an
`ant auth login` profile.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).parent
PROMPTS = {"A": HERE / "prompt_original.txt", "B": HERE / "prompt_cleaned.txt"}
TOOLS_FILE = HERE.parent / "tools.json"
CASES_FILE = HERE / "cases.json"

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_JUDGE = "claude-haiku-5-5"
MAX_TOOL_ROUNDS = 5
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

# Prices per 1M tokens (input, output), for the cost line only. Checked 2026-11-07.
PRICES = {"claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}


# --- tools -------------------------------------------------------------------


def anthropic_tools(openai_tools: list[dict]) -> list[dict]:
    """OpenAI-format tools to Anthropic format, with the same names and wording."""
    out = []
    for tool in openai_tools:
        fn = tool["function"]
        out.append(
            {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return out


def fake_tool(name: str, args: dict, orders: dict) -> str:
    """Fixed tool results, so every run sees the same data."""
    order = orders.get(str(args.get("order_id", "")).strip().upper())
    if name == "get_order_status":
        return json.dumps(order if order else {"error": "order not found"})
    if name == "create_refund":
        if not order:
            return json.dumps({"error": "order not found"})
        return json.dumps(
            {"refund_id": "R-5521", "order_id": order["order_id"], "status": "started"}
        )
    return json.dumps({"error": f"unknown tool {name}"})


# --- one conversation ----------------------------------------------------------


@dataclass
class Conversation:
    case_id: str
    arm: str
    run: int
    reply: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)
    stop_reason: str = ""
    error: str = ""
    usage: dict = field(default_factory=lambda: {"input": 0, "output": 0})


def _text(content) -> str:
    return "\n".join(b.text for b in content if b.type == "text").strip()


def _add_usage(conv: Conversation, usage) -> None:
    conv.usage["input"] += (
        usage.input_tokens
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        + (getattr(usage, "cache_read_input_tokens", 0) or 0)
    )
    conv.usage["output"] += usage.output_tokens


def run_conversation(client, model, system, tools, case, orders, arm, run) -> Conversation:
    conv = Conversation(case_id=case["id"], arm=arm, run=run)
    messages: list = []
    try:
        for turn in case["turns"]:
            messages.append({"role": "user", "content": turn})
            conv.transcript.append({"role": "user", "text": turn})
            for _ in range(MAX_TOOL_ROUNDS + 1):
                response = client.messages.create(
                    model=model,
                    max_tokens=4000,
                    system=system,
                    tools=tools,
                    output_config={"effort": "low"},
                    messages=messages,
                )
                _add_usage(conv, response.usage)
                conv.stop_reason = response.stop_reason
                messages.append({"role": "assistant", "content": response.content})
                text = _text(response.content)
                if text:
                    conv.transcript.append({"role": "assistant", "text": text})
                if response.stop_reason == "refusal":
                    return conv
                calls = [b for b in response.content if b.type == "tool_use"]
                if response.stop_reason != "tool_use" or not calls:
                    conv.reply = text
                    break
                results = []
                for call in calls:
                    result = fake_tool(call.name, call.input, orders)
                    conv.tool_calls.append({"name": call.name, "input": call.input})
                    conv.transcript.append(
                        {"role": "tool", "name": call.name, "input": call.input, "result": result}
                    )
                    results.append(
                        {"type": "tool_result", "tool_use_id": call.id, "content": result}
                    )
                messages.append({"role": "user", "content": results})
    except Exception as error:  # recorded, never counted as a pass
        conv.error = f"{type(error).__name__}: {error}"
    return conv


# --- checks in code ----------------------------------------------------------------


def _json_objects(text: str) -> list[dict]:
    decoder, found = json.JSONDecoder(), []
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            found.append(value)
    return found


def _sentences(text: str) -> int:
    prose = re.sub(r"```.*?```", " ", text, flags=re.S)
    prose = re.sub(r"\{.*?\}", " ", prose, flags=re.S)
    prose = re.sub(r"^\s*[-*\d.]+\s+", "", prose, flags=re.M)  # list markers
    parts = re.split(r"(?<=[.!?])\s+|\n+", prose)
    return sum(1 for p in parts if re.search(r"[A-Za-z]{2,}", p))


def run_check(check: dict, conv: Conversation) -> tuple[bool, str]:
    reply, called = conv.reply, [c["name"] for c in conv.tool_calls]
    kind = check["type"]
    if kind == "no_tool":
        ok = check["tool"] not in called
        return ok, f"{check['tool']} {'not called' if ok else 'was called'}"
    if kind == "tool_called":
        ok = check["tool"] in called
        return ok, f"{check['tool']} {'called' if ok else 'not called'}"
    if kind == "no_dates":
        extra = sorted(set(DATE.findall(reply)) - set(check.get("allowed", [])))
        return not extra, f"dates not in the data: {extra}" if extra else "no invented dates"
    if kind == "json_order":
        want = check["fields"]
        for obj in _json_objects(reply):
            if all(str(obj.get(k)) == v for k, v in want.items()):
                return True, "JSON order object found"
        return False, "no JSON object with the order's fields"
    if kind == "no_script":
        lo, hi = int(check["start"], 16), int(check["end"], 16)
        ok = not any(lo <= ord(ch) <= hi for ch in reply)
        return ok, f"{'no' if ok else 'contains'} {check['name']} text"
    if kind == "not_contains":
        ok = not re.search(check["pattern"], reply)
        return ok, "forbidden text absent" if ok else "forbidden text present"
    if kind == "max_sentences":
        n = _sentences(reply)
        return n <= check["max"], f"{n} sentences (max {check['max']})"
    raise ValueError(f"Unknown check type: {kind}")


# --- judge -------------------------------------------------------------------------

JUDGE_SYSTEM = (
    "You grade replies from a customer-support chatbot for an online electronics store. "
    "Answer each question about the bot's final reply with true or false, and give a "
    "one-sentence reason. Judge only what the reply says, not whether you like its style."
)


def judge(client, model, case: dict, conv: Conversation) -> list[dict]:
    questions = case["judge"]
    if not questions:
        return []
    lines = [f"Customer: {t['text']}" if t["role"] == "user" else None for t in conv.transcript]
    shown = "\n".join(line for line in lines if line)
    tools = "; ".join(f"{c['name']}({json.dumps(c['input'])})" for c in conv.tool_calls) or "none"
    prompt = (
        f"Customer messages:\n{shown}\n\nTools the bot called: {tools}\n\n"
        f"Bot's final reply:\n<reply>\n{conv.reply}\n</reply>\n\nQuestions:\n"
        + "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
    )
    # One required property per question, so the judge cannot skip or merge answers.
    item = {
        "type": "object",
        "properties": {"answer": {"type": "boolean"}, "reason": {"type": "string"}},
        "required": ["answer", "reason"],
        "additionalProperties": False,
    }
    keys = [f"q{i + 1}" for i in range(len(questions))]
    schema = {
        "type": "object",
        "properties": dict.fromkeys(keys, item),
        "required": keys,
        "additionalProperties": False,
    }
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=JUDGE_SYSTEM,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    )
    conv.usage.setdefault("judge_input", 0)
    conv.usage.setdefault("judge_output", 0)
    conv.usage["judge_input"] += response.usage.input_tokens
    conv.usage["judge_output"] += response.usage.output_tokens
    data = json.loads(_text(response.content))
    missing = [k for k in keys if k not in data]
    if missing:
        raise ValueError(f"Judge skipped {', '.join(missing)}")
    return [
        {"question": q, "answer": data[k]["answer"], "reason": data[k]["reason"]}
        for q, k in zip(questions, keys, strict=True)
    ]


# --- grading and report ---------------------------------------------------------------


def grade(client, judge_model, case, conv) -> dict:
    if conv.error:
        return {"outcome": "error", "detail": conv.error}
    if conv.stop_reason == "refusal":
        return {"outcome": "refusal", "detail": "the model declined"}
    checks = [dict(zip(("ok", "detail"), run_check(c, conv), strict=True)) for c in case["checks"]]
    try:
        verdicts = judge(client, judge_model, case, conv)
    except Exception as error:
        return {"outcome": "error", "detail": f"judge: {error}", "checks": checks}
    passed = all(c["ok"] for c in checks) and all(v["answer"] for v in verdicts)
    return {"outcome": "pass" if passed else "fail", "checks": checks, "judge": verdicts}


def cost(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


def summarize(cases, results, runs, model, judge_model) -> str:
    lines = [
        "# Behaviour test results",
        "",
        f"Model: `{model}` (effort low). Judge: `{judge_model}`. {runs} runs per case and prompt.",
        "A = original prompt (431 tokens), B = cleaned prompt (310 tokens).",
        "",
        "| Case | A passes | B passes | Note |",
        "|---|---:|---:|---|",
    ]
    drops = []
    for case in cases:
        counts = {}
        for arm in ("A", "B"):
            rows = [r for r in results if r["case_id"] == case["id"] and r["arm"] == arm]
            counts[arm] = sum(r["grade"]["outcome"] == "pass" for r in rows)
            other = [
                r["grade"]["outcome"] for r in rows if r["grade"]["outcome"] in ("error", "refusal")
            ]
            counts[arm + "_other"] = other
        note = ""
        if counts["B"] < counts["A"] - 1:
            note = "**B worse**"
            drops.append(case["id"])
        elif counts["A"] < counts["B"] - 1:
            note = "B better"
        extra = counts["A_other"] + counts["B_other"]
        if extra:
            note = (note + " " if note else "") + f"({len(extra)} error/refusal)"
        lines.append(f"| {case['title']} | {counts['A']}/{runs} | {counts['B']}/{runs} | {note} |")
    verdict = (
        "The cleaned prompt kept its behaviour: no case dropped by more than one run."
        if not drops
        else f"The cleaned prompt did worse on: {', '.join(drops)}. See the transcripts."
    )
    tokens = {
        k: sum(r["usage"].get(k, 0) for r in results)
        for k in ("input", "output", "judge_input", "judge_output")
    }
    total = cost(model, tokens["input"], tokens["output"]) + cost(
        judge_model, tokens["judge_input"], tokens["judge_output"]
    )
    lines += [
        "",
        verdict,
        "",
        f"Tokens: bot {tokens['input']:,} in / {tokens['output']:,} out; "
        f"judge {tokens['judge_input']:,} in / {tokens['judge_output']:,} out. "
        f"Estimated cost: ${total:.2f}.",
    ]
    return "\n".join(lines) + "\n"


# --- dry run ---------------------------------------------------------------------------


def dry_run(cases, tools, orders) -> None:
    """Validate the setup without calling any API."""
    for name, path in PROMPTS.items():
        print(f"Prompt {name}: {path.name}, {len(path.read_text(encoding='utf-8'))} characters")
    print(f"Tools: {[t['name'] for t in tools]}")
    print(f"Cases: {len(cases)}")
    fake = Conversation("x", "A", 0)
    samples = {
        "1-missing-order-number": "Could you share your order number so I can check it?",
        "2-order-lookup-json": 'Here it is: {"order_id": "A-10293", "status": "shipped", '
        '"estimated_delivery": "2026-11-12", "items": [{"name": "USB-C charger", "quantity": 1}]}',
        "6-punjabi-user": "Could you share your order number?",
        "7-full-card-number": "Refunds go to the original payment method.",
        "8-other-customer-data": "Sorry, I can't share details of another customer's order.",
        "9-short-shipping-answer": "Standard shipping takes 3 to 5 business days.",
    }
    for case in cases:
        for check in case["checks"]:
            fake.reply = samples.get(case["id"], "A short reply.")
            fake.tool_calls = (
                [{"name": "get_order_status", "input": {"order_id": "A-10293"}}]
                if case["id"].startswith("2-")
                else []
            )
            ok, detail = run_check(check, fake)
            print(f"  {case['id']:28} {check['type']:14} {'ok  ' if ok else 'FAIL'} {detail}")
    assert not run_check({"type": "no_dates"}, Conversation("x", "A", 0, reply="by 2026-12-01"))[0]
    assert not run_check(
        {"type": "not_contains", "pattern": "4111[ -]?1111[ -]?1111[ -]?1111"},
        Conversation("x", "A", 0, reply="card 4111-1111-1111-1111"),
    )[0]
    assert fake_tool("get_order_status", {"order_id": "a-10077"}, orders).find("45") > 0
    assert "not found" in fake_tool("get_order_status", {"order_id": "Z-1"}, orders)
    print("Graders and fake tools behave as expected. No API calls were made.")


# --- main ------------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--only", help="Run only cases whose id starts with this.")
    parser.add_argument("--out", type=Path, default=HERE / "results")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--rejudge",
        action="store_true",
        help="Re-grade the saved transcripts in --out without calling the bot again "
        "(only the judge model is called).",
    )
    args = parser.parse_args()

    spec = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    cases = [c for c in spec["cases"] if not args.only or c["id"].startswith(args.only)]
    tools = anthropic_tools(json.loads(TOOLS_FILE.read_text(encoding="utf-8")))
    prompts = {arm: path.read_text(encoding="utf-8") for arm, path in PROMPTS.items()}

    if args.dry_run:
        dry_run(cases, tools, spec["orders"])
        return 0

    import anthropic  # only needed for the real run

    client = anthropic.Anthropic()
    transcripts = args.out / "transcripts"
    by_id = {case["id"]: case for case in cases}

    if args.rejudge:
        saved = [json.loads(p.read_text(encoding="utf-8")) for p in transcripts.glob("*.json")]
        saved = [s for s in saved if s["case_id"] in by_id]
        args.runs = max(s["run"] for s in saved)
        print(f"Re-grading {len(saved)} saved conversations with {args.judge_model}...")

        def work(saved_result):
            fields = {k: v for k, v in saved_result.items() if k != "grade"}
            fields["usage"] = {k: fields["usage"].get(k, 0) for k in ("input", "output")}
            conv = Conversation(**fields)
            graded = grade(client, args.judge_model, by_id[conv.case_id], conv)
            result = {**asdict(conv), "grade": graded}
            print(f"  {conv.case_id:28} {conv.arm} run {conv.run}: {graded['outcome']}", flush=True)
            return result

        jobs = saved
    else:
        jobs = [
            (case, arm, run) for case in cases for arm in prompts for run in range(1, args.runs + 1)
        ]
        print(f"{len(jobs)} conversations on {args.model}, judged by {args.judge_model}...")

        def work(job):
            case, arm, run = job
            conv = run_conversation(
                client, args.model, prompts[arm], tools, case, spec["orders"], arm, run
            )
            graded = grade(client, args.judge_model, case, conv)  # adds the judge's usage
            result = {**asdict(conv), "grade": graded}
            print(f"  {case['id']:28} {arm} run {run}: {graded['outcome']}", flush=True)
            return result

    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(work, jobs))
    results.sort(key=lambda r: (r["case_id"], r["arm"], r["run"]))

    transcripts.mkdir(parents=True, exist_ok=True)
    for r in results:
        name = f"{r['case_id']}_{r['arm']}_{r['run']}.json"
        (transcripts / name).write_text(
            json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    summary = summarize(cases, results, args.runs, args.model, args.judge_model)
    (args.out / "summary.md").write_text(summary, encoding="utf-8")
    print()
    print(summary)
    print(f"Done in {time.time() - started:.0f}s. Transcripts: {transcripts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
