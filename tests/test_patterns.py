"""Fill-in-the-blank patterns: compiling, building from a selection, and serial number shapes."""

from __future__ import annotations

import re

import pytest

from datamapperx.patterns import (
    TemplateError,
    compile_template,
    sn_regex_from_example,
    template_from_marks,
    tokenize,
)

BLOCK_LINE = "{@BLOCK|1%cn107_sp|00"
JUM_LINE = "{@A-JUM|0|+3.888312E+07{@LIM2|+9.999999E+99|+1.000000E+04}}"
MEA_LINE = "{@A-MEA|0|+1.679574E+00|Output_B_high{@LIM2|+3.600000E+01|+1.000000E+00}}"
LIM3_LINE = "{@A-RES|0|+1.0E+03{@LIM3|+1.0E+03|+1.1E+03|+9.0E+02}}"


def search(template: str, rule: str, text: str, flags: int = 0) -> re.Match[str]:
    match = re.search(compile_template(template, rule), text, flags)
    assert match is not None, f"{template!r} did not match {text!r}"
    return match


# ----------------------------------------------------------------------------- compiling
def test_empty_template_means_unused():
    assert compile_template("", "limits") == ""
    assert compile_template("   ", "block") == ""


def test_component_line():
    match = search("{@BLOCK|[Component]|", "block", BLOCK_LINE)
    assert match.group("component") == "1%cn107_sp"


def test_component_at_the_end_stops_at_the_separator():
    match = search("{@BLOCK|[Component]", "block", BLOCK_LINE)
    assert match.group("component") == "1%cn107_sp"


def test_component_with_spaces_is_kept_when_a_delimiter_follows():
    match = search("{@BLOCK|[Component]|", "block", "{@BLOCK|R 10 k|00")
    assert match.group("component") == "R 10 k"


def test_measurement_line_gives_value_unit_and_the_rest_for_limits():
    template = "{@A-[Unit]|[Any]|[Measured]"
    match = search(template, "measure", JUM_LINE)
    assert (match.group("type"), match.group("measured")) == ("JUM", "+3.888312E+07")
    assert match.group("tail").startswith("{@LIM2")

    match = search(template, "measure", MEA_LINE)
    assert match.group("measured") == "+1.679574E+00"
    assert match.group("tail").startswith("|Output_B_high")


def test_limits_patterns_for_two_and_three_value_tags():
    tail = JUM_LINE.split("+3.888312E+07", 1)[1]
    two = search("{@LIM2|[Max]|[Min]", "limits", tail)
    assert (two.group("max"), two.group("min")) == ("+9.999999E+99", "+1.000000E+04")

    three = search("{@LIM3|[Any]|[Max]|[Min]", "limits", LIM3_LINE)
    assert (three.group("max"), three.group("min")) == ("+1.1E+03", "+9.0E+02")


def test_whitespace_in_a_pattern_matches_any_run_of_spaces():
    match = search("Result: [Measured] [Unit]", "measure", "Result:    3.30   V")
    assert (match.group("measured"), match.group("type")) == ("3.30", "V")


def test_text_that_follows_a_word_ends_a_value_with_spaces():
    match = search("Test [Component] finished", "block", "Test Init, Check Fixture finished OK")
    assert match.group("component") == "Init, Check Fixture"


def test_regex_special_characters_in_the_text_are_taken_literally():
    match = search("({@A.B*|[Measured]", "measure", "({@A.B*|12.5|x")
    assert match.group("measured") == "12.5"
    assert re.search(compile_template("({@A.B*|[Measured]", "measure"), "({@AxB*|12.5") is None


def test_any_blank_can_repeat_but_others_cannot():
    compile_template("[Any]|[Any]|[Measured]", "measure")
    with pytest.raises(TemplateError, match="only be used once"):
        compile_template("[Measured]|[Measured]", "measure")


def test_brackets_that_are_not_blanks_stay_literal():
    match = search("[INFO] value=[Measured]", "measure", "[INFO] value=7")
    assert match.group("measured") == "7"


def test_a_misspelt_blank_is_reported_with_a_suggestion():
    with pytest.raises(TemplateError, match=r"Did you mean \[Measured\]"):
        compile_template("{@A|[Mesured]", "measure")


def test_blank_names_are_not_case_sensitive_and_have_friendly_aliases():
    assert compile_template("a [measured]", "measure") == compile_template("a [Value]", "measure")
    assert compile_template("a [UNIT] [Measured]", "measure") == compile_template("a [Type] [Result]", "measure")


