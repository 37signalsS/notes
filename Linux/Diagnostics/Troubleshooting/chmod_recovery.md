# Восстановление прав на исполнение утилиты `chmod`

## Определения

**chmod recovery** — процесс восстановления прав на исполнение утилиты `/bin/chmod` после их случайного удаления (например, командой `chmod -x /bin/chmod`). В контексте SRE/DevOps относится к категории инцидентов «self-inflicted» (самопрогнозируемый сбой), возникающих при деплое конфигураций или выполнении скриптов с недостаточными валидациями.

**Системный вызов `chmod(2)`** — низкоуровневый интерфейс ядра Linux для изменения прав доступа к файлам. Большинство альтернативных методов восстановления основаны на прямом обращении к этому вызову в обход бинарного файла `/bin/chmod` (например, через libc в интерпретаторах Python/Perl или через явный вызов компоновщика).

**Демонтаж (downgrade прав)** — состояние, при котором исполняемый файл теряет бит `+x` (S_IXUSR, S_IXGRP, S_IXOTH). Ядро возвращает `EACCES` (Permission denied) при попытке `execve(2)`, и командная оболочка завершает выполнение с ошибкой до запуска программы.

**Динамический компоновщик (ld-linux.so / ld-musl-*.so.1)** — исполняемый файл, ответственный за загрузку разделяемых библиотек (.so) и передачу управления главной функции бинарника. Является самостоятельным исполняемым объектом; его права на выполнение не зависят от прав целевого бинарника, что позволяет обойти отсутствие `+x` у последнего.

**Пакетный менеджер (coreutils)** — источник «истинной копии» утилиты `chmod`. В дистрибутивах семейства Debian/RHEL/SUSE/Fedora/CoreOS утилита `chmod` входит в пакет `coreutils`. Переустановка пакета восстанавливает все метаданные файлов, включая права, владельца и хэши.

**SSoT для прав доступа** — канонический источник коррекции прав в автоматизированных системах. В контексте Configuration Management (Ansible, Chef, Puppet, SaltStack) состояние прав на критически важные утилиты должно управляться централизованно через модули `file`/`template`, а не ручными исправлениями.

## Предварительные требования

### Требования к окружению

Для применения методов восстановления прав на исполнение утилиты `chmod` необходимо:

| Компонент | Минимальные требования | Рекомендации для production |
| :--- | :--- | :--- |
| **Доступ к консоли** | root-привилегии (UID 0) или `sudo` | Использование `sudo -i` или `su -` для полного доступа к `/bin` |
| **Файловая система** | Не в режиме `ro` (read-only) | Если корневой раздел смонтирован как `ro`, выполнить `mount -o remount,rw /` |
| **Атрибуты файла** | Отсутствие флага `+i` (immutable) | Проверить через `lsattr /bin/chmod`; при наличии `i` снять через `chattr -i /bin/chmod` |
| **SELinux/AppArmor** | Не в режиме `Enforcing` с блокирующей политикой | Проверить через `getenforce` или `aa-status`; при необходимости переключить в `Permissive` для диагностики |
| **Место во временной директории** | ≥ 1 MB свободного места в `/tmp` или `$TMPDIR` | Использовать `mktemp` для создания уникального временного файла |

### Проверка начального состояния

Перед выполнением любых методов восстановления необходимо подтвердить проблему:

```bash
# 1. Подтвердить отсутствие права на выполнение
ls -l /bin/chmod
# → -rw-r--r-- 1 root root ... /bin/chmod

# 2. Подтвердить ошибку при вызове
chmod --version
# → -bash: /bin/chmod: Permission denied

# 3. Проверить тип ELF-бинарника и интерпретатор
file /bin/chmod
# → /bin/chmod: ELF 64-bit LSB pie executable, x86-64, ..., interpreter /lib64/ld-linux-x86-64.so.2, ...

# 4. Проверить атрибуты файла
lsattr /bin/chmod
# → ------------------ /bin/chmod
```

