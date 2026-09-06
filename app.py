import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from collections import Counter
import urllib.parse
from datetime import datetime, timedelta
import json

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
    DRIVERS_LIST = ["— ללא נהג / חסר —"]

    for row in records:
        f_key = str(row["family_key"])
        parents_str = str(row["parent_name"])
        parents = [p.strip() for p in parents_str.replace('/', ',').replace(' ו-', ',').replace(' ו', ',').split(',')]
        
        raw_address = str(row["address"])
        addresses = [a.strip() for a in raw_address.split('/') if a.strip()]
        
        FAMILIES_DB[f_key] = {
            "parents": parents,
            "phone": str(row["phone"]),
            "child_name": row["child_name"],
            "addresses": addresses,
            "default_address": addresses[0] if addresses else ""
        }
        
        for p in parents:
            DRIVERS_LIST.append(f"{p} (משפחת {f_key})")

except Exception as e:
    st.error(f"שגיאה בהתחברות ל-Google Sheets: {e}")
    st.stop()

def get_family_key_from_driver_str(driver_str):
    if not driver_str or driver_str == "— ללא נהג / חסר —":
        return None
    for f_key in FAMILIES_DB.keys():
        if f"משפחת {f_key}" in driver_str:
            return f_key
    return None

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

def calculate_optimal_pickup_time(end_times):
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

today = datetime.now()
days_until_sunday = (6 - today.weekday()) % 7
if days_until_sunday == 0 and today.weekday() != 6:
    days_until_sunday = 7
next_sunday = today + timedelta(days=days_until_sunday)
default_week_str = next_sunday.strftime("%d/%m/%Y")

st.title("🚗 ניהול הסעות - בית אריה לבן שמן")

tab1, tab2 = st.tabs(["🗓️ השבוע שלי", "📊 סטטיסטיקה"])

saved_state = load_weekly_state()
history = load_history()

