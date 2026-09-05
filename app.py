import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from collections import Counter
import urllib.parse
from datetime import datetime, timedelta
import json
import traceback

st.set_page_config(page_title="ניהול הסעות בית אריה - בן שמן", layout="wide")

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
    DRIVERS_LIST = []

    for row in records:
        f_key = str(row["family_key"])
        parents_str = str(row["parent_name"])
        parents = [p.strip() for p in parents_str.replace('/', ',').replace(' ו-', ',').replace(' ו', ',').split(',')]
        
        FAMILIES_DB[f_key] = {
            "parents": parents,
            "phone": str(row["phone"]),
            "child_name": row["child_name"],
            "address": row["address"]
        }
        
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
            
        hist_sheet.clear()
        rows = [["family_key", "count"]] + [[fam, count] for fam, count in history_data.items()]
        hist_sheet.update(range_name='A1', values=rows)
        return True, "הסטטיסטיקה וההיסטוריה עודכנו בהצלחה ברמת המשפחה!"
    except Exception as e:
        return False, f"שגיאה בשמירת ההיסטוריה: {e}"

def load_weekly_state():
    try:
        ws = sh.worksheet("weekly_state")
        records = ws.get_all_records()
        if records:
            return json.loads(records[0]["data_json"])
    except Exception as e:
        pass
    return {}

def save_weekly_state(state_data):
    try:
        try:
            ws = sh.worksheet("weekly_state")
        except:
            ws = sh.add_worksheet(title="weekly_state", rows="10", cols="2")
            
        json_str = json.dumps(state_data, ensure_ascii=False)
        
        ws.clear()
        ws.update_cell(1, 1, "week_id")
        ws.update_cell(1, 2, "data_json")
        ws.update_cell(2, 1, "current")
        ws.update_cell(2, 2, json_str)
        
        return True, "הנתונים נשמרו בהצלחה ב-Google Sheets!"
    except Exception as e:
        return False, f"שגיאה בעת שמירה: {str(e)}"

SCHOOL_ADDRESS = "בית ספר בן שמן"
DAYS = ["ראשון", "שני", "שלישי", "רביעי", "חמישי"]

def create_gmaps_link(origin, waypoints, destination):
    base_url = "https://www.google.com/maps/dir/?api=1"
    params = {"origin": origin, "destination": destination, "travelmode": "driving"}
    if waypoints:
        params["waypoints"] = "|".join(waypoints)
    return base_url + "&" + urllib.parse.urlencode(params)

def calculate_optimal_pickup_time(end_times, waits_dict):
    times_list = [str(t) for t in end_times.values()]
    if not times_list:
        return "15:00"
    counts = Counter(times_list)
    most_common = counts.most_common()
    
    if most_common[0][1] >= 3:
        return most_common[0][0]
    if len(most_common) >= 2 and most_common[0][1] == 2 and most_common[1][1] == 2:
        return max(most_common[0][0], most_common[1][0])
    if most_common[0][1] == 2:
        return most_common[0][0]
    return max(times_list)

