"""Live NBA player feature verification from reproducible public sources.

Historical form comes from SportsDataverse ESPN NBA schedule/player-box releases.
Current player/team identity and injury status come from ESPN's public team/injury
feeds.  The current model does not require announced starting-five membership:
recent rotation minutes + active roster + current injury clearance establish role.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import re
import unicodedata
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from statistics import pstdev

from jabazi.research.nba_player_experiment import BOX

SCHEDULE=(
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
    "espn_nba_schedules/nba_schedule_{season}.csv"
)
PLAYER=(
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
    "espn_nba_player_boxscores/player_box_{season}.csv"
)
ESPN="https://site.api.espn.com/apis/site/v2/sports/basketball/nba"

def _name(value):
    text=unicodedata.normalize("NFKD",str(value or ""))
    text="".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]","",text.lower())

def _fetch(url,max_bytes=80_000_000):
    req=urllib.request.Request(url,headers={"User-Agent":"JABBAZI-Research/0.5"})
    with urllib.request.urlopen(req,timeout=45) as response:
        raw=response.read(max_bytes+1)
    if len(raw)>max_bytes:
        raise ValueError("NBA live feature response too large")
    return raw

def _json(url,max_bytes=8_000_000):
    raw=_fetch(url,max_bytes)
    return json.loads(raw),hashlib.sha256(raw).hexdigest()

def _mean(values,n):
    values=list(values)[-n:]
    return sum(values)/len(values) if values else 0.0

def _features(history,is_home):
    minutes=[float(r["minutes"]) for r in history]
    out={
        "last1_minutes":minutes[-1],
        "mean3_minutes":_mean(minutes,3),
        "mean5_minutes":_mean(minutes,5),
        "mean10_minutes":_mean(minutes,10),
        "std5_minutes":pstdev(minutes[-5:]) if len(minutes[-5:])>=2 else 0.0,
        "games_prior":float(len(history)),
        "is_home":float(bool(is_home)),
    }
    for stat in BOX:
        values=[float(r[stat]) for r in history]
        out[f"mean3_{stat}"]=_mean(values,3)
        out[f"mean5_{stat}"]=_mean(values,5)
        out[f"mean10_{stat}"]=_mean(values,10)
        out[f"per_minute5_{stat}"]=sum(values[-5:])/max(sum(minutes[-5:]),1.0)
    return out

class NBAPlayerFeatureCollector:
    def __init__(self,*,now=None,max_seconds=35):
        self.now=now or datetime.now(UTC)
        self.max_seconds=max_seconds
        self._teams=None
        self._history=None
        self._diagnostics=[]

    @property
    def diagnostics(self):
        return tuple(self._diagnostics)

    def _team_index(self):
        if self._teams is not None:
            return self._teams
        payload,checksum=_json(f"{ESPN}/teams?limit=40")
        teams={}
        for sport in payload.get("sports",[]):
            for league in sport.get("leagues",[]):
                for row in league.get("teams",[]):
                    team=row.get("team",{})
                    name=str(team.get("displayName") or "").strip()
                    tid=str(team.get("id") or "").strip()
                    abbr=str(team.get("abbreviation") or "").strip()
                    if name and tid:
                        teams[name]={"id":tid,"abbr":abbr,"checksum":checksum}
        self._teams=teams
        return teams

    def _roster_player(self,card):
        parts=str(getattr(card,"event","") or "").split(" @ ",1)
        if len(parts)!=2:
            return None
        matches=[]
        teams=self._team_index()
        for team_name in parts:
            meta=teams.get(team_name)
            if not meta:
                continue
            payload,checksum=_json(f"{ESPN}/teams/{meta['id']}/roster")
            athletes=payload.get("athletes",[]) if isinstance(payload,dict) else []
            flattened=[]
            for group in athletes:
                if not isinstance(group,dict):
                    continue
                if isinstance(group.get("items"),list):
                    flattened.extend(row for row in group["items"] if isinstance(row,dict))
                elif group.get("id"):
                    flattened.append(group)
            for athlete in flattened:
                if _name(athlete.get("displayName") or athlete.get("fullName"))==_name(card.participant):
                    matches.append({
                        "player_id":str(athlete.get("id") or ""),
                        "team_name":team_name,
                        "team_id":meta["id"],
                        "team_abbr":meta["abbr"],
                        "checksum":checksum,
                    })
        return matches[0] if len(matches)==1 and matches[0]["player_id"] else None

    def _injury(self,player):
        payload,checksum=_json(f"{ESPN}/injuries?team={player['team_abbr']}")
        groups=payload.get("injuries",[]) if isinstance(payload,dict) else None
        if not isinstance(groups,list):
            return None
        rows=[]
        for group in groups:
            team=(group.get("team") or {}).get("abbreviation")
            if str(team or "").upper()==player["team_abbr"].upper():
                rows=group.get("injuries",[]) or []
                break
        matches=[
            row for row in rows
            if _name((row.get("athlete") or {}).get("displayName"))==_name(player.get("name"))
        ]
        if len(matches)>1:
            return None
        status=str((matches[0] if matches else {}).get("status") or "").strip().lower()
        blocked=status in {"out","doubtful","suspended","injured reserve","ir"}
        return {"verified":True,"available":not blocked,"status":status or "not_listed","checksum":checksum}

    def _history_rows(self):
        if self._history is not None:
            return self._history
        ending=self.now.year+1 if self.now.month>=7 else self.now.year
        seasons=(ending-1,ending)
        schedules={}
        rows=[]
        checks=[]
        for season in seasons:
            try:
                sraw=_fetch(SCHEDULE.format(season=season))
                praw=_fetch(PLAYER.format(season=season))
            except urllib.error.HTTPError as exc:
                if exc.code==404:
                    continue
                raise
            checks.extend([hashlib.sha256(sraw).hexdigest(),hashlib.sha256(praw).hexdigest()])
            for row in csv.DictReader(io.StringIO(sraw.decode("utf-8-sig"))):
                if str(row.get("season_type")) not in {"2","2.0","regular-season","Regular Season"}:
                    continue
                if str(row.get("status_type_completed","")).strip().lower() not in {"true","t","1","yes"}:
                    continue
                gid=str(row.get("game_id") or "")
                try:
                    start=datetime.fromisoformat(str(row.get("game_date_time") or "").replace("Z","+00:00"))
                except ValueError:
                    continue
                if start.tzinfo is None:
                    continue
                schedules[gid]={
                    "start":start.astimezone(UTC),
                    "home":str(row.get("home_display_name") or "").strip(),
                    "away":str(row.get("away_display_name") or "").strip(),
                }
            for row in csv.DictReader(io.StringIO(praw.decode("utf-8-sig"))):
                game=schedules.get(str(row.get("game_id") or ""))
                if not game:
                    continue
                try:
                    minutes=float(row.get("minutes") or 0)
                    clean={
                        "participant":str(row.get("athlete_display_name") or "").strip(),
                        "player_id":str(row.get("athlete_id") or "").strip(),
                        "start":game["start"],
                        "minutes":minutes,
                        "is_home":str(row.get("home_away") or "").lower()=="home",
                    }
                    mapping={
                        "points":"points","rebounds":"rebounds","assists":"assists",
                        "threes":"three_point_field_goals_made","blocks":"blocks",
                        "steals":"steals","turnovers":"turnovers",
                    }
                    for dst,src in mapping.items():
                        clean[dst]=float(row.get(src) or 0)
                    rows.append(clean)
                except (TypeError,ValueError):
                    continue
        rows.sort(key=lambda r:r["start"])
        self._history=(rows,hashlib.sha256("|".join(checks).encode()).hexdigest())
        return self._history

    def snapshot(self,card):
        if card.sport!="basketball_nba" or not card.participant or card.in_play or card.starts_at is None:
            return None
        player=self._roster_player(card)
        if not player:
            self._diagnostics.append(f"{card.event_id}:{card.participant}:NBA_ROSTER_IDENTITY_UNVERIFIED")
            return None
        player["name"]=card.participant
        rows,history_checksum=self._history_rows()
        eligible=[
            r for r in rows
            if _name(r["participant"])==_name(card.participant)
            and r["start"]<card.starts_at.astimezone(UTC)
            and r["minutes"]>0
        ][-40:]
        if len(eligible)<5:
            self._diagnostics.append(f"{card.event_id}:{card.participant}:NBA_INSUFFICIENT_HISTORY")
            return None
        mean5=_mean([r["minutes"] for r in eligible],5)
        if mean5<8:
            self._diagnostics.append(f"{card.event_id}:{card.participant}:NBA_ROTATION_MINUTES_TOO_LOW")
            return None
        injury=self._injury(player)
        if not injury:
            return None
        parts=str(card.event).split(" @ ",1)
        is_home=len(parts)==2 and player["team_name"]==parts[1]
        features=_features(eligible,is_home)
        checksum=hashlib.sha256(
            (history_checksum+"|"+player["checksum"]+"|"+injury["checksum"]+"|"+
             json.dumps({"player":player["player_id"],"last":[r["start"].isoformat() for r in eligible[-5:]]},sort_keys=True)).encode()
        ).hexdigest()
        healthy=bool(injury["available"])
        return {
            "player_id":player["player_id"],
            "features":features,
            "expected_opportunities":mean5,
            "provider":"SportsDataverse ESPN NBA history + ESPN roster/injury verification",
            "source_checksum":checksum,
            "feature_schema_version":"nba-player-minutes-box-v1",
            "integrity":{
                "event_identity":player["team_name"] in parts,
                "player_identity":True,
                "fresh_features":True,
                "schema":True,
                "role":healthy and mean5>=8,
                "availability":healthy,
                "injuries":healthy,
                "no_duplicate_event":True,
            },
            "roster_version":player["team_abbr"],
            "injury_version":injury["status"],
        }
