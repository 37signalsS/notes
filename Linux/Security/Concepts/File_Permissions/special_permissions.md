# Специальные права доступа в Linux: SUID, SGID, Sticky Bit

## Определения

**Специальные права (Special Permissions)** — расширенный набор битов доступа (`SUID`, `SGID`, `Sticky Bit`), которые дополняют стандартную модель DAC (Discretionary Access Control). Они изменяют стандартное поведение ядра при выполнении исполняемых файлов и работе с директориями, позволяя временно изменять идентификаторы пользователей или защищать файлы от удаления.

## Основные концепции

Специальные права задаются четвертой (ведущей) цифрой в восьмеричной нотации (например, `4755`) или специальными символами в символьном режиме.

### SUID (Set User ID)

| Параметр | Значение |
| :--- | :--- |
| **Назначение** | Процесс запускается с правами **владельца файла**, а не запускающего пользователя |
| **Применимость** | Только **бинарные исполняемые файлы** |
| **Числовое значение** | `4` (например, `4755`) |
| **Символьное обозначение** | `s` в позиции владельца: `-rwsr-xr-x` |
| **Заглавная `S`** | `-rwSr-xr-x` — бит SUID установлен, но у владельца нет права на выполнение (`x`). Ошибка конфигурации |

**Практическое применение (Пример с `passwd`):**
Классический сценарий делегирования прав `root` обычному пользователю без использования `sudo`:
1.  Файл паролей `/etc/shadow` доступен на запись только пользователю `root`.
2.  Утилита `/usr/bin/passwd` принадлежит `root` и имеет установленный **SUID-бит**.
3.  Когда обычный пользователь запускает `passwd`, ядро устанавливает **Effective UID (EUID)** процесса в значение `0` (root).
4.  Благодаря EUID=0 процесс получает доступ к `/etc/shadow` для обновления хеша пароля.
5.  Программа внутри себя проверяет **Real UID (RUID)** и разрешает пользователю менять пароль только для своей учетной записи.

**Безопасность и риски:**
*   **Приоритетная цель:** Любая уязвимость (например, переполнение буфера) в SUID-программе позволяет злоумышленнику получить права владелеца файла (обычно `root`). См. **[GTFOBins](../../../../Security/Tools/gtfobins.md)**.
*   **Минимизация:** Рекомендуется сокращать количество SUID-бинарников в системе до необходимого минимума.
*   **Скрипты:** В Linux SUID-бит **игнорируется для интерпретируемых скриптов** (`#!`). Это защита от атак через подмену окружения интерпретатора.

#### Практическая отладка: проверка EUID/RUID во время выполнения

Для понимания, какие идентификаторы есть у процесса в момент запуска, можно использовать `/proc`:

```bash
# Запуск SUID-бинарника и проверка его идентификаторов
# (запуск от обычного пользователя alice, UID=1000)
/usr/bin/passwd

# В другом терминале:
cat /proc/$(pgrep passwd)/status | grep -E '^(Uid|Gid):'
# → Uid: 0    1000 0    0    (EUID=0, RUID=1000, SUID=0, FSUID=0)
# → Gid: 0    1000 0    0

# Проверить, какой бинарник загружен ядром:
readlink -f /proc/$(pgrep passwd)/exe
# → /usr/bin/passwd

# Установить бит и проверить результат
sudo chmod u+s /usr/bin/custom_tool
ls -l /usr/bin/custom_tool
# → -rwsr-xr-x 1 root root ... /usr/bin/custom_tool
stat -c "%a" /usr/bin/custom_tool
# → 4755
```

**Команды проверки EUID/RUID в скриптах (на примере C и Python):**
```c
// C: проверка идентификаторов внутри SUID-программы
#include <stdio.h>
#include <unistd.h>
#include <sys/types.h>
int main() {
    printf("RUID=%d EUID=%d SUID=%d\n", getuid(), geteuid(), getuid()==geteuid()?getuid():-1);
    return 0;
}
```
```python
# Python: аналогичная проверка
import os
print(f"RUID={os.getuid()} EUID={os.geteuid()}")
```

#### Сценарий: безопасное внедрение SUID-бинарника в инфраструктуре

**Контекст:** Требуется дать приложению (например, лог-ротатору) доступ к `/var/log` без предоставления полных прав root.

