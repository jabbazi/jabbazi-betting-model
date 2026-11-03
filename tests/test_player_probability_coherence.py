from copy import deepcopy
import math

import numpy as np
import pytest
from sklearn.isotonic import IsotonicRegression

from jabazi.models.player_calibration import apply_calibration
from jabazi.models.player_distribution import calibrated_probability, raw_probability
from jabazi.models.train_player_props import _fit_calibration, _validation
from test_player_prop_models import binary_artifact, count_artifact


def test_linear_isotonic_matches_fitted_library_on_between_knot_predictions():
    fit = IsotonicRegression(out_of_bounds='clip').fit([.1,.3,.4,.6,.8], [0,0,1,0,1])
    spec = {'method':'isotonic','orientation':'positive','interpolation':'linear',
            'x':fit.X_thresholds_.tolist(),'y':fit.Y_thresholds_.tolist() if hasattr(fit,'Y_thresholds_') else fit.y_thresholds_.tolist()}
    values = np.linspace(0,1,301)
    assert np.allclose([apply_calibration(p,spec) for p in values], fit.predict(values))


def test_legacy_step_positive_predictions_are_preserved_but_unproven_negative_is_blocked():
    a = binary_artifact()
    a['calibration'] = {'method':'isotonic','x':[.1,.9],'y':[.2,.8]}
    assert apply_calibration(.5,a['calibration']) == .2
    assert calibrated_probability(a,{'red_zone_share':.3},'yes',None) == .2
    with pytest.raises(ValueError,match='Legacy'):
        calibrated_probability(a,{'red_zone_share':.3},'no',None)


def test_new_atd_calibration_uses_one_yes_probability_for_both_outcomes():
    a = binary_artifact()
    a['calibration'] = {'method':'platt','orientation':'positive','slope':.8,'intercept':-.4}
    for x in (-5,0,1,5):
        f={'red_zone_share':x}
        assert calibrated_probability(a,f,'yes',None) + calibrated_probability(a,f,'no',None) == pytest.approx(1)
    with pytest.raises(ValueError,match='0.5'):
        raw_probability(a,{'red_zone_share':0},'over',1.5)


def test_whole_count_line_excludes_push_from_under_win():
    a=count_artifact(); f={'usage':0}
    over=raw_probability(a,f,'over',5)
    under=raw_probability(a,f,'under',5)
    push=raw_probability(a,f,'over',4.5)-raw_probability(a,f,'over',5.5)
    assert push>0
    assert over+under+push == pytest.approx(1)
    for side in ('over','under'):
        with pytest.raises(ValueError,match='settlement'):
            calibrated_probability(a,f,side,5)


def test_calibrated_count_ladder_and_complements():
    a=count_artifact();f={'usage':0}
    a['calibration']={'method':'isotonic','orientation':'positive','interpolation':'linear','x':[0,.3,.8,1],'y':[0,.2,.9,1]}
    ladder=[calibrated_probability(a,f,'over',i+.5) for i in range(15)]
    assert all(x>=y for x,y in zip(ladder,ladder[1:]))
    for i,p in enumerate(ladder):
        assert p+calibrated_probability(a,f,'under',i+.5)==pytest.approx(1)


@pytest.mark.parametrize('calibration',[
    {'method':'isotonic','x':[.8,.2],'y':[.1,.8]},
    {'method':'isotonic','x':[.2,.8],'y':[.8,.1]},
    {'method':'isotonic','x':[.2,.8],'y':[.1,float('nan')]},
    {'method':'isotonic','x':[.2],'y':[]},
    {'method':'platt','slope':-1,'intercept':0},
])
def test_invalid_calibration_fails_closed(calibration):
    with pytest.raises(ValueError):apply_calibration(.5,calibration)


def test_mixed_calibration_sides_normalize_to_positive_target_and_report_same_as_inference():
    a=binary_artifact()
    rows=[]
    for i in range(200):
        side='yes' if i%2 else 'no'
        rows.append({'features':{'red_zone_share':i/100-1},'observed_value':int(i%5<2),
                     'market_side':side,'market_line':.5})
    a['calibration']=_fit_calibration(a,rows)
    assert a['calibration']['orientation']=='positive'
    result=_validation(a,rows)
    probs=[calibrated_probability(a,r['features'],r['market_side'],.5) for r in rows]
    ys=[r['observed_value'] if r['market_side']=='yes' else 1-r['observed_value'] for r in rows]
    assert result['brier']==pytest.approx(np.mean((np.array(probs)-ys)**2))


def test_malformed_scaler_and_nonfinite_line_cannot_generate_probability():
    a=count_artifact(); a['scaler']['scale']=[]
    with pytest.raises(ValueError,match='scaler'):raw_probability(a,{'usage':0},'over',4.5)
    with pytest.raises(ValueError,match='Non-finite'):raw_probability(count_artifact(),{'usage':0},'over',math.nan)


def test_one_game_cannot_cross_training_and_calibration_boundaries():
    from test_prop_data import dataset, inspect
    d=dataset(); duplicate=deepcopy(d['rows'][0]);duplicate['player_id']='other'
    duplicate.update(prediction_at='2024-01-01T00:00:00Z', starts_at='2024-01-01T01:00:00Z',result_available_at='2024-01-01T05:00:00Z')
    d['rows'].append(duplicate)
    with pytest.raises(ValueError,match='Event identity'):inspect(d)