def compute_schedule(saved_state, history):
    results = []
    for day in DAYS:
        data = saved_state.get(day, {})
        if not data or data.get("is_holiday"):
            results.append({"יום": day, "is_holiday": True})
            continue

        absent_fams = data.get("absent_fams", [])
        avail_morn_idx = data.get("avail_morn_idx", [])
        morn_drivers = [DRIVERS_LIST[i] for i in avail_morn_idx if i < len(DRIVERS_LIST)]
        m_candidates = sorted(morn_drivers, key=lambda d: history.get(d["family_key"], 0))
        m_driver_obj = m_candidates[0] if m_candidates else None
        
        if m_driver_obj:
            m_fam = m_driver_obj["family_key"]
            m_driver_str = f"{m_driver_obj['driver_name']} ({FAMILIES_DB[m_fam]['phone']})"
            pickups = [FAMILIES_DB[k]["address"] for k in FAMILIES_DB.keys() if k != m_fam and k not in absent_fams]
            gmaps_link = create_gmaps_link(FAMILIES_DB[m_fam]["address"], pickups, SCHOOL_ADDRESS)
        else:
            m_fam = None
            m_driver_str, gmaps_link = "⚠️ חסר נהג מתנדב!", "#"

        end_times = data.get("end_times", {})
        waits = data.get("waits", {})
        optimal_time = calculate_optimal_pickup_time(end_times, waits)
        
        avail_aft_idx = data.get("avail_aft_idx", [])
        aft_drivers = [DRIVERS_LIST[i] for i in avail_aft_idx if i < len(DRIVERS_LIST)]
        a_candidates = [
            d for d in aft_drivers 
            if end_times.get(d["family_key"]) == optimal_time or 
            (end_times.get(d["family_key"], "15:00") < optimal_time and waits.get(d["family_key"], True))
        ]
        a_candidates = sorted(a_candidates, key=lambda d: history.get(d["family_key"], 0))
        a_driver_obj = a_candidates[0] if a_candidates else None
        
        if a_driver_obj:
            a_fam = a_driver_obj["family_key"]
            a_driver_str = f"{a_driver_obj['driver_name']} ({FAMILIES_DB[a_fam]['phone']})"
        else:
            a_fam = None
            a_driver_str = "⚠️ חסר נהג מתנדב!"

        active_passengers = [
            info["child_name"] 
            for k, info in FAMILIES_DB.items() 
            if k not in absent_fams
        ]

        results.append({
            "יום": day, 
            "is_holiday": False, 
            "m_family_key": m_fam,
            "נהג בוקר": m_driver_str, 
            "a_family_key": a_fam,
            "נהג אחה\"צ": a_driver_str,
            "נוסעים": ", ".join(active_passengers) if active_passengers else "אין נוסעים", 
            "מסלול": gmaps_link, 
            "איסוף אחה\"צ": optimal_time, 
        })
    return results

today = datetime.now()
days_until_sunday = (6 - today.weekday()) % 7
if days_until_sunday == 0 and today.weekday() != 6:
    days_until_sunday = 7
next_sunday = today + timedelta(days=days_until_sunday)
default_week_str = next_sunday.strftime("%d/%m/%Y")

st.title("🚗 ניהול הסעות - בית אריה לבן שמן")

tab1, tab2, tab3, tab4 = st.tabs(["📺 לוח הסעות סופי", "✏️ עדכון זמינות ושעות", "🔄 החלפות", "📊 סטטיסטיקה"])

saved_state = load_weekly_state()
history = load_history()

# --- מסך 1: לוח הסעות סופי ---
with tab1:
    col_date, col_sync = st.columns([3, 1])
    with col_date:
        selected_week = st.text_input("📅 שבוע מתחיל בתאריך (יום ראשון):", value=default_week_str, key="week_tab1")
    with col_sync:
        st.write("")
        st.write("")
        if st.button("🔄 רענן נתונים מהענן", key="refresh_tab1"):
            st.rerun()

    st.subheader("📋 לוח הסעות שבועי סופי")
    current_schedule = compute_schedule(saved_state, history)
    
    status_options = ["⏳ ממתין לאישור", "✅ מאושר", "❌ נדחה / נדרשת החלפה"]
    confirmations = {}

    for idx, res in enumerate(current_schedule):
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

            st.write(f"👦👧 **ילדים נוסעים:** {res['נוסעים']}")

        st.markdown("---")
    
    st.session_state["weekly_confirmations"] = confirmations

