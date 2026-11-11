import json

import scan_coverage
import scan_lib

INVENTORY = {
    "skills": [
        {"name": "keyword-research", "model_invoked": True, "terms": ["keyword research", "keyword", "search", "volume", "intent"]},
        {"name": "deploy", "model_invoked": False, "terms": ["deploy", "production", "release"]},
    ],
    "mcp_servers": [{"name": "firecrawl", "source": "user"}, {"name": "github", "source": "project"}],
}
MATCHING_PROMPT = "find keyword ideas with search volume and intent for the pricing page please"
WEAK_PROMPT = "find keyword ideas and check the search results for the pricing page please"


def _coverage():
    cov = scan_coverage.Coverage(scan_coverage.Index(INVENTORY))
    cov.begin_session("/home/u/.claude/projects/-src-app/abc.jsonl")
    return cov


def test_prompt_with_three_terms_is_a_missed_skill_with_location():
    cov = _coverage()
    cov.on_prompt(MATCHING_PROMPT, 7)
    cov.end_session()
    assert cov.missed["keyword-research"] == 1
    assert cov.missed_locations["keyword-research"] == [["-src-app/abc.jsonl", 7]]


def test_prompt_with_two_terms_is_not_a_candidate():
    cov = _coverage()
    cov.on_prompt(WEAK_PROMPT, 3)
    cov.end_session()
    assert cov.missed == {}


def test_phrase_term_counts_double():
    cov = _coverage()
    cov.on_prompt("please run a keyword research pass on this landing page copy", 1)
    cov.end_session()
    assert cov.missed["keyword-research"] == 1


def test_invoked_skill_not_counted_as_missed_even_with_plugin_prefix():
    cov = _coverage()
    cov.on_prompt(MATCHING_PROMPT, 2)
    cov.on_tool_use("Skill", {"skill": "marketing:keyword-research"})
    cov.end_session()
    assert cov.missed == {} and cov.skills_used == {"keyword-research"}


def test_non_model_invoked_skill_never_scored():
    cov = _coverage()
    cov.on_prompt("deploy this to production as the next release today ok", 2)
    cov.end_session()
    assert cov.missed == {}


def test_short_prompt_ignored():
    cov = _coverage()
    cov.on_prompt("keyword search volume intent", 2)
    cov.end_session()
    assert cov.missed == {}


def test_location_keeps_subagent_path_under_project_dir():
    assert scan_coverage.project_location("/h/.claude/projects/-src-app/abc.jsonl") == "-src-app/abc.jsonl"
    assert scan_coverage.project_location("/h/.claude/projects/-src-app/abc/subagents/agent-1.jsonl") == "-src-app/abc/subagents/agent-1.jsonl"
    assert scan_coverage.project_location("/elsewhere/x/s.jsonl") == "x/s.jsonl"


def test_mcp_server_parsed_from_tool_name():
    assert scan_coverage.mcp_server_of("mcp__firecrawl__firecrawl_scrape") == "firecrawl"
    assert scan_coverage.mcp_server_of("mcp__plugin_omc_t__lsp_hover") == "plugin_omc_t"
    assert scan_coverage.mcp_server_of("Bash") is None


def test_summary_lists_used_and_unused_servers():
    cov = _coverage()
    cov.on_tool_use("mcp__firecrawl__firecrawl_scrape", {})
    cov.on_tool_use("mcp__firecrawl__firecrawl_search", {})
    cov.end_session()
    out = scan_coverage.summary(cov)
    assert out["mcp_servers_configured"] == ["firecrawl", "github"]
    assert out["mcp_servers_used"] == {"firecrawl": 2}
    assert out["mcp_servers_unused"] == ["github"]
    assert out["skills_available"] == 2


def test_missed_locations_capped_at_five_and_sorted_by_sessions():
    cov = scan_coverage.Coverage(scan_coverage.Index(INVENTORY))
    for i in range(7):
        cov.begin_session(f"/p/-proj/s{i}.jsonl")
        cov.on_prompt(MATCHING_PROMPT, i)
        cov.end_session()
    top = scan_coverage.summary(cov)["missed_skill_sessions"]
    assert top == [{"skill": "keyword-research", "sessions": 7, "locations": [[f"-proj/s{i}.jsonl", i] for i in range(5)]}]


def test_summary_without_inventory_is_empty():
    cov = scan_coverage.Coverage(None)
    cov.begin_session("/p/-proj/s.jsonl")
    cov.on_prompt(MATCHING_PROMPT, 1)
    cov.on_tool_use("mcp__firecrawl__firecrawl_scrape", {})
    cov.end_session()
    assert scan_coverage.summary(cov) == {
        "skills_available": 0, "skills_used_distinct": 0, "missed_skill_sessions": [],
        "mcp_servers_configured": [], "mcp_servers_used": {}, "mcp_servers_unused": []}


def test_scan_file_records_location_line_number(tmp_path):
    proj = tmp_path / "-src-app"
    proj.mkdir()
    f = proj / "sess.jsonl"
    f.write_text("\n".join([
        json.dumps({"type": "user", "message": {"content": "hello there, first line prompt that is long enough"}}),
        json.dumps({"type": "user", "message": {"content": MATCHING_PROMPT}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "mcp__firecrawl__firecrawl_scrape", "input": {}}]}}),
    ]) + "\n")
    pop = scan_lib.Pop(scan_coverage.Index(INVENTORY))
    scan_lib.scan_file(str(f), lambda e, p: pop, 10 ** 9, cutoff=0)
    out = scan_coverage.summary(pop.coverage)
    assert out["missed_skill_sessions"][0]["locations"] == [["-src-app/sess.jsonl", 2]]
    assert out["mcp_servers_used"] == {"firecrawl": 1}


def test_pop_without_inventory_keeps_empty_coverage_keys():
    import scan
    out = scan.population_summary(scan_lib.Pop())
    assert out["missed_skill_sessions"] == [] and out["skills_available"] == 0
    assert list(out)[-6:] == ["skills_available", "skills_used_distinct", "missed_skill_sessions",
                              "mcp_servers_configured", "mcp_servers_used", "mcp_servers_unused"]
