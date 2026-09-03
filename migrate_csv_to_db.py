import csv
from datetime import datetime, timedelta
import json
import os
import re
import sqlite3

# パス設定
BASE_DIR = r"C:\Users\misak\Desktop\karuta_vosk"
DB_PATH = os.path.join(BASE_DIR, "results", "karuta_results.db")
HISTORY_CSV = os.path.join(BASE_DIR, "results", "recognition_history.csv")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
PROCESSED_DIR = os.path.join(BASE_DIR, "recordings_processed")
CONVERTED_DIR = os.path.join(BASE_DIR, "converted_recordings")

# 切替基準日時
SWITCH_DATETIME = datetime(2026, 9, 3, 12, 30, 46)


def reset_and_init_db():
    """親・子テーブルの再構築および recognition_details への session_id カラム確保"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS recognition_logs")
    cursor.execute("DROP TABLE IF EXISTS test_sessions")

    # 1. 親テーブル
    cursor.execute(
        """
        CREATE TABLE test_sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_type TEXT,
            session_date TEXT,
            start_datetime TEXT,
            end_datetime TEXT,
            reader_name TEXT,
            gender TEXT,
            dictionary TEXT,
            total_cards INTEGER
        )
    """
    )

    # 2. 子テーブル
    cursor.execute(
        """
        CREATE TABLE recognition_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            card_order INTEGER,
            date_only TEXT,
            datetime TEXT,
            reader_name TEXT,
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
    """
    )

    # 3. recognition_details テーブルへの session_id カラムの確保
    cursor.execute("PRAGMA table_info(recognition_details)")
    detail_cols = [col[1] for col in cursor.fetchall()]
    if "session_id" not in detail_cols:
        cursor.execute(
            "ALTER TABLE recognition_details ADD COLUMN session_id INTEGER"
        )

    conn.commit()
    conn.close()


def parse_datetime(dt_str):
    if not dt_str:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%H:%M:%S.%f",
        "%H:%M:%S",
    ):
        try:
            return datetime.strptime(dt_str.strip(), fmt)
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


def load_detail_from_csv(base_filename, converted_fname=None):
    """【2026-09-03 12:30:46 未満用】個別CSVファイルからの読み込み"""
    target_csv_path = None
    target_csv_name = None

    if (
        converted_fname
        and converted_fname.strip()
        and converted_fname.strip() != "ー"
    ):
        match = re.search(r"\d{8}_\d{6}", converted_fname)
        if match:
            timestamp = match.group(0)
            if os.path.exists(RESULTS_DIR):
                for f in os.listdir(RESULTS_DIR):
                    if (
                        timestamp in f
                        and f.endswith(".csv")
                        and f != "recognition_history.csv"
                    ):
                        target_csv_name = f
                        target_csv_path = os.path.abspath(
                            os.path.join(RESULTS_DIR, f)
                        )
                        break

        if not target_csv_path:
            clean_c = (
                converted_fname.replace(".wav", "").replace(".csv", "").strip()
            )
            cand_path = os.path.abspath(
                os.path.join(RESULTS_DIR, f"{clean_c}.csv")
            )
            if os.path.exists(cand_path):
                target_csv_name = f"{clean_c}.csv"
                target_csv_path = cand_path

    if not target_csv_path and base_filename:
        clean_b = (
            base_filename.replace(".wav", "").replace(".csv", "").strip()
        )
        cand_path = os.path.abspath(
            os.path.join(RESULTS_DIR, f"{clean_b}.csv")
        )
        if os.path.exists(cand_path):
            target_csv_name = f"{clean_b}.csv"
            target_csv_path = cand_path

    if not target_csv_path or not os.path.exists(target_csv_path):
        fallback_name = target_csv_name or (
            f"{converted_fname}.csv"
            if converted_fname
            else f"{base_filename}.csv"
        )
        return fallback_name, "ー", "[]"

    logs = []
    try:
        with open(target_csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            next(reader, None)  # ヘッダー切り捨て
            for row in reader:
                if row:
                    logs.append(row)
    except Exception:
        pass

    return (
        target_csv_name,
        target_csv_path,
        json.dumps(logs, ensure_ascii=False),
    )


def get_processed_audio_path(file_name, converted_fname=None, row_num=0):
    if row_num >= 1748:
        if converted_fname:
            c_name = (
                converted_fname
                if converted_fname.endswith(".wav")
                else f"{converted_fname}.wav"
            )
            return os.path.abspath(os.path.join(CONVERTED_DIR, c_name))

        clean_base = file_name.replace(".wav", "").replace(".csv", "").strip()
        clean_base = re.sub(r"(_converted|_processed)$", "", clean_base)
        return os.path.abspath(
            os.path.join(CONVERTED_DIR, f"{clean_base}_converted.wav")
        )

    clean_base = file_name.replace(".wav", "").replace(".csv", "").strip()
    clean_base = re.sub(r"(_converted|_processed)$", "", clean_base)
    return os.path.abspath(
        os.path.join(PROCESSED_DIR, f"{clean_base}_processed.wav")
    )


def determine_reader_name(session_id, chunk):
    for item in chunk:
        if item.get("csv_reader") and item["csv_reader"] != "ー":
            return item["csv_reader"]

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
            if (
                not row
                or not row[0].strip()
                or "日時" in row[0]
                or "日付" in row[0]
            ):
                continue

            row_counter += 1
            dt = row[0].strip()
            gender, dict_val, csv_reader = "ー", "ー", "ー"
            converted_fname = None

            if row_counter >= 1748:
                csv_reader = row[1].strip() if len(row) > 1 and row[1].strip() else "ー"
                gender = row[2].strip() if len(row) > 2 and row[2].strip() else "ー"
                file_name = row[3].strip() if len(row) > 3 else ""
                converted_fname = row[4].strip() if len(row) > 4 else ""
                final_id = row[5].strip() if len(row) > 5 else "0"
                sim_str = row[6].replace("%", "").strip() if len(row) > 6 else "0"
                words = row[7].strip() if len(row) > 7 else "ー"

            elif row_counter == 1747:
                csv_reader = row[1].strip() if len(row) > 1 and row[1].strip() else "ー"
                gender = row[2].strip() if len(row) > 2 and row[2].strip() else "ー"
                file_name = row[3].strip() if len(row) > 3 else ""
                final_id = row[4].strip() if len(row) > 4 else "0"
                sim_str = row[5].replace("%", "").strip() if len(row) > 5 else "0"
                words = row[6].strip() if len(row) > 6 else "ー"

            elif row_counter >= 1440:
                gender = row[1].strip() if len(row) > 1 and row[1].strip() else "ー"
                dict_val = row[2].strip() if len(row) > 2 and row[2].strip() else "ー"
                file_name = row[3].strip() if len(row) > 3 else ""
                final_id = row[4].strip() if len(row) > 4 else "0"
                sim_str = row[5].replace("%", "").strip() if len(row) > 5 else "0"
                words = row[6].strip() if len(row) > 6 else "ー"

            else:
                file_name = row[1].strip() if len(row) > 1 else ""
                if len(row) >= 7:
                    final_id = row[4].strip()
                    sim_str = row[5].replace("%", "").strip()
                    words = row[6].strip()
                elif len(row) >= 5:
                    final_id = row[2].strip()
                    sim_str = row[3].replace("%", "").strip()
                    words = row[4].strip() if len(row) > 4 else "ー"
                else:
                    final_id, sim_str, words = "0", "0", "ー"

            try:
                sim_val = float(sim_str)
            except ValueError:
                sim_val = 0.0

            parsed_rows.append(
                {
                    "row_num": row_counter,
                    "dt_str": dt,
                    "dt_obj": parse_datetime(dt),
                    "date_only": extract_date_only(dt),
                    "csv_reader": csv_reader,
                    "gender": gender,
                    "dict": dict_val,
                    "file_name": file_name,
                    "converted_fname": converted_fname,
                    "final_id": final_id,
                    "sim": sim_val,
                    "words": words,
                }
            )

    # セッション構築（30秒判定）
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

    # DB書き込み開始
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. recognition_details を全取得
    cursor.execute(
        """
        SELECT id, log_time, word, card_id, current_score, max_score, similarity
        FROM recognition_details
        ORDER BY id ASC
    """
    )
    all_details = cursor.fetchall()

    # フラットな試行リスト
    flat_items = []
    for session_idx, chunk in enumerate(sessions, 1):
        for idx, item in enumerate(chunk, 1):
            item["session_idx"] = session_idx
            item["card_order"] = idx
            flat_items.append(item)

    # 2. セッションと試行ログの挿入・詳細ログとの結合
    for i, item in enumerate(flat_items):
        session_idx = item["session_idx"]
        chunk = sessions[session_idx - 1]

        # セッションの最初の場合、親テーブル (test_sessions) に書き込み
        if item["card_order"] == 1:
            first_item = chunk[0]
            last_item = chunk[-1]
            session_type = "100首セット" if len(chunk) >= 50 else "単体/一部試行"
            reader_name = determine_reader_name(session_idx, chunk)

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
            item["session_id"] = cursor.lastrowid
        else:
            item["session_id"] = flat_items[i - 1]["session_id"]

        session_id = item["session_id"]
        reader_name = determine_reader_name(session_idx, chunk)

        wav_name = (
            item["file_name"]
            if item["file_name"].endswith(".wav")
            else f"{item['file_name']}.wav"
        )
        raw_path = os.path.abspath(os.path.join(RECORDINGS_DIR, wav_name))
        if not os.path.exists(raw_path):
            alt = os.path.abspath(os.path.join(RECORDINGS_DIR, "raw", wav_name))
            raw_path = alt if os.path.exists(alt) else "ー"

        processed_path = get_processed_audio_path(
            wav_name, item["converted_fname"], item["row_num"]
        )

        item_dt = item["dt_obj"]

        # === 詳細ログ取得分岐 ===
        if item_dt and item_dt >= SWITCH_DATETIME:
            # ★あえて1個下にずらすために、1つ前の要素（i - 1）の時刻を基準にする★
            if (
                i > 0
                and flat_items[i - 1]["dt_obj"]
                and flat_items[i - 1]["session_idx"] == session_idx
            ):
                target_dt = flat_items[i - 1]["dt_obj"]
            else:
                target_dt = item_dt - timedelta(seconds=20)

            start_time = target_dt - timedelta(seconds=1)
            next_time = item_dt

            matched_logs = []
            matched_detail_ids = []

            for d_row in all_details:
                (
                    d_id,
                    log_time_str,
                    word,
                    card_id,
                    curr_score,
                    max_score,
                    sim,
                ) = d_row
                d_time = parse_datetime(log_time_str)

                if d_time:
                    if start_time.date() == d_time.date() or d_time.year == 1900:
                        d_datetime = datetime.combine(start_time.date(), d_time.time())
                    else:
                        d_datetime = d_time

                    if start_time <= d_datetime < next_time:
                        sim_str = (
                            f"{sim:.1f}%"
                            if isinstance(sim, (int, float))
                            else str(sim)
                        )
                        if not sim_str.endswith("%"):
                            sim_str += "%"

                        matched_logs.append(
                            [
                                str(log_time_str),
                                str(word),
                                str(card_id),
                                str(curr_score),
                                str(max_score),
                                sim_str,
                            ]
                        )
                        matched_detail_ids.append(d_id)

            csv_name = "DB_recognition_details"
            csv_path = "karuta_results.db"
            detail_json = json.dumps(matched_logs, ensure_ascii=False)

            cursor.execute(
                """
                INSERT INTO recognition_logs (
                    session_id, card_order, date_only, datetime, reader_name,
                    raw_audio_name, raw_audio_path, processed_audio_path, 
                    detail_csv_filename, detail_csv_path, final_id, 
                    final_similarity, recognized_words, detail_logs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    session_id,
                    item["card_order"],
                    item["date_only"],
                    item["dt_str"],
                    reader_name,
                    wav_name,
                    raw_path,
                    processed_path,
                    csv_name,
                    csv_path,
                    item["final_id"],
                    item["sim"],
                    item["words"],
                    detail_json,
                ),
            )

            if matched_detail_ids:
                placeholders = ",".join(["?"] * len(matched_detail_ids))
                cursor.execute(
                    f"""
                    UPDATE recognition_details
                    SET set_id = ?, session_id = ?
                    WHERE id IN ({placeholders})
                """,
                    [item["card_order"], session_id] + matched_detail_ids,
                )

        else:
            # 従来通り CSV ファイルから取得
            csv_name, csv_path, detail_json = load_detail_from_csv(
                item["file_name"], item["converted_fname"]
            )

            cursor.execute(
                """
                INSERT INTO recognition_logs (
                    session_id, card_order, date_only, datetime, reader_name,
                    raw_audio_name, raw_audio_path, processed_audio_path, 
                    detail_csv_filename, detail_csv_path, final_id, 
                    final_similarity, recognized_words, detail_logs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    session_id,
                    item["card_order"],
                    item["date_only"],
                    item["dt_str"],
                    reader_name,
                    wav_name,
                    raw_path,
                    processed_path,
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
    print("全処理が正常に完了しました:")
    print("・詳細ログの割り当てを意図的に1つ下へシフトし、上ズレを解消しました。")
    print("==========================================")


if __name__ == "__main__":
    migrate()