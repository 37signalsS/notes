# Управление репозиториями в Debian и Ubuntu (sources.list)

## Определения

Ниже приведены основные термины, используемые при настройке источников программного обеспечения в системах на базе DEB (Debian Package).

**APT-репозиторий** — сервер или локальный каталог, хранящий пакеты (`.deb`) и метаданные (индексы) в стандартизированной структуре. Позволяет системе APT (Advanced Package Tool) находить, устанавливать и автоматически обновлять программное обеспечение.

**sources.list** — основной конфигурационный файл (`/etc/apt/sources.list`), указывающий системе, по каким сетевым или локальным адресам искать пакеты. На современных системах (Debian 12+, Ubuntu 24.04+) этот файл может содержать только комментарий о миграции настроек в директорию `/etc/apt/sources.list.d/`.

**Файлы `.sources`** — конфигурационные файлы в директории `/etc/apt/sources.list.d/` с расширением `.sources`, использующие формат DEB822 (многострочные блоки). На Ubuntu 24.04+ файл `sources.sources` является основным хранилищем адресов репозиториев, заменяя классический `sources.list`.

**Release-файл** — текстовый метаданный файл в директории `dists/<suite>/`, содержащий информацию о дистрибутиве: дату выпуска, поддерживаемые архитектуры, список компонентов, хэш-суммы индексных файлов (`Packages`, `Sources`, `Contents`) и флаги безопасности (`Not-Automatic`, `But-Automatic-Upgrades`).

**InRelease** — объединённый файл, содержащий метаданные `Release` и встроенную подпись (clear-signed). Используется для проверки целостности репозитория без отдельного файла `Release.gpg`.

**Packages.gz / Packages** — индексный файл со списком всех доступных бинарных пакетов (`.deb`) в репозитории, их версий, зависимостях, размерах и контрольных суммах. Файл сжимается в `.gz` для экономии трафика.

**Sources** — индексный файл с исходными пакетами (`.dsc`, `.tar.gz`, `.debian.tar.xz`). Необходим для пересборки пакетов.

**Suite (Сют)** — логическая группа дистрибутивов, объединённых общим циклом разработки. Примеры: `stable`, `testing`, `unstable` в Debian или `noble`, `jammy` в Ubuntu.

**Codename (Кодовое имя)** — символическое имя конкретного выпуска дистрибутива (например, `bookworm`, `noble`, `jammy`). Является первичным ключом для поиска пакетов в `sources.list`.

**GPG-ключ (GNU Privacy Guard)** — криптографический ключ для проверки цифровой подписи репозитория. Гарантирует целостность пакетов и защищает от атак подмены данных (MITM).

**Компонент репозитория (Section/Component)** — логическая секция пакетов (например, `main`, `universe`), разделяющая ПО по типу лицензии, происхождению и уровню поддержки.

**PPA (Personal Package Archive)** — персональные архивы пакетов в экосистеме Ubuntu (Launchpad), позволяющие разработчикам публиковать версии ПО, отличные от официальных.

**By-Hash** — механизм доступа к индексным файлам и пакетам по их хэш-сумме вместо имени файла. Предотвращает ошибку "Hash Sum mismatch" при обновлении индексов на сервере во время скачивания клиентом.

**PDiffs (Patch Diffs)** — файлы дельта-обновлений индексов, позволяющие скачивать только изменения в `Packages`, а не полный файл целиком. Уменьшает трафик при частых обновлениях репозиториев.

**apt preferences** — механизм управления приоритетами источников пакетов. Позволяет зафиксировать версии, отдавать предпочтение определённым репозиториям или блокировать пакеты. Подробнее в документе **[Управление приоритетами пакетов в Apt (Pinning)](./deb_apt_pinning.md)**.

**apt-secure** — комплексный механизм безопасности APT, включающий проверку GPG-подписей репозиториев, целостности файлов и цепочку доверия от ключа до установленного пакета.

---

## Основные концепции

### Форматы файлов источников

#### Традиционный формат (One-line)

