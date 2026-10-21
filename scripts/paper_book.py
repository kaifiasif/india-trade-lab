#!/usr/bin/env python3
"""Offline, manual virtual-INR journal. No network code or live mode.

Quotes/fees are user inputs, fills are assumed, stops are descriptive only.
SQLite serializes concurrent writes; event IDs prevent duplicate fills.
"""
import argparse
import copy
import datetime as dt
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path
import re
import sqlite3
import sys

CENT = Decimal('.01')
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def number(value, positive=False):
    try:
        n = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('Invalid numeric value')
    if not n.is_finite() or n < 0 or (positive and n == 0):
        raise ValueError('Expected a finite ' + ('positive' if positive else 'nonnegative') + ' number')
    return n


def money(n):
    return str(n.quantize(CENT, rounding=ROUND_HALF_UP))


def timestamp(value):
    t = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('Timestamp must include a timezone offset')
    return t.astimezone(IST)


def create(cash, symbols, risk, daily_loss, position_limit, replay=False,
           max_trades=3, max_open=2, max_loss_streak=2, drawdown_stop=None):
    instruments = sorted(set(symbols.split(',')))
    if not instruments or any(not re.fullmatch(r'(NSE|BSE):[A-Z0-9&.\-]+', s) for s in instruments):
        raise ValueError('Allowlist must contain exchange-qualified symbols, e.g. NSE:TCS')
    values = [number(x, True) for x in (cash, risk, daily_loss, position_limit)]
    if min(values) < CENT or values[1] > values[2] or values[2] > values[0] or values[3] > values[0]:
        raise ValueError('Require 0.01 <= risk <= daily loss <= cash and position limit <= cash')
    if any(isinstance(x, bool) or not isinstance(x, int) or x <= 0 for x in (max_trades, max_open, max_loss_streak)):
        raise ValueError('Trade, open-position and loss-streak limits must be positive integers')
    dd = number(drawdown_stop, True) if drawdown_stop is not None else values[0] * Decimal('.02')
    if dd > values[0]:
        raise ValueError('Drawdown stop must not exceed initial virtual cash')
    return {'mode': 'replay_demo' if replay else 'paper_manual', 'currency': 'INR',
            'version': 2, 'paused': False, 'loss_streak': 0,
            'high_watermark_inr': money(values[0]), 'closed_trade_drawdown_inr': '0.00',
            'controls': {'max_trades_per_day': max_trades, 'max_open_positions': max_open,
                         'max_loss_streak': max_loss_streak, 'drawdown_stop_inr': money(dd)},
            'initial_cash': money(values[0]), 'cash': money(values[0]),
            'limits': dict(zip(('risk', 'daily_loss', 'position_limit'), map(money, values[1:]))),
            'symbols': instruments, 'positions': {}, 'events': [], 'realized_by_day': {}}


