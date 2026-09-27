"""
Generate clean, modern, high-resolution vector-like diagram graphics for the presentation.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

def generate_architecture_diagram():
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=200)
    fig.patch.set_facecolor("#F8FAFC")
    ax.set_facecolor("#F8FAFC")
    ax.axis("off")

    # Define palette
    c_navy = "#1A365D"
    c_teal = "#0D9488"
    c_blue = "#2563EB"
    c_green = "#059669"
    c_purple = "#7C3AED"
    c_gray = "#64748B"
    c_card = "#FFFFFF"

    # Title
    ax.text(5, 5.2, "SYSTEM ARCHITECTURE: 4-LAYER VERIFIABLE AI PIPELINE",
            ha="center", va="center", fontsize=13, fontweight="bold", color=c_navy)

    # Layer 4: Presentation Layer
    r4 = patches.FancyBboxPatch((0.5, 3.9), 9.0, 0.95, boxstyle="round,pad=0.1",
                                fc=c_card, ec="#CBD5E1", lw=1.5)
    ax.add_patch(r4)
    ax.text(0.8, 4.4, "PRESENTATION LAYER", fontsize=10, fontweight="bold", color=c_blue)
    ax.text(3.5, 4.4, "FastAPI Web Dashboard (WebSockets + Canvas)", fontsize=9, color="#1E293B",
            bbox=dict(boxstyle="round,pad=0.3", fc="#EFF6FF", ec="#BFDBFE", lw=1))
    ax.text(7.2, 4.4, "Textual Terminal UI (Headless TUI)", fontsize=9, color="#1E293B",
            bbox=dict(boxstyle="round,pad=0.3", fc="#EFF6FF", ec="#BFDBFE", lw=1))

    # Arrow Down
    ax.annotate("", xy=(5.0, 3.75), xytext=(5.0, 3.9),
                arrowprops=dict(arrowstyle="->", color=c_gray, lw=2))

    # Layer 3: Contracts & Explainability
    r3 = patches.FancyBboxPatch((0.5, 2.85), 9.0, 0.75, boxstyle="round,pad=0.1",
                                fc=c_card, ec="#CBD5E1", lw=1.5)
    ax.add_patch(r3)
    ax.text(0.8, 3.25, "EXPLAINABILITY & API", fontsize=10, fontweight="bold", color=c_purple)
    ax.text(3.3, 3.25, "snapshot() [State]", fontsize=9, color="#475569",
            bbox=dict(boxstyle="round,pad=0.2", fc="#F5F3FF", ec="#DDD6FE"))
    ax.text(5.5, 3.25, "events_since() [Audit Log]", fontsize=9, color="#475569",
            bbox=dict(boxstyle="round,pad=0.2", fc="#F5F3FF", ec="#DDD6FE"))
    ax.text(7.8, 3.25, "Deterministic Replay", fontsize=9, color="#475569",
            bbox=dict(boxstyle="round,pad=0.2", fc="#F5F3FF", ec="#DDD6FE"))

    # Arrow Down
    ax.annotate("", xy=(5.0, 2.7), xytext=(5.0, 2.85),
                arrowprops=dict(arrowstyle="->", color=c_gray, lw=2))

    # Layer 2: Classical AI Core Algorithms
    r2 = patches.FancyBboxPatch((0.5, 1.45), 9.0, 1.15, boxstyle="round,pad=0.1",
                                fc=c_card, ec="#CBD5E1", lw=1.5)
    ax.add_patch(r2)
    ax.text(0.8, 2.35, "CLASSICAL AI ENGINE", fontsize=10, fontweight="bold", color=c_teal)
    
    # 4 Modules
    mods = [
        (0.8, 1.6, "CNP Dispatch\nAuction + Re-negotiation", c_teal, "#CCFBF1"),
        (3.1, 1.6, "Search & Routing\nA* · LRTA* · D* Lite", c_blue, "#DBEAFE"),
        (5.4, 1.6, "Hospital CSP\nMRV · LCV · Fwd Check", c_purple, "#EDE9FE"),
        (7.6, 1.6, "Fleet Relocation\nMDP Value Iteration", c_green, "#D1FAE5"),
    ]
    for x, y, txt, col, bg in mods:
        ax.text(x + 0.95, y + 0.35, txt, fontsize=8.5, fontweight="bold", color=col, ha="center", va="center",
                bbox=dict(boxstyle="round,pad=0.4", fc=bg, ec=col, lw=1))

    # Arrow Down
    ax.annotate("", xy=(5.0, 1.3), xytext=(5.0, 1.45),
                arrowprops=dict(arrowstyle="->", color=c_gray, lw=2))

    # Layer 1: Simulation Core
    r1 = patches.FancyBboxPatch((0.5, 0.4), 9.0, 0.75, boxstyle="round,pad=0.1",
                                fc=c_navy, ec=c_navy, lw=1)
    ax.add_patch(r1)
    ax.text(0.8, 0.78, "SIMULATION ENVIRONMENT", fontsize=10, fontweight="bold", color="#FFFFFF")
    ax.text(4.2, 0.78, "Urban Road Graph G=(V,E)", fontsize=8.5, color="#E2E8F0")
    ax.text(6.4, 0.78, "Tick Engine (Δt=2.0s)", fontsize=8.5, color="#E2E8F0")
    ax.text(8.3, 0.78, "Dynamic Hazards", fontsize=8.5, color="#E2E8F0")

    plt.tight_layout()
    out = "diagram_architecture.png"
    plt.savefig(out, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()
    print(f"Saved {out}")

def generate_cnp_diagram():
    fig, ax = plt.subplots(figsize=(10, 3.8), dpi=200)
    fig.patch.set_facecolor("#F8FAFC")
    ax.set_facecolor("#F8FAFC")
    ax.axis("off")

    c_navy = "#1A365D"
    c_teal = "#0D9488"
    c_blue = "#2563EB"
    c_orange = "#EA580C"
    c_green = "#059669"

    ax.text(5, 3.5, "CONTRACT NET PROTOCOL (CNP) WITH DYNAMIC RE-NEGOTIATION",
            ha="center", va="center", fontsize=12, fontweight="bold", color=c_navy)

    steps = [
        (0.6, 1.3, "1. ANNOUNCE", "911 call triage\nSeverity (1-5)\nService deadline", c_blue, "#EFF6FF"),
        (2.8, 1.3, "2. BID", "Eligible units submit:\nA* ETA, Distance\nStatus & Workload", c_teal, "#F0FDFA"),
        (5.0, 1.3, "3. EVALUATE", "Multi-criteria Utility:\nScore = w1·ETA + w2·Dist\n+ w3·Stat + w4·Load", c_navy, "#F8FAFC"),
        (7.2, 1.3, "4. AWARD", "Best bid wins contract\nDeterministic tie-break\nUnit begins transit", c_green, "#F0FDF4"),
    ]

    for x, y, title, desc, col, bg in steps:
        r = patches.FancyBboxPatch((x, y), 1.9, 1.7, boxstyle="round,pad=0.08",
                                   fc=bg, ec=col, lw=1.5)
        ax.add_patch(r)
        ax.text(x + 0.95, y + 1.4, title, fontsize=9.5, fontweight="bold", color=col, ha="center")
        ax.text(x + 0.95, y + 0.7, desc, fontsize=8, color="#334155", ha="center", va="center")

    # Connect arrows between steps
    for x_arr in [2.55, 4.75, 6.95]:
        ax.annotate("", xy=(x_arr + 0.2, 2.15), xytext=(x_arr - 0.05, 2.15),
                    arrowprops=dict(arrowstyle="->", color="#94A3B8", lw=2))

    # Re-negotiation banner at bottom
    rb = patches.FancyBboxPatch((0.6, 0.2), 8.5, 0.8, boxstyle="round,pad=0.08",
                                fc="#FFF7ED", ec=c_orange, lw=1.5)
    ax.add_patch(rb)
    ax.text(0.9, 0.6, "DYNAMIC IN-TRANSIT RE-NEGOTIATION (ANTI-THRASH GUARD):", fontsize=8.5, fontweight="bold", color=c_orange)
    ax.text(0.9, 0.35, "Periodic audit (every 5 ticks) • Challenger reassigns ONLY if ETA savings > 60s margin • 60-tick cooldown",
            fontsize=8, color="#7C2D12")

    plt.tight_layout()
    out = "diagram_cnp_flow.png"
    plt.savefig(out, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()
    print(f"Saved {out}")

def generate_search_diagram():
    fig, ax = plt.subplots(figsize=(10, 3.8), dpi=200)
    fig.patch.set_facecolor("#F8FAFC")
    ax.set_facecolor("#F8FAFC")
    ax.axis("off")

    c_navy = "#1A365D"
    c_blue = "#2563EB"
    c_purple = "#7C3AED"
    c_teal = "#0D9488"

    ax.text(5, 3.5, "SPECIALIZED GRAPH SEARCH & REPLANNING STRATEGIES",
            ha="center", va="center", fontsize=12, fontweight="bold", color=c_navy)

    methods = [
        (0.6, "A* SEARCH", "Primary Optimal Dispatch",
         "• Global search f(n) = g(n) + h(n)\n• Euclidean admissible & consistent\n• Mathematical optimality guarantee\n• Algorithm Arena benchmark",
         c_blue, "#EFF6FF"),
        (3.6, "LRTA*", "Real-Time Urgent Dispatch",
         "• Urgent triage (Severity 5: arrest/trauma)\n• Interleaved action & planning\n• Immediate movement (one step lookahead)\n• Heuristic update: h(s) ← max(h, c+h')",
         c_purple, "#F5F3FF"),
        (6.6, "D* LITE", "Incremental Roadblock Repair",
         "• Partial observability (hidden road hazards)\n• Backward search maintaining rhs & g\n• Repairs only affected nodes locally\n• Saves up to 80% search expansions",
         c_teal, "#F0FDFA")
    ]

    for x, title, subtitle, bullets, col, bg in methods:
        r = patches.FancyBboxPatch((x, 0.4), 2.7, 2.7, boxstyle="round,pad=0.1",
                                   fc=bg, ec=col, lw=1.5)
        ax.add_patch(r)
        ax.text(x + 1.35, 2.75, title, fontsize=10.5, fontweight="bold", color=col, ha="center")
        ax.text(x + 1.35, 2.45, subtitle, fontsize=8, fontweight="bold", color="#64748B", ha="center")
        ax.text(x + 0.2, 1.35, bullets, fontsize=8, color="#1E293B", va="center")

    plt.tight_layout()
    out = "diagram_search_methods.png"
    plt.savefig(out, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()
    print(f"Saved {out}")

if __name__ == "__main__":
    generate_architecture_diagram()
    generate_cnp_diagram()
    generate_search_diagram()