### Специфические требования по методам

| Метод | Дополнительные требования |
| :--- | :--- |
| **Python/Perl** | Установленный интерпретатор (`python3` ≥ 3.6 или `perl`) с правом на выполнение |
| **ld-linux** | Знание пути к динамическому компоновщику (для glibc) или musl-компоновщику (для Alpine) |
| **GCC** | Компилятор C (`gcc` или `cc`) и заголовки glibc (`/usr/include/sys/stat.h`) |
| **Пакетный менеджер** | Доступ к репозиториям (apt, dnf, yum, apk) или локальный кеш пакетов |
| **LiveCD** | Загрузочный носитель или возможность монтирования файловой системы в другой системе |

## Базовые концепции

### Механизм проблемы

Утилита `chmod` — это исполняемый файл, требующий прав на запуск (`+x`). Если эти права сняты, ядро отказывается запускать процесс, и командная оболочка возвращает ошибку:

```bash
$ chmod 755 some_file
# → -bash: /bin/chmod: Permission denied
```

**Техническая причина:** При вызове `chmod` происходит системный вызов `execve("/bin/chmod", ...)`. Ядро проверяет бит `S_IXUSR` (владелец: execute) в иноде файла. Если бит сброшен, возвращается `-EACCES`. Оболочка (bash, zsh, sh) транслирует это в строку `Permission denied` и завершает дочерний процесс. Никакие сигналы (`SIGSEGV`, `SIGILL`) не генерируются — проблема диагностируется на уровне загрузчика ELF.

**Последствия для SRE/DevOps:**
- **Автоматизация:** Все playbook Ansible, Makefile-цели, CI/CD-пайплайны, использующие `chmod`, прерываются с кодом возврата 126 (command cannot be executed).
- **Деплой:** Скрипты инициализации контейнеров (entrypoint.sh), systemd-юниты с `ExecStartPre=/bin/chmod ...` падают на старте.
- **Безопасность:** В средах с hardened-профилем (CIS Benchmarks) потеря прав на системные утилиты — маркер неавторизованного изменения или ошибки оркестрации.

### Жизненный цикл инцидента

| Фаза | Проявление | Диагностический маркер |
| :--- | :--- | :--- |
| **Триггер** | Человеческая ошибка, сбой CI/CD, неправильный `chmod -R` | `auditd`: `type=SYSCALL msg=chmod(...)` |
| **Обнаружение** | Мониторинг / алерт / ручная проверка | Код возврата 126 в логах systemd/jenkins/gitlab-runner |
| **Диагностика** | Определение метода восстановления | `lsattr`, `file`, `readelf` для анализа бинарника |
| **Восстановление** | Применение одного из методов | Валидация через `stat` и повторный вызов `chmod` |
| **Пост-анализ** | Устранение коренной причины | Обновление runbook, добавление pre-commit хуков, конфигурации Ansible |

### Ключевые принципы восстановления

- **Принцип минимальных привилегий:** Используйте самый простой метод, требующий минимальных прав и зависимостей. В production-средах предпочтительны интерпретаторы и ld-linux перед компиляцией.
- **Использование интерпретаторов** — языки программирования (Python, Perl, Ruby) имеют встроенные функции, вызывающие `chmod(2)` напрямую через стандартную библиотеку C (glibc), минуяELF-загрузчик целевого файла.
- **Манипуляция существующими правами** — использование утилит (`cp`, `install`), которые могут создавать или изменять файлы, сохраняя или устанавливая бит исполнения. На ext4/xfs/btrfs при перезапиве существующего файла `cp` может сохранять права назначения, но это не гарантировано POSIX.
- **Обход загрузчика** — запуск динамически скомпилированного бинарника через явный вызов динамического компоновщика (`ld-linux.so`). Компоновщик сам загружает библиотеки и передаёт управление `main()` целевому бинарнику, игнорируя отсутствие `+x` у последнего.
- **Внешнее окружение** — использование LiveCD, rescue-режима ядра или монтирование файловой системы в другой системе, где `chmod` исправен. Крайний метод, применяемый при невозможности восстановления «изнутри».

