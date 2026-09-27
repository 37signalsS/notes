# Права доступа, атрибуты и привилегии в Linux: Обзор

## Определения

*   **Права доступа (Permissions):** Основной механизм дискреционного контроля доступа (DAC), определяющий разрешенные операции (`чтение`, `запись`, `выполнение`) для трех категорий субъектов (`владелец`, `группа`, `остальные`).
*   **Владение (Ownership):** Атрибут файла, связывающий его с конкретным пользователем (UID) и группой (GID).
*   **Специальные права (Special Permissions):** Дополнительные биты (`SUID`, `SGID`, `Sticky Bit`), изменяющие стандартную логику выполнения файлов и управления директориями.
*   **ACL (Access Control Lists):** Расширенный механизм, позволяющий назначать гранулярные права для произвольного списка пользователей и групп вне стандартной модели.
*   **Атрибуты файлов (File Attributes):** Флаги уровня файловой системы (например, `immutable`, `append-only`), имеющие приоритет над правами даже для пользователя `root`.
*   **Umask (User File-Creation Mask):** Маска, определяющая биты прав, которые будут автоматически сброшены (запрещены) при создании новых объектов.
*   **Linux Capabilities:** Механизм гранулярного разделения полномочий суперпользователя на атомарные единицы (например, только право на привязку к низким портам). Делит монолитные привилегии `root` на ~40+ независимых категорий.
*   **File Capabilities:** Расширенные атрибуты (xattr), позволяющие назначать capabilities конкретным бинарным файлам. Альтернатива SUID-биту, не дающая полные привилегии.
*   **LSM (Linux Security Modules):** Фреймворк ядра для реализации систем принудительного контроля доступа (MAC), таких как SELinux и AppArmor. Централизованная политика безопасности, недоступная обычным пользователям.
*   **User Namespace:** Механизм изоляции идентификаторов пользователей (UID/GID) внутри контейнеров, позволяющий непривилегированному процессу иметь UID 0 внутри контейнера без привилегий на хосте.

## Базовые концепции

### 1. Стандартная модель прав доступа (DAC)

**Discretionary Access Control (DAC)** — модель, в которой управление доступом к объекту остается на усмотрение его владельца. В Linux это реализуется через систему битов `rwx`.

#### Ограничения модели DAC

| Проблема | Описание | Метод компенсации |
| :--- | :--- | :--- |
| **Бинарность привилегий** | Либо бесправный пользователь, либо всемогущий `root` | Linux Capabilities |
| **Трудоёмкость настройки** | Группы не всегда позволяют гибко настроить доступ многим людям | ACL |
| **Проблема распространения** | Пользователь с правом `r` может скопировать файл и выдать любые права | MAC (SELinux/AppArmor) |
| **Уязвимость владельца** | Если процесс владельца взломан, атакующий получает доступ ко всем его файлам | Контейнеризация, изоляция |

**Принцип "Запрещено по умолчанию":** В целях безопасности доступ должен предоставляться только явно. Суперпользователь `root` (UID 0) обходит большинство проверок DAC, что делает его критической точкой отказа системы.

### 2. Управление владением (chown, chgrp)

Каждый файл и директория в Linux связаны с UID владельца и GID группы.

*   **`chown` (Change Owner):** Смена владельца. Команда `sudo chown user:group file` позволяет сменить обоих одновременно. Только `root` может отдавать файлы другим пользователям.
*   **`chgrp` (Change Group):** Смена группы. Владелец может сменить группу файла на ту, в которой сам состоит.
*   **Рекурсия:** Флаг `-R` применяет изменения ко всем вложенным объектам.

### 3. Linux Capabilities (Гранулярные привилегии)

capabilities позволяют предоставлять процессам специфические права `root` без выдачи полного UID 0.
*   `CAP_NET_BIND_SERVICE`: Позволяет слушать привилегированные порты (< 1024).
*   `CAP_SYS_TIME`: Позволяет изменять системное время.
*   `CAP_DAC_OVERRIDE`: Позволяет обходить проверки прав доступа (аналог `root` для ФС).
*   `CAP_CHOWN`: Позволяет изменять владение файлов без ограничений.
*   `CAP_KILL`: Позволяет посылать сигналы любым процессам (включая `root` процессы).
*   `CAP_SETUID`/`CAP_SETGID`: Позволяют изменять UID/GID процесса без ограничений.

**File Capabilities vs Process Capabilities:**
*   **Process capabilities** — хранятся в ядерной памяти, назначаются при запуске через `execve()` или `setcap`.
*   **File capabilities** — хранятся в расширенных атрибутах (xattr) бинарного файла, передаются процессу при выполнении.

