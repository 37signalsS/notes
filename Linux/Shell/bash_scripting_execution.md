# Выполнение скриптов в Bash: Subshell, Source и Shabang

## Определения

- **Bash-скрипт** — текстовый файл с последовательностью команд для интерпретатора Bash.
- **Интерпретатор** — программа, выполняющая команды скрипта. Bash читает и исполняет код построчно, в отличие от компилируемых языков (C++, Go).
- **Контекст выполнения (Execution Context)** — текущее состояние оболочки, включая переменные окружения, функции, алиасы и рабочую директорию.
- **Subshell (Подоболочка)** — дочерний процесс интерпретатора. Создается через системный вызов `fork()`.
- **Source (Внедрение)** — выполнение команд скрипта непосредственно в текущем процессе без создания дочерней оболочки.
- **Shebang (`#!`)** — специальная последовательность символов в начале файла, указывающая ядру путь к программе-интерпретатору.
- **`fork()`** — системный вызов Linux, создающий дочерний процесс как копию родителя. Ребенок получает собственный PID, но копию адресного пространства (технология copy-on-write откладывает физическое копирование до первого изменения).
- **`exec()`** — семейство системных вызовов (`execl`, `execv`, `execle`, `execve` и др.), заменяющих образ текущего процесса новым. PID сохраняется, но адресное пространство и дескрипторы перезаписываются.
- **PID (Process ID)** — уникальный числовой идентификатор процесса в ядре Linux.
- **PPID (Parent PID)** — PID процесса-родителя, создавшего данный процесс через `fork()`.
- **Job Control** — механизм Bash для управления фоновыми (`&`), приостановленными (`^Z`) и управляемыми задачами внутри сессии терминала.
- **Process Group** — группа процессов, обслуживающих один канал управления терминалом. Используется для отправки сигналов всем задачам сразу.
- **Session** — логическая группа process groups, создаваемая через `setsid()`. Отвязывает процессы от управляющего терминала.
- **Exit Status (Код возврата)** — целое число от 0 до 255, возвращаемое процессом при завершении. `0` означает успех, остальные значения — ошибку или сигнал.
- **POSIX Shell** — стандартизированная оболочка (`sh`), определяемая IEEE Std 1003.1. Bash является совместимым расширением, но не всегда POSIX-совместим.

---

## Базовые концепции

### Способы запуска скрипта

#### 1. Запуск как исполняемого файла (Subshell)
Создается новый процесс. Окружение родителя копируется, но изменения внутри скрипта **не возвращаются** родителю.

- **Условия**: наличие прав на исполнение (`chmod +x script.sh`) и корректного Shebang.
- **Запуск**: `./script.sh` или `/path/to/script.sh`.

#### 2. Прямой вызов интерпретатора
Аналогичен первому способу, но игнорирует Shebang внутри файла.

- **Запуск**: `bash script.sh`.
- **Особенности**: Позволяет запускать скрипты без прав на исполнение.

#### 3. Выполнение в текущем контексте (Source)
Новый процесс **не создается**. Все `export`, `alias` и `cd` внутри скрипта изменяют текущую сессию пользователя.

- **Синтаксис**: `source script.sh` или `. script.sh`.
- **Применение**: Загрузка конфигураций, инициализация виртуальных окружений.

#### 4. Замена текущего процесса (Exec)
Текущая оболочка завершается, и её место занимает новая программа с тем же PID.

- **Запуск**: `exec ./script.sh`.
- **Особенности**: Используется в обертках (wrappers) для корректного проброса сигналов и экономии ресурсов.

---

### Жизненный цикл выполнения: fork → copy → exec

При запуске внешнего скрипта ядро и оболочка выполняют три ключевых шага:

1. **`fork()`**: Bash создает дочерний процесс. Получает копию всех переменных окружения, дескрипторов файлов и памяти родителя (технология copy-on-write откладывает физическое копирование до первого изменения).
2. **Обработка в дочернем процессе**: Дочерний Bash читает Shebang, определяет интерпретатор и подготавливает окружение.
3. **`exec()`**: Если скрипт запускается как внешний файл, дочерний процесс заменяет свой образ на интерпретатор (например, `/bin/bash`). PID сохраняется, но всё адресное пространство оболочки Bash теряется.

**Для `source`:** `fork()` не вызывается. Команды выполняются в текущем процессе, PID не меняется.

