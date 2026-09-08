# Конструкции для написания скриптов на Bash

## Определения

- **Шебанг (Shebang)** — первая строка скрипта (`#!`), указывающая путь к интерпретатору (например, `#!/usr/bin/env bash`).
- **Управляющие конструкции (Control Structures)** — блоки кода для реализации логики: условия (`if`, `case`, `select`) и циклы (`for`, `while`, `until`).
- **Арифметическое вычисление (Arithmetic Evaluation)** — конструкции `(( ... ))` для выполнения операций и `$(( ... ))` для получения результата. Работают только с целыми числами.
- **Подстановка команд (Command Substitution)** — синтаксис `$(команда)`, позволяющий использовать вывод команды как значение.
- **Область видимости (Scope)** — контекст доступности переменных. В Bash переменные глобальны по умолчанию; `local` ограничивает их внутри функции.
- **Код возврата (Exit Code)** — число (0–255), возвращаемое командой. **0** — успех, остальные — ошибки.
- **Parameter Expansion (Расширение параметров)** — встроенный синтаксис `${...}` для манипуляции переменными без внешних утилит: значения по умолчанию, извлечение подстроки, замена шаблонов, проверка на пустоту.
- **Process Substitution (Подстановка процесса)** — синтаксис `<(команда)` и `>(команда)`, передающий вывод команды как временный файловый дескриптор или FIFO. Позволяет использовать `diff`, `comm` между потоками без промежуточных файлов.
- **Here Document / Here String** — способы передачи многострочного (`<<EOF`) или однострочного (`<<<"строка"`) ввода команде напрямую из скрипта.
- **Subshell (Подоболочка)** — дочерний процесс оболочки, создаваемый при группировке `( команды )`, конвейере `|`, подстановке процессов `$( ... )` или арифметической оценке `(( ... ))`. Изменения переменных и `cd` внутри subshell не влияют на родителя.
- **Strict Mode (Строгий режим)** — набор флагов `set -Eeuo pipefail` и `IFS=$'\n\t'`, минимизирующих скрытые ошибки за счет немедленного выхода при ошибках, обработки неопределенных переменных и проброса ошибок в конвейерах.
- **POSIX Shell** — стандартизированная оболочка (`sh`), определенная в POSIX.1-2017. Bash совместим с POSIX, но добавляет расширения (массивы, `[[ ]]`, `(( ))`, `coproc`).
- **Nameref** — ссылка на переменную (`declare -n ref=VAR`), позволяющая изменять значение целевой переменной косвенно. Удобно для универсальных функций.
- **Compound Command (Составная команда)** — конструкция, объединяющая несколько команд: `( list )` (subshell), `{ list; }` (группа в текущем shell), `(( expression ))` (арифметика), `[[ expression ]]` (условие).
- **Word Splitting (Разбиение на слова)** — этап обработки, на котором результат подстановок делится на отдельные аргументы по символам в `$IFS`. При отсутствии кавычек пустые значения и пробелы теряются.
- **Pathname Expansion (Подстановка имён файлов / Globbing)** — раскрытие wildcard-символов (`*`, `?`, `[abc]`) в реальные пути файловой системы.

---

## Базовые концепции

### 1. Условные операторы и тесты

#### Конструкция `if / elif / else`

```bash
# Строковое сравнение и числовые операции в одном условии
if [[ -z "$VAR" ]]; then
    echo "VAR пуста"
elif [[ "$VAR" =~ ^[0-9]+$ ]]; then
    echo "VAR содержит только цифры"
elif (( VAR > 10 )); then
    echo "Число больше 10"
else
    echo "Условие не выполнено"
fi
```

**Важно:** внутри `[[ ... ]]` кавычки вокруг переменной необязательны, но литералы с пробелами лучше брать в кавычки. Операторы `&&` и `||` внутри `[[ ... ]]` работают как логическое И/ИЛИ:

```bash
if [[ -f "$FILE" && -r "$FILE" ]]; then
    echo "Файл существует и доступен для чтения"
fi

if [[ -d "$DIR" || -L "$DIR" ]]; then
    echo "Это директория или симлинк"
fi
```

#### Сравнение механизмов тестирования

