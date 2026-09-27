# DNF — Практические сценарии

## Определения

Определения ключевых терминов (модуль, поток, профиль, транзакция, SAT-solver) приведены в документе **[Определения](./definitions.md)**. Архитектура и компоненты DNF описаны в **[Основные понятия](./basic_concepts.md)**. Продвинутые возможности, плагины и `dnf-automatic` детализированы в **[Дополнительная информация](./additional_info.md)**.

---

## Основные концепции

DNF — высокоуровневый пакетный менеджер для RPM-based систем (RHEL, Fedora, CentOS, AlmaLinux, Rocky Linux). Для понимания практических сценариев достаточно знать ключевые этапы транзакции: загрузка метаданных → SAT-разрешение зависимостей → Transaction Check → скачивание → исполнение через `librpm` → запись в историю. Детали архитектуры, `dnf.conf` параметров, GPG-верификации и Delta RPM доступны в **[Основные понятия DNF](./basic_concepts.md)**.

**Предварительные требования для практических сценариев:**
- Root-доступ (`sudo`) для операций изменения системы
- Настроенные репозитории в `/etc/yum.repos.d/`
- Импортированные GPG-ключи в RPMDB (`rpm -qa gpg-pubkey`)
- Достаточно места в `/var/cache/dnf` и `/var/lib/rpm`

---

## Практические сценарии

### Базовое управление пакетами

```bash
# Обновление метаданных всех репозиториев
sudo dnf makecache
# → Создает/обновляет кэш repomd.xml и primary.xml в /var/cache/dnf/
# → Возвращает список обработанных репозиториев

# Обновление всех пакетов до последних версий
sudo dnf upgrade
# → Показывает план транзакции (количество обновляемых/устанавливаемых/удаляемых пакетов)
# → Запрашивает подтверждение; используйте -y для автоматизации

# Установка пакета (с автоматическим разрешением зависимостей)
sudo dnf install <package_name>
# → DNF через libsolv разрешает все Requires/Recommends
# → Скачивает RPM, проверяет GPG, устанавливает через librpm

# Установка конкретной версии (из доступных в репозиториях)
sudo dnf install <package_name>-<version>
# → Пример: sudo dnf install nginx-1.24.0-1.el9
# → Работает только если версия доступна в репозитории

# Удаление пакета (без удаления зависимостей)
sudo dnf remove <package_name>
# → Запоминает пакет как user-installed
# → Не трогает зависимости, установленные ранее

# Удаление пакета и всех неиспользуемых зависимостей (рекомендуется)
sudo dnf autoremove <package_name>
# → Удаляет пакет + leaf-зависимости, не требуемые другими пакетами
# → Безопасно для системных библиотек (защищены protected_packages)

# Переустановка пакета (например, при повреждении файлов)
sudo dnf reinstall <package_name>
# → Скачивает текущую версию и переустанавливает поверх
# → Не меняет зависимости, только файлы пакета

# Понижение версии пакета (downgrade)
sudo dnf downgrade <package_name>
# → Устанавливает более старую версию из кэша или репозитория
# → Может потребовать --allowerasing при конфликтах

# Замена одного пакета другим (полезно при миграции, например, mysql -> mariadb)
sudo dnf swap <old_package> <new_package>
# → Атомарная операция: удаляет old, устанавливает new в одной транзакции
```

**Валидация:**
```bash
# Проверка установки
dnf list installed <package_name>
rpm -q <package_name>
# → Ожидаемый вывод: package_name-version.arch

# Проверка целостности файлов пакета
rpm -V <package_name>
# → Пустой вывод = файлы не изменены; S.5.T. = размер/контрольная сумма/время изменены
```

---

### Групповые операции

Группы позволяют устанавливать наборы пакетов для конкретных задач (например, "Development Tools").