**Для `exec`:** `fork()` может быть вызван перед `exec()`, а может и нет (например, при замене текущей оболочки). В любом случае, текущий процесс теряет код Bash.

```bash
# Демонстрация PID/PPID
echo "Родитель: PID=$$ PPID=$PPID"
bash -c 'echo "Subshell: PID=$$ PPID=$PPID"'
source <(echo 'echo "Source: PID=$$ PPID=$PPID"')
```

> **SRE-заметка:** `fork()` в Linux использует copy-on-write (COW). Физическая память копируется только при записи. Это делает создание subshell дешёвым, но при большом `RSS` процесса (например, JVM с 4 ГБ heap) `fork()` может занять несколько миллисекунд и привести к кратковременному давлению на память.

---

### Наследование переменных окружения

При `fork()` дочерний процесс получает **копию** таблицы окружения родителя. Это означает:

- Изменения `export VAR=val` в дочернем процессе **не влияют** на родителя.
- Изменения в родителе после `fork()` **не влияют** на уже запущенных детей.
- `env -i` запускает процесс с полностью пустым окружением (даже `PATH` отсутствует).

```bash
# Родитель
export MY_VAR="parent"
bash -c 'echo "Child sees: $MY_VAR"'
# → Child sees: parent

# Изменение в ребенке
bash -c 'export MY_VAR="child"'
echo "Parent still sees: $MY_VAR"
# → Parent still sees: parent
```

---

### Наследование файловых дескрипторов

Дочерний процесс наследует **все** открытые файловые дескрипторы родителя (stdin/stdout/stderr + любые пользовательские fd).

```bash
# Открываем fd 3 для записи в лог
exec 3>>/var/log/myscript.log

# Дочерний процесс унаследует fd 3
bash -c 'echo "from child" >&3'

exec 3>&-
```

**Важно:** При `exec()` дескрипторы **остаются открытыми** по умолчанию. Флаг `O_CLOEXEC` при открытии автоматически закрывает дескриптор при `exec`. Это критично для безопасности: если дочерний процесс унаследовал открытый fd на `/etc/shadow`, утечка данных возможна.

---

### Exit Status и распространение кодов возврата

- Каждый процесс возвращает целое число 0–255 через `exit()` или возврат из `main()`.
- `0` = успех. `1–125` = пользовательская ошибка. `126` = команда найдена, но не исполняема. `127` = команда не найдена. `128+N` = завершение сигналом N.
- В subshell `$?` возвращает код последней команды внутри subshell, но код subshell'а при выходе через `exit` переопределяет его.

```bash
bash -c 'exit 42'
echo "Subshell exit: $?"
# → Subshell exit: 42
```

**Для `source`:** `$?` возвращает код последней команды в sourced-скрипте.

**Для `exec`:** Код возврата переходит к программе, которая заменяет shell. Если она завершится с кодом 0, родитель увидит успех.

---

### Job Control и управление фоновыми задачами

Bash может управлять несколькими активными задачами внутри одной сессии. В **неинтерактивных скриптах** job control отключен по умолчанию (`set +m`).

```bash
# Включение job control в скрипте
set -m

# Запуск фоновой задачи
sleep 300 &
JOB_PID=$!

# Список задач
jobs -l

# Возврат в передний план
fg %1

# Отправка сигнала конкретной задаче
kill -TERM %1
```

> **Важно:** В скриптах `jobs` работает только если job control включен (`set -m`). В `systemd`-юнитах или cron job control недоступен.

Для детального обхода задач, сигналов и `disown` см. [Обработка сигналов и trap](./bash_signal_traps.md).

---

### `BASH_ENV` для неинтерактивных скриптов

В неинтерактивных скриптах (cron, systemd, Ansible, GitLab CI) не читаются `~/.bashrc` и `~/.profile`. Для инициализации окружения используйте `BASH_ENV`:

```bash
# systemd-юнит
[Service]
Type=oneshot
Environment=BASH_ENV=/home/deploy/.bash_env
ExecStart=/opt/scripts/backup.sh

# /home/deploy/.bash_env
export PATH="/usr/local/bin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export LANG="en_US.UTF-8"
source /home/deploy/.bash_aliases
```

**Правила:**
- `BASH_ENV` не наследуется автоматически. Каждая новая оболочка читает его заново.
- Значение переменной не раскрывается: если `BASH_ENV=$HOME/.bash_env`, Bash ищет именно файл с именем `$HOME/.bash_env`, а не раскрывает путь.
- В `dash`/`sh` аналогичная переменная — `ENV`.

