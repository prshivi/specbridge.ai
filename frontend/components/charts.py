from __future__ import annotations

import plotly.graph_objects as go


STATUS_COLORS = {
    "excellent": "#34d399",
    "good": "#84cc16",
    "caution": "#fbbf24",
    "critical": "#fb7185",
}


def health_gauge(score: float, status: str) -> go.Figure:
    color = STATUS_COLORS.get(status, "#60a5fa")
    figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=score,
            number={"suffix": "/100", "font": {"size": 38, "color": "#f8fafc"}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#64748b"},
                "bar": {"color": color, "thickness": 0.3},
                "bgcolor": "rgba(30,41,59,.65)",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 50], "color": "rgba(251,113,133,.10)"},
                    {"range": [50, 70], "color": "rgba(251,191,36,.10)"},
                    {"range": [70, 85], "color": "rgba(132,204,22,.10)"},
                    {"range": [85, 100], "color": "rgba(52,211,153,.10)"},
                ],
            },
        )
    )
    figure.update_layout(
        height=260,
        margin={"l": 30, "r": 30, "t": 30, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return figure


def health_radar(metrics: list[dict]) -> go.Figure:
    labels = [item["label"] for item in metrics]
    values = [item["score"] for item in metrics]
    figure = go.Figure(
        go.Scatterpolar(
            r=[*values, values[0]],
            theta=[*labels, labels[0]],
            fill="toself",
            fillcolor="rgba(99,102,241,.24)",
            line={"color": "#60a5fa", "width": 3},
        )
    )
    figure.update_layout(
        height=360,
        margin={"l": 50, "r": 50, "t": 30, "b": 30},
        paper_bgcolor="rgba(0,0,0,0)",
        font={"color": "#cbd5e1"},
        polar={
            "bgcolor": "rgba(15,23,42,.30)",
            "radialaxis": {
                "range": [0, 100],
                "gridcolor": "rgba(148,163,184,.18)",
            },
            "angularaxis": {"gridcolor": "rgba(148,163,184,.14)"},
        },
        showlegend=False,
    )
    return figure
