import sqlite3


def clean_database():
    conn = sqlite3.connect("knowledge_base.db")
    cursor = conn.cursor()

    cursor.execute("UPDATE facts SET geography = 'Неизвестно' WHERE LOWER(geography) = 'неизвестно';")

    abroad_variants = (
        "Китай",
        "КНР",
        "Чили",
        "Австралия",
        "Казахстан",
        "США",
        "Канада",
        "Новая Каледония",
        "Вьетнам",
        "Весь мир",
    )
    cursor.execute(f"UPDATE facts SET geography = 'Зарубежье' WHERE geography IN {abroad_variants};")

    cursor.execute("UPDATE facts SET geography = 'Зарубежье' WHERE geography LIKE '%Зарубежье%';")
    cursor.execute("UPDATE facts SET geography = 'РФ' WHERE geography LIKE '%РФ%';")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    clean_database()