| Инструмент | Синтаксис | Назначение | Особенности |
| :--- | :--- | :--- | :--- |
| **Расширенный тест** | `[[ ... ]]` | Строки, файлы, логика | Поддерживает Regex (`=~`) и Globbing. Не требует кавычек для переменных. |
| **Арифметический** | `(( ... ))` | Числа | Поддерживает C-подобные операторы: `>`, `<`, `==`, `!=`, `>=`, `<=`. |
| **Устаревший тест** | `[ ... ]` | Совместимость | Команда `test`. Требует экранирования и операторов `-eq`, `-gt`. |

**Таблица операторов сравнения:**

| Тип сравнения | `[[ ... ]]` (Строки) | `(( ... ))` (Числа) | `[ ... ]` (Числа) |
| :--- | :--- | :--- | :--- |
| Равно | `==` | `==` | `-eq` |
| Не равно | `!=` | `!=` | `-ne` |
| Больше | `>` | `>` | `-gt` |
| Меньше | `<` | `<` | `-lt` |
| Больше или равно | `>=` | `>=` | `-ge` |

**Таблица тестов файлов (работает в `[[ ... ]]` и `[ ... ]`):**

| Тест | `[[ ... ]]` | `[ ... ]` | Описание |
| :--- | :--- | :--- | :--- |
| Существует | `-e "$f"` | `-e "$f"` | Любой тип файла |
| Обычный файл | `-f "$f"` | `-f "$f"` | Не директория и не устройство |
| Директория | `-d "$d"` | `-d "$d"` | Является директорией |
| Символическая ссылка | `-L "$l"` | `-L "$l"` | Является symlink |
| Читаемый | `-r "$f"` | `-r "$f"` | Есть права на чтение |
| Записываемый | `-w "$f"` | `-w "$f"` | Есть права на запись |
| Исполняемый | `-x "$f"` | `-x "$f"` | Есть права на выполнение |
| Не пустой | `-s "$f"` | `-s "$f"` | Размер больше 0 |
| Новее | `"$f1" -nt "$f2"` | `"$f1" -nt "$f2"` | mtime `$f1` новее `$f2` |
| Старше | `"$f1" -ot "$f2"` | `"$f1" -ot "$f2"` | mtime `$f1` старше `$f2` |
| Один inode | `"$f1" -ef "$f2"` | `"$f1" -ef "$f2"` | Одинаковый файл (жесткая ссылка) |

#### Оператор `case` (Паттерны)

```bash
# Проверка расширения файла
case "$FILE_EXT" in
    jpg|jpeg|png) echo "Изображение" ;;
    txt|md)       echo "Текст" ;;
    *)            echo "Неизвестный формат"; exit 1 ;;
esac
```

**Особенности Bash 4+:** операторы `;;&` (продолжить проверку следующего паттерна) и `;&` (выполнить следующий блок без повторной проверки):

```bash
case "$SVC" in
    nginx|httpd)   echo "Веб-сервер" ;;&
    *)             echo "Неизвестный сервис" ;;
esac
```

#### Интерактивное меню (`select`)

```bash
PS3="Выберите действие: "
select opt in "Статус" "Перезапуск" "Выход"; do
    case $opt in
        "Статус")   systemctl status nginx; break ;;
        "Перезапуск") systemctl restart nginx; break ;;
        "Выход")    exit 0 ;;
        *)          echo "Неверный выбор" ;;
    esac
done
```

### 2. Циклы и итерация

#### Цикл `for`

```bash
# Итерация по элементам массива
for item in "${ARRAY[@]}"; do
    echo "Элемент: $item"
done

# Итерация по диапазону (Brace Expansion)
for i in {1..5}; do
    echo "Шаг $i"
done

# C-подобный синтаксис (Bash 3.0+)
for ((i=0; i<10; i++)); do
    printf "Пинг %d\n" "$i"
done
```

#### Цикл `while` и `until`

```bash
# while — пока условие истинно
while read -r line; do
    [[ -z "$line" ]] && continue
    process "$line"
done < <(journalctl -u nginx --no-pager)

# until — пока условие ложно (инверсный while)
until systemctl is-active --quiet prometheus; do
    echo "Ожидание запуска Prometheus..."
    sleep 2
done
```

#### Управление циклами

