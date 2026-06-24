"""
Performance timing context, recording, and summary formatting.
"""

import time
from typing import Any, Dict, List


def fn_format_timing_table(rows: List[Dict[str, Any]], total_duration: float = 0.0) -> str:
    """
    Format timing measurements as a fixed-width table string with percentage breakdown.
    """
    if total_duration <= 0 and rows:
        total_duration = rows[-1].get("cumulative_seconds", 0.0)

    headers = ("Step", "Section", "Elapsed (s)", "Cumulative (s)", "% of Total")
    formatted_rows = [
        (
            str(row["step"]),
            str(row["section"]),
            f'{row["elapsed_seconds"]:.6f}',
            f'{row["cumulative_seconds"]:.6f}',
            f'{(row["elapsed_seconds"] / total_duration * 100):.2f}%' if total_duration > 0 else "0.00%",
        )
        for row in rows
    ]

    widths = []
    for column_index, header in enumerate(headers):
        column_lengths = [len(header)]
        column_lengths.extend(len(row[column_index]) for row in formatted_rows)
        widths.append(max(column_lengths))

    def _format_row(values: Any) -> str:
        return "| " + " | ".join(
            value.ljust(widths[idx]) for idx, value in enumerate(values)
        ) + " |"

    divider = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    table_lines = [divider, _format_row(headers), divider]
    table_lines.extend(_format_row(row) for row in formatted_rows)
    table_lines.append(divider)
    return "\n".join(table_lines)


def fn_create_timing_context() -> Dict[str, Any]:
    """
    Create a timing context for tracking execution performance.
    """
    return {
        "start_time": time.perf_counter(),
        "section_time": time.perf_counter(),
        "started_at": time.strftime('%Y-%m-%d %H:%M:%S'),
        "measurements": [],
    }


def fn_record_timing(
    timing_context: Dict[str, Any],
    section_name: str,
) -> None:
    """
    Record a timing measurement for a completed section.
    """
    current_time = time.perf_counter()
    timing_context["measurements"].append(
        {
            "step": len(timing_context["measurements"]) + 1,
            "section": section_name,
            "elapsed_seconds": round(current_time - timing_context["section_time"], 6),
            "cumulative_seconds": round(current_time - timing_context["start_time"], 6),
        }
    )
    timing_context["section_time"] = current_time


def fn_finalize_timing_summary(
    timing_context: Dict[str, Any],
    final_section_name: str,
    entity_label: str = "CONSOLIDATION",
) -> Dict[str, Any]:
    """
    Finalize timing measurements and return a comprehensive summary
    with bottleneck analysis.

    Parameters:
    -----------
    timing_context : Dict[str, Any]
        Timing context from fn_create_timing_context.
    final_section_name : str
        Name of the final section to record.
    entity_label : str
        Label used in the summary header (e.g. "LANDCO CONSOLIDATION").
    """
    fn_record_timing(timing_context, final_section_name)
    measurements = timing_context["measurements"]
    total_duration = (
        measurements[-1]["cumulative_seconds"] if measurements else 0.0
    )
    timing_table = fn_format_timing_table(measurements, total_duration)

    # --- Bottleneck Analysis: Top 5 slowest steps ---
    sorted_by_elapsed = sorted(measurements, key=lambda r: r["elapsed_seconds"], reverse=True)
    top_bottlenecks = sorted_by_elapsed[:5]
    bottleneck_lines = ["", "Top 5 Bottlenecks (slowest steps):"]
    bottleneck_lines.append("-" * 70)
    for rank, row in enumerate(top_bottlenecks, 1):
        pct = (row["elapsed_seconds"] / total_duration * 100) if total_duration > 0 else 0.0
        bottleneck_lines.append(
            f"  #{rank}  {row['section']:<55s} "
            f"{row['elapsed_seconds']:.6f}s  ({pct:.2f}%)"
        )
    bottleneck_lines.append("-" * 70)

    summary_text = "\n".join(
        [
            "",
            "=" * 80,
            f"{entity_label} - DETAILED TIMING SUMMARY",
            "=" * 80,
            f"Started at : {timing_context['started_at']}",
            f"Total duration: {round(total_duration, 6):.6f} seconds",
            f"Total steps   : {len(measurements)}",
            "",
            timing_table,
        ]
        + bottleneck_lines
        + ["=" * 80, ""]
    )
    return {
        "started_at": timing_context["started_at"],
        "total_duration_seconds": round(total_duration, 6),
        "rows": measurements,
        "table": timing_table,
        "bottlenecks": top_bottlenecks,
        "summary_text": summary_text,
    }
