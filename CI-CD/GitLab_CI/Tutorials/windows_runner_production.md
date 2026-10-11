# Windows Runner в Production среде GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x, Windows Server 2022, Windows 11

> **Примечание:** Полная теория Windows Runner'ов, сравнение executor'ов и Fleet Management описаны в **[Управление парком Runner'ов (Fleet Management)](../Advanced/runner_fleet_management.md)** и **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)**. Это руководство фокусируется на production-grade конфигурации Windows Runner'ов для .NET, PowerShell и Windows-специфичных задач.

## Определения

**Windows Runner** — GitLab Runner, выполняющий задания на Windows-хостах через `shell` executor (`pwsh`/`cmd`) или `docker-windows` executor. В отличие от Linux-аналогов, Windows Runner'ы не поддерживают `docker-autoscaler` и имеют ограниченную изоляцию между задачами.

**PowerShell Core (`pwsh`)** — рекомендуемый shell для Windows Runner'ов. Кроссплатформенная реализация PowerShell с поддержкой современных синтаксиса и модулей. На Windows предпочтительнее устаревшего Windows PowerShell (`powershell.exe`).

**Windows Service (GitLab Runner)** — механизм запуска `gitlab-runner` как фонового системного сервиса под `Local Service` или выделенным пользователем, обеспечивающий автозапуск после перезагрузки и автоматический перезапуск при сбоях.

**Docker Engine (Windows Server)** — серверная редакция Docker для Windows Server 2022, работающая через `docker-windows` executor. Поддерживает только Windows-контейнеры на базе образов `mcr.microsoft.com/windows/servercore:ltsc2022`.

**Docker Desktop (Windows)** — редакция Docker для рабочих станций Windows, поддерживающая Windows-контейнеры и (через WSL2 backend) Linux-контейнеры. Для production CI/CD предпочтительнее Docker Engine на Windows Server без GUI.

**Windows containers** — контейнеры на базе образов `mcr.microsoft.com`. Совместимы только с Windows-хостами и требуют совпадения версии ядра хоста и образа.

**WSL2 backend** — режим Docker Desktop, позволяющий запускать Linux-контейнеры на Windows через виртуализацию WSL2. Доступен с GitLab Runner 18.0+.

**Active Directory (AD)** — служба каталогов Windows. Интеграция CI/CD с AD позволяет управлять правами развёртывания через групповые политики и Kerberos-аутентификацию.

**WinRM (Windows Remote Management)** — протокол удалённого управления Windows. Используется для PowerShell remoting при развёртывании на удалённых хостах из CI/CD пайплайнов.

**Chocolatey** — менеджер пакетов для Windows, аналог `apt`/`yum`. Используется для автоматизации установки зависимостей на Windows Runner'ах.

## Основные концепции

### Архитектура Windows Runner в production

Production Windows Runner строится на трехуровневой модели, аналогичной Linux-флоту, но с особенностями платформы:

1.  **Уровень управления (Control Plane):** GitLab Server, распределяющий задачи.
2.  **Уровень координации (Orchestration Layer):** Для Windows отсутствует автоскейлинг через Fleeting/Taskscaler. Масштабирование только статическое — администратор добавляет узлы вручную.
3.  **Уровень исполнения (Execution Layer):** Windows Server 2022 хосты с `shell` или `docker-windows` executor.

### Модели изоляции

| Модель | Изоляция | Масштабирование | Использование |
|:---|:---|:---|:---|
| **shell (pwsh)** | Отсутствует | Нет | .NET сборки, PowerShell-скрипты, Windows-specific тесты |
| **docker-windows** | Частичная (Windows-контейнеры) | Вертикальное (на хосте) | Изоляция зависимостей, повторяемые окружения |
| **docker (WSL2)** | Высокая (Linux-контейнеры) | Вертикальное | Сборки, совместимые с Linux-образами (через WSL2) |

### Особенности Windows Runner

- **Отсутствие изоляции по умолчанию:** `shell` executor разделяет файловую систему и переменные среды между задачами. Требует идемпотентности скриптов и очистки `before_script`.
- **Workspace persistence:** В отличие от Linux-контейнеров, рабочая директория `C:\builds` не очищается автоматически между задачами.
- **Нет docker-autoscaler:** Fleeting не поддерживает Windows-инстансы для динамического масштабирования.
- **Ограниченная поддержка services:** Docker Compose-style sidecar-контейнеры не работают в Windows-контейнерах через `docker-windows` executor.
- **Версия ядра:** Windows-контейнеры должны соответствовать версии ядра хоста. Несовместимость приводит к ошибке `The container does not match the host operating system`.

## Предварительные требования

### Аппаратные ресурсы

| Компонент | Минимум | Рекомендация (production) |
|:---|:---|:---|
| **RAM** | 8 ГБ | 16 ГБ+ для параллельных .NET сборок |
| **CPU** | 4 ядра | 8 ядер+ (Windows container overhead) |
| **Диск** | 100 ГБ SSD | 500 ГБ+ NVMe SSD для кэша и артефактов |
| **Сеть** | 1 Гбит/с | Стабильный доступ к GitLab API (443/tcp) |

### Программное обеспечение

| Компонент | Минимум | Рекомендация | Проверка |
|:---|:---|:---|:---|
| **Windows** | Windows Server 2022 | Windows Server 2025 | `winver` |
| **GitLab Runner** | 17.0 | 19.3+ | `gitlab-runner --version` |
| **PowerShell Core** | 7.2+ | 7.4+ LTS | `pwsh --version` |
| **Git for Windows** | 2.40+ | 2.47+ | `git --version` |
| **Docker Engine** (опционально) | 24.0+ | 27.0+ | `docker --version` |
| **.NET SDK** (опционально) | 6.0+ | 8.0+ | `dotnet --version` |

### Безопасность и сеть

- **NTP:** Синхронизация времени между GitLab Server и Runner'ами — критична для проверки JWT-подписи.
- **TLS:** GitLab Server должен работать по HTTPS с валидным сертификатом (не self-signed в production).
- **RBAC:** Роль `Maintainer`/`Owner` для регистрации Runner'ов.
- **Execution Policy:** `Set-ExecutionPolicy RemoteSigned -Scope LocalMachine` для PowerShell.
- **WinRM:** Для удалённого развёртывания — включение и настройка PowerShell remoting (`Enable-PSRemoting -Force`).
- **Firewall:** Открыт исходящий 443/tcp; входящие соединения не требуются (Pull-модель).

## Практические сценарии

### Сценарий 1: Базовый Windows Runner (shell executor, pwsh)

Для .NET сборок и PowerShell-задач, требующих прямого доступа к ОС хоста.

#### 1. Установка GitLab Runner

```powershell
# Через Chocolatey (рекомендуется)
choco install gitlab-runner -y

# Или скачайте .exe с https://gitlab.com/runner/archives
# Проверка
gitlab-runner --version
# → Version: 19.3.1
```

#### 2. Регистрация Runner'а

```powershell
gitlab-runner register `
  --non-interactive `
  --url "https://gitlab.example.com/" `
  --token "glrt-YOUR_TOKEN_HERE" `
  --executor "shell" `
  --shell "pwsh" `
  --description "windows-powershell-runner" `
  --tag-list "windows,pwsh" `
  --run-untagged="false" `
  --locked="false"
```

#### 3. Установка как Windows Service

```powershell
gitlab-runner install
gitlab-runner start

# Проверка
Get-Service gitlab-runner
# → Status: Running
```

**Валидация:**
```powershell
# Статус службы
gitlab-runner status
# → gitlab-runner: Service is running

# Список раннеров
gitlab-runner list
# → Runner: abc123... https://gitlab.example.com/ ... executor=shell
```

#### 4. Пример .gitlab-ci.yml

```yaml
stages:
  - build
  - test
  - deploy

variables:
  NUGET_PACKAGES: $CI_PROJECT_DIR/.nuget/packages

before_script:
  - nuget restore

build:
  stage: build
  image: mcr.microsoft.com/dotnet/sdk:8.0
  tags:
    - windows
    - pwsh
  script:
    - dotnet build --configuration Release
    - dotnet publish --configuration Release --output ./publish
  artifacts:
    paths:
      - ./publish/**
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

test:
  stage: test
  image: mcr.microsoft.com/dotnet/sdk:8.0
  tags:
    - windows
    - pwsh
  script:
    - dotnet test --configuration Release --no-build --logger trx
  artifacts:
    paths:
      - TestResults/*.trx
    reports:
      junit: TestResults/*.trx
    expire_in: 30 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

> **Примечание:** При использовании `shell` executor образ `image:` в `.gitlab-ci.yml` должен совмещаться с ОС хоста. На Windows-раннере с `pwsh` shell можно использовать Windows-образы (`mcr.microsoft.com/dotnet/...`). Если зависимости установлены на хосте, `image` можно опустить.

### Сценарий 2: Docker Windows Executor

Для изоляции окружений через Windows-контейнеры.

#### 1. Регистрация Runner'а

```powershell
gitlab-runner register `
  --non-interactive `
  --url "https://gitlab.example.com/" `
  --token "glrt-YOUR_TOKEN_HERE" `
  --executor "docker-windows" `
  --docker-image "mcr.microsoft.com/windows/servercore:ltsc2022" `
  --description "windows-docker-runner" `
  --tag-list "windows,docker"
```

#### 2. config.toml

```toml
[[runners]]
  name = "windows-docker-runner"
  url = "https://gitlab.example.com/"
  token = "glrt-..."
  executor = "docker-windows"
  limit = 8
  [runners.docker]
    image = "mcr.microsoft.com/windows/servercore:ltsc2022"
    privileged = false
    volumes = ["C:\cache:C:\cache"]
    cleanup = "always"
  [runners.cache]
    Type = "s3"
    Shared = true
    [runners.cache.s3]
      ServerAddress = "minio.internal:9000"
      BucketName = "gitlab-runner-cache"
      BucketLocation = "us-east-1"
      Insecure = false
```

#### 3. Установка как Service

```powershell
gitlab-runner install
gitlab-runner start
```

**Валидация:**
```powershell
# Статус службы
gitlab-runner status
# → gitlab-runner: Service is running

# Проверка Windows-контейнеров
docker info
# → OSType: windows
```

### Сценарий 3: Сборка образов на Windows (Docker Desktop / Kaniko)

Для задач, требующих сборки Docker-образов на Windows-хостах.

**Вариант A: Docker Desktop с WSL2 backend (Linux-контейнеры)**

```powershell
# На хосте: Docker Desktop с включённым WSL2 backend
# Регистрация runner'а с executor "docker" (Linux-контейнеры через WSL2)
gitlab-runner register `
  --non-interactive `
  --url "https://gitlab.example.com/" `
  --token "glrt-YOUR_TOKEN_HERE" `
  --executor "docker" `
  --docker-image "docker:27.0" `
  --description "windows-docker-desktop-runner" `
  --tag-list "windows,docker,wsl2"
```

```yaml
build-image:
  stage: build
  image: docker:27.0
  services:
    - docker:27.0-dind
  variables:
    DOCKER_HOST: tcp://docker:2375
    DOCKER_TLS_CERTDIR: ""
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

> **Безопасность:** `privileged = true` требуется для DinD, но даёт полный доступ к ядру хоста. Для production используйте **Kaniko** (Вариант B).

**Вариант B: Kaniko (без privileged mode)**

```yaml
build-image:
  stage: build
  image: gcr.io/kaniko-project/executor:v1.19.2
  tags:
    - windows
    - docker
  script:
    - kaniko --context $CI_PROJECT_DIR --dockerfile $CI_PROJECT_DIR/Dockerfile --destination $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Сценарий 4: PowerShell автоматизация для Windows

Автоматизация подготовки окружения через Chocolatey и PowerShell.

```yaml
stages:
  - configure
  - build
  - deploy

variables:
  CHOCO_INSTALL: "C:\ProgramData\chocolatey"

configure-windows:
  stage: configure
  tags:
    - windows
    - pwsh
  script:
    - |
      # Установка Chocolatey
      Set-ExecutionPolicy Bypass -Scope Process -Force
      [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
      Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    - choco install git -y
    - choco install dotnet-8.0-sdk -y
    - choco install nuget.commandline -y
    - refreshenv
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      when: manual

build-dotnet:
  stage: build
  image: mcr.microsoft.com/dotnet/sdk:8.0
  tags:
    - windows
    - pwsh
  script:
    - dotnet restore --packages $env:NUGET_PACKAGES
    - dotnet build --configuration Release
    - dotnet publish --configuration Release --output ./publish
  artifacts:
    paths:
      - ./publish/**
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy-windows:
  stage: deploy
  image: mcr.microsoft.com/dotnet/sdk:8.0
  tags:
    - windows
    - pwsh
  script:
    - |
      # Развертывание через PowerShell remoting
      $password = ConvertTo-SecureString "$DEPLOY_PASSWORD" -AsPlainText -Force
      $credential = New-Object System.Management.Automation.PSCredential("$DEPLOY_USER", $password)
      Invoke-Command -ComputerName "production-server" -Credential $credential -ScriptBlock {
        Stop-Service -Name "MyApp" -Force
        Copy-Item -Path "C:\deploy\publish" -Destination "C:\MyApp" -Recurse -Force
        Start-Service -Name "MyApp"
      }
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

> **Безопасность:** Для production используйте Kerberos-аутентификацию и сертификаты вместо plain-text паролей. Рекомендуется PowerShell Just Enough Administration (JEA) для ограничения доступных команд на целевом хосте.

### Сценарий 5: Windows Service Management

Создание и управление Windows Service из CI/CD пайплайна.

```yaml
stages:
  - deploy

deploy-windows-service:
  stage: deploy
  tags:
    - windows
    - pwsh
  script:
    - |
      # Создание Windows Service
      New-Service -Name "MyApp" `
        -BinaryPathName "C:\MyApp\MyApp.exe" `
        -DisplayName "My Application" `
        -Description "My Application Service" `
        -StartupType Automatic
    - |
      # Настройка Service Recovery (перезапуск через 5 сек, 3 попытки)
      sc.exe failure MyApp reset= 86400 actions= restart/5000/restart/5000/restart/5000
    - Start-Service -Name "MyApp"
    - Get-Service -Name "MyApp"
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 6: Active Directory Integration

Интеграция развёртывания с Active Directory для управления правами.

```yaml
stages:
  - deploy

deploy-ad:
  stage: deploy
  tags:
    - windows
    - pwsh
  script:
    - |
      # Интеграция с Active Directory
      Import-Module ActiveDirectory
      $group = Get-ADGroup -Filter {Name -eq "MyApp-Admins"}
      $user = Get-ADUser -Filter {SamAccountName -eq "deploy-user"}
      Add-ADGroupMember -Identity $group -Members $user
    - |
      # Настройка Kerberos аутентификации
      $spn = "HTTP/myapp.example.com"
      setspn -S $spn "$DEPLOY_USER"
    - |
      # Развертывание с Kerberos
      $credential = Get-Credential
      Invoke-Command -ComputerName "production-server" -Credential $credential -Authentication Kerberos -ScriptBlock {
        # Deploy commands
      }
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

## Валидация и проверка

1. **Runner status:** `gitlab-runner status` — Service должен быть `running`
2. **PowerShell script:** Запустите простой PowerShell скрипт — должен выполняться корректно
3. **Docker Windows:** `docker info` — должен отображаться `OSType: windows`
4. **Service:** `Get-Service gitlab-runner` — статус `Running`
5. **Deploy:** Проверьте развертывание на Windows-хосте — Service должен быть запущен
6. **Pipeline:** Запустите тестовый пайплайн — задача должна выполниться на раннере с нужным тегом

## Граничные случаи (Edge Cases)

| Сценарий | Описание | Решение |
|:---|:---|:---|
| **Workspace pollution** | Файлы из предыдущей задачи остаются в `C:\builds` | Используйте `before_script` для очистки; настройте `cleanup` политику |
| **File locking** | Файлы заблокированы процессом между задачами | Добавьте `Stop-Process` перед сборкой; используйте `Remove-Item -Force` |
| **Antivirus** | Антивирус блокирует доступ к рабочим директориям | Добавьте исключения для `C:\GitLab-Runner` и `C:\builds` |
| **Long paths** | Ошибки доступа к путям >260 символов | Включите `LongPathsEnabled` в реестре Windows |
| **PowerShell execution policy** | Скрипты не выполняются | `Set-ExecutionPolicy RemoteSigned -Scope LocalMachine` |
| **WinRM firewalls** | Не удаётся подключиться к удалённому хосту | Включите `Enable-PSRemoting -Force` и откройте порт 5985/5986 |
| **Docker Desktop WSL2** | Нестабильная работа Linux-контейнеров | Обновите WSL2 kernel; выделите достаточно памяти в `.wslconfig` |
| **Windows container version mismatch** | Ошибка `The container does not match the host operating system` | Обновите образ до той же версии, что и хост, или наоборот |

## Troubleshooting

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **Runner not connecting** | Неверный URL или токен | Проверьте URL и `glrt-` токен в конфигурации |
| **PowerShell script failed** | Execution Policy блокирует скрипт | `Set-ExecutionPolicy RemoteSigned -Scope LocalMachine` |
| **Docker not available** | Docker Engine/Desktop не установлен | Установите Docker Engine для Windows Server |
| **Windows container failed** | Несовместимость образа | Используйте образы для Windows (`mcr.microsoft.com`) |
| **Service not starting** | Нет прав или конфигурация неверна | Проверьте логи: `Get-EventLog -LogName Application` |
| **NuGet restore failed** | NuGet не установлен или источник недоступен | Установите NuGet и настройте источники |
| **Deployment failed** | Нет прав на удаленный хост | Настройте WinRM и права доступа |
| **File in use** | Файл заблокирован другим процессом | Используйте `handle.exe` или завершите процесс |
| **Path too long** | Превышен лимит 260 символов | Включите `LongPathsEnabled` в реестре |

## Лучшие практики (Best Practices)

**Безопасность:**
- Запускайте Runner как Windows Service под выделенным пользователем с минимальными правами (Least Privilege)
- Используйте Kerberos для аутентификации вместо NTLM или plain-text паролей
- Включите audit logging для всех деплоев
- Используйте LAPS (Local Administrator Password Solution) для управления локальными паролями
- Ограничьте права Service только необходимыми
- Включите `protected` флаг для production Runner'ов

**Производительность:**
- Отключайте антивирус для рабочих директорий (`C:\GitLab-Runner`, `C:\builds`)
- Используйте NVMe SSD для рабочей директории Runner'а
- Кешируйте NuGet пакеты между запусками
- Используйте MSBuild /t:Restore для параллельной загрузки пакетов
- Для Docker-задач используйте `pull_policy: if-not-present` для внутренних образов

**Надёжность:**
- Запускайте Runner как Windows Service с автоматическим перезапуском (Recovery: Restart the Service)
- Настройте Service Recovery Actions через `sc.exe failure`
- Используйте `retry: 2` для network-dependent задач
- Мониторьте Runner через Windows Event Log и Prometheus metrics (`listen_address = ":9252"`)
- Для управления Service с расширенными опциями используйте NSSM
- Настройте алерты на `gitlab_runner_queue_size > 0` и `runner_system_failure`

**Управление конфигурацией:**
- Храните `config.toml` в IaC (Ansible, Chef, Puppet)
- Используйте `glrt-` токены вместо устаревших registration tokens
- Регулярно обновляйте GitLab Runner и Windows Server (в рамках поддерживаемых версий)

## Очистка

```powershell
# Остановка и удаление Windows Service
Stop-Service -Name "gitlab-runner"
sc.exe delete gitlab-runner

# Очистка рабочих директорий
Remove-Item -Path "C:\GitLab-Runner\*" -Recurse -Force
Remove-Item -Path "C:\builds\*" -Recurse -Force

# Очистка кэша NuGet
Remove-Item -Path "$env:USERPROFILE\.nuget\packages\*" -Recurse -Force
```

## Дополнительная информация

### Смотрите также

- **[Управление парком Runner'ов (Fleet Management)](../Advanced/runner_fleet_management.md)** — теория, типы раннеров, Fleet Management, автоскейлинг
- **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)** — сравнение executor'ов, Windows ограничения, security
- **[Регистрация GitLab Runner](../Tutorials/runner_registration.md)** — пошаговая регистрация runner'ов, шаблоны конфигурации
- **[Раннеры GitLab CI: Windows и macOS](../Concepts/gitlab_ci_runners_platforms.md)** — архитектура shell executor на Windows, кросс-платформенные матрицы