Записи в файлах `.list` представляют собой одну строку:
```bash
# Тип [Опции] URL Дистрибутив Компоненты
deb [arch=amd64 signed-by=/etc/apt/keyrings/repo.gpg] https://repo.example.com/debian bookworm main
```

#### Современный формат (DEB822)

Рекомендуется для Debian 12+ и Ubuntu 24.04+. Файлы имеют расширение `.sources` и используют структуру блоков, идентичную файлам `control`. Это позволяет более гибко настраивать параметры и избегать длинных нечитаемых строк:

```ini
Types: deb deb-src
URIs: https://deb.debian.org/debian
Suites: bookworm bookworm-updates bookworm-backports
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
Architectures: amd64 arm64
```

На чистой установке Ubuntu 24.04 (Noble Numbat) классический файл `/etc/apt/sources.list` содержит лишь комментарий о том, что настройки переехали. Фактические адреса репозиториев находятся в директории `/etc/apt/sources.list.d/` в файле `sources.sources` в формате DEB822. Аналогичная миграция применима к новым выпускам Debian 13 (Trixie).

### Структура репозитория Debian/Ubuntu

Официальные репозитории имеют фиксированную структуру каталогов:

```text
deb.debian.org/debian/
├── dists/
│   └── bookworm/
│       ├── Release
│       ├── InRelease
│       ├── Release.gpg
│       ├── main/
│       │   ├── binary-amd64/
│       │   │   ├── Packages
│       │   │   ├── Packages.gz
│       │   │   └── Release
│       │   └── binary-arm64/
│       │       └── ...
│       ├── contrib/
│       │   └── ...
│       └── non-free-firmware/
│           └── ...
└── pool/
    ├── main/
    │   └── a/
    │       └── app/
    │           └── app_1.0_amd64.deb
    ├── contrib/
    └── non-free-firmware/
```

Директория `dists/` содержит метаданные (индексы) с разделением по архитектурам и компонентам. Директория `pool/` содержит фактические `.deb`-файлы, организованные по начальным буквам названий пакетов для дедупликации между дистрибутивами.

### Потоки обновлений (Suites)

Официальные репозитории делятся на несколько типов в зависимости от назначения пакетов:

- **Основной релиз** (`bookworm`, `noble`): Стабильное состояние на момент выпуска.
- **security** (`bookworm-security`): Срочные исправления критических уязвимостей. Имеет наивысший приоритет.
- **updates** (`bookworm-updates`): Незначительные обновления, не влияющие на безопасность (например, исправления ошибок, не являющихся критическими).
- **backports** (`bookworm-backports`): Новые версии ПО, перенесенные из следующей (testing/unstable) ветки. Имеют низкий приоритет (Pin: 100) и не устанавливаются автоматически без явного указания.

### Компоненты дистрибутивов

#### Debian (с версии 12)
- **main**: Полностью свободное ПО (согласно DFSG).
- **contrib**: Свободное ПО, которое зависит от несвободных компонентов.
- **non-free**: Проприетарное ПО.
- **non-free-firmware**: Выделенный компонент для несвободных микрокодов и драйверов (внедрен в Debian 12 для улучшения поддержки оборудования "из коробки").

#### Ubuntu
- **main**: Официально поддерживаемое свободное ПО.
- **restricted**: Официально поддерживаемое несвободное ПО (обычно драйверы).
- **universe**: Поддерживаемое сообществом свободное ПО.
- **multiverse**: Неподдерживаемое несвободное ПО.

### Механизм `apt update` и индексы

Команда `apt update` выполняет следующие действия:
1. Загружает `Release` и `InRelease` для каждого указанного в источниках дистрибутива.
2. Проверяет GPG-подпись `InRelease` (или `Release.gpg`).
3. Сравнивает дату модификации индексов с локальной копией в `/var/lib/apt/lists/`.
4. Скачивает только изменившиеся индексные файлы (`Packages.gz`, `Sources.gz`, `Contents`).
5. Если включено PDiffs — скачивает только дельты, а не полные индексы.

