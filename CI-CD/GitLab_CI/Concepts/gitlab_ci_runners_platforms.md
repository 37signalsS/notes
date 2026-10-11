# Раннеры GitLab CI: Windows и macOS

**Актуально для:** GitLab 17.x–19.x, GitLab Runner 17.x–19.x

## Определения

*   **Windows Runner** — GitLab Runner, выполняющий задания на Windows-хостах. Использует `shell` executor с `pwsh` (PowerShell Core, рекомендуется) или `cmd`.
*   **macOS Runner** — GitLab Runner, выполняющий задания на macOS-хостах. Стандартный executor для iOS/macOS сборок; использует `shell` executor с доступом к Xcode, симуляторам и Keychain.
*   **PowerShell Core (`pwsh`)** — рекомендуемый shell для Windows Runner'ов. Кроссплатформенный, поддерживает современный синтаксис и `pwsh:lts` как stable-версию.
*   **Xcode** — IDE Apple для разработки под iOS/macOS. Требуется на macOS Runner'ах; включает `xcodebuild`, симуляторы и инструменты подписи.
*   **Fastlane** — инструмент автоматизации сборки и деплоя iOS/macOS приложений ( lanes, `pilot`, `match` ).
*   **launchd** — системный менеджер служб macOS (аналог `systemd` в Linux). Используется для регистрации GitLab Runner как автозапускаемого сервиса с `KeepAlive`.
*   **SIP (System Integrity Protection)** — механизм защиты macOS, ограничивающий запись в защищённые разделы диска. Влияет на установку инструментов CI.
*   **Ephemeral Keychain** — временная связка ключей, создаваемая внутри джобы CI для безопасного хранения сертификатов. Автоматически удаляется после завершения сборки.
*   **WSL2 backend** — режим Docker Desktop на Windows, позволяющий запускать Linux-контейнеры через виртуализацию WSL2. Доступен с GitLab Runner 18.0+.
*   **Windows Service** — механизм запуска GitLab Runner в фоне под системным аккаунтом `Local Service` или выделенным пользователем, обеспечивающий автозапуск после перезагрузки.

> **Примечание:** Полное сравнение executor'ов, Windows/macOS ограничения и конфигурация — в **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)**. Для production-конфигурации Windows — см. **[Windows Runner в Production](../Tutorials/windows_runner_production.md)**. Для provisioning macOS и SRE-подхода — см. **[Mobile CI/CD: Архитектура и инфраструктура](../../mobile-ci-cd/index.md)** и **[GitLab CI/CD для iOS и macOS](../../mobile-ci-cd/gitlab-ios-ci.md)**.

## Базовые концепции

### Архитектура shell executor на Windows и macOS

На Windows и macOS GitLab Runner работает через **shell executor**, который предоставляет прямой доступ к ОС хоста без контейнеризации. Это отличает эти платформы от Linux, где стандартом является `docker` или `kubernetes` executor.

**Механизм работы shell executor на Windows:**
1.  Runner Manager опрашивает GitLab API (`POST /api/v4/jobs/request`).
2.  При получении задачи Runner создаёт изолированную сессию PowerShell Core (`pwsh`) или `cmd`.
3.  В рамках сессии выполняются `pre_clone_script`, клонирование репозитория, `script` и `post_build_script`.
4.  Логи и артефакты передаются обратно в GitLab через API.
5.  Сессия завершается; временные файлы остаются в `builds`-директории по умолчанию (отсутствует автоматическая очистка контейнера).

**Механизм работы shell executor на macOS:**
1.  Аналогично Windows, Runner использует shell executor (по умолчанию `zsh` или `bash`).
2.  Сессия имеет доступ к Xcode, симуляторам, Keychain и инструментам Fastlane.
3.  Особенность: для доступа к сертификатам подписи используется **Keychain**, который может быть заблокирован без эфемерного разблокирования.
4.  Как и на Windows, workspace не очищается автоматически между задачами (в отличие от эфемерных контейнеров).

