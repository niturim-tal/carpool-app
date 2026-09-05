import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from collections import Counter
import urllib.parse
from datetime import datetime, timedelta

st.set_page_config(page_title="ניהול הסעות בית אריה - בן שמן", layout="wide")

# התחברות ל-Google Sheets דרך ה-Secrets של Streamlit
@st.cache_resource
def get_gspread_client():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=scope
    )
    return gspread.authorize(creds)

try:
    gc = get_gspread_client()
    sh = gc.open("carpool_app") 
    worksheet = sh.sheet1
    
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
        st.success("הנתונים שאושרו בלבד נשמרו בהצלחה ב-Google Sheets!")
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

def calculate_optimal_pickup_time(end_times, waits_dict):
    times_list = [t.strftime("%H:%M") for t in end_times.values()]
    counts = Counter(times_list)
    most_common = counts.most_common()
    
    if most_common[0][1] >= 3:
        return most_common[0][0]
    if len(most_common) >= 2 and most_common[0][1] == 2 and most_common[1][1] == 2:
        return max(most_common[0][0], most_common[1][0])
    if most_common[0][1] == 2:
        return most_common[0][0]
    return max(times_list)

# חישוב תאריך יום ראשון הקרוב
today = datetime.now()
days_until_sunday = (6 - today.weekday()) % 7
if days_until_sunday == 0 and today.weekday() != 6:
    days_until_sunday = 7
next_sunday = today + timedelta(days=days_until_sunday)
default_week_str = next_sunday.strftime("%d/%m/%Y")

st.title("🚗 ניהול הסעות - בית אריה לבן שמן")

tab1, tab2, tab3 = st.tabs(["🗓️ השבוע שלי", "🔄 החלפות", "📊 סטטיסטיקה"])