**Механизм работы:**
1. При выполнении бинарника ядро проверяет наличие file capabilities в xattr.
2. Если есть — добавляет их к процессу (включая `effective` и `permitted` наборы).
3. Процесс получает точные привилегии, но не полный доступ `root`.

**Практическое применение (SRE/DevOps):**
*   Замена SUID-бинарников (например, `ping`, `mount`) на file capabilities.
*   Ограничение привилегий контейнеров через `--cap-drop` и `--cap-add`.
*   Настройка доступа к привилегированным ресурсам без выдачи root.

**Аналогия:** SUID дает ключ от всех дверей дома, capabilities — только от конкретной двери.

**Таблица: SUID vs File Capabilities**

| Характеристика | SUID | File Capabilities |
| :--- | :--- | :--- |
| Уровень привилегий | Полный UID 0 | Точные capabilities |
| Риск | Высокий (компрометация = root) | Низкий (ограниченный доступ) |
| Управление | Бит на файле | xattr + setcap/getcap |
| Современный стандарт | Устаревший | Рекомендуется |
| Пример | `/usr/bin/passwd` | `/usr/bin/ping cap_net_raw=ep` |

**Команды управления:**
```bash
# Установить capabilities на бинарник
sudo setcap cap_net_bind_service=ep /usr/local/bin/myapp

# Проверить capabilities файла
getcap /usr/local/bin/myapp

# Удалить capabilities
sudo setcap -r /usr/local/bin/myapp

# Проверить capabilities процесса
cat /proc/PID/status | grep Cap
capsh --print
```

**Интеграция с контейнеризацией (Docker):**
```bash
# Удалить все capabilities по умолчанию
docker run --cap-drop=ALL myapp

# Добавить конкретные capabilities
docker run --cap-add=NET_BIND_SERVICE --cap-add=SYS_TIME myapp

# Проверить capabilities контейнера
docker inspect myapp | grep -i cap
```

**Интеграция с systemd:**
```ini
# /etc/systemd/system/myapp.service
[Service]
# Удалить все capabilities
CapabilityBoundingSet=
# Добавить конкретные
AmbientCapabilities=CAP_NET_BIND_SERVICE CAP_SYS_PTRACE
# Запретить получение новых привилегий
NoNewPrivileges=yes
```

Подробнее: **[Linux Capabilities](../../Mechanisms/Capabilities.md)**.

### 4. Представление прав доступа

Права отображаются в выводе `ls -l` или через `stat`.

#### Символьное представление
Пример: `drwxr-xr-x`
1.  **Тип файла (1-й символ):** `-` (файл), `d` (директория), `l` (ссылка), `c`/`b` (устройства), `s` (сокет), `p` (канал).
2.  **Триады прав:**
    *   `u` (владелец): первые три бита (`rwx`).
    *   `g` (группа): средние три бита (`r-x`).
    *   `o` (остальные): последние три бита (`r-x`).

#### Числовое (восьмеричное) представление
Рассчитывается как сумма весов битов: `r=4`, `w=2`, `x=1`.
*   `7` (4+2+1) — полный доступ.
*   `6` (4+2) — чтение и запись.
*   `5` (4+1) — чтение и выполнение.
*   `4` — только чтение.

**Использование stat:** Для быстрого получения числовых прав используйте `stat -c "%a" file`.

### 5. Маска создания файлов (umask)

**Umask** — это системный фильтр. При создании объекта ядро вычитает значение маски из максимально возможных прав:
*   **Файлы:** `666` (макс) - `umask` = результат.
*   **Директории:** `777` (макс) - `umask` = результат.

*Пример:* При `umask 022` новый файл получит `644` (`rw-r----`), а директория `755` (`rwxr-xr-x`).

#### Практические сценарии настройки umask (DevOps/SRE)

**1. Установка umask для service-аккаунтов (SRE)**
Системные пользователи (например, `www-data`, `postgres`) должны получать предсказуемые права при создании файлов. Настройка через `/etc/login.defs`:

```bash
# /etc/login.defs — глобальная маска для новых пользователей
UMASK 027  # Файлы: 640, директории: 750
```

Для конкретного сервиса — через systemd unit:

```ini
# /etc/systemd/system/myapp.service
[Service]
UMask=0077  # Файлы: 600, директории: 700 (только владелец)
User=myapp
```

**2. Установка через PAM (после входа в систему)**
Для интерактивных сессий — через `pam_umask.so`:

```bash
# /etc/pam.d/common-session или /etc/pam.d/sshd
session required pam_umask.so 027
```