**Изоляция:** В отличие от `docker` или `kubernetes` executor'ов, `shell` executor не изолирует среду выполнения. Задачи разделяют файловую систему, переменные окружения и системные ресурсы хоста. Это требует:
*   Соблюдения идемпотентности в скриптах (не полагаться на состояние из предыдущей задачи).
*   Отдельных пользовательских аккаунтов для Runner'ов с минимальными правами (Least Privilege).
*   Использования `before_script` для подготовки "чистого" окружения (очистка DerivedData, NuGet cache и т.д.).

### Сравнение Runner'ов по платформам

| Параметр | Linux | Windows | macOS |
|:---|:---|:---|:---|
| **Executor** | `docker`, `kubernetes`, `shell` | `shell` (pwsh/cmd), `docker` (Docker Desktop/WSL2) | `shell` (zsh/bash) |
| **Изоляция** | Высокая (контейнеры/поды) | Отсутствует (shell), частичная (Docker Desktop) | Отсутствует (shell) |
| **Стандартный shell** | `bash` | `pwsh` (PowerShell Core) | `zsh` / `bash` |
| **Системный сервис** | `systemd` | Windows Service (`sc.exe`) | `launchd` |
| **Изоляция между задачами** | Полная (контейнер уничтожается) | Отсутствует (workspace сохраняется) | Отсутствует (workspace сохраняется) |
| **Доступ к железу** | Через Docker volumes | Прямой доступ к COM-портам, GPU | Прямой доступ к GPU, периферии |
| **iOS/macOS сборки** | Нет | Нет | Да (требуется Xcode) |
| **WSL2 backend** | N/A | Да (с GitLab Runner 18.0+) | N/A |

### Cross-platform матрица

GitLab CI поддерживает матричные сборки для кросс-платформенного тестирования, но важно учитывать ограничения: образы для Linux несовместимы с Windows/macOS без эмуляции.

```yaml
test:
  stage: test
  parallel:
    matrix:
      - OS: [linux, windows, macos]
        PKG: [pip, npm, yarn]
        # Примечание: для каждого OS должен быть свой Runner с соответствующим тегом
  script:
    - echo "Testing on $OS with $PKG"
  tags:
    - $OS  # Раннер должен иметь тег "linux", "windows" или "macos"
```

## Предварительные требования

### Windows Runner

#### Аппаратные ресурсы

| Компонент | Минимум | Рекомендация |
|:---|:---|:---|
| **RAM** | 8 ГБ | 16 ГБ+ для .NET Framework / Docker Desktop |
| **CPU** | 4 ядра | 8 ядер+ для параллельных задач |
| **Диск** | 100 ГБ SSD | 500 ГБ+ NVMe SSD для кэша и артефактов |
| **Сеть** | 1 Гбит/с | Стабильный доступ к GitLab API (443/tcp) |

#### Программное обеспечение

| Компонент | Минимум | Рекомендация | Проверка |
|:---|:---|:---|:---|
| **Windows** | Windows Server 2022 / Windows 11 22H2 | Windows Server 2025 / Windows 11 24H2 | `winver` |
| **Git** | 2.40+ | 2.47+ | `git --version` |
| **PowerShell Core** | 7.2+ | 7.4+ LTS | `pwsh --version` |
| **Docker Desktop** (опционально) | 24.0+ | 27.0+ с WSL2 backend | `docker --version` |
| **.NET SDK** (опционально) | 6.0+ | 8.0+ | `dotnet --version` |
| **GitLab Runner** | 17.0 | 19.3+ | `gitlab-runner --version` |

#### Предустановки и конфигурация ОС

1.  **PowerShell Execution Policy:** Разрешите выполнение скриптов:
    ```powershell
    Set-ExecutionPolicy RemoteSigned -Scope LocalMachine
    ```
2.  **Git for Windows:** Установите с включённым `Use Git from the Windows Command Prompt` (добавляет `git` в PATH).
3.  **WSL2 (опционально):** Для Linux-контейнеров через Docker Desktop:
    ```powershell
    wsl --install
    # Перезагрузка
    wsl --set-default-version 2
    ```