## Практические сценарии

### Сценарий 1: Интерпретаторы (Python/Perl/Ruby/PHP)

Самый быстрый и надёжный способ «изнутри» системы. Интерпретаторы используют libc, которая вызывает `chmod(2)` напрямую, минуяELF-загрузчик `/bin/chmod`.

**Python 3:**
```bash
python3 -c 'import os; os.chmod("/bin/chmod", 0o755)'
# → (пустой вывод при успехе)
```

**Python 2 (устаревшие системы):**
```bash
python -c 'import os; os.chmod("/bin/chmod", 0755)'
# → (пустой вывод при успехе)
```

**Perl:**
```bash
perl -e 'chmod 0755, "/bin/chmod"'
# → (пустой вывод при успехе)
```

**Ruby:**
```bash
ruby -e 'File.chmod(0755, "/bin/chmod")'
# → (пустой вывод при успехе)
```

**PHP CLI:**
```bash
php -r 'chmod("/bin/chmod", 0755);'
# → (пустой вывод при успехе)
```

**Валидация:**
```bash
# Проверка восьмеричного значения
stat -c '%a' /bin/chmod
# → 755

# Функциональная проверка (должен выполниться без ошибки)
chmod --version | head -1
# → chmod (GNU coreutils) 8.32

# Проверка на систему (не должно быть Permission denied)
chmod 644 /etc/hostname
```

**Когда работает:** Если в системе установлен соответствующий интерпретатор и у него самого есть права на выполнение. Проверка:
```bash
ls -l $(which python3)
# → -rwxr-xr-x ... /usr/bin/python3
```

---

### Сценарий 2: Утилиты копирования и установки

**Метод с `cp` (Трюк с перезаписью):**
При копировании файла в существующий файл на файловых системах ext4/xfs/btrfs `cp` без ключа `-p` может сохранять права назначения. Метод ненадёжный, но работает на большинстве систем.

```bash
# 1. Создаём временный файл с правами выполнения через mktemp (безопасное создание)
TMPFILE=$(mktemp /tmp/chmod_fix.XXXXXX)

# 2. Копируем исполняемый файл-«донор» (ls) — получаем +x
cp /bin/ls "$TMPFILE"

# 3. Перезаписываем содержимое /bin/chmod, сохраняя бит +x от ls
cp /bin/chmod "$TMPFILE"

# 4. Используем временный файл как замену chmod
"$TMPFILE" 755 /bin/chmod

# 5. Валидация
stat -c '%a %n' /bin/chmod
# → 755 /bin/chmod
chmod --version | head -1
# → chmod (GNU coreutils) ...

# 6. Очистка
rm -f "$TMPFILE"
```

**Важно:** На некоторых файловых системах (NFS с `no_root_squash`, CIFS/SMB) или при использовании GNU `cp` с опцией `--remove-destination` права назначения могут не сохраняться. В этом случае используйте метод с `install`.

**Метод с `install` (Рекомендуемый):**
Команда `install` умеет явно задавать права доступа в процессе копирования.

```bash
TMPFILE=$(mktemp /tmp/chmod_fix.XXXXXX)

# Копируем с явным указанием прав
install -m 755 /bin/chmod "$TMPFILE"

# Используем временный файл для исправления оригинала
"$TMPFILE" 755 /bin/chmod

# Валидация
stat -c '%a %n' /bin/chmod
# → 755 /bin/chmod

rm -f "$TMPFILE"
```

**Метод с `cp --attributes-only` (только для GNU coreutils ≥ 8.32):**
Копирует только метаданные (права, владельца, timestamps) без данных. Полезен, если `/bin/chmod` повреждён не только в правах, но и в содержимом.

