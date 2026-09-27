# База данных установленных пакетов

## Определения

Ниже приведены основные термины, описывающие внутренние механизмы хранения информации о программном обеспечении в дистрибутивах Linux.

**База данных пакетов (Package Database)** — централизованное системное хранилище информации об установленных, удалённых и доступных пакетах. Содержит метаданные, списки файлов, статусы, зависимости и конфигурационные скрипты. Для DevOps/SRE инженеров целостность БД пакетов — критический параметр: её повреждение делает невозможным установку обновлений и аудит соответствия baseline.

**DPKG Database** — текстовая база данных в дистрибутивах на базе DEB. Основной файл — `/var/lib/dpkg/status`, представляющий собой плоский текстовый файл в формате RFC822. Дополнительные каталоги `/var/lib/dpkg/info/` и `/var/lib/dpkg/triggers/` хранят списки файлов, хеши и скрипты жизненного цикла.

**RPM Database** — структурированное хранилище в дистрибутивах на базе RPM. В современных системах (RHEL 9+, Fedora 33+, AlmaLinux 9+) используется формат **SQLite** (`/var/lib/rpm/rpmdb.sqlite`), в устаревших (RHEL 7, CentOS 7) — Berkeley DB (BDB) с файлами `Packages` и `__db.*`.

**Файл блокировки (Lock file)** — механизм предотвращения состояния гонки (race condition), запрещающий одновременную модификацию базы данных несколькими процессами (например, одновременный запуск двух экземпляров `apt`). Блокировки реализуются через advisory-блокировки `fcntl(2)` или `flock`.

**Триггер (Trigger)** — механизм deferred-execution в DEB, позволяющий пакету зарегистрировать действие, которое выполняется при установке/удалении других пакетов (например, обновление кеша иконок или `ldconfig`).

**Аварийное завершение транзакции (Interrupted Transaction)** — состояние, при котором пакет остался в промежуточном состоянии (`half-installed`, `half-configured`) из-за сбоя питания, `SIGKILL` или перезагрузки во время установки/удаления.

---

## Основные концепции

### Принцип работы базы данных пакетов

База данных пакетов — не просто список установленного ПО. Это транзакционное хранилище, обеспечивающее:

1. **Атомарность:** Установка/удаление пакета либо полностью завершается, либо откатывается. Частично установленный пакет фиксируется в БД с промежуточным статусом.
2. **Целостность:** Каждый пакет имеет запись с контрольными суммами файлов (`.md5sums` в DEB, заголовок в RPM). Изменение файла без обновления БД фиксируется при верификации.
3. **Обратимость:** DEB хранит `status-old`, RPM ведет историю транзакций. Это позволяет откатить изменения или восстановить повреждённую БД.
4. **Зависимости:** БД содержит полный граф зависимостей, что позволяет пакетным менеджерам вычислять конфликты и разрешать их перед установкой.

### Структура базы данных DPKG

Располагается в `/var/lib/dpkg/`. Ключевые файлы и каталоги:

- **status**: Единственный критически важный файл. Содержит записи о каждом пакете в формате RFC822 (пустые строки разделяют записи).
  - Структура статуса: `Status: <selection> <flag> <status>` (например, `install ok installed`).
  - `selection`: `install`, `hold`, `deinstall`, `purge`.
  - `status`: `installed`, `half-installed`, `unpacked`, `half-configured`, `config-files`, `not-installed`.
