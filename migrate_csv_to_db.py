import csv
from datetime import datetime
import json
import os
import re
import sqlite3

DB_PATH = "results/karuta_results.db"
HISTORY_CSV = "results/recognition_history.csv"
RESULTS_DIR = "results"
RECORDINGS_DIR = "recordings"


def reset_and_init_db():
    """親テーブル（試行セット）と子テーブル（各札ログ）を作成"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS recognition_logs")
    cursor.execute("DROP TABLE IF EXISTS test_sessions")

    # 親テーブル
    cursor.execute("""
        CREATE TABLE test_sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_type TEXT,        -- '100首セット' または '単体/個別試行'
            session_date TEXT,        -- 日付のみ (YYYY-MM-DD)
            start_datetime TEXT,      -- 開始日時
            end_datetime TEXT,        -- 終了日時
            reader_name TEXT,         -- 読手名
            gender TEXT,
            dictionary TEXT,
            total_cards INTEGER       -- セットに含まれる枚数
        )
    """)

    # 子テーブル（reader_name カラムを追加）
    cursor.execute("""
        CREATE TABLE recognition_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,       -- 親テーブル(test_sessions)のID
            card_order INTEGER,       -- セット内での順序 (1~)
            date_only TEXT,           -- 日付のみ (YYYY-MM-DD)
            datetime TEXT,
            reader_name TEXT,         -- ★読手名を追加
            raw_audio_name TEXT,
            raw_audio_path TEXT,
            processed_audio_path TEXT,
            detail_csv_filename TEXT,
            detail_csv_path TEXT,
            final_id TEXT,
            final_similarity REAL,
            recognized_words TEXT,
            detail_logs_json TEXT,
            FOREIGN KEY (session_id) REFERENCES test_sessions(session_id)
        )
    """)
    conn.commit()
    conn.close()


def parse_datetime(dt_str):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            pass
    return None


def extract_date_only(dt_str):
    dt_obj = parse_datetime(dt_str)
    if dt_obj:
        return dt_obj.strftime("%Y-%m-%d")
    return dt_str.split(" ")[0].replace("/", "-") if dt_str else "ー"


def is_first_card_file(file_name):
    pattern = r"set_0*1[._]"
    return bool(re.search(pattern, file_name, re.IGNORECASE))


def load_detail_csv(base_filename):
    csv_name = (
        base_filename
        if base_filename.endswith(".csv")
        else f"{base_filename}.csv"
    )
    csv_path = os.path.abspath(os.path.join(RESULTS_DIR, csv_name))

    if not os.path.exists(csv_path):
        return "ー", "ー", "[]"

    logs = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if row:
                logs.append(row)

    return csv_name, csv_path, json.dumps(logs, ensure_ascii=False)


def determine_reader_name(session_id, chunk):
    """読手を判定する関数"""
    if 130 <= session_id <= 132:
        return "芹野専任読手"

    file_names_concat = " ".join(
        [item["file_name"].lower() for item in chunk]
    )
    
    if "yoshi" in file_names_concat or "yosi" in file_names_concat:
        return "吉川専任読手"

    if "hito" in file_names_concat:
        return "廣瀨"

    return "稲葉専任読手"


def migrate():
    reset_and_init_db()

    if not os.path.exists(HISTORY_CSV):
        print(f"Error: {HISTORY_CSV} が見つかりませんでした。")
        return

    parsed_rows = []
    row_counter = 0

    with open(HISTORY_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or not row[0].strip() or "日時" in row[0] or "日付" in row[0]:
                continue

            row_counter += 1

            if len(row) >= 7:
                if row_counter <= 1400:
                    dt, gender, dict_val = row[0].strip(), "ー", "ー"
                    file_name, final_id = row[1].strip(), row[4].strip()
                    sim_str = row[5].replace("%", "").strip()
                    words = row[6].strip() if len(row) > 6 else "ー"
                else:
                    dt = row[0].strip()
                    gender = row[1].strip() if row[1].strip() else "ー"
                    dict_val = row[2].strip() if row[2].strip() else "ー"
                    file_name, final_id = row[3].strip(), row[4].strip()
                    sim_str = row[5].replace("%", "").strip()
                    words = row[6].strip() if len(row) > 6 else "ー"
            elif len(row) >= 5:
                dt, gender, dict_val = row[0].strip(), "ー", "ー"
                file_name, final_id = row[1].strip(), row[2].strip()
                sim_str = row[3].replace("%", "").strip()
                words = row[4].strip() if len(row) > 4 else "ー"
            else:
                continue

            try:
                sim_val = float(sim_str)
            except ValueError:
                sim_val = 0.0

            parsed_rows.append({
                "dt_str": dt,
                "dt_obj": parse_datetime(dt),
                "date_only": extract_date_only(dt),
                "gender": gender,
                "dict": dict_val,
                "file_name": file_name,
                "final_id": final_id,
                "sim": sim_val,
                "words": words,
            })

    # グループ化処理
    sessions = []
    current_chunk = []
    prev_dt = None

    for item in parsed_rows:
        is_new_set = False

        if is_first_card_file(item["file_name"]):
            is_new_set = True
        elif prev_dt and item["dt_obj"]:
            time_diff = (item["dt_obj"] - prev_dt).total_seconds()
            if time_diff > 30:
                is_new_set = True

        if is_new_set and current_chunk:
            sessions.append(current_chunk)
            current_chunk = []

        current_chunk.append(item)
        if item["dt_obj"]:
            prev_dt = item["dt_obj"]

    if current_chunk:
        sessions.append(current_chunk)

    # DBへの書き込み
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    for session_idx, chunk in enumerate(sessions, 1):
        first_item = chunk[0]
        last_item = chunk[-1]

        session_type = (
            "100首セット" if len(chunk) >= 50 else "単体/一部試行"
        )

        reader_name = determine_reader_name(session_idx, chunk)

        # 親テーブル (test_sessions)
        cursor.execute(
            """
            INSERT INTO test_sessions (
                session_type, session_date, start_datetime, end_datetime, 
                reader_name, gender, dictionary, total_cards
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                session_type,
                first_item["date_only"],
                first_item["dt_str"],
                last_item["dt_str"],
                reader_name,
                first_item["gender"],
                first_item["dict"],
                len(chunk),
            ),
        )

        session_id = cursor.lastrowid

        # 子テーブル (recognition_logs) に reader_name もセットして登録
        for idx, item in enumerate(chunk, 1):
            wav_name = (
                item["file_name"]
                if item["file_name"].endswith(".wav")
                else f"{item['file_name']}.wav"
            )
            raw_path = os.path.abspath(os.path.join(RECORDINGS_DIR, wav_name))
            if not os.path.exists(raw_path):
                alt = os.path.abspath(
                    os.path.join(RECORDINGS_DIR, "raw", wav_name)
                )
                raw_path = alt if os.path.exists(alt) else "ー"

            base_csv = item["file_name"].replace(".wav", "").replace(".csv", "")
            csv_name, csv_path, detail_json = load_detail_csv(base_csv)

            cursor.execute(
                """
                INSERT INTO recognition_logs (
                    session_id, card_order, date_only, datetime, reader_name,
                    raw_audio_name, raw_audio_path, processed_audio_path, 
                    detail_csv_filename, detail_csv_path, final_id, 
                    final_similarity, recognized_words, detail_logs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ー', ?, ?, ?, ?, ?, ?)
            """,
                (
                    session_id,
                    idx,
                    item["date_only"],
                    item["dt_str"],
                    reader_name,  # ★読手名を追加
                    wav_name,
                    raw_path,
                    csv_name,
                    csv_path,
                    item["final_id"],
                    item["sim"],
                    item["words"],
                    detail_json,
                ),
            )

    conn.commit()
    conn.close()

    print("\n==========================================")
    print(
        f"処理完了: recognition_logs にも読手名(reader_name)を追加し、全 {len(sessions)} 個のセッションに格納しました！"
    )
    print("==========================================")


if __name__ == "__main__":
    migrate()