**Решение через file capabilities (предпочтительнее SUID):**
```bash
# 1. Установить capability вместо SUID
sudo setcap cap_dac_read_search+ep /opt/logrotate/logrotate
# 2. Проверить
getcap /opt/logrotate/logrotate
# → /opt/logrotate/logrotate cap_dac_read_search=ep
# 3. Удалить SUID-бит, если был установлен ранее
sudo chmod u-s /opt/logrotate/logrotate
```

**Если SUID необходим (например, для утилиты, которой нет в capabilities):**
```bash
# 1. Создать отдельного системного пользователя-владельца бинарника
sudo useradd -r -s /usr/sbin/nologin logagent
# 2. Установить бит только на конкретный бинарник
sudo chown logagent /opt/logagent/bin/logagent
sudo chmod 4750 /opt/logagent/bin/logagent   # owner-only execute
# 3. Записать в sudoers ограничение (NOEXEC предотвращает shell escape)
sudo visudo -f /etc/sudoers.d/logagent
# Добавить: logagent ALL=(root) NOPASSWD: NOEXEC: /opt/logagent/bin/logagent
```

**Проверка результата:**
```bash
# Убедиться, что бит установлен только у нужного бинарника
sudo find / -xdev -type f -perm -4000 2>/dev/null
# → /usr/bin/passwd /usr/bin/su /usr/bin/mount /usr/bin/umount /opt/logagent/bin/logagent
```

### SGID (Set Group ID)

| Параметр | Значение |
| :--- | :--- |
| **Для файлов** | Процесс запускается с правами **группы-владельца** файла |
| **Для директорий** | Новые файлы и поддиректории наследуют **группу родительской директории** |
| **Числовое значение** | `2` (например, `2775`) |
| **Символьное обозначение** | `s` в позиции группы: `-rwxr-sr-x` |
| **Заглавная `S`** | `-rwxr-Sr-x` — бит SGID установлен, но у группы нет права на выполнение (`x`) |

**SGID на директориях (Совместная работа):**
Это основной механизм организации общих папок для групп пользователей.
1.  При создании файла в директории с SGID, его GID будет равен GID директории, а не основной группе создателя.
2.  Новые подкаталоги автоматически получают SGID-бит, что делает наследование группы рекурсивным.
3.  Незаменимо в проектах, где несколько пользователей должны иметь полный доступ к файлам друг друга через групповые права.

#### Практический сценарий: совместная разработка (Dev-команда)

**Контекст:** Группа `developers` должна работать над проектом в `/srv/www/project`. Все файлы должны быть доступны для чтения/записи/выполнения членам группы, новые файлы — автоматически наследовали группу, а доступ посторонних — ограничен.

**Пошаговая настройка:**
```bash
# 1. Создать системную группу проекта
sudo groupadd developers
# → Группа создана, GID присвоен автоматически

# 2. Добавить пользователей в группу
sudo usermod -aG developers alice
sudo usermod -aG developers bob
# Проверка: id alice → groups=alice,developers

# 3. Создать общую директорию с правами
sudo mkdir -p /srv/www/project
sudo chown root:developers /srv/www/project
sudo chmod 2775 /srv/www/project
# → rwxrwsr-x, owner=root, group=developers, SGID включен

# 4. Настроить umask для пользователей (чтобы новые файлы не были world-readable)
# В ~/.bashrc каждого пользователя:
echo "umask 0027" >> ~/.bashrc
# → Файлы: 640, директории: 750

# 5. Проверить поведение:
cd /srv/www/project
touch testfile.txt
ls -l testfile.txt
# → -rw-r----- 1 alice developers 0 ... testfile.txt
#    GID = developers (наследован от директории, а не основной группы alice)
stat -c "%G" testfile.txt
# → developers

# 6. Проверить рекурсивное наследование:
mkdir subdir
ls -ld subdir
# → drwxrwsr-x 2 alice developers ... subdir
#    SGID-бит сохранен в подкаталоге
```

