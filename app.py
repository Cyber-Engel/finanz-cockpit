import streamlit as st
import pandas as pd
import altair as alt
import io
import hashlib

# 1. Grundkonfiguration
st.set_page_config(page_title="Finanz-Cockpit Pro", page_icon="🏢", layout="wide")

# --- INITIALISIERUNG SESSION STATE (Das Gedächtnis) ---
defaults = {
    'ausgaben_fix': 2000, 'ausgaben_wohnen': 1000, 'inflation_pa': 2.0,
    'gehalt_p1': 3500, 'rente_jahr_p1': 35, 'lohnerhoehung_pa_p1': 1.0, 'anzahl_befoerderungen_p1': 2, 'sprung_rate_p1': 10, 'sprung_intervall_p1': 5,
    'gehalt_p2': 3000, 'rente_jahr_p2': 35, 'lohnerhoehung_pa_p2': 1.0, 'anzahl_befoerderungen_p2': 1, 'sprung_rate_p2': 10, 'sprung_intervall_p2': 7,
    'pause_start': 0, 'pause_ende': 0, 'ersatz_rate': 65,
    'auto_budget': 30000, 'a_jahr': 5, 'auto_regelmaessig': False, 'auto_intervall': 8,
    'urlaub_budget': 5000, 'hochzeit': 0, 'h_jahr': 0, 'erbe_betrag': 0, 'erbe_jahr': 0,
    'anzahl_kinder': 0, 'kindergeld_aktiv': True,
    'wohneigentum_geplant': False, 'kauf_jahr': 5, 'eigenkapital': 50000, 'wohnflaeche': 120, 'nebenkosten_qm': 3.5, 'instandhaltung_qm': 1.5,
    'kredit_summe': 300000, 'zins_pa': 3.5, 'tilgung_pa': 2.0, 'sondertilgung': 0, 'sondertilgung_jahr': 10,
    'rendite_depot': 7.0, 'rendite_konto': 2.0, 'jahre_plan': 40, 'quote_depot': 80,
    'max_tagesgeld': 20000, 'max_tagesgeld_nach_hauskauf': 40000, 'max_tagesgeld_nach_kind': 30000,
    'start_depot_fallback': 10000, 'start_konto_fallback': 5000,
    'start_immo': 0.0, 'start_schuld': 0.0  # Scope-Bug Fix für Export
}

# Werte ins Kurzzeitgedächtnis schreiben
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

if 'hist_daten' not in st.session_state:
    st.session_state['hist_daten'] = []
if 'kinder_daten' not in st.session_state:
    st.session_state['kinder_daten'] = []
if 'start_kalenderjahr' not in st.session_state:
    st.session_state['start_kalenderjahr'] = 2026
if 'last_loaded_file_hash' not in st.session_state:
    st.session_state['last_loaded_file_hash'] = None

# --- HILFSFUNKTIONEN ---

def format_euro_smart(wert):
    if wert >= 1000000:
        return f"{wert / 1000000:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " Mio."
    return f"{wert:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# Performance-Fix: Gecachter Excel-Export ohne Scope-Bug
@st.cache_data
def generate_excel_cached(params_dict, kinder_daten, hist_daten):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        param_data = [{"Parameter": k, "Wert": v} for k, v in params_dict.items() if k in defaults]
        pd.DataFrame(param_data).to_excel(writer, sheet_name='Parameter', index=False)
        
        if kinder_daten:
            pd.DataFrame(kinder_daten).to_excel(writer, sheet_name='Kinder', index=False)
            
        export_hist = []
        for h in hist_daten:
            export_hist.append({"Jahr": h["Kalenderjahr"], "Depot": h["Depot"], "Tagesgeld": h["Tagesgeld"], "Immo": h["Immobilienwert"], "Schuld": h["Restschuld"]})
        
        # Startwerte für die nächste Berechnung hinzufügen
        export_hist.append({
            "Jahr": params_dict.get('start_kalenderjahr', 2026), 
            "Depot": params_dict.get('start_depot_fallback', 0), 
            "Tagesgeld": params_dict.get('start_konto_fallback', 0), 
            "Immo": params_dict.get('start_immo', 0.0), 
            "Schuld": params_dict.get('start_schuld', 0.0)
        })
        pd.DataFrame(export_hist).to_excel(writer, sheet_name='Historie', index=False)
        
    output.seek(0)
    return output.getvalue()

# DRY-Fix: Einheitliche Vorschau für Gehalt P1 & P2
def render_gehaltsvorschau(gehalt, rente_j, erhoehung, anz_bef, sprung, intervall, color, pause=None):
    jahre_vorschau = list(range(51))
    gehalt_list = []
    akt_gehalt = gehalt
    bef_gemacht = 0
    summe_gehalt = 0
    monate_work = 0
    
    for j in jahre_vorschau:
        if j >= rente_j:
            avg = (summe_gehalt / max(1, monate_work)) if monate_work > 0 else akt_gehalt
            gehalt_list.append(avg * 0.375)
        else:
            if j > 0:
                akt_gehalt *= (1 + (erhoehung / 100))
                if j % intervall == 0 and bef_gemacht < anz_bef:
                    akt_gehalt *= (1 + (sprung / 100))
                    bef_gemacht += 1
            
            eink_monat = akt_gehalt
            if pause and pause[0] <= j < pause[1]:
                eink_monat *= (st.session_state['ersatz_rate'] / 100)
                
            summe_gehalt += eink_monat * 12
            monate_work += 12
            gehalt_list.append(eink_monat)
            
    df = pd.DataFrame({"Jahr": jahre_vorschau, "Netto-Gehalt (€)": gehalt_list}).set_index("Jahr")
    st.line_chart(df, color=color)

