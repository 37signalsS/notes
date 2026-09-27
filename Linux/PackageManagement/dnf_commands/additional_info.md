# DNF — Продвинутые возможности и плагины

## Определения

Определения базовых терминов (DNF, RPM, Транзакция, Libsolv) и ключевых понятий модульности приведены в документе **[Определения](./definitions.md)**.

---

## Основные концепции

Эволюция высокоуровневых менеджеров пакетов (от YUM к DNF 5) и детали архитектурных изменений описаны в разделе **[Дополнительная информация](#эволюция-высокоуровневых-менеджеров-пакетов)**.

### Модульность и потоки приложений (AppStream)

Механизм модульности позволяет сосуществовать нескольким версиям одного программного стека в одном дистрибутиве.

*   **Модуль (Module):** Коллекция пакетов, представляющая приложение (например, `postgresql` или `nodejs`).
*   **Поток (Stream):** Конкретная версия или ветка модуля (например, `nodejs:18` и `nodejs:20`). Только один поток модуля может быть активен в системе в один момент времени.
*   **Профиль (Profile):** Вариант установки внутри потока (например, `common`, `minimal`, `development`). Профиль определяет, какой набор пакетов будет установлен.
*   **Логика переключения:** При смене потока DNF автоматически выполняет замену пакетов, обеспечивая корректное разрешение зависимостей для новой версии.

**Формат метаданных модулей:** В репозиториях AppStream каждый модуль описывается файлом `modules.yaml` (или `modules.yaml.zstd`), который содержит:
*   Документ с описанием модуля (`document`)
*   Список доступных потоков (`streams`) с версиями и зависимостями между ними
*   Профили (`profiles`) с перечнем пакетов для каждого варианта установки
*   Требуемые контексты (`requires`) — условия, при которых поток доступен для установки

DNF скачивает и кэширует эти файлы в `/var/cache/dnf/` аналогично `repomd.xml`. При включении модуля (`dnf module enable`) DNF проверяет, что выбранный поток совместим с установленной версией дистрибутива и уже активными модулями. Конфликты между потоками обнаруживаются на этапе разрешения зависимостей (`libsolv`), что предотвращает частичные обновления.

### Архитектура плагинов

Плагины в DNF реализуются как Python-модули (в DNF 4) или C++-библиотеки (в DNF 5), которые динамически загружаются в процессе инициализации менеджера. Каждый плагин может перехватывать события жизненного цикла транзакции:

*   `init` — загрузка конфигурации плагина
*   `close` — перед завершением работы DNF
*   `pre_configure` / `post_configure` — до и после настройки репозиториев
*   `pre_transaction` / `post_transaction` — до и после выполнения транзакции
*   `download_packages` — при загрузке RPM-файлов
*   `install` / `erase` — при установке/удалении конкретного пакета

Плагины размещаются в:
*   `/usr/lib/python3/site-packages/dnf-plugins/` (DNF 4)
*   `/usr/lib64/dnf5/plugins/` (DNF 5)

DNF 5 требует переписывания плагинов на C++ для использования единого API `libdnf5`. Совместимость с плагинами DNF 4 обеспечивается только через слой совместимости или адаптеры.

### Внутреннее устройство dnf-automatic

`dnf-automatic` — сервис для автоматического применения обновлений по расписанию. Он состоит из трех компонентов:

1.  **Timer unit:** `dnf-automatic.timer` запускает сервис по системному времени.
2.  **Service unit:** `dnf-automatic.service` выполняет сканирование обновлений и их установку.
3.  **Конфигурация:** `/etc/dnf/automatic.conf` управляет поведением через секции `[commands]`, `[emitters]` и `[command_emitters]`.

Таймер использует `Persistent=true`, что означает запуск сервиса сразу после загрузки системы, если запуск был пропущен. Это критично для серверов, которые могут быть выключены во время планового окна обновлений.

---

## Практические сценарии

### Автоматизация обновлений с dnf-automatic

Утилита `dnf-automatic` позволяет настроить автоматическую загрузку и установку обновлений (аналог `unattended-upgrades`).

1.  **Установка:** `sudo dnf install dnf-automatic`.
2.  **Конфигурация:** Файл `/etc/dnf/automatic.conf`.
    *   `upgrade_type = security` — устанавливать только обновления безопасности.
    *   `download_updates = yes` — скачивать пакеты автоматически.
    *   `apply_updates = yes` — применять обновления без участия пользователя.
    *   `emit_via = email` — уведомлять о результатах по почте.
3.  **Активация:** `sudo systemctl enable --now dnf-automatic.timer`.

**Полный пример конфигурации для production:**

```ini
[commands]
upgrade_type = security
download_updates = yes
apply_updates = yes
random_sleep = 0

[emitters]
emit_via = command
command_format = echo "DNF automatic: {update_count} updates available"
output_width = 80

[command_emitters]
command = /usr/local/bin/dnf-update-notify.sh
```

Скрипт уведомления `/usr/local/bin/dnf-update-notify.sh`:
```bash
#!/bin/bash
# Принимает на вход данные от dnf-automatic через stdin
# Пример интеграции с Slack/PagerDuty/локальным логом
logger -t dnf-automatic "Update notification received"
```

**Режимы `emit_via`:**
*   `stdout` — вывод в стандартный поток (для journalctl)
*   `email` — отправка через локальный MTA (postfix, sendmail)
*   `motd` — запись в `/etc/motd`
*   `command` — запуск внешнего скрипта

### Расширенное управление через плагины

Плагины расширяют базовую логику DNF без изменения ядра системы.

| Плагин | Сценарий использования | Команда / Настройка |
| :--- | :--- | :--- |
| **versionlock** | Запрет обновления критически важного ПО (например, ядра или БД). | `dnf versionlock add <pkg>` |
| **post-transaction-actions** | Выполнение скриптов (очистка кэша, рестарт сервиса) после транзакции. | `/etc/dnf/plugins/post-transaction-actions.d/` |
| **needs-restarting** | Проверка, какие процессы требуют перезапуска после обновления библиотек. | `dnf needs-restarting -s` |
| **copr** | Работа с репозиториями сообщества (аналог PPA). | `dnf copr enable <user/repo>` |
| **leaves** | Поиск пакетов, от которых не зависят другие пакеты (кандидаты на удаление). | `dnf leaves` |

#### Пример post-transaction-actions

Файл: `/etc/dnf/plugins/post-transaction-actions.d/web.action`
```text
# <package_name>:<state>:<shell_command>
nginx:any:systemctl reload nginx
rsyslog:update:systemctl restart rsyslog
openssl:update:/usr/local/bin/notify-ssl-update.sh
```

Триггеры `state`:
*   `update` — пакет обновлен с более новой версии
*   `install` — пакет установлен впервые
*   `erase` — пакет удален
*   `any` — любое изменение состояния

#### Детализация плагинов

**needs-restarting:**
```bash
# Список процессов, требующих перезапуска после обновления shared-библиотек
sudo dnf needs-restarting -s

# Список пакетов, после обновления которых требуется перезагрузка ОС
sudo dnf needs-restarting -r

# Интеграция с systemd: автоматический рестарт сервисов
sudo systemctl list-units --type=service --state=running | awk '{print $1}' | while read svc; do
    sudo systemctl restart "$svc"
done
```

**leaves:**
```bash
# Поиск "листьев" в дереве зависимостей (пакеты, от которых ничего не зависит)
dnf leaves

# Только установленные пакеты
dnf leaves --installed

# Безопасный сценарий удаления (проверка перед удалением)
dnf leaves --installed | xargs -p sudo dnf remove
```

**copr:**
```bash
# Включение репозитория COPR
sudo dnf copr enable @cockpit/cockpit-preview

# Установка пакета из COPR
sudo dnf install cockpit

# Просмотр включенных COPR-репозиториев
dnf copr list

# Отключение COPR (сохраняет установленные пакеты)
sudo dnf copr disable @cockpit/cockpit-preview
```

> **Важно для production:** COPR — сторонние репозитории без гарантий поддержки. В production используйте только репозитории с проверенными подписями GPG и официальные mirror'ы.

### Тюнинг производительности (dnf.conf)

Продвинутые параметры для оптимизации работы в высоконагруженных или ограниченных средах.

*   **Параллельная загрузка:** `max_parallel_downloads=10` (ускоряет скачивание на быстрых каналах).
*   **Выбор зеркала:** `fastestmirror=True` (выбирает ближайшее зеркало по пингу).
*   **Тайм-ауты:** `ip_resolve=4` (форсирует IPv4, если IPv6 работает медленно/нестабильно).
*   **Очистка зависимостей:** `clean_requirements_on_remove=True` (минимизирует накопление "мусора" в системе).

**Дополнительные параметры для production:**

```ini
[main]
# Транзакции
skip_if_unavailable=False  # Прерывать, если репозиторий недоступен (для predictability)
best=True                  # Всегда выбирать максимальную версию (для security)

# Сеть
retries=6                  # Повторные запросы при тайм-аутах
timeout=30                 # Тайм-аут одного запроса (секунды)
http_caching=all           # Использовать HTTP ETag/Last-Modified

# Delta RPM
deltarpm=True              # Использовать DRPM для экономного трафика (только DNF 4)

# Логирование
debuglevel=2               # Подробность логов DNF
errorlevel=2               # Уровень ошибок для отладки
```

### Управление репозиториями в промышленной эксплуатации

В production-средах требуется контроль над источниками пакетов, приоритетами и доступностью.

```bash
# Включение репозитория только для одной сессии (без сохранения в .repo)
sudo dnf --enablerepo=<repo_id> install <package_name>

# Настройка приоритета репозитория (плагин dnf-plugins-core)
sudo dnf config-manager --setopt=<repo_id>.priority=1 --save

# Проверка приоритетов
dnf repolist -v

# Использование metalink для автоматического выбора зеркала
cat <<EOF | sudo tee /etc/yum.repos.d/fedora.repo
[fedora]
name=Fedora $releasever - $basearch
metalink=https://mirrors.fedoraproject.org/metalink?repo=fedora-$releasever&arch=$basearch
enabled=1
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-$releasever-primary
EOF
```

**Приоритеты репозиториев:** Чем ниже числовое значение `priority`, тем выше приоритет. При конфликте версий DNF выберет пакет из репозитория с наименьшим значением `priority`.

### Управление GPG-ключами

GPG-верификация обеспечивает целостность и происхождение пакетов.

```bash
# Импорт ключа репозитория (с проверкой отпечатка)
sudo rpm --import --checksum sha256:abcd1234... https://example.com/RPM-GPG-KEY

# Проверка импортированных ключей
rpm -qa gpg-pubkey --qf "%{name}-%{version}\n"

# Верификация конкретного пакета
rpm -K /path/to/package.rpm

# Экспорт ключа для распространения в инфраструктуре
rpm -qa gpg-pubkey --qf "%{name}\n" | grep -i repo-name
rpm -qi --queryformat "%{signatures}\n" gpg-pubkey-<key-id>
```

**Ротация ключей в production:**
1.  Импортируйте новый ключ ДО истечения срока действия старого.
2.  Обновите `.repo` файлы с новым `gpgkey`.
3.  После успешного обновления репозиториев удалите старый ключ: `sudo rpm -e gpg-pubkey-<old-key-id>`.

### Аудит и соответствие

DNF предоставляет инструменты для аудита состояния системы и проверки соответствия базовому уровню (baseline).

```bash
# Список пакетов, установленных не из репозиториев
dnf list extras

# Список пакетов, установленных явно пользователем (не как зависимости)
dnf repoquery --userinstalled

# Список всех файлов пакета (для аудита целостности)
dnf repoquery -l <package_name>

# Проверка, какие пакеты устарели относительно репозиториев
dnf check-update

# Аудит обновлений безопасности
dnf updateinfo list cves

# Полный отчет по обновлениям с критичностью
dnf updateinfo summary
```

**Интеграция с compliance-инструментами:**
```bash
# Генерация SBOM (Software Bill of Materials)
sudo dnf repoquery --installed --queryformat '%{name}-%{epoch}:%{version}-%{release}.%{arch}\n' > /tmp/sbom.txt

# Проверка на уязвимости (требуется подключение к базе CVE)
sudo dnf updateinfo list cves --security
```

### Стратегии кэширования для офлайн-сред

В air-gapped средах или при нестабильном соединении требуется тщательное управление кэшем.

```bash
# Настройка per-repo метаданных (в .repo файле)
[local-repo]
name=Local Mirror
baseurl=http://mirror.local/centos/$releasever/$basearch
enabled=1
gpgcheck=1
metadata_expire=7d    # Обновлять метаданные раз в неделю

# Принудительное обновление только конкретного репозитория
sudo dnf makecache --repo=local-repo

# Создание зеркала репозитория (для air-gapped сред)
sudo dnf reposync --repoid=fedora --download-metadata --downloadcomps --delete --delete-after

# Создание локального репозитория из скачанных пакетов
sudo dnf install createrepo_c
mkdir -p /var/www/html/local-repo/{pkgs,repodata}
cp /path/to/*.rpm /var/www/html/local-repo/pkgs/
createrepo_c /var/www/html/local-repo

# Настройка .repo файла для локального зеркала
cat <<EOF | sudo tee /etc/yum.repos.d/local.repo
[local]
name=Local Repository
baseurl=file:///var/www/html/local-repo
enabled=1
gpgcheck=0
EOF
```

### Стандартизация окружений через группы

Группы пакетов обеспечивают повторяемую установку окружения ( Infrastructure as Code).

```bash
# Список доступных групп окружений (Environment Groups)
sudo dnf group list --hidden

# Установка серверного окружения без GUI
sudo dnf group install "Server with GUI"

# Установка группы Development Tools
sudo dnf group install "Development Tools"

# Проверка, какие группы установлены
sudo dnf group mark install "Development Tools"

# Экспорт списка установленных групп для воссоздания окружения
sudo dnf group list --installed > /tmp/installed_groups.txt
```

### Тестирование транзакций перед применением

Перед применением критических обновлений на production используйте dry-run механизмы:

```bash
# Проверка, какие пакеты будут обновлены/установлены/удалены
sudo dnf upgrade --assumeno

# Проверка конкретного пакета
sudo dnf install <package_name> --assumeno

# Только загрузка пакетов без установки
sudo dnf upgrade --downloadonly --downloaddir=/tmp/updates

# Проверка зависимостей для офлайн-установки
dnf repoquery --requires <package_name> | dnf repoquery --whatprovides -
```

### Анализ влияния обновлений

Перед массовым обновлением оцените, что изменится в системе.

```bash
# Список доступных обновлений с деталями
dnf list updates

# Просмотр changelog обновлений
dnf updateinfo info

# Анализ, какие пакеты станут candidates на удаление (orphaned)
dnf repoquery --extras

# Пакеты, установленные явно пользователем (не как зависимости)
dnf repoquery --userinstalled

# Пакеты, оставшиеся после удаления приложения
dnf leaves --installed
```

### Устранение типичных проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Failed to download metadata for repo` | Репозиторий недоступен или URL устарел | Проверьте `dnf repolist`, настройки сети, `baseurl` в `.repo` |
| `GPG check FAILED` | Неверный или отсутствующий ключ | `sudo rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-*` |
| `No space left on device` | Недостаточно места в `/var/cache/dnf` или `/var/lib/rpm` | `df -h /var`, `sudo dnf clean all` |
| `Transaction check error` | Конфликт файлов или зависимостей | `dnf distro-sync`, проверка `dnf repoquery --conflicts` |
| `Plugin versionlock не работает` | Плагин не установлен | `sudo dnf install python3-dnf-plugin-versionlock` |

---

## Дополнительная информация

### Эволюция высокоуровневых менеджеров пакетов

#### YUM (Yellowdog Updater, Modified)

YUM (Yellowdog Updater, Modified) — первоначальный высокоуровневый пакетный менеджер для RPM-based дистрибутивов, включая CentOS, RHEL и Fedora. Название происходит от проекта Yellowdog Linux — дистрибутива для архитектур PowerPC и PlayStation 3, который в 2000-х годах стал базой для первого менеджера пакетов с автоматическим разрешением зависимостей на основе RPM.

YUM успешно справлялся с разрешением зависимостей, но имел ряд фундаментальных ограничений, которые привели к его замене:

- **Высокое потребление оперативной памяти:** YUM загружал все метаданные репозитория в память целиком, что делало работу с большими репозиториями (особенно EPEL и Fedora) крайне ресурсоёмкой.
- **Медленный поиск пакетов:** Алгоритм поиска сканировал всё содержимое репозитория последовательно, без использования индексов, что приводило к длительным задержкам при работе с тысячами пакетов.
- **Отсутствие SAT-солвера:** Разрешение зависимостей выполнялось итеративно, без глобальной оптимизации графа, что могло приводить к субоптимальным решениям и конфликтам.
- **Застреленная версия Python 2:** В последние годы поддержка Python 2 становилась критической проблемой совместимости.

#### Переход на DNF (Dandified YUM)

DNF (Dandified YUM) — наследник YUM, разработанный с нуля для устранения перечисленных ограничений. Ключевые изменения:

- **SAT-солвер `libsolv`:** Разрешение зависимостей выполняется с использованием алгоритма вещественного решателя (SAT-solver), что гарантирует поиск оптимального и непротиворечивого решения даже в сложных графах зависимостей.
- **Инкрементальные метаданные:** DNF использует локальный кэш метаданных с настраиваемым сроком жизни (`metadata_expire`), минимизируя сетевые запросы.
- **Совместимость синтаксиса:** Все команды YUM (`search`, `install`, `remove`, `update`) работают в DNF без изменений, что упрощает миграцию.
- **Поддержка модульности (AppStream):** Возможность переключения между версиями одних и тех же приложений (например, `nodejs:18` vs `nodejs:20`) на одном дистрибутиве.

#### DNF 5

DNF 5 представляет собой полную переработку пакетного менеджера, направленную на унификацию и производительность.

*   **Архитектурный сдвиг:** Переход с Python (DNF 4) на C++ (библиотека `libdnf5`). Это устраняет накладные расходы интерпретатора и снижает потребление оперативной памяти до 3-4 раз.
*   **Унификация API:** В DNF 4 логика была распределена между `python-dnf` и `libdnf`. В DNF 5 всё сосредоточено в `libdnf5`, что обеспечивает идентичное поведение CLI, плагинов и графических интерфейсов (например, Cockpit).
*   **Отказ от Delta RPM (DRPM):** В DNF 5 поддержка DRPM удалена. Современные скорости сетей и накладные расходы на вычисление дельт сделали этот механизм менее эффективным по сравнению с чистой загрузкой RPM.
*   **Улучшенная обработка метаданных:** Новый движок быстрее индексирует пакеты и эффективнее работает с SQLite базами данных репозиториев.
*   **Совместимость плагинов:** Плагины DNF 4 (Python) не работают в DNF 5 (C++). Требуется переписывание или использование слоя совместимости.

### Сравнение поколений пакетных менеджеров

| Характеристика | YUM (Legacy) | DNF 4 (Current) | DNF 5 (Next-gen) |
| :--- | :--- | :--- | :--- |
| **Язык реализации** | Python 2 | Python 3 + C | C++ |
| **Разрешение зависимостей** | Итеративное | SAT Solver (libsolv) | SAT Solver (libsolv5) |
| **Потребление RAM** | Высокое | Среднее | Минимальное |
| **Поддержка модулей** | Нет | Полная | Полная (оптимизирована) |
| **Delta RPM** | Да | Да | Нет |
| **API** | Монолитный Python | Раздельный (python-dnf + libdnf) | Единый libdnf5 |
| **Плагины** | Python | Python | C++ |

### Связанные документы

- **[Определения DNF](./definitions.md)** — глоссарий и терминология.
- **[Основные понятия DNF](./basic_concepts.md)** — архитектура и базовая настройка `dnf.conf`.
- **[Практические сценарии DNF](./practical_scenarios.md)** — полный справочник команд.
- **[Управление репозиториями DNF](../Repository_Management/index.md)** — детальная настройка источников ПО.