**Комбинация с ACL для гарантии записи (на случай, если umask не соблюден):**
```bash
# Установить default ACL — гарантирует запись для группы при любом umask
sudo setfacl -d -m g:developers:rwx /srv/www/project
sudo setfacl -m g:developers:rwx /srv/www/project

# Проверить ACL:
getfacl /srv/www/project
# → # file: srv/www/project
# → # owner: root
# → # group: developers
# → rwxrwsr-x+  # "+" указывает на наличие ACL
# → # mask: rwx
# → # other: r-x
# → group: developers rwx
# → default:group:developers rwx
```

#### Сценарий: SGID для service-аккаунтов (SRE)

**Контекст:** Служебный процесс (например, бэкап-агент) должен писать в общую директорию, принадлежащую группе `backup`, но не иметь прав root.

```bash
# 1. Создать системного пользователя для бэкапа
sudo useradd -r -s /usr/sbin/nologin -G backup backup-agent
# → -r: системный пользователь, без домашней директории

# 2. Общая папка для бэкапов
sudo mkdir -p /var/backups/shared
sudo chown backup-agent:backup /var/backups/shared
sudo chmod 2770 /var/backups/shared
# → Только владелец и группа могут читать/писать/выполнять

# 3. Запуск через systemd с фиксацией группы:
# /etc/systemd/system/backup-agent.service
# [Service]
# User=backup-agent
# Group=backup
# ExecStart=/opt/backup-agent/bin/backup
# SupplementaryGroups=backup
```

**Проверка:**
```bash
# Проверить, что процесс работает от нужной группы
ps aux | grep backup-agent
# → backup-agent ... /opt/backup-agent/bin/backup

# Проверить GID процесса:
cat /proc/$(pgrep backup-agent)/status | grep Gid
# → Gid: 1001 1002 1002 1002   (real=1002, effective=1002 — группа backup)
```

### Sticky Bit (Бит ограничения удаления)

| Параметр | Значение |
| :--- | :--- |
| **Назначение** | В современных системах применяется **только к директориям** |
| **Эффект** | Удалить или переименовать файл может только **владелец файла**, **владелец директории** или `root` |
| **Числовое значение** | `1` (например, `1777`) |
| **Символьное обозначение** | `t` в позиции остальных: `drwxrwxrwt` |
| **Заглавная `T`** | `drwxrwxrwT` — бит установлен, но у категории "others" нет права на вход (`x`) |

**Зачем это нужно:**
В директориях с правами `777` (например, `/tmp`) любой пользователь мог бы удалить чужой файл, так как удаление — это операция записи в родительский каталог. Sticky Bit предотвращает это деструктивное поведение.

#### Практические сценарии использования Sticky Bit

**Сценарий 1: Публичная загрузочная папка (shared dropbox)**

Контекст: Требуется дать пользователям возможность загружать и редактировать только свои файлы, но не удалять чужие.

```bash
# 1. Создать папку для общего доступа
sudo mkdir -p /srv/shared_dropbox
sudo chown root:shared_users /srv/shared_dropbox
# 2. Установить права: запись для всех + Sticky Bit
sudo chmod 1777 /srv/shared_dropbox
# → drwxrwxrwt

# 3. Проверка поведения:
cd /srv/shared_dropbox
# Пользователь alice создает файл:
echo "data" > alice_file.txt
# Пользователь bob пытается удалить чужой файл:
rm alice_file.txt
# → rm: cannot remove 'alice_file.txt': Operation not permitted
# Sticky Bit заблокировал удаление, несмотря на запись в директорию

# 4. Проверка через ls:
ls -l /srv/shared_dropbox
# → -rw-r--r-- 1 alice alice ... alice_file.txt
#    t в правах директории: drwxrwxrwt
```

**Сценарий 2: Временные директории и сокеты (SRE)**

Контекст: Приложению нужно создавать временные файлы в общей папке, где другие процессы также могут писать (например, локальный кэш).

```bash
# Пример: временный кэш для прокси
sudo mkdir -p /var/cache/proxy/tmp
sudo chmod 1733 /var/cache/proxy/tmp
# → drwxrwxrwt (t = sticky, 3 = write+execute для всех)

# Используется в nginx:
# /etc/nginx/nginx.conf
# worker_temp_path /var/cache/proxy/tmp;
```

**Сценарий 3: Защита от случайного удаления в /tmp**

