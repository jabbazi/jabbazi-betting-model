import pytest
from jabazi.models.nba_joint import NBAPlayerDistribution


def model():
    return NBAPlayerDistribution(((30,10,3,2,2),)*50 + ((35,30,10,10,5),)*50,'fixture','event','player')


def test_nba_combined_props_and_ladders():
    m = model()
    assert m.values('player_points_rebounds_assists') == (15,)*50+(50,)*50
    previous = 1
    for threshold in range(61):
        over = m.outcome('player_points_rebounds_assists','Over',threshold)
        under = m.outcome('player_points_rebounds_assists','Under',threshold)
        assert over['win'] <= previous
        assert abs(over['win']+under['win']+over['push']-1) < 1e-12
        previous = over['win']


def test_nba_joint_preserves_same_player_dependence():
    legs = [dict(event_id='event',player_id='player',market=market,side='Over',line=line)
            for market,line in [('player_points',20.5),('player_assists',5.5)]]
    assert model().joint(legs)['joint_probability'] == .5
    legs[1]['player_id'] = 'other'
    with pytest.raises(ValueError):
        model().joint(legs)


@pytest.mark.parametrize('row', [(0,10,0,0,0),(30,2,0,0,1),(30,1.5,0,0,0)])
def test_impossible_player_samples_rejected(row):
    with pytest.raises(ValueError):
        NBAPlayerDistribution((row,)*100,'fixture','event','player')
