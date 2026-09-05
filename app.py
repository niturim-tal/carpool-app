import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from collections import Counter
import urllib.parse
from datetime import datetime, timedelta

st.set_page_config(page_title="ניהול הסעות בית אריה - בן שמן", layout="wide")

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
    
    FAMILIES_DB = {}
    DRIVERS_LIST = []  # רשימת הנהגים הבודדים לבחירה

    for row in records:
        f_key = str(row["family_key"])
        parents_str = str(row["parent_name"])
        
        # תמיכה בפיצול מספר הורים המופרדים בלוכסן, פסיק או "ו"
        parents = [p.strip() for p in parents_str.replace('/', ',').replace(' ו-', ',').replace(' ו', ',').split(',')]
        
        FAMILIES_DB[f_key] = {
            "parents": parents,
            "phone": str(row["phone"]),
            "child_name": row["child_name"],
            "address": row["address"]
        }
        
        # יצירת רשימת נהגים ספציפיים
        for p in parents:
            DRIVERS_LIST.append({"driver_name": p, "family_key": f_key})

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
        st.success("הנתונים שאושרו בלבד נשמרו בהצלחה ב-Google Sheets ברמת המשפחה!")
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
                    # בחירת נהגים ספציפיים (כולל הפרדה בין הורי המשפחה)
                    avail_morn_idx = st.multiselect(
                        "🙋‍♂️ מתנדבים לבוקר", 
                        range(len(DRIVERS_LIST)), 
                        default=[], 
                        format_func=lambda i: f"{DRIVERS_LIST[i]['driver_name']} (משפחת {DRIVERS_LIST[i]['family_key']})",
                        key=f"{day}_morn"
                    )
                    avail_aft_idx = st.multiselect(
                        "🙋‍♂️ מתנדבים לאחה\"צ", 
                        range(len(DRIVERS_LIST)), 
                        default=[], 
                        format_func=lambda i: f"{DRIVERS_LIST[i]['driver_name']} (משפחת {DRIVERS_LIST[i]['family_key']})",
                        key=f"{day}_aft"
                    )
                
                absent = st.multiselect("🚨 החרגות בוקר (ילדים שלא נוסעים):", [f"{info['child_name']} ({k})" for k, info in FAMILIES_DB.items()], key=f"{day}_absent")
                absent_fams = [k for k, info in FAMILIES_DB.items() if f"{info['child_name']} ({k})" in absent]
                
                schedule_data[day] = {
                    "is_holiday": False, 
                    "end_times": end_times, 
                    "waits": waits, 
                    "avail_morn_drivers": [DRIVERS_LIST[i] for i in avail_morn_idx], 
                    "avail_aft_drivers": [DRIVERS_LIST[i] for i in avail_aft_idx], 
                    "absent_fams": absent_fams
                }
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

            # בחירת נהג בוקר לפי מדד העומס של המשפחה
            m_candidates = sorted(data["avail_morn_drivers"], key=lambda d: history.get(d["family_key"], 0))
            m_driver_obj = m_candidates[0] if m_candidates else None
            
            if m_driver_obj:
                m_fam = m_driver_obj["family_key"]
                m_driver_str = f"{m_driver_obj['driver_name']} ({FAMILIES_DB[m_fam]['phone']})"
                pickups = [FAMILIES_DB[k]["address"] for k in FAMILIES_DB.keys() if k != m_fam and k not in data["absent_fams"]]
                gmaps_link = create_gmaps_link(FAMILIES_DB[m_fam]["address"], pickups, SCHOOL_ADDRESS)
            else:
                m_fam = None
                m_driver_str, gmaps_link = "⚠️ חסר נהג מתנדב!", "#"

            # חישוב שעת איסוף אחה"צ
            optimal_time = calculate_optimal_pickup_time(data["end_times"], data["waits"])
            
            # סינון נהגים פנויים לאחה"צ
            a_candidates = [
                d for d in data["avail_aft_drivers"] 
                if data["end_times"][d["family_key"]].strftime("%H:%M") == optimal_time or 
                (data["end_times"][d["family_key"]].strftime("%H:%M") < optimal_time and data["waits"][d["family_key"]])
            ]
            a_candidates = sorted(a_candidates, key=lambda d: history.get(d["family_key"], 0))
            a_driver_obj = a_candidates[0] if a_candidates else None
            
            if a_driver_obj:
                a_fam = a_driver_obj["family_key"]
                a_driver_str = f"{a_driver_obj['driver_name']} ({FAMILIES_DB[a_fam]['phone']})"
            else:
                a_fam = None
                a_driver_str = "⚠️ חסר נהג מתנדב!"

            results.append({
                "יום": day, 
                "is_holiday": False, 
                "m_family_key": m_fam,
                "נהג בוקר": m_driver_str, 
                "a_family_key": a_fam,
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
                    st.write(f"🌅 **נהג מסיע בבוקר:** {res['נהג בוקר']}")
                    if res["m_family_key"]:
                        status_m = st.selectbox(
                            f"אישור נסיעת בוקר ({day}):", 
                            status_options, 
                            key=f"status_m_{day}"
                        )
                        confirmations[(day, "morn")] = {
                            "family_key": res["m_family_key"], 
                            "status": status_m
                        }
                    if res['מסלול'] != "#":
                        st.markdown(f"[🗺️ ניווט ב-Google Maps]({res['מסלול']})")
                
                with c_aft:
                    st.write(f"🌆 **נהג מסיע אחה\"צ ({res['איסוף אחה\"צ']}):** {res['נהג אחה\"צ']}")
                    if res["a_family_key"]:
                        status_a = st.selectbox(
                            f"אישור נסיעת אחה\"צ ({day}):", 
                            status_options, 
                            key=f"status_a_{day}"
                        )
                        confirmations[(day, "aft")] = {
                            "family_key": res["a_family_key"], 
                            "status": status_a
                        }

            st.markdown("---")
            
        if st.button("💾 עדכון היסטוריה ב-Google Sheets (קרדיט נרשם למשפחה)"):
            history = load_history()
            updated_counts = history.copy()
            approved_count = 0
            
            for (d, shift), info in confirmations.items():
                if info["status"] == "✅ מאושר" and info["family_key"]:
                    fam = info["family_key"]
                    updated_counts[fam] = updated_counts.get(fam, 0) + 1
                    approved_count += 1
            
            save_history(updated_counts)
            st.info(f"עודכנו {approved_count} נסיעות שאושרו בפועל ברמת המשפחה!")

with tab2:
    st.header("🔄 בקשת החלפה בנסיעה")
    swap_day = st.selectbox("בחר יום להחלפה:", DAYS)
    swap_type = st.radio("סוג הנסיעה:", ["בוקר", "אחה\"צ"])
    current_driver_idx = st.selectbox(
        "הנהג המשובץ כרגע:", 
        range(len(DRIVERS_LIST)),
        format_func=lambda i: f"{DRIVERS_LIST[i]['driver_name']} (משפחת {DRIVERS_LIST[i]['family_key']})"
    )
    
    if st.button("🔍 מצא מחליף מומלץ"):
        history = load_history()
        current_fam = DRIVERS_LIST[current_driver_idx]["family_key"]
        candidates = [k for k in FAMILIES_DB.keys() if k != current_fam]
        recommended = sorted(candidates, key=lambda x: history.get(x, 0))[0]
        st.info(f"💡 המשפחה המחליפה המומלצת ביותר (לפי מדד עומס): **{FAMILIES_DB[recommended]['parents'][0]} (משפחת {recommended})**")

with tab3:
    st.header("📊 סטטיסטיקת נסיעות מצטברת לפי משפחה")
    history_data = load_history()
    df_hist = pd.DataFrame([{"משפחה": f"{'/'.join(FAMILIES_DB[k]['parents'])} ({k})", "סך נסיעות": v} for k, v in history_data.items()])
    
    st.bar_chart(df_hist.set_index("משפחה"))
    st.table(df_hist)
