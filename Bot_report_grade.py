import os
import json
import time
import random
import requests
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import (
    NoSuchElementException,
    WebDriverException,
    UnexpectedAlertPresentException,
)
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


# ===================== โหลดค่า ENV =====================

# โหลด .env จากโฟลเดอร์เดียวกับไฟล์นี้
BASE_DIR = os.path.dirname(__file__)
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path=ENV_PATH, override=True)

LOGIN_URL = os.environ["LOGIN_URL"]
USER = os.environ["USER"]
PASS = os.environ["PASS"]

TARGET_TERM_TEXT = os.environ["TARGET_TERM_TEXT"]

REFRESH_MIN_SEC = int(os.environ.get("REFRESH_MIN_SEC", "300"))
REFRESH_MAX_SEC = int(os.environ.get("REFRESH_MAX_SEC", "600"))

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]


# ===================== ไฟล์สถานะที่เคยแจ้งแล้ว =====================

SEEN_FILE = os.path.join(BASE_DIR, "seen.json")

def load_seen():
    """อ่านไฟล์ seen.json ถ้าไม่มีให้คืน {}"""
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_seen(seen_dict):
    """เขียนไฟล์ seen.json"""
    with open(SEEN_FILE, "w", encoding="utf8") as f:
        json.dump(seen_dict, f, ensure_ascii=False, indent=2)


# ===================== Discord Notify =====================

def notify_embed(title: str, body: str, color_rgb: int):
    """
    ส่ง Discord webhook แบบ embed สี
    color_rgb เป็น int เช่น 0xFFFF00 (เหลือง), 0x00FF00 (เขียว), 0xFF0000 (แดง)
    """
    payload = {
        "content": title,  # fallback
        "embeds": [
            {
                "title": title,
                "description": body,
                "color": color_rgb,
            }
        ],
    }
    try:
        res = requests.post(DISCORD_WEBHOOK, json=payload, timeout=6)
        print("Discord status:", res.status_code, res.text)
    except Exception as e:
        print("ส่งแจ้งเตือน Discord ไม่ได้:", e)


# ===================== Selenium helpers =====================

def login(driver):
    """เข้าสู่ระบบ"""
    driver.get(LOGIN_URL)
    time.sleep(2)

    user_box = driver.find_element(By.ID, "f_uid")
    pass_box = driver.find_element(By.ID, "f_pwd")

    user_box.clear()
    user_box.send_keys(USER)
    pass_box.clear()
    pass_box.send_keys(PASS)
    pass_box.send_keys(Keys.ENTER)
    time.sleep(2)

    # ปิด popup ประเมิน ถ้ามี
    try:
        alert = driver.switch_to.alert
        alert.dismiss()  # Cancel = เข้า dashboard
        print("ปิด popup การประเมินแล้ว")
    except:
        pass


def goto_grade_page(driver):
    """คลิกเมนู 'ผลการศึกษา'"""
    try:
        driver.find_element(By.LINK_TEXT, "ผลการศึกษา").click()
    except NoSuchElementException:
        driver.find_element(By.PARTIAL_LINK_TEXT, "ผลการศึกษา").click()
    time.sleep(2)


def parse_grade_from_row_text(row_text: str, valid_grades: set[str]) -> str:
    """
    รับข้อความรายวิชาใน 1 row เช่น
      'EN813001 STOCHASTIC PROCESSES AND MODELING 3   A'
      'EN813202 MICROPROCESSORS AND INTERFACING 3'
    คืนค่าเกรดเช่น 'A', 'B+', 'F'
    หรือ '' ถ้ายังไม่มีเกรด
    """
    row_text = row_text.strip().replace("\xa0", " ")
    parts = row_text.split()
    for token in parts:
        t = token.upper()
        if t in valid_grades:
            return t
    return ""


