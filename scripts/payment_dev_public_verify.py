"""Verify public dev Payment reads; never log response bodies or Bearer values."""
import argparse
import json
import os
from pathlib import Path
import stat
import urllib.error
import urllib.request

ORIGIN = 'https://test-ggt-api.rvkang.app'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def request(path, query, bearer=None, forged=False):
    headers = {'Content-Type': 'application/json'}
    if bearer:
        headers['Authorization'] = 'Bearer ' + bearer
    if forged:
        headers['x-gaegaeting-principal'] = 'synthetic-invalid-owner-assertion'
        headers['x-gaegaeting-edge-assertion'] = 'synthetic-invalid-edge-assertion'
        headers['x-jwt-payload'] = '{"user_id":"synthetic-other-owner"}'
    req = urllib.request.Request(ORIGIN + path, data=json.dumps({'query': query}).encode(), headers=headers)
    try:
        with OPENER.open(req, timeout=20) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, None


def verify(bearer=None):
    wallet = 'query { mySnackWallet { balance availableBalance frozen } }'
    status, _ = request('/gateway/graphql', wallet)
    assert status == 401
    status, _ = request('/gateway/graphql', wallet, forged=True)
    assert status == 401
    for path in ['/payment/graphql', '/payment/health', '/payment/notifications/apple/extra', '/payment/notifications/google/']:
        assert request(path, wallet)[0] == 404
    result = {'origin': ORIGIN, 'unauthenticatedRejected': True, 'forgedOwnerHeadersRejected': True,
              'privatePaymentPathsBlocked': True, 'actualUserBearerVerified': False}
    if bearer:
        status, body = request('/gateway/graphql', wallet, bearer)
        assert status == 200 and not body.get('errors')
        balance = body['data']['mySnackWallet']
        assert all(type(balance[k]) is int and balance[k] >= 0 for k in ['balance', 'availableBalance'])
        assert type(balance['frozen']) is bool
        status, body = request('/gateway/graphql', 'query { mySnackTransactions { id } }', bearer)
        assert status == 200 and not body.get('errors') and isinstance(body['data']['mySnackTransactions'], list)
        for provider in ['APPLE', 'GOOGLE']:
            status, body = request('/gateway/graphql', 'query { snackProducts(provider:' + provider + ') { id } }', bearer)
            assert status == 200 and body['errors'][0]['extensions']['code'] == 'STORE_UNAVAILABLE'
        result.update(actualUserBearerVerified=True, walletRead=True, transactionsRead=True, disabledCatalogRejected=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bearer-file', type=Path, help='Existing protected session token file; the token is never printed')
    args = parser.parse_args()
    try:
        bearer = None
        if args.bearer_file:
            info = args.bearer_file.lstat()
            assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == os.getuid()
            bearer = args.bearer_file.read_text().strip()
            assert bearer and not any(c.isspace() for c in bearer)
        print(json.dumps(verify(bearer)))
    except Exception:
        print(json.dumps({'valid': False, 'error': 'Public Payment verification failed; sensitive details suppressed'}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
