import sqlite3


def get_processed_files():
    conn = sqlite3.connect("knowledge_base.db")
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT source_file FROM facts;")
    rows = cursor.fetchall()
    print("Обработанные файлы в базе данных:\n")
    for i, row in enumerate(rows, 1):
        print(f"{i}. {row[0]}")
    conn.close()


if __name__ == "__main__":
    get_processed_files()