- **`break [n]`**: выход из цикла (или из `n` вложенных циклов).
- **`continue [n]`**: переход к следующей итерации.
- **`continue 2`**: полезно во вложенных циклах для перехода на внешний уровень.

### 3. Функции

Функции должны быть определены до вызова. Bash поддерживает два синтаксиса: `name()` и `function name`.

```bash
# Два эквивалентных синтаксиса
do_backup() {
    local src="$1"
    local dest="${2:-/backup}"
    [[ -d "$src" ]] || return 1
    tar -czf "$dest/backup.tar.gz" "$src"
}

function restore {
    local src="$1"
    local dest="${2:-/restore}"
    tar -xzf "$src" -C "$dest"
}
```

**Аргументы и специальные переменные:**

| Переменная | Значение |
| :--- | :--- |
| `$1`, `$2`, ... `$9` | Позиционные аргументы |
| `$#` | Количество аргументов |
| `$@` | Все аргументы как отдельные слова |
| `$*` | Все аргументы как одно слово |
| `$FUNCNAME` | Имя текущей функции (стек вызовов) |
| `$BASH_SOURCE` | Путь к файлу, где определена функция |
| `$0` | Имя скрипта или функции (в контексте `source`) |

**Возврат значений:**

```bash
# Через return (число 0–255)
is_valid() {
    [[ -f "$1" ]]
    return $?  # 0 = true, 1 = false
}

# Через echo/stdout (любые данные)
get_config() {
    echo "/etc/nginx/nginx.conf"
}

# Использование
if is_valid "/etc/passwd"; then
    echo "Файл валиден"
fi
CONFIG=$(get_config)
```

**`local` с массивами:**

```bash
process_services() {
    local -a services=("$@")   # Все аргументы как элементы массива
    local -i count=0           # Целое число
    for svc in "${services[@]}"; do
        echo "Checking: $svc"
        ((count++))
    done
    echo "Обработано: $count"
}
```

**Nameref (`declare -n`) — косвенная ссылка на переменную:**

```bash
apply_limit() {
    local -n target=$1   # target теперь указывает на переменную, имя которой в $1
    local value=$2
    target=$(( target > value ? value : target ))
}

ulimit_n=1024
apply_limit ulimit_n 512
echo "$ulimit_n"  # → 512
```

**Trap RETURN — выполнение кода при выходе из функции:**

```bash
audit_fn() {
    trap 'echo "[AUDIT] Выход из $FUNCNAME (строка $LINENO), статус: $?"' RETURN
    echo "Работа функции..."
    return 0
}
```

### 4. Группировка команд и операторы управления

#### Виды группировки

| Синтаксис | Область | Применение |
| :--- | :--- | :--- |
| `( list )` | Subshell | Изоляция переменных, параллельный запуск через `&` |
| `{ list; }` | Текущий shell | Группировка для `;`, `&&`, `||`, перенаправлений |
| `(( expr ))` | Текущий shell | Арифметическое вычисление как команда |
| `$(( expr ))` | Подстановка | Результат арифметики как строка |
| `[[ expr ]]` | Текущий shell | Условие (не команда, а ключевое слово) |

**Пример группировки:**

```bash
# В текущем shell: переменная сохраняется
{ count=0; echo "start"; } && echo "count=$count"

# В subshell: переменная теряется
( count=0; echo "start" ); echo "count=$count"  # → count=

# Арифметика в конвейере (subshell)
echo "5" | (( sum += $1 )); echo "$sum"  # sum не изменится

# Правильно: process substitution
while read -r n; do (( sum += n )); done < <(echo "5")
```

#### Операторы управления выполнением

- **`;`** — последовательное выполнение (игнорирует код возврата).
- **`&&`** — выполнить следующую команду только если предыдущая завершилась успехом (`exit 0`).
- **`||`** — выполнить следующую команду только если предыдущая завершилась с ошибкой (`exit != 0`).
- **`&`** — запустить команду в фоне (асинхронно).

```bash
# Типичный DevOps-паттерн: проверка и запуск
[[ -f /etc/nginx/nginx.conf ]] && nginx -t && systemctl reload nginx

# Обработка ошибки: fallback
pgrep -x prometheus >/dev/null || systemctl start prometheus
```

### 5. Parameter Expansion (Расширение параметров)

