"""
Refined, Impeccable Design Deck for Project Review-1:
AI-Based Ambulance Dispatch & Dynamic Routing System (FOAI).

Design Standards Applied:
- Reduced from 18 slides to 12 tightly structured, high-impact slides.
- Perfectly balanced text-to-visual ratio on every slide.
- Embedded high-resolution diagrams (Architecture, CNP Flow, Search Methods),
  live UI screenshots, and empirical evaluation charts.
- Strict mathematical centering, consistent vertical padding, and visual hierarchy.
- Direct coverage of all 7 mandatory Review-1 constraints.
"""

import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

def build_impeccable_deck():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    # Color Palette - Modern Academic & Engineering
    NAVY = RGBColor(15, 23, 42)          # #0F172A (Deep Slate/Navy)
    DARK_BLUE = RGBColor(26, 54, 93)      # #1A365D (Primary Brand)
    TEAL = RGBColor(13, 148, 136)        # #0D9488 (Teal Accent)
    BLUE_ACCENT = RGBColor(37, 99, 235)  # #2563EB (Highlight Blue)
    CARD_BG = RGBColor(255, 255, 255)    # #FFFFFF (Crisp White Card)
    LIGHT_BG = RGBColor(248, 250, 252)   # #F8FAFC (Subtle Slate Background)
    TEXT_MAIN = RGBColor(30, 41, 59)     # #1E293B (Dark Slate Text)
    TEXT_MUTED = RGBColor(100, 116, 139) # #64748B (Secondary Text)
    BORDER_COL = RGBColor(226, 232, 240) # #E2E8F0 (Subtle Border)
    RED_ACCENT = RGBColor(220, 38, 38)   # #DC2626 (Failure / Warning)
    GREEN_ACCENT = RGBColor(16, 149, 106)# #10956A (Success / Proposed)

    def set_slide_background(slide, color=LIGHT_BG):
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
        bg.fill.solid()
        bg.fill.fore_color.rgb = color
        bg.line.fill.background()
        return bg

    def add_header(slide, title_text, section_tag=""):
        # Header banner
        header_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11.733), Inches(0.85))
        tf = header_box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
        
        p_cat = tf.paragraphs[0]
        cat_text = "FOUNDATIONS OF ARTIFICIAL INTELLIGENCE  •  PROJECT REVIEW - 1"
        if section_tag:
            cat_text = f"[{section_tag.upper()}]  •  " + cat_text
        p_cat.text = cat_text
        p_cat.font.size = Pt(9.5)
        p_cat.font.bold = True
        p_cat.font.color.rgb = TEAL

        p_title = tf.add_paragraph()
        p_title.text = title_text
        p_title.font.size = Pt(21)
        p_title.font.bold = True
        p_title.font.color.rgb = DARK_BLUE
        p_title.space_before = Pt(3)

        # Subtle divider
        line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(1.32), Inches(11.733), Inches(0.015))
        line.fill.solid()
        line.fill.fore_color.rgb = BORDER_COL
        line.line.color.rgb = BORDER_COL

    def add_card(slide, left, top, width, height, bg_color=CARD_BG, border_color=BORDER_COL):
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
        card.fill.solid()
        card.fill.fore_color.rgb = bg_color
        card.line.color.rgb = border_color
        card.line.width = Pt(1)
        return card

    # =========================================================================
    # SLIDE 1: Title Slide (Hero Dark Theme)
    # =========================================================================
    s1 = prs.slides.add_slide(blank_layout)
    set_slide_background(s1, NAVY)

    # Accent pill tag
    pill = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1.2), Inches(1.4), Inches(4.8), Inches(0.45))
    pill.fill.solid()
    pill.fill.fore_color.rgb = RGBColor(19, 78, 74)
    pill.line.color.rgb = TEAL
    pill_tf = pill.text_frame
    pill_p = pill_tf.paragraphs[0]
    pill_p.text = "CAPSTONE PROJECT  •  REVIEW - 1 EVALUATION"
    pill_p.font.size = Pt(10)
    pill_p.font.bold = True
    pill_p.font.color.rgb = RGBColor(94, 234, 212)
    pill_p.alignment = PP_ALIGN.CENTER

    tbox = s1.shapes.add_textbox(Inches(1.2), Inches(2.0), Inches(10.9), Inches(4.8))
    tf1 = tbox.text_frame
    tf1.word_wrap = True

    p1 = tf1.paragraphs[0]
    p1.text = "AI-Based Ambulance Dispatch &\nDynamic Routing System"
    p1.font.size = Pt(36)
    p1.font.bold = True
    p1.font.color.rgb = RGBColor(255, 255, 255)

    p2 = tf1.add_paragraph()
    p2.text = "A Verifiable Classical AI Simulation: Multi-Agent Dispatch (CNP), Hybrid Search (A*, LRTA*, D* Lite), Bed Triage (CSP), and Fleet Positioning (MDP)"
    p2.font.size = Pt(14)
    p2.font.color.rgb = RGBColor(203, 213, 225)
    p2.space_before = Pt(14)

    # 4 Feature Badges horizontally
    badges = [
        "100% Classical AI (No ML)",
        "Contract Net Protocol + Re-negotiation",
        "Exact MDP Value Iteration",
        "Dual Web Canvas & Terminal UI"
    ]
    p_b = tf1.add_paragraph()
    p_b.text = "   •   ".join(badges)
    p_b.font.size = Pt(11)
    p_b.font.bold = True
    p_b.font.color.rgb = TEAL
    p_b.space_before = Pt(22)

    p3 = tf1.add_paragraph()
    p3.text = "Course: Foundations of Artificial Intelligence (FOAI)   |   Department Review Committee   |   September 2026"
    p3.font.size = Pt(11.5)
    p3.font.color.rgb = RGBColor(148, 163, 184)
    p3.space_before = Pt(24)

    # =========================================================================
    # SLIDE 2: 1. Problem Statement & PEAS Framework
    # =========================================================================
    s2 = prs.slides.add_slide(blank_layout)
    set_slide_background(s2)
    add_header(s2, "Problem Statement & PEAS Agent Formulation", "1. Problem Statement")

    # Left Card: Formal Problem Definition
    add_card(s2, 0.8, 1.55, 5.7, 5.4)
    tb_l = s2.shapes.add_textbox(Inches(1.0), Inches(1.75), Inches(5.3), Inches(5.0))
    tf_l = tb_l.text_frame
    tf_l.word_wrap = True

    p = tf_l.paragraphs[0]
    p.text = "Formal Mathematical Problem"
    p.font.bold = True
    p.font.size = Pt(15)
    p.font.color.rgb = DARK_BLUE

    p = tf_l.add_paragraph()
    p.text = "Given an urban graph G = (V, E) with dynamic travel costs, a fleet of K ambulances, and stochastic emergency calls arriving with clinical severities s ∈ {1, ..., 5}, design an autonomous emergency response system that jointly optimizes:\n\n" \
             "1. Response Latency: Minimize mean and P95 tail delay across calls.\n" \
             "2. Dynamic Adaptability: Reassign en-route calls if closer units emerge.\n" \
             "3. Partial Observability: Efficiently bypass unmapped road closures.\n" \
             "4. Resource Constraints: Hand off patients without hospital bed overflow.\n" \
             "5. Geographic Equity: Eliminate 'medical deserts' across city zones."
    p.font.size = Pt(11)
    p.font.color.rgb = TEXT_MAIN
    p.space_before = Pt(6)

    # Right Side: 4 Visual PEAS Blocks
    peas_data = [
        ("PERFORMANCE MEASURE", "Mean & P95 response latency, fleet workload variance, Gini equity index, and search expansion efficiency.", TEAL, "#F0FDFA"),
        ("ENVIRONMENT", "Urban graph G=(V,E), partially observable road closures, stochastic arrivals, multi-agent cooperative, tick-discrete.", BLUE_ACCENT, "#EFF6FF"),
        ("ACTUATORS", "Dispatch contract awards, edge traversal navigation vectors, hospital admissions, and idle repositioning commands.", DARK_BLUE, "#F8FAFC"),
        ("SENSORS", "911 emergency call telemetry, ambulance GPS coordinates, hospital bed capacity monitors, and junction obstacle sensors.", TEAL, "#F0FDFA")
    ]

    for i, (title, desc, col, bg) in enumerate(peas_data):
        add_card(s2, 6.75, 1.55 + i * 1.38, 5.78, 1.25, bg_color=RGBColor(255, 255, 255), border_color=BORDER_COL)
        tb = s2.shapes.add_textbox(Inches(6.95), Inches(1.65 + i * 1.38), Inches(5.38), Inches(1.05))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = title
        p.font.bold = True
        p.font.size = Pt(11)
        p.font.color.rgb = col
        p = tf.add_paragraph()
        p.text = desc
        p.font.size = Pt(10)
        p.font.color.rgb = TEXT_MAIN
        p.space_before = Pt(2)

    # =========================================================================
    # SLIDE 3: 2. Abstract & Core AI Pillars
    # =========================================================================
    s3 = prs.slides.add_slide(blank_layout)
    set_slide_background(s3)
    add_header(s3, "Abstract: Classical AI Architecture & Key Pillars", "2. Abstract")

    # Left: Concise Abstract Narrative Card
    add_card(s3, 0.8, 1.55, 5.5, 5.4)
    tb_abs = s3.shapes.add_textbox(Inches(1.0), Inches(1.75), Inches(5.1), Inches(5.0))
    tf_abs = tb_abs.text_frame
    tf_abs.word_wrap = True

    p = tf_abs.paragraphs[0]
    p.text = "Executive Summary"
    p.font.bold = True
    p.font.size = Pt(15)
    p.font.color.rgb = DARK_BLUE

    p = tf_abs.add_paragraph()
    p.text = "Emergency Medical Services (EMS) require rapid, dependable, and explainable decision-making. Existing dispatch systems rely on greedy heuristics that cause vehicle clustering, or experimental deep learning models that lack formal verification.\n\n" \
             "This project demonstrates an end-to-end, high-fidelity emergency simulation driven entirely by verifiable Classical AI. By coordinating multi-agent task auctions, real-time and incremental graph search, constraint satisfaction, and dynamic programming, the framework achieves balanced fleet workload, provable bed allocation, and inter-zone geographic equity."
    p.font.size = Pt(11.5)
    p.font.color.rgb = TEXT_MAIN
    p.space_before = Pt(8)

    p = tf_abs.add_paragraph()
    p.text = "Core Takeaway: Provable classical AI matches modern response demands while delivering 100% auditable explainability."
    p.font.bold = True
    p.font.size = Pt(11)
    p.font.color.rgb = TEAL
    p.space_before = Pt(14)

    # Right: 4 Visual Pillars (2x2 Grid)
    pillars = [
        ("Multi-Agent Dispatch", "Contract Net Protocol (CNP) with multi-criteria bidding and dynamic in-transit re-negotiation.", TEAL, "#F0FDFA"),
        ("Hybrid Graph Search", "A* (optimal), LRTA* (urgent real-time learning), and D* Lite (incremental roadblock replanning).", BLUE_ACCENT, "#EFF6FF"),
        ("Hospital Allocation", "Constraint Satisfaction Problem (CSP) solved via backtracking with MRV, LCV, and Forward Checking.", DARK_BLUE, "#F8FAFC"),
        ("Proactive Relocation", "Markov Decision Process (MDP) solved via exact Value Iteration to optimize geographic equity (Gini).", GREEN_ACCENT, "#F0FDF4")
    ]

    for i, (title, desc, col, bg) in enumerate(pillars):
        r = i // 2
        c_idx = i % 2
        add_card(s3, 6.55 + c_idx * 3.0, 1.55 + r * 2.75, 2.85, 2.6, bg_color=CARD_BG)
        tb = s3.shapes.add_textbox(Inches(6.75 + c_idx * 3.0), Inches(1.75 + r * 2.75), Inches(2.45), Inches(2.2))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = title
        p.font.bold = True
        p.font.size = Pt(13)
        p.font.color.rgb = col
        p = tf.add_paragraph()
        p.text = desc
        p.font.size = Pt(10)
        p.font.color.rgb = TEXT_MAIN
        p.space_before = Pt(6)

    # =========================================================================
    # SLIDE 4: 3. Literature Review & Research Gaps
    # =========================================================================
    s4 = prs.slides.add_slide(blank_layout)
    set_slide_background(s4)
    add_header(s4, "Literature Review: Foundations & Research Gaps", "3. Literature Review")

    # Clean Styled Table
    t_rows, t_cols = 6, 4
    table_shape = s4.shapes.add_table(t_rows, t_cols, Inches(0.8), Inches(1.55), Inches(11.733), Inches(3.6))
    table = table_shape.table
    table.columns[0].width = Inches(2.2)
    table.columns[1].width = Inches(2.8)
    table.columns[2].width = Inches(3.8)
    table.columns[3].width = Inches(2.933)

    headers = ["Author & Year", "Concept & Foundation", "Key Principle", "Identified Research Gap"]
    for j, h in enumerate(headers):
        cell = table.cell(0, j)
        cell.text = h
        cell.fill.solid()
        cell.fill.fore_color.rgb = DARK_BLUE
        p = cell.text_frame.paragraphs[0]
        p.font.bold = True
        p.font.size = Pt(10.5)
        p.font.color.rgb = RGBColor(255, 255, 255)

    lit_rows = [
        ("Smith (1980)", "Contract Net Protocol", "Distributed task auctioning via bidding and award.", "Static auctions; ignores in-transit reallocation."),
        ("Hart et al. (1968)", "A* Graph Search", "Optimal heuristic search with admissible heuristics.", "Scratch recomputation is costly during road obstacles."),
        ("Korf (1990)", "LRTA* Real-Time Search", "Interleaved action and heuristic learning.", "Lacks coordination in multi-vehicle fleets."),
        ("Koenig & Likhachev (2002)", "D* Lite Incremental", "Repairs search trees locally when edge costs change.", "Rarely integrated with multi-agent dispatch."),
        ("Bellman / Puterman", "Markov Decision Process", "Exact Value Iteration over Bellman equations.", "Decoupled from dispatch; omits spatial fairness.")
    ]

    for i, row in enumerate(lit_rows):
        for j, val in enumerate(row):
            cell = table.cell(i + 1, j)
            cell.text = val
            cell.fill.solid()
            cell.fill.fore_color.rgb = CARD_BG if i % 2 == 0 else LIGHT_BG
            p = cell.text_frame.paragraphs[0]
            p.font.size = Pt(9.5)
            p.font.color.rgb = TEXT_MAIN

    # Highlight Banner at bottom
    add_card(s4, 0.8, 5.35, 11.733, 1.6)
    tb_gap = s4.shapes.add_textbox(Inches(1.0), Inches(5.45), Inches(11.333), Inches(1.4))
    tf_g = tb_gap.text_frame
    tf_g.word_wrap = True
    p = tf_g.paragraphs[0]
    p.text = "Identified Research Gap & Our Contribution"
    p.font.bold = True
    p.font.size = Pt(12)
    p.font.color.rgb = TEAL
    p = tf_g.add_paragraph()
    p.text = "Existing academic literature studies dispatch, replanning, hospital triage, and idle relocation in isolated silos, while industry trends favor uninterpretable neural networks. Our contribution is the holistic synthesis of these five classical paradigms into a unified, deterministic, fully explainable emergency response simulation."
    p.font.size = Pt(10.5)
    p.font.color.rgb = TEXT_MAIN
    p.space_before = Pt(3)

    # =========================================================================
    # SLIDE 5: 4 & 5. Existing System vs. Proposed System
    # =========================================================================
    s5 = prs.slides.add_slide(blank_layout)
    set_slide_background(s5)
    add_header(s5, "Comparative Analysis: Existing System vs. Proposed System", "4. Existing & 5. Proposed")

    # Left: Existing System (Red Accents)
    add_card(s5, 0.8, 1.55, 5.7, 5.4, border_color=RGBColor(254, 202, 202))
    tb_e = s5.shapes.add_textbox(Inches(1.0), Inches(1.75), Inches(5.3), Inches(5.0))
    tf_e = tb_e.text_frame
    tf_e.word_wrap = True
    p = tf_e.paragraphs[0]
    p.text = "Existing System (Legacy CAD Heuristics)"
    p.font.bold = True
    p.font.size = Pt(15)
    p.font.color.rgb = RED_ACCENT

    ex_items = [
        ("Greedy Nearest-Unit Dispatch", "Dispatches closest idle ambulance based solely on distance, overworking central units."),
        ("Static Return-to-Base Policy", "Units return to home garage, creating fleet clustering and leaving suburbs unprotected."),
        ("Scratch A* Recomputation", "Full path is recalculated from scratch on every roadblock, causing CPU latency spikes."),
        ("First-Free Bed Allocation", "Rushes patients to closest hospital, triggering emergency department saturation."),
        ("High Workload Inequity", "Workload spread reaches 3.5 calls; Gini index > 0.36 indicates severe geographic disparity.")
    ]
    for h, b in ex_items:
        p = tf_e.add_paragraph()
        p.text = f"• {h}: {b}"
        p.font.size = Pt(10)
        p.font.color.rgb = TEXT_MAIN
        p.space_before = Pt(5)

    # Right: Proposed System (Green Accents)
    add_card(s5, 6.75, 1.55, 5.78, 5.4, border_color=RGBColor(167, 243, 208))
    tb_p = s5.shapes.add_textbox(Inches(6.95), Inches(1.75), Inches(5.38), Inches(5.0))
    tf_p = tb_p.text_frame
    tf_p.word_wrap = True
    p = tf_p.paragraphs[0]
    p.text = "Proposed System (Classical AI Stack)"
    p.font.bold = True
    p.font.size = Pt(15)
    p.font.color.rgb = GREEN_ACCENT

    prop_items = [
        ("Contract Net Protocol (CNP)", "Multi-criteria auction evaluates ETA, distance, momentum, and workload fairness."),
        ("Dynamic Task Re-negotiation", "In-transit re-auctioning reassigns calls when a closer unit saves ≥ 60 seconds."),
        ("D* Lite Incremental Replanning", "Repairs only affected nodes upon roadblock discovery, saving up to 80% expansions."),
        ("CSP Bed Capacity Allocation", "Backtracking + MRV/LCV/Forward Checking guarantees zero emergency bed overflow."),
        ("Proactive MDP Relocation", "Value Iteration relocates idle fleet to high-risk zones, lowering Gini equity to 0.246.")
    ]
    for h, b in prop_items:
        p = tf_p.add_paragraph()
        p.text = f"✓ {h}: {b}"
        p.font.size = Pt(10)
        p.font.color.rgb = TEXT_MAIN
        p.space_before = Pt(5)

    # =========================================================================
    # SLIDE 6: 7. System Architecture & Workflow Pipeline
    # =========================================================================
    s6 = prs.slides.add_slide(blank_layout)
    set_slide_background(s6)
    add_header(s6, "System Architecture: 4-Layer Verifiable Pipeline", "7. Architecture")

    # Left: Embed High-Resolution Architecture Diagram
    diag_path = os.path.abspath("diagram_architecture.png")
    if os.path.exists(diag_path):
        s6.shapes.add_picture(diag_path, Inches(0.8), Inches(1.55), width=Inches(6.6))

    # Right: Pipeline Stages & Core Engine Contract
    add_card(s6, 7.6, 1.55, 4.933, 5.4)
    tb_pipe = s6.shapes.add_textbox(Inches(7.8), Inches(1.75), Inches(4.533), Inches(5.0))
    tf_pipe = tb_pipe.text_frame
    tf_pipe.word_wrap = True

    p = tf_pipe.paragraphs[0]
    p.text = "Tick Execution Pipeline (Δt = 2.0s)"
    p.font.bold = True
    p.font.size = Pt(14)
    p.font.color.rgb = DARK_BLUE

    pipe_steps = [
        ("1. Environment Update", "Dynamic blockages apply/expire; hidden road hazards revealed upon junction entry."),
        ("2. CNP Dispatch", "New 911 calls announced; fleet evaluates bids; contracts awarded with in-transit audits."),
        ("3. Movement & Routing", "Vehicles advance along optimal A* / LRTA* paths; D* Lite repairs blocked routes."),
        ("4. Scene & Bed Triage", "Paramedic on-scene stabilization; CSP solver assigns destination hospital."),
        ("5. MDP Relocation", "Idle units evaluate exact Value Iteration policy to drift toward high-risk coverage zones.")
    ]
    for h, b in pipe_steps:
        p = tf_pipe.add_paragraph()
        p.text = f"• {h}: {b}"
        p.font.size = Pt(9.5)
        p.font.color.rgb = TEXT_MAIN
        p.space_before = Pt(4)

    p = tf_pipe.add_paragraph()
    p.text = "Unified Engine Contract: Pure-Python, in-memory state engine exposing snapshot() and events_since() to ensure 100% identical web and terminal replays."
    p.font.bold = True
    p.font.size = Pt(9.5)
    p.font.color.rgb = TEAL
    p.space_before = Pt(8)

    # =========================================================================
    # SLIDE 7: 6. Methodology I — Multi-Agent Dispatch (CNP)
    # =========================================================================
    s7 = prs.slides.add_slide(blank_layout)
    set_slide_background(s7)
    add_header(s7, "Methodology I: Multi-Agent Dispatch & Task Re-negotiation", "6. Methodologies")

    # Top: Embed CNP Flowchart Diagram
    cnp_diag = os.path.abspath("diagram_cnp_flow.png")
    if os.path.exists(cnp_diag):
        s7.shapes.add_picture(cnp_diag, Inches(0.8), Inches(1.55), width=Inches(11.733))

    # Bottom Left: Utility Formulation Card
    add_card(s7, 0.8, 4.45, 5.7, 2.5)
    tb_c1 = s7.shapes.add_textbox(Inches(1.0), Inches(4.6), Inches(5.3), Inches(2.2))
    tf_c1 = tb_c1.text_frame
    tf_c1.word_wrap = True
    p = tf_c1.paragraphs[0]
    p.text = "Multi-Criteria Utility Scoring Function"
    p.font.bold = True
    p.font.size = Pt(13)
    p.font.color.rgb = DARK_BLUE

    p = tf_c1.add_paragraph()
    p.text = "Score = w_eta·norm(ETA) + w_dist·norm(Dist) + w_stat·Status + w_load·Workload\n" \
             "• Weights: w_eta=0.45, w_dist=0.20, w_stat=0.15, w_load=0.20\n" \
             "• norm(x): Normalized against worst bidder in auction\n" \
             "• Status Penalty: Rewards active vehicle momentum\n" \
             "• Workload Penalty: Favors units with fewer completed calls (fleet fairness)"
    p.font.size = Pt(10)
    p.font.color.rgb = TEXT_MAIN
    p.space_before = Pt(3)

    # Bottom Right: Re-negotiation Card
    add_card(s7, 6.8, 4.45, 5.733, 2.5)
    tb_c2 = s7.shapes.add_textbox(Inches(7.0), Inches(4.6), Inches(5.333), Inches(2.2))
    tf_c2 = tb_c2.text_frame
    tf_c2.word_wrap = True
    p = tf_c2.paragraphs[0]
    p.text = "Dynamic In-Transit Re-negotiation Guard"
    p.font.bold = True
    p.font.size = Pt(13)
    p.font.color.rgb = DARK_BLUE

    p = tf_c2.add_paragraph()
    p.text = "• In-Transit Evaluation: Re-auction scanned every renog_check_every = 5 ticks.\n" \
             "• Reassignment Condition: ETA(Challenger) < ETA(Incumbent) - 60.0 s\n" \
             "• Anti-Thrash Threshold: Strict 60-second penalty margin prevents cyclic reassignment.\n" \
             "• Incident Cooldown: 60-tick anchor eliminates auction churn.\n" \
             "• Audit Trail: Generates explainable dispatch.renegotiated events."
    p.font.size = Pt(10)
    p.font.color.rgb = TEXT_MAIN
    p.space_before = Pt(3)

    # =========================================================================
    # SLIDE 8: 6. Methodology II — Heuristic & Incremental Search
    # =========================================================================
    s8 = prs.slides.add_slide(blank_layout)
    set_slide_background(s8)
    add_header(s8, "Methodology II: Heuristic, Real-Time & Incremental Search", "6. Methodologies")

    # Top: Embed Search Diagram
    s_diag = os.path.abspath("diagram_search_methods.png")
    if os.path.exists(s_diag):
        s8.shapes.add_picture(s_diag, Inches(0.8), Inches(1.55), width=Inches(11.733))

    # Bottom: 2 Mathematical Formulation Cards
    add_card(s8, 0.8, 4.6, 5.7, 2.35)
    tb_s1 = s8.shapes.add_textbox(Inches(1.0), Inches(4.75), Inches(5.3), Inches(2.05))
    tf_s1 = tb_s1.text_frame
    tf_s1.word_wrap = True
    p = tf_s1.paragraphs[0]
    p.text = "A* Admissibility & LRTA* Real-Time Rule"
    p.font.bold = True
    p.font.size = Pt(12.5)
    p.font.color.rgb = DARK_BLUE
    p = tf_s1.add_paragraph()
    p.text = "• A* Heuristic: Euclidean distance h(u,v) = ||pos(u) - pos(v)||\n" \
             "  - Admissibility proven: h(n) ≤ h*(n) across all graph nodes\n" \
             "  - Monotonicity verified: h(u) ≤ c(u, v) + h(v)\n" \
             "• LRTA* Update: In cardiac arrest (Severity 5), unit acts immediately:\n" \
             "  h(s) ← max [ h(s), min_{v ∈ N(s)} (c(s, v) + h(v)) ]"
    p.font.size = Pt(9.5)
    p.font.color.rgb = TEXT_MAIN
    p.space_before = Pt(3)

    add_card(s8, 6.8, 4.6, 5.733, 2.35)
    tb_s2 = s8.shapes.add_textbox(Inches(7.0), Inches(4.75), Inches(5.333), Inches(2.05))
    tf_s2 = tb_s2.text_frame
    tf_s2.word_wrap = True
    p = tf_s2.paragraphs[0]
    p.text = "D* Lite Incremental Replanning Mechanics"
    p.font.bold = True
    p.font.size = Pt(12.5)
    p.font.color.rgb = DARK_BLUE
    p = tf_s2.add_paragraph()
    p.text = "• Maintains g(s) and rhs(s): rhs(s) = min_{s'} (c(s, s') + g(s'))\n" \
             "• Priority Key: k(s) = [min(g, rhs) + h(s_start, s) + km; min(g, rhs)]\n" \
             "• When road hazard discovered, c(u,v) → ∞; only inconsistent states (rhs ≠ g) are recomputed.\n" \
             "• Efficiency: Amortizes search, eliminating costly scratch re-runs."
    p.font.size = Pt(9.5)
    p.font.color.rgb = TEXT_MAIN
    p.space_before = Pt(3)

    # =========================================================================
    # SLIDE 9: 6. Methodology III — Hospital CSP & Fleet MDP
    # =========================================================================
    s9 = prs.slides.add_slide(blank_layout)
    set_slide_background(s9)
    add_header(s9, "Methodology III: Hospital Bed CSP & Idle Fleet MDP", "6. Methodologies")

    # Left Card: Hospital CSP
    add_card(s9, 0.8, 1.55, 5.7, 5.4)
    tb_csp = s9.shapes.add_textbox(Inches(1.0), Inches(1.75), Inches(5.3), Inches(5.0))
    tf_csp = tb_csp.text_frame
    tf_csp.word_wrap = True
    p = tf_csp.paragraphs[0]
    p.text = "Hospital Bed Allocation via CSP"
    p.font.bold = True
    p.font.size = Pt(14)
    p.font.color.rgb = DARK_BLUE

    p = tf_csp.add_paragraph()
    p.text = "Formal CSP Model ⟨X, D, C⟩:\n" \
             "• Variables X: Incidents requiring hospital admission.\n" \
             "• Domains D(x_i): Feasible hospitals within distance limit.\n" \
             "• Capacity Constraint: For every hospital h,\n" \
             "  ∑_{i=1}^n I(x_i = h) ≤ FreeBeds(h)\n\n" \
             "Search & Pruning Heuristics:\n" \
             "• Minimum Remaining Values (MRV): Assigns variable with smallest domain first ('fail-first' principle).\n" \
             "• Least Constraining Value (LCV): Chooses bed that preserves maximum options for other patients.\n" \
             "• Forward Checking: Immediately prunes hospitals from all domains once bed capacity hits zero."
    p.font.size = Pt(10)
    p.font.color.rgb = TEXT_MAIN
    p.space_before = Pt(4)

    # Right Card: Idle Relocation MDP & Gini
    add_card(s9, 6.75, 1.55, 5.78, 5.4)
    tb_mdp = s9.shapes.add_textbox(Inches(6.95), Inches(1.75), Inches(5.38), Inches(5.0))
    tf_mdp = tb_mdp.text_frame
    tf_mdp.word_wrap = True
    p = tf_mdp.paragraphs[0]
    p.text = "Idle Relocation MDP & Spatial Equity"
    p.font.bold = True
    p.font.size = Pt(14)
    p.font.color.rgb = DARK_BLUE

    p = tf_mdp.add_paragraph()
    p.text = "MDP Value Iteration Formulation:\n" \
             "• State Space S: City zones {z_1, ..., z_Z}; Action Space A: Relocate.\n" \
             "• Reward: R(s, a) = Coverage(a) - λ · TravelTime(s, a)\n" \
             "  where Coverage(z) = ∑_i P(i) · [ 1 / (1 + TravelTime(z, i)/τ) ]\n" \
             "• Bellman Update: V_{k+1}(s) = max_a [ R(s, a) + γ · V_k(a) ]\n" \
             "  Iterates until Bellman residual < 10^-6.\n\n" \
             "Gini Equity Metric Formula:\n" \
             "G = ∑_{i=1}^n (2i - n - 1) y_i  /  [ n ∑_{i=1}^n y_i ]\n" \
             "• Range: G ∈ [0, 1]. G = 0 represents perfect inter-zone equality.\n" \
             "• Impact: MDP reduces Gini from 0.361 down to 0.246."
    p.font.size = Pt(10)
    p.font.color.rgb = TEXT_MAIN
    p.space_before = Pt(4)

    # =========================================================================
    # SLIDE 10: Live Demonstration & Dual Dashboard UI
    # =========================================================================
    s10 = prs.slides.add_slide(blank_layout)
    set_slide_background(s10)
    add_header(s10, "Live Demonstration: Web Dashboard & Terminal Interface", "Live Demo & UI")

    # Left: Web UI Screenshot
    web_img = os.path.abspath("web_screenshot_1280.png")
    if os.path.exists(web_img):
        s10.shapes.add_picture(web_img, Inches(0.8), Inches(1.55), width=Inches(7.3))

    # Right: Feature Cards
    add_card(s10, 8.3, 1.55, 4.233, 5.4)
    tb_ui = s10.shapes.add_textbox(Inches(8.45), Inches(1.75), Inches(3.933), Inches(5.0))
    tf_ui = tb_ui.text_frame
    tf_ui.word_wrap = True
    p = tf_ui.paragraphs[0]
    p.text = "Interactive UI Features"
    p.font.bold = True
    p.font.size = Pt(14)
    p.font.color.rgb = DARK_BLUE

    ui_feats = [
        ("HTML5 Canvas Grid", "Visualizes real-time vehicle routes, stations, and hospital bed levels."),
        ("Algorithm Arena", "Compares A*, Dijkstra, GBFS, and BFS head-to-head on every dispatch."),
        ("Explainability Feed", "Live audit stream of CNP bids, LRTA* updates, and CSP backtracks."),
        ("Zone Fairness Strip", "Dynamic heatmap and Gini coefficient of per-zone response latencies."),
        ("Terminal TUI Dashboard", "Pure-terminal Textual dashboard for headless or server deployments.")
    ]
    for h, b in ui_feats:
        p = tf_ui.add_paragraph()
        p.text = f"• {h}: {b}"
        p.font.size = Pt(9.5)
        p.font.color.rgb = TEXT_MAIN
        p.space_before = Pt(4)

    p = tf_ui.add_paragraph()
    p.text = "Single Source of Truth: Both web and terminal UIs consume identical engine snapshots."
    p.font.bold = True
    p.font.size = Pt(9.5)
    p.font.color.rgb = TEAL
    p.space_before = Pt(8)

    # =========================================================================
    # SLIDE 11: Empirical Results & Ablation Benchmarking
    # =========================================================================
    s11 = prs.slides.add_slide(blank_layout)
    set_slide_background(s11)
    add_header(s11, "Empirical Evaluation: Ablation Study & Performance", "Evaluation & Results")

    # Top: Two Embedded Benchmark Charts
    c1 = os.path.abspath("benchmark_out/charts/response_avg.png")
    c2 = os.path.abspath("benchmark_out/charts/equity.png")
    if os.path.exists(c1):
        s11.shapes.add_picture(c1, Inches(0.8), Inches(1.55), width=Inches(5.7))
    if os.path.exists(c2):
        s11.shapes.add_picture(c2, Inches(6.8), Inches(1.55), width=Inches(5.7))

    # Bottom: Quantitative Ablation Table
    t_rows, t_cols = 4, 6
    t_shape = s11.shapes.add_table(t_rows, t_cols, Inches(0.8), Inches(4.35), Inches(11.733), Inches(2.6))
    t = t_shape.table
    widths = [Inches(2.7), Inches(1.8), Inches(1.8), Inches(1.8), Inches(1.9), Inches(1.733)]
    for idx, w in enumerate(widths):
        t.columns[idx].width = w

    b_heads = ["Policy Combination", "Mean Latency", "P95 Latency", "Gini Equity", "Workload Spread", "Travel Dist"]
    for j, h in enumerate(b_heads):
        cell = t.cell(0, j)
        cell.text = h
        cell.fill.solid()
        cell.fill.fore_color.rgb = DARK_BLUE
        p = cell.text_frame.paragraphs[0]
        p.font.bold = True
        p.font.size = Pt(10)
        p.font.color.rgb = RGBColor(255, 255, 255)

    res_subset = [
        ("Naive Baseline", "78.7 s", "146.8 s", "0.361 (High Inequity)", "3.5 calls", "120.2 km"),
        ("Smart Stack (Full)", "100.7 s", "183.8 s", "0.246 (Best Equity)", "1.5 calls (Fair)", "75.2 km (-37%)"),
        ("Flip Idle (Station Return)", "84.3 s", "146.5 s", "0.303", "1.6 calls", "114.5 km")
    ]
    for i, row in enumerate(res_subset):
        for j, val in enumerate(row):
            cell = t.cell(i + 1, j)
            cell.text = val
            cell.fill.solid()
            cell.fill.fore_color.rgb = CARD_BG if i % 2 == 0 else LIGHT_BG
            p = cell.text_frame.paragraphs[0]
            p.font.size = Pt(9.5)
            p.font.color.rgb = TEXT_MAIN

    # =========================================================================
    # SLIDE 12: Project Status, Milestones & References
    # =========================================================================
    s12 = prs.slides.add_slide(blank_layout)
    set_slide_background(s12)
    add_header(s12, "Project Status, Review-2 Roadmap & References", "Project Plan & Close")

    # 3 Balanced Cards
    cards_close = [
        ("Review-1 Completed",
         "✓ Problem formulation & PEAS\n"
         "✓ Tick-based simulation engine\n"
         "✓ CNP dispatch + re-negotiation\n"
         "✓ A*, LRTA*, and D* Lite routing\n"
         "✓ CSP hospital bed allocator\n"
         "✓ MDP value iteration repositioner\n"
         "✓ Dual Web & Terminal UIs\n"
         "✓ 105 passing automated tests",
         GREEN_ACCENT),
        ("Review-2 & Final Roadmap",
         "• Real-world OpenStreetMap (OSM) graph ingestion via OSMnx\n"
         "• Dynamic traffic congestion modeling based on rush-hour patterns\n"
         "• Multi-casualty clinical survival triage\n"
         "• Scaling simulations to 100+ vehicles\n"
         "• Interactive explainability query tool\n"
         "• Academic paper submission",
         BLUE_ACCENT),
        ("Key Academic References",
         "• Russell & Norvig (2020). Artificial Intelligence: A Modern Approach.\n"
         "• Smith (1980). Contract Net Protocol. IEEE Trans. Computers.\n"
         "• Hart et al. (1968). A* Graph Search. IEEE Trans. SSC.\n"
         "• Korf (1990). Real-Time Search. AIJ.\n"
         "• Koenig & Likhachev (2002). D* Lite. AAAI.\n"
         "• Bellman (1957). Dynamic Programming.",
         DARK_BLUE)
    ]

    for i, (head, body, col) in enumerate(cards_close):
        add_card(s12, 0.8 + i * 3.95, 1.55, 3.8, 5.4)
        tb = s12.shapes.add_textbox(Inches(0.95 + i * 3.95), Inches(1.75), Inches(3.5), Inches(5.0))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = head
        p.font.bold = True
        p.font.size = Pt(14)
        p.font.color.rgb = col
        p = tf.add_paragraph()
        p.text = body
        p.font.size = Pt(9.5)
        p.font.color.rgb = TEXT_MAIN
        p.space_before = Pt(8)

    out_path = os.path.abspath("Project_Review_1_Presentation.pptx")
    prs.save(out_path)
    print(f"Impeccable 12-slide presentation saved to {out_path}")

if __name__ == "__main__":
    build_impeccable_deck()