4.  **Сеть:** Убедитесь, что Runner может доставлять HTTPS-запросы к GitLab API (исходящий 443/tcp). Входящие соединения не требуются.

### macOS Runner

#### Аппаратные ресурсы

| Компонент | Минимум | Рекомендация |
|:---|:---|:---|
| **RAM** | 16 ГБ | 32 ГБ+ для параллельных сборок |
| **CPU** | 8 ядер (Apple Silicon M2+) | 12 ядер+ (M3/M4 Pro/Max) |
| **Диск** | 200 ГБ SSD | 500 ГБ+ NVMe (для DerivedData, кэша, симуляторов) |
| **Сеть** | 1 Гбит/с | Стабильный доступ к GitLab API (443/tcp) |

#### Программное обеспечение

| Компонент | Минимум | Рекомендация | Проверка |
|:---|:---|:---|:---|
| **macOS** | 14 Sonoma | 15 Sequoia | `sw_vers` |
| **Архитектура** | Apple Silicon (M1+) | Apple Silicon M2/M3/M4 | `uname -m` → `arm64` |
| **Xcode** | 15.x | 16.x+ с Command Line Tools | `xcodebuild -version` |
| **Xcode CLT** | Установлены | Обновлены до версии Xcode | `xcode-select --install` |
| **Homebrew** | Установлен | `/opt/homebrew` (Apple Silicon) | `brew --version` |
| **Ruby** | 3.1+ | 3.3+ (через `mise` или системный) | `ruby --version` |
| **Fastlane** | Установлен | `gem install fastlane` | `fastlane --version` |
| **GitLab Runner** | 17.0 | 19.3+ | `gitlab-runner --version` |

#### Предустановки и конфигурация ОС

1.  **Xcode License:** Примите лицензию Xcode (требует `sudo`):
    ```bash
    sudo xcodebuild -license accept
    ```
2.  **Command Line Tools:** Установите отдельно от Xcode, если нужно:
    ```bash
    xcode-select --install
    ```
3.  **Homebrew:** Установите для управления зависимостями:
    ```bash
    /bin/bash -c "$(curl -fsSL https://brew.sh/install)"
    ```
4.  **launchd сервис:** GitLab Runner должен быть зарегистрирован как системный сервис с автозапуском:
    ```bash
    brew services start gitlab-runner
    ```
5.  **Сеть:** Убедитесь, что Runner может доставлять HTTPS-запросы к GitLab API (исходящий 443/tcp).

### Общие требования к инфраструктуре

*   **NTP:** Синхронизация времени между GitLab Server и Runner'ами — критична для проверки JWT-подписи.
*   **Хранилище:** Достаточное место для артефактов, кэша и логов; рекомендуется отдельный диск для `/var/lib/gitlab-runner` (Linux/macOS) или `C:\GitLab-Runner` (Windows).
*   **RBAC:** Роль `Maintainer`/`Owner` для регистрации Runner'ов; `Developer` для запуска задач.
*   **TLS:** GitLab Server должен работать по HTTPS с валидным сертификатом (не self-signed в production).
*   **Виртуализация** (для Fleet Management): KVM/libvirt, VMware vSphere или Proxmox на гипервизорах для автоскейлинга через Fleeting.

## Практические сценарии

### Сценарий 1: Регистрация Windows Runner

#### Шаг 1: Установка GitLab Runner

```powershell
# Скачайте установщик с https://gitlab.com/runner/archives
# Или через Chocolatey:
choco install gitlab-runner

# Проверка
gitlab-runner --version
# → Version: 19.3.1
```

#### Шаг 2: Регистрация Runner'а

```bash
gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.example.com/" \
  --token "glrt-YOUR_TOKEN" \
  --executor "shell" \
  --shell "pwsh" \
  --description "windows-runner-pwsh" \
  --tag-list "windows,pwsh" \
  --run-untagged="false" \
  --locked="true"
```

**Валидация:**
```powershell
# Проверка статуса сервиса
Get-Service gitlab-runner
# → Status: Running

# Проверка зарегистрированных раннеров
gitlab-runner list
# → Вывод: windows-runner-pwsh, executor: shell, shell: pwsh, url: https://gitlab.example.com/

# Проверка связи с GitLab
gitlab-runner verify
# → Verifying runner... is alive
```