def read_all_grades_for_term(driver, term_text: str):
    """
    อ่านเฉพาะวิชาในเทอม term_text เท่านั้น
    โครงสร้างในหน้า: มี <tr class='HeaderDetail'>ภาคการศึกษาที่ X/XXXX
    ตามด้วย <tr class='g_normalDetail'> วิชาแต่ละตัว
    ถ้าเจอเทอมอื่น ให้หยุด

    return dict เช่น:
        {
          'EN813001': 'A',
          'EN813202': '',
          'EN813203': 'B+',
          ...
        }

    return None ถ้าไม่สามารถอ่านเทอมนั้นได้ (เช่น session หลุด)
    """
    try:
        tables = driver.find_elements(By.TAG_NAME, "table")
    except WebDriverException:
        return None

    valid_grades = {
        "A", "B", "C", "D", "F",
        "A+", "B+", "C+", "D+",
        "S", "U", "W", "P", "AU",
        "S AU"
    }

    for t in tables:
        rows = t.find_elements(By.TAG_NAME, "tr")

        collecting = False
        grades_map = {}

        for r in rows:
            cls = r.get_attribute("class") or ""
            text = r.text.strip().replace("\xa0", " ")

            # ถ้าเป็น header ของเทอม
            if "HeaderDetail" in cls:
                # ตัวอย่าง header: "ภาคการศึกษาที่ 1/2568"
                if term_text in text:
                    # เริ่มเก็บตั้งแต่ตรงนี้
                    collecting = True
                    continue
                else:
                    # ถ้าเรากำลังเก็บอยู่ แล้วเจอ header ใหม่ที่ไม่ตรง term_text
                    # แปลว่าเทอมใหม่เริ่มแล้ว จบการเก็บ
                    if collecting:
                        return grades_map
                    collecting = False
                    continue

            # ระหว่างกำลังเก็บเทอมที่สนใจ
            if collecting:
                # แถววิชามักเป็น class='g_normalDetail'
                if "g_normalDetail" in cls:
                    row_text = text
                    parts = row_text.split()
                    if not parts:
                        continue

                    # token แรกควรเป็นรหัสวิชา เช่น EN813001
                    course_code = parts[0].upper()
                    has_alpha = any(ch.isalpha() for ch in course_code)
                    has_digit = any(ch.isdigit() for ch in course_code)
                    if not (has_alpha and has_digit):
                        # ถ้าไม่ใช่โค้ดรายวิชา (อาจเป็นสรุป CR/CP/GPA)
                        continue

                    grade_val = parse_grade_from_row_text(row_text, valid_grades)
                    grades_map[course_code] = grade_val

        # ถ้าเรามีข้อมูลจากเทอมนี้แล้วใน table นี้ ส่งกลับเลย
        if grades_map:
            return grades_map

    # วนทุก table แล้วยังไม่เจอเทอมเลย
    return None


# ===================== main loop =====================