- **info/**: Директория со вспомогательными данными:
  - `.list`: Список всех файлов пакета (используется для `dpkg -L`).
  - `.md5sums`: Хеши файлов для проверки целостности.
  - `.postinst`, `.prerm` и др.: Скрипты, выполняемые при установке/удалении.
- **triggers/**: Информация о триггерах (например, обновление кеша иконок или `ldconfig`).
  - Файлы имеют формат `interest`, `interest-await`, `activate`, `inhibit`.
  - При изменении триггер-состояния deferred-скрипты помещаются в очередь и выполняются в конце транзакции.
- **alternatives/**: Управляет переключаемыми пакетами (update-alternatives). Содержит:
  - `maintainer`: пакет, владеющий альтернативой.
  - `status`: текущее состояние (auto/manual).
  - `best-choice`/`slaves`: приоритеты и связанные ссылки.
- **updates/**: Временные файлы во время конфигурации пакетов (`/var/lib/dpkg/updates/`). Содержит промежуточные обновления статуса. Если произошёл сбой, здесь могут остаться временные файлы, блокирующие `dpkg`.
- **tmp/**: Временные файлы менеджера пакетов.

#### Интерфейс dpkg-query

Утилита `dpkg-query` — основной интерфейс для программного доступа к данным БД:

```bash
# Список всех установленных пакетов с пользовательским форматом
dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n'
# → nginx\t1.24.0-1ubuntu3\tamd64
# → curl\t7.81.0-1ubuntu1.14\tamd64

# Метаданные конкретного пакета (аналог чтения файла status)
dpkg-query -s nginx
# → Package: nginx
# → Status: install ok installed
# → Version: 1.24.0-1ubuntu3

# Проверка, установлен ли пакет
dpkg-query -W -f='${Status}' nginx 2>/dev/null
# → install ok installed
```

### Структура базы данных RPM

Располагается в `/var/lib/rpm/`. Дополнительные каталоги: `/var/lib/dnf/` (метаданные DNF), `/var/cache/dnf/` (кэш репозиториев).

- **rpmdb.sqlite**: Современный стандарт (RHEL 9+, Fedora 33+). Позволяет выполнять SQL-запросы к базе пакетов.
  - Основные таблицы: `Packages`, `Provides`, `Obsoletes`, `Conflicts`, `Files`, `Triggers`.
  - Преимущество: возможность резервного копирования одной командой `cp /var/lib/rpm/rpmdb.sqlite`.
- **Packages**: Основная таблица метаданных в формате BDB (устарело, RHEL 7 и старше).
- **__db.001, __db.002**: Временные файлы общей памяти BDB. Их удаление часто помогает при "зависании" `rpm`.
- **Basenames, Dirnames, Installtid, Sigmd5**: Дополнительные индексы BDB для ускорения поиска по файлам и директориям.

#### Интерфейс rpm

Утилита `rpm` предоставляет программный доступ к метаданным:

```bash
# Список всех установленных пакетов с кастомным форматом
rpm -qa --queryformat='%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n'
# → nginx\t1.24.0-1.el9\tx86_64

# Детальная информация о пакете
rpm -qi nginx
# → Name        : nginx
# → Version     : 1.24.0
# → Release     : 1.el9
# → Architecture: x86_64
# → Install Date: Mon 01 Jan 2024 12:00:00 PM MSK
# → Group       : Unspecified
# → Size        : 1234567
# → License     : BSD
# → Signature   : RSA/SHA256, ...
```

### Механизмы блокировок (APT/DPKG и DNF/RPM)

APT использует иерархию блокировок для защиты разных этапов транзакции:
1.  `/var/lib/dpkg/lock-frontend`: Блокирует высокоуровневые менеджеры (apt, aptitude, synaptic).
2.  `/var/lib/dpkg/lock`: Блокирует низкоуровневый `dpkg`.
3.  `/var/cache/apt/archives/lock`: Блокирует кэш загруженных пакетов.
4.  `/var/lib/apt/lists/lock`: Блокирует обновление индексов репозиториев.

DNF использует аналогичные блокировки:
1.  `/var/cache/dnf/metadata_lock.pid`: Блокирует доступ к метаданным репозиториев.
2.  `/var/lib/rpm/.rpm.lock`: Блокирует низкоуровневые операции RPMDB.
3.  `/var/run/yum.pid` (устаревшее): Блокирует экземпляр yum/dnf.

Блокировки реализуются через advisory-блокировки файлов (`fcntl(2)` с `F_SETLKW`). При аварийном завершении процесса блокировка автоматически снимается ядром. Однако в редких случаях (NFS, зависший процесс в uninterruptible sleep) требуется ручное вмешательство.

### Контроль целостности и верификация

#### DEB: debsums

Пакет `debsums` проверяет контрольные суммы файлов установленных пакетов против записей в БД:

```bash
# Проверка всех пакетов (требует установки debsums)
sudo debsums -s
# → Выводит только измененные файлы (пустой вывод = система чистая)

# Проверка конкретного пакета
sudo debsums -s nginx
# → /usr/sbin/nginx   # ← файл изменён относительно БД
```

#### RPM: rpm -V

Команда `rpm -V` (verify) сравнивает файлы на диске с метаданными в БД:

```bash
# Полная проверка всех файлов системы
sudo rpm -Va
# → Пустой вывод = файлы не изменены
# → S.5.T. /usr/bin/nginx   # S=размер, 5=MD5, T=время модификации

# Проверка конкретного пакета
sudo rpm -V nginx
```

Расшифровка кодов вывода:
- `S` — размер файла изменился
- `5` — MD5/SHA256 контрольная сумма изменилась
- `T` — время модификации изменилось
- `D` — устройство изменилось
- `L` — симлинк изменился
- `U` — права доступа изменились
- `G` — группа изменилась
- `M` — режим (permissions) изменился

### Механизм diversion (dpkg-divert)

`dpkg-divert` позволяет перенаправлять установку файлов одного пакета в другое место, предотвращая конфликты:

```bash
# Создание diversion для конфига nginx
sudo dpkg-divert --divert /etc/nginx/nginx.conf.custom --rename /etc/nginx/nginx.conf
# → Файл переименован в .custom, новый файл от пакета будет установлен как .dist

# Просмотр всех diversion в системе
sudo dpkg-divert --list
# → diversion of /usr/bin/awk to /usr/bin/awk.original by awk
```

Изменения фиксируются в `/var/lib/dpkg/diversions` и не отображаются в обычном `dpkg -L`.

---

## Практические сценарии

### Обслуживание DPKG (Debian/Ubuntu)

#### Анализ состояния пакетов

```bash
# Вывод полного списка всех установленных пакетов (ключевой инструмент аудита)
dpkg -l
# → result: таблица со столбцами: статус (Desired/Status/Error), имя, версия, архитектура, описание
# Коды статуса: 'ii' = установлен, 'rc' = удалён но конфиги остались, 'iF' = ошибка конфигурации

# Поиск пакетов, находящихся в промежюточном состоянии (сломанных)
dpkg -l | grep -v '^ii'
# → result: список пакетов со статусами 'rc' (удален, но конфиги остались) или 'iF' (ошибка конфигурации)

# Просмотр записи о конкретном пакете в файле status
sed -n '/Package: nginx/,/^$/p' /var/lib/dpkg/status

# Поиск пакета по имени файла (установленного)
dpkg -S /etc/nginx/nginx.conf
# → nginx-common: /etc/nginx/nginx.conf

# Пользовательский форматирование списка пакетов (для скриптов)
dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\t${Status}\n' | sort
# → Имя\tВерсия\tАрхитектура\tСтатус
```

> **Различие `dpkg -l` и `dpkg -L`:** строчная `-l` (от list) выводит **список всех
> установленных пакетов**, тогда как заглавная `-L` выводит **список файлов конкретного
> установленного пакета**. Доступные команды `dpkg` описаны в
> [Обзоре управления пакетами](./linux_package_management_overview.md).

#### Восстановление поврежденного файла status

Если файл `/var/lib/dpkg/status` поврежден или пуст, APT перестанет работать.
1.  Проверьте наличие ежедневных копий: `/var/lib/dpkg/status-old` или архивов в `/var/backups/dpkg.status.*`.
2.  Восстановление из последней копии:
```bash
sudo cp /var/lib/dpkg/status-old /var/lib/dpkg/status
sudo apt update
```

#### Исправление сломанных зависимостей (broken packages)

Если `apt` сообщает о неразрешенных зависимостях или `dpkg` завершился с ошибкой:

```bash
# Автоматическое исправление зависимостей (скачивает недостающие пакеты)
sudo apt-get install -f
# → Дополняет или удаляет пакеты для восстановления консистентности

# Принудительное завершение конфигурации всех незавершённых пакетов
sudo dpkg --configure -a
# → Последовательно завершает setup всех пакетов в состоянии half-configured

# Удаление проблемного пакета (при невозможности исправить)
sudo dpkg --remove --force-remove-reinstreq <package_name>
# → --force-remove-reinstreq удаляет пакет даже если требуется переустановка
```

#### Очистка блокировок

```bash
# 1. Найти процесс, удерживающий блокировку
sudo lsof /var/lib/dpkg/lock-frontend

# 2. Если процесс не найден (зависшая блокировка), удалить файлы
sudo rm /var/lib/dpkg/lock-frontend
sudo rm /var/lib/dpkg/lock
sudo dpkg --configure -a
```

#### Использование apt-mark (фиксация/разрешение пакетов)

Для предотвращения автоматического обновления критичных пакетов:

```bash
# Фиксация пакета (hold) — запрет автоматического обновления
sudo apt-mark hold nginx
# → В файле /var/lib/dpkg/status появляется Selection: hold

# Проверка списка зафиксированных пакетов
apt-mark showhold
# → nginx
# → mysql-server

# Снятие фиксации
sudo apt-mark unhold nginx

# Отметка пакета как установленного вручную (не как зависимости)
sudo apt-mark manual nginx
# → Пакет не будет удалён apt autoremove
```

#### Проверка целостности кеша APT

```bash
# Проверка и удаление повреждённых кешей
sudo apt update
# → W: Failed to fetch ... Hash Sum mismatch
# Решение: очистка кеша
sudo apt clean
sudo rm -rf /var/lib/apt/lists/*
sudo apt update
```

#### Управление diversion

```bash
# Создание diversion
sudo dpkg-divert --divert /usr/bin/foo.original --rename /usr/bin/foo

# Возврат diversion
sudo dpkg-divert --rename --remove /usr/bin/foo

# Просмотр всех diversion
sudo dpkg-divert --list | grep foo
# → diversion of /usr/bin/foo to /usr/bin/foo.original by foo
```

### Обслуживание RPM (Fedora/RHEL/AlmaLinux)

#### Верификация и восстановление

```bash
# Глубокая проверка базы данных
sudo rpm --verifydb

# Перестроение БД (безопасно для SQLite, критично для BDB)
# Команда перечитывает заголовки установленных пакетов и создает новые индексы
sudo rpm --rebuilddb
```

#### Использование dnf check

```bash
# Проверка целостности базы RPM
sudo dnf check
# → Выявляет: неразрешенные зависимости, отсутствующие заголовки пакетов
# → Возвращает 0 при успехе; ненулевой код = проблемы
```

#### Восстановление повреждённых lock-файлов после аварии

```bash
# Удаление устаревших блокировок DNF/RPM
sudo rm -f /var/lib/rpm/.rpm.lock
sudo rm -f /var/cache/dnf/*.lock
sudo dnf clean all
sudo dnf makecache
```

#### Работа с SQLite (для экспертов)

Если установлена утилита `sqlite3`, можно изучать базу напрямую:

```bash
# Список всех установленных пакетов через SQL
sqlite3 /var/lib/rpm/rpmdb.sqlite "SELECT name, version, release FROM packages LIMIT 10;"
# → nginx|1.24.0|1.el9

# Поиск пакета по файлу (аналог rpm -qf)
sqlite3 /var/lib/rpm/rpmdb.sqlite "
  SELECT p.name, f.name 
  FROM packages p 
  JOIN files f ON p.pkgID = f.pkgID 
  WHERE f.name LIKE '/usr/bin/nginx%';
"
# → nginx|/usr/sbin/nginx
# → nginx|/usr/sbin/nginx.1
```

#### Исправление прав доступа на файлы пакетов

```bash
# Восстановление стандартных прав доступа на файлы пакета
sudo rpm --setperms nginx
sudo rpm --setugids nginx
# → Устанавливает права и владельцев из метаданных пакета (полезно после chmod 777)
```

### Кросс-платформенные сценарии (Debian/Ubuntu и RHEL/Fedora)

#### Аудит инодов в /var/lib/dpkg/info/

Исчерпание inodes на разделе `/var` блокирует установку пакетов:

```bash
# Проверка использования inodes на разделе /var
df -i /var /var/lib /var/cache
# → Filesystem     Inodes  IUsed  IFree IUse% Mounted on
# → /dev/sda1      655360  640000  15360   98%  /var

# Если IUse% > 90%, требуется очистка
# Анализ каталогов с большим количеством файлов
sudo du --inodes /var/lib/dpkg/info/ | sort -rn | head -20
# → 15000 /var/lib/dpkg/info/
# → 8000  /var/lib/dpkg/info/nginx-common.list

# Очистка устаревших кешей APT
sudo apt-get clean
sudo apt-get autoclean
# → Удаляет устаревшие .deb из /var/cache/apt/archives/

# Удаление старых ядер (если installonly_limit не сработал)
sudo dnf remove --oldinstallonly --setopt=installonly_limit=2 kernel
# → Оставляет только 2 последних ядра; проверьте: dnf list installed kernel
```

#### Аудит пакетов, установленных вручную (не как зависимости)

```bash
# DEB: список явно установленных пакетов
apt-mark showmanual | sort > /tmp/manual_deb.txt
wc -l /tmp/manual_deb.txt
# → Количество пакетов, установленных вручную

# RPM: аналогичный отчёт
dnf repoquery --userinstalled --queryformat='%{name}\n' | sort > /tmp/manual_rpm.txt
wc -l /tmp/manual_rpm.txt
```

#### Создание инвентаризации пакетов (SBOM-lite)

```bash
# DEB: экспорт списка пакетов для compliance
dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n' | sort > /tmp/packages_deb.txt

# RPM: экспорт списка пакетов
rpm -qa --queryformat='%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n' | sort > /tmp/packages_rpm.txt

# Сравнение между двумя серверами (DevOps-сценарий)
diff --side-by-side --suppress-common-lines \
  <(ssh server1 "rpm -qa --queryformat='%{NAME} %{VERSION}-%{RELEASE}\n'" | sort) \
  <(ssh server2 "rpm -qa --queryformat='%{NAME} %{VERSION}-%{RELEASE}\n'" | sort)
# → Показывает расхождения в версиях пакетов между серверами
```

#### Восстановление после сбоя транзакции

Если система была перезагружена во время `apt upgrade` или `dnf upgrade`:

```bash
# DEB: проверка состояния пакетов
sudo dpkg -l | grep -E '^..[^i]'
# → Покажет пакеты в состояниях, отличных от 'installed'

# DEB: завершение конфигурации
sudo dpkg --configure -a

# DEB: исправление зависимостей
sudo apt-get install -f

# RPM: проверка БД
sudo rpm --verifydb

# RPM: перестроение БД
sudo rpm --rebuilddb

# RPM: проверка и исправление зависимостей
sudo dnf check
sudo dnf distro-sync
```

#### Проверка, что пакет предоставляет конкретный файл

```bash
# DEB
dpkg -S /usr/bin/nginx
# → nginx-core: /usr/sbin/nginx

# RPM
rpm -qf /usr/sbin/nginx
# → nginx-1.24.0-1.el9.x86_64

# DNF (даже если пакет не установлен)
dnf provides /usr/sbin/nginx
# → nginx-1.24.0-1.el9.x86_64 : A high performance web server
# → Repo : fedora
```

---

## Дополнительная информация

### Журналирование изменений

- **/var/log/dpkg.log**: История всех действий `dpkg`.
  `grep "status installed" /var/log/dpkg.log` — когда и что было установлено.
