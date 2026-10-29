"""In-memory Lookup store for tests. Passes the same contract tests as PostgreSQL."""

from soc.store.lookups.checks import asset_matches, check_assets, check_users, valid_at


class FakeLookupStore:
    def __init__(self):
        self._assets = []
        self._users = []
        self.closed = False

    def replace_assets(self, rows):
        self._assets = check_assets(rows)
        return len(self._assets)

    def replace_users(self, rows):
        self._users = check_users(rows)
        return len(self._users)

    def asset_candidates(self, value, at):
        return [asset for asset in self._assets if asset_matches(asset, value, at)]

    def user_candidates(self, user, at):
        return [
            row
            for row in self._users
            if row.user.user == user and valid_at(row.valid_from, row.valid_to, at)
        ]

    def close(self):
        self.closed = True