```bash
# Проверить, что /tmp уже имеет Sticky Bit (по умолчанию):
ls -ld /tmp
# → drwxrwxrwt 1 root root ... /tmp

# Добавить Sticky Bit в существующую папку без него:
sudo chmod +t /path/to/dir
# Или через числовое значение:
sudo chmod 1777 /path/to/dir

# Проверить, что бит установлен:
stat -c "%a %A" /path/to/dir
# → 1777 drwxrwxrwt
```

#### Взаимодействие Sticky Bit с other правами

**Важно:** Sticky Bit работает только если у категории "others" есть право на выполнение (`x`). Если `x` отсутствует, бит отображается как заглавная `T`, но не действует:

```bash
# Установить права без x, но с Sticky Bit
sudo chmod 1766 /tmp/test_dir
ls -ld /tmp/test_dir
# → drwxrw-rwT  (заглавная T — бит есть, но не действует, т.к. нет x)

# Попытка удаления чужого файла:
# Даже несмотря на отсутствие x, пользователь может заходить в директорию,
# если у него есть права на запись (w), но Sticky Bit не защитит,
# так как нет x. Это ошибка конфигурации.
```

**Рекомендация:** Всегда проверяте, что после установки Sticky Bit отображается строчная `t`, а не заглавная `T`:
```bash
stat -c "%A" /path/to/dir | grep -q 't$' && echo "Sticky Bit активен" || echo "Sticky Bit не действует (нет x)"
```

## Практические сценарии

### 0. Подготовка: проверка текущего состояния и инструментов

Перед изменением специальных прав убедитесь, что у вас есть необходимые инструменты и понимание текущей конфигурации.

**Проверка наличия утилит:**
```bash
# Проверка доступности базовых команд
which chmod chown find stat getcap setcap 2>/dev/null
# → /usr/bin/chmod /usr/bin/chown /usr/bin/find /usr/bin/stat /usr/bin/getcap /usr/bin/setcap

# Проверка версии find (поддержка -perm / vs -perm -)
find --version | head -1
# → find (GNU findutils) 4.9.0
```

**Просмотр полных метаданных файла (inotify, xattr, числовые UID/GID):**
```bash
# Полный дамп метаданных через stat
stat -c "%a %A %u %g %U %G %n" /usr/bin/passwd
# → 4755 -rwsr-xr-x 0 0 root root /usr/bin/passwd

# Проверка file capabilities (альтернатива SUID)
getcap /usr/bin/ping
# → /usr/bin/ping cap_net_raw=ep

# Вывод всех расширенных атрибутов (xattr)
getfattr -d -m - /usr/bin/passwd 2>/dev/null | head -20
```

**Контекст: версии ядра и поддержка флагов**
- `fs.protected_symlinks`, `fs.protected_hardlinks`, `fs.suid_dumpable` доступны с ядра Linux 4.15+ (проверяется через `sysctl -a | grep fs.protected`).
- `no_new_privs` доступен с ядра 3.5+, но полная поддержка в контейнерных рантаймах — с Docker 1.13+ и Kubernetes 1.24+ (Pod Security `allowPrivilegeEscalation`).

### 1. Установка и удаление прав

```bash
# SUID: символьный и числовой режимы
chmod u+s /usr/bin/custom_tool
chmod 4755 /usr/bin/custom_tool

# SGID на директорию
chmod g+s /var/www/shared
chmod 2775 /var/www/shared

# Sticky Bit
chmod +t /home/public_dropbox
chmod 1777 /home/public_dropbox

# Удаление (сброс) прав
chmod u-s /path/to/bin   # Снять SUID
chmod g-s /path/to/dir   # Снять SGID
chmod -t /path/to/dir    # Снять Sticky Bit
```

### 2. Поиск и аудит безопасности

Регулярная инвентаризация специальных прав — критическая задача администратора.

```bash
# Поиск всех SUID-файлов (режим 4000)
find / -type f -perm -4000 2>/dev/null

# Поиск всех SGID-файлов (режим 2000)
find / -type f -perm -2000 2>/dev/null

# Комбинированный поиск SUID/SGID с выводом подробностей
find / -type f \( -perm -4000 -o -perm -2000 \) -exec ls -ld {} \; 2>/dev/null

# Поиск директорий с правами на запись для всех, но без Sticky Bit
find / -type d -perm -0002 ! -perm -1000 -ls 2>/dev/null
```