- **/var/log/apt/history.log**: Полные команды `apt`, включая зависимости и время выполнения.
- **/var/log/apt/term.log**: Полный вывод терминала установок (полезен для отладки).
- **/var/log/unattended-upgrades/unattended-upgrades.log**: История автоматических обновлений (если настроен unattended-upgrades).
- **dnf history**: Мощный инструмент для RPM-систем.
  `dnf history info <ID>` — детальный отчет о транзакции.
- **/var/log/dnf.log** и **/var/log/dnf.librepo.log**: Подробное логирование операций DNF.

### Контроль inodes

База данных пакетов (особенно в `/var/lib/dpkg/info/`) содержит десятки тысяч мелких файлов. Исчерпание inodes может заблокировать установку обновлений. Мониторинг:

```bash
# Проверка использования inodes на критичных разделах
df -i /var /var/lib /var/cache
# → IUse% > 90% — требуется очистка

# Поиск директорий с наибольшим количеством файлов
sudo find /var/lib/dpkg -type f | wc -l
# → 50000  (примерно 50K файлов на сервере с ~200 пакетами)

# Топ-20 директорий по количеству файлов
sudo find /var/lib/dpkg -type f -printf '%h\n' | sort | uniq -c | sort -rn | head -20
# → 15000 /var/lib/dpkg/info
# → 12000 /var/lib/dpkg/info/triggers
```

