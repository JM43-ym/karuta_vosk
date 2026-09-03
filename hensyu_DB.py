import sqlite3

DB_PATH = "results/karuta_results.db"


def update_reader_names():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. 全セッションを取得
    cursor.execute(
        "SELECT session_id, start_datetime FROM test_sessions ORDER BY session_id"
    )
    sessions = cursor.fetchall()

    updated_count = 0

    for session_id, start_dt in sessions:
        # このセッションに属するファイル名の一覧を取得
        cursor.execute(
            "SELECT raw_audio_name FROM recognition_logs WHERE session_id = ?",
            (session_id,),
        )
        rows = cursor.fetchall()

        # セッション内のファイル名を1つの文字列として結合（キーワード検知用）
        all_filenames = " ".join([r[0].lower() for r in rows if r[0]])

        # --- 読手の判定ロジック ---
        # 優先度1: 130〜132セット目
        if 130 <= session_id <= 132:
            reader = "芹野(serino)専任読手"

        # 優先度2: ファイル名に yoshi
        elif "yoshi" in all_filenames:
            reader = "吉川( yoshikawa )専任読手"

        elif "yosi" in all_filenames:
            reader = "吉川( yoshikawa )専任読手"

        # 優先度3: ファイル名に hito
        elif "hito" in all_filenames:
            reader = "廣瀨"

        # 優先度4: その他
        else:
            reader = "稲葉(inaba)専任読手"

        # 親テーブル (test_sessions) を更新
        cursor.execute(
            "UPDATE test_sessions SET reader_name = ? WHERE session_id = ?",
            (reader, session_id),
        )
        updated_count += 1

    conn.commit()
    conn.close()

    print(
        f"処理完了: 合計 {updated_count} 件のセットに対して読手名を一括更新しました！"
    )


if __name__ == "__main__":
    update_reader_names()