@pytest.mark.parametrize(
    ("template", "rule", "message"),
    [
        ("{@BLOCK|", "block", "needs \\[Component\\]"),
        ("{@A-|[Measured]", "block", "cannot be used in the component line"),
        ("[Min]x", "measure", "cannot be used in the measurement line"),
        ("{@LIM2|[Any]", "limits", "needs \\[Min\\] or \\[Max\\]"),
        ("[Min][Max]", "limits", "next to each other"),
    ],
)
def test_unusable_patterns_explain_themselves(template, rule, message):
    with pytest.raises(TemplateError, match=message):
        compile_template(template, rule)


def test_tokenize_splits_text_and_blanks():
    assert tokenize("a[Min]b[INFO]") == [("text", "a"), ("blank", "Min"), ("text", "b[INFO]")]


# ----------------------------------------------------------------------------- built from a selection
def span(line: str, text: str, name: str, occurrence: int = 0) -> tuple[int, int, str]:
    start = -1
    for _ in range(occurrence + 1):
        start = line.index(text, start + 1)
    return start, start + len(text), name


def test_component_line_from_a_selection_keeps_the_separator_and_the_status_after_it():
    assert template_from_marks(BLOCK_LINE, [span(BLOCK_LINE, "1%cn107_sp", "Component")], "block") == "{@BLOCK|[Component]|00"


def test_only_a_short_number_after_the_separator_counts_as_a_status():
    named = "{@BLOCK|R1|Result|00"
    assert template_from_marks(named, [span(named, "R1", "Component")], "block") == "{@BLOCK|[Component]|"
    assert template_from_marks("id=R1;7;x", [span("id=R1;7;x", "R1", "Component")], "block") == "id=[Component];7"
    assert template_from_marks("id=R1;7x", [span("id=R1;7x", "R1", "Component")], "block") == "id=[Component];"


def test_a_failed_attempt_is_not_read_when_the_pattern_requires_the_passing_status():
    regex = compile_template("{@BLOCK|[Component]|00", "block")
    assert re.search(regex, "{@BLOCK|1%c1133|01") is None
    assert re.search(regex, "{@BLOCK|1%c1133|00|1").group("component") == "1%c1133"


def test_measurement_line_from_selections_ignores_changing_numeric_fields_and_drops_the_rest():
    marks = [span(JUM_LINE, "JUM", "Unit"), span(JUM_LINE, "+3.888312E+07", "Measured")]
    assert template_from_marks(JUM_LINE, marks, "measure") == "{@A-[Unit]|[Any]|[Measured]"


def test_limits_start_at_their_own_tag_not_at_the_line_start():
    marks = [span(JUM_LINE, "+9.999999E+99", "Max"), span(JUM_LINE, "+1.000000E+04", "Min")]
    assert template_from_marks(JUM_LINE, marks, "limits") == "{@LIM2|[Max]|[Min]"


def test_limits_without_a_bracket_use_the_words_just_before():
    line = "Voltage 3.3 V  limits: 3.0 .. 3.6"
    marks = [span(line, "3.0", "Min"), span(line, "3.6", "Max")]
    assert template_from_marks(line, marks, "limits") == "limits: [Min] .. [Max]"


@pytest.mark.parametrize(
    ("line", "marks", "rule", "template"),
    [
        (BLOCK_LINE, [(8, 18, "Component")], "block", "{@BLOCK|[Component]|00"),
        ("  Test: R1 done", [(8, 10, "Component")], "block", "Test: [Component] done"),
    ],
)
def test_templates_built_from_marks_compile_and_find_the_marked_text(line, marks, rule, template):
    assert template_from_marks(line, marks, rule) == template
    assert search(template, rule, line).group("component") == line[marks[0][0] : marks[0][1]]


def test_a_name_followed_by_more_fields_needs_a_separator_to_know_where_it_ends():
    line = "  Test: R1 3.3 V"
    template = template_from_marks(line, [(8, 10, "Component")], "block")
    assert template == "Test: [Component]"
    # Nothing in the line says where the name ends, so it runs to the end. The person adds a separator in the log
    # format (or a fixed word after the name) to cut it; the sample viewer shows the over-long match straight away.
    assert search(template, "block", line).group("component") == "R1 3.3 V"