### Бэкап базы пакетов

```bash
# DEB: бэкап критичных файлов
sudo tar -czf /root/dpkg-backup-$(date +%Y%m%d).tar.gz \
  /var/lib/dpkg/status \
  /var/lib/dpkg/status-old \
  /var/lib/dpkg/info/ \
  /var/backups/dpkg.status.*

# RPM: бэкап RPMDB (включая метаданные DNF)
sudo tar -czf /root/rpmdb-backup-$(date +%Y%m%d).tar.gz \
  /var/lib/rpm/ \
  /var/lib/dnf/ \
  /etc/dnf/ \
  /etc/yum.repos.d/

# Проверка бэкапа
tar -tzf /root/dpkg-backup-20240101.tar.gz | head
# → Список содержимого архива
```

### Восстановление в rescue-режиме

При невозможности загрузки системы:

```bash
# Загрузка с LiveCD/USB
# Монтирование корневого раздела
sudo mount /dev/sda1 /mnt
sudo mount --bind /dev /mnt/dev
sudo mount --bind /proc /mnt/proc
sudo mount --bind /sys /mnt/sys

# Восстановление DEB БД
sudo cp /mnt/var/backups/dpkg.status.* /mnt/var/lib/dpkg/status
sudo chroot /mnt dpkg --configure -a

# Восстановление RPM БД
sudo chroot /mnt rpm --rebuilddb
```

