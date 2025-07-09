## Установка и настройка Termux

Скачиваем Termux из F-Droid.

Откройте Termux, запустите:
```sh
termux-change-repo
```

Нажмите `↓` и `пробел`, чтобы отметить все репозитории, затем нажмите `Enter`.
Далее, отметьте «Зеркала, размещенные Albatross» и нажмите `Enter`.

Установим `git`:
```sh
pkg install git -y
```

Предоставим доступ к хранилищу:
```sh
termux-setup-storage
```

Перейдем в общую папку:
```sh
cd storage/shared/
```

## Настройка Git

Настроим Git для сохранения учетных данных и идентификации пользователя:
```sh
git config --global credential.helper store
git config --global user.email "misha-eliseyev@mail.ru"
git config --global user.name "37signalsS"
```

Клонируем репозиторий с заметками:
```sh
git clone https://<PERSONAL_ACCESS_TOKEN>@github.com/37signalsS/my-notes.git
```

## Настройка автоматической синхронизации

Установим `cronie` для выполнения задач по расписанию:
```sh
pkg install cronie termux-services
sv-enable crond
```

Создадим задачу для `cron`:
```sh
crontab -e
```

Добавим строку для ежеминутной синхронизации:
```sh
*/1 * * * * ~/sync_repo.sh
```

Создадим и наполним скрипт синхронизации:
```sh
nano sync_repo.sh
```

Содержимое скрипта `sync_repo.sh`:
```sh
#!/bin/bash

# Переходим в директорию с репозиторием
if [ -d storage/shared/my-notes ]; then
    cd storage/shared/my-notes
else
    echo "Директория storage/shared/my-notes не существует." >&2
    exit 1
fi

echo "Выполняю git pull..."
git pull || { echo "Ошибка при выполнении git pull" >&2; exit 1; }

echo "Добавляю изменения в индекс..."
git add -A

# Проверяем, есть ли изменения для коммита
if git diff --cached --quiet && git diff --quiet; then
    echo "Нет изменений для коммита."
else
    echo "Создаю коммит..."
    git commit -m "synched with android on $(date)"
fi

echo "Отправляю изменения в удалённый репозиторий..."
git push || { echo "Ошибка при выполнении git push" >&2; exit 1; }

echo "Синхронизация завершена!"
```

Сделаем скрипт исполняемым:
```sh
chmod +x sync_repo.sh
```

Добавим директорию в список безопасных для Git:
```sh
git config --global --add safe.directory /storage/emulated/0/my-notes
```

Запустим скрипт для первоначальной синхронизации:
```sh
./sync_repo.sh
```

> **Примечание:** Чтобы Termux работал в фоновом режиме, может потребоваться отключить для него оптимизацию батареи в настройках Android.