```bash
# Список всех доступных и установленных групп
dnf group list
# → Выводит группы с пометками [installed], [hidden] для environment groups

# Информация о составе группы (обязательные, рекомендуемые пакеты)
dnf group info "Development Tools"
# → Показывает: Mandatory Packages, Default Packages, Optional Packages

# Установка группы
sudo dnf group install "Development Tools"
# → Устанавливает все mandatory + default пакеты группы

# Удаление группы
sudo dnf group remove "Development Tools"
# → Удаляет только пакеты, установленные как часть группы

# Установка группы окружения (Environment Group)
sudo dnf group install "Server with GUI"
# → Environment Group — верхнеуровневая группа, содержащая другие группы
# → Список всех Environment Groups: dnf group list --hidden

# Отметка группы как установленной (без фактической установки)
sudo dnf group mark install "Development Tools"
# → Полезно для идемпотентных сценариев: группа "установлена", пакеты не трогаются
```

---

### Расширенный поиск и инспекция (Repoquery)

Утилита `repoquery` позволяет делать сложные запросы к базе данных пакетов.

```bash
# Поиск пакета по имени или части описания
dnf search <keyword>
# → Ищет по имени и краткому описанию во всех репозиториях

# Показать, какой пакет предоставляет конкретный файл (например, /usr/bin/python3)
dnf provides /usr/bin/python3
# → Возвращает пакет(ы), содержащие этот файл

# Подробная информация о пакете (версия, лицензия, описание)
dnf info <package_name>
# → Выводит: Name, Version, Release, Architecture, Size, Repo, Summary, URL, License

# Список всех файлов, входящих в пакет (даже если он не установлен)
dnf repoquery --list <package_name>
# → Полный список путей файлов внутри RPM

# Поиск пакетов, которые зависят от указанного (обратные зависимости)
dnf repoquery --installed --whatrequires <package_name>
# → Показывает, какие установленные пакеты требуют указанный

# Поиск пакета, предоставляющего конкретную Capability или shared library
dnf repoquery --whatprovides "libssl.so.1.1()(64bit)"
# → Используйте для поиска по "virtual provides"

# Список всех зависимостей пакета
dnf deplist <package_name>
# → Дерево Requires/Recommends/Suggests с указанием версий

# Показать все доступные версии пакета во всех репозиториях
dnf list --showduplicates <package_name>
# → Выводит все версии с репозиторием-источником

# Показать пакеты, установленные не из репозиториев (локальные или устаревшие)
dnf list extras
# → Кандидаты на удаление или переустановку
```

**Практический пример: поиск и установка nmap**

```bash
# 1. Поиск пакета по ключевому слову
dnf search nmap
# → Загружает метаданные репозитория, ищет по имени и описанию
# → Выводит список совпадений с кратким описанием

# 2. Просмотр детальной информации о пакете перед установкой
dnf info nmap
# → Показывает версию, лицензию, размер загрузки, зависимости и описание

# 3. Установка с автоматическим подтверждением (неинтерактивный режим)
sudo dnf install -y nmap
# → -y (--assumeyes) подавляет интерактивный запрос подтверждения
# → DNF автоматически разрешает все зависимости через SAT-солвер libsolv
# → Скачивает RPM, проверяет GPG-подписи и устанавливает пакет

# 4. Проверка установки
nmap --version
# → nmap version 7.94 ( https://nmap.org )
```

> **Важно:** флаг `-y` (`--assumeyes`) обязателен в скриптах и автоматизации, чтобы процесс не блокировался на интерактивном подтверждении. В интерактивном режиме рекомендуется сначала выполнить `dnf install` без `-y`, изучить план транзакции, а затем подтвердить.

---

### Управление модулями и потоками (AppStream)

Модули позволяют переключаться между разными версиями одного ПО в рамках одного дистрибутива.