# --- SEITENLEISTE: SPEICHERN & LADEN ---
with st.sidebar:
    st.header("💾 Profil-Management")
    st.write("Speichere dein Setup oder lade ein altes.")
    
    uploaded_file = st.file_uploader("📂 Profil/Historie laden (.xlsx)", type=["xlsx"])
    
    # Bug-Fix: Einmaliger Upload-Check über Dateihash
    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        file_hash = hashlib.md5(file_bytes).hexdigest()
        
        # Nur ausführen, wenn es eine NEUE Datei ist
        if st.session_state['last_loaded_file_hash'] != file_hash:
            try:
                xls = pd.ExcelFile(io.BytesIO(file_bytes))
                
                if 'Parameter' in xls.sheet_names:
                    df_params = pd.read_excel(xls, sheet_name='Parameter')
                    for _, row in df_params.iterrows():
                        key = row['Parameter']
                        wert = row['Wert']
                        
                        if key in st.session_state and key in defaults and pd.notna(wert):
                            ziel_typ = type(defaults[key])
                            if ziel_typ == bool:
                                st.session_state[key] = bool(int(wert))
                            else:
                                st.session_state[key] = ziel_typ(wert)
                
                if 'Kinder' in xls.sheet_names:
                    df_kinder = pd.read_excel(xls, sheet_name='Kinder')
                    kinder_import = []
                    for _, row in df_kinder.iterrows():
                        kinder_import.append({
                            "jahr": int(row['jahr']) if pd.notna(row['jahr']) else 0,
                            "basis_kosten": int(row['basis_kosten']) if pd.notna(row['basis_kosten']) else 0
                        })
                    st.session_state['kinder_daten'] = kinder_import
                
                sheet_to_load = 'Historie' if 'Historie' in xls.sheet_names else 0
                df_hist = pd.read_excel(xls, sheet_name=sheet_to_load, usecols="A:E")
                df_hist.columns = ["Jahr", "Depot", "Tagesgeld", "Immo", "Schuld"]
                df_hist = df_hist.dropna(subset=["Depot", "Tagesgeld"])
                
                if not df_hist.empty:
                    letzter_stand = df_hist.iloc[-1]
                    st.session_state['start_kalenderjahr'] = int(letzter_stand["Jahr"])
                    st.session_state['start_depot_fallback'] = float(letzter_stand["Depot"])
                    st.session_state['start_konto_fallback'] = float(letzter_stand["Tagesgeld"])
                    
                    st.session_state['start_immo'] = float(pd.to_numeric(letzter_stand["Immo"], errors='coerce'))
                    st.session_state['start_schuld'] = float(pd.to_numeric(letzter_stand["Schuld"], errors='coerce'))
                    
                    temp_hist = []
                    for idx, row in df_hist.iloc[:-1].iterrows():
                        i_val = pd.to_numeric(row["Immo"], errors='coerce')
                        s_val = pd.to_numeric(row["Schuld"], errors='coerce')
                        temp_hist.append({
                            "Kalenderjahr": int(row["Jahr"]),
                            "Jahr": int(row["Jahr"]) - st.session_state['start_kalenderjahr'],
                            "Depot": float(row["Depot"]),
                            "Tagesgeld": float(row["Tagesgeld"]),
                            "Immobilienwert": float(i_val) if pd.notna(i_val) else 0.0,
                            "Restschuld": float(s_val) if pd.notna(s_val) else 0.0
                        })
                    st.session_state['hist_daten'] = temp_hist
                
                st.session_state['last_loaded_file_hash'] = file_hash
                st.success("✅ Profil & Historie erfolgreich geladen!")
                st.rerun() 
                
            except Exception as e:
                st.error(f"Fehler beim Laden: {e}")

    st.markdown("---")
    
    excel_data = generate_excel_cached(
        dict(st.session_state), 
        st.session_state.get('kinder_daten', []), 
        st.session_state.get('hist_daten', [])
    )
    
    st.download_button(
        label="📥 Aktuelles Profil speichern",
        data=excel_data,
        file_name="Finanz_Profil.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Lädt eine Excel herunter, die du beim nächsten Mal wieder hochladen kannst."
    )

st.title("🏢 Strategisches Familien-Finanz-Cockpit")
st.write("Maximale Realität: Intelligente Engpass-Analyse, Cash-Sweep und Netto-Lohnentwicklung.")

tab1, tab2, tab3, tab4 = st.tabs(["👥 Status Quo & Karriere", "📅 Familien- und Ausgabenplanung", "🏠 Immobilien", "📈 Analyse"])

# Globale Startwerte
hist_daten = st.session_state['hist_daten']
start_kalenderjahr = st.session_state['start_kalenderjahr']
start_depot = st.session_state['start_depot_fallback']
start_konto = st.session_state['start_konto_fallback']
start_immo = st.session_state['start_immo']
start_schuld = st.session_state['start_schuld']