**3. Проверка текущей маски и её влияния**
```bash
# Текущее значение
umask
# → 0022

# Прогноз: какой права получит новый файл/директория
# umask 022: файл 666-022=644, директория 777-022=755
# umask 027: файл 666-027=640, директория 777-027=750
# umask 077: файл 666-077=600, директория 777-077=700
```

**4. Сценарий: развертывание веб-приложения (DevOps)**
При копировании файлов деплоя важно сохранять права. Используйте `install` вместо `cp`:

```bash
# Неправильно: cp применяет umask, права могут быть открытыми
cp -r ./app/ /var/www/html/

# Правильно: install задаёт права явно
install -d -m 755 /var/www/html/
install -m 644 ./app/index.html /var/www/html/
install -m 600 ./app/.env /var/www/html/  # Секреты — только владелец
```

**5. Контейнеры и umask**
В Docker-контейнерах umask по умолчанию — `022`. Для ужесточения:

```dockerfile
# Dockerfile
RUN mkdir -p /var/app && umask 077 && \
    wget -O /var/app/config.yml https://internal/config.yml && \
    chmod 600 /var/app/config.yml
```

Или через ENTRYPOINT с явной установкой:

```bash
#!/bin/bash
umask 077  # Файлы создаются только с правами 600
exec /usr/bin/myapp
```

**Таблица: рекомендуемые umask по типам ресурсов**

| Сценарий | umask | Файлы | Директории | Применение |
| :--- | :--- | :--- | :--- | :--- |
| Разработка | `022` | `644` | `755` | Стандарт, совместная работа |
| Производство (SRE) | `027` | `640` | `750` | Групповой доступ, чужие исключены |
| Секреты/ключевые файлы | `077` | `600` | `700` | Только владелец |
| Общие папки (tmp) | `077` + sticky | `600` | `700` | Временные файлы |

Конфигурация: `/etc/login.defs`, `~/.bashrc`, `pam_umask.so`, systemd `UMask=`.

#### Практические сценарии: настройка прав доступа для DevOps/SRE/Sysadmin

**Сценарий 1: Развертывание веб-приложения (DevOps)**
```bash
# 1. Создать структуру директорий с правильными правами
sudo mkdir -p /var/www/html/{logs,uploads,config}

# 2. Установить права: директории 755, файлы 644
sudo chown -R www-data:www-data /var/www/html
sudo find /var/www/html -type d -exec chmod 755 {} +
sudo find /var/www/html -type f -exec chmod 644 {} +

# 3. Защитить конфигурационные файлы
sudo chmod 600 /var/www/html/config/.env
sudo chmod 600 /var/www/html/config/database.yml

# 4. Настроить доступ к логам (только для чтения)
sudo chmod 750 /var/www/html/logs
sudo chown www-data:www-data /var/www/html/logs

# 5. Проверить результат
ls -la /var/www/html/
# → drwxr-xr-x 1 www-data www-data ... .
# → drwxr-xr-x 1 www-data www-data ... config/
# → -rw------- 1 www-data www-data ... config/.env
# → drwxr-xr-x 1 www-data www-data ... logs/
```

**Сценарий 2: Настройка доступа к базе данных (SRE)**
```bash
# 1. Создать системного пользователя для БД
sudo useradd -r -M -s /usr/sbin/nologin postgres

# 2. Установить права на данные
sudo mkdir -p /var/lib/postgresql/data
sudo chown -R postgres:postgres /var/lib/postgresql/data
sudo chmod 700 /var/lib/postgresql/data

# 3. Защитить конфигурацию
sudo chmod 600 /etc/postgresql/15/main/pg_hba.conf
sudo chmod 600 /etc/postgresql/15/main/postgresql.conf

# 4. Настроить доступ через ACL (если нужно несколько пользователей)
sudo setfacl -m u:backup:r-- /var/lib/postgresql/data/
sudo setfacl -d -m u:backup:r-- /var/lib/postgresql/data/

# 5. Проверить права
sudo -u postgres ls -la /var/lib/postgresql/data/
sudo getfacl /var/lib/postgresql/data/
```

**Сценарий 3: Управление доступом к SSH-ключам (Sysadmin)**
```bash
# 1. Проверить текущие права на SSH-директории
ls -la ~/.ssh/
# → drwx------ 1 user user ... .ssh/
# → -rw------- 1 user user ... id_rsa
# → -rw-r--r-- 1 user user ... id_rsa.pub
# → -rw------- 1 user user ... config

# 2. Правильные права по умолчанию
chmod 700 ~/.ssh/
chmod 600 ~/.ssh/id_rsa
chmod 644 ~/.ssh/id_rsa.pub
chmod 600 ~/.ssh/config
chmod 600 ~/.ssh/authorized_keys

# 3. Защита от несанкционального доступа (immutable)
sudo chattr +i ~/.ssh/authorized_keys

# 4. Проверить через stat
stat -c "%a %A %n" ~/.ssh/id_rsa
# → 600 -rw------- ~/.ssh/id_rsa
```

