import math
import sqlite3
import time
import json
from urllib.parse import quote
from urllib.request import Request, urlopen


def fetch_settled_result(ticker):
    """Only an official, final binary result can settle a paper contract."""
    try:
        url = 'https://external-api.kalshi.com/trade-api/v2/markets/' + quote(ticker, safe='')
        with urlopen(Request(url, headers={'Accept': 'application/json'}), timeout=4) as response:
            market = json.load(response).get('market', {})
        if market.get('ticker') != ticker or market.get('status') not in {'settled', 'finalized'}:
            return None
        result = str(market.get('result', '')).lower()
        return result if result in {'yes', 'no'} else None
    except Exception:
        return None

GENERAL_TAKER_FEE_RATE = 0.07
MAX_ENTRY_PRICE = 0.75
# Match the master decision's extreme-opposing-odds veto. A selected side
# priced below 20% is a lottery-style thesis, not an approved SCALP setup.
MIN_SCALP_MARKET_PROBABILITY = 0.20
LOCK_MIN_CONFIDENCE = 0.95
MAX_SCALPS_PER_MARKET = 10
MAX_LOCKS_PER_MARKET = 1
MAX_SCALP_LOSSES_PER_MARKET = 2

# Versioned forward-performance baseline.  Trades opened before this instant
# remain in the lifetime ledger, but cannot distort the scorecard or safety
# gate for the loss-loop safeguards shipped in commit 40ebf83.
POST_FIX_START_TS = 1788909457.0  # 2026-09-08 23:17:37 UTC
POST_FIX_LABEL = "Loss-loop safeguards v1"
POST_FIX_GATE_TRADES = 50
POST_FIX_VALIDATION_TRADES = 100
POST_FIX_PROFIT_FACTOR_FLOOR = 1.15
POST_FIX_MAX_DRAWDOWN_PCT = 0.10
UNPROVEN_POSITION_CAP = 0.02

# SCALP positions require a forecast and realized move worth at least a 10%
# gross return on entry cost (for example, 50% to 55%), before fees.  This is
# deliberately lower than the original 20% gate so moderate, correctly-priced
# Kalshi opportunities can enter while the 75% entry cap and fee accounting
# continue to prevent expensive or negative-value fills.
SCALP_MIN_GROSS_RETURN = 0.10
# After the minimum return is reached, hold only when the live forecast still
# shows meaningful additional upside beyond the executable exit bid.
SCALP_MIN_REMAINING_EDGE = 0.01
SCALP_STOP_LOSS_POINTS = 0.05
OPPOSITE_SIGNAL_CONFIRM_SECONDS = 10.0

# A LOCK keeps its original direction, but its paper position realizes the
# near-certain payout early whenever its executable bid reaches 95%.
LOCK_TAKE_PROFIT_PRICE = 0.95


def _f(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def kalshi_taker_fee(contracts, price):
    """General Kalshi taker-fee model: ceil(0.07*C*P*(1-P)) to cents."""
    c = max(0, int(contracts or 0))
    p = min(1.0, max(0.0, _f(price, 0.0)))
    raw = GENERAL_TAKER_FEE_RATE * c * p * (1.0 - p)
    return math.ceil(raw * 100.0 - 1e-12) / 100.0


def lock_target_pnl(contracts, entry_price):
    """Fee-aware P/L if a LOCK enters now and exits at its 95% bid target."""
    c = max(0, int(contracts or 0))
    entry = min(1.0, max(0.0, _f(entry_price, 0.0)))
    entry_cost = entry * c + kalshi_taker_fee(c, entry)
    exit_proceeds = (
        LOCK_TAKE_PROFIT_PRICE * c
        - kalshi_taker_fee(c, LOCK_TAKE_PROFIT_PRICE)
    )
    return exit_proceeds - entry_cost


def _connect(db_path, starting_cash=500.0):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kalshi_paper_account (
            id INTEGER PRIMARY KEY CHECK(id=1),
            cash REAL NOT NULL,
            starting_cash REAL NOT NULL,
            updated_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kalshi_paper_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            side TEXT NOT NULL,
            strategy TEXT NOT NULL,
            status TEXT NOT NULL,
            opened_at REAL NOT NULL,
            expires_at REAL,
            target_price REAL,
            spot_entry_price REAL,
            entry_price REAL NOT NULL,
            contracts INTEGER NOT NULL,
            entry_fee REAL NOT NULL,
            last_mark REAL,
            closed_at REAL,
            exit_price REAL,
            exit_fee REAL DEFAULT 0,
            pnl REAL,
            exit_reason TEXT,
            opposite_since REAL
        )
    """)
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(kalshi_paper_positions)")
    }
    if "opposite_since" not in columns:
        conn.execute(
            "ALTER TABLE kalshi_paper_positions ADD COLUMN opposite_since REAL"
        )
    if "spot_entry_price" not in columns:
        conn.execute(
            "ALTER TABLE kalshi_paper_positions ADD COLUMN spot_entry_price REAL"
        )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kalshi_paper_rearm (
            ticker TEXT NOT NULL,
            side TEXT NOT NULL CHECK(side IN ('YES', 'NO')),
            armed INTEGER NOT NULL DEFAULT 1,
            updated_at REAL NOT NULL,
            PRIMARY KEY(ticker, side)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kalshi_decision_locks (
            ticker TEXT PRIMARY KEY,
            side TEXT NOT NULL CHECK(side IN ('YES', 'NO')),
            locked_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )
    """)
    conn.execute(
        "INSERT OR IGNORE INTO kalshi_paper_account(id,cash,starting_cash,updated_at) VALUES(1,?,?,?)",
        (float(starting_cash), float(starting_cash), time.time()),
    )
    conn.commit()
    return conn