def fill(book, side, event_id, symbol, price, as_of, source, fee, slippage,
         qty=None, stop=None, exit_fee=None, now=None):
    """Return a new state only after all checks pass; do not mutate input."""
    if book.get('mode') not in ('paper_manual', 'replay_demo') or book.get('currency') != 'INR':
        raise ValueError('Unsupported book mode/currency')
    if side not in ('buy', 'sell') or symbol not in book['symbols']:
        raise ValueError('Unsupported side or symbol not in allowlist')
    if not event_id.strip() or len(event_id) > 128 or any(e['id'] == event_id for e in book['events']):
        raise ValueError('Event ID must be unique and 1-128 characters')
    if not source.strip():
        raise ValueError('Quote source is required')
    t = timestamp(as_of)
    clock = now or dt.datetime.now(IST)
    if book['mode'] == 'paper_manual' and not -5 <= (clock - t).total_seconds() <= 120:
        raise ValueError('Paper quote must be <=120 seconds old and <=5 seconds in the future')
    if book['events'] and t < timestamp(book['events'][-1]['as_of']):
        raise ValueError('Quote times must be nondecreasing')
    price, fee, slip = number(price, True), number(fee), number(slippage)
    if price < CENT or slip >= 10000:
        raise ValueError('Price must be >=0.01 and slippage <10000 bps')
    px = Decimal(money(price * (1 + slip / 10000 if side == 'buy' else 1 - slip / 10000)))
    if px <= 0:
        raise ValueError('Adjusted fill price must be positive')
    fee = Decimal(money(fee))
    state = copy.deepcopy(book)
    positions, limits = state['positions'], state['limits']
    day = t.date().isoformat()
    event = {'id': event_id, 'side': side, 'symbol': symbol, 'as_of': t.isoformat(),
             'source': source, 'quote_inr': str(price), 'assumed_fill_inr': money(px),
             'fee_inr': money(fee), 'slippage_bps': str(slip), 'mode': state['mode']}
    cash = number(state['cash'])
    if side == 'buy':
        controls = state.get('controls')
        if not controls:
            raise ValueError('Book requires version-2 controls; preserve old results and initialize a separate book')
        if state.get('paused'):
            raise ValueError('New entries paused; exits remain available')
        if state.get('loss_streak', 0) >= controls['max_loss_streak']:
            raise ValueError('Consecutive loss stop reached; review before any new paper session')
        if number(state.get('closed_trade_drawdown_inr', '0')) >= number(controls['drawdown_stop_inr']):
            raise ValueError('Closed-trade drawdown stop reached; review the strategy')
        entries = sum(e['side'] == 'buy' and timestamp(e['as_of']).date() == t.date() for e in state['events'])
        if entries >= controls['max_trades_per_day'] or len(positions) >= controls['max_open_positions']:
            raise ValueError('Daily entry or concurrent position cap reached')
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ValueError('Quantity must be positive whole shares')
        if symbol in positions:
            raise ValueError('Close the existing symbol position before re-entry')
        if any(p['day'] != day for p in positions.values()):
            raise ValueError('Close prior-day paper positions before new entries')
        stop, reserve = number(stop, True), number(exit_fee)
        if not stop < px:
            raise ValueError('Long stop must be below assumed entry')
        reserve = Decimal(money(reserve))
        assumed_stop = stop * (1 - slip / 10000)
        loss = (px - assumed_stop) * qty + fee + reserve
        cost = px * qty + fee
        existing_risk = sum((number(p['planned_loss_inr']) for p in positions.values()), Decimal(0))
        realized = Decimal(state['realized_by_day'].get(day, '0'))
        daily_used = max(Decimal(0), -realized) + existing_risk
        existing_reserves = sum((number(p['exit_fee_reserve_inr']) for p in positions.values()), Decimal(0))
        if cost + reserve + existing_reserves > cash:
            raise ValueError('Insufficient virtual cash including exit-fee reserve')
        if cost > number(limits['position_limit']):
            raise ValueError('Position limit exceeded')
        if loss > number(limits['risk']) or daily_used + loss > number(limits['daily_loss']):
            raise ValueError('Per-trade or daily planned loss limit exceeded')
        positions[symbol] = {'qty': qty, 'entry_inr': money(px), 'entry_fee_inr': money(fee),
                             'cost_inr': money(cost), 'planned_loss_inr': money(loss),
                             'stop_inr': str(stop), 'day': day, 'entry_event_id': event_id,
                             'exit_fee_reserve_inr': money(reserve)}
        state['cash'] = money(cash - cost)
        event.update(qty=qty, stop_inr=str(stop), planned_loss_inr=money(loss),
                     exit_fee_reserve_inr=money(reserve))
    else:
        if symbol not in positions:
            raise ValueError('No virtual position to sell; shorts are unsupported')
        p = positions.pop(symbol)
        proceeds = px * p['qty'] - fee
        pnl = proceeds - number(p['cost_inr'])
        if cash + proceeds < 0:
            raise ValueError('Exit charges exceed remaining cash')
        state['cash'] = money(cash + proceeds)
        state['realized_by_day'][day] = money(Decimal(state['realized_by_day'].get(day, '0')) + pnl)
        state['loss_streak'] = state.get('loss_streak', 0) + 1 if pnl < 0 else 0
        closed_equity = number(state['initial_cash']) + sum(map(Decimal, state['realized_by_day'].values()))
        peak = max(number(state.get('high_watermark_inr', state['initial_cash'])), closed_equity)
        state['high_watermark_inr'] = money(peak)
        state['closed_trade_drawdown_inr'] = money(peak - closed_equity)
        event.update(qty=p['qty'], net_realized_pnl_inr=money(pnl), entry_event_id=p['entry_event_id'])
    state['events'].append(event)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--book', required=True, type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    for key in ('cash-inr', 'symbols', 'risk-inr', 'daily-loss-inr', 'position-limit-inr'):
        init.add_argument('--' + key, required=True)
    init.add_argument('--replay', action='store_true')
    init.add_argument('--max-trades', type=int, default=3)
    init.add_argument('--max-open', type=int, default=2)
    init.add_argument('--max-loss-streak', type=int, default=2)
    init.add_argument('--drawdown-stop-inr')
    sub.add_parser('status')
    sub.add_parser('pause').add_argument('--reason', required=True)
    for side in ('buy', 'sell'):
        p = sub.add_parser(side)
        for key in ('id', 'symbol', 'price-inr', 'as-of', 'source', 'fee-inr', 'slippage-bps'):
            p.add_argument('--' + key, required=True)
        if side == 'buy':
            p.add_argument('--qty', type=int, required=True)
            p.add_argument('--stop-inr', required=True)
            p.add_argument('--exit-fee-reserve-inr', required=True)
    args = parser.parse_args()
    if args.command != 'init' and not args.book.is_file():
        parser.error('Book does not exist; initialize it explicitly first')
    try:
        if args.command == 'init':
            args.book.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(args.book), isolation_level=None, timeout=10) as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('CREATE TABLE IF NOT EXISTS book (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)')
            row = conn.execute('SELECT data FROM book WHERE id=1').fetchone()
            if args.command == 'init':
                if row:
                    raise ValueError('Book already initialized; refusing to overwrite')
                state = create(args.cash_inr, args.symbols, args.risk_inr, args.daily_loss_inr,
                               args.position_limit_inr, args.replay, args.max_trades,
                               args.max_open, args.max_loss_streak, args.drawdown_stop_inr)
            else:
                if not row:
                    raise ValueError('Book has not been initialized')
                state = json.loads(row[0])
                if args.command == 'pause':
                    state.update(paused=True, pause_reason=args.reason,
                                 paused_at=dt.datetime.now(IST).isoformat())
                elif args.command != 'status':
                    state = fill(state, args.command, args.id, args.symbol, args.price_inr,
                                 args.as_of, args.source, args.fee_inr, args.slippage_bps,
                                 getattr(args, 'qty', None), getattr(args, 'stop_inr', None),
                                 getattr(args, 'exit_fee_reserve_inr', None))
            if args.command != 'status':
                conn.execute('INSERT OR REPLACE INTO book VALUES (1, ?)', (json.dumps(state),))
            conn.commit()
        print(json.dumps(state, indent=2))
        return 0
    except (ValueError, TypeError, InvalidOperation, sqlite3.Error, OSError) as exc:
        print('REFUSED: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
