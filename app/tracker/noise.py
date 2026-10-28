"""User-selected spatial noise exclusions, independent of recycled target IDs."""
from dataclasses import asdict, dataclass
import math
import uuid


@dataclass(frozen=True)
class NoiseZone:
    id: str
    x_mm: float
    y_mm: float
    radius_mm: float = 300.0

    def __post_init__(self):
        if (not self.id or not all(math.isfinite(v) for v in (self.x_mm,self.y_mm,self.radius_mm))
                or not 50 <= self.radius_mm <= 1500):
            raise ValueError('Noise exclusions need finite coordinates and a 50–1500 mm radius')

    def contains(self,x,y):
        return math.hypot(x-self.x_mm,y-self.y_mm) <= self.radius_mm

    def to_dict(self):
        return asdict(self)

    @classmethod
    def create(cls,x,y,radius):
        return cls(uuid.uuid4().hex[:8],float(x),float(y),float(radius))


def load_zones(records):
    zones=[]
    if not isinstance(records,list):
        return zones
    for entry in records:
        try:
            zone=NoiseZone(str(entry['id']),float(entry['x_mm']),float(entry['y_mm']),float(entry['radius_mm']))
        except (KeyError,TypeError,ValueError,OverflowError):
            continue
        if zone.id not in {z.id for z in zones}:
            zones.append(zone)
    return zones
