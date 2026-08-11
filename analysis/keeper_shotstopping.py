"""WM-2026 Torhueter-Shotstopping: Goals-Prevented-PROXY aus Zaehlstatistik.

Hintergrund (2026-06-25, hart verifiziert): FBref fuehrt im Gratis-Tier KEINE
Expected-Daten mehr (kein xG/xA/PSxG -- StatsBomb-Partnerschaft beendet, ueber
5 Seiten geprueft inkl. Einzelspieler). Die ideale Keeper-Metrik PSxG-GA
("wirklich gehaltene Tore") ist damit frei nicht mehr beziehbar.

Bestmoeglicher freier Ersatz = ein Goals-Prevented-PROXY aus Zaehlstatistik:
  erwartete_Gegentore(Durchschnittskeeper) = SoTA * (Sigma GA / Sigma SoTA)
  goals_prevented_proxy                    = erwartete_Gegentore - GA

LIMIT (ehrlich): KEINE Schussqualitaet (ein Durchschnitts-Save-Rate je Schuss
aufs Tor, nicht je Schussschwere wie PSxG) und winzige Stichprobe (2 Spiele).
Zeigt aber bereits, warum nacktes Save% irrefuehrt (ein 100%-Keeper mit 2 leichten
Schuessen hat real fast nichts verhindert). Datenquelle: FBref WM-2026 Keeper
(Zaehlstatistik), erfasst per Browser 2026-06-25.

Lauf:  python3 analysis/keeper_shotstopping.py
"""
import math

# (player, team, 90s, GA, SoTA, saves, save_pct, clean_sheets)
KEEPERS = [
    ("Yazeed Abulaila", "Jordan", 2.0, 5, 12, 7, 58.3, 0),
    ("Mahmoud Abunada", "Qatar", 2.0, 7, 16, 9, 56.3, 0),
    ("Alisson", "Brazil", 2.0, 1, 6, 5, 83.3, 1),
    ("Benjamin Asare", "Ghana", 1.5, 0, 6, 6, 100.0, 2),
    ("Lawrence Ati-Zigi", "Ghana", 0.5, 0, 1, 1, 100.0, 1),
    ("Ahmed Basil", "Iraq", 1.0, 3, 5, 2, 40.0, 0),
    ("Patrick Beach", "Australia", 2.0, 2, 11, 9, 81.8, 1),
    ("Alireza Beiranvand", "Iran", 2.0, 2, 15, 13, 86.7, 1),
    ("Yassine Bounou", "Morocco", 2.0, 1, 5, 4, 80.0, 1),
    ("Ugurcan Cakir", "Turkiye", 2.0, 3, 6, 3, 50.0, 0),
    ("Mouhib Chamakh", "Tunisia", 1.0, 5, 6, 1, 16.7, 0),
    ("Diogo Costa", "Portugal", 2.0, 1, 4, 3, 75.0, 1),
    ("Thibaut Courtois", "Belgium", 2.0, 1, 6, 5, 83.3, 1),
    ("Maxime Crepeau", "Canada", 2.0, 1, 3, 2, 66.7, 1),
    ("Max Crocombe", "New Zealand", 2.0, 5, 11, 6, 54.5, 0),
    ("Aymen Dahmen", "Tunisia", 1.0, 4, 5, 1, 20.0, 0),
    ("Mory Diaw", "Senegal", 0.3, 0, 0, 0, None, 0),
    ("Yahia Fofana", "Cote d'Ivoire", 2.0, 2, 8, 6, 75.0, 1),
    ("Matt Freese", "United States", 2.0, 1, 3, 2, 66.7, 1),
    ("Hernan Galindez", "Ecuador", 2.0, 1, 7, 6, 85.7, 1),
    ("Orlando Gill", "Paraguay", 2.0, 4, 12, 8, 66.7, 1),
    ("Angus Gunn", "Scotland", 2.0, 1, 4, 3, 75.0, 1),
    ("Jalal Hassan", "Iraq", 1.0, 4, 6, 2, 33.3, 0),
    ("Gregor Kobel", "Switzerland", 2.0, 2, 7, 5, 71.4, 0),
    ("Matej Kovar", "Czechia", 2.0, 3, 10, 7, 70.0, 0),
    ("Dominik Livakovic", "Croatia", 2.0, 4, 12, 8, 66.7, 1),
    ("Mike Maignan", "France", 2.0, 1, 3, 2, 66.7, 1),
    ("Emiliano Martinez", "Argentina", 2.0, 0, 1, 1, 100.0, 2),
    ("Edouard Mendy", "Senegal", 1.7, 6, 14, 8, 57.1, 0),
    ("Orlando Mosquera", "Panama", 2.0, 2, 5, 3, 60.0, 0),
    ("Lionel Mpasi", "Congo DR", 2.0, 2, 10, 8, 80.0, 0),
    ("Fernando Muslera", "Uruguay", 2.0, 3, 7, 4, 57.1, 0),
    ("Abduvohid Nematov", "Uzbekistan", 1.0, 5, 9, 4, 44.4, 0),
    ("Manuel Neuer", "Germany", 2.0, 2, 4, 2, 50.0, 0),
    ("Kristoffer Nordfeldt", "Sweden", 2.0, 6, 9, 3, 33.3, 0),
    ("Orjan Nyland", "Norway", 2.0, 3, 5, 2, 40.0, 0),
    ("Mohammed Al-Owais", "Saudi Arabia", 2.0, 5, 19, 14, 73.7, 0),
    ("Jordan Pickford", "England", 2.0, 2, 5, 3, 60.0, 1),
    ("Johny Placide", "Haiti", 2.0, 4, 7, 3, 42.9, 0),
    ("Raul Rangel", "Mexico", 2.0, 0, 4, 4, 100.0, 2),
    ("Eloy Room", "Curacao", 2.0, 7, 26, 19, 73.1, 1),
    ("Alexander Schlager", "Austria", 2.0, 3, 8, 5, 62.5, 0),
    ("Kim Seung-gyu", "Korea Republic", 2.0, 2, 8, 6, 75.0, 0),
    ("Mostafa Shobeir", "Egypt", 2.0, 2, 9, 7, 77.8, 0),
    ("Unai Simon", "Spain", 2.0, 0, 2, 2, 100.0, 2),
    ("Zion Suzuki", "Japan", 2.0, 2, 6, 4, 66.7, 1),
    ("Camilo Vargas", "Colombia", 2.0, 1, 3, 2, 66.7, 1),
    ("Nikola Vasilj", "Bosnia & Herz.", 2.0, 5, 9, 4, 44.4, 0),
    ("Bart Verbruggen", "Netherlands", 2.0, 3, 11, 8, 72.7, 0),
    ("Vozinha", "Cabo Verde", 2.0, 2, 9, 7, 77.8, 1),
    ("Ronwen Williams", "South Africa", 2.0, 3, 7, 4, 57.1, 0),
    ("Utkir Yusupov", "Uzbekistan", 1.0, 3, 4, 1, 25.0, 0),
    ("Luca Zidane", "Algeria", 2.0, 4, 10, 6, 60.0, 0),
]