Локальный кэш индексов хранится в `/var/lib/apt/lists/`. Скачанные `.deb`-пакеты хранятся в `/var/cache/apt/archives/` до установки.

### Безопасность: GPG и Signed-By

Использование устаревшего `apt-key add` небезопасно, так как ключ добавляется в глобальное доверенное хранилище, что позволяет любому репозиторию подписывать любые пакеты. Современный стандарт требует:
1. **Изоляция**: Ключи хранятся в `/etc/apt/keyrings/` (для сторонних) или `/usr/share/keyrings/` (для системных).
2. **Формат**: Ключи должны быть в бинарном формате (OpenPGP ASCII Armor должен быть конвертирован через `gpg --dearmor`).
3. **Привязка**: Использование опции `signed-by` в строке репозитория для жесткой привязки ключа к конкретному источнику.

### Флаги безопасности репозиториев

В файле `Release` может содержаться метка `Not-Automatic: yes`, указывающая APT, что пакеты из этого источника не должны автоматически обновляться без явного указания. Примером являются `*-backports`. При наличии `But-Automatic-Upgrades: yes` уже установленные пакеты будут автоматически обновляться.

### Multi-arch и архитектуры

На системах с несколькими архитектурами (например, `amd64` + `arm64` для контейнеров или кросс-компиляции) используйте опцию `Architectures:` в DEB822 или `[arch=...]` в классическом формате. Это предотвращает попытки установки пакетов для неподдерживаемых архитектур и ошибки 404.

---

## Практические сценарии

### Сценарий 1: Настройка официального зеркала (Debian 12)

Рекомендуется использовать `deb.debian.org` — это сервис-балансировщик на базе CDN, который автоматически выбирает ближайшее и наиболее быстрое зеркало.

```bash
# Пример содержимого /etc/apt/sources.list
# Основной репозиторий
deb http://deb.debian.org/debian/ bookworm main non-free-firmware
# Обновления безопасности
deb http://security.debian.org/debian-security bookworm-security main non-free-firmware
# Стабильные обновления
deb http://deb.debian.org/debian/ bookworm-updates main non-free-firmware
```

### Сценарий 2: Добавление стороннего репозитория (Docker)

Пример демонстрирует современный подход с созданием бинарного ключа и использованием формата DEB822.

```bash
# 1. Создание директории для ключей с правильными правами
sudo install -m 0755 -d /etc/apt/keyrings

# 2. Скачивание ASCII-ключа, конвертация в бинарный (dearmor) и сохранение
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 3. Добавление репозитория в современном формате DEB822
echo \
  "Types: deb
  URIs: https://download.docker.com/linux/ubuntu
  Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
  Components: stable
  Architectures: $(dpkg --print-architecture)
  Signed-By: /etc/apt/keyrings/docker.gpg" | \
  sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null
```

### Сценарий 3: Настройка прокси для APT

Если сервер находится за корпоративным прокси-сервером или используется кэширующий прокси (например, `apt-cacher-ng`):

```bash
# Создание файла /etc/apt/apt.conf.d/proxy.conf
# Можно настроить отдельно для разных протоколов
Acquire::http::Proxy "http://proxy.example.com:8080";
Acquire::https::Proxy "http://proxy.example.com:8080";
Acquire::ftp::Proxy "http://proxy.example.com:8080";

# Исключение для локальных адресов
Acquire::http::Proxy::repo.local "DIRECT";
```

### Сценарий 4: Подготовка источников для изолированной сети (Air-Gapped)

В средах без доступа в интернет используйте `snapshot.debian.org` или локальный кэш для загрузки пакетов на машине с выходом, с последующей передачей на изолированные серверы.

#### Вариант A: Использование snapshot.debian.org

```bash
# /etc/apt/sources.list
# Фиксированная дата для воспроизводимости
deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/20240101T000000Z bookworm main contrib non-free non-free-firmware
deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/20240101T000000Z bookworm-security main contrib non-free non-free-firmware

# Предварительная загрузка пакетов на машине с интернетом
sudo apt update
sudo apt install --download-only -y --reinstall nginx curl

# Упаковка кэша и перенос на изолированный сервер
sudo tar czf /tmp/apt-cache.tar.gz /var/cache/apt/archives/
```