def _side_from_action(action):
    a = str(action or "").upper()
    if a in {"SCALP UP", "LOCK UP"}:
        return "YES"
    if a in {"SCALP DOWN", "LOCK DOWN"}:
        return "NO"
    return None


def _quote(decision, side, ask=False):
    yes_bid = _f(decision.get("yes_bid_dollars"))
    yes_ask = _f(decision.get("yes_ask_dollars"))
    no_bid = _f(decision.get("no_bid_dollars"))
    no_ask = _f(decision.get("no_ask_dollars"))
    if no_ask is None and yes_bid is not None:
        no_ask = 1.0 - yes_bid
    if no_bid is None and yes_ask is not None:
        no_bid = 1.0 - yes_ask
    value = (yes_ask if ask else yes_bid) if side == "YES" else (no_ask if ask else no_bid)
    if value is None or not 0 <= value <= 1 or (ask and not 0 < value < 1):
        return None
    return value


def _selected_side_market_probability(decision, side):
    """Return the executable selected-side midpoint used by the odds veto."""
    bid = _quote(decision, side, ask=False)
    ask = _quote(decision, side, ask=True)
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2.0


def _projected_scalp_exit(decision):
    """Return the model's selected-side fair value used for SCALP qualification."""
    projected = _f(decision.get("scalp_projected_exit_price"))
    if projected is not None and projected > 1.0:
        projected /= 100.0
    return projected if projected is not None and 0.0 <= projected <= 1.0 else None


def _decision_confidence(decision):
    """Return confidence as a 0..1 probability, accepting legacy percentages."""
    confidence = _f(decision.get("confidence"), 0.0)
    if confidence > 1.0:
        confidence /= 100.0
    return min(1.0, max(0.0, confidence))


def _strategy_entry_count(conn, ticker, strategy):
    return int(conn.execute(
        """SELECT COUNT(*) AS count FROM kalshi_paper_positions
           WHERE ticker=? AND strategy=?""",
        (str(ticker), str(strategy)),
    ).fetchone()["count"])


def _strategy_loss_count(conn, ticker, strategy):
    return int(conn.execute(
        """SELECT COUNT(*) AS count FROM kalshi_paper_positions
           WHERE ticker=? AND strategy=? AND status='CLOSED' AND pnl<0""",
        (str(ticker), str(strategy)),
    ).fetchone()["count"])


def _scalp_is_armed(conn, ticker, side):
    row = conn.execute(
        "SELECT armed FROM kalshi_paper_rearm WHERE ticker=? AND side=?",
        (str(ticker), str(side)),
    ).fetchone()
    return row is None or bool(row["armed"])


def _set_scalp_armed(conn, ticker, side, armed):
    conn.execute(
        """INSERT INTO kalshi_paper_rearm(ticker,side,armed,updated_at)
           VALUES(?,?,?,?)
           ON CONFLICT(ticker,side) DO UPDATE SET
               armed=excluded.armed, updated_at=excluded.updated_at""",
        (str(ticker), str(side), int(bool(armed)), time.time()),
    )


