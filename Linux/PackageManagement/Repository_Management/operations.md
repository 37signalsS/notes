# Операции с репозиториями DNF

## Определения

Ниже приведены термины, специфичные для выполнения операций по управлению источниками программного обеспечения. Базовые понятия (идентификатор, GPG-ключ, repodata) описаны в главном разделе **[Управление репозиториями](./index.md)**.

**EPEL (Extra Packages for Enterprise Linux)** — репозиторий от сообщества Fedora, содержащий пакеты высокого качества, совместимые с RHEL-based системами.

**COPR (Cool Other Package Repo)** — сервис для создания персональных репозиториев (аналог PPA в Ubuntu). Позволяет пользователям собирать пакеты и распространять их через DNF без необходимости поддерживать собственный веб-сервер.

**Метаданные (Metadata)** — XML/SQLite индексы репозитория, содержащие списки пакетов, зависимости и контрольные суммы. DNF загружает их в локальный кэш (`/var/cache/dnf/<repo_id>*/`) перед операциями.

**Repoquery** — утилита из `dnf-plugins-core` для выполнения сложных запросов к базе данных пакетов. Позволяет фильтровать пакеты по репозиторию, архитектуре, зависимостям.

**Repoclosure** — проверка целостности зависимостей внутри репозитория. Обнаруживает "разорванные" зависимости, когда пакет требует другой, отсутствующий в том же репозитории.

**Config-manager** — встроенный инструмент CLI для динамического управления репозиториями без редактирования `.repo` файлов вручную. В DNF 5 является нативной подкомандой, в DNF 4 — плагином `dnf-plugins-core`.

**Priority (Приоритет репозитория)** — числовое значение (1–99), определяющее предпочтительный источник пакета при наличии одинаковой версии в разных репозиториях. Чем меньше значение, тем выше приоритет. Требует плагин `dnf-plugins-core`.

**skip_if_unavailable** — параметр, определяющий, прерывать ли транзакцию при недоступности репозитория. `False` (по умолчанию) — прерывать; `True` — пропускать недоступные репозитории.

**repomd.xml** — индексный файл метаданных репозитория. Содержит контрольные суммы и пути к остальным индексным файлам (`primary.xml`, `filelists.xml`, `other.xml`, `comps.xml`). Подписывается GPG-ключом репозитория.

---

## Основные концепции

### Методология управления через CLI

DNF предоставляет два способа изменения конфигурации репозиториев:
1.  **Перманентные изменения:** Использование `config-manager`. Изменения записываются в соответствующие `.repo` файлы в `/etc/yum.repos.d/`.
2.  **Временные переопределения:** Использование флагов `--enablerepo` и `--disablerepo` в конкретной команде (например, `dnf install`). Изменения действуют только для одной транзакции.

### Переход на DNF 5

В DNF 5 (Fedora 41+, RHEL 10) архитектура управления репозиториями стала более строгой. `config-manager` теперь является встроенной подкомандой, а синтаксис унифицирован:
- **DNF 4:** `dnf config-manager --add-repo <url>`
- **DNF 5:** `dnf config-manager addrepo <url>`

### Жизненный цикл загрузки метаданных

При выполнении любой операции DNF проходит следующие этапы:
1.  **Сканирование конфигурации:** Чтение `.repo` файлов из `/etc/yum.repos.d/` и `/etc/dnf/dnf.conf`.
2.  **Загрузка `repomd.xml`:** DNF запрашивает индексный файл у каждого активного репозитория. При включенном `repo_gpgcheck=1` выполняется верификация подписи перед использованием.
3.  **Загрузка остальных индексов:** `primary.xml`/`primary.sqlite`, `filelists.xml`, `other.xml`, `updateinfo.xml`. В DNF 4+ метаданные преобразуются в SQLite для ускорения поиска.
4.  **Кэширование:** Индексы сохраняются в `/var/cache/dnf/<repo_id>*/`. Срок актуальности управляется параметром `metadata_expire`.