with tab1:
    col_date, col_sync = st.columns([3, 1])
    with col_date:
        selected_week = st.text_input("📅 שבוע מתחיל בתאריך (יום ראשון):", value=default_week_str)
    with col_sync:
        st.write("")
        st.write("")
        if st.button("🔄 רענן נתונים מהענן"):
            st.rerun()

    with st.form("weekly_schedule_form"):
        schedule_data = {}
        for day in DAYS:
            day_state = saved_state.get(day, {})
            st.markdown(f"## 📅 יום {day}")
            is_holiday = st.checkbox(f"🎉 יום חופש / חג (אין לימודים ביום {day})", value=day_state.get("is_holiday", False), key=f"{day}_holiday")
            
            if not is_holiday:
                c1, c2 = st.columns(2)
                
                saved_morn_driver = day_state.get("morn_driver")
                if not saved_morn_driver:
                    m_idxs = day_state.get("avail_morn_idx", [])
                    if m_idxs and (m_idxs[0] + 1) < len(DRIVERS_LIST):
                        saved_morn_driver = DRIVERS_LIST[m_idxs[0] + 1]
                    else:
                        saved_morn_driver = "— ללא נהג / חסר —"

                saved_aft_driver = day_state.get("aft_driver")
                if not saved_aft_driver:
                    a_idxs = day_state.get("avail_aft_idx", [])
                    if a_idxs and (a_idxs[0] + 1) < len(DRIVERS_LIST):
                        saved_aft_driver = DRIVERS_LIST[a_idxs[0] + 1]
                    else:
                        saved_aft_driver = "— ללא נהג / חסר —"

                with c1:
                    morn_idx = DRIVERS_LIST.index(saved_morn_driver) if saved_morn_driver in DRIVERS_LIST else 0
                    selected_morn_driver = st.selectbox("🌅 נהג/ת לבוקר:", DRIVERS_LIST, index=morn_idx, key=f"{day}_morn")
                    
                    aft_idx = DRIVERS_LIST.index(saved_aft_driver) if saved_aft_driver in DRIVERS_LIST else 0
                    selected_aft_driver = st.selectbox("🌆 נהג/ת לאחה\"צ:", DRIVERS_LIST, index=aft_idx, key=f"{day}_aft")

                with c2:
                    saved_absent = day_state.get("absent", [])
                    absent = st.multiselect("🚨 החרגות בוקר (ילדים שלא נוסעים):", [f"{info['child_name']} ({k})" for k, info in FAMILIES_DB.items()], default=saved_absent, key=f"{day}_absent")
                    absent_fams = [k for k, info in FAMILIES_DB.items() if f"{info['child_name']} ({k})" in absent]

                # חלון עדכון שעות סיום וכתובות איסוף
                with st.expander(f"⏰ עדכון שעות סיום וכתובת איסוף - יום {day}", expanded=False):
                    end_times = {}
                    selected_addresses = {}
                    saved_ends = day_state.get("end_times", {})
                    saved_selected_addrs = day_state.get("selected_addresses", {})
                    
                    for f_key, f_info in FAMILIES_DB.items():
                        col_a, col_b = st.columns([1, 2])
                        with col_a:
                            saved_val = saved_ends.get(f_key, "15:00")
                            try:
                                default_time = datetime.strptime(saved_val, "%H:%M").time()
                            except:
                                default_time = pd.to_datetime("15:00").time()
                                
                            t_val = st.time_input(f"סיום {f_info['child_name']}", value=default_time, key=f"{day}_{f_key}_end")
                            end_times[f_key] = t_val.strftime("%H:%M")
                            
                        with col_b:
                            addrs = f_info["addresses"]
                            if len(addrs) > 1:
                                saved_addr = saved_selected_addrs.get(f_key, addrs[0])
                                addr_idx = addrs.index(saved_addr) if saved_addr in addrs else 0
                                chosen_addr = st.selectbox(
                                    f"📍 כתובת איסוף עבור {f_info['child_name']}:", 
                                    addrs, 
                                    index=addr_idx, 
                                    key=f"{day}_{f_key}_addr"
                                )
                                selected_addresses[f_key] = chosen_addr
                            else:
                                chosen_addr = f_info["default_address"]
                                selected_addresses[f_key] = chosen_addr
                                st.markdown(f"📍 **כתובת איסוף:** {chosen_addr}")

                col_status_m, col_status_a = st.columns(2)
                
                m_fam = get_family_key_from_driver_str(selected_morn_driver)
                with col_status_m:
                    if selected_morn_driver == "— ללא נהג / חסר —":
                        st.warning("🌅 **בוקר:** ⚠️ חסר נהג מתנדב!")
                    else:
                        st.success(f"🌅 **בוקר:** {selected_morn_driver}")
                        if m_fam:
                            pickups = [
                                selected_addresses.get(k, FAMILIES_DB[k]["default_address"]) 
                                for k in FAMILIES_DB.keys() 
                                if k != m_fam and k not in absent_fams
                            ]
                            driver_origin = selected_addresses.get(m_fam, FAMILIES_DB[m_fam]["default_address"])
                            gmaps_link = create_gmaps_link(driver_origin, pickups, SCHOOL_ADDRESS)
                            st.markdown(f"[🗺️ ניווט ב-Google Maps]({gmaps_link})")

                optimal_time = calculate_optimal_pickup_time(end_times)
                with col_status_a:
                    if selected_aft_driver == "— ללא נהג / חסר —":
                        st.warning(f"🌆 **אחה\"צ ({optimal_time}):** ⚠️ חסר נהג מתנדב!")
                    else:
                        st.success(f"🌆 **אחה\"צ ({optimal_time}):** {selected_aft_driver}")

                active_passengers = [info["child_name"] for k, info in FAMILIES_DB.items() if k not in absent_fams]
                st.caption(f"👦👧 **ילדים נוסעים בבוקר:** {', '.join(active_passengers) if active_passengers else 'אין נוסעים'}")

                schedule_data[day] = {
                    "is_holiday": False, 
                    "morn_driver": selected_morn_driver,
                    "aft_driver": selected_aft_driver,
                    "m_fam": m_fam,
                    "a_fam": get_family_key_from_driver_str(selected_aft_driver),
                    "end_times": end_times, 
                    "selected_addresses": selected_addresses,
                    "absent": absent,
                    "absent_fams": absent_fams
                }
            else:
                st.info(f"🎉 **יום {day}:** יום חופש / חג - אין הסעות")
                schedule_data[day] = {"is_holiday": True}
            
            st.markdown("---")

        submit_button = st.form_submit_button("💾 שמור זמינות ושיבוץ בענן")

    if submit_button:
        success, msg = save_weekly_state(schedule_data)
        if success:
            st.success("✅ " + msg)
            st.rerun()
        else:
            st.error("❌ " + msg)

with tab2:
    st.header("📊 סטטיסטיקת נסיעות מצטברת לפי משפחה")
    
    st.subheader("📥 סגירת שבוע ועדכון נסיעות")
    st.caption("לחץ על הכפתור בסוף השבוע כדי לסכם את כל הנסיעות שבוצעו בפועל ולהוסיף אותן למאזן הכללי ב-Google Sheets.")
    
    if st.button("📥 סיכום שבועי – סגירת שבוע ועדכון הסטטיסטיקה"):
        updated_counts = history.copy()
        approved_count = 0
        
        for day in DAYS:
            day_data = saved_state.get(day, {})
            if not day_data.get("is_holiday"):
                m_fam = day_data.get("m_fam")
                if m_fam:
                    updated_counts[m_fam] = updated_counts.get(m_fam, 0) + 1
                    approved_count += 1
                
                a_fam = day_data.get("a_fam")
                if a_fam:
                    updated_counts[a_fam] = updated_counts.get(a_fam, 0) + 1
                    approved_count += 1
        
        if approved_count > 0:
            success, msg = save_history(updated_counts)
            if success:
                st.success(f"🎉 השבוע נסגר בהצלחה! התווספו {approved_count} נסיעות למאזן המשפחות.")
                st.rerun()
            else:
                st.error(f"❌ {msg}")
        else:
            st.info("ℹ️ לא נמצאו נהגים משובצים בשבוע הנוכחי. הסטטיסטיקה לא שונתה.")

    st.markdown("---")
    
    df_hist = pd.DataFrame([{"משפחה": f"{'/'.join(FAMILIES_DB[k]['parents'])} ({k})", "סך נסיעות": v} for k, v in history.items()])
    
    st.bar_chart(df_hist.set_index("משפחה"))
    st.table(df_hist)
