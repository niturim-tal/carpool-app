import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from collections import Counter
import urllib.parse
import json

st.set_page_config(page_title="ניהול הסעות בית אריה - בן שמן", layout="wide")

# התחברות ל-Google Sheets דרך ה-Secrets של Streamlit
@st.cache_resource
def get_gspread_client():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    sec = st.secrets["gcp_service_account"]
    
    # טיפול במצב שבו Streamlit קורא את ה-JSON כטקסט מרובה שורות או كمילון
    if isinstance(sec, str):
        sec = json.loads(sec.strip())
    elif not isinstance(sec, dict):
        sec = dict(sec)
        
    creds = Credentials.from_service_account_info(
        sec,
        scopes=scope
    )
    return gspread.authorize(creds)

try:
    gc = get_gspread_client()
    # שם הגיליון כפי שמופיע אצלך ב-Google Drive
    sh = gc.open("carpool_app") 
    worksheet = sh.sheet1
    
    # טעינת נתוני המשפחות מהגיליון
    records = worksheet.get_all_records()
    FAMILIES_DB = {
        str(row["family_key"]): {
            "parent_name": row["parent_name"],
            "phone": str(row["phone"]),
            "child_name": row["child_name"],
            "address": row["address"]
        } for row in records
    }
except Exception as e:
    st.error(f"שגיאה בהתחברות ל-Google Sheets: {e}")
    st.stop()

# טעינת היסטוריה מתוך לשונית שניה בגיליון (אם קיימת)
def load_history():
    try:
        hist_sheet = sh.worksheet("history")
        hist_records = hist_sheet.get_all_records()
        return {str(row["family_key"]): int(row["count"]) for row in hist_records}
    except:
        return {fam: 0 for fam in FAMILIES_DB.keys()}

def save_history(history_data):
    try:
        try:
            hist_sheet = sh.worksheet("history")
        except:
            hist_sheet = sh.add_worksheet(title="history", rows="100", cols="2")
            hist_sheet.append_row(["family_key", "count"])
            
        hist_sheet.clear()
        hist_sheet.append_row(["family_key", "count"])
        for fam, count in history_data.items():
            hist_sheet.append_row([fam, count])
        st.success("הנתונים נשמרו בהצלחה ב-Google Sheets!")
    except Exception as e:
        st.error(f"שגיאה בשמירת ההיסטוריה: {e}")

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

            m_candidates = sorted(data["avail_morn"], key=lambda x: temp_counts.get(x, 0))
            m_driver = m_candidates[0] if m_candidates else None
            
            if m_driver:
                temp_counts[m_driver] = temp_counts.get(m_driver, 0) + 1
                m_driver_str = f"{FAMILIES_DB[m_driver]['parent_name']} ({FAMILIES_DB[m_driver]['phone']})"
                pickups = [FAMILIES_DB[k]["address"] for k in FAMILIES_DB.keys() if k != m_driver and k not in data["absent_fams"]]
                gmaps_link = create_gmaps_link(FAMILIES_DB[m_driver]["address"], pickups, SCHOOL_ADDRESS)
            else:
                m_driver_str, gmaps_link = "אין נהג פנוי!", "#"

            times_list = [t.strftime("%H:%M") for t in data["end_times"].values()]
            common_time = Counter(times_list).most_common(1)[0][0]
            a_candidates = [k for k in data["avail_aft"] if data["end_times"][k].strftime("%H:%M") == common_time or (data["end_times"][k].strftime("%H:%M") < common_time and data["waits"][k])]
            a_candidates = sorted(a_candidates, key=lambda x: temp_counts.get(x, 0))
            a_driver = a_candidates[0] if a_candidates else None
            
            if a_driver:
                temp_counts[a_driver] = temp_counts.get(a_driver, 0) + 1
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
            
        if st.button("💾 אישור ועדכון היסטוריה ב-Google Sheets"):
            save_history(st.session_state["temp_counts"])

with tab2:
    st.header("🔄 בקשת החלפה בנסיעה")
    swap_day = st.selectbox("בחר יום להחלפה:", DAYS)
    swap_type = st.radio("סוג הנסיעה:", ["בוקר", "אחה\"צ"])
    current_driver = st.selectbox("הנהג המשובץ כרגע:", list(FAMILIES_DB.keys()))
    
    if st.button("🔍 מצא מחליף מומלץ"):
        history = load_history()
        candidates = [k for k in FAMILIES_DB.keys() if k != current_driver]
        recommended = sorted(candidates, key=lambda x: history.get(x, 0))[0]
        st.info(f"💡 המחליף המומלץ ביותר (לפי מדד עומס): **{FAMILIES_DB[recommended]['parent_name']} ({recommended})**")

with tab3:
    st.header("📊 סטטיסטיקת נסיעות מצטברת")
    history_data = load_history()
    df_hist = pd.DataFrame([{"משפחה": FAMILIES_DB[k]["parent_name"], "סך נסיעות": v} for k, v in history_data.items()])
    
    st.bar_chart(df_hist.set_index("משפחה"))
    st.table(df_hist)
