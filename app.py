import streamlit as st
import pandas as pd
from collections import Counter
import urllib.parse
import json
import os

st.set_page_config(page_title="ניהול הסעות בית אריה - בן שמן", layout="wide")

HISTORY_FILE = "history.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {fam: 0 for fam in FAMILIES_DB.keys()}

def save_history(history_data):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history_data, f, ensure_ascii=False, indent=4)

FAMILIES_DB = {
    "משפחה א'": {"parent_name": "ישראל ישראלי", "phone": "050-1234567", "child_name": "אורי", "address": "האורנים 12, בית אריה"},
    "משפחה ב'": {"parent_name": "דנה לוי", "phone": "052-2345678", "child_name": "נועה", "address": "הזית 5, בית אריה"},
    "משפחה ג'": {"parent_name": "עוז כהן", "phone": "054-3456789", "child_name": "איתי", "address": "השקד 18, בית אריה"},
    "משפחה ד'": {"parent_name": "תמר אברהם", "phone": "053-4567890", "child_name": "מאיה", "address": "הרימון 3, בית אריה"}
}

SCHOOL_ADDRESS = "בית ספר בן שמן"
DAYS = ["ראשון", "שני", "שלישי", "רביעי", "חמישי"]

def create_gmaps_link(origin, waypoints, destination):
    base_url = "https://www.google.com/maps/dir/?api=1"
    params = {"origin": origin, "destination": destination, "travelmode": "driving"}
    if waypoints:
        params["waypoints"] = "|".join(waypoints)
    return base_url + "&" + urllib.parse.urlencode(params)

st.title("🚗 ניהול הסעות - בית אריה לבן שמן")

tab1, tab2, tab3 = st.tabs(["🗓️ השבוע שלי", "🔄 החלפות", "📊 סטטיסטיקה"])