def main():
    print("เริ่ม Grade Watcher")

    # เปิด Chrome
    chrome_opts = webdriver.ChromeOptions()
    # ถ้าอยากรันแบบไม่มีหน้าต่าง ให้ uncomment:
    # chrome_opts.add_argument("--headless=new")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_opts,
    )
    print("เปิด browser แล้ว")

    # login + ไปหน้าผลการศึกษา
    login(driver)
    goto_grade_page(driver)

    # โหลดสถานะที่เคยแจ้งไปแล้ว
    seen = load_seen()
    # seen มีรูปแบบ {"EN813001": "A", "EN813202": "" ...}
    # ค่า "" ใน seen หมายถึงเคยบอกแล้วว่าวิชานี้ยังไม่ออกเกรด
    # ค่า "A","B+",... หมายถึงเคยแจ้งเกรดไปแล้ว

    none_count = 0

    while True:
        try:
            all_grades = read_all_grades_for_term(driver, TARGET_TERM_TEXT)
            now = time.strftime("%H:%M:%S")

            if all_grades is None:
                # อ่านไม่ได้ อาจ session หลุด หรือ DOM ไม่ครบ
                none_count += 1
                print(f"[{now}] ไม่อ่านเทอม '{TARGET_TERM_TEXT}' ได้ / session อาจหมด ({none_count}/3)")

                if none_count >= 3:
                    print(f"[{now}] re-login ...")
                    login(driver)
                    goto_grade_page(driver)
                    none_count = 0

                time.sleep(10)
                continue

            # อ่านได้ปกติ
            none_count = 0

            print(f"[{now}] เทอม {TARGET_TERM_TEXT}: วิชา {list(all_grades.keys())}")

            # แจ้งเตือนเฉพาะวิชาที่มีสถานะ "ใหม่" เท่านั้น
            for course_code, grade_val in all_grades.items():
                prev_val = seen.get(course_code, None)

                # เคสยังไม่มีเกรด (ช่องว่าง)
                if grade_val.strip() == "":
                    # ถ้าเราเคยแจ้งว่ายังไม่ประกาศไปแล้ว ก็ข้าม
                    if prev_val is not None:
                        continue

                    # ยังไม่เคยแจ้ง -> print เฉยๆ ไม่ส่ง Discord
                    print(f"[{now}] ⏳ {course_code} ({TARGET_TERM_TEXT}) ยังไม่ประกาศเกรด")
                    seen[course_code] = ""  # เก็บว่ารายวิชานี้เจอแล้ว จะไม่ print ซ้ำ
                    save_seen(seen)
                    continue

                # ถึงตรงนี้หมายถึงวิชานี้มีเกรดแล้วจริง
                # ถ้าเคยแจ้งเกรดนี้ไปแล้ว ให้ข้าม
                if prev_val == grade_val:
                    continue

                # แจ้งตามสี
                if grade_val.upper() == "F":
                    body = (
                        f"{course_code} ({TARGET_TERM_TEXT}) = {grade_val}\n"
                        f"ขอให้ตั้งหลักใหม่ได้เร็วที่สุด"
                    )
                    color = 0xFF0000  # แดง
                    title = "แจ้งผลเกรด (F)"
                    print(f"[{now}] 💀 {course_code} = {grade_val}")
                else:
                    body = (
                        f"{course_code} ({TARGET_TERM_TEXT}) = {grade_val}\n"
                        f"ยินดีด้วยคุณได้ไปฝึกงานที่ Analog"
                    )
                    color = 0x00FF00  # เขียว
                    title = "แจ้งผลเกรด"
                    print(f"[{now}] ✅ {course_code} = {grade_val}")

                notify_embed(
                    title=title,
                    body=body,
                    color_rgb=color,
                )

                # บันทึกสถานะเกรดที่แจ้งล่าสุด
                seen[course_code] = grade_val
                save_seen(seen)

            # ตรวจว่าครบทุกวิชาในเทอมนี้มีเกรดหรือยัง
            # ถ้าไม่มีตัวไหนว่าง "" อีกแล้ว แปลว่าครบแล้ว
            still_waiting = [
                c for (c, g) in all_grades.items() if g.strip() == ""
            ]
            if not still_waiting:
                # แจ้งสรุปสุดท้ายแล้วจบการทำงาน
                summary_body = (
                    f"เกรดครบทุกวิชาใน {TARGET_TERM_TEXT} แล้ว\n"
                    f"ปิดการเฝ้าระบบอัตโนมัติ"
                )
                notify_embed(
                    title="ครบทุกวิชาแล้ว",
                    body=summary_body,
                    color_rgb=0x00FF00,  # เขียว
                )
                print(f"[{now}] เกรดครบทุกวิชาแล้ว จบการทำงาน")
                driver.quit()
                break

            # ถ้ายังไม่ครบ ให้รอแล้วรีเฟรชต่อ
            wait_s = random.uniform(REFRESH_MIN_SEC, REFRESH_MAX_SEC)
            print(f"[{now}] ยังรอวิชา: {still_waiting}")
            print(f"[{now}] รอ {int(wait_s)} วินาที แล้วรีเฟรชใหม่")
            time.sleep(wait_s)

            driver.refresh()
            time.sleep(2)

        except UnexpectedAlertPresentException:
            # ถ้ามี popup เด้งระหว่างรัน เช่นบังคับประเมิน
            try:
                alert = driver.switch_to.alert
                alert.dismiss()
                print("ปิด popup กลางคันแล้ว")
            except:
                pass

        except Exception as e:
            print("เกิดข้อผิดพลาด:", e)
            time.sleep(10)


if __name__ == "__main__":
    main()