**Сценарий 4: Настройка общих папок для команды (Sysadmin)**
```bash
# 1. Создать группу разработчиков
sudo groupadd developers
sudo usermod -a -G developers alice
sudo usermod -a -G developers bob

# 2. Создать общую папку с SGID
sudo mkdir /shared/projects
sudo chown root:developers /shared/projects
sudo chmod 2770 /shared/projects  # SGID + rwx для группы

# 3. Установить default ACL для наследования
sudo setfacl -d -m u::rwx,g::rwx,o::--- /shared/projects
sudo setfacl -d -m g:developers:rwx /shared/projects

# 4. Настроить umask для пользователей (чтобы новые файлы были приватными)
# В ~/.bashrc каждого пользователя:
# umask 027

# 5. Проверить результат
ls -la /shared/projects/
getfacl /shared/projects/
```

**Сценарий 5: Защита временных файлов (SRE)**
```bash
# 1. Настроить /tmp и /var/tmp с sticky bit
chmod 1777 /tmp
chmod 1777 /var/tmp

# 2. Создать отдельную tmpfs для приложения
sudo mkdir -p /run/myapp
sudo mount -t tmpfs -o size=100M,mode=1777,uid=myapp,gid=myapp tmpfs /run/myapp

# 3. Добавить в fstab для постоянства
# echo "tmpfs /run/myapp tmpfs size=100M,mode=1777,uid=myapp,gid=myapp 0 0" >> /etc/fstab

# 4. Проверить монтирование
mount | grep /run/myapp
# → tmpfs on /run/myapp type tmpfs (rw,relatime,size=102400k,mode=777)
```

## Практические сценарии

### Примеры использования chmod и chown

```bash
# Сделать скрипт исполняемым для всех
chmod +x script.sh

# Полный доступ владельцу, чтение группе, остальным ничего
chmod 740 secret.txt

# Рекурсивная смена владельца и группы для веб-проекта
sudo chown -R www-data:www-data /var/www/html

# Установка прав: директории 755, файлы 644 (стандарт безопасности)
find /path -type d -exec chmod 755 {} +
find /path -type f -exec chmod 644 {} +
```

### Диагностика: почему chmod 777 не всегда решает проблему

Если после `chmod 777` доступ всё ещё запрещён, проверьте следующие факторы:

#### 1. Расширенные права ACL
*   **Диагностика:** `getfacl /path/to/file`.
*   **Решение:** `setfacl -b` для удаления всех ACL.

#### 2. Принудительный контроль доступа (SELinux / AppArmor)
MAC-системы блокируют доступ на основе меток контекста, даже если DAC разрешает его.
*   **Диагностика SELinux:** `ls -Z`, `ausearch -m avc -ts recent`.
*   **Диагностика AppArmor:** `aa-status`, `journalctl | grep apparmor`.

#### Практические сценарии: SELinux и AppArmor в DevOps/SRE

**Сценарий 10: Настройка SELinux для веб-сервера (SRE)**
```bash
# 1. Проверить текущий контекст файлов
ls -Z /var/www/html/
# → -rw-r--r-- 1 root root system_u:object_r:httpd_sys_content_t:s0 index.html

# 2. Проверить, разрешено ли nginx читать файлы
getenforce
# → Enforcing (или Permissive)

# 3. Проверить AVC denied логи
sudo ausearch -m avc -ts recent
# → type=AVC ... denied { read } for pid=... comm="nginx" ... path="/var/www/html/secret.txt"

# 4. Изменить контекст для доступа nginx
sudo chcon -t httpd_sys_content_t /var/www/html/secret.txt

# 5. Постоянная настройка через policy (семантический контекст)
sudo semanage fcontext -a -t httpd_sys_content_t "/var/www/html/secret(/.*)?"
sudo restorecon -R /var/www/html/secret

# 6. Проверить результат
ls -Z /var/www/html/secret.txt
# → -rw-r--r-- 1 root root system_u:object_r:httpd_sys_content_t:s0 secret.txt
```

