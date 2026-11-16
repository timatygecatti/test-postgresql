import psycopg2
from driver import PostgresDriver


def main():
    try:
        with PostgresDriver() as db:

            # Удаляем пользователя с ID 5
            deleted = db.delete(
                "users",
                {"id": 5}
            )

            print(f"Удалено записей: {deleted}")

            # Проверяем, остался ли пользователь
            user = db.read_one(
                "users",
                where={"id": 5}
            )

            if user is None:
                print("Пользователь успешно удалён!")
            else:
                print("Пользователь всё ещё существует:", user)

    except psycopg2.Error as exc:
        print(f"Ошибка PostgreSQL: {exc}")

    except Exception as exc:
        print(f"Другая ошибка: {exc}")


if __name__ == "__main__":
    main()