```bash
# Копируем права с исправного бинарника
cp --attributes-only --reference=/bin/ls /bin/chmod

# Валидация
stat -c '%a %n' /bin/chmod
# → 755 /bin/chmod
```

---

### Сценарий 3: Динамический компоновщик

Позволяет запустить исполняемый файл, даже если у него нет бита `+x`, так как исполняемым в данном случае является сам компоновщик. Компоновщик загружает разделяемые библиотеки (.so), отображает сегменты памяти и передаёт управление на `_start()` целевого бинарника.

#### glibc (Debian, RHEL, Ubuntu, Fedora, SUSE)

```bash
# 64-битные системы (x86_64)
/lib64/ld-linux-x86-64.so.2 /bin/chmod 755 /bin/chmod

# 32-битные системы (i386/i686)
/lib/ld-linux.so.2 /bin/chmod 755 /bin/chmod
```

#### musl libc (Alpine Linux, Void Linux, Gentoo)

```bash
# Alpine Linux (aarch64/arm/x86_64)
/lib/ld-musl-*.so.1 /bin/chmod 755 /bin/chmod

# Уточнение архитектуры:
file /bin/chmod | grep interpreter
# → interpreter /lib/ld-musl-x86_64.so.1
```

#### Автоматическое определение пути к компоновщику

```bash
# Получение пути из ELF-заголовка
readelf -l /bin/chmod | grep interpreter | awk '{print $4}'
# → /lib64/ld-linux-x86-64.so.2

# Или через objdump
objdump -p /bin/chmod | grep INTERP | awk '{print $2}'
# → /lib64/ld-linux-x86-64.so.2
```

**Валидация:**
```bash
# Запуск chmod через компоновщик и проверка
/lib64/ld-linux-x86-64.so.2 /bin/chmod --version
# → chmod (GNU coreutils) 8.32

# Проверка прав
stat -c '%a %n' /bin/chmod
# → 755 /bin/chmod
```

**Ограничение:** Компоновщик должен иметь права на выполнение. На минимальных системах (например, `distroless` или `scratch`-контейнеры) компоновщик может отсутствовать или быть статически вшит в бинарник.

---

### Сценарий 4: Оболочки и встроенные модули

**Zsh (встроенный модуль `zsh/files`):**
Zsh позволяет загрузить собственную реализацию `chmod` как builtin-команду. Это работает даже если `/bin/chmod` отсутствует или повреждён.

```zsh
zmodload zsh/files
chmod 755 /bin/chmod
```

**Bash (с help-встроенными):**
Bash не имеет встроенного `chmod`, но может использовать `/dev/tcp` или `/dev/udp` для сетевых операций — не применимо для локального изменения прав.

**BusyBox:**
Если в системе есть `busybox`, он обычно скомпилирован статически и содержит свою реализацию `chmod`, не зависящую от `/bin/chmod`.

```bash
# Проверка доступности busybox
which busybox || ls -l /bin/busybox

# Использование
busybox chmod 755 /bin/chmod
```

**Вариация: BusyBox через полный путь (если which сломан)**
```bash
/bin/busybox chmod 755 /bin/chmod
```

**Валидация:**
```bash
stat -c '%a %n' /bin/chmod
# → 755 /bin/chmod
```

---

### Сценарий 5: Компиляция C-кода (Rescue Program)

Если в системе есть `gcc`, можно написать и скомпилировать минимальную программу, вызывающую `chmod(2)` через libc.

**Полный сброс прав (рекомендуемый для повреждённых файлов):**
```bash
cat << 'EOF' > /tmp/restore.c
#include <sys/stat.h>
#include <stdio.h>

int main(int argc, char *argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <mode_octal> <path>\n", argv[0]);
        return 1;
    }
    int mode = 0;
    sscanf(argv[1], "%o", &mode);
    if (chmod(argv[2], mode) != 0) {
        perror("chmod");
        return 1;
    }
    return 0;
}
EOF

gcc /tmp/restore.c -o /tmp/restore
/tmp/restore 755 /bin/chmod

# Валидация
stat -c '%a %n' /bin/chmod
# → 755 /bin/chmod

# Очистка
rm -f /tmp/restore.c /tmp/restore
```

