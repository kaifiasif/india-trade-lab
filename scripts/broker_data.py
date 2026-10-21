#!/usr/bin/env python3
"""Read-only Indian cash-equity candle export. No order endpoints or login automation.

Credentials come from environment variables, never CLI arguments or output.
Use broker-issued OAuth sessions and current market-data entitlements.
"""
import argparse
import csv
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Provider redirect refused; credentials were not forwarded')


def make_request(provider, instrument, start, end, environ=None):
    env = os.environ if environ is None else environ
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if first > last:
        raise ValueError('Start must not be after end')
    if provider == 'upstox':
        if not re.fullmatch(r'(NSE_EQ|BSE_EQ)\|[A-Z0-9]+', instrument):
            raise ValueError('Expected an Upstox cash-equity instrument key')
        token = env.get('UPSTOX_ACCESS_TOKEN', '')
        if not token:
            raise ValueError('Set UPSTOX_ACCESS_TOKEN privately outside chat')
        key = urllib.parse.quote(instrument, safe='')
        url = f'https://api.upstox.com/v3/historical-candle/{key}/minutes/5/{last}/{first}'
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
    elif provider == 'kite':
        if not instrument.isdigit():
            raise ValueError('Expected a Kite instrument token from the verified master')
        key, token = env.get('KITE_API_KEY', ''), env.get('KITE_ACCESS_TOKEN', '')
        if not key or not token:
            raise ValueError('Set KITE_API_KEY and KITE_ACCESS_TOKEN privately outside chat')
        query = urllib.parse.urlencode({'from': f'{first} 00:00:00', 'to': f'{last} 23:59:59'})
        url = f'https://api.kite.trade/instruments/historical/{instrument}/5minute?{query}'
        headers = {'Authorization': f'token {key}:{token}', 'X-Kite-Version': '3'}
    else:
        raise ValueError('Provider must be upstox or kite')
    return urllib.request.Request(url, headers=headers, method='GET')


def export(payload, symbol, source, path):
    if not re.fullmatch(r'(NSE|BSE):[A-Z0-9&.\-]+', symbol):
        raise ValueError('Use a verified exchange-qualified cash-equity symbol')
    if payload.get('status') != 'success':
        raise ValueError('Provider did not return a successful data response')
    candles = payload.get('data', {}).get('candles')
    if not isinstance(candles, list) or not candles:
        raise ValueError('No candles returned')
    # Import only numeric OHLCV; never copy response metadata or account details.
    from india_research import validate_bar
    rows = []
    for candle in candles:
        if not isinstance(candle, list) or len(candle) < 6:
            raise ValueError('Malformed provider candle')
        row = dict(zip(('timestamp', 'open', 'high', 'low', 'close', 'volume'), candle[:6]))
        row.update(symbol=symbol, source=source)
        normalized = validate_bar(row)
        row['timestamp'] = normalized['t'].isoformat()
        rows.append(row)
    rows.sort(key=lambda x: x['timestamp'])
    if len({x['timestamp'] for x in rows}) != len(rows):
        raise ValueError('Duplicate candle timestamps')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=('symbol', 'timestamp', 'open', 'high', 'low', 'close', 'volume', 'source'))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--provider', choices=('upstox', 'kite'), required=True)
    p.add_argument('--instrument', required=True)
    p.add_argument('--symbol', required=True)
    p.add_argument('--from-date', required=True)
    p.add_argument('--to-date', required=True)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    try:
        request = make_request(a.provider, a.instrument, a.from_date, a.to_date)
        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(request, timeout=30) as response:
            raw = response.read(20_000_001)
        if len(raw) > 20_000_000:
            raise ValueError('Response too large; request a smaller date range')
        payload = json.loads(raw)
        source = f'{a.provider}:historical:5minute:{a.instrument}'
        count = export(payload, a.symbol, source, a.output)
        print(json.dumps({'status': 'data_only', 'provider': a.provider, 'rows': count,
                          'output': str(a.output), 'currency': 'INR',
                          'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                          'notice': 'Data is not a fill or a trading recommendation.'}))
        return 0
    except urllib.error.HTTPError as e:
        print(f'REFUSED: provider HTTP {e.code}; check session, entitlements and rate limits', file=sys.stderr)
    except (ValueError, TypeError, KeyError, OSError, urllib.error.URLError):
        print('REFUSED: data request or export failed; check inputs, session and output path. No orders were sent.', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