#### Шаг 3: Конфигурация config.toml

```toml
# C:\GitLab-Runner\config.toml
concurrent = 4
check_interval = 3

[[runners]]
  name = "windows-runner-pwsh"
  url = "https://gitlab.example.com/"
  token = "glrt-XXX"
  executor = "shell"
  shell = "pwsh"
  [runners.cache]
    Type = "s3"
    Path = "cache"
    [runners.cache.s3]
      ServerAddress = "s3.internal.company.com"
      BucketName = "gitlab-runner-cache"
      BucketLocation = "us-east-1"
      Insecure = false
  [runners.custom_build_dir]
    enabled = true
```

### Сценарий 2: Базовый пайплайн для Windows

```yaml
stages:
  - build
  - test

variables:
  NUGET_PACKAGES: $CI_PROJECT_DIR/.nuget/packages

build_windows:
  stage: build
  tags:
    - windows
    - pwsh
  script:
    - Write-Host "Building on Windows..."
    - dotnet build --configuration Release --nologo
  artifacts:
    paths:
      - bin/Release/net8.0/*.exe
    expire_in: 1 week
  cache:
    key: "${CI_COMMIT_REF_SLUG}"
    paths:
      - .nuget/packages/

test_windows:
  stage: test
  tags:
    - windows
    - pwsh
  script:
    - Write-Host "Testing on Windows..."
    - dotnet test --configuration Release --no-build --logger trx --results-directory TestResults
  artifacts:
    reports:
      junit: TestResults/*.trx
    expire_in: 30 days
```

**Валидация:**
```yaml
# Проверка Runner'а в UI: CI/CD > Runners > windows,pwsh → online
# Проверка логов: в задании видно вывод Write-Host
# Проверка артефактов: скачивание .exe из UI pipeline
```

### Сценарий 3: Пайплайн для .NET Framework (Windows-specific)

```yaml
stages:
  - build
  - test
  - deploy

build_dotnet_framework:
  stage: build
  tags:
    - windows
    - pwsh
  image: mcr.microsoft.com/dotnet/framework/sdk:4.8
  script:
    - msbuild MyApp.csproj /p:Configuration=Release /nologo
  artifacts:
    paths:
      - bin/Release/*.exe
    expire_in: 1 week

test_dotnet_framework:
  stage: test
  tags:
    - windows
    - pwsh
  image: mcr.microsoft.com/dotnet/framework/sdk:4.8
  script:
    - vstest.console.exe bin/Release/MyApp.Tests.dll /Logger:trx
  artifacts:
    reports:
      junit: TestResults/*.trx
```

### Сценарий 4: Регистрация macOS Runner

#### Шаг 1: Установка зависимостей

```bash
# Homebrew
/bin/bash -c "$(curl -fsSL https://brew.sh/install)"

# GitLab Runner
brew install gitlab-runner

# Xcode Command Line Tools
xcode-select --install

# Fastlane
gem install fastlane

# Ruby (через mise/asdf или системный)
mise use ruby@3.3
```

#### Шаг 2: Регистрация Runner'а

```bash
gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.example.com/" \
  --token "glrt-YOUR_TOKEN" \
  --executor "shell" \
  --shell "zsh" \
  --description "macos-runner-$(hostname)" \
  --tag-list "macos,xcode" \
  --run-untagged="false" \
  --locked="true"
```

**Валидация:**
```bash
# Проверка статуса сервиса
brew services list | grep gitlab-runner
# → gitlab-runner started user/$(whoami)

# Проверка зарегистрированных раннеров
gitlab-runner list
# → Вывод: macos-runner-xxx, executor: shell, shell: zsh

# Проверка связи с GitLab
gitlab-runner verify
# → Verifying runner... is alive
```

#### Шаг 3: Конфигурация config.toml

