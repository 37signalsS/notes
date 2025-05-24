Скачиваем Termux из f-droid

Откройте Termux, запустите 

```sh
termux-change-repo
```

Нажмите кнопку ↓ и пробел, чтобы отметить все репозитории, затем нажмите Enter, чтобы перейти к следующему экрану.

Нажмите ↓, затем пробел, чтобы отметить «Зеркала, размещенные Albatross», нажмите Enter.

```sh
pkg install git -y
```

```sh
termux-setup-storage
```

```sh
cd storage/shared/
```

```sh
git config --global credential.helper store
```

```sh
git config --global user.email "misha-eliseyev@mail.ru"
```

```sh
git config --global user.name "37signalsS"
```

```sh
git clone https://<PERSONAL_ACCESS_TOKEN>@github.com/37signalsS/my-notes.git
```

```sh
pkg install cronie termux-services
```

```sh
exit
```

```sh
sv-enable crond
```

```sh
crontab -e 
```

```sh
*/1 * * * * ~/sync_repo.sh
```

Синхронизация каждую минуту

```sh
nano sync_repo.sh
```

```sh
#!/bin/bash

if [ -d storage/shared/my-notes ]; then
    cd storage/shared/my-notes
else
    echo "Директория storage/shared не существует."
    exit 1
fi

echo "Выполняю git pull..."
git pull || { echo "Ошибка при выполнении git pull"; exit 1; }

echo "Добавляю изменения в индекс..."
git add -A

if git diff --cached --quiet && git diff --quiet; then
    echo "Нет изменений для коммита."
else
    echo "Создаю коммит..."
    git commit -m "synched with android on $(date)"
fi

echo "Отправляю изменения в удалённый репозиторий..."
git push || { echo "Ошибка при выполнении git push"; exit 1; }

echo "Синхронизация завершена!"
```

```sh
chmod +x sync_repo.sh
```

```sh
git config --global --add safe.directory /storage/emulated/0/my-notes
```

```sh
./sync_repo.sh
```

Заставить Termux работать в фоновом режиме или синхронизировать по мере необходимости