---

### `source` vs `.` (dot command)

Оба варианта идентичны по поведению в Bash. Различия появляются в POSIX-совместимых оболочках:

- **Bash**: `source file` и `. file` полностью эквивалентны.
- **POSIX `/bin/sh` (dash, ash)**: поддерживается только `. file`. `source` может быть недоступен.

```bash
# POSIX-портативный вариант
. ./config.env

# Bash-specific (удобно для чтения)
source ./config.env
```

---

### POSIX sh vs Bash: портативность shebang

| Shebang | Совместимость | Особенности |
| :--- | :--- | :--- |
| `#!/bin/sh` | Максимальная (POSIX) | Используйте для переносимых скриптов. На Debian/Ubuntu `/bin/sh` = `dash` (быстрее). |
| `#!/bin/bash` | Только Bash | Позволяет расширения: массивы, `[[ ]]`, `(( ))`, `coproc`. |
| `#!/usr/bin/env bash` | Только Bash, но переносимо | `env` ищет `bash` в `$PATH`. Работает на macOS, NixOS, BusyBox с bash. |
| `#!/usr/bin/env python3` | Python 3+ | Переносимо, медленнее (двойной `fork` через `env`). |

**Security note:** Shebang позволяет только **один аргумент**. `#!/bin/bash -e` работает, но `#!/bin/bash -e -u` трактуется как часть имени файла.

---

### `nice`, `renice`, `ionice` для управления ресурсами

Скрипты, запущенные по умолчанию, получают одинаковый приоритет CPU и I/O. Для фоновых задач снижайте приоритет, чтобы не конкурировать с интерактивными процессами:

```bash
# Запуск с пониженным приоритетом CPU (nice = +10)
nice -n 10 /opt/scripts/report.sh

# Запуск с минимальным приоритетом I/O (idle class)
ionice -c3 /opt/scripts/backup.sh

# Комбинация: низкий CPU + низкий I/O
nice -n 19 ionice -c3 /opt/scripts/batch.sh

# Изменение приоритета уже запущенного процесса
renice -n 10 -p 12345
ionice -c2 -n7 -p 12345
```

---

### `timeout` — ограничение времени выполнения

Утилита `timeout` (coreutils) отправляет сигнал после истечения лимита:

```bash
# Простой таймаут 10 секунд
timeout 10s curl -s http://unresponsive-service:8080/health

# SIGTERM через 10с, затем SIGKILL через 5с (short form: -k)
timeout --kill-after=5s 10s long-running-task

# Сокращённый синтаксис с -k: тот же эффект
timeout -k 5s 30s ./long_task.sh || echo "timed out: $?"

# Проверка кода возврата
exit_code=$?
if [ $exit_code -eq 124 ]; then
    echo "Команда превысила таймаут (SIGTERM)"
elif [ $exit_code -eq 137 ]; then
    echo "Команда убита SIGKILL (не обработала SIGTERM)"
fi
```

---

### `env` — запуск с контролируемым окружением

```bash
# Полностью пустое окружение
env -i PATH=/usr/bin:/bin HOME=$HOME /usr/bin/myapp

# Исключение конкретной переменной
env -u SECRET_KEY /opt/scripts/deploy.sh

# Смена директории без cd
env -C /opt/app /usr/bin/myapp
```

---

### `script` — запись сессии для аудита

```bash
# Запись всего вывода команды с таймстампами
script -q -c "/opt/scripts/deploy.sh" /var/log/deploy-$(date +%Y%m%d).log

# Продолжение записи в существующий файл
script -a -q -c "/opt/scripts/backup.sh" /var/log/backup.log

# Воспроизведение записи
scriptreplay /var/log/deploy-20240906.log
```

---

### Удаленное выполнение через SSH

```bash
# Передача скрипта по SSH и выполнение
ssh user@host 'bash -s' < local_script.sh

# С явной передачей переменных
ssh user@host bash <<'REMOTE_EOF'
export APP_ENV=production
export CONFIG_FILE=/etc/app/prod.conf
/opt/app/start.sh
REMOTE_EOF
```

---

### `wait` — ожидание фоновых процессов

```bash
# Запуск параллельных задач
python3 task1.py &
PID1=$!
python3 task2.py &
PID2=$!

# Ожидание конкретного процесса
wait $PID1
echo "Task 1 finished with $?"

# Ожидание всех фоновых процессов
wait
echo "All tasks finished"

# Ожидание первого завершившегося (Bash 4.3+)
wait -n
echo "First task done: $?"
```