**Сценарий 11: Отладка AppArmor профиля для приложения (DevOps)**
```bash
# 1. Проверить статус AppArmor
sudo aa-status
# → apparmor profile is enabled.
# → 1 profiles are loaded.
# → 0 profiles are in enforce mode.
# → 0 profiles are in complain mode.

# 2. Проверить, какой профиль применён к процессу
cat /proc/1234/attr/current
# → /usr/sbin/nginx (enforce)

# 3. Проверить логи нарушений
sudo journalctl -u apparmor -f
# → apparmor[1234]: DENIED [write] /var/log/nginx/access.log

# 4. Обновить профиль (режим complain для отладки)
sudo aa-complain /etc/apparmor.d/usr.serve.nginx

# 5. Проверить логи и добавить разрешения
sudo aa-logprof  # Интерактивный анализ логов

# 6. Перевести в enforce mode после настройки
sudo aa-enforce /etc/apparmor.d/usr.serve.nginx
```

**Сценарий 12: Управление SELinux в контейнерах (DevOps)**
```bash
# 1. Проверить, включен ли SELinux в контейнере
docker run --rm -it alpine cat /proc/1/attr/current
# → (если пусто — SELinux не применился к контейнеру)

# 2. Запустить контейнер с SELinux метками
docker run --rm -it --security-opt label=type:spc_t alpine bash

# 3. Проверить контекст файлов в контейнере
docker run --rm -it --security-opt label=type:spc_t alpine ls -Z /
# → drwxr-xr-x 1 root root system_u:object_r:spc_t:s0 bin

# 4. На хосте проверить, что SELinux блокирует доступ к volume
sudo ls -Z /var/lib/docker/volumes/myapp/_data/
# → drwxr-xr-x 1 root root system_u:object_r:container_var_lib_t:s0 myapp
```

#### 3. Иерархия директорий (Принцип проходимости)
Для доступа к объекту нужны права на выполнение (`x`) на **все** родительские директории в пути.
*   **Диагностика:** `namei -l /full/path/to/file` — покажет права на каждый сегмент пути.

#### 4. Несоответствие пользователя процесса
Процесс (например, nginx или postgres) может работать от имени пользователя, не входящего в нужную группу.
*   **Диагностика:** `ps aux | grep <process>`, проверка `id <user>`.

#### 5. Атрибут неизменяемости (Immutable)
Атрибут `i` блокирует любые изменения даже для `root`.
*   **Диагностика:** `lsattr /path/to/file`.
*   **Решение:** `sudo chattr -i /path/to/file`.

#### 6. Ограничивающие опции монтирования
Опции `noexec`, `nosuid`, `nodev` или `ro` в `/etc/fstab` блокируют действия на уровне файловой системы.
*   **Диагностика:** `findmnt -T /path/to/file` (колонка `OPTIONS`).

#### 7. Особенности NFS (root_squash)
На NFS-шарах запросы от `root` клиента могут мапиться в `nobody` на сервере.
*   **Диагностика:** Проверка `/etc/exports` на сервере.

#### 8. Ошибки интерпретатора (Shebang)
Неверный путь в первой строке скрипта или формат Windows (CRLF) вызывают ошибку `Permission denied` или `No such file`.
*   **Диагностика:** `file script.sh`, `head -1 script.sh | cat -A` (ищите `^M`).
*   **Решение:** `dos2unix script.sh`.

#### 9. Битая символическая ссылка
Ссылка указывает на несуществующий файл или на файл, к которому нет доступа.
*   **Диагностика:** `ls -LH /path/to/link` (флаг `-L` разыменовывает ссылку).

#### 10. Файловая система в режиме Read-Only
Из-за ошибок ФС или настроек монтирования раздел может перейти в `ro`.
*   **Диагностика:** `mount | grep " (ro,"`.

#### 11. Скрытые символы в именах
Лишние пробелы или непечатаемые символы в именах файлов.
*   **Диагностика:** `ls -b` (экранирование), `ls -Q` (кавычки).

#### 12. Пользовательские пространства имен (User Namespaces)
В контейнерах (Docker/LXC) UID внутри может не совпадать с UID на хосте из-за `userns-remap`.
*   **Диагностика:** Проверка маппинга в конфигурации демона контейнеризации.

#### Практические сценарии диагностики (DevOps/SRE)

**Сценарий 1: Процесс не может прочитать конфиг (SRE)**
```bash
# 1. Проверить, от какого пользователя запущен процесс
ps aux | grep nginx
# → nginx    1234  ... /usr/sbin/nginx

# 2. Проверить права на конфиг и цепочку директорий
namei -l /etc/nginx/nginx.conf
# → drwxr-xr-x / 
#   drwxr-xr-x /etc 
#   drwxr-xr-x /etc/nginx 
#   -rw-r-- 1 root root ... /etc/nginx/nginx.conf

# 3. Проверить, есть ли ACL или SELinux
ls -Z /etc/nginx/nginx.conf
getfacl /etc/nginx/nginx.conf

# 4. Проверить опции монтирования
findmnt -T /etc/nginx/nginx.conf
```