### Рекомендации (Best Practices)

1.  **Запрет на ручное редактирование**: Прямое изменение файлов базы данных (особенно `/var/lib/dpkg/status`) может привести к тому, что менеджер пакетов откажется работать. Используйте `dpkg-query`, `apt-mark`, `dpkg-divert` для программных изменений.
2.  **Контроль inodes**: База данных пакетов (особенно в `/var/lib/dpkg/info/`) содержит десятки тысяч мелких файлов. Исчерпание inodes может заблокировать установку обновлений.
3.  **Использование apt-mark**: Для предотвращения автоматического обновления пакета (фиксации версии) используйте `sudo apt-mark hold <package>`, что вносит изменения в поле `Selection` файла `status`.
4.  **Регулярный аудит**: Сравнивайте список установленных пакетов с эталонным SBOM. Автоматизируйте через cron/systemd-timer.
5.  **Мониторинг блокировок**: В production-скриптах проверяйте `lslocks` перед запуском пакетных операций, чтобы избежать конфликтов с unattended-upgrades.
6.  **Бэкап перед массовыми изменениями**: Создавайте резервные копии `/var/lib/dpkg/` и `/var/lib/rpm/` перед крупными обновлениями или миграциями.
7.  **Использование `--assume-yes` в скриптах**: Для неинтерактивного режима (CI/CD, Ansible) используйте флаг `-y`, но проверяйте план транзакции сначала через `--assumeno` (dry-run).

### Связанные документы

- **[Обзор управления пакетами](./linux_package_management_overview.md)** — сравнение систем DEB и RPM.
- **[Анализ и получение пакетов](./package_analysis.md)** — исследование состава `.deb` и `.rpm`.
- **[Команды DNF](./dnf_commands/practical_scenarios.md)** — подробнее о `dnf history`, `dnf check`, восстановлении RPMDB.
- **[Apt Pinning](./deb_apt_pinning.md)** — управление приоритетами на базе метаданных.
- **[Диагностика процессов lsof](../Diagnostics/Processes/lsof.md)** — анализ блокировок файлов и процессов.
- **[Атомарные операции](../Concepts/atomic_operations.md)** — внутренние механизмы блокировок и транзакционности.
- **[Проверка целостности файлов](../Security/Concepts/file-integrity-checking.md)** — детали верификации файлов и расшифровка кодов `rpm -V` и `debsums`.