### Уровни изоляции репозиториев

DNF поддерживает несколько механизмов ограничения доступа к пакетам:
- **`includepkgs`:** Белый список пакетов, разрешённых для загрузки из репозитория. Остальные пакеты игнорируются, даже если они доступны.
- **`exclude`:** Чёрный список пакетов, которые не будут загружаться из репозитория.
- **`priority`:** Определяет порядок выбора репозитория при наличии одинаковых версий пакетов.

---

## Справочник параметров .repo файла

### Обязательные параметры

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `name` | Человекочитаемое имя репозитория | `name=AlmaLinux 9 BaseOS` |
| `baseurl` | URL или локальный путь к корню репозитория | `baseurl=https://repo.almalinux.org/almalinux/9/BaseOS/$basearch/os/` |
| `mirrorlist` | URL, возвращающий список зеркал | `mirrorlist=https://mirrors.fedoraproject.org/metalink?repo=fedora-$releasever&arch=$basearch` |
| `metalink` | URL XML-файла с метаданными зеркал (контрольные суммы, приоритеты) | `metalink=https://mirrors.fedoraproject.org/metalink?repo=fedora-$releasever&arch=$basearch` |
| `enabled` | Активен ли репозиторий (1/0/True/False) | `enabled=1` |

> **Важно:** `baseurl`, `mirrorlist` и `metalink` взаимозаменяемы. Используйте только один из них в секции. Если указаны несколько — DNF использует первый встреченный.

### Безопасность

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `gpgcheck` | Проверка GPG-подписи каждого `.rpm` файла (1/0) | `gpgcheck=1` |
| `gpgkey` | Путь или URL к публичному ключу GPG | `gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-AlmaLinux-9` |
| `repo_gpgcheck` | Проверка подписи метаданных `repomd.xml` (1/0) | `repo_gpgcheck=1` |
| `sslverify` | Проверка SSL-сертификата сервера (1/0) | `sslverify=1` |
| `sslclientcert` | Путь к клиентскому сертификату для mTLS | `sslclientcert=/etc/pki/tls/certs/client.pem` |
| `sslclientkey` | Путь к приватному ключу клиента для mTLS | `sslclientkey=/etc/pki/tls/private/client.key` |

### Фильтрация и приоритизация

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `priority` | Приоритет репозитория (1 — наивысший, 99 — низший) | `priority=10` |
| `includepkgs` | Список пакетов, которые РАЗРЕШЕНО брать из этого репозитория | `includepkgs=nginx,php-*,httpd` |
| `exclude` | Список пакетов, которые ЗАПРЕЩЕНО брать из этого репозитория | `exclude=kernel*,firmware*` |

### Производительность и сеть

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `metadata_expire` | Время актуальности кэша метаданных | `metadata_expire=6h`, `metadata_expire=1d`, `metadata_expire=never` |
| `skip_if_unavailable` | Пропускать репозиторий при недоступности (True/False) | `skip_if_unavailable=True` |
| `best` | Всегда выбирать максимальную доступную версию (True/False) | `best=True` |
| `proxy` | URL прокси для этого репозитория | `proxy=http://proxy.internal.local:3128` |
| `proxy_username` | Имя пользователя для аутентификации на прокси | `proxy_username=svc_dnf` |
| `proxy_password` | Пароль для аутентификации на прокси | `proxy_password=SecretPass` |

### Глобальные параметры (dnf.conf)

Критически важные параметры из `/etc/dnf/dnf.conf`, влияющие на работу с репозиториями:

```ini
[main]
gpgcheck=1              # Проверка подписей всех пакетов
repo_gpgcheck=0         # Проверка подписи repomd.xml (0 по умолчанию, 1 для доверенных зеркал)
protected_packages=dnf, glibc, systemd  # Защищенные пакеты
skip_if_unavailable=False  # Прерывать транзакцию при недоступности репозитория
best=True               # Всегда выбирать максимальную версию
metadata_expire=6h      # Срок актуальности кэша
max_parallel_downloads=10  # Параллельные загрузки
fastestmirror=True      # Автоматический выбор ближайшего зеркала
retries=6               # Количество повторов при тайм-аутах
timeout=30              # Тайм-аут одного запроса (секунды)
```