**Минимальная версия (без обработки аргументов):**
```bash
echo '#include <sys/stat.h>
int main() { chmod("/bin/chmod", 0755); return 0; }' > /tmp/restore.c
gcc /tmp/restore.c -o /tmp/restore
/tmp/restore
```

**Требования:** Наличие заголовочных файлов glibc (`/usr/include/sys/stat.h`). На минимальных образах (например, `scratch` или `distroless`) заголовки могут отсутствовать.

**Валидация:**
```bash
chmod --version | head -1
# → chmod (GNU coreutils) 8.32
```

---

### Сценарий 6: Пакетный менеджер

Переустановка пакета восстанавливает права всех входящих в него файлов. Этот метод предпочтителен, если повреждение затронуло не только `chmod`, но и другие утилиты `coreutils`.

**Debian/Ubuntu:**
```bash
sudo apt install --reinstall coreutils
```

**RHEL/CentOS/Fedora/Rocky Linux/AlmaLinux:**
```bash
sudo dnf reinstall coreutils
# Или для устаревших систем:
sudo yum reinstall coreutils
```

**SUSE/openSUSE:**
```bash
sudo zypper install --force coreutils
```

**Alpine Linux (musl):**
```bash
sudo apk add --force-overwrite coreutils
```

**Arch Linux:**
```bash
sudo pacman -S --overwrite coreutils
```

**Void Linux:**
```bash
sudo xbps-install -f coreutils
```

**Валидация:**
```bash
# Проверка целостности пакета (Debian/Ubuntu)
dpkg -V coreutils
# → (нет вывода = повреждений нет)

# Проверка целостности пакета (RHEL/Fedora)
rpm -V coreutils
# → (нет вывода = повреждений нет)

# Функциональная проверка
chmod 644 /etc/hostname
```

**Когда использовать:** При массовом повреждении прав, после обновления ОС, или когда другие методы недоступны. Недостаток: требуется доступ к репозиториям и наличие места в `/var/cache`.

---

### Сценарий 7: LiveCD / Внешнее монтирование

Если система не загружается или нет доступа к интерпретаторам.

**Вариант A: LiveCD/USB**
```bash
# 1. Загрузиться с LiveCD (Ubuntu Server ISO, SystemRescueCD, Grml)
# 2. Определить корневой раздел
lsblk -f
# → sda1  ext4  /

# 3. Смонтировать корневой раздел
sudo mount /dev/sda1 /mnt

# 4. Исправить права
sudo chmod +x /mnt/bin/chmod

# 5. (Опционально) Перемонтировать в основную систему
sudo mount --bind /mnt / && sudo chroot /mnt
```

**Вариант B: Монтирование через сеть (NFS/iSCSI)**
```bash
# Если корневой раздел доступен через NFS
sudo mount -o ro server:/export/root /mnt
sudo chmod +x /mnt/bin/chmod
```

**Вариант C: Прямой доступ к блочному устройству**
```bash
# Через debugfs (ext4)
sudo debugfs -w -R 'chmod +x /bin/chmod' /dev/sda1

# Через tune2fs + debugfs (если /bin/chmod вне корня)
sudo debugfs -w /dev/sda1 -R 'ls -l /bin/chmod'
```

**Валидация:**
```bash
# После chroot в восстановленную систему
chmod --version | head -1
# → chmod (GNU coreutils) ...
```

---

### Сценарий 8: Восстановление через nsenter/unshare (Контейнеры)

В среде контейнеризации (Docker, Podman, LXC) доступ к хостовым утилитам может быть ограничен. Используйте `nsenter` для выполнения команды в контексте пространства имён PID хоста.