```bash
# Список модулей и их доступных потоков (streams)
dnf module list
# → Выводит: Name, Stream, Profiles, Summary, Enabled

# Включение конкретного потока (например, Node.js 20)
sudo dnf module enable nodejs:20
# → Включает поток nodejs:20; делает соответствующие пакеты доступными

# Установка модуля с профилем по умолчанию (обычно common)
sudo dnf module install nodejs:20
# → Устанавливает пакеты, указанные в профиле по умолчанию

# Установка модуля с конкретным профилем (например, минимальная установка)
sudo dnf module install nodejs:20/minimal
# → Устанавливает только минимальный набор пакетов профиля minimal

# Переключение на другой поток (автоматически обновит/заменит пакеты)
sudo dnf module switch-to nodejs:22
# → Отключает старый поток, включает новый, обновляет пакеты

# Сброс состояния модуля (отмена выбора потока)
sudo dnf module reset nodejs
# → Возвращает модуль в состояние "не выбран"; пакеты не удаляются автоматически
```

**Идемпотентность для automation:**
```bash
# Гарантированное включение потока (не падает, если уже включен)
sudo dnf module enable nodejs:20 -y || true

# Проверка текущего активного потока перед переключением
dnf module list nodejs | grep "^nodejs"
# → Если output содержит "nodejs : 20 [e] ", переключение не требуется
```

---

### История транзакций и откат изменений

DNF ведет детальный лог всех изменений, что позволяет безопасно откатывать систему.

```bash
# Просмотр списка последних транзакций
dnf history
# → ID, Date & Time, Action(s), Altered (количество измененных пакетов)

# Детальная информация о транзакции (кто, когда и что изменил)
sudo dnf history info <transaction_id>
# → Command Line, User, IP-адрес (если удаленный), список пакетов

# Отмена изменений конкретной транзакции (undo)
sudo dnf history undo <transaction_id>
# → Создает новую транзакцию, обратную указанной
# → Может потребовать отката нескольких последующих транзакций

# Повтор ранее выполненной транзакции (redo)
sudo dnf history redo <transaction_id>
# → Повторяет действия транзакции (install/remove/upgrade)

# Полный откат состояния системы к моменту после указанной транзакции
sudo dnf history rollback <transaction_id>
# → Откатывает ВСЕ транзакции после указанной, а не только одну

# Список транзакций, инициированных пользователем (а не системой)
dnf history userinstalled
# → Полезно для аудита: что установил человек, а что — автоматизация
```

**Валидация отката:**
```bash
# Перед откатом проверьте, что система в ожидаемом состоянии
dnf history list
sudo dnf history undo 42 --assumeno
# → План отката покажет, какие пакеты будут downgrade/remove

# После отката проверьте критичные пакеты
rpm -q kernel glibc systemd
dnf list installed kernel
```

---

### Продвинутые техники и автоматизация

```bash
# Фиксация версии пакета (запрет обновления через плагин versionlock)
sudo dnf versionlock add nginx
# → Записывает пакет в /etc/dnf/plugins/versionlock.list
# → SAT-солвер исключает обновление при разрешении зависимостей

# Удаление блокировки версии
sudo dnf versionlock delete nginx
# → Удаляет из versionlock.list; обновление разрешено

# Установка зависимостей для сборки пакета (из .spec файла)
sudo dnf builddep <package_name>.spec
# → Автоматически устанавливает BuildRequires из spec-файла

# Проверка базы данных RPM на наличие ошибок и конфликтов
sudo dnf check
# → Проверяет: неразрешенные зависимости, дубликаты, отсутствующие файлы
# → Возвращает 0 при успехе; ненулевой код = проблемы

# Синхронизация версий установленных пакетов с версиями в репозитории
sudo dnf distro-sync
# → Приводит ВСЕ пакеты к версиям репозитория
# → Может понизить версии, если установлен пакет из внешнего источника

# Интерактивная оболочка DNF (ускоряет выполнение нескольких команд подряд)
dnf shell
# Внутри оболочки (несколько команд без повторной загрузки метаданных):
# > install vim curl wget
# > upgrade
# > run
# > exit
```

---

### Резервное копирование RPMDB перед изменениями

