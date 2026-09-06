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
SCALP_TAKE_PROFIT_PCT = 0.15
SCALP_STOP_LOSS_PCT = 0.10


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


def open_position(db_path, starting_cash, decision, risk, spot_price):
    side = _side_from_action(decision.get("action"))
    if side is None or not bool(risk.get("approved")):
        return None
    ticker = str(decision.get("kalshi_ticker") or "")
    if not ticker:
        return None
    entry = _quote(decision, side, ask=True)
    if entry is None:
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
        strategy = "LOCK" if str(decision.get("action", "")).upper().startswith("LOCK") else "SCALP"
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
            "message": f"Opened PAPER {strategy} {direction} • Amount down: ${total_cost:,.2f} • {ticker}",
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


def persistent_lock_side(db_path, ticker, starting_cash=500.0):
    if not ticker:
        return None
    conn = _connect(db_path, starting_cash)
    try:
        row = conn.execute(
            "SELECT side FROM kalshi_paper_positions WHERE status='OPEN' AND strategy='LOCK' AND ticker=? ORDER BY id DESC LIMIT 1",
            (str(ticker),),
        ).fetchone()
        return row["side"] if row else None
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
            if row["strategy"] == "SCALP" and mark is not None:
                entry = float(row["entry_price"])
                rel = (mark - entry) / max(entry, 0.01)
                action_side = _side_from_action(decision.get("action"))
                if action_side and action_side != side:
                    return _close(conn, row, mark, "OPPOSITE_SIGNAL")
                if rel >= SCALP_TAKE_PROFIT_PCT:
                    return _close(conn, row, mark, "TAKE_PROFIT")
                if rel <= -SCALP_STOP_LOSS_PCT:
                    return _close(conn, row, mark, "STOP_LOSS")
            return {"event": False, "message": f"Holding PAPER {row['strategy']} {row['side']} {row['ticker']}"}
    finally:
        conn.close()
    if not enabled:
        return {'event': False, 'message': 'AUTO PAPER paused; existing positions remain managed'}
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
