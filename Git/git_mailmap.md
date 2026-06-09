# Git Mailmap — маппинг авторов

## Определения

**`.mailmap`** — файл для маппинга имён и email-адресов авторов на канонические идентичности в истории Git.

**Mailmap** — механизм Git для объединения записей об авторах, которые используют разные имена или email-адреса.

---

## Базовые концепции

### Назначение

Файл `.mailmap` маппит имена и email авторов на канонические идентичности. Git использует его для вывода `git log`, `git shortlog`, `git blame`.

### Проблемы, которые решает mailmap

* **Смена email:** Автор сменил работу и использует новый корпоративный email
* **Разные написания имени:** `Jane Dev`, `Jane Developer`, `J. Developer`
* **Личный и рабочий email:** Коммиты с разных адресов считаются разными авторами
* **Опечатки:** Случайные ошибки в имени или email при настройке Git

### Формат файла

**Формат строки:** `Proper Name <proper@email.com> Commit Name <commit@email.com>`

```text
# Маппинг старого email на новый
Jane Developer <jane@company.com> <jane@oldcompany.com>

# Стандартизация написания имени
Jane Developer <jane@company.com> Jane Dev <jane@company.com>

# Исправление обоих
Jane Developer <jane@company.com> <janed@personal.com>
Jane Developer <jane@company.com> J Developer <janed@personal.com>

# Маппинг только по имени (без email)
Jane Developer <jane@company.com> Jane Dev
```

### Особенности

* **Инструменты:** `git shortlog -sn`, `git log`, `git blame` используют mailmap для агрегации коммитов
* **GitHub:** Графики контрибьюторов GitHub не используют `.mailmap` — дубликаты сохраняются в веб-интерфейсе
* **Расположение:** По умолчанию `.mailmap` в корне репозитория; путь настраивается через `mailmap.file`

---

## Практические сценарии

### Сценарий 1: Объединение коммитов после смены email

Автор перешёл из старой компании в новую:

```text
# .mailmap
Ivan Petrov <ivan@newcompany.com> <ivan@oldcompany.com>
Ivan Petrov <ivan@newcompany.com> <i.petrov@personal.com>
```

### Сценарий 2: Стандартизация написания имён

Разные разработчики по-разному писали одно имя:

```text
# .mailmap
Alexander Ivanov <alex@company.com> Alex Ivanov <alex@company.com>
Alexander Ivanov <alex@company.com> A. Ivanov <alex@company.com>
Alexander Ivanov <alex@company.com> alex.ivanov <alex@company.com>
```

### Сценарий 3: Исправление опечаток

```text
# .mailmap
Maria Sidorova <maria@company.com> Maria Sidorova <maira@company.com>
Maria Sidorova <maria@company.com> Maria Sidorova <maria@compnay.com>
```

### Сценарий 4: Настройка кастомного пути к mailmap

```bash
# Использовать файл в другой директории
git config mailmap.file .github/mailmap

# Глобально для всех репозиториев
git config --global mailmap.file ~/.git-mailmap
```

### Сценарий 5: Проверка результата

```bash
# Статистика авторов с учётом mailmap
git shortlog -sn --all

# Log с каноническими именами
git log --use-mailmap --format="%an <%ae>" | sort | uniq -c

# Blame с правильными именами
git blame --use-mailmap file.txt
```

### Сценарий 6: Генерация mailmap из существующей истории

```bash
# Получить список всех авторов
git log --format='%aN <%aE>' | sort -u

# Создать начальный .mailmap
git log --format='%aN <%aE>' | sort -u > .mailmap.template
```

---

## Дополнительная информация

### Официальные ресурсы

* **Документация Git:** [git-scm.com/docs/gitmailmap](https://git-scm.com/docs/gitmailmap)
* **Проверка mailmap:** [git-scm.com/docs/git-check-mailmap](https://git-scm.com/docs/git-check-mailmap)

### Связанные темы

Обзор специальных файлов в [git_special_files_overview.md](./git_special_files_overview.md).