```bash
# Создание резервной копии базы RPM перед критичными операциями
sudo tar -czf /root/rpmdb-backup-$(date +%Y%m%d).tar.gz \
  /var/lib/rpm/ \
  /var/lib/dnf/ \
  /etc/dnf/ \
  /etc/yum.repos.d/

# Проверка бэкапа
tar -tzf /root/rpmdb-backup-$(date +%Y%m%d).tar.gz | head
# → Список содержимого архива

# Восстановление из бэкапара (в rescue-режиме)
sudo tar -xzf /root/rpmdb-backup-20240101.tar.gz -C /
```

---

### Управление загрузчиком GRUB через `grubby`

Подробное описание инструмента `grubby` и практические сценарии работы с загрузочными записями см. в **[Загрузчик GRUB](../../Linux/SystemAdministration/grub.md)**.

Краткие команды:
```bash
# Просмотр всех загрузочных записей
sudo grubby --info=ALL | grep -E "^title|^kernel"

# Ручная установка дефолтного ядра
sudo grubby --set-default-index=0

# Добавление параметра ко всем ядрам
sudo grubby --update-kernel=ALL --args="systemd.unified_cgroup_hierarchy=1"
```

---

### Ремонт базы RPM после прерванной транзакции

```bash
# Проверка целостности базы RPM
sudo dnf check
# → Выявляет: неразрешенные зависимости, отсутствующие заголовки пакетов

# Принудительное создание базы заново (экстренный случай)
sudo rm -f /var/lib/rpm/__db.*
sudo rpm --rebuilddb
# → Удаляет BerkeleyDB кэш; перестраивает индексы RPMDB

# Проверка и восстановление lock-файла (если DNF завис)
sudo rm -f /var/lib/rpm/.rpm.lock
sudo rm -f /var/cache/dnf/*.lock
# → Удаляет устаревшие блокировки после аварийного завершения DNF

# Проверка целостности конкретного пакета
rpm -V <package_name>
# → Пустой вывод = файлы не изменены
# → S.5.T. = размер/контрольная сумма/время изменены (ожидается при патчах)
```

---

### Тюнинг поведения через флаги

```bash
# Пропуск обновлений для конкретных пакетов
sudo dnf upgrade --exclude=kernel*
# → Исключает пакеты по glob-паттерну; можно указать несколько --exclude

# Отключение установки слабых зависимостей (recommends)
sudo dnf install <package_name> --setopt=install_weak_deps=False
# → Устанавливает только hard dependencies (Requires)
# → Полезно для минимальных/container образов

# Использование только локального кэша (без сети)
dnf upgrade --cacheonly
# → Ошибка, если требуемые пакеты отсутствуют в кэше
# → Для проверки полноты кэша: dnf repoquery --requires <pkg> | dnf repoquery --whatprovides -

# Скачивание RPM-пакета без установки
dnf download --destdir=/tmp <package_name>
# → Скачивает только сам RPM, без зависимостей
# → Для зависимостей: dnf download --resolve --destdir=/tmp <package_name>

# Скачивание исходного кода пакета (Source RPM)
dnf download --source <package_name>
# → Скачивает .src.rpm; требует включенного репозитория source

# Принудительная перезагрузка метаданных
sudo dnf clean metadata && sudo dnf makecache
# → Очищает кэш и загружает заново; решает проблемы устаревших индексов

# Только проверка доступных обновлений без загрузки
dnf check-update
# → Возвращает 0 если обновлений нет, 100 если есть, 1 при ошибке
# → Подходит для мониторинга (Zabbix, Nagios)
```

---

### Массовое обновление и пакетная установка

