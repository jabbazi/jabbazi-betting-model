"""NBA joint player-outcome contract; NOT a fitted or approved model.

Future fitted minutes/production models must supply aligned samples. No synthetic
samples are generated here. Combination props preserve within-row dependence.
"""
from dataclasses import dataclass
from math import isfinite

NBA_COMPONENTS = {
    'player_points': (1,), 'player_rebounds': (2,), 'player_assists': (3,),
    'player_threes': (4,), 'player_points_rebounds_assists': (1,2,3),
    'player_points_rebounds': (1,2), 'player_points_assists': (1,3),
    'player_rebounds_assists': (2,3),
}

@dataclass(frozen=True)
class NBAPlayerDistribution:
    # (minutes, points, rebounds, assists, threes), conditional on participation.
    samples: tuple[tuple[float, int, int, int, int], ...]
    model_version: str
    event_id: str
    player_id: str

    def __post_init__(self):
        if not all((self.model_version,self.event_id,self.player_id)) or len(self.samples) < 100:
            raise ValueError('Aligned, versioned NBA samples required')
        for row in self.samples:
            if len(row) != 5 or any(not isfinite(v) or v < 0 for v in row):
                raise ValueError('Invalid NBA sample')
            if any(int(v) != v for v in row[1:]) or 3*row[4] > row[1]:
                raise ValueError('Incoherent NBA count sample')
            if row[0] == 0:
                raise ValueError('DNP settlement requires separate participation/void model')

    def values(self, market):
        columns = NBA_COMPONENTS.get(market)
        if columns is None:
            raise ValueError('Unsupported NBA market')
        return tuple(sum(row[i] for i in columns) for row in self.samples)

    def outcome(self, market, side, line):
        if side not in ('Over','Under') or not isfinite(line) or line < 0:
            raise ValueError('Invalid NBA threshold or side')
        values = self.values(market)
        win = sum(v > line if side == 'Over' else v < line for v in values)/len(values)
        push = sum(v == line for v in values)/len(values)
        return {'win':win,'push':push,'loss':1-win-push}

    def joint(self, legs):
        if not 2 <= len(legs) <= 4:
            raise ValueError('Two to four aligned legs required')
        masks = []
        for leg in legs:
            if leg['event_id'] != self.event_id or leg['player_id'] != self.player_id:
                raise ValueError('Cross-player or cross-event dependence unavailable')
            p = self.outcome(leg['market'],leg['side'],leg['line'])
            if p['push']:
                raise ValueError('Push repricing unsupported')
            masks.append([v > leg['line'] if leg['side'] == 'Over' else v < leg['line']
                          for v in self.values(leg['market'])])
        return {'joint_probability':sum(all(row) for row in zip(*masks))/len(self.samples),
                'method':'aligned_player_samples','approved_for_betting':False}
