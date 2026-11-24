import re
import shlex
from pathlib import Path


ACCENT = "1;96"
SECONDARY = "1;35"
SUCCESS = "1;92"
WARNING = "1;93"
DIFFICULTY_COLORS = {"Лёгкая": SUCCESS, "Средняя": WARNING, "Сложная": SECONDARY}
COMMAND = re.compile(r"(?<!\S)/(?:source|work|save|demo|status|reset|help|exit)\b")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


CHECK = re.compile(r"плагиат|уникальност|совпадени|^сравни\b|^проверь\b", re.I)
REVISE = re.compile(
    r"усложни|упрости|переделай|измени|добавь|убери|замени|адаптируй|перепиши|"
    r"сделай (?:их|его|её|проще|сложнее|легче|короче)", re.I,
)
GREETING = re.compile(
    r"(?:привет(?:ик)?|здравствуй(?:те)?|добрый (?:день|вечер)|что ты умеешь|помощь)[.!? ]*", re.I,
)
HELP = """Напиши «Составь задачи по SQL для начинающих». После ответа можно попросить
«Усложни среднюю задачу» или сохранить комплект командой /save файл.md.

Для проверки сначала добавь /source источник.txt (можно несколько раз).
Затем напиши «Проверь: текст работы» или добавь /work работа.txt и напиши «Проверь».

/demo     Проверить пример
/status   Показать файлы и текущую тему
/reset    Убрать прикреплённые файлы
/help     Показать подсказку
/exit     Выйти

Пути с пробелами заключай в кавычки."""