```bash
# Установка нескольких пакетов одной командой
sudo dnf install -y pkg1 pkg2 pkg3
# → DNF разрешает общую граф зависимостей для всех пакетов

# Удаление нескольких пакетов
sudo dnf remove -y pkg1 pkg2 pkg3

# Обновление до определенной версии дистрибутива
sudo dnf distro-sync --releasever=9.4
# → Полезно при миграции на новую minor-версию без полной переустановки

# Чтение списка пакетов из файла (идемпотентная установка)
sudo dnf install -y $(cat /tmp/packages.txt)
# → Файл packages.txt содержит по одному имени пакета на строке
# → Для Ansible-free идемпотентности: dnf list installed $(cat packages.txt) || dnf install -y ...

# Массовая проверка обновлений в скрипте
UPDATE_LIST=$(dnf check-update --quiet | awk 'NR>1 {print $1}')
if [ -n "$UPDATE_LIST" ]; then
  echo "Доступны обновления:"
  echo "$UPDATE_LIST"
  # Отправка уведомления: mail, Slack webhook, PagerDuty
fi
```

---

### Работа через прокси и ограничение пропускной способности

```bash
# Настройка прокси для DNF (в /etc/dnf/dnf.conf)
sudo tee -a /etc/dnf/dnf.conf <<EOF
[main]
proxy=http://proxy.example.com:8080
proxy_username=user  # опционально
proxy_password=pass  # опционально
EOF

# Или через переменные окружения (для разовых операций)
sudo http_proxy=http://proxy.example.com:8080 dnf upgrade -y
sudo HTTP_PROXY=http://proxy.example.com:8080 HTTPS_PROXY=http://proxy.example.com:8080 dnf install -y <package>

# Ограничение скорости загрузки (экономия канала)
sudo dnf --setopt=throttle=1m install -y <package>
# → Ограничивает скорость до 1 МБ/с на загрузчик
# → Актуально для медленных/оплачиваемых каналов

# Проверка, что DNF видит прокси
sudo dnf repolist -v | grep -i proxy
# → Proxy: http://proxy.example.com:8080
```

---

### Автоматический перезапуск сервисов после обновления

```bash
# Список процессов, требующих перезапуска после обновления shared-библиотек
sudo dnf needs-restarting -s
# → Возвращает список PID/имён процессов, использующих устаревшие .so

# Список пакетов, после обновления которых требуется перезагрузка ОС
sudo dnf needs-restarting -r
# → Полезно для compliance: если требуется reboot, система не соответствует baseline

# Автоматический рестарт сервисов через systemd
sudo systemctl list-units --type=service --state=running | awk '{print $1}' | while read svc; do
  sudo systemctl restart "$svc"
done
# → Перезапускает ВСЕ running-сервисы; используйте с осторожностью
# → Более безопасно: рестартовать только сервисы, затронутые обновлением

# Интеграция с post-transaction-actions (автоматический рестарт nginx после обновления)
sudo tee /etc/dnf/plugins/post-transaction-actions.d/nginx.action <<'EOF'
nginx:any:systemctl reload nginx
EOF
# → После установки/обновления/удаления nginx systemctl reload выполнится автоматически
```

---

### Очистка системы и утилизация места

```bash
# Очистка всего кэша (метаданные и скачанные RPM)
sudo dnf clean all
# → Удаляет /var/cache/dnf/*; освобождает от 500 МБ до нескольких ГБ

# Очистка только устаревших метаданных
sudo dnf clean metadata
# → Сохраняет скачанные RPM, удаляет только старые primary.xml/filelists.xml

# Удаление старых ядер (если installonly_limit не сработал)
sudo dnf remove --oldinstallonly --setopt=installonly_limit=2 kernel
# → Оставляет только 2 последних ядра; проверьте: dnf list installed kernel

# Удаление orphaned пакетов (не требуются ни одним установленным пакетом)
dnf repoquery --extras
# → Пакеты, установленные явно, но не являющиеся зависимостями
# → Кандидаты на удаление: dnf remove $(dnf repoquery --extras)

# Поиск пакетов, от которых ничего не зависит (leaves)
dnf leaves --installed
# → Показывает leaf-пакеты; проверяйте перед удалением, не сломают ли они что-то

# Удаление кэша документации (man, info) для экономии места
sudo dnf remove --duplicates $(rpm -qa '*-doc*' '*-docs*' 2>/dev/null) || true
# → Удаляет дубликаты документации; используйте с осторожностью

# Проверка использования места в /var
df -h /var /var/cache /var/lib
sudo du -sh /var/cache/dnf/*
# → Визуализация самых крупных каталогов
```

