"""One module per source plus the registry the CLI walks.

Order is the landing order from sources.md: Eventbrite first (68 rows, zero parsing risk), then
Luma, the two campuses, and Meetup last because its page is the heaviest.
"""

from __future__ import annotations

from . import clubs, eventbrite, local_tech, luma, meetup
from .base import Adapter, Http, RedLineError, SourceBlocked, Stats

ADAPTERS: dict[str, Adapter] = {
    "eventbrite": eventbrite.Eventbrite(),
    "luma": luma.Luma(),
    "luma_discover": luma.LumaDiscover(),
    "invest_ottawa": local_tech.InvestOttawa(),
    "kanata_north": local_tech.KanataNorth(),
    "clubs_uottawa": clubs.UOttawaClubs(),
    "clubs_carleton": clubs.CarletonClubs(),
    "meetup": meetup.Meetup(),
}

__all__ = ["ADAPTERS", "Adapter", "Http", "RedLineError", "SourceBlocked", "Stats"]