def _refresh_scalp_rearm(conn, ticker, current_side):
    """A closed scalp side rearms only after its signal disappears or flips."""
    if not ticker:
        return
    if current_side is None:
        conn.execute(
            "UPDATE kalshi_paper_rearm SET armed=1,updated_at=? WHERE ticker=?",
            (time.time(), str(ticker)),
        )
    else:
        other = "NO" if current_side == "YES" else "YES"
        _set_scalp_armed(conn, ticker, other, True)


def _performance_from_rows(rows, starting_cash):
    """Summarize exact Kalshi paper fills in chronological order."""
    pnls = [float(row["pnl"]) for row in rows]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (
        gross_profit / gross_loss
        if gross_loss
        else (math.inf if gross_profit else None)
    )
    equity = float(starting_cash)
    peak = equity
    max_drawdown_pct = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown_pct = max(max_drawdown_pct, (peak - equity) / peak)
    samples = len(pnls)
    return {
        "label": POST_FIX_LABEL,
        "start_ts": POST_FIX_START_TS,
        "samples": samples,
        "markets": len({str(row["ticker"]) for row in rows}),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / samples if samples else None,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "total_pnl": sum(pnls),
        "expectancy": sum(pnls) / samples if samples else None,
        "fees": sum(
            float(row["entry_fee"] or 0.0) + float(row["exit_fee"] or 0.0)
            for row in rows
        ),
        "max_drawdown_pct": max_drawdown_pct,
        "gate_sample_target": POST_FIX_GATE_TRADES,
        "validation_sample_target": POST_FIX_VALIDATION_TRADES,
    }


def paper_performance_since_update(
    db_path, starting_cash=500.0, strategy=None, opened_since=POST_FIX_START_TS
):
    """Return a version-isolated Kalshi execution scorecard.

    This uses the authoritative contract ledger, including executable entry and
    exit prices, recorded fees, and official settlement outcomes.
    """
    conn = _connect(db_path, starting_cash)
    try:
        params = [float(opened_since)]
        where = (
            "status='CLOSED' AND pnl IS NOT NULL AND opened_at>=?"
        )
        if strategy:
            where += " AND strategy=?"
            params.append(str(strategy).upper())
        rows = conn.execute(
            f"""SELECT ticker,pnl,entry_fee,exit_fee
                FROM kalshi_paper_positions
                WHERE {where}
                ORDER BY closed_at ASC,id ASC""",
            params,
        ).fetchall()
        result = _performance_from_rows(rows, starting_cash)
        result["strategy"] = str(strategy).upper() if strategy else "ALL"
        return result
    finally:
        conn.close()


def scalp_profitability_gate(db_path, starting_cash=500.0):
    """Pause new SCALPs only after a meaningful post-fix Kalshi sample."""
    performance = paper_performance_since_update(
        db_path, starting_cash, strategy="SCALP"
    )
    samples = performance["samples"]
    reasons = []
    if samples >= POST_FIX_GATE_TRADES:
        pf = performance["profit_factor"]
        if pf is None or pf < POST_FIX_PROFIT_FACTOR_FLOOR:
            reasons.append(
                f"profit factor below {POST_FIX_PROFIT_FACTOR_FLOOR:.2f}"
            )
        if performance["expectancy"] is None or performance["expectancy"] <= 0:
            reasons.append("expectancy is not positive")
        if performance["max_drawdown_pct"] > POST_FIX_MAX_DRAWDOWN_PCT:
            reasons.append(
                f"drawdown above {POST_FIX_MAX_DRAWDOWN_PCT * 100:.0f}%"
            )
    approved = samples < POST_FIX_GATE_TRADES or not reasons
    if samples < POST_FIX_GATE_TRADES:
        status = "COLLECTING EVIDENCE"
    elif reasons:
        status = "SCALPS PAUSED"
    elif samples < POST_FIX_VALIDATION_TRADES:
        status = "PROVISIONAL PASS"
    else:
        status = "VALIDATED PASS"
    return {
        "approved": approved,
        "status": status,
        "reason": "; ".join(reasons) if reasons else "Kalshi safeguards satisfied",
        "performance": performance,
    }