**Сценарий 2: Контейнер не может писать в том (DevOps)**
```bash
# 1. Проверить права на хосте
ls -la /var/lib/docker/volumes/myapp_data/_data/
# → drwxr-xr-x 1 root root ... (права 755)

# 2. Проверить, какой UID использует контейнер
docker inspect myapp | grep -i user
# → "User": "1000"

# 3. Проверить, не монтирован ли раздел с ro
findmnt -T /var/lib/docker/volumes/myapp_data/_data/

# 4. Проверить, нет ли immutable-атрибута
lsattr /var/lib/docker/volumes/myapp_data/_data/

# 5. Решение: создать директорию с правильными правами
sudo mkdir -p /var/lib/docker/volumes/myapp_data/_data
sudo chown 1000:1000 /var/lib/docker/volumes/myapp_data/_data
sudo chmod 755 /var/lib/docker/volumes/myapp_data/_data
```

**Сценарий 3: Скрипт деплоя падает с "Permission denied" (DevOps)**
```bash
# 1. Проверить права на скрипт
ls -la deploy.sh
# → -rw-r--r-- 1 deploy deploy ... deploy.sh  (нет x!)

# 2. Проверить shebang
head -1 deploy.sh | cat -A
# → #!/bin/bash$  (или ^M$ — проблема CRLF)

# 3. Проверить, не монтирован ли раздел с noexec
findmnt -T /home/deploy/deploy.sh

# 4. Решение:
chmod +x deploy.sh
file deploy.sh  # Проверка формата
```

**Сценарий 4: Аудит безопасности прав доступа (SRE)**
```bash
# 1. Поиск всех world-writable файлов (риск)
sudo find / -type f -perm -0002 -ls 2>/dev/null | head -20

# 2. Поиск всех SUID/SGID бинарников
sudo find / -type f \( -perm -4000 -o -perm -2000 \) -ls 2>/dev/null

# 3. Проверка immutable-файлов (защита от изменения)
sudo lsattr /etc/passwd /etc/shadow /etc/sudoers

# 4. Проверка ACL на критичные файлы
sudo getfacl /etc/shadow
```

**Сценарий 5: Устранение проблем с доступом к общей папке (Sysadmin)**
```bash
# 1. Проверить права на папку
ls -la /shared/
# → drwxrwx--- 1 root developers ... /shared/

# 2. Проверить, состоит ли пользователь в группе
id alice
# → uid=1000(alice) gid=1000(alice) groups=1000(alice),1001(developers)

# 3. Проверить цепочку директорий
namei -l /shared/project/file.txt

# 4. Проверить umask пользователя
sudo -u alice bash -c 'umask'
# → 0022

# 5. Проверить, нет ли ACL, которые блокируют доступ
getfacl /shared/
```

#### Практические сценарии: настройка ACL, атрибутов, capabilities (DevOps/SRE)

**Сценарий 6: Настройка гранулярного доступа к конфигу (SRE)**
```bash
# Ситуация: конфиг должен быть доступен только конкретным пользователям/группам
# Стандартные права (750) не достаточны — нужен доступ только для alice и bob, но не для остальных группы

# 1. Создать ACL с точным контролем
setfacl -m u:alice:rw-,u:bob:r--,g:devops:--- /app/config.yml
# alice: чтение+запись, bob: только чтение, devops: нет доступа

# 2. Установить default ACL для директории (наследование)
setfacl -d -m u:deployer:rw-,g:appreaders:r-- /app/

# 3. Проверить результат
getfacl /app/config.yml
# → user::rw- (владелец)
# → user:alice:rw- (доступ alice)
# → user:bob:r-- (доступ bob)
# → group::r-x (группа)
# → group:devops:--- (запрет для группы)
# → mask::rw- (максимальные права)
# → other::--- (остальные — нет доступа)

# 4. Проверить, что права отображаются в ls -l
ls -l /app/config.yml
# → -rw-r--r--+ 1 root root ... /app/config.yml
# (знак + указывает на наличие ACL)
```

