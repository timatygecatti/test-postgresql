
import psycopg2
from driver import PostgresDriver


def main():
    try:
        with PostgresDriver() as db:

            # Создаём таблицы, если их ещё нет
            db.create_tables()
            print("Таблицы готовы!")

            # Проверяем наличие пользователей
            users = db.read("users")

            if len(users) < 3:
                new_users = [
                    ("Тим", 28),
                    ("Дима", 25),
                    ("Вика", 21),
                ]

                for name, age in new_users:
                    db.add_user(name, age)

                print("Пользователи добавлены!")

            # Проверяем наличие заказов
            orders = db.read("orders")
            users = db.read("users")

            if len(orders) < 2 and users:
                db.add_order(users[0]["id"], 1500.50)
                db.add_order(users[1]["id"], 2500.00)

                print("Заказы добавлены!")

            # Выводим пользователей
            print("\nСписок пользователей:")
            for user in db.read("users"):
                print(user)

            # Выводим суммы заказов
            print("\nСумма заказов по пользователям:")
            for user in db.get_user_totals():
                print(
                    f"{user['name']} — "
                    f"{user['total_amount']}"
                )

    except psycopg2.Error as exc:
        print(f"Ошибка PostgreSQL: {exc}")

    except Exception as exc:
        print(f"Другая ошибка: {exc}")


if __name__ == "__main__":
    main()