Parameter Expansion выполняется на этапе парсинга, до запуска команд, и позволяет манипулировать строками без `sed`, `awk` или `cut`.

#### Значение по умолчанию и проверки

| Синтаксис | Поведение | Пример |
| :--- | :--- | :--- |
| `${VAR:-default}` | Если `VAR` пуста или не определена — вернуть `default` | `echo "${PORT:-80}"` |
| `${VAR:=default}` | Как `:-`, но ещё присвоить `default` в `VAR` | `: "${LOG_DIR:=/var/log}"` |
| `${VAR:?error}` | Если `VAR` пуста — вывести `error` в stderr и выйти | `: "${DB_HOST:?DB_HOST не задан}"` |
| `${VAR:+alt}` | Если `VAR` не пуста — вернуть `alt` | `echo "${DEBUG:+[DEBUG]}"` |

#### Подстрока и замена шаблонов

| Синтаксис | Поведение | Пример |
| :--- | :--- | :--- |
| `${VAR:offset:length}` | Подстрока с позиции `offset` (с 0), длиной `length` | `echo "${HOST:0:8}"` |
| `${VAR%pattern}` | Удалить shortest совпадение `pattern` с конца | `echo "${FILE%.log}"` |
| `${VAR%%pattern}` | Удалить longest совпадение `pattern` с конца | `echo "${PATH%%:*}"` |
| `${VAR#pattern}` | Удалить shortest совпадение `pattern` с начала | `echo "${DIR#/}"` |
| `${VAR##pattern}` | Удалить longest совпадение `pattern` с начала | `echo "${PATH##*/}"` |
| `${VAR/pattern/repl}` | Заменить первое совпадение `pattern` на `repl` | `echo "${URL/http/https}"` |
| `${VAR//pattern/repl}` | Заменить все совпадения | `echo "${PATH//:/ }"` |

#### Имена переменных и массивы

| Синтаксис | Поведение |
| :--- | :--- |
| `${!prefix*}` | Имена переменных, начинающихся с `prefix` |
| `${!name[@]}` | Элементы массива `name` (как отдельные слова) |
| `${!array[@]}` | Индексы массива `array` |

```bash
# Практический пример: безопасное получение значения
read -r MAX_CONNECTIONS < /etc/myapp/conf
: "${MAX_CONNECTIONS:=100}"

# Извлечение имени хоста из URL
url="https://monitoring.example.com:9090"
host="${url#*//}"      # monitoring.example.com:9090
host="${host%%:*}"     # monitoring.example.com

# Замена всех двоеточий на пробелы
IFS=' ' read -ra ADDRS <<< "${PATH//:/ }"
```

### 6. Подстановка процессов (Process Substitution)

Подстановка процессов передаёт вывод команды как файловый дескриптор. В отличие от `$(command)`, результат можно передать команде, ожидающей файл.

```bash
# Сравнение двух сортированных списков без временных файлов
diff <(sort /etc/hosts.allow) <(sort /etc/hosts.deny)

# Чтение вывода команды в цикл (сохраняет переменные в текущем shell)
while read -r user; do
    echo "User: $user"
done < <(cut -d: -f1 /etc/passwd)

# Двусторонний обмен: tee пишет в subshell и в файл одновременно
tee >(wc -l > /tmp/count.txt) < /var/log/syslog | grep "ERROR"
```

**Механика:** Bash создаёт `/dev/fd/N` (или именованный канал/FIFO) и передаёт путь как аргумент команде. Команда читает/пишет как из обычного файла.

### 7. Here Document / Here String

#### Here Document (`<<`)

Многострочный ввод, ограниченный маркером (обычно `EOF`):

```bash
# Передача конфига без кавычек: переменные раскрываются
cat <<EOF > /tmp/config.cfg
host = "${DB_HOST:-localhost}"
port = "${DB_PORT:-5432}"
pool_size = 20
EOF

# Кавычки вокруг маркера (<<'EOF'): переменные НЕ раскрываются
cat <<'EOF' > /etc/nginx/conf.d/default.conf
server {
    listen 80;
    server_name ${SERVER_NAME};
}
EOF
```

#### Here String (`<<<`)

Однострочный ввод:

```bash
grep "pattern" <<< "$VAR"
md5sum <<< "password"
```