with tab1:
    st.sidebar.header("⚙️ הגדרות שבועיות")
    selected_week = st.sidebar.text_input("שבוע בתאריך:", "10/09/2026")
    
    schedule_data = {}
    for day in DAYS:
        with st.expander(f"📅 הגדרות ליום {day}", expanded=(day == "ראשון")):
            is_holiday = st.checkbox(f"🎉 יום חופש / חג (אין לימודים ביום {day})", key=f"{day}_holiday")
            
            if not is_holiday:
                c1, c2 = st.columns(2)
                with c1:
                    end_times, waits = {}, {}
                    for f_key, f_info in FAMILIES_DB.items():
                        col_a, col_b = st.columns([2, 1])
                        with col_a:
                            end_times[f_key] = st.time_input(f"סיום {f_info['child_name']}", value=pd.to_datetime("15:00").time(), key=f"{day}_{f_key}_end")
                        with col_b:
                            waits[f_key] = st.checkbox("ממתין/ה", value=True, key=f"{day}_{f_key}_wait")
                with c2:
                    avail_morn = st.multiselect("פנויים לבוקר", list(FAMILIES_DB.keys()), default=list(FAMILIES_DB.keys()), key=f"{day}_morn")
                    avail_aft = st.multiselect("פנויים לאחה\"צ", list(FAMILIES_DB.keys()), default=list(FAMILIES_DB.keys()), key=f"{day}_aft")
                
                absent = st.multiselect("🚨 החרגות בוקר (ילדים שלא נוסעים):", [f"{info['child_name']} ({k})" for k, info in FAMILIES_DB.items()], key=f"{day}_absent")
                absent_fams = [k for k, info in FAMILIES_DB.items() if f"{info['child_name']} ({k})" in absent]
                
                schedule_data[day] = {"is_holiday": False, "end_times": end_times, "waits": waits, "avail_morn": avail_morn, "avail_aft": avail_aft, "absent_fams": absent_fams}
            else:
                schedule_data[day] = {"is_holiday": True}

    if st.button("🧮 מחשב שיבוץ שבועי"):
        history = load_history()
        temp_counts = history.copy()
        results = []

        for day in DAYS:
            data = schedule_data[day]
            
            if data["is_holiday"]:
                results.append({"יום": day, "is_holiday": True})
                continue

            m_candidates = sorted(data["avail_morn"], key=lambda x: temp_counts[x])
            m_driver = m_candidates[0] if m_candidates else None
            
            if m_driver:
                temp_counts[m_driver] += 1
                m_driver_str = f"{FAMILIES_DB[m_driver]['parent_name']} ({FAMILIES_DB[m_driver]['phone']})"
                pickups = [FAMILIES_DB[k]["address"] for k in FAMILIES_DB.keys() if k != m_driver and k not in data["absent_fams"]]
                gmaps_link = create_gmaps_link(FAMILIES_DB[m_driver]["address"], pickups, SCHOOL_ADDRESS)
            else:
                m_driver_str, gmaps_link = "אין נהג פנוי!", "#"

            times_list = [t.strftime("%H:%M") for t in data["end_times"].values()]
            common_time = Counter(times_list).most_common(1)[0][0]
            a_candidates = [k for k in data["avail_aft"] if data["end_times"][k].strftime("%H:%M") == common_time or (data["end_times"][k].strftime("%H:%M") < common_time and data["waits"][k])]
            a_candidates = sorted(a_candidates, key=lambda x: temp_counts[x])
            a_driver = a_candidates[0] if a_candidates else None
            
            if a_driver:
                temp_counts[a_driver] += 1
                a_driver_str = f"{FAMILIES_DB[a_driver]['parent_name']} ({FAMILIES_DB[a_driver]['phone']})"
            else:
                a_driver_str = "נדרש תיאום ידני"

            results.append({"יום": day, "is_holiday": False, "נהג בוקר": m_driver_str, "נוסעים": ", ".join([FAMILIES_DB[k]["child_name"] for k in FAMILIES_DB.keys() if k not in data["absent_fams"]]), "מסלול": gmaps_link, "איסוף אחה\"צ": common_time, "נהג אחה\"צ": a_driver_str})

        st.session_state["current_schedule"] = results
        st.session_state["temp_counts"] = temp_counts

    if "current_schedule" in st.session_state:
        st.subheader("📋 לוח ההסעות השבועי")
        for res in st.session_state["current_schedule"]:
            if res.get("is_holiday"):
                st.markdown(f"**יום {res['יום']}** | 🏖️ **יום חופש / חג - אין הסעות**")
            else:
                st.markdown(f"**יום {res['יום']}** | 🌅 בוקר: {res['נהג בוקר']} | 🌆 אחה\"צ ({res['איסוף אחה\"צ']}): {res['נהג אחה\"צ']}")
                if res['מסלול'] != "#":
                    st.markdown(f"[🗺️ ניווט מעודכן ב-Google Maps]({res['מסלול']})")
            st.markdown("---")
            
        if st.button("💾 אישור ועדכון היסטוריה"):
            save_history(st.session_state["temp_counts"])
            st.success("הנתונים נשמרו בהצלחה בהיסטוריה!")

with tab2:
    st.header("🔄 בקשת החלפה בנסיעה")
    swap_day = st.selectbox("בחר יום להחלפה:", DAYS)
    swap_type = st.radio("סוג הנסיעה:", ["בוקר", "אחה\"צ"])
    current_driver = st.selectbox("הנהג המשובץ כרגע:", list(FAMILIES_DB.keys()))
    
    if st.button("🔍 מצא מחליף מומלץ"):
        history = load_history()
        candidates = [k for k in FAMILIES_DB.keys() if k != current_driver]
        recommended = sorted(candidates, key=lambda x: history[x])[0]
        st.info(f"💡 המחליף המומלץ ביותר (לפי מדד עומס): **{FAMILIES_DB[recommended]['parent_name']} ({recommended})**")

with tab3:
    st.header("📊 סטטיסטיקת נסיעות מצטברת")
    history_data = load_history()
    df_hist = pd.DataFrame([{"משפחה": FAMILIES_DB[k]["parent_name"], "סך נסיעות": v} for k, v in history_data.items()])
    
    st.bar_chart(df_hist.set_index("משפחה"))
    st.table(df_hist)