# --- מסך 2: עדכון זמינות ושעות ---
with tab2:
    st.header("✏️ עדכון זמינות שבועית ושעות סיום")
    
    with st.form("weekly_schedule_form"):
        schedule_data = {}
        for day in DAYS:
            day_state = saved_state.get(day, {})
            st.markdown(f"### 📅 יום {day}")
            is_holiday = st.checkbox(f"🎉 יום חופש / חג (אין לימודים ביום {day})", value=day_state.get("is_holiday", False), key=f"{day}_holiday")
            
            if not is_holiday:
                c1, c2 = st.columns(2)
                
                with c1:
                    default_morn = day_state.get("avail_morn_idx", [])
                    default_aft = day_state.get("avail_aft_idx", [])
                    
                    avail_morn_idx = st.multiselect(
                        "🙋‍♂️ מתנדבים לבוקר", 
                        range(len(DRIVERS_LIST)), 
                        default=default_morn, 
                        format_func=lambda i: f"{DRIVERS_LIST[i]['driver_name']} (משפחת {DRIVERS_LIST[i]['family_key']})",
                        key=f"{day}_morn"
                    )
                    avail_aft_idx = st.multiselect(
                        "🙋‍♂️ מתנדבים לאחה\"צ", 
                        range(len(DRIVERS_LIST)), 
                        default=default_aft, 
                        format_func=lambda i: f"{DRIVERS_LIST[i]['driver_name']} (משפחת {DRIVERS_LIST[i]['family_key']})",
                        key=f"{day}_aft"
                    )
                
                with c2:
                    saved_absent = day_state.get("absent", [])
                    absent = st.multiselect("🚨 החרגות בוקר (ילדים שלא נוסעים):", [f"{info['child_name']} ({k})" for k, info in FAMILIES_DB.items()], default=saved_absent, key=f"{day}_absent")
                    absent_fams = [k for k, info in FAMILIES_DB.items() if f"{info['child_name']} ({k})" in absent]

                with st.expander(f"⏰ עדכון שעות סיום והמתנה - יום {day}", expanded=False):
                    end_times, waits = {}, {}
                    saved_ends = day_state.get("end_times", {})
                    saved_waits = day_state.get("waits", {})
                    
                    for f_key, f_info in FAMILIES_DB.items():
                        col_a, col_b = st.columns([2, 1])
                        with col_a:
                            saved_val = saved_ends.get(f_key, "15:00")
                            try:
                                default_time = datetime.strptime(saved_val, "%H:%M").time()
                            except:
                                default_time = pd.to_datetime("15:00").time()
                                
                            t_val = st.time_input(f"סיום {f_info['child_name']}", value=default_time, key=f"{day}_{f_key}_end")
                            end_times[f_key] = t_val.strftime("%H:%M")
                        with col_b:
                            waits[f_key] = st.checkbox("ממתין/ה", value=saved_waits.get(f_key, True), key=f"{day}_{f_key}_wait")

                schedule_data[day] = {
                    "is_holiday": False, 
                    "end_times": end_times, 
                    "waits": waits, 
                    "avail_morn_idx": avail_morn_idx, 
                    "avail_aft_idx": avail_aft_idx, 
                    "absent": absent,
                    "absent_fams": absent_fams
                }
            else:
                schedule_data[day] = {"is_holiday": True}
            
            st.markdown("---")

        submit_button = st.form_submit_button("💾 שמור זמינות בענן ועדכן לוח")

    if submit_button:
        clean_save = {}
        for day, data in schedule_data.items():
            if data.get("is_holiday"):
                clean_save[day] = {"is_holiday": True}
            else:
                clean_save[day] = {
                    "is_holiday": False,
                    "end_times": data["end_times"],
                    "waits": data["waits"],
                    "avail_morn_idx": data["avail_morn_idx"],
                    "avail_aft_idx": data["avail_aft_idx"],
                    "absent": data["absent"]
                }
                
        success, msg = save_weekly_state(clean_save)
        if success:
            st.success("✅ " + msg + " עבור לחוצץ 'לוח הסעות סופי' לצפייה בלוח המעודכן.")
            st.rerun()
        else:
            st.error("❌ " + msg)

