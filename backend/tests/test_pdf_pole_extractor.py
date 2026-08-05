from app.services.pdf_pole_extractor import ExtractedPage, TextLine, extract_evidence


# Verbatim native-text lines from
# SUT-JB2109029-C-CO-AERIAL-BLOWN POLE_APPROVED PERMIT_EP2025-0118 R5.pdf.
PERMIT_LINES = (
    TextLine(
        "LASH FIBER CABLE FROM POLE #110393455 TO POLE #121467850 (66')",
        (96.2, 183.4, 512.7, 196.1),
    ),
    TextLine(
        "#121673073 TO POLE #121673072 (215')",
        (102.0, 244.0, 387.0, 257.0),
    ),
    TextLine(
        "NEW ANCHOR AT POLE #121692810",
        (88.0, 301.0, 322.0, 314.0),
    ),
    TextLine(
        "EXIST. POLE #121467850",
        (90.0, 352.0, 270.0, 365.0),
    ),
)


def test_extracts_real_permit_pole_relationships_lengths_and_anchor():
    evidence = extract_evidence([ExtractedPage(7, "\n".join(line.text for line in PERMIT_LINES), PERMIT_LINES)])

    spans = [item for item in evidence if item.evidence_type == "SPAN"]
    anchors = [item for item in evidence if item.evidence_type == "ANCHOR"]
    poles = [item for item in evidence if item.evidence_type == "POLE_ID"]

    assert [(item.from_pole_id, item.to_pole_id, item.span_length_ft) for item in spans] == [
        ("110393455", "121467850", 66.0),
        ("121673073", "121673072", 215.0),
    ]
    assert [(item.pole_id, item.confidence) for item in anchors] == [("121692810", 0.96)]
    assert any(item.pole_id == "121467850" for item in poles)


def test_preserves_page_raw_text_bbox_and_confidence():
    evidence = extract_evidence([ExtractedPage(43, PERMIT_LINES[0].text, (PERMIT_LINES[0],))])

    span = evidence[0]
    assert span.page_number == 43
    assert span.raw_text == PERMIT_LINES[0].text
    assert span.bbox == PERMIT_LINES[0].bbox
    assert span.confidence == 0.98


def test_does_not_infer_coordinates_or_assets():
    evidence = extract_evidence([ExtractedPage(7, PERMIT_LINES[1].text, (PERMIT_LINES[1],))])

    assert evidence[0].from_pole_id == "121673073"
    assert not hasattr(evidence[0], "longitude")
    assert not hasattr(evidence[0], "latitude")


def test_rejects_layout_artifacts_that_are_not_nine_digit_pole_ids():
    line = TextLine("POLE #1216722956 TO POLE #121672957 (282')", (1.0, 2.0, 3.0, 4.0))

    evidence = extract_evidence([ExtractedPage(15, line.text, (line,))])

    assert not any(item.evidence_type == "SPAN" for item in evidence)
    assert [item.pole_id for item in evidence] == ["121672957"]