```bash
# Получение PID init-процесса хоста (PID 1)
HOST_PID=$(cat /proc/1/status | grep NSpid | awk '{print $NF}')

# Выполнение chmod в пространстве имён хоста
sudo nsenter -t "$HOST_PID" -m chmod 755 /bin/chmod

# Или через unshare (если nsenter недоступен)
sudo unshare --mount -- chmod 755 /bin/chmod
```

**Для Docker-контейнеров с доступом к docker.sock:**
```bash
# Запуск временного контейнера с монтированием корня
docker run --rm -it -v /:/host alpine chmod 755 /host/bin/chmod
```

**Валидация:**
```bash
stat -c '%a %n' /bin/chmod
# → 755 /bin/chmod
```

## Устранение неполадок

### Типичные ошибки и их решения

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `-bash: /bin/chmod: Permission denied` | Бит `+x` сброшен у `/bin/chmod` | `ls -l /bin/chmod` → отсутствует `x` | Любой метод восстановления из Practical Scenarios |
| `python3: command not found` | Интерпретатор не установлен или не в PATH | `which python3` | Использовать `python`, `perl`, `ld-linux`, или пакетный менеджер |
| `perl: command not found` | Perl не установлен | `which perl` | `python3`, `ld-linux`, или GCC |
| `gcc: command not found` | Компилятор не установлен | `which gcc` | Интерпретаторы, `ld-linux`, или `install` |
| `/lib64/ld-linux-x86-64.so.2: No such file` | Неверный путь к компоновщику или musl-система | `readelf -l /bin/chmod \| grep interpreter` | Уточнить архитектуру через `file /bin/chmod` |
| `cp: cannot preserve permissions` | Файловая система NFS/CIFS, `cp` не сохраняет права dest | `mount \| grep /tmp` | Использовать `install` или `cp --preserve=mode` |
| `apt/dnf/apk: command not found` | Минимальный образ без пакетного менеджера | `which apt` | Использовать `ld-linux`, интерпретаторы, или внешнее монтирование |
| `Read-only file system` | Корневой раздел смонтирован как `ro` | `mount \| grep " on / "` | `mount -o remount,rw /` (требует root) |
| `Operation not permitted` при chmod | Файл имеет атрибут `immutable` (`+i`) | `lsattr /bin/chmod` | `chattr -i /bin/chmod`, затем повторное применение метода |
| `Permission denied` от SELinux | Политика SELinux блокирует изменение прав | `ausearch -m avc -ts recent` | `setenforce 0` (временно) или корректировка политики |
| `chmod: cannot access '/bin/chmod': No such file or directory` | Файл удалён или `/bin` — симлинк на `/usr/bin` | `ls -l /bin` | Определить реальный путь: `readlink -f /bin/chmod` |
| `Text file busy` при перезапиве | Бинарник исполняется другим процессом | `lsof +L1 /bin/chmod` | Остановить процесс или использовать LiveCD |
| `No space left on device` в `/tmp` | Недостаточно места для временных файлов | `df -h /tmp` | Очистка `/tmp` или использование `$TMPDIR` на другом разделе |

### Дополнительные диагностические команды

```bash
# Определение реального пути (в системах с usrmerge)
readlink -f /bin/chmod
# → /usr/bin/chmod

# Проверка, что chmod не является частью запущенных процессов
pgrep -a chmod
# → (пустой вывод или список процессов)

# Проверка, что chmod не открыт файловыми дескрипторами
lsof /bin/chmod
# → (пустой вывод)

# Проверка, что chmod не заблокирован OOM-killer
cat /proc/sys/fs/oom_score_adj 2>/dev/null || echo "not applicable"
```

### Восстановление после частичного повреждения

Если повреждение затронуло не только `chmod`, но и другие утилиты `coreutils` (например, `cp`, `mv`, `ls`), последовательность действий:

1. Восстановить `chmod` через интерпретатор Python/Perl (он обычно менее зависим от других coreutils).
2. С помощью восстановленного `chmod` исправить права на остальные утилиты.
3. Запустить полную переустановку пакета `coreutils`.