#### Расширенные сценарии аудита (SRE/DevOps)

**Сценарий 1: Аудит только в пределах конкретной ФС (исключение сетевых монтирований):**
```bash
# Поиск без пересечения NFS/сетевых filesystems (избегаем " зависания")
find / -xdev -type f -perm -4000 2>/dev/null
# -xdev: не заходить за границы одной файловой системы

# Поиск с сортировкой по размеру (топ самых крупных SUID-бинарников):
find / -xdev -type f -perm -4000 -exec ls -l {} \; 2>/dev/null | sort -k5 -hr | head -10
```

**Сценарий 2: Интеграция с cron для регулярного аудита:**
```bash
# Создать скрипт аудита: /usr/local/bin/audit_suid.sh
#!/bin/bash
# Логи аудита специальных прав
LOG_FILE="/var/log/suid_audit.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')

echo "=== SUID/SGID Audit: $DATE ===" >> "$LOG_FILE"
find / -xdev -type f \( -perm -4000 -o -perm -2000 \) -exec ls -ld {} \; >> "$LOG_FILE" 2>/dev/null
echo "---" >> "$LOG_FILE"

# Уведомление в systemd journal при обнаружении новых SUID-файлов:
# (сравним с предыдущей инвентаризацией)
```
```cron
# /etc/cron.d/suid_audit
# Ежедневно в 02:00
0 2 * * * root /usr/local/bin/audit_suid.sh
```

**Сценарий 3: Мониторинг в реальном времени через auditd (SRE)**

Для отслеживания попыток изменения SUID/SGID-битов:
```bash
# Добавить правило в auditd:
sudo auditctl -a always,exit -F arch=b64 -S chmod,fchmod,fchmodat -F auid>=1000 -F auid!=-1 -k perm_mod

# Или через файл конфигурации /etc/audit/rules.d/perm-changes.rules:
-a always,exit -F arch=b64 -S chmod,fchmod,fchmodat -F auid>=1000 -F auid!=-1 -k perm_mod
-w /etc/sudoers -p wa -k scope
-a always,exit -F arch=b64 -S setuid -F a0=0 -F exe=/usr/bin/su -k priv_esc

# Проверить логи:
sudo ausearch -k perm_mod | aureport -f
```

**Сценарий 4: Проверка через getcap (альтернатива SUID — file capabilities):**
```bash
# Поиск всех бинарников с file capabilities
getcap -r / 2>/dev/null

# Проверить конкретный бинарник:
getcap /usr/bin/ping
# → /usr/bin/ping cap_net_raw=ep

# Проверить capabilities запущенного процесса:
getpcaps $(pgrep nginx)
# → Capabilities: =ep cap_net_bind_service

# Проверить, есть ли у процесса file capabilities:
getcap $(readlink -f /proc/$(pgrep nginx)/exe)
# → /usr/sbin/nginx cap_net_bind_service=ep
```

**Сценарий 5: Сравнение SUID-бинарников с GTFOBins (приоритет рисков):**
```bash
# Получить список SUID-бинарников и проверить их наличие в GTFOBins
for bin in $(find / -xdev -type f -perm -4000 2>/dev/null); do
    if grep -q "$(basename "$bin")" /usr/share/gtfobins.txt 2>/dev/null; then
        echo "ОПАСНО: $bin присутствует в GTFOBins"
    fi
done
```

### 3. Безопасное монтирование файловых систем

Для предотвращения атак через SUID на внешних носителях или пользовательских разделах используйте опции монтирования в `/etc/fstab`:

```bash
# nosuid — игнорирует SUID/SGID биты на разделе
UUID=... /home ext4 defaults,nosuid,nodev 0 2

# noexec — запрещает запуск любых бинарных файлов (включая SUID)
UUID=... /tmp  ext4 defaults,nosuid,nodev,noexec 0 2
```

#### Подробный разбор опций монтирования и сценарии применения (SRE)

**Таблица релевантных опций fstab:**