```toml
# /Users/gitlab-runner/.gitlab-runner/config.toml
concurrent = 2
check_interval = 3

[[runners]]
  name = "macos-runner-$(hostname)"
  url = "https://gitlab.example.com/"
  token = "glrt-XXX"
  executor = "shell"
  shell = "zsh"
  environment = ["LC_ALL=en_US.UTF-8", "FASTLANE_DISABLE_COLORS=1"]
  limit = 2
  [runners.cache]
    Type = "s3"
    Path = "cache"
    [runners.cache.s3]
      ServerAddress = "s3.internal.company.com"
      BucketName = "gitlab-runner-cache"
      BucketLocation = "us-east-1"
```

### Сценарий 5: Пайплайн для iOS сборки

```yaml
stages:
  - build
  - test
  - deploy

variables:
  FASTLANE_DISABLE_COLORS: "1"
  LC_ALL: "en_US.UTF-8"

build_ios:
  stage: build
  tags:
    - macos
    - xcode
  script:
    - xcodebuild -workspace MyApp.xcworkspace \
      -scheme MyApp \
      -configuration Release \
      -destination 'platform=iOS Simulator,name=iPhone 15' \
      clean build \
      -derivedDataPath build/DerivedData
  artifacts:
    paths:
      - build/Release-iphoneos/*.ipa
      - build/DerivedData/Logs/
    expire_in: 1 week

test_ios:
  stage: test
  tags:
    - macos
    - xcode
  script:
    - xcodebuild test \
      -workspace MyApp.xcworkspace \
      -scheme MyApp \
      -destination 'platform=iOS Simulator,name=iPhone 15' \
      -resultBundlePath TestResults
  artifacts:
    reports:
      junit: TestResults/*.xcresult
    expire_in: 30 days

deploy_testflight:
  stage: deploy
  tags:
    - macos
    - xcode
  script:
    - fastlane pilot upload \
      --ipa "build/Release-iphoneos/MyApp.ipa" \
      --api_token "$APP_STORE_CONNECT_API_TOKEN"
  environment:
    name: testflight
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  when: manual
```

### Сценарий 6: Кросс-платформенная матрица (платформо-специфичные задачи)

Для кросс-платформенного тестирования используйте отдельные раннеры для каждой ОС и явные теги:

```yaml
stages:
  - build
  - test

build_linux:
  stage: build
  tags:
    - linux
  parallel:
    matrix:
      - IMAGE: [python:3.12, python:3.11]
  script:
    - python --version
    - pip install -r requirements.txt
    - python setup.py build
  artifacts:
    paths:
      - dist/

build_windows:
  stage: build
  tags:
    - windows
    - pwsh
  script:
    - python --version
    - pip install -r requirements.txt
    - python setup.py build
  artifacts:
    paths:
      - dist/

build_macos:
  stage: build
  tags:
    - macos
  script:
    - python3 --version
    - pip3 install -r requirements.txt
    - python3 setup.py build
  artifacts:
    paths:
      - dist/
```

> **Важно:** Задачи для разных ОС не могут использовать один и тот же Docker-образ, так как Linux-образы несовместимы с Windows/macOS shell executor'ами.

## Лучшие практики

### Безопасность

1.  **Изоляция Runner'ов**: Используйте отдельные Runner'ы для Windows/macOS, не смешивайте с Linux.
2.  **Least Privilege**: Создайте отдельного пользователя для Runner'а с минимальными правами (не `Administrator` на Windows, не `root` на macOS).
3.  **Protected Runner'ы**: Для production-деплоев используйте protected Runner'ы (`protected = true` в настройках).
4.  **Защищённые переменные**: Не храните секреты в скриптах; используйте GitLab Variables с маскированием.
5.  **Windows Service**: Запускайте Runner как Windows Service (не из под пользовательской сессии), чтобы обеспечить автозапуск.
6.  **macOS SIP**: На dedicated-раннерах может потребоваться отключение SIP для установки инструментов; на shared-пулах — не рекомендуется.
7.  **Сетевая изоляция**: Runner'ы должны находиться в отдельном сегменте сети с доступом только к GitLab API и внутреннему registry.

### Организация