### 8. POSIX sh совместимость и Bash-расширения

| Возможность | POSIX sh | Bash |
| :--- | :--- | :--- |
| Массивы | Нет | Есть (`"${arr[@]}"`) |
| Ассоциативные массивы | Нет | Есть (`declare -A`) |
| `[[ ... ]]` | Нет | Есть |
| `(( ... ))` | Нет | Есть |
| `coproc` | Нет | Есть |
| `source` | Нет (только `.`) | Есть |
| `BASH_ENV` | Нет (`ENV`) | Есть |
| `shopt` | Нет | Есть |
| `function` | Нет | Есть |

> **SRE-заметка:** Для максимальной переносимости используйте `#!/bin/sh` и синтаксис `[ ... ]`, `for f in *`, `. file.sh`. Для сложной логики, массивов и regex указывайте `#!/usr/bin/env bash`.

---

## Практические сценарии

### Шаблон надежного скрипта (Strict Mode)

Используйте этот заголовок для предотвращения скрытых ошибок:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
# -E: наследование ловушек (traps) функциями
# -e: немедленный выход при ошибке команды
# -u: ошибка при обращении к неопределенной переменной
# -o pipefail: код ошибки конвейера = коду последнего упавшего звена

trap 'echo "Ошибка в строке $LINENO"; cleanup' ERR

cleanup() {
    # Код для очистки временных файлов
    exit
}
```

### POSIX-совместимый шаблон (`/bin/sh`)

Для скриптов, которые должны работать на Alpine Linux, BusyBox или BSD без Bash:

```bash
#!/bin/sh
set -eu

# POSIX не имеет pipefail; проверяем каждый этап конвейера отдельно
set -- $(df . | tail -n 1 | awk '{print $5}')
usage=${1%\%}
echo "Использование: $usage"
```

### Безопасное чтение файла построчно

Использование `IFS=` сохраняет пробелы в начале и конце строк.

```bash
while IFS= read -r line; do
    [[ -z "$line" || "$line" == #* ]] && continue
    echo "Обработка: $line"
done < "data.txt"
```

### Чтение всего файла в массив (`mapfile`)

Эффективнее, чем циклы `while`, для небольших и средних файлов.

```bash
mapfile -t SERVICES < <(systemctl list-unit-files --type=service --state=enabled --no-pager --no-legend | awk '{print $1}')
echo "Первая служба: ${SERVICES[0]}"
```

### Обработка аргументов (`getopts`)

```bash
while getopts "vf:" opt; do
    case $opt in
        v) verbose=true ;;
        f) file="$OPTARG" ;;
        *) exit 1 ;;
    esac
done
shift $((OPTIND - 1))
```

### Валидация конфигурационного файла

Проверка существования, прав и синтаксиса перед загрузкой:

```bash
CONFIG="/etc/nginx/nginx.conf"

if [[ ! -f "$CONFIG" ]]; then
    echo "Файл не найден: $CONFIG" >&2; exit 1
fi

if [[ ! -r "$CONFIG" ]]; then
    echo "Нет прав на чтение: $CONFIG" >&2; exit 1
fi

# Проверка: содержит ли файл обязательную директиву
if ! grep -q "^worker_processes" "$CONFIG"; then
    echo "Отсутствует worker_processes" >&2; exit 1
fi

echo "Конфиг валиден"
```

### Парсинг логов без потери переменных

Правильный способ подсчета строк в логе — через process substitution, а не конвейер:

```bash
count=0
while IFS= read -r line; do
    ((count++))
done < <(grep -c "ERROR" /var/log/syslog || true)
echo "ERROR строк: $count"
```

### Управление сервисами через `select`

Админское меню для управления systemd-сервисами:

```bash
SERVICES=(nginx prometheus node_exporter)

PS3="Выберите сервис: "
select SVC in "${SERVICES[@]}" "Выход"; do
    [[ "$SVC" == "Выход" ]] && exit 0
    [[ -z "$SVC" ]] && continue

    echo "1) Статус  2) Перезапуск  3) Логи"
    read -r action

    case $action in
        1) systemctl status "$SVC" ;;
        2) systemctl restart "$SVC" ;;
        3) journalctl -u "$SVC" --no-pager -n 50 ;;
        *) echo "Неверный выбор" ;;
    esac
    break