```bash
# 1. Восстановление chmod
python3 -c 'import os; os.chmod("/usr/bin/chmod", 0o755)'

# 2. Исправление прав на cp, mv, ls
chmod 755 /bin/cp /bin/mv /bin/ls

# 3. Переустановка
apt install --reinstall coreutils  # Debian/Ubuntu
```

## Дополнительная информация

### Сводная таблица методов

| Метод | Сложность | Требования | Скорость | Надёжность |
| :--- | :--- | :--- | :--- | :--- |
| **Python/Perl/Ruby/PHP** | Низкая | Интерпретатор | Высокая | Высокая |
| **ld-linux** | Низкая | Знание пути к компоновщику | Высокая | Высокая |
| **install** | Низкая | Наличие `install` | Высокая | Высокая |
| **cp --attributes-only** | Средняя | GNU coreutils ≥ 8.32 | Высокая | Средняя |
| **Zsh/BusyBox** | Низкая | Наличие оболочки/busybox | Высокая | Высокая |
| **GCC** | Средняя | Компилятор + заголовки | Средняя | Высокая |
| **Пакетный менеджер** | Средняя | Доступ к репозиториям | Низкая | Высокая |
| **nsenter/unshare** | Средняя | Контейнерная среда | Высокая | Средняя |
| **LiveCD** | Высокая | Загрузочный носитель | Низкая | Высокая |

### Порядок применения (Best Practice)

**Для production-серверов (SRE/Sysadmin):**

1. **Python/Perl** — самый быстрый путь, минимальные зависимости.
2. **ld-linux** — если интерпретаторы отсутствуют (например, в minimal container).
3. **install** — надёжный метод с явным указанием прав.
4. **GCC** — если есть компилятор и заголовки.
5. **Пакетный менеджер** — при массовом повреждении или отсутствии других методов.
6. **nsenter/unshare** — для контейнерных сред.
7. **LiveCD** — в крайнем случае, когда система не загружается.

**Для контейнеров (Docker/Podman):**

1. **nsenter/unshare** или `docker run --rm -v /:/host` с Alpine.
2. **Python/Perl** — если образ основан на python:alpine или debian.
3. **Пакетный менеджер** — пересборка образа.

### Лучшие практики и очистка

#### Стандарты для DevOps/SRE

**Предотвращение повторения:**

- **Alias в bashrc/zshrc:** Добавить алиас для защиты рекурсивных правок:
  ```bash
  alias chmod='chmod --preserve-root'
  ```
  Это предотвращает случайное выполнение `chmod -R 755 /`, которое может сломать всю систему.

- **Configuration Management:** Управление правами через Ansible/Puppet/Chef/SaltStack:
  ```yaml
  # Ansible: обеспечение прав на chmod
  - name: Ensure /bin/chmod has correct permissions
    ansible.builtin.file:
      path: /bin/chmod
      mode: '0755'
      state: file
  ```

- **Pre-commit хуки:** В репозиториях с скриптами деплоя добавьте проверку прав:
  ```bash
  # .git/hooks/pre-commit
  find ./scripts -type f ! -executable -print
  ```

- **CI/CD валидация:** Добавьте стадию в пайплайн:
  ```yaml
  # GitLab CI
  validate_permissions:
    script:
      - find /usr/bin -type f ! -executable | grep -q . && exit 1 || echo "OK"
  ```

- **Immutable Infrastructure:** Использование принципа Immutable Infrastructure вместо изменения прав на running-инстансах. Изменения применяются на этапе сборки образа, а не на работающей системе.

#### Очистка временных файлов

После восстановления необходимо удалить все временные артефакты:

```bash
# Удаление Rescue-программ и временных файлов
rm -f /tmp/restore.c /tmp/restore /tmp/chmod_tmp /tmp/chmod_fix.*
rm -f /tmp/restore_chmod.c /tmp/restore_chmod

# Проверка, что временный файл удалён
ls /tmp/restore* 2>/dev/null || echo "Cleanup OK"
```