| Опция | Действие | Рекомендуемые разделы | Риск без опции |
| :--- | :--- | :--- | :--- |
| `nosuid` | Игнорирует SUID/SGID биты | `/home`, `/tmp`, `/var` | Пользователь может запустить SUID-бинарник с правами root |
| `noexec` | Запрещает выполнение бинарников | `/tmp`, `/var/tmp`, `/usr/share` | Возможность запуска вредоносного кода из временной папки |
| `nodev` | Игнорирует устройство (device nodes) | `/home`, `/tmp` | Пользователь может создать `/dev/null` и перенаправить вывод |
| `ro` | Монтирование только для чтения | `/usr/local`, `/var/log` | Предотвращает модификацию системных бинарников |

**Готовые конфигурационные фрагменты для типовых сценариев:**

```bash
# /etc/fstab — защищённая конфигурация для сервера (SRE)
# Корневая ФС (полный доступ — системные бинарники должны работать):
UUID=A1B2C3D4 /     ext4 defaults,noatime,nodiratime 0 0

# /home — пользовательские данные, запрет SUID/SGID:
UUID=E5F6G7H8 /home ext4 defaults,nosuid,nodev,noatime 0 2

# /tmp — временные файлы, максимальная защита:
UUID=I9J0K1L2 /tmp  ext4 defaults,nosuid,nodev,noexec,noatime,relatime 0 2

# /var/log — логи, только чтение для пользователей:
UUID=M3N4O5P6 /var/log ext4 defaults,nosuid,nodev,noatime 0 2

# /var/tmp — аналог /tmp, но с сохранением данных между перезагрузками:
UUID=Q7R8S9T0 /var/tmp ext4 defaults,nosuid,nodev,noexec 0 2

# Своп (не требует опций, но рекомендуется noexec):
UUID=U1V2W3X4 none swap defaults,nosuid,noexec 0 0
```

**Проверка активных опций монтирования:**
```bash
# Проверить, какие опции примонтированы в данный момент:
mount | grep -E '/tmp|/home|/var'
# → /dev/sda1 on /tmp type ext4 (rw,noexec,nosuid,nodev,relatime)

# Проверить конфигурацию fstab:
sudo mount -a --fake 2>&1 || echo "Проверьте fstab"
sudo findmnt --verify
# → Success: no errors or warnings detected

# Проверить конкретную опцию:
findmnt -T /tmp -o OPTIONS
# → noexec,nosuid,nodev,relatime
```

**Сценарий: защита виртуальных ФС (tmpfs) для контейнеров и systemd:**
```bash
# Монтирование tmpfs с защитой для /run (systemd делает это автоматически):
sudo mount -t tmpfs -o size=512M,mode=1777,uid=0,gid=0,nosuid,nodev,noexec tmpfs /run

# Для временной директории приложения:
sudo mount -t tmpfs -o size=256M,mode=1777,nosuid,nodev,noexec tmpfs /opt/app/tmp

# Проверить:
mount | grep tmpfs
# → tmpfs on /run type tmpfs (rw,relatime,size=524288k,mode=777,uid=0,gid=0,nosuid,nodev,noexec)
```

**Сценарий: настройка через systemd (для служб):**
```ini
# /etc/systemd/system/myapp.service
[Unit]
Description=My Application with Hardened Mounts

[Service]
# Запретить получение новых привилегий через SUID
NoNewPrivileges=yes
# Запретить создание SUID/SGID файлов в контексте службы
RestrictSUIDSGID=yes
# Запретить выполнение бинарников из определённых путей
ReadWritePaths=/var/lib/myapp /tmp
# Запускать от непривилегированного пользователя
User=myapp
```

**Важно:** Опции `nosuid` и `noexec` действуют независимо. `nosuid` отключает только SUID/SGID-биты, но бинарники всё ещё можно запускать. `noexec` полностью запрещает выполнение, но не влияет на SUID-биты (которые и так не будут работать, если нет `x`). Для максимальной защиты используйте обе опции вместе.

## Дополнительная информация