---

### Аудит изменений и отчетность для compliance

```bash
# Полный SBOM (Software Bill of Materials) установленной системы
sudo dnf repoquery --installed --queryformat '%{name}-%{epoch}:%{version}-%{release}.%{arch}\n' > /tmp/sbom.txt
# → Формат: name-epoch:version-release.arch
# → Для CycloneDX: используйте cyclonedx-bom или SPDX-генераторы

# Список пакетов, установленных явно пользователем (не как зависимости)
dnf repoquery --userinstalled
# → Полезно для аудита: что установил человек, а что — автоматизация

# Список пакетов, установленных не из репозиториев (локальные RPM, сторонние)
dnf list extras
# → Выявляет несанкционированное ПО; важно для compliance

# Проверка обновлений безопасности с критичностью
dnf updateinfo summary
# → Статистика: security, bugfix, enhancement, newpackage

# Список только критичных уязвимостей
dnf updateinfo list --security --severity=Critical
# → Требует подключение к базе CVE (appstream metadata)

# Проверка, что установленные пакеты соответствуют GPG-подписям
rpm -Va --nopgp --nomd5 2>/dev/null | grep -E "^..5|^..S" | head -20
# → S = размер изменен, 5 = контрольная сумма MD5/SHA256 изменена
# → Ожидается пустой вывод для чистых систем

# Экспорт списка репозиториев для аудита
dnf repolist -v > /tmp/repo-audit-$(date +%Y%m%d).txt
# → Включает: baseurl, mirrorlist, metalink, enabled/disabled, GPG статус
```

---

### Отладка неработающих транзакций

```bash
# Включение максимальной подробности логов DNF
sudo dnf -v upgrade -y 2>&1 | tee /tmp/dnf-debug.log
# → -v = verbose; вывод включает HTTP-запросы, SAT-солвер решения, GPG проверки

# Просмотр полного лога DNF
sudo less /var/log/dnf.log
sudo less /var/log/dnf.librepo.log
# → Хронология всех операций с временными метками

# Анализ SQLite базы истории транзакций
sudo sqlite3 /var/lib/dnf/history.sqlite "SELECT * FROM trans WHERE dtid = (SELECT MAX(dtid) FROM trans);"
# → Показывает детали последней транзакции: пользователь, команда, пакеты

# Проверка блокировок (если DNF завис)
sudo lslocks | grep -E "rpm|dnf"
sudo rm -f /var/lib/rpm/.rpm.lock /var/cache/dnf/*.lock
# → Удаляет устаревшие блокировки после аварийного завершения

# Принудительное завершение зависшего процесса DNF
sudo pkill -9 dnf
sudo dnf clean all
sudo dnf makecache
```

---

### Стандартизация окружений через группы

```bash
# Список всех скрытых Environment Groups (включая Server/Workstation)
sudo dnf group list --hidden
# → Выводит: Environment Groups, псевдонимы (server-product-env, workstation-product-env)

# Установка Server Environment (минимальная серверная установка)
sudo dnf group install "Server with GUI"
# → Устанавливает все группы, входящие в Server Environment

# Проверка, какие группы установлены
sudo dnf group mark install "Development Tools"
# → Помечает группу как установленную (для idempotency)

# Экспорт списка установленных групп для воссоздания окружения
sudo dnf group list --installed > /tmp/installed_groups.txt
# → Используйте в automation: while read group; do sudo dnf group install "$group"; done < /tmp/installed_groups.txt
```

---

### Тестирование транзакций перед применением

