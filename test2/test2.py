from datetime import datetime


def show_message() -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"test2 is running at {now}")


if __name__ == "__main__":
    show_message()