**Сценарий 7: Защита критических файлов через immutable (Sysadmin)**
```bash
# Ситуация: предотвратить изменение системных файлов даже root-процессам

# 1. Установить immutable на критичные файлы
sudo chattr +i /etc/passwd
sudo chattr +i /etc/shadow
sudo chattr +i /etc/sudoers
sudo chattr +i /etc/hosts

# 2. Проверить атрибуты
lsattr /etc/passwd
# → ----i-------- /etc/passwd (атрибут immutable установлен)

# 3. Попытаться изменить (даже как root)
sudo echo "test" >> /etc/passwd
# → Operation not permitted

# 4. Временно снять для обновления
sudo chattr -i /etc/passwd
# ... выполнить изменения ...
sudo chattr +i /etc/passwd

# 5. Защита логов от стирания (append-only)
sudo chattr +a /var/log/syslog
# → Дозапись разрешена, но удаление/перезапись запрещена
```

**Сценарий 8: Настройка capabilities вместо SUID (SRE)**
```bash
# Ситуация: бинарник нуждается в привилегиях, но SUID — риск безопасности

# 1. Проверить текущие capabilities бинарника
getcap /usr/bin/ping
# → /usr/bin/ping cap_net_raw=ep

# 2. Установить capabilities вместо SUID
# Удалить SUID-бит
sudo chmod u-s /usr/local/bin/myapp
# Установить нужные capabilities
sudo setcap cap_net_bind_service=ep /usr/local/bin/myapp

# 3. Проверить результат
getcap /usr/local/bin/myapp
# → /usr/local/bin/myapp cap_net_bind_service=ep

# 4. Проверить, что бинарник работает без root
sudo -u nobody /usr/local/bin/myapp

# 5. Список всех бинарников с capabilities
sudo getcap -r /usr/ 2>/dev/null | head -20
```

**Сценарий 9: Проверка соответствия прав доступа стандартам безопасности (SRE)**
```bash
# 1. Проверить, что нет world-writable файлов
sudo find /etc -type f -perm -0002 2>/dev/null
# → (пусто — хорошо)

# 2. Проверить, что нет SUID-файлов, которых не должно быть
sudo find / -type f -perm -4000 -not -path "/usr/bin/*" -not -path "/usr/lib/*" 2>/dev/null
# → (пусто — хорошо)

# 3. Проверить права на ключевые файлы
sudo stat -c "%a %A %n" /etc/shadow /etc/sudoers /etc/passwd
# → 000 ---... /etc/shadow
# → 440 r--r----- /etc/sudoers
# → 644 rw-r--r-- /etc/passwd

# 4. Проверить, что sticky bit установлен на общие директории
sudo find / -type d -perm -1000 -ls 2>/dev/null
# → drwxrwxrwt /tmp
# → drwxrwxrwt /var/tmp
# → drwxrwxrwt /shared/
```

#### Практические сценарии: User Namespaces и контейнерная безопасность

**Сценарий 10: Настройка User Namespaces в Docker (DevOps)**
```bash
# 1. Проверить, включены ли User Namespaces в демоне Docker
docker info | grep -i userns
# → Security Features: seccomp, userns-remap

# 2. Включить userns-remap в daemon.json
# /etc/docker/daemon.json
# {
#   "userns-remap": "default"
# }

# 3. Перезапустить Docker daemon
sudo systemctl restart docker

# 4. Проверить маппинг UID
cat /etc/subuid
# → docker:100000:65536
cat /etc/subgid
# → docker:100000:65536

# 5. Запустить контейнер с user namespace
docker run --rm -it alpine id
# → uid=0(root) gid=0(root) groups=0(root),65534(nobody)
# (UID 0 внутри контейнера = UID 100000 на хосте)

# 6. Проверить маппинг на хосте
docker inspect myapp | grep -i userns
# → "UsernsMode": "host"
```

**Сценарий 11: Защита контейнера через capability dropping (SRE)**
```bash
# 1. Запустить контейнер без всех capabilities
docker run --cap-drop=ALL --rm -it alpine bash

# 2. Проверить, какие capabilities остались
cat /proc/self/status | grep Cap
# → CapEff: 0000000000000000 (нет capabilities)

# 3. Добавить конкретные capabilities
docker run --cap-add=NET_BIND_SERVICE --cap-add=SYS_TIME myapp

# 4. Проверить capabilities процесса
docker exec myapp cat /proc/self/status | grep CapEff
# → CapEff: 00000000000000000000000000000002 (только NET_BIND_SERVICE)

# 5. Проверить через capsh
docker exec myapp capsh --print
# → Current: =ep cap_net_bind_service
```

