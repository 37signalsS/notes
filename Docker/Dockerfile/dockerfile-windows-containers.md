# Windows-контейнеры в Dockerfile

**Актуально для:** Windows Server 2025 (ltsc2025, build 26100) / Windows Server 2022 (ltsc2022, build 20348) / Docker Engine 29.x / Docker Desktop 4.38+.

## Определения

**Windows-контейнер** — контейнер на базе Windows Server OS, совместимый только с Windows-хостом. В отличие от Linux-контейнеров, требует совпадения версии ядра хоста и образа.

**Nano Server** — минимальный Windows Server-образ (только .NET runtime и PowerShell Core). Для .NET/Go/Rust-приложений; не содержит Win32 subsystem, IIS, full PowerShell.

**Server Core** — полный Windows Server-образ с Win32 subsystem (IIS, full PowerShell, Win32 API). Для Win32-приложений, IIS, PowerShell-скриптов, нативных Windows API.

**LTSC (Long-Term Servicing Channel)** — канал долгосрочной поддержки Windows Server. Версии: `ltsc2025` (Windows Server 2025, build 26100), `ltsc2022` (Windows Server 2022, build 20348), `ltsc2019` (build 17763, end of updates). Каждый LTSC — отдельная линейка образов.

**Process isolation** — режим изоляции по умолчанию: контейнер разделяет ядро хоста. Быстрый, но требует точного совпадения версии хоста и образа.

**Hyper-V isolation** — режим изоляции через utility VM: контейнер работает в лёгкой виртуальной машине с собственным ядром. Медленнее, но позволяет запускать контейнеры с версией, отличной от хоста (например, ltsc2022-образ на ltsc2025-хосте).