class TeacherChat:
    def __init__(self, generate_tasks, check_plagiarism, *, color=False):
        self.generate_tasks = generate_tasks
        self.check_plagiarism = check_plagiarism
        self.color = color
        self.work = None
        self.sources = []
        self.awaiting_text = False
        self.topic = None
        self.markdown = None

    def label(self, caption, code):
        return f"\033[{code}m{caption}\033[0m" if self.color else caption

    def answer(self, text, *, heading="Помощник", color=ACCENT, markdown=False, emphasis=None):
        text = CONTROL.sub("", text)
        if markdown:
            text = "\n".join(self.markdown_line(line) for line in text.splitlines())
        if not markdown:
            text = COMMAND.sub(lambda match: self.label(match[0], SECONDARY), text)
        if emphasis:
            text = text.replace(emphasis, self.label(emphasis, color), 1)
        print(f"\n  {self.label('◆ ' + heading, color)}")
        for line in text.splitlines():
            print(f"  {line}" if line else "")
        print()

    def markdown_line(self, line):
        if line.startswith("## "):
            title = line[3:]
            level = title.partition(" — ")[0]
            return self.label(title, DIFFICULTY_COLORS.get(level, ACCENT))
        if line.startswith(("# ", "### ")):
            return self.label(line.lstrip("# "), "1")
        return COMMAND.sub(lambda match: self.label(match[0], SECONDARY), line.replace("**Тема:**", "Тема:"))

    def send(self, text):
        if text.startswith("/"):
            return self.command(text)
        if GREETING.fullmatch(text):
            self.answer(HELP)
        elif CHECK.search(text) and not self.awaiting_text:
            self.compare(text.partition(":")[2].strip())
        elif self.awaiting_text:
            self.compare(text.partition(":")[2].strip() if CHECK.match(text) else text)
        else:
            revision = self.markdown is not None and REVISE.search(text) is not None
            topic = self.topic if revision else text
            self.answer("Готовлю задания…", color=SECONDARY)
            markdown = self.generate_tasks(
                topic,
                previous=self.markdown if revision else None,
                revision=text if revision else None,
            )
            self.topic, self.markdown = topic, markdown
            self.answer(markdown.rstrip() + "\n\nЧтобы сохранить, введи /save файл.md",
                        heading="Задания", markdown=True)
        return True

    def compare(self, body):
        if not self.sources:
            self.answer("Добавь источник командой /source источник.txt, затем повтори запрос.")
            return
        if not body and self.work:
            body = self.work.read_text(encoding="utf-8-sig")
        if not body:
            self.awaiting_text = True
            self.answer("Вставь текст следующим сообщением или добавь /work работа.txt и напиши «Проверь».")
            return
        self.report(body, self.sources)
        self.awaiting_text = False

    def report(self, body, sources):
        verdict, unique, matched, total = self.check_plagiarism(body, sources)
        percentage = f"{unique:.1f}%"
        self.answer(f"{verdict}\nУникальность относительно источников — {percentage}."
                    f"\nВ совпадениях — {matched} из {total} слов.",
                    heading="Проверка текста", color=WARNING if matched else SUCCESS, emphasis=percentage)

    def command(self, text):
        command, *args = shlex.split(text)
        if command in {"/help", "/reset", "/exit", "/demo", "/status"}:
            if args:
                raise ValueError(f"Команда {command} не принимает аргументы.")
            if command == "/exit":
                return False
            if command == "/reset":
                self.work = None
                self.sources.clear()
                self.awaiting_text = False
                self.answer("Файлы убраны.")
            elif command == "/demo":
                folder = Path(__file__).resolve().parent
                work = folder / "test_work.txt"
                source = folder / "test_source.txt"
                self.report(work.read_text(encoding="utf-8-sig"), [source])
            elif command == "/status":
                work = str(self.work) if self.work else "файл не добавлен"
                sources = ", ".join(map(str, self.sources)) or "файлы не добавлены"
                topic = self.topic or "задания ещё не созданы"
                self.answer(f"Работа — {work}\nИсточники — {sources}\nТема заданий — {topic}",
                            heading="Текущая сессия")
            else:
                self.answer(HELP)
        elif command in {"/source", "/work", "/save"}:
            if len(args) != 1:
                raise ValueError(f"Укажи один путь после {command}. Пути с пробелами заключай в кавычки.")
            path = Path(args[0]).expanduser()
            if command == "/save":
                self.save(path)
            elif not path.is_file():
                raise ValueError(f"Файл не найден — {path}")
            elif command == "/work":
                self.work = path
                self.answer(f"Работа прикреплена — {path.name}.")
            else:
                if path not in self.sources:
                    self.sources.append(path)
                self.answer(f"Источник добавлен — {path.name}.")
        else:
            self.answer("Введи /help, чтобы увидеть команды.")
        return True

    def save(self, path):
        if self.markdown is None:
            raise ValueError("Сначала попроси сгенерировать задачи.")
        if path.suffix.lower() != ".md":
            raise ValueError("Выбери имя файла с расширением .md.")
        with path.open("x", encoding="utf-8") as output:
            output.write(self.markdown)
        self.answer(f"Задания сохранены в {path}.", heading="Файл сохранён", color=SUCCESS)


def launch(generate_tasks, check_plagiarism):
    import os
    import sys

    try:
        import readline
    except ImportError:
        pass

    color = sys.stdout.isatty() and not os.getenv("NO_COLOR") and os.getenv("TERM") != "dumb"
    chat = TeacherChat(generate_tasks, check_plagiarism, color=color)
    title = "  Помощник преподавателя  "
    rule = "─" * len(title)
    print(chat.label(f"\n  ╭{rule}╮\n  │{title}│\n  ╰{rule}╯", ACCENT))
    chat.answer(HELP)
    while True:
        try:
            text = input("  Вы › ").strip()
            if text and not chat.send(text):
                break
        except (EOFError, KeyboardInterrupt):
            print()
            break
        except FileExistsError:
            chat.answer("Файл уже существует. Выбери другое имя.", heading="Сохранение", color=WARNING)
        except (OSError, ValueError) as error:
            chat.answer(str(error), heading="Ошибка", color=WARNING)
    return 0