# --- מסך 3: החלפות ---
with tab3:
    st.header("🔄 בקשת החלפה בנסיעה")
    swap_day = st.selectbox("בחר יום להחלפה:", DAYS)
    swap_type = st.radio("סוג הנסיעה:", ["בוקר", "אחה\"צ"])
    current_driver_idx = st.selectbox(
        "הנהג המשובץ כרגע:", 
        range(len(DRIVERS_LIST)),
        format_func=lambda i: f"{DRIVERS_LIST[i]['driver_name']} (משפחת {DRIVERS_LIST[i]['family_key']})"
    )
    
    if st.button("🔍 מצא מחליף מומלץ"):
        current_fam = DRIVERS_LIST[current_driver_idx]["family_key"]
        candidates = [k for k in FAMILIES_DB.keys() if k != current_fam]
        recommended = sorted(candidates, key=lambda x: history.get(x, 0))[0]
        st.info(f"💡 המשפחה המחליפה המומלצת ביותר (לפי מדד עומס): **{FAMILIES_DB[recommended]['parents'][0]} (משפחת {recommended})**")

# --- מסך 4: סטטיסטיקה ---
with tab4:
    st.header("📊 סטטיסטיקת נסיעות מצטברת לפי משפחה")
    
    st.subheader("📥 סגירת שבוע ועדכון נסיעות")
    st.caption("לחץ על הכפתור למטה בסוף השבוע כדי לסכם את כל הנסיעות שאושרו ב-✅ ולהוסיף אותן למאזן הכללי ב-Google Sheets.")
    
    if st.button("📥 סיכום שבועי – סגירת שבוע ועדכון הסטטיסטיקה"):
        confirmations = st.session_state.get("weekly_confirmations", {})
        if not confirmations:
            st.warning("⚠️ לא נמצאו נתוני נסיעות מאושרות מהשבוע הנוכחי.")
        else:
            updated_counts = history.copy()
            approved_count = 0
            
            for (d, shift), info in confirmations.items():
                if info["status"] == "✅ מאושר" and info["family_key"]:
                    fam = info["family_key"]
                    updated_counts[fam] = updated_counts.get(fam, 0) + 1
                    approved_count += 1
            
            if approved_count > 0:
                success, msg = save_history(updated_counts)
                if success:
                    st.success(f"🎉 השבוע נסגר בהצלחה! התווספו {approved_count} נסיעות מאושרות למאזן המשפחות.")
                    st.rerun()
                else:
                    st.error(f"❌ {msg}")
            else:
                st.info("ℹ️ לא סומנו נסיעות בסטטוס '✅ מאושר'. הסטטיסטיקה לא שונתה.")

    st.markdown("---")
    
    with st.expander("⚙️ ניהול ואיפוס נתונים (מנהל מערכת)", expanded=False):
        st.warning("⚠️ אזהרה: פעולה זו תאפס את ניקוד כל המשפחות ל-0 ב-Google Sheets. מומלץ לבצע רק בתחילת עונה/שנה חדשה.")
        confirm_reset = st.checkbox("אני מאשר/ת שברצוני לאפס את ניקוד כל המשפחות ל-0")
        if st.button("🗑️ אפס את כל הסטטיסטיקה ל-0"):
            if confirm_reset:
                zero_history = {fam: 0 for fam in FAMILIES_DB.keys()}
                success, msg = save_history(zero_history)
                if success:
                    st.success("🎉 הסטטיסטיקה אופסה בהצלחה! כל המשפחות עודכנו ל-0 נסיעות.")
                    st.rerun()
                else:
                    st.error(f"❌ {msg}")
            else:
                st.error("אנא סמן את תיבת האישור לפני הלחיצה על איפוס.")

    st.markdown("---")
    
    df_hist = pd.DataFrame([{"משפחה": f"{'/'.join(FAMILIES_DB[k]['parents'])} ({k})", "סך נסיעות": v} for k, v in history.items()])
    
    st.bar_chart(df_hist.set_index("משפחה"))
    st.table(df_hist)
