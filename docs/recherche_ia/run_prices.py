import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from research import *
folder = ROOT/"research"/"daily" if len(sys.argv) > 1 and sys.argv[1] == "5y" else ROOT/"daily"
panel = Panel(load_closes(folder, AI + ["SPX"]))
D0 = date(2023,1,1) if folder.name == "daily" and "research" in str(folder) else date(2024,10,1)
disc, hold = (D0, date(2026,3,31)), (date(2026,4,1), date(2026,9,25))
print("univers:", len(panel.s), "calendrier", panel.cal[0], panel.cal[-1])
for name, f in [("P1 retournement 1m (-)", p1_rev1m), ("P2 mom 12-1 (+)", p2_mom12_1), ("P3 52s haut (+)", p3_52wh),
                ("P4 MAX (-)", p4_max), ("P5 rev 1 sem (-)", p5_rev1w)]:
    m, tt, n = evaluate(panel, f, *disc)
    print(f"{name:26} découverte IC {m:+.3f} t {tt if tt is None else round(tt,2)} n={n}")