def main():
    tot_ga = sum(k[3] for k in KEEPERS)
    tot_sota = sum(k[4] for k in KEEPERS)
    rate = tot_ga / tot_sota  # Gegentore je Schuss aufs Tor (= 1 - Liga-Save%)
    print(f"WM 2026 -- Torhueter-Shotstopping (Goals-Prevented-PROXY)")
    print(f"Sigma GA={tot_ga}  Sigma SoTA={tot_sota}  Liga-Rate={rate:.3f} "
          f"GG/SoT  (Liga-Save% {100*(1-rate):.1f})")
    print(f"Proxy = SoTA*Rate - GA   (+ = besser als Durchschnitt; KEINE Schussqualitaet)\n")

    rows = []
    for name, team, n90, ga, sota, saves, sp, cs in KEEPERS:
        exp = sota * rate
        prevented = exp - ga
        per90 = prevented / n90 if n90 else 0.0
        rows.append((prevented, per90, name, team, n90, ga, sota, sp, cs))

    starters = [r for r in rows if r[4] >= 1.5]  # nur echte Stammkeeper ranken
    starters.sort(reverse=True)
    print(f"-- Beste Shotstopper (Proxy, Stammkeeper >=1.5x90) --")
    print(f"   {'Keeper':<20}{'Team':<16}{'SoTA':>5}{'GA':>4}{'Save%':>7}{'verhind.':>9}")
    for prevented, per90, name, team, n90, ga, sota, sp, cs in starters[:8]:
        spx = f"{sp:.0f}" if sp is not None else "-"
        print(f"   {name:<20}{team:<16}{sota:>5}{ga:>4}{spx:>7}{prevented:>+9.2f}")
    print(f"\n-- Schwaechste Shotstopper (Proxy) --")
    for prevented, per90, name, team, n90, ga, sota, sp, cs in starters[-6:]:
        spx = f"{sp:.0f}" if sp is not None else "-"
        print(f"   {name:<20}{team:<16}{sota:>5}{ga:>4}{spx:>7}{prevented:>+9.2f}")

    # Lehre: Save% vs Proxy divergieren bei kleinem Schussvolumen
    print(f"\n-- Warum Save% allein irrefuehrt (100%-Keeper) --")
    for prevented, per90, name, team, n90, ga, sota, sp, cs in rows:
        if sp == 100.0 and n90 >= 1.0:
            print(f"   {name:<20}{team:<16} Save% 100 aber nur {sota} SoT -> "
                  f"Proxy nur {prevented:+.2f} verhinderte Tore")

    # Skizze: so wuerde ein PROXY-skalierter Keeper-Ausfall-Malus aussehen
    # (heute: flacher Floor 0.4). Wert pro 90, auf [0.4 .. 1.2] gemappt.
    print(f"\n-- Skizze T-0115: Keeper-Ausfall-Skalierung statt Flat-Floor 0.4 --")
    vals = [r[1] for r in starters]
    lo, hi = min(vals), max(vals)
    for label in ("Alireza Beiranvand", "Manuel Neuer", "Eloy Room", "Mouhib Chamakh"):
        for prevented, per90, name, team, n90, ga, sota, sp, cs in rows:
            if name == label:
                scale = 0.4 + 0.8 * (per90 - lo) / (hi - lo) if hi > lo else 0.4
                print(f"   {name:<20} verhind/90 {per90:+.2f} -> Malus-Skala {scale:.2f} "
                      f"(heute pauschal 0.40)")
                break


if __name__ == "__main__":
    main()