**Сценарий 12: Настройка AppArmor/Docker для изоляции (SRE)**
```bash
# 1. Создать профиль AppArmor для контейнера
cat > /etc/apparmor.d/docker-myapp <<EOF
#include <tunables/global>

profile docker-myapp flags=(attach_disconnected) {
  #include <abstractions/base>
  
  # Разрешить доступ только к конкретным ресурсам
  network inet tcp,
  network inet udp,
  /var/log/myapp/** rw,
  /etc/myapp/config rw,
  /usr/bin/myapp rix,
  ~/** rix,
}
EOF

# 2. Перезагрузить AppArmor
sudo apparmor_parser -r /etc/apparmor.d/docker-myapp

# 3. Запустить контейнер с профилем
docker run --security-opt apparmor=docker-myapp myapp

# 4. Проверить, что профиль применяется
docker inspect myapp | grep -i apparmor
```

## Чек-лист диагностики

| Команда | Объект проверки |
| :--- | :--- |
| `namei -l <path>` | Проверка прав по всей цепочке каталогов |
| `getfacl <file>` | Наличие расширенных правил ACL |
| `lsattr <file>` | Специфические атрибуты (например, `i` - immutable) |
| `ls -Z <file>` | Контекст безопасности SELinux |
| `findmnt -T <path>` | Опции монтирования (`noexec`, `ro`, `nosuid`) |
| `stat <file>` | Полные метаданные (UID, GID, восьмеричные права) |
| `ps aux \| grep <proc>` | Пользователь, от имени которого запущен процесс |
| `head -1 <script> \| cat -A` | Корректность Shebang и отсутствие CRLF |

## Дополнительная информация

*   **Inode:** Метаданные (права, владельцы) хранятся в индексном дескрипторе файла. Подробнее: **[Inode и ссылки](../../../FileSystems/links_inodes_dentries.md)**.
*   **Поведение cp:** По умолчанию `cp` применяет текущий `umask`. Для сохранения прав используйте `cp -p` или `cp -a`.
*   **Связь с пользователями:** Модель DAC неразрывно связана с **[управлением пользователями](../../../SystemAdministration/users_management.md)**.
*   **Специальные права:** Подробный разбор SUID/SGID/Sticky Bit см. в **[отдельном документе](./special_permissions.md)**.

#### Практические сценарии: Extended Attributes (xattr) и метаданные

**Сценарий 13: Работа с расширенными атрибутами (xattr) (DevOps/SRE)**
```bash
# 1. Просмотреть все xattr файла
getfattr -d /path/to/file
# → # file: /path/to/file
# → security.capability="..."

# 2. Просмотреть только системные namespace
getfattr -n security.capability /path/to/file

# 3. Установить xattr (например, security label)
sudo setfattr -n user.custom_attr -v "value123" /path/to/file

# 4. Проверить установленный атрибут
getfattr -n user.custom_attr /path/to/file
# → /path/to/file: user.custom_attr="value123"

# 5. Удалить атрибут
sudo setfattr -x user.custom_attr /path/to/file

# 6. Проверить, что xattr хранятся в filesystem
ls -l /path/to/file
# → -rw-r--r-- 1 root root ... /path/to/file
# (xattr не видимы в стандартном ls, только через getfattr)

# 7. Критично для контейнеров: проверить capabilities
getcap -r /var/lib/docker/ 2>/dev/null | head -10
```

**Сценарий 14: Форенсика и аудит через метаданные (SRE)**
```bash
# 1. Полный дамп метаданных
stat /path/to/suspicious_file
# →  File: ...
# →  Size: ...            Blocks: ... IO Block: ... regular file
# →  Device: ...          Inode: ...           Links: 1
# →  Access: (644/-rw-r--r--)  Uid: (1000/user)   Gid: (1000/group)
# →  Access: 2024-01-15 10:30:00.000000000 +0000
# →  Modify: 2024-01-15 10:30:00.000000000 +0000
# →  Change: 2024-01-15 10:30:00.000000000 +0000
# →  Birth: 2024-01-15 10:29:00.000000000 +0000

# 2. Проверить, изменились ли атрибуты (chattr)
lsattr /path/to/suspicious_file
# → ----i-------- /path/to/suspicious_file (immutable!)

# 3. Проверить, есть ли ACL (признак нестандартного доступа)
getfacl /path/to/suspicious_file
# → # file: /path/to/suspicious_file
# → # owner: root
# → # group: root
# → user::rw-
# → user:hacker:rw-  (подозрный пользователь!)

# 4. Проверить контекст SELinux
ls -Z /path/to/suspicious_file
# → -rw-r--r-- 1 root root system_u:object_r:unlabeled_t:s0 file

# 5. Отследить изменения через auditd
sudo ausearch -m avc -ts recent | grep /path/to/suspicious_file
```