def open_position(db_path, starting_cash, decision, risk, spot_price):
    side = _side_from_action(decision.get("action"))
    if side is None or not bool(risk.get("approved")):
        return None
    ticker = str(decision.get("kalshi_ticker") or "")
    if not ticker:
        return None
    strategy = "LOCK" if str(decision.get("action", "")).upper().startswith("LOCK") else "SCALP"
    if strategy == "SCALP" and not scalp_profitability_gate(
        db_path, starting_cash
    )["approved"]:
        return None
    if strategy == "LOCK" and _decision_confidence(decision) < LOCK_MIN_CONFIDENCE:
        return None
    entry = _quote(decision, side, ask=True)
    if entry is None or (strategy == "SCALP" and entry > MAX_ENTRY_PRICE):
        return None
    if strategy == "SCALP":
        market_probability = _selected_side_market_probability(decision, side)
        if (
            market_probability is None
            or market_probability < MIN_SCALP_MARKET_PROBABILITY
        ):
            return None
        projected_exit = _projected_scalp_exit(decision)
        required_exit = entry * (1.0 + SCALP_MIN_GROSS_RETURN)
        if projected_exit is None or projected_exit < required_exit - 1e-12:
            return None
    now = time.time()
    expires_at = _f(decision.get('kalshi_close_ts'))
    if expires_at is None:
        remain = _f(decision.get('seconds_remaining'))
        expires_at = now + remain if remain is not None else None
    if expires_at is None or expires_at <= now:
        return None
    post_fix = paper_performance_since_update(db_path, starting_cash)
    exposure_cap = (
        UNPROVEN_POSITION_CAP
        if post_fix["samples"] < POST_FIX_VALIDATION_TRADES
        else 0.25
    )
    conn = _connect(db_path, starting_cash)
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT 1 FROM kalshi_paper_positions WHERE status='OPEN' LIMIT 1").fetchone():
            return None
        prior_entries = _strategy_entry_count(conn, ticker, strategy)
        if strategy == "SCALP" and prior_entries >= MAX_SCALPS_PER_MARKET:
            return None
        if strategy == "LOCK" and prior_entries >= MAX_LOCKS_PER_MARKET:
            return None
        if (
            strategy == "SCALP"
            and _strategy_loss_count(conn, ticker, strategy) >= MAX_SCALP_LOSSES_PER_MARKET
        ):
            return None
        if strategy == "SCALP" and not _scalp_is_armed(conn, ticker, side):
            return None
        acct = conn.execute("SELECT cash FROM kalshi_paper_account WHERE id=1").fetchone()
        cash = float(acct["cash"])
        pct = min(exposure_cap, max(0.0, _f(risk.get("position_pct"), 0.0)))
        budget = cash * pct
        contracts = int(budget // max(entry, 0.01))
        while contracts > 0 and entry * contracts + kalshi_taker_fee(contracts, entry) > min(cash, budget):
            contracts -= 1
        if contracts < 1:
            return None
        fee = kalshi_taker_fee(contracts, entry)
        total_cost = entry * contracts + fee
        if strategy == "LOCK" and lock_target_pnl(contracts, entry) <= 1e-12:
            return None
        now = time.time()
        expires_at = _f(decision.get("kalshi_close_ts"))
        if expires_at is None:
            remain = _f(decision.get("seconds_remaining"))
            expires_at = now + remain if remain is not None else None
        conn.execute("UPDATE kalshi_paper_account SET cash=?,updated_at=? WHERE id=1", (cash-total_cost, now))
        conn.execute("""
            INSERT INTO kalshi_paper_positions(
                ticker,side,strategy,status,opened_at,expires_at,target_price,
                spot_entry_price,entry_price,contracts,entry_fee,last_mark
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            ticker, side, strategy, "OPEN", now, expires_at,
            _f(decision.get("target_price")), _f(spot_price), entry, contracts,
            fee, _quote(decision, side, ask=False),
        ))
        conn.commit()
        direction = "UP" if side == "YES" else "DOWN"
        return {
            "event": True,
            "message": (
                f"Opened PAPER {strategy} {direction} • Amount: ${total_cost:,.2f} • "
                f"Kalshi entry: {entry * 100:.0f}%"
            ),
        }
    finally:
        conn.close()


def _close(conn, row, exit_price, reason, charge_exit_fee=True):
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    row = conn.execute("SELECT * FROM kalshi_paper_positions WHERE id=? AND status='OPEN'", (int(row['id']),)).fetchone()
    if row is None:
        conn.rollback()
        return {'event': False, 'message': 'Paper position already closed'}
    exit_price = min(1.0, max(0.0, float(exit_price)))
    contracts = int(row["contracts"])
    exit_fee = kalshi_taker_fee(contracts, exit_price) if charge_exit_fee else 0.0
    proceeds = exit_price * contracts - exit_fee
    basis = float(row["entry_price"]) * contracts + float(row["entry_fee"])
    pnl = proceeds - basis
    cash = float(conn.execute("SELECT cash FROM kalshi_paper_account WHERE id=1").fetchone()["cash"])
    now = time.time()
    conn.execute("UPDATE kalshi_paper_account SET cash=?,updated_at=? WHERE id=1", (cash+proceeds, now))
    conn.execute("""
        UPDATE kalshi_paper_positions
        SET status='CLOSED',closed_at=?,exit_price=?,exit_fee=?,pnl=?,exit_reason=?,last_mark=?
        WHERE id=?
    """, (now, exit_price, exit_fee, pnl, reason, exit_price, int(row["id"])))
    if str(row["strategy"]).upper() == "SCALP":
        _set_scalp_armed(conn, row["ticker"], row["side"], False)
    conn.commit()
    return {"event": True, "message": f"Closed PAPER {row['strategy']} {row['side']} {row['ticker']} @ {exit_price:.2f} | P/L {pnl:+.2f}"}


def register_decision_lock(db_path, ticker, side, expires_at, starting_cash=500.0):
    """Atomically establish one immutable direction for a Kalshi window."""
    ticker = str(ticker or "").strip()
    side = str(side or "").upper().strip()
    side = "YES" if side in {"YES", "UP", "LOCK UP"} else "NO" if side in {"NO", "DOWN", "LOCK DOWN"} else ""
    expiry = _f(expires_at)
    now = time.time()
    if not ticker or not side or expiry is None or expiry <= now:
        return None

    conn = _connect(db_path, starting_cash)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM kalshi_decision_locks WHERE expires_at<=?", (now,))
        conn.execute(
            """INSERT OR IGNORE INTO kalshi_decision_locks(
                   ticker,side,locked_at,expires_at
               ) VALUES(?,?,?,?)""",
            (ticker, side, now, expiry),
        )
        row = conn.execute(
            "SELECT side FROM kalshi_decision_locks WHERE ticker=? AND expires_at>?",
            (ticker, now),
        ).fetchone()
        conn.commit()
        return row["side"] if row else None
    finally:
        conn.close()


def persistent_lock_side(db_path, ticker=None, starting_cash=500.0):
    """Return the immutable side for this window, even without a paper entry."""
    ticker = str(ticker or "").strip()
    now = time.time()
    conn = _connect(db_path, starting_cash)
    try:
        if ticker:
            row = conn.execute(
                """SELECT side FROM kalshi_decision_locks
                   WHERE ticker=? AND expires_at>?
                   ORDER BY locked_at DESC LIMIT 1""",
                (ticker, now),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT side FROM kalshi_decision_locks
                   WHERE expires_at>?
                   ORDER BY locked_at DESC LIMIT 1""",
                (now,),
            ).fetchone()
        if row:
            return row["side"]

        # Compatibility for LOCK paper positions opened before this table existed.
        if ticker:
            legacy = conn.execute(
                """SELECT side FROM kalshi_paper_positions
                   WHERE status='OPEN' AND strategy='LOCK' AND ticker=?
                     AND (expires_at IS NULL OR expires_at>?)
                   ORDER BY id DESC LIMIT 1""",
                (ticker, now),
            ).fetchone()
        else:
            legacy = conn.execute(
                """SELECT side FROM kalshi_paper_positions
                   WHERE status='OPEN' AND strategy='LOCK'
                     AND (expires_at IS NULL OR expires_at>?)
                   ORDER BY id DESC LIMIT 1""",
                (now,),
            ).fetchone()
        return legacy["side"] if legacy else None
    finally:
        conn.close()


def manage_kalshi_paper_cycle(db_path, starting_cash, decision, risk, spot_price, enabled=True, settlement_reader=None):
    conn = _connect(db_path, starting_cash)
    try:
        row = conn.execute("SELECT * FROM kalshi_paper_positions WHERE status='OPEN' ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            side = row["side"]
            same_ticker = str(decision.get("kalshi_ticker") or "") == str(row["ticker"])
            mark = _quote(decision, side, ask=False) if same_ticker else None
            if mark is not None:
                conn.execute("UPDATE kalshi_paper_positions SET last_mark=? WHERE id=?", (mark, int(row["id"])))
                conn.commit()
            now = time.time()
            expired = row["expires_at"] is not None and now >= float(row["expires_at"])
            if expired:
                result = (settlement_reader or fetch_settled_result)(str(row['ticker']))
                if result not in {'yes', 'no'}:
                    return {'event': False, 'message': 'Awaiting official Kalshi settlement: ' + str(row['ticker'])}
                payoff = float(side.lower() == result)
                return _close(conn, row, payoff, 'OFFICIAL_SETTLEMENT:' + result, charge_exit_fee=False)
            # LOCK direction remains immutable, but bank the position once its
            # executable bid reaches 95% instead of risking the final five cents.
            if row["strategy"] == "LOCK" and mark is not None and mark >= LOCK_TAKE_PROFIT_PRICE:
                return _close(conn, row, mark, "LOCK_BID_95_PCT")
            # Opposite master/whale signals remain learning inputs for LOCK.
            if row["strategy"] == "SCALP" and mark is not None:
                action_side = _side_from_action(decision.get("action"))
                entry_price = float(row["entry_price"])
                price_gain = mark - entry_price
                projected_exit = _projected_scalp_exit(decision)
                sees_more_upside = (
                    action_side == side
                    and projected_exit is not None
                    and projected_exit >= mark + SCALP_MIN_REMAINING_EDGE - 1e-12
                )
                if (
                    price_gain >= entry_price * SCALP_MIN_GROSS_RETURN - 1e-12
                    and not sees_more_upside
                ):
                    return _close(
                        conn,
                        row,
                        mark,
                        "TAKE_PROFIT_AI_UPSIDE_EXHAUSTED",
                    )
                price_loss = float(row["entry_price"]) - mark
                if price_loss >= SCALP_STOP_LOSS_POINTS - 1e-12:
                    return _close(conn, row, mark, "STOP_LOSS_5_POINTS")
                opposite_since = _f(row["opposite_since"])
                if action_side and action_side != side:
                    if opposite_since is None:
                        conn.execute(
                            "UPDATE kalshi_paper_positions SET opposite_since=? WHERE id=?",
                            (now, int(row["id"])),
                        )
                        conn.commit()
                    elif now - opposite_since >= OPPOSITE_SIGNAL_CONFIRM_SECONDS:
                        return _close(conn, row, mark, "CONFIRMED_OPPOSITE_SIGNAL")
                elif opposite_since is not None:
                    conn.execute(
                        "UPDATE kalshi_paper_positions SET opposite_since=NULL WHERE id=?",
                        (int(row["id"]),),
                    )
                    conn.commit()
            return {"event": False, "message": f"Holding PAPER {row['strategy']} {row['side']} {row['ticker']}"}
    finally:
        conn.close()
    if not enabled:
        return {'event': False, 'message': 'AUTO PAPER paused; existing positions remain managed'}
    entry_side = _side_from_action(decision.get("action"))
    entry_price = _quote(decision, entry_side, ask=True) if entry_side else None
    ticker = str(decision.get("kalshi_ticker") or "")
    rearm_conn = _connect(db_path, starting_cash)
    try:
        _refresh_scalp_rearm(rearm_conn, ticker, entry_side)
        rearm_conn.commit()
    finally:
        rearm_conn.close()
    action = str(decision.get("action", "")).upper()
    strategy = "LOCK" if action.startswith("LOCK") else "SCALP"
    if (
        entry_side
        and strategy == "SCALP"
        and entry_price is not None
        and entry_price > MAX_ENTRY_PRICE
    ):
        return {
            "event": False,
            "message": (
                f"Skipped PAPER SCALP: Kalshi price {entry_price * 100:.0f}% "
                f"is above the {MAX_ENTRY_PRICE * 100:.0f}% maximum."
            ),
        }
    if entry_side:
        if strategy == "SCALP":
            market_probability = _selected_side_market_probability(decision, entry_side)
            if (
                market_probability is None
                or market_probability < MIN_SCALP_MARKET_PROBABILITY
            ):
                probability_text = (
                    "unavailable"
                    if market_probability is None
                    else f"{market_probability * 100:.0f}%"
                )
                return {
                    "event": False,
                    "message": (
                        f"Skipped PAPER SCALP: selected-side market probability "
                        f"{probability_text} is below the "
                        f"{MIN_SCALP_MARKET_PROBABILITY * 100:.0f}% lottery floor."
                    ),
                }
            profitability_gate = scalp_profitability_gate(db_path, starting_cash)
            if not profitability_gate["approved"]:
                return {
                    "event": False,
                    "message": (
                        "Skipped PAPER SCALP: post-fix Kalshi profitability "
                        "gate is active — " + profitability_gate["reason"] + "."
                    ),
                }
        if strategy == "LOCK" and _decision_confidence(decision) < LOCK_MIN_CONFIDENCE:
            return {
                "event": False,
                "message": (
                    f"Skipped PAPER LOCK: confidence {_decision_confidence(decision) * 100:.0f}% "
                    f"is below the {LOCK_MIN_CONFIDENCE * 100:.0f}% minimum."
                ),
            }
        if strategy == "LOCK" and entry_price is not None:
            performance = paper_performance_since_update(db_path, starting_cash)
            exposure_cap = (
                UNPROVEN_POSITION_CAP
                if performance["samples"] < POST_FIX_VALIDATION_TRADES
                else 0.25
            )
            summary = paper_summary(db_path, starting_cash)
            cash = float(summary["cash"])
            pct = min(
                exposure_cap,
                max(0.0, _f(risk.get("position_pct"), 0.0)),
            )
            budget = cash * pct
            contracts = int(budget // max(entry_price, 0.01))
            while (
                contracts > 0
                and entry_price * contracts
                + kalshi_taker_fee(contracts, entry_price)
                > min(cash, budget)
            ):
                contracts -= 1
            expected_pnl = lock_target_pnl(contracts, entry_price)
            if contracts > 0 and expected_pnl <= 1e-12:
                return {
                    "event": False,
                    "message": (
                        f"Skipped PAPER LOCK at {entry_price * 100:.0f}%: "
                        f"selling at the 95% bid target would return "
                        f"{expected_pnl:+.2f} after estimated Kalshi fees."
                    ),
                }
        count_conn = _connect(db_path, starting_cash)
        try:
            prior_entries = _strategy_entry_count(count_conn, decision.get("kalshi_ticker"), strategy)
            prior_losses = _strategy_loss_count(count_conn, decision.get("kalshi_ticker"), strategy)
        finally:
            count_conn.close()
        limit = MAX_LOCKS_PER_MARKET if strategy == "LOCK" else MAX_SCALPS_PER_MARKET
        if prior_entries >= limit:
            noun = "LOCK" if strategy == "LOCK" else "SCALPs"
            return {
                "event": False,
                "message": f"Skipped PAPER {strategy}: {limit} {noun} already entered for this 15-minute market.",
            }
        if strategy == "SCALP" and prior_losses >= MAX_SCALP_LOSSES_PER_MARKET:
            return {
                "event": False,
                "message": (
                    "Skipped PAPER SCALP: two losses already occurred in this "
                    "15-minute market; market circuit breaker is active."
                ),
            }
    if entry_side and str(decision.get("action", "")).upper().startswith("SCALP"):
        projected_exit = _projected_scalp_exit(decision)
        required_exit = (
            entry_price * (1.0 + SCALP_MIN_GROSS_RETURN)
            if entry_price is not None
            else None
        )
        if projected_exit is None or required_exit is None or projected_exit < required_exit - 1e-12:
            projected_text = "unavailable" if projected_exit is None else f"{projected_exit * 100:.0f}%"
            required_text = "unavailable" if required_exit is None else f"{required_exit * 100:.0f}%"
            return {
                "event": False,
                "message": (
                    f"Skipped PAPER SCALP: projected exit {projected_text} is below "
                    f"the {SCALP_MIN_GROSS_RETURN * 100:.0f}% gross-return target "
                    f"({required_text})."
                ),
            }
        armed_conn = _connect(db_path, starting_cash)
        try:
            if not _scalp_is_armed(armed_conn, ticker, entry_side):
                return {
                    "event": False,
                    "message": "Skipped PAPER SCALP: waiting for a fresh signal before re-entry.",
                }
        finally:
            armed_conn.close()
    opened = open_position(db_path, starting_cash, decision, risk, spot_price)
    return opened or {"event": False, "message": "No Kalshi paper-contract action"}


def paper_summary(db_path, starting_cash=500.0):
    conn = _connect(db_path, starting_cash)
    try:
        acct = conn.execute("SELECT cash,starting_cash FROM kalshi_paper_account WHERE id=1").fetchone()
        closed = conn.execute("SELECT pnl FROM kalshi_paper_positions WHERE status='CLOSED' AND pnl IS NOT NULL").fetchall()
        opened = conn.execute("SELECT * FROM kalshi_paper_positions WHERE status='OPEN' ORDER BY id DESC LIMIT 1").fetchone()
        pnls = [float(r["pnl"]) for r in closed]
        realized = sum(pnls)
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        unrealized = 0.0
        if opened:
            mark = _f(opened["last_mark"], float(opened["entry_price"]))
            contracts = int(opened["contracts"])
            unrealized = mark * contracts - kalshi_taker_fee(contracts, mark) - (
                float(opened["entry_price"]) * contracts + float(opened["entry_fee"])
            )
        start = float(acct["starting_cash"])
        equity = start + realized + unrealized
        open_position = dict(opened) if opened else None
        if open_position:
            open_position["amount_down"] = (
                float(open_position["entry_price"]) * int(open_position["contracts"])
                + float(open_position["entry_fee"])
            )
        return {
            "cash": float(acct["cash"]),
            "starting_cash": start,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "total_pnl": realized + unrealized,
            "equity": equity,
            "return_pct": ((equity-start)/start*100.0) if start else 0.0,
            "samples": len(pnls),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins)/len(pnls)) if pnls else None,
            "profit_factor": (sum(wins)/abs(sum(losses))) if losses else (math.inf if wins else None),
            "open_position": open_position,
        }
    finally:
        conn.close()

def paper_history(db_path, starting_cash=500.0, limit=100):
    """Return the automatic Kalshi trade ledger from its authoritative table."""
    conn = _connect(db_path, starting_cash)
    try:
        rows = conn.execute(
            """SELECT * FROM kalshi_paper_positions
               ORDER BY opened_at DESC, id DESC LIMIT ?""",
            (max(1, min(1000, int(limit))),),
        ).fetchall()
        history = []
        for row in rows:
            item = dict(row)
            contracts = int(item["contracts"])
            entry = float(item["entry_price"])
            amount = entry * contracts + float(item["entry_fee"])
            is_open = str(item["status"]).upper() == "OPEN"
            if is_open:
                mark = _f(item.get("last_mark"), entry)
                pnl = mark * contracts - kalshi_taker_fee(contracts, mark) - amount
                result = "OPEN"
                current_or_exit = mark
            else:
                pnl = _f(item.get("pnl"), 0.0)
                result = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "EVEN")
                current_or_exit = _f(item.get("exit_price"))

            history.append({
                "status": "OPEN" if is_open else "CLOSED",
                "direction": "UP" if item["side"] == "YES" else "DOWN",
                "strategy": item["strategy"],
                "amount": amount,
                "kalshi_entry_pct": entry * 100.0,
                "current_or_exit_pct": (
                    current_or_exit * 100.0 if current_or_exit is not None else None
                ),
                "result": result,
                "pnl": pnl,
                "opened_at": item["opened_at"],
                "closed_at": item.get("closed_at"),
                "expires_at": item.get("expires_at"),
            })
        return history
    finally:
        conn.close()


def paper_chart_entries(db_path, ticker, starting_cash=500.0, limit=11):
    """Return plot-safe entry markers for one active 15-minute market."""
    ticker = str(ticker or "").strip()
    if not ticker:
        return []
    conn = _connect(db_path, starting_cash)
    try:
        rows = conn.execute(
            """SELECT side,strategy,opened_at,entry_price,spot_entry_price
               FROM kalshi_paper_positions
               WHERE ticker=? AND spot_entry_price IS NOT NULL
               ORDER BY opened_at ASC, id ASC LIMIT ?""",
            (ticker, max(1, min(25, int(limit)))),
        ).fetchall()
        return [
            {
                "direction": "UP" if row["side"] == "YES" else "DOWN",
                "strategy": str(row["strategy"]),
                "opened_at": float(row["opened_at"]),
                "kalshi_entry_pct": float(row["entry_price"]) * 100.0,
                "spot_entry_price": float(row["spot_entry_price"]),
            }
            for row in rows
        ]
    finally:
        conn.close()