**`# escape=` `** — директива Dockerfile, меняющая символ экранирования с `\` на `` ` ``. Актуальна для Windows, где `\` используется в путях (`C:\Windows\System32`).

## Предварительные требования

### На хосте
- **ОС:** Windows Server 2022/2025 (LTSC) или Windows 11 21H2+/24H2+ (для Docker Desktop). Windows Server 2019 — end of updates.
- **Docker Engine:** 29.x+ на Windows Server (скачать с [mcr.microsoft.com](https://mcr.microsoft.com/product/docker/docker-engine)); Docker Desktop 4.38+ на Windows 11.
- **Режим контейнеров:** Windows Containers (не Linux Containers) — переключение через настройки Docker Desktop или установка Docker Engine.
- **Виртуализация:** Для Hyper-V isolation — включённая роль Hyper-V (`Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All`).
- **Права:** Администратор для установки Docker Engine, членство в группе `docker-users` (Docker Desktop) или локальный админ (Windows Server).

### В образе
- **Base image:** `mcr.microsoft.com/windows/servercore:ltsc2025` или `nanoserver:ltsc2025` с версией, совместимой с хостом.
- **Фреймворки (опционально):** Официальные образы `mcr.microsoft.com/dotnet/*` уже содержат .NET — не ставьте .NET поверх вручную.

## Основные концепции

### Выбор базового образа

| Образ | Содержимое | Размер (прибл.) | Когда использовать |
| :--- | :--- | :--- | :--- |
| `mcr.microsoft.com/windows/server:ltsc2025` | Базовый Windows Server OS | ~5.5 ГБ | Редко — как основа для кастомных образов |
| `mcr.microsoft.com/windows/servercore:ltsc2025` | Полный Win32 subsystem, IIS, full PowerShell | ~5.5 ГБ | Win32-приложения, IIS, PowerShell-скрипты, нативные Windows API |
| `mcr.microsoft.com/windows/nanoserver:ltsc2025` | Минимальный: .NET runtime, PowerShell Core | ~250 МБ | .NET/Go/Rust-приложения, микросервисы |
| `mcr.microsoft.com/windows/servercore/iis:windowsservercore-ltsc2025` | Server Core + IIS | ~5.8 ГБ | Веб-приложения на IIS |

Размер Windows-контейнера значительно больше Linux (~250–5500 МБ против ~80 МБ для chiseled Linux, по данным [.NET best practices](Docker_best_practices/dotnet.md)). Chiseled-образы (минимальные, как distroless) для Windows недоступны — только nanoserver или servercore.

### Version matching — ключевое правило

**Windows требует, чтобы версия ОС хоста совпадала с версией ОС образа.** Это фундаментальное отличие от Linux-контейнеров.

| Тег образа | Требуемый хост | Build |
| :--- | :--- | :--- |
| `ltsc2025` | Windows Server 2025 / Windows 11 24H2+ | 26100 |
| `ltsc2022` | Windows Server 2022 / Windows 11 21H2+ | 20348 |
| `ltsc2019` | Windows Server 2019 (end of updates) | 17763 |

При несовпадении версий — ошибка `The container does not match the host operating system`. Обход — Hyper-V isolation (см. ниже). Образы Windows **не имеют `latest`-тега** — всегда указывайте явный тег (`ltsc2025`/`ltsc2022`).

### Process vs Hyper-V isolation

| Режим | Ядро | Скорость | Совпадение версий | Когда |
| :--- | :--- | :--- | :--- | :--- |
| **Process** | Общее с хостом | Быстро | Обязательно | Production на выделенном Windows Server |
| **Hyper-V** | Отдельная utility VM | Медленнее (~5-15% overhead) | Не обязательно | Dev/CI, когда версия хоста ≠ версии образа |

Hyper-V isolation включается флагом `--isolation=hyperv` и требует установленной роли Hyper-V на хосте. На Windows Server 2025/2022 Hyper-V isolation является единственным способом запуска контейнеров с другой LTSC-версией.

### Отличия Dockerfile: Linux vs Windows

| Аспект | Linux | Windows |
| :--- | :--- | :--- |
| Экранирование | `\` (по умолчанию) | `` ` `` (через `# escape=` `) |
| Пути | `/app`, `/usr/local/bin` | `C:\app`, `C:\inetpub` |
| `--chown` в COPY/ADD | Поддерживается | **Не поддерживается** |
| `--tmpfs` | Поддерживается | **Не поддерживается** (используйте `--mount type=volume`) |
| `--read-only` | Поддерживается | С Windows Server 2022+ |
| Пользователь по умолчанию | root | ContainerUser |
| Chiseled/distroless | Доступны | Недоступны |
| PID 1 / сигналы | Нужен tini/dumb-init | Встроенные `csrss`/`wininit` (orphan adoption), сигналы через Windows Events/Job Objects |
| BuildKit | Полная поддержка | Экспериментальная (BuildKit v0.13+); `docker build` на Windows переключается на Legacy Builder |

Подробнее по каждому отличию: [`# escape`](Instructions/overview_definitions.md#ограничение-windows-контейнеры-и-escape), [`--chown` и пути](Instructions/copying_files.md#копирование-на-windows-контейнерах), [BuildKit на Windows](dockerfile_build_context.md#сборка-windows-контейнеров), [PID 1 на Windows](init_process_tini.md#windows-containers).

## Практические сценарии

### Сценарий 1: .NET multi-stage (nanoserver)

Полный пример с ограничениями — в [.NET best practices: сценарий 6](Docker_best_practices/dotnet.md#сценарий-6-windows-контейнер-nasмногосервисное-приложение). Схема:

```dockerfile
# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/dotnet/sdk:10.0-nanoserver-ltsc2022 AS builder
WORKDIR /src
COPY . .
RUN dotnet publish "MyApp.csproj" -c Release -o /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:10.0-nanoserver-ltsc2022
WORKDIR /app
COPY --from=builder /app/publish .
EXPOSE 8080
ENTRYPOINT ["dotnet", "MyApp.dll"]
```

### Сценарий 2: IIS (servercore/iis)

```dockerfile
# escape=`
FROM mcr.microsoft.com/windows/servercore/iis:windowsservercore-ltsc2025
RUN powershell -NoProfile -Command Remove-Item -Recurse C:\inetpub\wwwroot\*
WORKDIR /inetpub/wwwroot
COPY ./site/ .
EXPOSE 80
```

`# escape=` ` обязателен, если в Dockerfile есть Windows-пути с `\`. IIS-образ уже содержит Server Core + IIS — не устанавливайте Web-Server через `Add-WindowsFeature` поверх него.

### Сценарий 3: Директива `# escape`

```dockerfile
# escape=`
FROM mcr.microsoft.com/windows/servercore:ltsc2025
RUN dir C:\Windows\System32
```

Без `# escape=` ` обратный слэш в `C:\Windows` интерпретируется как экранирование и ломает команду. Подробнее: [ограничение Windows и `#escape`](Instructions/overview_definitions.md#ограничение-windows-контейнеры-и-escape).

### Сценарий 4: Windows-native приложение (NTLM, Windows Auth, реестр)

Для приложений, требующих Windows-специфичных API (NTLM, Windows Auth, реестр, COM), multi-stage сохраняется, но базовые образы — Windows-based. Это единственный случай, когда Windows-контейнер оправдан: приложение жёстко зависит от Win32 subsystem. Для кроссплатформенных приложений (.NET Core, Go, Java, Node.js) используйте Linux-контейнеры — они меньше, быстрее и не требуют совпадения версий.

### Сценарий 5: Hyper-V isolation для dev/CI

```bash
# Хост: Windows Server 2025 (ltsc2025), образ: ltsc2022
docker run --isolation=hyperv mcr.microsoft.com/windows/servercore:ltsc2022 cmd
# → работает: Hyper-V изоляция позволяет несовпадение версий
```

Полезно в CI, где версия runner-хоста фиксирована, а образ приложения — другой LTSC.

### Сценарий 6: PowerShell в Windows-контейнерах

Стандартная оболочка Windows (`cmd`) ограничена. Переключение на PowerShell — стандарт для современных Windows-образов:

```dockerfile
# escape=`
FROM mcr.microsoft.com/windows/servercore:ltsc2025
SHELL ["pwsh", "-Command"]
RUN $PSVersionTable.PSVersion
# → Major  Minor  Patch  PreReleaseLabel BuildLabel
# → 7      4      0                  7.4.0
```

Подробнее: [WORKDIR: PowerShell в Windows](Instructions/working_context.md#сценарий-2-powershell-в-windows-контейнерах).

## Операции и команды

| Команда | Описание |
| :--- | :--- |
| `docker build -t myapp:win .` | Сборка Windows-образа (на Windows-хосте) |
| `docker run --isolation=hyperv <img>` | Запуск в Hyper-V изоляции |
| `docker inspect <container> --format '{{.HostConfig.Isolation}}'` | Проверка режима изоляции (`windows` / `hyperv`) |
| `docker exec <container> netstat -an \| findstr 8080` | Проверка слушающего порта |
| `docker exec <container> powershell Get-Host` | Проверка PowerShell в контейнере |
| `docker info --format '{{.OSType}}'` | Проверка типа контейнеров (windows / linux) |
| `ver` | Проверка версии Windows внутри контейнера |

## Валидация

### Проверка сборки и запуска
```bash
# 1. Сборка образа
docker build -t myapp:win .
# → Successfully tagged myapp:win:latest

# 2. Проверка изоляции
docker run --rm myapp:win ver
# → Microsoft Windows [Version 10.0.26100]  (ltsc2025)

# 3. Проверка режима изоляции
docker run -d --name test myapp:win sleep infinity
docker inspect test --format '{{.HostConfig.Isolation}}'
# → windows  (process isolation)
docker stop test && docker rm test
```

### Проверка совместимости версий
```bash
# Версия хоста
ver
# → Microsoft Windows [Version 10.0.26100.XXXX]

# Версия образа (build)
docker run --rm mcr.microsoft.com/windows/servercore:ltsc2025 ver
# → Microsoft Windows [Version 10.0.26100]

# Должны совпадать для process isolation
```

### Проверка .NET в контейнере
```bash
# Версия .NET SDK/рантайма
docker run --rm mcr.microsoft.com/dotnet/sdk:10.0-nanoserver-ltsc2022 dotnet --version
# → 10.0.xxx
```

## Граничные случаи (Edge Cases)

| Сценарий | Описание | Решение |
| :--- | :--- | :--- |
| **Версия хоста новее образа (ltsc2025 → ltsc2022)** | Process isolation: ошибка version mismatch | `--isolation=hyperv` или пересборка образа под ltsc2025 |
| **Версия хоста старше образа** | Нельзя запустить ltsc2025 на ltsc2022-хосте | Только Hyper-V isolation (если поддерживается хостом) |
| **Пути > 260 символов** | Windows API limit MAX_PATH | Включить `LongPathsEnabled` в реестре хоста и контейнера |
| **Симлинки в COPY** | Windows симлинки ведут себя иначе | Проверять совместимость; избегать симлинков |
| **Antivirus блокирует слои** | Real-time scanning замедляет/ломает сборку | Исключить `C:\ProgramData\docker` и рабочие директории |
| **BuildKit фичи недоступны** | `docker build` на Windows использует Legacy Builder | BuildKit v0.13+ (экспериментально) или сборка на Linux-хосте |
| **Windows-контейнеры на Docker Desktop Mac** | Не поддерживаются | Использовать Linux-контейнеры или Windows-хост |

## Очистка (Cleanup)

```bash
# Удаление неиспользуемых Windows-образов (крупные!)
docker image prune -f
# → Reclaimed space: 5.2GB  (Windows-образы занимают много места)

# Очистка кэша сборки
docker builder prune -f

# Остановка и удаление контейнеров
docker container prune -f

# Удаление томов (если не нужны)
docker volume prune -f

# Полная очистка (осторожно!)
docker system prune -a --volumes
# → Внимание: удалит ВСЕ неиспользуемые образы, тома, сети
```

> **Важно:** Windows-образы (servercore ~5.5 ГБ) быстро заполняют диск. Настройте `docker system prune` по расписанию в production.

## Разрешение проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `The container does not match the host operating system` | Версия хоста ≠ версии образа | Согласовать версии или `--isolation=hyperv` |
| `--chown` игнорируется / ошибка | `--chown` не поддерживается на Windows | Использовать `USER` и ACL внутри `RUN` |
| `--tmpfs` не работает | Не поддерживается на Windows | `--mount type=volume` |
| `COPY` с `C:\...` ломается | Не задан `# escape=` ` | Добавить `# escape=` ` первой строкой |
| BuildKit-фичи недоступны (`--mount`, Heredoc) | `docker build` на Windows использует Legacy Builder | BuildKit v0.13+ (экспериментально) или сборка на Linux-хосте |
| Образ не запускается на Docker Desktop for Mac | Windows-контейнеры требуют Windows-хост | Использовать Linux-контейнеры или Windows-хост |
| `COPY` копирует как папку, а не файлы | Завершающий слэш в источнике | Уберите слэш: `COPY ./site /inetpub/wwwroot` |
| `SHELL` не влияет на exec-form | `SHELL` работает только для shell-form | Использовать JSON-массив в `RUN`/`CMD`/`ENTRYPOINT` |

Диагностика GPU на хосте (не в контейнере) — в [GPU-диагностика](../../Linux/Diagnostics/Hardware/gpu_diagnostics.md).

Производственные Windows-runner'ы (GitLab CI) — в [Windows Runner Production](../../CI-CD/GitLab_CI/Tutorials/windows_runner_production.md).

## Best Practices

- **Явный LTSC-тег** (`ltsc2025`/`ltsc2022`), никогда `latest` — его нет, и версия критична.
- **nanoserver для размера** — если приложение не требует Win32 subsystem; servercore только при необходимости IIS/Win32 API.
- **Linux-контейнер по умолчанию** — Windows-контейнер только для приложений, жёстко зависящих от Win32 subsystem.
- **Hyper-V isolation в dev/CI** — чтобы не привязываться к версии хоста; process isolation в production.
- **`# escape=` `** — первой строкой, если есть Windows-пути.
- **Согласовывайте версию хоста и образа** — самое частое препятствие при деплое.
- **Multi-stage и на Windows** — builder (sdk) → runtime (aspnet/nanoserver), как в сценарии 1.
- **PowerShell вместо cmd** — `SHELL ["pwsh", "-Command"]` для современных скриптов.
- **Регулярная очистка** — Windows-образы крупные (~5.5 ГБ servercore); настройте `docker system prune` по расписанию.
- **Long Paths** — включите `LongPathsEnabled` в реестре хоста для путей > 260 символов.

## Дополнительная информация

- **[.NET best practices: сценарий 6 (Windows-контейнер)](Docker_best_practices/dotnet.md#сценарий-6-windows-контейнер-nasмногосервисное-приложение)** — полный multi-stage пример и ограничения.
- **[`# escape` и Windows](Instructions/overview_definitions.md#ограничение-windows-контейнеры-и-escape)** — директива экранирования.
- **[COPY/ADD: Windows-ограничения](Instructions/copying_files.md#копирование-на-windows-контейнерах)** — `--chown`, симлинки.
- **[BuildKit на Windows](dockerfile_build_context.md#сборка-windows-контейнеров)** — Legacy Builder, разделители путей.
- **[PID 1 и Tini: Windows](init_process_tini.md#windows-containers)** — orphan adoption, сигналы.
- **[WORKDIR: PowerShell в Windows](Instructions/working_context.md#сценарий-2-powershell-в-windows-контейнерах)** — `SHELL ["pwsh", "-Command"]`.
- **[Windows Runner Production](../../CI-CD/GitLab_CI/Tutorials/windows_runner_production.md)** — production Windows-runner'ы в CI/CD.
- **[Windows Container Version Compatibility](https://learn.microsoft.com/virtualization/windowscontainers/deploy-containers/version-compatibility)** — матрица совместимости версий (Microsoft).
- **[Docker Engine for Windows Server](https://learn.microsoft.com/virtualization/windowscontainers/manage-docker/configure-docker-daemon)** — установка и настройка Docker Engine на Windows Server.