#### Вариант B: Локальный кэш через apt-cacher-ng

Для средних сетей (<50 серверов) можно использовать кэширующий прокси `apt-cacher-ng`, который предзагружает популярные пакеты и раздаёт их клиентам. Подробнее о настройке зеркал и кэширования см. документ **[Зеркалирование APT](./apt_mirror/practical_scenarios.md)**.

### Сценарий 5: Восстановление после сбоя GPG или повреждённого кэша

#### Симптомы и диагностика

```bash
# Проверка подлинности индексов
sudo apt update
# → GPG error: ... The following signatures were invalid: ...

# Проверка статуса кэша
ls -la /var/lib/apt/lists/lock
sudo fuser /var/lib/apt/lists/lock
```

#### Решение

```bash
# 1. Очистка битого кэша индексов
sudo rm -rf /var/lib/apt/lists/*

# 2. Перезагрузка ключей репозитория (если истёк срок действия)
sudo apt-key list
sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-keys <KEY_ID>

# 3. Повторное обновление
sudo apt update

# 4. Если проблема в блокировке — завершить зависший процесс
sudo kill -9 $(sudo lsof -t /var/lib/dpkg/lock)
sudo dpkg --configure -a
```

### Сценарий 6: Мониторинг доступности репозиториев и автоматизация

#### Проверка доступности upstream

```bash
#!/bin/bash
# /usr/local/bin/check-apt-repos.sh
set -euo pipefail

REPOS=(
  "http://deb.debian.org/debian/dists/bookworm/Release"
  "http://security.debian.org/debian-security/dists/bookworm-security/Release"
)

for repo in "${REPOS[@]}"; do
  if ! curl -sfI --max-time 10 "$repo" >/dev/null; then
    echo "ALERT: $repo unreachable"
    exit 1
  fi
done

echo "OK: all repositories reachable"
```

#### Автоматическое обновление через systemd timer

```ini
# /etc/systemd/system/apt-daily-upgrade.service
[Unit]
Description=Daily APT upgrade
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/apt-get upgrade -y
ExecStartPost=/usr/bin/apt-get autoremove -y
```

```ini
# /etc/systemd/system/apt-daily-upgrade.timer
[Unit]
Description=Run daily APT upgrade

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now apt-daily-upgrade.timer
```

#### Валидация

```bash
# Проверка статуса таймера
systemctl list-timers | grep apt

# Ручной запуск
sudo systemctl start apt-daily-upgrade.service
sudo journalctl -u apt-daily-upgrade -n 20
```

### Сценарий 7: Восстановление после «Hash Sum mismatch»

Ошибка возникает, когда хэш-сумма скачанного файла не совпадает с указанной в индексе. Типичные причины: обновление индексов upstream во время скачивания, повреждение кэша, ошибки сетевого оборудования.

```bash
# 1. Очистка кэша индексов
sudo rm -rf /var/lib/apt/lists/*

# 2. Отключение PDiffs на время обновления (если ошибка повторяется)
echo 'Acquire::PDiffs "false";' | sudo tee /etc/apt/apt.conf.d/99no-pdiffs

# 3. Повторное обновление с проверкой
sudo apt update

# 4. Если проблема в конкретном источнике — временное отключение
# Удалите или закомментируйте проблемную строку в sources.list.d/
sudo rm /etc/apt/sources.list.d/problematic-repo.sources

# 5. Восстановление после Network Issue
sudo apt clean
sudo apt update
```

### Сценарий 8: Управление несколькими источниками и Pinning

При работе с несколькими репозиториями (stable, backports, security, сторонние) используйте `apt-cache policy` для анализа приоритетов и механизм Pinning для управления версиями. Подробное руководство по настройке Pinning, включая примеры конфигурации и отладку, см. в документе **[Управление приоритетами пакетов в Apt (Pinning)](./deb_apt_pinning.md)**.

