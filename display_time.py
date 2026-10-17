"""Eastern Time presentation helpers; persisted/feed timestamps remain UTC."""

from numbers import Real
import re

import pandas as pd

EASTERN = "America/New_York"


def eastern_timestamp(value):
    """Interpret naive source dates as UTC and numeric timestamps as epoch seconds."""
    if value is None or pd.isna(value) or value == "":
        return pd.NaT
    if isinstance(value, str):
        value = re.sub(r" EST$", " -0500", value)
        value = re.sub(r" EDT$", " -0400", value)
    return pd.to_datetime(value, unit="s" if isinstance(value, Real) else None,
                          utc=True, errors="coerce").tz_convert(EASTERN)


def eastern_time(value, *, clock_only=False, fallback="—"):
    stamp = eastern_timestamp(value)
    if pd.isna(stamp):
        return fallback
    return stamp.strftime("%I:%M:%S %p %Z" if clock_only else "%Y-%m-%d %I:%M:%S %p %Z")


def eastern_table(frame):
    """Return a display copy of known timestamp columns, preserving source values."""
    view = frame.copy()
    names = {"time", "timestamp", "created_iso", "expires_utc", "opened", "closed",
             "expires", "opened utc", "expires utc", "opened et", "expires et"}
    for column in view.columns:
        name = str(column).lower()
        if (name in names or name.endswith(("_at", "_utc", "_time", "_timestamp", "_iso"))
                or pd.api.types.is_datetime64_any_dtype(view[column])):
            view[column] = view[column].map(lambda value: eastern_time(
                value, fallback=value if isinstance(value, str) and value.upper() in {"OPEN", "PENDING"} else "—"))
            if "utc" in name:
                view = view.rename(columns={column: re.sub("utc", "ET", str(column), flags=re.I)})
    return view


def eastern_plotly(fig):
    """Format date ticks and hover text in ET without moving data or chart shapes."""
    stamps = []
    for trace in fig.data:
        if trace.x is None or not len(trace.x):
            continue
        # Numeric/category axes are not timestamps.
        if isinstance(trace.x[0], Real):
            continue
        times = pd.to_datetime(trace.x, utc=True, errors="coerce")
        if times.isna().all():
            continue
        stamps.extend(times.dropna())
        labels = [eastern_time(value) for value in times]
        if trace.type in {"candlestick", "ohlc"}:
            trace.text = labels
            trace.hoverinfo = "text+y"
        elif hasattr(trace, "hovertemplate"):
            # Preserve value formatting in custom MACD templates.
            template = trace.hovertemplate or "%{y}<extra>%{fullData.name}</extra>"
            template = re.sub(r"%\{x(?:\|[^}]*)?\}", "%{text}", template)
            trace.text = labels
            trace.hovertemplate = template if "%{text}" in template else "%{text}<br>" + template
    if stamps:
        unique = sorted(set(stamps))
        stride = max(1, (len(unique) + 7) // 8)
        ticks = unique[::stride]
        fig.update_xaxes(tickmode="array", tickvals=ticks,
                         ticktext=[value.tz_convert(EASTERN).strftime("%I:%M %p %Z") for value in ticks],
                         title_text="Time (ET)")
        # Plotly's unified date header cannot apply a named timezone.
        fig.update_layout(hovermode="closest")
    return fig