done
```

### Генерация systemd-юнита через Here Document

Создание временного юнита для запуска скрипта:

```bash
cat <<EOF > /etc/systemd/system/monitor-temp.service
[Unit]
Description=Temperature monitor
After=network.target

[Service]
Type=simple
ExecStart=/opt/scripts/monitor-temp.sh
Restart=on-failure
RestartSec=5
Environment=LOG_LEVEL=info

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now monitor-temp.service
```

### Сравнение конфигов через Process Substitution

Без создания временных файлов:

```bash
diff <(grep -v '^#' /etc/hosts.allow | sort) \
     <(grep -v '^#' /etc/hosts.deny | sort)
```

### Ожидание готовности сервиса (Health Check)

Цикл `until` с проверкой порта:

```bash
HOST="10.0.0.10"
PORT=9100

until (echo > /dev/tcp/$HOST/$PORT) 2>/dev/null; do
    echo "Ожидание $HOST:$PORT..."
    sleep 2
done

echo "Сервис доступен"
```

Для портативных скриптов (без `/dev/tcp`):

```bash
until curl -sf "http://$HOST:$PORT/metrics" >/dev/null; do
    sleep 2
done
```

### Ротация логов по размеру

```bash
LOG_DIR="/var/log/myapp"
MAX_SIZE=$((10 * 1024 * 1024))  # 10 MB