```bash
# Просмотр политики всех подключенных источников
apt-cache policy

# Проверка доступных версий конкретного пакета
apt-cache policy nginx

# Список заблокированных пакетов
apt-mark showhold
```

---

## Дополнительная информация

### Диагностика и инструменты

- **`apt policy`**: Просмотр приоритетов (Pinning) и доступных версий пакетов во всех подключенных источниках.
- **`apt-config dump`**: Позволяет увидеть все примененные настройки APT, включая конфигурацию прокси, пути к кэшу и архитектуры.
- **`apt-get indextargets`**: Список всех целевых файлов (индексов), которые APT пытается скачать при обновлении.
- **`lsb_release -a`**: Полная информация о текущем дистрибутиве и его кодовом имени (`Codename`).
- **`dpkg -l`**: Аудит установленных пакетов (статус, версия, архитектура).
- **`apt list --upgradable`**: Список пакетов, доступных для обновления.
- **`apt-get install --download-only`**: Предварительная загрузка пакетов без установки (полезно для air-gapped сред).

### Рекомендации по эксплуатации

1.  **HTTPS**: Всегда предпочитайте `https://` для защиты от перехвата и инъекций на уровне транспортного протокола (даже если используется проверка GPG).
2.  **Минимализм (Franken-Debian)**: Избегайте добавления репозиториев от других версий ОС (например, репозитории Ubuntu в Debian). Это нарушает стабильность зависимостей и может привести к неработоспособности системы.
3.  **Архитектуры**: На мультиархитектурных системах всегда указывайте `arch=amd64` (или аналогичную) для сторонних репозиториев, которые не поддерживают все архитектуры вашей системы. Это предотвратит ошибки 404 при выполнении `apt update`.
4.  **Очистка**: При удалении стороннего ПО не забывайте удалять соответствующие файлы из `/etc/apt/sources.list.d/` и ключи из `/etc/apt/keyrings/`.
5.  **Воспроизводимость**: Для критичных систем используйте `snapshot.debian.org` с фиксированной датой или локальные зеркала, чтобы гарантировать одинаковые версии пакетов во времени.
6.  **Безопасность**: Храните ключи в `/etc/apt/keyrings/` с правами `0644` (чтение для всех), а не в `/root/`. Используйте `signed-by` для привязки ключа к источнику.
7.  **Валидация**: После любого изменения в `sources.list.d/` всегда запускайте `apt update` и проверяйте вывод на ошибки GPG и 404.

### Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **GPG: NO_PUBKEY** | Ключ репозитория отсутствует в keyring. | Убедитесь, что ключ добавлен через `gpg --dearmor` и указан в `signed-by`. |
| **404 Not Found** | Неправильный URL, дистрибутив или архитектура. | Проверьте `dpkg --print-architecture` и наличие дистрибутива на upstream. |
| **Hash Sum mismatch** | Индексы upstream обновились во время скачивания. | Выполните `sudo rm -rf /var/lib/apt/lists/* && sudo apt update`. |
| **Битый кэш** | Некорректное завершение `apt update`. | Выполните `sudo apt clean && sudo apt update`. |
| **apt update зависает** | Проблема с DNS или недоступность upstream. | Проверьте `curl -I http://deb.debian.org/debian/dists/bookworm/Release`. |
| **Временно недоступен (Temporary failure)** | Проблема с сетью или прокси. | Проверьте настройки прокси в `/etc/apt/apt.conf.d/`. |

### Связанные документы

- **[Apt Pinning](./deb_apt_pinning.md)** — управление приоритетами пакетов.
- **[Зеркалирование APT](./apt_mirror/practical_scenarios.md)** — создание локальных копий репозиториев.
- **[Приватный репозиторий (reprepro)](./deb_private_apt_repository_reprepro/definitions_and_concepts.md)** — создание собственной инфраструктуры.
- **[Обзор управления пакетами](./linux_package_management_overview.md)** — архитектурные принципы.
- **[База данных пакетов](./package_database.md)** — внутреннее устройство `dpkg`.
