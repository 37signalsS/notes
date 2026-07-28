# Управление репозиториями в Debian и Ubuntu (sources.list)

## Определения

Ниже приведены основные термины, используемые при настройке источников программного обеспечения в системах на базе DEB (Debian Package).

**APT-репозиторий** — сервер или локальный каталог, хранящий пакеты и метаданные в стандартизированной структуре. Позволяет системе APT (Advanced Package Tool) находить, устанавливать и обновлять программное обеспечение.

**sources.list** — основной конфигурационный файл (`/etc/apt/sources.list`) и файлы в директории `/etc/apt/sources.list.d/`, указывающие системе, по каким адресам искать пакеты.

**GPG-ключ (GNU Privacy Guard)** — криптографический ключ для проверки цифровой подписи репозитория. Гарантирует целостность пакетов и защищает от атак подмены данных.

**Компонент репозитория** — логическая секция пакетов (например, `main`, `universe`), разделяющая ПО по типу лицензии и уровню поддержки.

**PPA (Personal Package Archive)** — персональные архивы пакетов в экосистеме Ubuntu, позволяющие разработчикам публиковать версии ПО, отличные от официальных.

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

Рекомендуется для Debian 12+ и Ubuntu 24.04+. Файлы имеют расширение `.sources` и используют структуру блоков. Это позволяет более гибко настраивать параметры:

```ini
Types: deb deb-src
URIs: https://deb.debian.org/debian
Suites: bookworm bookworm-updates
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
Architectures: amd64 arm64
```

### Компоненты дистрибутивов

#### Debian (с версии 12)
- **main**: Свободное ПО (DFS — Debian Free Software Guidelines).
- **contrib**: Свободное ПО, требующее несвободных зависимостей.
- **non-free**: Проприетарное ПО.
- **non-free-firmware**: Выделенный компонент для несвободных прошивок (драйверов) оборудования.

#### Ubuntu
- **main**: Официально поддерживаемое свободное ПО.
- **restricted**: Официально поддерживаемое несвободное ПО (драйверы).
- **universe**: Поддерживаемое сообществом свободное ПО.
- **multiverse**: Неподдерживаемое несвободное ПО.

### Безопасность: GPG и Signed-By

Использование `apt-key add` устарело и небезопасно. Современный стандарт требует:
1.  Хранить ключи в `/etc/apt/keyrings/` (для сторонних репозиториев) или `/usr/share/keyrings/` (для системных).
2.  Ключи должны быть в бинарном формате (GPG dearmor).
3.  Явно указывать путь к ключу в опции `signed-by`.

---

## Практические сценарии

### Сценарий 1: Настройка официального зеркала (Debian 12)

Рекомендуется использовать `deb.debian.org` — это сервис-балансировщик, выбирающий ближайшее зеркало.

```bash
# Пример содержимого /etc/apt/sources.list
deb http://deb.debian.org/debian/ bookworm main non-free-firmware
deb http://security.debian.org/debian-security bookworm-security main non-free-firmware
deb http://deb.debian.org/debian/ bookworm-updates main non-free-firmware
```

### Сценарий 2: Добавление стороннего репозитория (Docker)

```bash
# 1. Создание директории для ключей
sudo install -m 0755 -d /etc/apt/keyrings

# 2. Скачивание и деарморинг ключа
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 3. Добавление репозитория в формате DEB822
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

Если сервер находится за корпоративным прокси-сервером:

```bash
# Создание файла /etc/apt/apt.conf.d/proxy.conf
Acquire::http::Proxy "http://proxy.example.com:8080";
Acquire::https::Proxy "http://proxy.example.com:8080";
```

---

## Дополнительная информация

### Диагностика и инструменты

- **`apt policy`**: Просмотр приоритетов и версий пакетов в подключенных репозиториях.
- **`apt-get indextargets`**: Просмотр детальной информации об индексах репозиториев.
- **`lsb_release -c`**: Быстрое получение кодового имени текущего дистрибутива.

### Рекомендации по эксплуатации

1.  **HTTPS**: Всегда предпочитайте `https://` для защиты от подмены пакетов в пути (даже при наличии GPG).
2.  **Минимализм**: Не добавляйте репозитории от других версий ОС (например, Debian пакеты в Ubuntu) — это ведет к "Franken-Debian" (нестабильной системе).
3.  **Архитектуры**: Используйте опцию `arch=amd64` (или другие), если репозиторий поддерживает только специфическую архитектуру, чтобы избежать ошибок при `apt update` на мультиархитектурных системах.

### Связанные документы

- **[Apt Pinning](./deb_apt_pinning.md)** — управление приоритетами пакетов.
- **[Зеркалирование APT](./apt_mirror/practical_scenarios.md)** — создание локальных копий репозиториев.
- **[Обзор управления пакетами](../linux_package_management_overview.md)** — архитектурные принципы.