for log in "$LOG_DIR"/*.log; do
    [[ -f "$log" ]] || continue
    size=$(stat -c%s "$log")
    if (( size > MAX_SIZE )); then
        mv "$log" "${log}.1"
        gzip "${log}.1"
        echo "Ротация: $log"
    fi
done
```

### Удаление старых файлов

```bash
DAYS=30
while IFS= read -r file; do
    echo "Удаление: $file"
    rm -f "$file"
done < <(find /var/backups -type f -mtime +$DAYS)
```

### Mass rename через цикл

```bash
i=1
for f in /opt/data/*.csv; do
    new=$(printf "/opt/data/report_%03d.csv" "$i")
    mv "$f" "$new"
    ((i++))
done
```

### Функция с Nameref для универсальной обработки конфигов

```bash
apply_defaults() {
    local -n cfg=$1
    cfg=("${cfg[@]/#/default_}")  # Префикс к каждому элементу
}

declare -a NGINX=(worker_processes worker_connections)
apply_defaults NGINX
printf '%s\n' "${NGINX[@]}"
# → default_worker_processes
# → default_worker_connections
```

### Long options без `getopts` (ручная обработка)

```bash
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)   CONFIG_FILE="$2"; shift 2 ;;
        --verbose)  VERBOSE=1; shift ;;
        --help)     usage; exit 0 ;;
        --)         shift; break ;;
        -*)         echo "Неизвестный флаг: $1" >&2; exit 1 ;;
        *)          break ;;
    esac
done
```

### Функция с аудитом через `trap RETURN`

```bash
audited_deploy() {
    trap 'echo "[AUDIT] $FUNCNAME завершилась в строке $LINENO, статус: $?"' RETURN
    echo "Деплой приложения..."
    sleep 1
    return 0
}

audited_deploy
# → [AUDIT] audited_deploy завершилась в строке 3, статус: 0
```

---

## Дополнительная информация

### Builtin, keyword и external commands

| Тип | Примеры | Особенности |
| :--- | :--- | :--- |
| **Builtin** | `echo`, `cd`, `read`, `printf`, `test`, `eval`, `set`, `export` | Выполняются внутри процесса Shell. Не создают дочерний процесс. |
| **Keyword** | `if`, `then`, `else`, `for`, `while`, `function`, `[[`, `((`, `{`, `}` | Парсятся самой оболочкой. Не имеют PID. |
| **External** | `grep`, `sed`, `awk`, `curl`, `systemctl`, `tar` | Отдельные исполняемые файлы. Создают дочерний процесс. |

> **SRE-заметка:** `time` — reserved word в Bash (встроенный), но часто есть и как external `/usr/bin/time`. Для измерения времени внешних команд используйте `/usr/bin/time -v`.

### Группировка команд

- **`( команды )`**: Выполнение в **Subshell**. Переменные, `cd` и `ulimit` внутри не влияют на основной скрипт. Удобно для параллельного запуска через `&`.
- **`{ команды; }`**: Выполнение в текущей оболочке. Требует `;` перед закрывающей скобкой. Используется для группировки перед `|`, `&&`, `||`, `>`.
- **`(( выражение ))`**: Арифметическое вычисление как команда. Возвращает 0, если результат != 0.
- **`$(( выражение ))`**: Подстановка результата арифметики как строки.
- **`[[ выражение ]]`**: Условное выражение как ключевое слово. Не создаёт subshell.

```bash
# Subshell: параллельный запуск двух команд
( cd /opt/scripts && ./backup.sh ) &
( cd /opt/scripts && ./cleanup.sh ) &
wait  # дождаться обоих
```

### `shopt` — управление поведением Shell

Часто используемые опции, влияющие на конструкции:

| Опция | Эффект |
| :--- | :--- |
| `shopt -s lastpipe` | Последняя команда в pipeline выполняется в текущем shell (неинтерактивные скрипты) |
| `shopt -s nullglob` | `*` без совпадений расширяется в пустоту (а не в себя) |
| `shopt -s failglob` | `*` без совпадений вызывает ошибку |
| `shopt -s extglob` | Включает расширенные glob-паттерны `@(foo|bar)` |
| `shopt -s globstar` | `**` рекурсивно обходит директории |
| `shopt -s nocaseglob` | Globbing без учета регистра |

```bash
shopt -s nullglob
for f in /tmp/*.log; do
    echo "Найден: $f"
done
shopt -u nullglob  # вернуть как было
```

### POSIX sh vs Bash: ключевые различия

| Возможность | POSIX sh | Bash |
| :--- | :--- | :--- |
| Массивы | Нет | Есть (`"${arr[@]}"`) |
| Ассоциативные массивы | Нет | Есть (`declare -A`) |
| `[[ ... ]]` | Нет | Есть |
| `(( ... ))` | Нет | Есть |
| `coproc` | Нет | Есть |
| `source` | Нет (только `.`) | Есть |
| `BASH_ENV` | Нет (`ENV`) | Есть |
| `shopt` | Нет | Есть |
| `function` | Нет | Есть |
| `local` | Нет | Есть |
| `<<<` (here-string) | Нет | Есть |
| `&>>` (добавление в stderr+stdout) | Нет | Есть |

> **SRE-заметка:** Для максимальной переносимости используйте `#!/bin/sh` и синтаксис `[ ... ]`, `for f in *`, `. file.sh`. Для сложной логики, массивов и regex указывайте `#!/usr/bin/env bash`. На Debian/Ubuntu `/bin/sh` — это `dash`, что заметно быстрее для простых скриптов.

### `case` с `;;&` и `;&` (Bash 4.0+)

```bash
case "$MODE" in
    start)   echo "Запуск" ;;&   # продолжить проверку следующего паттерна
    restart) echo "Перезапуск" ;;&
    stop)    echo "Остановка" ;;
    *)       echo "Неверный режим"; exit 1 ;;
esac
```

### Оптимизация циклов

| Метод | Скорость | Примечание |
| :--- | :--- | :--- |
| `for i in {1..1000}` | Высокая | Brace Expansion выполняется в момент парсинга |
| `for ((i=0; i<1000; i++))` | Высокая | C-подобный цикл внутри Shell |
| `seq 1 1000 \| while read` | Низкая | Создает subshell и внешний процесс `seq` |
| `for i in $(seq 1 1000)` | Низкая | Command substitution + word splitting |

### См. также

- [Логика выполнения команд](./bash_command_execution.md) — порядок подстановок, жизненный цикл команды.
- [Логика потоков данных](./operators_and_pipelines.md) — конвейеры, `coproc`, `xargs`, `lastpipe`.
- [Переменные оболочки](./shell_variables.md) — типы переменных, области видимости, `mapfile`, `declare -n`.
- [Коды возврата](./exit_codes.md) — логика завершения и обработка ошибок.
- [Сигналы и trap](./bash_signal_traps.md) — перехват сигналов и очистка ресурсов.
- [Экранирование (Quoting)](./quoting.md) — защита данных от интерпретации Shell.