---

## Практические сценарии

### Subshell против Source: Влияние на среду
`setup_env.sh`:
```bash
#!/bin/bash
export APP_PORT=8080
cd /var/www
```

**Результат:**
```bash
# Subshell — текущий Shell не изменился
$ ./setup_env.sh
$ echo $APP_PORT # (пусто)

# Source — настройки применились к текущей сессии
$ source ./setup_env.sh
$ echo $APP_PORT # 8080
$ pwd           # /var/www
```

---

### Фоновый запуск и игнорирование SIGHUP
При закрытии терминала все дочерние процессы получают сигнал `SIGHUP` и завершаются.

- **`nohup`**: Перехватывает `SIGHUP`. Вывод по умолчанию пишется в `nohup.out`.
  `nohup ./long_task.sh &`
- **`systemd-run`**: Современная альтернатива. Запускает скрипт как временный системный сервис.
  `systemd-run --user ./long_task.sh`
- **`disown`**: Удаляет уже запущенный фоновый процесс из списка задач оболочки.

---

### Активация виртуального окружения Python
Скрипты активации (например, `venv`) обязаны запускаться через `source`, так как их задача — изменить переменную `$PATH` в текущей сессии.
```bash
source .venv/bin/activate
# Команда 'python' теперь указывает на интерпретатор внутри .venv
```

---

### `BASH_ENV` в cron-задаче

```bash
# /etc/cron.d/backup
SHELL=/bin/bash
BASH_ENV=/home/deploy/.bash_env
PATH=/usr/local/bin:/usr/bin:/bin

0 2 * * * deploy /opt/scripts/backup.sh >> /var/log/backup.log 2>&1
```

`/home/deploy/.bash_env`:
```bash
export PATH="/usr/local/bin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export LANG="en_US.UTF-8"
source /home/deploy/.bash_aliases
```

**Валидация:**
```bash
# Тест вручную
env -i SHELL=/bin/bash HOME=/home/deploy BASH_ENV=/home/deploy/.bash_env /bin/bash -c 'echo $PATH; type deploy-tool'
```

---

### PID/PPID для отладки иерархии процессов

```bash
#!/bin/bash
echo "Main script: PID=$$ PPID=$PPID"

# Subshell
( echo "Subshell: PID=$$ PPID=$PPID" )

# Source (PID не меняется)
source <(echo 'echo "Sourced: PID=$$ PPID=$PPID"')

# Exec (PID сохраняется, но процесс заменяется)
exec bash -c 'echo "Exec bash: PID=$$ PPID=$PPID"'
```

---

### `env -i` для чистого запуска в CI/CD

```bash
# Гарантированный чистый запуск без inherited variables
env -i \
  PATH=/usr/local/bin:/usr/bin:/bin \
  HOME=/tmp \
  /opt/scripts/deploy.sh
```

---

### `nice`/`ionice` для фоновых batch-задач

```bash
# Фоновый парсинг логов с низким приоритетом
nice -n 19 ionice -c3 /opt/scripts/parse-logs.sh > /var/log/parse.log 2>&1 &

# Валидация приоритетов
ps -o pid,ni,pri,comm -p $!
```

---

### `timeout` в CI/CD pipeline

```bash
#!/bin/bash
set -euo pipefail

# Запуск с автоматическим прерыванием
timeout --kill-after=30s 5m /opt/scripts/migration.sh
status=$?

if [ $status -eq 124 ]; then
    echo "Migration timed out (SIGTERM)"
    exit 1
elif [ $status -eq 137 ]; then
    echo "Migration killed (SIGKILL after SIGTERM)"
    exit 1
fi
```

---

### `script` для аудита сессий деплоя

```bash
# Запись всего backup-операции
script -q -c "/opt/scripts/backup.sh -full" /var/log/deploy/deploy-$(date +%Y%m%d-%H%M%S).log

# Просмотр replay
scriptreplay /var/log/deploy/deploy-20240906-143022.log
```

---

### Удаленное выполнение через SSH

```bash
# Передача и выполнение локального скрипта на удаленном хосте
ssh deploy@web01 'bash -s' < ./restart-app.sh

# С явной передачей переменных
ssh deploy@web01 bash <<'REMOTE_EOF'
export APP_ENV=production
export CONFIG_FILE=/etc/app/prod.conf
/opt/app/restart.sh
REMOTE_EOF
```