# --- TAB 1: STATUS QUO, EINKOMMEN & PARTNER ---
with tab1:
    st.header("Ausgangslage & Karrierewege")
    
    st.subheader("Dein Start-Punkt & Haushaltskosten")
    col_start1, col_start2, col_start3 = st.columns(3)
    with col_start1:
        st.write("**Startkapital (ohne Upload)**")
        start_depot = st.number_input("Startkapital Depot (€)", step=500, key='start_depot_fallback')
        start_konto = st.number_input("Startkapital Tagesgeld (€)", step=500, key='start_konto_fallback')

    with col_start2:
        ausgaben_fix = st.number_input("Fixkosten ohne Wohnen (€)", step=100, key='ausgaben_fix')
        ausgaben_wohnen = st.number_input("Wohnkosten (Miete etc.) (€)", step=100, key='ausgaben_wohnen')
    with col_start3:
        inflation_pa = st.slider("Globale jährliche Inflation (%)", 0.0, 10.0, key='inflation_pa')

    st.markdown("---")
    st.subheader("Einkommen, Pausen & Rente")
    
    st.info("ℹ️ **Information zur Rente:** Das Tool simuliert deine Rente automatisch. Es rechnet pauschal mit **37,5 % deines durchschnittlichen kaufkraftbereinigten Netto-Gehalts** ab dem festgelegten Renteneintrittsjahr.")
    
    col_p1, col_p2 = st.columns(2)
    progression_help = "Tipp: Da hier auf das Netto-Gehalt gerechnet wird, frisst die kalte Progression einen Teil der Brutto-Erhöhung auf. Plane hier nur mit ca. 50 % des erwarteten Brutto-Wertes."
    
    with col_p1:
        st.write("**Person 1 (Du)**")
        gehalt_p1 = st.number_input("Netto-Gehalt P1 (€)", step=100, key='gehalt_p1')
        rente_jahr_p1 = st.number_input("Renteneintritt P1 (in X Jahren)", 0, 60, key='rente_jahr_p1')
        
        st.markdown("*Karriere-Planung P1*")
        st.warning("⚠️ **Kalte Progression:** Trage bei den folgenden Werten nur ca. 50 % der erwarteten *Brutto*-Erhöhung ein.")
        lohnerhoehung_pa_p1 = st.slider("Allg. jährliche Lohnerhöhung P1 (%)", 0.0, 10.0, step=0.1, help=progression_help, key='lohnerhoehung_pa_p1')
        anzahl_befoerderungen_p1 = st.number_input("Anzahl geplanter Beförderungen P1", 0, 10, key='anzahl_befoerderungen_p1')
        sprung_rate_p1 = st.slider("Gehaltssprung pro Beförderung P1 (%)", 0, 30, help=progression_help, key='sprung_rate_p1')
        sprung_intervall_p1 = st.number_input("Intervall Beförderungen P1 (Jahre)", 1, 15, key='sprung_intervall_p1')
        
        with st.expander("📊 Vorschau: Lohnentwicklung P1"):
            render_gehaltsvorschau(gehalt_p1, rente_jahr_p1, lohnerhoehung_pa_p1, anzahl_befoerderungen_p1, sprung_rate_p1, max(1, sprung_intervall_p1), "#1f77b4")

    with col_p2:
        st.write("**Person 2 (Partner/in)**")
        gehalt_p2 = st.number_input("Netto-Gehalt P2 (€)", step=100, key='gehalt_p2')
        rente_jahr_p2 = st.number_input("Renteneintritt P2 (in X Jahren)", 0, 60, key='rente_jahr_p2')
        
        st.markdown("*Karriere-Planung P2*")
        st.warning("⚠️ **Kalte Progression:** Trage bei den folgenden Werten nur ca. 50 % der erwarteten *Brutto*-Erhöhung ein.")
        lohnerhoehung_pa_p2 = st.slider("Allg. jährliche Lohnerhöhung P2 (%)", 0.0, 10.0, step=0.1, help=progression_help, key='lohnerhoehung_pa_p2')
        anzahl_befoerderungen_p2 = st.number_input("Anzahl geplanter Beförderungen P2", 0, 10, key='anzahl_befoerderungen_p2')
        sprung_rate_p2 = st.slider("Gehaltssprung pro Beförderung P2 (%)", 0, 30, help=progression_help, key='sprung_rate_p2')
        sprung_intervall_p2 = st.number_input("Intervall Beförderungen P2 (Jahre)", 1, 15, key='sprung_intervall_p2')
        
        st.markdown("*Pausen-Planung P2*")
        pause_start = st.number_input("Beginn der Pause (Jahr)", 0, 40, key='pause_start')
        pause_ende = st.number_input("Ende der Pause (Jahr)", 0, 40, key='pause_ende')
        ersatz_rate = st.slider("Lohnersatz während Pause (%)", 0, 100, key='ersatz_rate')

        with st.expander("📊 Vorschau: Lohnentwicklung P2"):
            render_gehaltsvorschau(gehalt_p2, rente_jahr_p2, lohnerhoehung_pa_p2, anzahl_befoerderungen_p2, sprung_rate_p2, max(1, sprung_intervall_p2), "#ff4b4b", pause=(pause_start, pause_ende))

# --- TAB 2: EVENTS, AUTOS & URLAUB ---
with tab2:
    st.header("Lebensstil & Ereignisse")
    col_e1, col_e2 = st.columns(2)
    
    with col_e1:
        st.subheader("Fahrzeuge")
        auto = st.number_input("Budget Autokauf (heutiger Wert, €)", 0, 300000, step=1000, key='auto_budget')
        a_jahr = st.number_input("Jahr (erster) Autokauf", 0, 60, key='a_jahr')
        auto_regelmaessig = st.checkbox("Regelmäßig neues Fahrzeug anschaffen?", key='auto_regelmaessig')
        auto_intervall = 0
        if auto_regelmaessig:
            auto_intervall = st.number_input("Alle wie viele Jahre ein neues Auto?", 1, 20, key='auto_intervall')
            
        st.markdown("---")
        st.subheader("Urlaub & Reisen")
        urlaub_budget = st.number_input("Jährliches Urlaubsbudget (€)", 0, 100000, step=100, key='urlaub_budget')

    with col_e2:
        st.subheader("Große Einzel-Events")
        hochzeit = st.number_input("Hochzeit (€)", 0, 100000, step=1000, key='hochzeit')
        h_jahr = st.number_input("Jahr Hochzeit", 0, 40, key='h_jahr')
        
        st.markdown("---")
        st.subheader("Einmalzahlungen")
        erbe_betrag = st.number_input("Betrag Erbe/Bonus (€)", 0, 10000000, step=1000, key='erbe_betrag')
        erbe_jahr = st.number_input("Jahr des Zuflusses", 0, 80, key='erbe_jahr')
        
        st.markdown("---")
        st.subheader("Kinderplanung")
        anzahl_kinder = st.number_input("Anzahl geplanter/vorhandener Kinder", 0, 10, key='anzahl_kinder')
        
        kinder_liste = []
        if anzahl_kinder > 0:
            for i in range(int(anzahl_kinder)):
                st.markdown(f"**Kind {i+1}**")
                
                def_jahr = 0
                def_kosten = 0
                if i < len(st.session_state['kinder_daten']):
                    def_jahr = st.session_state['kinder_daten'][i].get('jahr', 0)
                    def_kosten = st.session_state['kinder_daten'][i].get('basis_kosten', 0)
                
                c_k1, c_k2 = st.columns(2)
                with c_k1:
                    k_jahr = st.number_input(f"Startjahr Kind {i+1} (0 = sofort)", 0, 40, value=def_jahr, key=f"dyn_k_jahr_{i}")
                with c_k2:
                    k_kosten = st.number_input(f"Kosten/Monat (€)", 0, 5000, value=def_kosten, step=50, key=f"dyn_k_kosten_{i}")
                kinder_liste.append({"jahr": k_jahr, "basis_kosten": k_kosten})
                
            st.session_state['kinder_daten'] = kinder_liste
                
        kindergeld_aktiv = st.checkbox("Kindergeld anrechnen?", key='kindergeld_aktiv')
        st.info("ℹ️ Startwert Kindergeld: 255 € pro Kind/Monat.")