**Важно:** Не оставляйте rescue-программы в `/tmp` или `/var/tmp` — это снижает безопасность системы.

#### Аудит после восстановления

```bash
# Проверка целостности пакета coreutils (Debian/Ubuntu)
sudo debsums -s coreutils

# Проверка целостности пакета coreutils (RHEL/Fedora)
sudo rpm -V coreutils

# Проверка, что только ожидаемые файлы изменены
sudo find /bin /usr/bin -type f ! -executable -ls | grep -v expected
```

### Предотвращение

- Использование `chmod --preserve-root` для защиты от случайных рекурсивных правок в `/`.
- Регулярный аудит прав системных файлов (утилиты типа `debsums` или `rpm -V`).
- Внедрение принципа «immutable infrastructure» — изменения прав применяются на этапе сборки образа, а не на running-хосте.

### Крайние случаи

#### Статически скомпонованные бинарники

Если `/bin/chmod` скомпилирован статически (например, в Alpine Linux с musl или в rescue-образах), метод с `ld-linux.so` не работает. Используйте интерпретаторы или переустановку пакета.

```bash
# Проверка типа линковки
file /bin/chmod
# → /bin/chmod: ELF 64-bit ... statically linked ...
```

#### Системы NixOS / GuixSD

В NixOS и GuixSD файловая система `/bin` является символической ссылкой на `/usr/bin`, а права управляются через `/etc/static` и nix-стор. Восстановление через `chmod` невозможно — требуется переключение в другую генерацию (boot loader) или rebuild через `nixos-rebuild switch`.

#### Read-only корневой раздел

В контейнерах `distroless` или системах с `systemd` в режиме `verity` корневой раздел может быть смонтирован как `ro`. Используйте метод с `nsenter` или перемонтирование:
```bash
sudo mount -o remount,rw /
```

#### Файловые системы без поддержки POSIX-прав

На FAT32/exFAT/NTFS (через ntfs-3g) права доступа эмулируются и не сохраняются между перезагрузками. Восстановление `/bin/chmod` на такой ФС невозможно — требуется перенос файла на ext4/xfs/btrfs.

#### Контейнеры `distroless` / `scratch`

В образах `distroless` или `scratch` отсутствуют интерпретаторы, компиляторы и даже `sh`. Единственный метод — монтирование хостовой файловой системы:
```bash
docker run --rm -v /:/host alpine chmod 755 /host/bin/chmod
```

#### Атрибут immutable (`+i`)

Если на `/bin/chmod` установлен атрибут `immutable`, любые попытки изменения прав (включая `chattr`) завершатся `Operation not permitted`. Требуется:
```bash
# Сначала снять immutable (нужен root и live-режим, если /bin/chmod сломан)
sudo chattr -i /bin/chmod
# Затем восстановить права
sudo chmod 755 /bin/chmod
```

#### SELinux / AppArmor блокировка

В режиме `Enforcing` SELinux может блокировать изменение прав на системные файлы через `audit2allow`:
```bash
# Проверка блокировок
sudo ausearch -m avc -ts recent | grep chmod

# Временное разрешение (только для диагностики!)
sudo setenforce 0
sudo chmod 755 /bin/chmod
sudo setenforce 1

# Постоянное исправление политики
sudo ausearch -m avc -ts recent | audit2allow -M chmod_recovery
sudo semodule -i chmod_recovery.pp
```

#### 32-битные системы (i386) на 64-битном ядре (x32 ABI)

На системах с x32 ABI путь к компоновщику отличается:
```bash
file /bin/chmod | grep interpreter
# → interpreter /libx32/ld-linux-x32.so.2
```

### Связанные темы

- [Файловые права в Linux](../../Security/Concepts/File_Permissions/overview_definitions.md)
- [Chroot — смена корневого каталога](../../Core/chroot.md)