def test_marks_must_be_clean():
    with pytest.raises(TemplateError, match="overlap"):
        template_from_marks("abcdef", [(0, 4, "Min"), (2, 6, "Max")], "limits")
    with pytest.raises(TemplateError, match="inside a single line"):
        template_from_marks("abc", [(2, 9, "Min")], "limits")
    with pytest.raises(TemplateError, match="Select some text"):
        template_from_marks("abc", [], "limits")


# ----------------------------------------------------------------------------- serial numbers
@pytest.mark.parametrize(
    ("example", "text", "expected"),
    [
        ("VSE2C00000112", "AP1020K-DG-08-FW4_F_VSE2C00000113_260908164350_1_P.log", "VSE2C00000113"),
        ("VSEC000247657", "vsec000247658 2.xlsx", "VSEC000247658"),
        ("SV3826-06310A8C6-E1", "SV3826-06310A8C7-E2 1.xlsx", "SV3826-06310A8C7-E2"),
        ("06310A8C", "board 06310A8D done", "06310A8D"),
    ],
)
def test_serial_pattern_generalises_the_example(example, text, expected):
    match = re.search(sn_regex_from_example(example), text, re.IGNORECASE)
    assert match is not None and match.group("sn").upper() == expected.upper()


def test_serial_pattern_does_not_start_inside_a_longer_word():
    assert re.search(sn_regex_from_example("VSE123"), "XVSE456", re.IGNORECASE) is None
    assert re.search(sn_regex_from_example("06310A8C"), "x006310A8C9y", re.IGNORECASE) is None


def test_serial_example_must_be_usable():
    with pytest.raises(TemplateError, match="example serial"):
        sn_regex_from_example("  ")
    with pytest.raises(TemplateError, match="spaces"):
        sn_regex_from_example("SN 12")


# ----------------------------------------------------------------------------- component at the end of a line
def test_a_component_that_ends_the_pattern_keeps_its_spaces():
    match = search("TESTING [Component]", "block", "TESTING U7 VCC")
    assert match.group("component") == "U7 VCC"
    # ...but still stops at the separators that logs use between fields
    assert search("{@BLOCK|[Component]", "block", "{@BLOCK|R 10 k|00").group("component") == "R 10 k"
    assert search("TESTING [Component]", "block", "TESTING R9|00").group("component") == "R9"


# ----------------------------------------------------------------------------- profiles built from patterns
def test_a_profile_built_from_patterns_keeps_them_for_the_guided_editor():
    from datamapperx.profiles import patterns_from_profile, text_profile_from_patterns

    patterns = {"block": "TESTING [Component]", "measure": "RESULT [Measured] [Unit]", "lim2": "LIMITS [Min] .. [Max]", "lim3": ""}
    profile = text_profile_from_patterns(patterns, "UNIT-8841", ".txt")
    assert profile["file_extensions"] == ".txt" and profile["sn_example"] == "UNIT-8841"
    assert "lim3_template" not in profile and profile["lim3_regex"] == ""
    assert patterns_from_profile(profile) == ({k: v for k, v in patterns.items() if v}, [])


def test_a_pattern_is_not_offered_once_its_regular_expression_was_edited():
    from datamapperx.profiles import patterns_from_profile, text_profile_from_patterns

    profile = text_profile_from_patterns({"block": "TESTING [Component]", "measure": "RESULT [Measured]"}, "")
    profile["block_regex"] = r"TESTING (?P<component>\w+)"
    patterns, custom = patterns_from_profile(profile)
    assert patterns == {"measure": "RESULT [Measured]"} and custom == ["block"]


def test_built_in_profiles_are_reported_as_regular_expressions():
    from datamapperx.profiles import DEFAULT_PROFILES, patterns_from_profile

    patterns, custom = patterns_from_profile(DEFAULT_PROFILES["ICT_I3070 Test Log"])
    assert patterns == {} and custom == ["block", "measure", "lim2", "lim3"]


def test_a_wrong_pattern_names_the_rule_it_belongs_to():
    from datamapperx.profiles import text_profile_from_patterns

    with pytest.raises(TemplateError, match=r"Component line: .*needs \[Component\]"):
        text_profile_from_patterns({"block": "TESTING", "measure": "RESULT [Measured]"})
    with pytest.raises(TemplateError, match=r"Limits \(style B\): .*needs \[Min\] or \[Max\]"):
        text_profile_from_patterns({"block": "T [Component]", "measure": "R [Measured]", "lim3": "LIM [Any]"})
    with pytest.raises(TemplateError, match="Serial number: .*spaces"):
        text_profile_from_patterns({"block": "T [Component]", "measure": "R [Measured]"}, "A B")