# --- TAB 3: IMMOBILIEN ---
with tab3:
    st.header("Immobilien-Planung")
    wohneigentum_geplant = st.checkbox("Wohneigentum geplant?", key='wohneigentum_geplant')
    
    kauf_jahr = 0
    eigenkapital = 0
    kredit_summe = 0
    zins_pa = 0.0
    tilgung_pa = 0.0
    sondertilgung = 0
    sondertilgung_jahr = 0
    wohnflaeche = 0
    nebenkosten_qm = 0.0
    instandhaltung_qm = 0.0
    
    if wohneigentum_geplant:
        col_i1, col_i2 = st.columns(2)
        with col_i1:
            kauf_jahr = st.number_input("Kaufdatum (in X Jahren)", 0, 40, key='kauf_jahr')
            eigenkapital = st.number_input("Eingebrachtes Eigenkapital (€)", 0, 5000000, step=5000, key='eigenkapital')
            wohnflaeche = st.number_input("Wohnfläche in Quadratmetern (m²)", 0, 500, step=5, key='wohnflaeche')
            
            st.markdown("---")
            st.subheader("Laufende Hauskosten")
            nebenkosten_qm = st.number_input("Nebenkosten (Müll, Grundsteuer etc.) pro m²/Monat (€)", 0.0, 10.0, step=0.1, key='nebenkosten_qm')
            instandhaltung_qm = st.number_input("Instandhaltungsrücklage pro m²/Monat (€)", 0.0, 10.0, step=0.1, key='instandhaltung_qm')
            
        with col_i2:
            kredit_summe = st.number_input("Kredit (€)", 0, 5000000, step=5000, key='kredit_summe')
            zins_pa = st.slider("Jährlicher Zinssatz Hauskredit (%)", 0.0, 10.0, step=0.1, key='zins_pa')
            tilgung_pa = st.slider("Anfängliche Tilgung (%)", 1.0, 10.0, step=0.1, key='tilgung_pa')
            
            st.markdown("---")
            st.subheader("Sondertilgung")
            sondertilgung = st.number_input("Sondertilgung (einmalig, €)", 0, 500000, step=5000, key='sondertilgung')
            sondertilgung_jahr = st.number_input("Jahr der Sondertilgung", 0, 40, key='sondertilgung_jahr')