---

## Динамические переменные

DNF поддерживает подстановку переменных в `.repo` файлах для универсальности конфигураций.

### Встроенные переменные

| Переменная | Описание | Источник |
| :--- | :--- | :--- |
| `$releasever` | Мажорная версия дистрибутива | `/etc/os-release` (VERSION_ID) |
| `$basearch` | Базовая архитектура (x86_64, aarch64, ppc64le) | Автоопределение ядра |
| `$arch` | Конкретная архитектура CPU (i686, x86_64, s390x) | `uname -i` |
| `$infra` | Тип инфраструктуры (container, vagrant, cloud) | Автоопределение через virt-what |

### Пользовательские переменные

Любой файл в `/etc/dnf/vars/` создает переменную с именем файла и содержимым этого файла:

```bash
# Создание переменной для корпоративного зеркала
echo "http://repo.internal.local" | sudo tee /etc/dnf/vars/mirror_url

# Использование в .repo файле
[internal]
name=Internal Repository
baseurl=$mirror_url/alma9/$releasever/$basearch/os/
enabled=1
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-internal
```

### Валидация переменных

```bash
# Проверка значения переменной
dnf repolist --show-duplicates
# → Если $releasever или $basearch не определены, URL будет некорректным

# Отладка подстановки
sudo dnf repolist -v
# → Выводит полные URL для каждого репозитория
```

---

## Практические сценарии

### Сценарий 1: Глубокая инвентаризация и поиск

Команды для анализа содержимого конкретных источников и verification состояния репозиториев.

```bash
# Показать только активные репозитории с количеством пакетов
dnf repolist
# → Вывод: repo_id, name, status (enabled/disabled), packages count

# Список всех репозиториев с детальной информацией (URL, срок кэша, GPG)
dnf repoinfo
dnf repoinfo <repo_id>
# → Base URL, mirrorlist, metalink, enabled/disabled, GPG status, metadata_expire

# Вывод всех пакетов, доступных в конкретном репозитории
dnf repository-packages <repo_id> list
# → Список пакетов с архитектурой и версией

# Проверка, из какого репозитория был установлен конкретный пакет
dnf list installed <package_name>
# → Результат в последней колонке (например, @anaconda или @updates)

# Детальный поиск по репозиторию (требует dnf-plugins-core)
dnf repoquery --repoid=<repo_id> --list <package_name>
# → Полный список файлов пакета внутри репозитория

# Проверка доступности конкретного пакета в конкретном репозитории
dnf list --showduplicates <package_name> --repoid=<repo_id>
# → Все доступные версии из указанного источника
```

**Валидация:**
```bash
# Экспорт инвентаря для аудита
dnf repolist -v > /tmp/repo-inventory-$(date +%Y%m%d).txt
# → Включает: baseurl, mirrorlist, metalink, enabled/disabled, GPG статус
```

### Сценарий 2: Управление состоянием (Включение/Выключение)

Использование временных флагов для изоляции окружения и пакетных операций.

```bash
# Установка пакета ТОЛЬКО из конкретного репозитория (игнорируя остальные)
sudo dnf install <package> --disablerepo="*" --enablerepo=<repo_id>

# Временное включение репозитория для обновления
sudo dnf upgrade --enablerepo=epel-testing

# Перманентное включение репозитория (запись в .repo файл)
sudo dnf config-manager --set-enabled <repo_id>

# Перманентное отключение репозитория
sudo dnf config-manager --set-disabled <repo_id>

# Включение нескольких репозиториев сразу
sudo dnf config-manager --set-enabled=repo1,repo2,repo3

# Проверка приоритетов после настройки
dnf repolist -v
# → Поле "Priority" показывает значение для каждого репозитория
```

