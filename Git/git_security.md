### Верификация коммитов (GPG)

Вы можете подписывать свои коммиты с помощью GPG-ключа для подтверждения их подлинности.
[Инструкция на Habr: Верификация коммитов GPG](https://habr.com/ru/articles/754128/)

### Шифрование файлов (Git Crypt)

1.  **Инициализация:** `git-crypt init`
2.  **Добавление GPG ключа:** `git-crypt add-gpg-user "ваш@email.com"`
3.  **Настройка шифрования:** Создайте файл `.gitattributes` и укажите, какие файлы шифровать (например, `secret.json filter=git-crypt diff=git-crypt`).
4.  **Блокировка/разблокировка:** `git-crypt lock` / `git-crypt unlock`.
