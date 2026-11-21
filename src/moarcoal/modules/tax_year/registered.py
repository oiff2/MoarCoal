"""Die Anlagen, die das Steuerjahr kennt; eine neue meldet man hier an."""

from moarcoal.modules.tax_year.anlage_est1a import ANLAGE_EST1A
from moarcoal.modules.tax_year.anlage_n import ANLAGE_N
from moarcoal.modules.tax_year.anlage_sa import ANLAGE_SA
from moarcoal.modules.tax_year.anlage_v import ANLAGE_V
from moarcoal.modules.tax_year.anlage_vor import ANLAGE_VOR
from moarcoal.modules.tax_year.anlagen import Anlage

ANLAGEN: tuple[Anlage, ...] = (ANLAGE_EST1A, ANLAGE_N, ANLAGE_SA, ANLAGE_V, ANLAGE_VOR)