1.  **Теги Runner'ов**: Используйте осмысленные теги (`windows,pwsh`, `macos,xcode`, `windows,dotnet`). Теги используются для маршрутизации задач (AND-логика: задача запустится только на раннере со всеми указанными тегами).
2.  **Образы**: Используйте официальные образы (MCR for Windows, Xcode images for macOS). Для Windows-задач, требующих .NET Framework, используйте `mcr.microsoft.com/dotnet/framework/sdk:4.8`.
3.  **Кэширование**: Настройте кэш для зависимостей (pip, npm, NuGet, CocoaPods, DerivedData). Для distributed-кэша используйте S3-совместимое хранилище.
4.  **Артефакты**: Устанавливайте `expire_in` для автоматической очистки старых артефактов.
5.  **Скрипты**: Пишите идемпотентные скрипты, так как workspace между задачами не очищается автоматически.

### Производительность

1.  **Параллелизм**: Ограничьте `concurrent` на macOS Runner'ах (ресурсы ограничены). Настройте `limit` на уровне раннера.
2.  **Warm-up**: Для macOS используйте snapshot'ы VM (Tart/Orka) для ускорения запуска новых раннеров.
3.  **Incremental builds**: Используйте incremental builds (Xcode derived data, NuGet packages) для сокращения времени сборки.
4.  **Интервал опроса**: Устанавливайте `check_interval = 1` для production-раннеров для быстрого получения задач.
5.  **Очистка DerivedData**: В `before_script` добавляйте очистку кэша Xcode:
    ```bash
    rm -rf ~/Library/Developer/Xcode/DerivedData/*
    ```

### Sysadmin: эксплуатация хостов

#### Windows

1.  **Windows Service**: Используйте Windows Service для запуска Runner'а с автоматическим перезапуском:
    ```powershell
    gitlab-runner install
    gitlab-runner start
    Set-Service -Name gitlab-runner -StartupType Automatic
    ```
2.  **Мониторинг**: Мониторьте Runner через Windows Event Log и Prometheus-метрики (`metrics_server` в config.toml).
3.  **Обновление**: Используйте rolling update: остановите приём новых задач, дождитесь завершения текущих, обновите бинарник, проверьте `gitlab-runner verify`, запустите.
4.  **SSD**: Используйте SSD для рабочей директории Runner'а (`C:\GitLab-Runner\builds`).

#### macOS

1.  **launchd**: Используйте `brew services start gitlab-runner` для регистрации автозапускаемого сервиса с `KeepAlive`.
2.  **Управление дисками**: DerivedData и кэши могут занимать десятки гигабайт. Настройте log rotation и регулярную очистку через `launchd` или `cron`.
3.  **Мониторинг**: Установите `prometheus_node_exporter` или `datadog-agent` на каждый раннер для сбора метрик CPU, RAM, disk I/O, температуры.
4.  **Эфемерность**: Для reproducible-окружения используйте подход Infrastructure as Code (Packer, Ansible) или виртуализацию (Tart/Orka).

## Устранение неполадок (Troubleshooting)

