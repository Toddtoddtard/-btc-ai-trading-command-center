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
LOCK_MIN_CONFIDENCE = 0.95
MAX_SCALPS_PER_MARKET = 10
MAX_LOCKS_PER_MARKET = 1

# SCALP positions require a forecast of at least 15 contract-price points and
# realize profit once that full move is available (for example, 50% to 65%).
SCALP_MIN_MOVE_POINTS = 0.15
SCALP_STOP_LOSS_PCT = 0.10

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
            entry_price REAL NOT NULL,
            contracts INTEGER NOT NULL,
            entry_fee REAL NOT NULL,
            last_mark REAL,
            closed_at REAL,
            exit_price REAL,
            exit_fee REAL DEFAULT 0,
            pnl REAL,
            exit_reason TEXT
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


def _projected_scalp_exit(decision):
    """Return the model's selected-side fair value used for SCALP qualification."""
    projected = _f(decision.get("scalp_projected_exit_price"))
    if projected is None:
        projected = _f(decision.get("confidence"))
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


def open_position(db_path, starting_cash, decision, risk, spot_price):
    side = _side_from_action(decision.get("action"))
    if side is None or not bool(risk.get("approved")):
        return None
    ticker = str(decision.get("kalshi_ticker") or "")
    if not ticker:
        return None
    strategy = "LOCK" if str(decision.get("action", "")).upper().startswith("LOCK") else "SCALP"
    if strategy == "LOCK" and _decision_confidence(decision) < LOCK_MIN_CONFIDENCE:
        return None
    entry = _quote(decision, side, ask=True)
    if entry is None or entry > MAX_ENTRY_PRICE:
        return None
    if strategy == "SCALP":
        projected_exit = _projected_scalp_exit(decision)
        if projected_exit is None or projected_exit - entry < SCALP_MIN_MOVE_POINTS - 1e-12:
            return None
    now = time.time()
    expires_at = _f(decision.get('kalshi_close_ts'))
    if expires_at is None:
        remain = _f(decision.get('seconds_remaining'))
        expires_at = now + remain if remain is not None else None
    if expires_at is None or expires_at <= now:
        return None
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
        acct = conn.execute("SELECT cash FROM kalshi_paper_account WHERE id=1").fetchone()
        cash = float(acct["cash"])
        pct = min(0.25, max(0.0, _f(risk.get("position_pct"), 0.0)))
        budget = cash * pct
        contracts = int(budget // max(entry, 0.01))
        while contracts > 0 and entry * contracts + kalshi_taker_fee(contracts, entry) > min(cash, budget):
            contracts -= 1
        if contracts < 1:
            return None
        fee = kalshi_taker_fee(contracts, entry)
        total_cost = entry * contracts + fee
        now = time.time()
        expires_at = _f(decision.get("kalshi_close_ts"))
        if expires_at is None:
            remain = _f(decision.get("seconds_remaining"))
            expires_at = now + remain if remain is not None else None
        conn.execute("UPDATE kalshi_paper_account SET cash=?,updated_at=? WHERE id=1", (cash-total_cost, now))
        conn.execute("""
            INSERT INTO kalshi_paper_positions(
                ticker,side,strategy,status,opened_at,expires_at,target_price,
                entry_price,contracts,entry_fee,last_mark
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (
            ticker, side, strategy, "OPEN", now, expires_at,
            _f(decision.get("target_price")), entry, contracts, fee, _quote(decision, side, ask=False),
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
                contracts = int(row["contracts"])
                entry_cost = (
                    float(row["entry_price"]) * contracts
                    + float(row["entry_fee"])
                )
                exit_value = (
                    mark * contracts
                    - kalshi_taker_fee(contracts, mark)
                )
                net_return = (exit_value - entry_cost) / max(entry_cost, 0.01)
                action_side = _side_from_action(decision.get("action"))
                if action_side and action_side != side:
                    return _close(conn, row, mark, "OPPOSITE_SIGNAL")
                price_gain = mark - float(row["entry_price"])
                if price_gain >= SCALP_MIN_MOVE_POINTS - 1e-12:
                    return _close(conn, row, mark, "TAKE_PROFIT_15_POINTS")
                if net_return <= -SCALP_STOP_LOSS_PCT:
                    return _close(conn, row, mark, "STOP_LOSS")
            return {"event": False, "message": f"Holding PAPER {row['strategy']} {row['side']} {row['ticker']}"}
    finally:
        conn.close()
    if not enabled:
        return {'event': False, 'message': 'AUTO PAPER paused; existing positions remain managed'}
    entry_side = _side_from_action(decision.get("action"))
    entry_price = _quote(decision, entry_side, ask=True) if entry_side else None
    if entry_price is not None and entry_price > MAX_ENTRY_PRICE:
        return {
            "event": False,
            "message": (
                f"Skipped PAPER entry: Kalshi price {entry_price * 100:.0f}% "
                f"is above the {MAX_ENTRY_PRICE * 100:.0f}% maximum."
            ),
        }
    if entry_side:
        strategy = "LOCK" if str(decision.get("action", "")).upper().startswith("LOCK") else "SCALP"
        if strategy == "LOCK" and _decision_confidence(decision) < LOCK_MIN_CONFIDENCE:
            return {
                "event": False,
                "message": (
                    f"Skipped PAPER LOCK: confidence {_decision_confidence(decision) * 100:.0f}% "
                    f"is below the {LOCK_MIN_CONFIDENCE * 100:.0f}% minimum."
                ),
            }
        count_conn = _connect(db_path, starting_cash)
        try:
            prior_entries = _strategy_entry_count(count_conn, decision.get("kalshi_ticker"), strategy)
        finally:
            count_conn.close()
        limit = MAX_LOCKS_PER_MARKET if strategy == "LOCK" else MAX_SCALPS_PER_MARKET
        if prior_entries >= limit:
            noun = "LOCK" if strategy == "LOCK" else "SCALPs"
            return {
                "event": False,
                "message": f"Skipped PAPER {strategy}: {limit} {noun} already entered for this 15-minute market.",
            }
    if entry_side and str(decision.get("action", "")).upper().startswith("SCALP"):
        projected_exit = _projected_scalp_exit(decision)
        if projected_exit is None or entry_price is None or projected_exit - entry_price < SCALP_MIN_MOVE_POINTS - 1e-12:
            projected_text = "unavailable" if projected_exit is None else f"{projected_exit * 100:.0f}%"
            return {
                "event": False,
                "message": (
                    f"Skipped PAPER SCALP: projected exit {projected_text} does not provide "
                    f"the {SCALP_MIN_MOVE_POINTS * 100:.0f}-point minimum move."
                ),
            }
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