---

### `exec` в wrapper-скрипте для systemd

```ini
# /etc/systemd/system/webapp.service
[Service]
Type=exec
ExecStart=/opt/webapp/start.sh
Environment=BASH_ENV=/opt/webapp/.env
KillSignal=SIGUSR1
TimeoutStopSec=15
```

`/opt/webapp/start.sh`:
```bash
#!/bin/bash
# exec заменяет shell, сигналы доходят напрямую в приложение
exec /opt/webapp/bin/server --config /etc/webapp/conf.d
```

---

### `set -m` для управления фоновыми задачами в скрипте

```bash
#!/bin/bash
set -m  # Включить job control

download_file() {
    curl -s -o "$1" "$2"
    echo "Downloaded: $1"
}

download_file "https://speed.hetzner.de/100MB.bin" &
JOB1=$!
download_file "https://speed.hetzner.de/100MB.bin" &
JOB2=$!

# Ожидание любого
wait -n
echo "At least one download finished"

# Ожидание всех
wait
echo "All downloads finished"
```

---

### SUID-скрипты: безопасность и ограничения

Ядро Linux **игнорирует** SUID-бит на скриптах (shebang-файлы) из-за race condition. Это стандартное поведение:

```bash
# НЕ работает на Linux:
chmod u+s /usr/local/bin/admin-task.sh
# Ядро запустит /bin/sh, а не task.sh с EUID=root
```

**Правильные альтернативы:**
```bash
# 1. sudoers (NOPASSWD для конкретной команды)
# /etc/sudoers.d/admin
deploy ALL=(root) NOPASSWD: /usr/local/bin/admin-task.sh

# 2. setcap на бинарном wrapper
sudo setcap cap_net_bind_service=+ep /usr/bin/myapp

# 3. systemd-сервис с RootDirectoryStartOnly
```

---

## Best Practices

1. **Всегда используйте `set -euo pipefail`** в production-скриптах для раннего прерывания при ошибках.
2. **Используйте `#!/usr/bin/env bash`** для портативности между Linux, macOS и NixOS.
3. **Используйте `exec` в entrypoint/wrapper-скриптах** для корректного проброса сигналов (особенно в контейнерах и systemd).
4. **Настраивайте `BASH_ENV`** для неинтерактивных окружений (cron, systemd, Ansible, CI/CD).
5. **Используйте `timeout`** для всех внешних вызовов в production-скриптах для предотвращения зависаний.
6. **Используйте `command -v` вместо `which`**: `command -v` является POSIX-совместимым builtin.
7. **Избегайте `cd` в subshell**: используйте явные пути или `(cd /dir && cmd)`.
8. **Используйте `wait` после `&`** для предотвращения зомби-процессов и корректного сбора exit code.
9. **Не делайте скрипты SUID**: используйте `sudo`, `pkexec` или `setcap` на бинарных wrapper'ах.
10. **Используйте `script`** для записи аудита деплоев и troubleshooting.

---

## Ограничения и edge cases

1. **`fork()`** создает копию процесса с copy-on-write. При большом `RSS` (например, JVM) может занять десятки миллисекунд.
2. **`exec()`** полностью заменяет образ процесса. Все `trap` теряются. Используйте обертку-скрипт для cleanup.
3. **Shebang ограничен одним аргументом.** `#!/bin/bash -e` работает, но `#!/bin/bash -e -u` трактуется как часть имени файла.
4. **SUID-скрипты игнорируются ядром Linux** по соображениям безопасности (race condition при чтении shebang).
5. **`source` не определен в POSIX** `/bin/sh` на некоторых системах (BusyBox, dash). Используйте `.` для портативности.
6. **`BASH_ENV`** не читается при явном вызове `sh -c`, если переменная не установлена в окружении вызывающей оболочки.
7. **`lastpipe`** работает только в неинтерактивных скриптах, не влияет на `-e` и недоступен в `zsh`/`dash`.
8. **`set -m`** (job control) несовместим с некоторыми POSIX-скриптами и может нарушать pipe-пайплайны.
9. **`timeout`** отправляет SIGTERM, затем SIGKILL через `--kill-after` (short form: `-k`). Процесс не может перехватить SIGKILL.
10. **`env -i`** удаляет даже `PATH`. Если `PATH` не указан явно, команды по абсолютным путям или builtin'ы.