### Типичные ошибки на Windows

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **`error during connect: Post http://%2F.%2Fpipe%2Fdocker_engine`** | Docker Desktop не запущен или Docker-демон недоступен | Проверьте `Get-Service com.docker.service`. Убедитесь, что WSL2 backend включён. |
| **`exec format error`** | Несоответствие архитектуры образа (arm64 vs amd64) | Используйте multi-arch образы или QEMU. Проверьте `docker info` → `Architecture`. |
| **`Runner: OOMKilled`** | Недостаточно RAM на хосте | Увеличьте `limit` в `config.toml` или добавьте swap. Проверьте: `docker inspect <container>`. |
| **`Runner не берет задачи`** | Runner не авторизован, теги не совпадают, или Runner `paused`/`locked` | Проверьте статус: `gitlab-runner list`. Убедитесь, что теги задачи совпадают с тегами Runner'а. Проверьте `protected` статус. |
| **`Cleartext secrets` в логах** | Секреты передаются через переменные окружения в скриптах | Используйте GitLab Variables с `protected` и `masked` флагами. |
| **Обратные разделители путей** | PowerShell скрипты используют `\` вместо `/` | Используйте `Join-Path` или `Resolve-Path` для кроссплатформенных путей. |
| **Case-insensitive переменные** | В PowerShell `$env:VAR` и `$env:var` — одно и то же | Избегайте переменных, отличающихся только регистром. |

### Типичные ошибки на macOS

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **`xcodebuild: error: Unable to find utility "xcodebuild"`** | Xcode или CLT не установлены | Установите Xcode из App Store, затем `sudo xcodebuild -license accept`. |
| **`Code signing is required`** | Отсутствуют сертификаты или Keychain заблокирован | Используйте Ephemeral Keychain или Fastlane Match. Проверьте, что сервис `gitlab-runner` имеет доступ к Keychain. |
| **`No space left on device`** | Заполнен диск DerivedData или кэша | Очистите `~/Library/Developer/Xcode/DerivedData` и `/var/folders`. |
| **`Simulator failed to boot`** | Недостаточно ресурсов или симулятор повреждён | Увеличьте RAM для Runner'а. Сбросьте симулятор: `xcrun simctl shutdown all && xcrun simctl erase all`. |
| **`fastlane pilot upload failed`** | Неверный `API_TOKEN` или истёк сессия App Store Connect | Проверьте `APP_STORE_CONNECT_API_TOKEN`. Убедитесь, что токен имеет права `App Manager`. |
| **`SIP блокирует запись`** | Попытка записи в защищённый раздел диска | Используйте `/usr/local` (Intel) или `/opt/homebrew` (Apple Silicon). На dedicated-раннерах можно отключить SIP через Recovery Mode (не рекомендуется для shared-пулов). |
| **`zsh: command not found: brew`** | Homebrew не установлен или не в PATH | Установите Homebrew: `/bin/bash -c "$(curl -fsSL https://brew.sh/install)"`. |

### Диагностика

1.  **Логи Runner'а (Windows):**
    ```powershell
    # Windows Event Log
    Get-EventLog -LogName Application -Source gitlab-runner -Newest 20

    # Журнал Runner'а
    Get-Content C:\GitLab-Runner\gitlab-runner.log -Tail 50
    ```
2.  **Логи Runner'а (macOS):**
    ```bash
    # systemd-аналог в macOS
    log show --predicate 'subsystem == "com.gitlab.runner"' --last 50

    # Или через brew services
    brew services log gitlab-runner
    ```
3.  **Debug mode:** Запуск раннера с флагом `--debug` для подробных логов.
4.  **Verify:** Команда `gitlab-runner verify` для проверки связи всех зарегистрированных раннеров с сервером.
5.  **Сеть:** `curl -s https://gitlab.internal/api/v4/version` — проверка доступности GitLab API с хоста раннера.
6.  **Ресурсы (Windows):**
    ```powershell
    Get-Process | Sort-Object CPU -Descending | Select-Object -First 10
    Get-Counter '\Memory\Available MBytes'
    ```
7.  **Ресурсы (macOS):**
    ```bash
    top -l 1 -n 10
    vm_stat
    df -h /
    ```

## Особенности и ограничения (Edge Cases)

### Windows Runner