# --- TAB 4: LOGIK & STRATEGIE ---
with tab4:
    st.header("Langfristige Simulation")
    
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        st.subheader("Renditen & Planung")
        rendite_depot = st.slider("Rendite Depot (% p.a.)", 0.0, 15.0, key='rendite_depot')
        rendite_konto = st.slider("Rendite Tagesgeld/Konto (% p.a.)", 0.0, 10.0, key='rendite_konto')
        jahre_plan = st.slider("Planungshorizont (Jahre)", 5, 50, key='jahre_plan')
    
    with col_b2:
        st.subheader("Spar-Aufteilung & Cashflow")
        quote_depot = st.slider("Monatliche Sparrate: % ins Depot (Rest aufs Tagesgeld)", 0, 100, key='quote_depot')
        
        max_tagesgeld = st.number_input(
            "🔹 Obergrenze Tagesgeldkonto (Basis) – ab Jahr 0 (€)", 
            0, 1000000, step=5000, 
            help="Automatischer Sweep: Alles, was diesen Betrag übersteigt, wird am Monatsende zinsbringend ins Aktiendepot umgeschichtet.",
            key='max_tagesgeld'
        )
        
        max_tagesgeld_nach_hauskauf = max_tagesgeld
        if wohneigentum_geplant:
            max_tagesgeld_nach_hauskauf = st.number_input(
                f"🏠 Obergrenze ab Hauskauf – ab Jahr {kauf_jahr} (€)", 
                0, 1000000, step=5000,
                help="Neue Obergrenze nach Immobilienkauf.",
                key='max_tagesgeld_nach_hauskauf'
            )
        
        max_tagesgeld_nach_kind = max_tagesgeld
        if anzahl_kinder > 0 and len(kinder_liste) > 0:
            erstes_kind_jahr = min(k["jahr"] for k in kinder_liste)
            max_tagesgeld_nach_kind = st.number_input(
                f"👶 Obergrenze ab 1. Kindsgeburt – ab Jahr {erstes_kind_jahr} (€)", 
                0, 1000000, step=5000,
                help="Neue Obergrenze ab Geburt des ersten Kindes.",
                key='max_tagesgeld_nach_kind'
            )
        
        quote_konto = 100 - quote_depot

    def berechne_zwei_konten_logic():
        wert_konto = start_konto
        erster_engpass_jahr = None
        hauswert = start_immo
        
        depot_pakete = []
        if start_depot > 0:
            depot_pakete.append({
                'kauf_monat': -12,
                'menge': start_depot,
                'kaufpreis': 1.0
            })
        
        wert_depot = start_depot
        
        akt_p1 = gehalt_p1
        akt_p2 = gehalt_p2
        akt_fix = ausgaben_fix
        akt_wohnen_miete = ausgaben_wohnen
        akt_urlaub = urlaub_budget
        akt_auto_preis = auto
        
        sim_kinder = [{"jahr": k["jahr"], "kosten_aktuell": k["basis_kosten"]} for k in kinder_liste]
        akt_kindergeld = 255  
        
        befoerderungen_gemacht_p1 = 0
        befoerderungen_gemacht_p2 = 0
        ek_erreicht_jahr = None
        
        summe_einkommen_p1 = 0
        monate_gearbeitet_p1 = 0
        rente_monat_p1 = 0
        
        summe_einkommen_p2 = 0
        monate_gearbeitet_p2 = 0
        rente_monat_p2 = 0
        
        if wohneigentum_geplant:
            restschuld = start_schuld 
            rate_kredit = kredit_summe * ((zins_pa + tilgung_pa) / 100) / 12
            akt_haus_betriebskosten = wohnflaeche * (nebenkosten_qm + instandhaltung_qm)
        else:
            restschuld = start_schuld
            rate_kredit = 0
            akt_haus_betriebskosten = 0
            
        daten = hist_daten.copy()
        
        # Geometrische Formeln
        zins_mon_depot = (1 + rendite_depot / 100)**(1/12) - 1
        zins_mon_konto = (1 + rendite_konto / 100)**(1/12) - 1
        infl_mon = (1 + inflation_pa / 100)**(1/12) - 1
        
        engpass_gruende = set()
        jahre_mit_depot_verkauf = set()
        
        schutzpolster_ab_monat = kauf_jahr * 12 if wohneigentum_geplant else 0
        
        def depot_normwert():
            return sum(p['menge'] for p in depot_pakete)
        
        def preis_pro_einheit(depot_bruttowert):
            norm = depot_normwert()
            return depot_bruttowert / norm if norm > 0 else 1.0
        
        def verkauf_fifo(netto_bedarf, aktueller_depot_wert, gruende_set, grund, j_m):
            nonlocal erster_engpass_jahr, depot_pakete, jahre_mit_depot_verkauf
            
            if erster_engpass_jahr is None:
                erster_engpass_jahr = j_m
            gruende_set.add(grund)
            jahre_mit_depot_verkauf.add(j_m)
            
            preis_je_einheit = preis_pro_einheit(aktueller_depot_wert)
            zu_verkaufen_netto = netto_bedarf
            gesamt_verkaufswert = 0
            steuern = 0
            
            verbleibende_pakete = []
            for paket in sorted(depot_pakete, key=lambda x: x['kauf_monat']):
                if zu_verkaufen_netto <= 0:
                    verbleibende_pakete.append(paket)
                    continue
                
                paket_marktwert = paket['menge'] * preis_je_einheit
                
                if paket_marktwert <= zu_verkaufen_netto:
                    gewinn_pro_einheit = preis_je_einheit - paket['kaufpreis']
                    gesamtgewinn = gewinn_pro_einheit * paket['menge']
                    steuerlast = max(0, gesamtgewinn) * 0.26375
                    
                    gesamt_verkaufswert += paket_marktwert
                    steuern += steuerlast
                    zu_verkaufen_netto -= paket_marktwert
                else:
                    einheiten_zu_verkaufen = zu_verkaufen_netto / preis_je_einheit
                    gewinn_pro_einheit = preis_je_einheit - paket['kaufpreis']
                    gesamtgewinn = gewinn_pro_einheit * einheiten_zu_verkaufen
                    steuerlast = max(0, gesamtgewinn) * 0.26375
                    
                    gesamt_verkaufswert += zu_verkaufen_netto
                    steuern += steuerlast
                    
                    paket['menge'] -= einheiten_zu_verkaufen
                    verbleibende_pakete.append(paket)
                    zu_verkaufen_netto = 0
            
            depot_pakete = verbleibende_pakete
            brutto_verkauf = gesamt_verkaufswert + steuern
            return brutto_verkauf, steuern
        
        def abziehen(betrag, aktueller_konto_wert, depot_wert, gruende_set, grund, j_m):
            if aktueller_konto_wert >= betrag:
                return aktueller_konto_wert - betrag, depot_wert, gruende_set
            else:
                fehlbetrag = betrag - aktueller_konto_wert
                puffer = max_tagesgeld
                netto_bedarf = fehlbetrag + puffer
                
                brutto_verkauf, steuern = verkauf_fifo(netto_bedarf, depot_wert, gruende_set, grund, j_m)
                
                return puffer, depot_wert - brutto_verkauf, gruende_set

        for m in range((jahre_plan * 12) + 1):
            jahr_aktuell = m // 12
            
            aktueller_max_tagesgeld = max_tagesgeld
            if wohneigentum_geplant and m >= kauf_jahr * 12:
                aktueller_max_tagesgeld = max_tagesgeld_nach_hauskauf
            if anzahl_kinder > 0 and len(kinder_liste) > 0 and m >= min(k["jahr"] for k in kinder_liste) * 12:
                aktueller_max_tagesgeld = max_tagesgeld_nach_kind
            
            if wohneigentum_geplant and ek_erreicht_jahr is None and wert_konto >= eigenkapital and m <= kauf_jahr * 12:
                ek_erreicht_jahr = jahr_aktuell
            
            if m > 0 and m % 12 == 0:
                akt_urlaub *= (1 + (inflation_pa / 100))
                akt_auto_preis *= (1 + (inflation_pa / 100))
                akt_kindergeld *= (1 + (inflation_pa / 100))
                
                for k in sim_kinder:
                    k["kosten_aktuell"] *= (1 + (inflation_pa / 100))
                
                if jahr_aktuell < rente_jahr_p1:
                    akt_p1 *= (1 + (lohnerhoehung_pa_p1 / 100))
                    if jahr_aktuell % sprung_intervall_p1 == 0 and befoerderungen_gemacht_p1 < anzahl_befoerderungen_p1:
                        akt_p1 *= (1 + (sprung_rate_p1 / 100))
                        befoerderungen_gemacht_p1 += 1
                
                if jahr_aktuell < rente_jahr_p2:
                    akt_p2 *= (1 + (lohnerhoehung_pa_p2 / 100))
                    if jahr_aktuell % sprung_intervall_p2 == 0 and befoerderungen_gemacht_p2 < anzahl_befoerderungen_p2:
                        akt_p2 *= (1 + (sprung_rate_p2 / 100))
                        befoerderungen_gemacht_p2 += 1
            
            if jahr_aktuell >= rente_jahr_p1:
                if rente_monat_p1 == 0: 
                    avg = (summe_einkommen_p1 / max(1, monate_gearbeitet_p1)) if monate_gearbeitet_p1 > 0 else akt_p1
                    rente_monat_p1 = avg * 0.375
                einkommen_p1_monat = rente_monat_p1
            else:
                einkommen_p1_monat = akt_p1
                summe_einkommen_p1 += akt_p1
                monate_gearbeitet_p1 += 1
            
            if jahr_aktuell >= rente_jahr_p2:
                if rente_monat_p2 == 0:
                    avg = (summe_einkommen_p2 / max(1, monate_gearbeitet_p2)) if monate_gearbeitet_p2 > 0 else akt_p2
                    rente_monat_p2 = avg * 0.375
                einkommen_p2_monat = rente_monat_p2
            else:
                if pause_start <= jahr_aktuell < pause_ende:
                    eink_temp = akt_p2 * (ersatz_rate / 100)
                else:
                    eink_temp = akt_p2
                einkommen_p2_monat = eink_temp
                summe_einkommen_p2 += eink_temp
                monate_gearbeitet_p2 += 1
            
            if m > 0: 
                akt_fix *= (1 + infl_mon)
                akt_wohnen_miete *= (1 + infl_mon)
                if wohneigentum_geplant and m >= kauf_jahr * 12:
                    akt_haus_betriebskosten *= (1 + infl_mon)
                    hauswert *= (1 + infl_mon) 
            
            if wohneigentum_geplant and m >= kauf_jahr * 12:
                if m == kauf_jahr * 12:
                    wert_konto, wert_depot, engpass_gruende = abziehen(eigenkapital, wert_konto, wert_depot, engpass_gruende, "Hauskauf (Eigenkapital)", jahr_aktuell)
                    restschuld = kredit_summe
                    hauswert = eigenkapital + kredit_summe 
                    
                if m == sondertilgung_jahr * 12 and sondertilgung > 0:
                    wert_konto, wert_depot, engpass_gruende = abziehen(sondertilgung, wert_konto, wert_depot, engpass_gruende, "Sondertilgung Immobilie",jahr_aktuell)
                    restschuld = max(0, restschuld - sondertilgung)
                
                if restschuld > 0:
                    zins_anteil = restschuld * (zins_pa / 100) / 12
                    tilgungs_anteil = rate_kredit - zins_anteil
                    if tilgungs_anteil > restschuld: tilgungs_anteil = restschuld
                    restschuld -= tilgungs_anteil
                    akt_wohnen = zins_anteil + tilgungs_anteil + akt_haus_betriebskosten
                else:
                    akt_wohnen = akt_haus_betriebskosten
            else:
                akt_wohnen = akt_wohnen_miete
            
            if m > 0:
                wert_depot *= (1 + zins_mon_depot)
                wert_konto *= (1 + zins_mon_konto)
                
                sparrate = (einkommen_p1_monat + einkommen_p2_monat) - (akt_fix + akt_wohnen + (akt_urlaub / 12))
                
                if sparrate > 0:
                    sparrate_depot = sparrate * (quote_depot / 100)
                    wert_depot += sparrate_depot
                    wert_konto += sparrate * (quote_konto / 100)
                    
                    if sparrate_depot > 0:
                        aktueller_preis = preis_pro_einheit(wert_depot - sparrate_depot) 
                        depot_pakete.append({
                            'kauf_monat': m,
                            'menge': sparrate_depot,
                            'kaufpreis': aktueller_preis
                        })
                else:
                    wert_konto, wert_depot, engpass_gruende = abziehen(abs(sparrate), wert_konto, wert_depot, engpass_gruende, "Laufende monatliche Kosten (Negativer Cashflow)", jahr_aktuell)
            
            if m >= schutzpolster_ab_monat:
                if wert_konto < 50000 and wert_depot > 0:
                    fehlbetrag = 50000 - wert_konto
                    brutto_verkauf, steuern = verkauf_fifo(fehlbetrag, wert_depot, engpass_gruende, "Depot-Liquidierung (Schutzpolster)", jahr_aktuell)
                    wert_depot -= brutto_verkauf
                    wert_konto = 50000
            
            if m == h_jahr * 12: wert_konto, wert_depot, engpass_gruende = abziehen(hochzeit, wert_konto, wert_depot, engpass_gruende, "Hochzeit", jahr_aktuell)
            if m == erbe_jahr * 12: wert_konto += erbe_betrag 
            
            for i, kind in enumerate(sim_kinder):
                k_jahr_start = kind["jahr"]
                if m >= k_jahr_start * 12 and m < (k_jahr_start + 25) * 12:
                    wert_konto, wert_depot, engpass_gruende = abziehen(kind["kosten_aktuell"], wert_konto, wert_depot, engpass_gruende, f"Kosten für Kind {i+1}", jahr_aktuell)
                    if kindergeld_aktiv: wert_konto += akt_kindergeld
            
            if a_jahr >= 0 and a_jahr > 0:
                if m == a_jahr * 12:
                    wert_konto, wert_depot, engpass_gruende = abziehen(akt_auto_preis, wert_konto, wert_depot, engpass_gruende, "Autokauf", jahr_aktuell)
                elif auto_regelmaessig and m > a_jahr * 12 and (m - a_jahr * 12) % (auto_intervall * 12) == 0:
                    wert_konto, wert_depot, engpass_gruende = abziehen(akt_auto_preis, wert_konto, wert_depot, engpass_gruende, "Autokauf (Folgefahrzeug)", jahr_aktuell)
            
            if wert_konto > aktueller_max_tagesgeld:
                ueberschuss = wert_konto - aktueller_max_tagesgeld
                wert_depot += ueberschuss
                wert_konto = aktueller_max_tagesgeld
                
                if ueberschuss > 0:
                    aktueller_preis = preis_pro_einheit(wert_depot - ueberschuss)
                    depot_pakete.append({
                        'kauf_monat': m,
                        'menge': ueberschuss,
                        'kaufpreis': aktueller_preis
                    })
            
            if m % 12 == 0:
                daten.append({
                    "Kalenderjahr": start_kalenderjahr + jahr_aktuell,
                    "Jahr": jahr_aktuell, 
                    "Depot": wert_depot, 
                    "Tagesgeld": wert_konto, 
                    "Immobilienwert": hauswert,
                    "Restschuld": restschuld
                })
                
        return daten, engpass_gruende, ek_erreicht_jahr, erster_engpass_jahr, jahre_mit_depot_verkauf

    d_plan, engpass_ausloeser, ek_jahr, bottleneck_jahr, jahre_mit_depot_verkauf = berechne_zwei_konten_logic()
    
    aktuelle_obergrenze_am_ende = max_tagesgeld
    if wohneigentum_geplant:
        aktuelle_obergrenze_am_ende = max_tagesgeld_nach_hauskauf
    if anzahl_kinder > 0 and len(kinder_liste) > 0:
        aktuelle_obergrenze_am_ende = max_tagesgeld_nach_kind
        
    df_plot = pd.DataFrame(d_plan)

    df_assets = df_plot.melt(id_vars=['Kalenderjahr', 'Jahr', 'Restschuld'], value_vars=['Tagesgeld', 'Depot', 'Immobilienwert'], var_name='Anlageklasse', value_name='Wert')
    y_fmt = alt.Axis(format=",d", labelExpr="datum.value >= 1000000 ? (datum.value / 1000000) + ' Mio.' : format(datum.value, ',d')")
    
    chart_assets = alt.Chart(df_assets).mark_area(opacity=0.85).encode(
        x=alt.X('Kalenderjahr:Q', title="Kalenderjahr", axis=alt.Axis(format="d")),
        y=alt.Y('Wert:Q', title="Brutto-Vermögen (€)", axis=y_fmt),
        color=alt.Color('Anlageklasse:N', scale=alt.Scale(domain=['Tagesgeld', 'Depot', 'Immobilienwert'], range=['#2ca02c', '#1f77b4', '#ff7f0e'])),
        tooltip=['Kalenderjahr', 'Anlageklasse', alt.Tooltip('Wert', format=",d")]
    ).properties(height=500)

    bars_schuld = alt.Chart(df_plot).mark_bar(color='#ff4b4b', opacity=0.7, size=10).encode(
        x='Kalenderjahr:Q',
        y=alt.Y('Restschuld:Q', title="Restschuld (€)", axis=alt.Axis(format=",d")),
        tooltip=['Kalenderjahr', alt.Tooltip('Restschuld', format=",d")]
    )

    layers = [chart_assets, bars_schuld]

    marker_events = []
    
    max_vermoegen = (df_plot['Tagesgeld'].max() + df_plot['Depot'].max() + df_plot['Immobilienwert'].max())
    rauten_y_pos = max_vermoegen * 0.95
    offset_step = max_vermoegen * 0.05  
    
    if wohneigentum_geplant and ek_jahr is not None:
        marker_events.append({
            "Kalenderjahr": start_kalenderjahr + ek_jahr,
            "Event": "💰 Eigenkapital erreicht",
            "Typ": "positiv"
        })
    
    if rente_jahr_p1 < jahre_plan:
        marker_events.append({
            "Kalenderjahr": start_kalenderjahr + rente_jahr_p1,
            "Event": "🎓 Renteneintritt P1",
            "Typ": "neutral"
        })
    
    if rente_jahr_p2 < jahre_plan:
        marker_events.append({
            "Kalenderjahr": start_kalenderjahr + rente_jahr_p2,
            "Event": "🎓 Renteneintritt P2",
            "Typ": "neutral"
        })
    
    if wohneigentum_geplant:
        abbezahlt_row = df_plot[(df_plot['Restschuld'] == 0) & (df_plot['Jahr'] >= kauf_jahr)]
        if len(abbezahlt_row) > 0:
            abbezahlt_jahr = abbezahlt_row['Jahr'].min()
            marker_events.append({
                "Kalenderjahr": start_kalenderjahr + abbezahlt_jahr,
                "Event": "🏠 Immobilie abbezahlt",
                "Typ": "positiv"
            })
    
    if bottleneck_jahr is not None:
        marker_events.append({
            "Kalenderjahr": start_kalenderjahr + bottleneck_jahr,
            "Event": "📉 Depotverkauf erforderlich",
            "Typ": "negativ"
        })
    
    for jahr_mit_verkauf in jahre_mit_depot_verkauf:
        if bottleneck_jahr is None or jahr_mit_verkauf > bottleneck_jahr:  
            marker_events.append({
                "Kalenderjahr": start_kalenderjahr + jahr_mit_verkauf,
                "Event": "📉 Depot-Liquidierung",
                "Typ": "negativ"
            })
    
    for i, kind in enumerate(kinder_liste):
        k_jahr_start = kind["jahr"]
        if k_jahr_start < jahre_plan:
            marker_events.append({
                "Kalenderjahr": start_kalenderjahr + k_jahr_start,
                "Event": f"👶 Geburt Kind {i+1}",
                "Typ": "positiv"
            })
            k_selbststaendig = k_jahr_start + 25
            if k_selbststaendig <= jahre_plan:
                marker_events.append({
                    "Kalenderjahr": start_kalenderjahr + k_selbststaendig,
                    "Event": f"👨‍🎓 Kind {i+1} selbstständig",
                    "Typ": "positiv"
                })
    
    if a_jahr > 0 and a_jahr < jahre_plan:
        marker_events.append({
            "Kalenderjahr": start_kalenderjahr + a_jahr,
            "Event": "🚗 Autokauf",
            "Typ": "negativ"
        })
        
        if auto_regelmaessig and auto_intervall > 0:
            next_auto = a_jahr + auto_intervall
            while next_auto <= jahre_plan:
                marker_events.append({
                    "Kalenderjahr": start_kalenderjahr + next_auto,
                    "Event": "🚗 Autokauf (Folgefahrzeug)",
                    "Typ": "negativ"
                })
                next_auto += auto_intervall
    
    if marker_events:
        df_marker_all = pd.DataFrame(marker_events)
        
        ereignisse_pro_jahr = df_marker_all.groupby('Kalenderjahr').size()
        df_marker_all['Offset_Index'] = 0
        
        for jahr in ereignisse_pro_jahr.index:
            events_im_jahr = df_marker_all[df_marker_all['Kalenderjahr'] == jahr].index
            for idx, event_idx in enumerate(sorted(events_im_jahr)):
                df_marker_all.loc[event_idx, 'Offset_Index'] = idx
        
        df_marker_all['Wert'] = rauten_y_pos - (df_marker_all['Offset_Index'] * offset_step)
        
        for typ, color, stroke in [("positiv", "#FFD700", "#DAA520"), ("neutral", "#87CEEB", "#4682B4"), ("negativ", "#FF6B6B", "#DC143C")]:
            df_typ = df_marker_all[df_marker_all['Typ'] == typ]
            if len(df_typ) > 0:
                marker_points = alt.Chart(df_typ).mark_point(
                    shape='diamond', size=200, color=color, filled=True, opacity=0.9, stroke=stroke, strokeWidth=2
                ).encode(
                    x='Kalenderjahr:Q',
                    y=alt.Y('Wert:Q', axis=None),
                    tooltip=[alt.Tooltip('Event:N', title='')]
                )
                layers.append(marker_points)

    combined_chart = alt.layer(*layers).resolve_scale(y='independent')
    st.altair_chart(combined_chart, use_container_width=True)

    if bottleneck_jahr is not None:
        st.error(f"⚠️ **Strategisches Rebalancing im Jahr {start_kalenderjahr + bottleneck_jahr} erforderlich!**")
        
        st.markdown(f"""
        Dein Cash-Bestand ist in diesem Jahr auf 0 € gefallen. Das System hat automatisch Aktien nach dem FIFO-Prinzip verkauft (mit Berechnung der Kapitalertragssteuer: 26,375% auf Gewinne),
        um dein Tagesgeldkonto sofort wieder auf den Ziel-Puffer von **{format_euro_smart(aktuelle_obergrenze_am_ende)}** aufzufüllen.
        """)

        with st.expander("Analyse der Ursachen & Lösungswege"):
            st.write(f"**Identifizierte Auslöser:** {', '.join(engpass_ausloeser)}")
            st.markdown("---")
            st.markdown("""
            **Strategische Optionen, um den Depotverkauf zu verhindern:**
            1. **Vorausschauendes Sparen:** Erhöhe die Cash-Quote (Regler 'Sparrate ins Depot' senken) ca. 2-3 Jahre vor dem Engpass.
            2. **Event-Verschiebung:** Prüfe im Graphen, welche Events (Auto, Hochzeit etc.) im Jahr des Engpasses liegen und schiebe sie um 12 Monate.
            3. **Puffer-Check:** Ist dein 'Rebalancing-Ziel' hoch genug, um nachfolgende monatliche Kosten während einer Niedriglohnphase (z.B. Pause P2) zu decken?
            """)
        
    if d_plan[-1]['Depot'] < 0:
        st.error("🚨 Totalausfall: Auch das Depotvolumen hat nicht gereicht. Dein liquides Gesamtvermögen ist ins Minus gerutscht.")

    st.subheader(f"Zusammenfassung Bilanz (Jahr {start_kalenderjahr + jahre_plan})")
    c1, c2, c3 = st.columns(3)
    
    brutto_vermoegen = d_plan[-1]['Depot'] + d_plan[-1]['Tagesgeld'] + d_plan[-1]['Immobilienwert']
    netto_vermoegen = brutto_vermoegen - d_plan[-1]['Restschuld']
    kaufkraft_heute = netto_vermoegen / ((1 + (inflation_pa / 100)) ** jahre_plan)
    
    c1.metric(
        "Netto-Gesamtvermögen", 
        f"{format_euro_smart(netto_vermoegen)} €", 
        f"Kaufkraft heute: {format_euro_smart(kaufkraft_heute)} €",
        delta_color="off" 
    )
    
    c2.metric("Davon liquide (Depot + Tagesgeld)", f"{format_euro_smart(d_plan[-1]['Depot'] + d_plan[-1]['Tagesgeld'])} €")
    
    if wohneigentum_geplant:
        c3.metric("Immobilienwert / Restschuld", f"{format_euro_smart(d_plan[-1]['Immobilienwert'])} € / {format_euro_smart(d_plan[-1]['Restschuld'])} €")
    else:
        c3.metric("Davon auf Tagesgeld", f"{format_euro_smart(d_plan[-1]['Tagesgeld'])} €")
    
    st.markdown("---")