### Сценарий 3: Добавление и настройка источников

Подробные операции по добавлению новых репозиториев и тонкой настройке параметров.

```bash
# Добавление репозитория по URL (DNF 4)
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo

# Добавление репозитория по URL (DNF 5)
sudo dnf config-manager addrepo --from-repofile=https://download.docker.com/linux/centos/docker-ce.repo

# Подключение репозитория COPR
sudo dnf copr enable <user/project>

# Тонкая настройка параметра через CLI (например, установка приоритета)
sudo dnf config-manager --setopt=<repo_id>.priority=10 --save

# Настройка прокси для конкретного репозитория через .repo файл
cat <<EOF | sudo tee /etc/yum.repos.d/internal.repo
[internal]
name=Internal Repository
baseurl=http://repo.internal.local/alma9/\$releasever/\$basearch/os/
enabled=1
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-internal
priority=5
proxy=http://proxy.internal.local:3128
proxy_username=svc_dnf
proxy_password=SecretPass
EOF

# Валидация добавленного репозитория
sudo dnf repolist
sudo dnf repoinfo <repo_id>
curl -s -o /dev/null -w "%{http_code}" http://repo.internal.local/alma9/9/x86_64/os/repodata/repomd.xml
# → Ожидается 200
```

### Сценарий 4: Отладка и работа с кэшем

Критически важно при возникновении ошибок "Metadata conflict" или проблем с зеркалами.

```bash
# Принудительное обновление метаданных с выводом отладочной информации
sudo dnf makecache --verbose
# → Показывает: загружаемые URL, размеры файлов, статус GPG

# Очистка кэша только для одного репозитория (чтобы не перекачивать всё)
sudo dnf clean metadata --repo=<repo_id>

# Полная очистка кэша (метаданные + скачанные RPM)
sudo dnf clean all

# Пропуск битых репозиториев (позволяет обновить систему, если одно зеркало упало)
sudo dnf upgrade --skip-broken --setopt=skip_if_unavailable=True

# Очистка только устаревших метаданных (сохраняет скачанные RPM)
sudo dnf clean metadata

# Проверка актуальности кэша без внесения изменений
dnf check-update
# → Возвращает 0 если обновлений нет, 100 если есть, 1 при ошибке
```

### Сценарий 5: Управление GPG-ключами

Операции импорта, верификации и ротации GPG-ключей репозиториев.

```bash
# Импорт ключа напрямую из URL
sudo rpm --import https://keys.example.com/RPM-GPG-KEY-project

# Импорт с проверкой отпечатка (SHA256)
sudo rpm --import --checksum sha256:abcd1234... https://keys.example.com/RPM-GPG-KEY-project

# Проверка, какие ключи уже установлены в системе
rpm -q gpg-pubkey --qf '%{name}-%{version}-%{release} --> %{summary}\n'

# Верификация конкретного пакета
rpm -K /path/to/package.rpm
# → Должен показать: RSA sha256 (<<FINGERPRINT>>) ключ verification OK

# Верификация метаданных репозитория
gpg --verify repodata/repomd.xml.asc repodata/repomd.xml

# Ротация ключей в production
# 1. Импортируйте новый ключ ДО истечения срока действия старого
sudo rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-project-new
# 2. Обновите .repo файлы с новым gpgkey
sudo dnf config-manager --setopt=<repo_id>.gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-project-new --save
# 3. Удалите старый ключ
sudo rpm -e gpg-pubkey-<old-key-id>
```

### Сценарий 6: Валидация репозитория

Проверка целостности и доступности репозитория перед добавлением в production-окружение.