*   **Изоляция:** Shell executor не изолирует среду между задачами. Для изоляции используйте Docker Desktop с WSL2 backend (не совместимо с Docker-in-Docker на Windows-контейнерах).
*   **WSL2 backend:** Доступен с GitLab Runner 18.0+. Позволяет запускать Linux-контейнеры через виртуализацию WSL2, но не поддерживает Windows-контейнеры.
*   **Переменные среды:** Case-insensitive (`%VAR%` и `%var%` — одно и то же в `cmd`; в `pwsh` — `$env:VAR` и `$env:var` эквивалентны).
*   **Разделители путей:** Обратный слэш `\` в PowerShell; для кроссплатформенных скриптов используйте `Join-Path`.
*   **Git for Windows:** Требует наличия в PATH; клонирование через HTTPS требует настройки `git config --global credential.helper manager-core`.
*   **.NET Framework vs .NET:** Для .NET Framework 4.x используйте Docker-образ `mcr.microsoft.com/dotnet/framework/sdk:4.8`. Для .NET 6+ используйте `mcr.microsoft.com/dotnet/sdk:8.0` (Linux-образ через WSL2) или `mcr.microsoft.com/dotnet/sdk:8.0-windowsservercore-ltsc2022` (Windows-контейнер).
*   **Docker Desktop:** При использовании Docker Desktop на Windows убедитесь, что WSL2 backend включён, а Docker Engine запущен до начала выполнения задачи.

### macOS Runner

*   **Изоляция:** Shell executor не изолирует среду между задачами. Для изоляции используйте виртуализацию (Tart/Orka) или эфемерные VM через Fleeting.
*   **Keychain:** Без эфемерного Keychain сертификаты подписи могут быть недоступны между задачами или требовать интерактивного ввода пароля.
*   **Xcode License:** При обновлении Xcode требуется повторное принятие лицензии (`sudo xcodebuild -license accept`).
*   **SIP (System Integrity Protection):** Ограничивает запись в `/System`, `/usr` (кроме `/usr/local`), `/bin`, `/sbin`. Для установки инструментов используйте `/opt/homebrew` (Apple Silicon) или `/usr/local` (Intel).
*   **Apple Silicon:** Начиная с 2024–2025 годов, Intel-машины не поддерживают новые версии Xcode (16+). Стандартом для новых развёртываний является Apple Silicon (M2/M3/M4).
*   **Симуляторы:** Требуют графического доступа; не работают в headless-среде без виртуализации. Для CI используйте headless-режим или реальные устройства.
*   **SRE-ограничения:** macOS не имеет `systemd`; вместо него — `launchd`. Мониторинг через `prometheus_node_exporter`. Очистка DerivedData через cron/`launchd`.

### Общие ограничения

*   **Workspace persistence:** Файлы из предыдущих задач сохраняются в директории `builds`. Для идемпотентности добавляйте очистку в `before_script`.
*   **Секреты в логах:** PowerShell и `zsh` могут вывод-sensitive данные в логи при отладке. Используйте `Write-Host` с маскированием или `Write-Output` для обычных данных.
*   **Сеть:** Runner опрашивает GitLab по Pull-модели. При высоких задержках (>10 секунд) увеличьте `check_interval` или используйте regional Runner'ы.
*   **TLS:** GitLab не отправляет задачи на HTTP (кроме `localhost` в development-режиме). Убедитесь, что GitLab Server работает по HTTPS.

## Дополнительная информация

*   **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)** — подробное руководство по типам executor'ов.
*   **[Управление парком раннеров](../Advanced/runner_fleet_management.md)** — масштабирование и мониторинг.
*   **[Регистрация GitLab Runner](../Tutorials/runner_registration.md)** — практическое руководство.
*   **[Windows Runner в Production](../Tutorials/windows_runner_production.md)** — production-grade конфигурация для Windows.
*   **[GitLab CI/CD для iOS и macOS](../../mobile-ci-cd/gitlab-ios-ci.md)** — provisioning, Keychain, Fastlane.
*   **[Mobile CI/CD: Архитектура и инфраструктура](../../mobile-ci-cd/index.md)** — SRE/Sysadmin подход к мобильным раннерам.
*   **[GitLab Runner Docker Compose](../Tutorials/gitlab_runner_docker_compose.md)** — быстрый старт.
*   **[GitLab Docs: Windows Runners](https://docs.gitlab.com/runner/executors/shell/windows/)** — официальная документация.
*   **[GitLab Docs: macOS Runners](https://docs.gitlab.com/runner/executors/shell/macos/)** — официальная документация.

> **Критичные изменения последних версий:**
>
> *   **19.0**: Улучшена поддержка PowerShell Core (`pwsh`) как стандартного shell для Windows.
> *   **18.0**: Поддержка WSL2 backend для Docker Desktop на Windows; добавлен `docker-windows` executor.
> *   **17.0**: Улучшена совместимость с Xcode 15 и macOS 14; переход на `glrt-` токены по умолчанию.
