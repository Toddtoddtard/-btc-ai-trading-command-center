"""Presentation timezone contracts; UTC source data must remain untouched."""
import subprocess
from pathlib import Path

import pandas as pd
from types import SimpleNamespace

from display_time import eastern_time, eastern_table, eastern_plotly


def test_winter_summer_and_midnight():
    assert eastern_time("2026-01-15T00:30:00Z") == "2026-01-14 07:30:00 PM EST"
    assert eastern_time("2026-07-15T00:30:00Z") == "2026-07-14 08:30:00 PM EDT"
    assert eastern_time("2026-01-15T05:00:00Z") == "2026-01-15 12:00:00 AM EST"
    assert eastern_time("2026-07-15T04:00:00Z") == "2026-07-15 12:00:00 AM EDT"
    assert eastern_time(None) == "—"
    assert eastern_time(pd.NaT) == "—"
    assert eastern_time("pending", fallback="pending") == "pending"


def test_naive_utc_dataframe_display_preserves_source_and_other_values():
    source = pd.DataFrame({"created_iso": ["2026-01-15 00:30:00", "2026-07-15 00:30:00"],
                           "expires_utc": pd.to_datetime(["2026-01-15 05:00", "2026-07-15 04:00"]),
                           "closes_iso": ["2026-01-15T05:00:00Z", "2026-07-15T04:00:00Z"],
                           "price": [83100, 83200], "opened_at": [1768453200, None]})
    original = source.copy(deep=True)
    display = eastern_table(source)
    pd.testing.assert_frame_equal(source, original)
    assert display["created_iso"].tolist() == ["2026-01-14 07:30:00 PM EST", "2026-07-14 08:30:00 PM EDT"]
    assert display["expires_ET"].tolist() == ["2026-01-15 12:00:00 AM EST", "2026-07-15 12:00:00 AM EDT"]
    assert display["closes_iso"].tolist() == display["expires_ET"].tolist()
    assert display["price"].tolist() == [83100, 83200]
    assert eastern_table(display)["created_iso"].tolist() == display["created_iso"].tolist()


def test_chart_ticks_and_hover_preserve_real_timestamps():
    xs = pd.to_datetime(["2026-07-15T00:30Z", "2026-07-15T00:31Z"])
    class Figure:
        def __init__(self):
            self.data = [SimpleNamespace(x=xs, type="candlestick")]
            self.layout = SimpleNamespace()
        def update_xaxes(self, **kwargs):
            self.layout.xaxis = SimpleNamespace(**kwargs)
        def update_layout(self, **kwargs):
            self.layout.__dict__.update(kwargs)
    fig = Figure()
    eastern_plotly(fig)
    assert list(fig.data[0].x) == list(xs)
    assert fig.layout.xaxis.ticktext[0] == "08:30 PM EDT"
    assert fig.data[0].text[0] == "2026-07-14 08:30:00 PM EDT"
    assert fig.data[0].hoverinfo == "text+y"


def test_browser_ticks_and_clock_ignore_device_timezone():
    source = Path("app.py").read_text()
    start = source.index('        const easternClock =')
    end = source.index('        function candleTrace(', start)
    script = source[start:end].replace('{{', '{').replace('}}', '}')
    script += '''
const assert=require('assert');
assert.equal(easternTime('2026-01-15T05:00:00Z'),'12:00:00 AM EST');
assert.equal(easternTime('2026-07-15T04:00:00Z'),'12:00:00 AM EDT');
const ticks=easternAxis([{time:'2026-07-15T00:30:00Z'}]);
assert(ticks.ticktext.every(t=>t.endsWith('EDT')));
assert(ticks.tickvals.every(t=>t.endsWith('Z')));
'''
    # Python source doubles backslashes inside the containing f-string.
    script = script.replace('\\\\d', '\\d')
    result = subprocess.run(["node", "-e", script], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_sidebar_close_label_uses_eastern_time():
    import ast
    import re
    tree = ast.parse(Path("app.py").read_text())
    html = next(ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and any(isinstance(target, ast.Name) and target.id == "_kalshi_timer_html"
                        for target in node.targets))
    script = re.search(r"<script>(.*?)</script>", html, re.S)[1]
    script = script.replace("__CLOSE_MS__", str(int(pd.Timestamp("2026-01-15T05:00Z").timestamp() * 1000)))
    script = script.replace("__TICKER__", "KXBTC15M")
    harness = '''
const assert=require('assert');
const elements={};
global.document={getElementById:id=>elements[id]||(elements[id]={style:{}})};
Date.now=()=>Date.parse('2026-01-15T04:55:00Z');
global.setInterval=()=>0;
'''
    checks = '''
assert.equal(elements['close-time'].textContent,'Closes 12:00 AM EST');
assert.equal(elements.countdown.textContent,'05:00');
'''
    result = subprocess.run(["node", "-e", harness + script + checks], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_timestamp_columns_preserve_open_and_pending_statuses():
    view=eastern_table(pd.DataFrame({'Closed':['OPEN','pending',None]}))
    assert view['Closed'].tolist()==['OPEN','pending','—']