---

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Permission denied` при запуске скрипта | Нет бита исполнения или неверный shebang | `chmod +x script.sh`; проверьте первую строку `#!/bin/bash` |
| `command not found` в cron | Отсутствует окружение (PATH, переменные) | Укажите полный путь или настройте `BASH_ENV` |
| Переменная пустая после `source` | Файл не найден или ошибка внутри sourced-скрипта | Проверьте `set -e` и путь к файлу |
| Переменная пустая в цикле `while` | Цикл в subshell (конвейер `|`) | `shopt -s lastpipe` или `done < <(cmd)` |
| Фоновый процесс завершается при logout | Не хватает `nohup`, `disown` или `systemd-run` | Используйте `disown -h %1` или `systemd-run --user --scope` |
| `exec` не передает сигналы | Entrypoint-shell перехватывает сигнал | Добавьте `exec` перед основной командой |
| SUID-скрипт не работает | Ядро Linux игнорирует SUID на shebang-файлах | Используйте `sudoers`, `setcap` или systemd-сервис |
| `timeout` не убивает процесс | Процесс игнорирует SIGTERM | Добавьте `--kill-after` или используйте `pkill -P $PID` |
| `BASH_ENV` игнорируется | Переменная не экспортирована или файл не существует | Проверьте `echo $BASH_ENV` и права на файл |
| `set -m` ломает пайплайн | Job control меняет обработку сигналов в pipe | Отключите `set +m` или используйте POSIX-совместимый код |
| `source` не работает в `/bin/sh` | Используется Bash-синтаксис в POSIX-оболочке | Замените `source` на `.` или используйте `#!/bin/bash` |
| `env -i` падает с `command not found` | `PATH` не указан | Добавьте `PATH=/usr/bin:/bin` в `env -i` |

---

## Дополнительная информация

### Механизм Shebang и портативность

Когда ОС видит `#!`, она запускает указанный путь и передает ему путь к скрипту как аргумент.

**Тонкие моменты:**
- **Прямой вызов**: Если запустить скрипт как `bash script.sh`, строка с Shebang игнорируется и воспринимается как обычный комментарий.
- **Пустые строки**: Shebang **обязательно** должен быть на первой строке (строка 0), без пробелов перед `#!`.
- **Windows-формат (CRLF)**: Если скрипт сохранен в Windows, в конце строки Shebang будет невидимый символ `\r`. Ядро попытается запустить `/bin/bash\r`, что приведет к ошибке `No such file or directory`.
- **Портативность**: Путь `/bin/bash` может отличаться (напр. в macOS или NixOS). Использование `#!/usr/bin/env bash` более надежно, так как `env` ищет Bash в `$PATH`.

### Видимость переменных в конвейерах (`|`)
Каждое звено конвейера в Bash выполняется в **отдельном Subshell**.

```bash
count=0
ls | while read line; do
    ((count++))
done
echo $count # Выведет 0, так как изменения были в подоболочке
```

**Решение**: Использование подстановки процессов или `shopt -s lastpipe`.
```bash
count=0
while read line; do ((count++)); done < <(ls)
echo $count # Выведет корректное число
```

### Файлы инициализации и режимы Shell

| Режим сессии | Читаемые файлы | Примечание |
| :--- | :--- | :--- |
| **Interactive Login** | `/etc/profile`, `~/.bash_profile`, `~/.profile` | При входе по SSH. |
| **Interactive Non-login**| `~/.bashrc` | Каждое новое окно терминала. |
| **Non-interactive** | `$BASH_ENV` | При запуске скриптов. |

### Строгий режим (Strict Mode)
Для повышения надежности всегда добавляйте в начало скрипта:
```bash
#!/bin/bash
set -euo pipefail
IFS=$'\n\t'
```
- **`-e` (errexit)**: Выход при любой ошибке команды.
- **`-u` (nounset)**: Ошибка при обращении к необъявленной переменной.
- **`-o pipefail`**: Конвейер вернет ошибку, если упала любая его часть (а не только последняя).
- **`IFS`**: Настройка разделителей для защиты от некорректного Word Splitting в циклах.

### См. также
- [Обработка сигналов и trap](./bash_signal_traps.md) — SIGHUP, graceful shutdown и взаимодействие trap с exec.
- [Перенаправление ввода-вывода](./io_redirection.md) — наследование файловых дескрипторов и exec с fd.
- [Операторы потоков и конвейеры](./operators_and_pipelines.md) — subshell в пайплайнах и lastpipe.
