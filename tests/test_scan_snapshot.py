from types import SimpleNamespace as NS
from unittest.mock import Mock

from jabazi import api
from jabazi.persistence.store import Store


def test_manual_scan_refreshes_vip_archive_and_reports_write_failure(tmp_path, monkeypatch):
    result=NS(actions=[],arbitrages=[],errors=[],feeds_scanned=2,quotes_archived=0,
              credits_remaining=100,event_market_coverage={},slate_events=[])
    monkeypatch.setattr(api.Settings,'from_environment',lambda:NS(api_key='synthetic',database_path='unused'))
    monkeypatch.setattr(api,'AutomaticScanner',lambda *a,**k:NS(run=lambda mode:result))
    url='sqlite:///'+str(tmp_path/'snapshot.db')
    monkeypatch.setattr(api,'platform_store',lambda:Store(url,initialize=True))
    response=api.perform_scan(api.ScanRequest())
    assert response['vip_snapshot_status']=='UPDATED'
    store=Store(url)
    sheet=store.list_records('research_sheet',1,entity='latest_scan')[0]['payload']
    assert sheet['feeds']==2 and sheet['healthy'] and sheet['rows']==[]
    store.close()
    monkeypatch.setattr(api,'platform_store',Mock(side_effect=RuntimeError('private details')))
    response=api.perform_scan(api.ScanRequest())
    assert response['vip_snapshot_status']=='UNAVAILABLE'
    assert 'private details' not in str(response)