with tab1:
    selected_week = st.text_input("📅 שבוע מתחיל בתאריך (יום ראשון):", value=default_week_str)
    
    schedule_data = {}
    for day in DAYS:
        with st.expander(f"📅 הזנת זמינות ליום {day}", expanded=(day == "ראשון")):
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
                    # ברירת המחדל עכשיו ריקה ([] במקום רשימת כל המשפחות)
                    avail_morn = st.multiselect("🙋‍♂️ מתנדבים לבוקר", list(FAMILIES_DB.keys()), default=[], key=f"{day}_morn")
                    avail_aft = st.multiselect("🙋‍♂️ מתנדבים לאחה\"צ", list(FAMILIES_DB.keys()), default=[], key=f"{day}_aft")
                
                absent = st.multiselect("🚨 החרגות בוקר (ילדים שלא נוסעים):", [f"{info['child_name']} ({k})" for k, info in FAMILIES_DB.items()], key=f"{day}_absent")
                absent_fams = [k for k, info in FAMILIES_DB.items() if f"{info['child_name']} ({k})" in absent]
                
                schedule_data[day] = {"is_holiday": False, "end_times": end_times, "waits": waits, "avail_morn": avail_morn, "avail_aft": avail_aft, "absent_fams": absent_fams}
            else:
                schedule_data[day] = {"is_holiday": True}

    if st.button("🧮 חישוב שיבוץ סופי מהמתנדבים"):
        history = load_history()
        results = []

        for day in DAYS:
            data = schedule_data[day]
            
            if data["is_holiday"]:
                results.append({"יום": day, "is_holiday": True})
                continue

            # בחירת נהג בוקר מתוך המתנדבים לפי מדד העומס
            m_candidates = sorted(data["avail_morn"], key=lambda x: history.get(x, 0))
            m_driver = m_candidates[0] if m_candidates else None
            
            if m_driver:
                m_driver_str = f"{FAMILIES_DB[m_driver]['parent_name']} ({FAMILIES_DB[m_driver]['phone']})"
                pickups = [FAMILIES_DB[k]["address"] for k in FAMILIES_DB.keys() if k != m_driver and k not in data["absent_fams"]]
                gmaps_link = create_gmaps_link(FAMILIES_DB[m_driver]["address"], pickups, SCHOOL_ADDRESS)
            else:
                m_driver_str, gmaps_link = "⚠️ חסר נהג מתנדב!", "#"

            # חישוב שעת איסוף אחה"צ
            optimal_time = calculate_optimal_pickup_time(data["end_times"], data["waits"])
            
            # בחירת נהג אחה"צ מתוך המתנדבים הפנויים בשעה הנדרשת
            a_candidates = [
                k for k in data["avail_aft"] 
                if data["end_times"][k].strftime("%H:%M") == optimal_time or 
                (data["end_times"][k].strftime("%H:%M") < optimal_time and data["waits"][k])
            ]
            a_candidates = sorted(a_candidates, key=lambda x: history.get(x, 0))
            a_driver = a_candidates[0] if a_candidates else None
            
            if a_driver:
                a_driver_str = f"{FAMILIES_DB[a_driver]['parent_name']} ({FAMILIES_DB[a_driver]['phone']})"
            else:
                a_driver_str = "⚠️ חסר נהג מתנדב!"

            results.append({
                "יום": day, 
                "is_holiday": False, 
                "m_driver_key": m_driver,
                "נהג בוקר": m_driver_str, 
                "a_driver_key": a_driver,
                "נהג אחה\"צ": a_driver_str,
                "נוסעים": ", ".join([FAMILIES_DB[k]["child_name"] for k in FAMILIES_DB.keys() if k not in data["absent_fams"]]), 
                "מסלול": gmaps_link, 
                "איסוף אחה\"צ": optimal_time, 
            })

        st.session_state["current_schedule"] = results

    if "current_schedule" in st.session_state:
        st.subheader("📋 לוח הסעות שבועי סופי ואישור נהגים")
        
        status_options = ["⏳ ממתין לאישור", "✅ מאושר", "❌ נדחה / נדרשת החלפה"]
        confirmations = {}

        for idx, res in enumerate(st.session_state["current_schedule"]):
            day = res["יום"]
            if res.get("is_holiday"):
                st.markdown(f"**יום {day}** | 🏖️ **יום חופש / חג - אין הסעות**")
            else:
                st.markdown(f"### יום {day}")
                c_morn, c_aft = st.columns(2)
                
                with c_morn:
                    st.write(f"🌅 **בוקר:** {res['נהג בוקר']}")
                    if res["m_driver_key"]:
                        status_m = st.selectbox(
                            f"אישור נהג בוקר ({day}):", 
                            status_options, 
                            key=f"status_m_{day}"
                        )
                        confirmations[(day, "morn")] = {
                            "driver_key": res["m_driver_key"], 
                            "status": status_m
                        }
                    if res['מסלול'] != "#":
                        st.markdown(f"[🗺️ ניווט ב-Google Maps]({res['מסלול']})")
                
                with c_aft:
                    st.write(f"🌆 **אחה\"צ ({res['איסוף אחה\"צ']}):** {res['נהג אחה\"צ']}")
                    if res["a_driver_key"]:
                        status_a = st.selectbox(
                            f"אישור נהג אחה\"צ ({day}):", 
                            status_options, 
                            key=f"status_a_{day}"
                        )
                        confirmations[(day, "aft")] = {
                            "driver_key": res["a_driver_key"], 
                            "status": status_a
                        }

            st.markdown("---")
            
        if st.button("💾 עדכון היסטוריה ב-Google Sheets (רק עבור נסיעות שאושרו)"):
            history = load_history()
            updated_counts = history.copy()
            approved_count = 0
            
            for (d, shift), info in confirmations.items():
                if info["status"] == "✅ מאושר" and info["driver_key"]:
                    driver = info["driver_key"]
                    updated_counts[driver] = updated_counts.get(driver, 0) + 1
                    approved_count += 1
            
            save_history(updated_counts)
            st.info(f"עודכנו {approved_count} נסיעות שאושרו בפועל!")

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