```bash
# 1. Проверка доступности по HTTP
curl -s -o /dev/null -w "%{http_code}" http://repo.internal.local/alma9/baseos/repodata/repomd.xml
# → Ожидается 200

# 2. Проверка наличия и подписи repomd.xml
curl -s http://repo.internal.local/alma9/baseos/repodata/repomd.xml | head
gpg --verify repodata/repomd.xml.asc repodata/repomd.xml

# 3. Проверка контрольных сумм пакетов (сравнение с upstream)
sudo dnf repoquery --disablerepo="*" --enablerepo="local-baseos" \
  --queryformat "%{name}-%{epoch}:%{version}-%{release}.%{arch} %{pkgid}\n" > /tmp/local-pkgs.txt

# 4. Проверка отсутствия "разорванных" зависимостей
sudo dnf repoclosure --repoid=local-baseos --repofrompath="local-baseos,http://repo.internal.local/alma9/baseos/"
# → Возвращает 0 при успехе; ненулевой код = есть неразрешенные зависимости

# 5. Проверка обновления через локальное зеркало
sudo dnf upgrade --disablerepo="*" --enablerepo="local-baseos,local-appstream" --assumeno
# → Должен показать план транзакции без ошибок сети
```

### Сценарий 7: Массовое обслуживание и окна обновления

Операции для проведения плановых работ на репозиториях.

```bash
# Отключение всех сторонних репозиториев перед обновлением системы
sudo dnf config-manager --set-disabled=epel,docker,nginx,grafana

# Проведение обновления только из базовых репозиториев
sudo dnf upgrade

# Включение репозиториев обратно
sudo dnf config-manager --set-enabled=epel,docker,nginx,grafana

# Проверка, что все репозитории снова активны
dnf repolist

# Экспорт текущего состояния репозиториев для отката
dnf repolist -v > /tmp/repo-state-before-$(date +%Y%m%d-%H%M).txt

# Восстановление состояния из резервной копии
while read repo; do
  sudo dnf config-manager --set-enabled="$repo"
done < <(grep -oP '^[\w-]+(?=\s+\w+\s+https)' /tmp/repo-state-before-20240101-1200.txt)
```

### Сценарий 8: Аудит и соответствие

Команды для проверки соответствия базовому уровню (baseline) и аудита состояния репозиториев.

```bash
# Список репозиториев с полными параметрами для аудита
dnf repolist -v > /tmp/repo-audit-$(date +%Y%m%d).txt
# → Включает: baseurl, mirrorlist, metalink, enabled/disabled, GPG статус, приоритет

# Проверка, что repo_gpgcheck включен для всех активных репозиториев
dnf repolist -v | grep -E "Repo-(baseos|appstream|epel)" | grep -v "repo_gpgcheck"
# → Если вывод пустой — все репозитории имеют repo_gpgcheck

# Поиск репозиториев с отключенной проверкой подписей
for repo in /etc/yum.repos.d/*.repo; do
  echo "=== $repo ==="
  grep -E "^gpgcheck=|^repo_gpgcheck=" "$repo" 2>/dev/null || echo "  [WARNING] GPG check not configured"
done

# Проверка использования прокси в репозиториях
grep -r "^proxy=" /etc/yum.repos.d/
# → Выводит репозитории, использующие прокси

# Аудит источников пакетов (какие пакеты установлены не из репозиториев)
dnf list extras
# → Пакеты, установленные из локальных RPM или сторонних источников

# Проверка обновлений безопасности с критичностью
dnf updateinfo list --security --severity=Critical
# → Требует подключение к базе CVE через appstream metadata

# Генерация SBOM (Software Bill of Materials) установленной системы
sudo dnf repoquery --installed --queryformat '%{name}-%{epoch}:%{version}-%{release}.%{arch}\n' > /tmp/sbom.txt
```

### Сценарий 9: Экстренное отключение проблемного репозитория

Быстрые действия при падении репозитория или некорректном обновлении метаданных.

```bash
# 1. Немедленное отключение проблемного репозитория
sudo dnf config-manager --set-disabled=problematic-repo

# 2. Очистка кэша проблемного репозитория
sudo dnf clean metadata --repo=problematic-repo

# 3. Повторная попытка операции
sudo dnf upgrade

# 4. Если проблема не решена — полная очистка и повторное включение
sudo dnf clean all
sudo dnf config-manager --set-enabled=problematic-repo
sudo dnf makecache

# 5. Быстрая проверка доступности зеркала
curl -s -o /dev/null -w "%{http_code}" http://mirror.example.com/repodata/repomd.xml
# → Если не 200 — проблема на стороне зеркала, а не DNF
```