### Усиление защиты на уровне ядра (sysctl)
Современные ядра Linux включают дополнительные механизмы защиты, связанные со специальными правами:
*   `fs.protected_symlinks = 1`: запрещает следовать по символьным ссылкам в директориях со Sticky Bit, если владелец ссылки не совпадает с владельцем папки или файла.
*   `fs.protected_hardlinks = 1`: запрещает создание жестких ссылок на файлы, которыми пользователь не владеет (предотвращает создание "якорей" на SUID-файлы).
*   `fs.suid_dumpable = 0`: отключает создание дампов памяти (core dumps) для SUID-процессов, предотвращая утечку секретов. Подробнее: **[Защита среды выполнения](../../Fstec/kernel_runtime_protection.md#запрет-создания-core-dump-для-suidsgid-файлов)**.

### Современные альтернативы и контекст
*   **Linux Capabilities:** Позволяют заменить монолитный SUID на гранулярные привилегии (например, `CAP_NET_RAW` вместо полного root для `ping`). Подробнее: **[Linux Capabilities](../../Mechanisms/Capabilities.md)**.
*   **Контейнеризация:** В Docker/Kubernetes рекомендуется использовать параметр `no-new-privileges`, чтобы блокировать SUID внутри контейнера. Подробнее: **[Hardening контейнеров](../../../../Docker/Docker_security/container_hardening.md)**.
*   **Аудит (FSTEC):** Методология контроля спецправ в сертифицированных системах. Подробнее: **[Контроль прав доступа](../../Fstec/file_permissions_control.md)**.

### Управление привилегиями через systemd (SRE)

Современные системные службы должны использовать механизмы systemd для ограничения SUID/SGID-векторов:

**Ключевые настройки безопасности в unit-файлах:**

| Параметр | Действие | Рекомендация |
| :--- | :--- | :--- |
| `NoNewPrivileges=yes` | Блокирует получение новых привилегий через `execve()` (SUID/SGID/fcaps) | Включать для всех служб |
| `RestrictSUIDSGID=yes` | Запрещает создание новых SUID/SGID-файлов | Включать для всех служб |
| `ProtectSystem=full` | Делает `/usr`, `/boot`, `/etc` доступными только для чтения | Для служб, не требующих модификации |
| `ProtectHome=yes` | Делает `/home`, `/root`, `/run/user` недоступными | Для системных служб |
| `ReadWritePaths=` | Определяет разрешённые пути для записи | Ограничить только необходимыми |
| `User=` | Запускать службу от конкретного пользователя | Избегать запуска от root |
| `Group=` | Группа для запуска | Использовать системные группы |

**Пример защищённого unit-файла:**
```ini
# /etc/systemd/system/web-server.service
[Unit]
Description=Web Server with Hardened Security
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
ExecStart=/usr/bin/nginx -g 'daemon off;'

# --- Критически важные hardening-параметры ---
NoNewPrivileges=yes
RestrictSUIDSGID=yes
ProtectSystem=full
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
PrivateTmp=yes
PrivateDevices=yes
MemoryDenyWriteExecute=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
ReadWritePaths=/var/www /var/log/nginx /var/cache/nginx /run/nginx

# --- Дополнительная защита ---
SystemCallFilter=@system-service
SystemCallArchitectures=native
RestrictNamespaces=yes

[Install]
WantedBy=multi-user.target
```

**Проверка эффективности:**
```bash
# Проверить, что служба запущена с правильными флагами:
systemctl show web-server.service -p NoNewPrivileges -p RestrictSUIDSGID
# → NoNewPrivileges=yes
# → RestrictSUIDSGID=yes

# Проверить флаги ядра процесса:
cat /proc/$(pgrep nginx)/status | grep -E 'NoNewPrivs|Seccomp'
# → NoNewPrivs:  2
# → Seccomp:     2 (filter)

# Проверить, что SUID-биты игнорируются:
# (если бинарник имеет SUID, он не будет работать при NoNewPrivileges=yes)
```

### Таблица: специальные биты vs file capabilities vs no_new_privs

| Механизм | Устанавливается на | Действие | Защита от |
| :--- | :--- | :--- | :--- |
| SUID (4) | Файл | Запуск от владельца | `no_new_privs`, `nosuid`, `noexec` |
| SGID (2) | Файл/директория | Запуск от группы / наследование группы | `no_new_privs`, `nosuid` |
| Sticky Bit (1) | Директория | Защита от удаления чужих файлов | Никак (工作机制 чётко) |
| file capabilities | Файл | Гранулярные привилегии без root | `no_new_privs` (игнорирует fcaps) |
| `no_new_privs` | Процесс | Блокирует SUID/SGID/fcaps при `execve()` | Сам по себе — защита, не привилегия |

### Устранение неисправностей (Troubleshooting)

**Ситуация 1: SUID-бит не действует на бинарнике**

| Причина | Проверка | Решение |
| :--- | :--- | :--- |
| У бинарника нет права `x` | `ls -l /path/to/bin` — заглавная `S` вместо `s` | Добавить `chmod u+x` |
| Файл — скрипт (interpretted) | `file /path/to/bin` — "script" | SUID игнорируется для скриптов; использовать бинарную обёртку |
| Раздел монтируется с `nosuid` | `mount \| grep /path` | Убрать `nosuid` из fstab или монтировать без него |
| Установлен `no_new_privs` | `cat /proc/PID/status \| grep NoNewPrivs` | Сбросить флаг: `prctl(PR_SET_NO_NEW_PRIVS, 0)` или перезапустить без него |
| Файл на NFS/сетевой ФС | `df -T /path \| grep nfs` | NFS v4 с опцией `root_squash` игнорирует SUID |

**Ситуация 2: SGID на директории не наследуется подкаталогами**

```bash
# Проверить, что SGID-бит установлен на родительской директории:
ls -ld /path/to/dir
# → drwxrwsr-x  (должна быть строчка s в позиции группы)

# Если бит есть, но подкаталоги не наследуют:
mkdir /path/to/dir/test_subdir
ls -ld /path/to/dir/test_subdir
# → drwxr-xr-x  (наследования нет)

# Решение: установить SGID-бит вручную или через default ACL:
sudo chmod g+s /path/to/dir
# Или использовать setfacl для guarantee:
sudo setfacl -d -m g:groupname:rwx /path/to/dir
```

**Ситуация 3: Sticky Bit не защищает от удаления**

```bash
# Проверить, что бит отображается как строчная t, а не заглавная T:
ls -ld /path/to/dir
# → drwxrwxrwt  (t — активен)
# → drwxrwxrwT  (T — не действует, нет x)

# Если T — добавить x:
sudo chmod o+x /path/to/dir
# → теперь будет drwxrwxrwt

# Проверить, что пользователь пытается удалить чужой файл:
# (даже при наличии w в директории, sticky bit должен заблокировать)
```

**Ситуация 4: Слишком много SUID-бинарников (аудит показал избыток)**

```bash
# 1. Получить список всех SUID-файлов:
find / -xdev -type f -perm -4000 -exec ls -ld {} \; 2>/dev/null

# 2. Оценить, какие из них необходимы:
# Обязательные: /usr/bin/passwd, /usr/bin/su, /usr/bin/mount, /usr/bin/umount,
#               /usr/bin/sudo, /usr/bin/newgrp, /usr/bin/chsh, /usr/bin/chfn
#               /usr/lib/openssh/ssh-keysign, /usr/lib/policykit-1/polkit-agent-helper-1

# 3. Удалить ненужные биты (пример):
sudo chmod u-s /usr/bin/custom_tool
sudo chmod u-s /opt/legacy/binary

# 4. Проверить результат:
find / -xdev -type f -perm -4000 2>/dev/null | wc -l
# → 12 (было 25)
```

**Ситуация 5: Процесс не может получить доступ к файлу несмотря на SUID**

```bash
# Проверить, какой EUID у процесса:
cat /proc/$(pgrep problematic_process)/status | grep -E '^Uid:'
# → Uid: 0 1000 0 0  (EUID=0, RUID=1000)

# Проверить, загружен ли правильный бинарник:
readlink -f /proc/$(pgrep problematic_process)/exe

# Проверить права на файл:
ls -l /path/to/binary
# → -rwsr-xr-x 1 root root ... /path/to/binary

# Проверить, не монтирован ли раздел с nosuid:
findmnt -T /path/to/binary -o OPTIONS,FS-TYPE
# → nosuid,ext4  (вот проблема!)
```

### См. также
* [Обзор прав доступа (DAC)](./overview_definitions.md)
* [ACL, атрибуты и временные метки](./acl_immutable_timestamps.md)
* [Типы идентификаторов пользователей (UID/EUID)](../../../SystemAdministration/Users/users_definitions.md)