```bash
# Проверка, какие пакеты будут обновлены/установлены/удалены
sudo dnf upgrade --assumeno
# → --assumeno (аналог --dry-run) показывает план без выполнения
# → Коды возврата: 0 = нет обновлений, 100 = есть обновления, 1 = ошибка

# Проверка конкретного пакета
sudo dnf install <package_name> --assumeno
# → Выводит список зависимостей, которые будут установлены

# Только загрузка пакетов без установки
sudo dnf upgrade --downloadonly --downloaddir=/tmp/updates
# → Требует плагин dnf-plugins-core
# → Пакеты остаются в /tmp/updates для ручной инсталляции

# Проверка зависимостей для офлайн-установки
dnf repoquery --requires <package_name> | dnf repoquery --whatprovides -
# → Строит цепочку зависимостей; проверяет, все ли они доступны в кэше
```

---

### Анализ влияния обновлений

```bash
# Список доступных обновлений с деталями
dnf list updates
# → Выводит: package, версия, репозиторий для каждого обновления

# Просмотр changelog обновлений
dnf updateinfo info
# → Краткое описание изменений из repomd.xml updateinfo

# Анализ, какие пакеты станут candidates на удаление (orphaned)
dnf repoquery --extras
# → Пакеты, установленные явно, но не входящие в репозитории

# Пакеты, установленные явно пользователем (не как зависимости)
dnf repoquery --userinstalled
# → Основа для очистки: можно переустановить только необходимое

# Пакеты, оставшиеся после удаления приложения
dnf leaves --installed
# → Кандидаты на удаление; проверяйте обратные зависимости перед удалением
```

---

### Диагностика нехватки места

```bash
# Проверка места в /var/cache/dnf и /var/lib/rpm
df -h /var/cache /var/lib

# Детализация по каталогам
sudo du -sh /var/cache/dnf/*
# → Показывает размер каждого кэша репозитория

# Очистка устаревших кэшей
sudo dnf clean all
# → Очищает все кэши; требуется повторный dnf makecache
```

---

### Работа с debuginfo и отладка

```bash
# Установка отладочных пакетов для конкретного приложения
sudo dnf debuginfo-install <package_name>
# → Устанавливает package-debuginfo с символами .debug
# → Требует включенный репозиторий debuginfo

# Установка debuginfo для ядра (требует debug репозиторий)
sudo dnf debuginfo-install kernel-$(uname -r)
# → Критично для tracelog, crash dump анализа, kdump

# Проверка наличия debuginfo репозитория
dnf repolist | grep -i debug
# → Если пусто: sudo dnf config-manager --set-enabled debuginfo (или отдельный .repo)
```

---

### Информация об обновлениях безопасности

```bash
# Список всех доступных обновлений
dnf updateinfo list

# Только обновления безопасности
dnf updateinfo list security

# Обновления с указанием критичности
dnf updateinfo list --security --severity=Critical
# → Severity: Critical, Important, Moderate, Low

# Полный отчет по обновлениям с критичностью
dnf updateinfo summary
# → Статистика: security, bugfix, enhancement, newpackage
```

---

### Сравнение с DNF 5

| Задача | Команда DNF 4 | Команда DNF 5 |
| :--- | :--- | :--- |
| **История** | `dnf history` | `dnf5 history list` |
| **Поиск** | `dnf search` | `dnf5 search` |
| **Скорость** | Стандартная | Значительно выше (C++) |
| **Список репозиториев** | `dnf repolist` | `dnf5 repolist` |
| **Очистка кэша** | `dnf clean all` | `dnf5 clean all` |
| **Добавление репо** | `dnf config-manager --add-repo <url>` | `dnf5 config-manager addrepo <url>` |

---

## Дополнительная информация

### Связанные документы

- **[Определения DNF](./definitions.md)** — глоссарий терминов.
- **[Основные понятия DNF](./basic_concepts.md)** — архитектура, конфигурация и настройки.
- **[Продвинутые возможности DNF](./additional_info.md)** — плагины, `dnf-automatic`, приоритеты репозиториев и GPG-ротация.
- **[Управление репозиториями](../Repository_Management/index.md)** — настройка источников ПО.
- **[Анализ пакетов](../package_analysis.md)** — глубокая инспекция RPM и метаданных.
- **[База данных пакетов](../package_database.md)** — структура RPMDB и работа с ней.