### Сценарий 10: Очистка устаревших источников

Удаление репозиториев, которые больше не поддерживаются или используются.

```bash
# 1. Поиск неактивных .repo файлов
for repo in /etc/yum.repos.d/*.repo; do
  repo_id=$(grep -oP '^\[.+\]' "$repo" | tr -d '[]')
  if ! dnf repolist | grep -q "^$repo_id"; then
    echo "Неактивный: $repo ($repo_id)"
  fi
done

# 2. Проверка, какие пакеты были установлены из удаляемого репозитория
dnf repository-packages <repo_id> list installed

# 3. Отключение репозитория
sudo dnf config-manager --set-disabled=<repo_id>

# 4. Удаление .repo файла
sudo rm /etc/yum.repos.d/<file>.repo

# 5. Очистка кэша, связанного с удаленным репозиторием
sudo dnf clean metadata --repo=<repo_id>

# 6. Удаление устаревших GPG-ключей (опционально)
rpm -q gpg-pubkey --qf '%{name}-%{version}-%{release} --> %{summary}\n' | grep -i "<vendor>"
sudo rpm -e gpg-pubkey-<key-id>
```

---

## Дополнительная информация

### Диагностика типовых ошибок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Error: Failed to download metadata** | Проблемы с сетью, DNS или недоступность upstream. | Проверьте `baseurl` в `.repo` и доступность зеркала через `curl -I <url>`. Проверьте `dnf repolist -v` для деталей подключения. |
| **GPG key retrieval failed** | Блокировка порта 80/443 или битая ссылка. | Скачайте ключ вручную и используйте `rpm --import <file>`. Проверьте целостность ключа через `rpm -K <file>`. |
| **Repo ... has no mirrorlist** | Опечатка в конфиге или репозиторий удален. | Проверьте актуальность `mirrorlist` на сайте дистрибутива. Переключитесь на `baseurl` с фиксированным зеркалом. |
| **GPG: NO_PUBKEY** | Ключ репозитория отсутствует в RPMDB. | Убедитесь, что ключ импортирован: `rpm -q gpg-pubkey`. Добавьте ключ через `rpm --import`. |
| **404 Not Found** | Неправильный URL, дистрибутив или архитектура. | Проверьте `$basearch` и `$releasever`. Убедитесь, что дистрибутив существует на upstream. |
| **Hash Sum mismatch** | Индексы upstream обновились во время скачивания. | Выполните `sudo dnf clean metadata --repo=<repo_id> && sudo dnf makecache`. |
| **Metadata conflict** | Несовпадение версий метаданных в кэше. | `sudo dnf clean metadata --repo=<repo_id>` и повторная операция. |
| **Битый кэш** | Некорректное завершение `dnf makecache` или `dnf upgrade`. | Выполните `sudo dnf clean all && sudo dnf makecache`. |
| **dnf repoclosure показывает неудовлетворённые зависимости** | Частичное зеркало или неправильная конфигурация. | Используйте `--includepkgs` или зеркалируйте все required репозитории. |
| **GPG check FAILED** | Неверный или отсутствующий ключ, либо подделанный пакет. | `sudo rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-*`. Проверьте целостность пакета через `rpm -K <package.rpm>`. |
| **No space left on device** | Недостаточно места в `/var/cache/dnf` или `/var/lib/rpm`. | `df -h /var`, `sudo dnf clean all`. |
| **Transaction check error** | Конфликт файлов или зависимостей между пакетами. | `sudo dnf distro-sync`, проверка `dnf repoquery --conflicts <package>`. |

### Валидация конфигурации репозиториев

Перед применением изменений в production-среде выполняйте комплексную проверку:

```bash
# 1. Синтаксис .repo файлов
for f in /etc/yum.repos.d/*.repo; do
  echo "Проверка: $f"
  grep -E '^\[.+\]' "$f" || echo "  [ОШИБКА] Отсутствует секция"
  grep -E '^(baseurl|mirrorlist|metalink)=' "$f" || echo "  [ОШИБКА] Отсутствует источник"
  grep -E '^(gpgcheck|repo_gpgcheck)=' "$f" || echo "  [ПРЕДУПРЕЖДЕНИЕ] GPG не настроен"
done

# 2. Доступность всех активных репозиториев
dnf repolist -v | grep -E "Repo.*enabled" | while read line; do
  baseurl=$(echo "$line" | grep -oP 'Base URL: \K.*' || true)
  if [ -n "$baseurl" ]; then
    code=$(curl -s -o /dev/null -w "%{http_code}" "$baseurl/repodata/repomd.xml")
    echo "  $baseurl → HTTP $code"
  fi
done

# 3. Проверка подлинности ключей
rpm -q gpg-pubkey --qf '%{name}-%{version}\n' | sort > /tmp/current-keys.txt
diff /tmp/current-keys.txt /etc/ansible/roles/dnf/files/approved-gpg-keys.txt
# → Отличия указывают на несанкционированные или устаревшие ключи
```

### Рекомендации по безопасности

1.  **GPG-верификация:** Никогда не отключайте `gpgcheck` и `repo_gpgcheck` в production. Скопируйте GPG-ключи на сервер зеркала и указывайте путь к ним в `gpgkey` (через HTTP или локально). Подписывайте `repomd.xml` через `gpg --detach-sign --armor`.
2.  **Изоляция стороннего ПО:** При использовании репозиториев с широким составом пакетов (например, EPEL) используйте параметр `includepkgs` в `.repo`, чтобы разрешить установку только нужных вам программ.
3.  **Архитектуры:** Используйте флаг `--arch` (RPM) или архитектурные каталоги в URL, чтобы не выкачивать пакеты для неиспользуемых архитектур.
4.  **HTTPS:** Всегда предпочитайте `https://` для защиты от перехвата и инъекций (даже если используется проверка GPG).
5.  **Сетевая изоляция:** Размещайте внутренние зеркала в отдельном VLAN. Используйте mTLS (`sslclientcert` + `sslclientkey`) для критичных контуров.
6.  **Очистка кэша:** При удалении стороннего ПО не забывайте удалять соответствующие файлы из `/etc/yum.repos.d/` и устаревшие ключи через `rpm -e gpg-pubkey-<id>`.
7.  **Жёсткие ссылки:** При синхронизации нескольких репозиториев используйте общий пул и hardlinks для экономии дискового пространства.
8.  **Воспроизводимость:** Для критичных систем используйте снапшоты зеркал с фиксированной датой, чтобы гарантировать одинаковые версии пакетов.
9.  **Верификация после изменений:** После добавления/изменения репозитория всегда выполняйте `dnf repolist` и `dnf repoinfo <repo_id>` для проверки корректности конфигурации.

### Связанные документы

- **[Управление репозиториями (Index)](./index.md)** — архитектура и структура файлов.
- **[Создание собственного репозитория](./custom_repository.md)** — подготовка локальных RPM-хранилищ.
- **[Зеркалирование YUM/DNF](../yum_dnf_repository_mirror.md)** — создание локальных копий официальных репозиториев, reposync, systemd-автоматизация.
- **[Практические сценарии DNF](../dnf_commands/practical_scenarios.md)** — общие команды управления пакетами.
- **[Определения DNF](../dnf_commands/definitions.md)** — терминология модулей, потоков и профилей.
- **[Конфигурация DNF](../dnf_commands/basic_concepts.md)** — глобальные настройки в `dnf.conf`.
- **[Траблшутинг сети](../../../Networking/ServicesAndTools/Wireshark/tshark_usage.md)** — инструменты для отладки проблем с загрузкой.
