# Runner Management для Mobile CI/CD

**Актуально для:** macOS 15+, Xcode 16–26, Android API 24–35, Tart 1.x, Orka 3.x, GitLab Runner 17.x

---

## Определения

**Runner Management** — управление исполнителями CI/CD: provisioning, scaling, monitoring, cleanup.

**Tart** — инструмент для управления виртуальными машинами macOS на Apple Silicon.

**Orka** — коммерческая платформа виртуализации macOS от MacStadium.

**UTM** — open-source виртуализация для macOS (QEMU-based).

**Golden Image** — шаблон ВМ с предустановленными инструментами.

**VM Template** — запеченный образ ВМ для быстрого развертывания.

**Pre-warmed Simulator** — предзагруженный симулятор для ускорения тестов.

**Headless Mode** — режим работы без графического интерфейса.

**Apple Silicon Hypervisor** — аппаратная виртуализация Apple (VZ framework).

**Runner MTTR** — среднее время от падения runner'а до восстановления его работоспособности.

**Runner Queue SLO** — целевое максимальное время ожидания job в очереди (например, < 5 минут для 95-го перцентиля).

**Runner Flake Rate** — процент недетерминированных падений джобов, вызванных состоянием runner'а (остатки предыдущих джобов, утечки ресурсов).

**Runner Capacity Headroom** — запас пропускной способности пула раннеров, выраженный в свободных slots vs. средней длине очереди.

**Noisy Neighbor** — эффект, когда один джоб на shared runner'е потребляет избыточно CPU/RAM/disk I/O, ухудшая стабильность соседних джобов.

**Runner Image Drift** — неконтролируемое расхождение конфигурации golden image от эталона из-за неотслеживаемых изменений в джобах.

---

## Базовые концепции

### Dedicated hardware vs virtualized runners

Dedicated Mac mini/Mac Studio обеспечивают предсказуемую производительность, но масштабируются линейно и стоят дорого. Virtualized runners на Apple Silicon дают плотность 4–8 ВМ на физический хост, снижая cost per job. Торг-офф: нагруженные UI-тесты на симуляторах теряют <15% производительности против bare metal, тогда как эмуляторы Android на KVM внутри ВМ — до 40%.

### Tart: установка, конфигурация, networking, storage, VM templates

Tart работает поверх Apple Virtualization.framework. ВМ хранятся как директории, что упрощает бэкапы и шаринг. Networking по умолчанию — `shared` (NAT), для изоляции используется `host` или bridges. Storage живёт в `~/Library/Tart/` и поддерживает thin provisioning. Томы можно монтировать через `--disk` для шаринг кэшей между инстансами.

### Orka: архитектура, преимущества, ограничения

Orka — коммерческий аналог Tart от MacStadium. Архитектура: control plane + compute nodes (Mac mini/Mac Pro). Преимущества: in-place миграция ВМ, GPU passthrough, SLA. Ограничения: vendor lock-in, цена, требуется внешний Mac для certain Apple-проверок.

### Управление Xcode симуляторами

Управление runtime, pre-warmed симуляторы, concurrent лимиты. Каждый Xcode runtime (~4–8 GB) устанавливается один раз в golden image. Pre-warmed симуляторы создаются `xcrun simctl create` и хранятся в backed-up директории. Concurrent limit: 2–4 активных симулятора на ядро M-серии, зависит от ОЗУ. Для параллельного запуска используйте `xcrun simctl spawn` + `xcpar` для парсинга статусов.

### Управление Android эмуляторами

Headless режим, hardware acceleration (HAXM/Hypervisor/KVM), multi-ABI. На macOS эмуляторы должны запускаться headless: `-no-window -no-audio -gpu swiftshader_indirect`. Hardware acceleration: на Apple Silicon — `-accel on` (Hypervisor), на Intel — HAXM. Multi-ABI: храните `~/.android/avd/` отдельно для x86_64 и arm64-v8a, кэшируйте системные образы.

### Disk management на macOS-раннерах

`~/Library/Developer/Xcode/DerivedData/`, SPM/Gradle/CocoaPods кэши, cleanup. DerivedData — основной потребитель места (~10–30 GB). CocoaPods кэш в `~/Library/Caches/CocoaPods`, SPM в `~/Library/Caches/org.swift.swiftpm`. Cleanup через `xcrun simctl erase all` + `rm -rf ~/Library/Developer/Xcode/DerivedData/*`. Scheduler: `launchd` раз в 6–12 часов или пре- и пост-джоба в CI.

### Scaling strategies

Auto-scaling, пул раннеров, queue management. На Apple Silicon используют пулы из 2–4 ВМ на хост с rotation. Auto-scaling: внешний orchestrator поднимает/уничтожает ВМ по длине очереди. Queue management: GitLab Runner `limit` в конфигурации, либо отдельные очереди для unit-tests и UI-tests.

### SRE-подход к Runner Management

**Принципы:**

- **Runner MTTR:** Измеряйте время от падения runner'а до восстановления. Target: < 15 минут для macOS-раннеров, < 5 минут для Linux-раннеров.
- **Runner Queue SLO:** Договоритесь о целевом времени ожидания job в очереди. Target: P95 < 5 минут.
- **Runner Flake Rate Management:** Ведите реестр flaky джобов, вызванных runner'ами. Устанавливайте SLA на починку (например, 3 рабочих дня).
- **Capacity Headroom:** Поддерживайте запас в 20–30% свободных slots для пиковых нагрузок и emergency-сборок.
- **Toil Reduction:** Автоматизируйте ротацию ВМ, cleanup, обновление golden image. Ручная замена "умершего" железа — это toil.
- **Observability:** Каждый runner должен иметь метрики: CPU, RAM, disk, temperature, job queue depth, last job duration.

### Sysadmin: управление парком macOS-раннеров

**Hardware lifecycle:**

- **Thermal Management:** Mac Studio/Mac mini при длительной нагрузке троттлят. Мониторьте температуру через `powermetrics` или `istat`. Порог: > 95°C CPU — требуется перерыв или улучшение вентиляции.
- **Hardware Refresh:** Планируйте замену железа по calendar, а не по отказу. Apple Silicon цикл — 3–4 года. После — wipe через `Erase All Content and Settings`.
- **Physical Security:** macOS-раннеры должны находиться в locked rack или secure room. SIP + FileVault + firmware password обязательны.

**Provisioning и конфигурация:**

- **macOS Updates:** Тестируйте новые minor macOS версии в изолированном пуле перед промоушеном в production. Apple Silicon runners обновляются через `softwareupdate`.
- **SIP и TCC:** На dedicated-раннерах может потребоваться отключение SIP для инструментов виртуализации. Для shared-пулов SIP должен оставаться включенным.
- **Network Egress:** Раннеры должны иметь стабильный доступ к Apple Developer Portal, TestFlight, Google APIs. В air-gapped окружениях требуется internal mirror.
- **Secrets Rotation:** Сертификаты подписи, Match password, Fastlane session хранятся на runner'е. Автоматизируйте ротацию: Apple Distribution — 1 год, Match password — 90 дней.
- **Cleanup Automation:** DerivedData, кэши, логи заполняют диск. Настройте `launchd` или `cron` для периодической очистки.

---

## Практические сценарии

### 1. Tart: установка и конфигурация

```bash
# Установка
brew install cirruslabs/tart/tart

# Создание golden image
tart create --from ~/Downloads/macos-14.4-arm64.dmg my-macos-runner

# Запуск
tart run my-macos-runner --net shared --disk 100GB

# Создание snapshot
tart clone my-macos-runner my-macos-runner-base

# Export шаблона
tart export my-macos-runner --output ~/templates/my-macos-runner.tar.gz --compression 6
```

Создание нового раннера из шаблона:

```bash
# Импорт шаблона (копирование быстрее, чем full clone)
tart clone my-macos-runner-base new-runner-$(date +%s)

# Установка зависимостей
tart set new-runner-123 --cloud-init ./cloud-init.yaml
```

### 2. Xcode симуляторы в CI

```bash
# Список доступных runtimes
xcrun simctl runtime list

# Создание pre-warmed симулятора (выполняется в golden image)
xcrun simctl create "iPhone 15 Pro" "com.apple.CoreSimulator.SimDeviceType.iPhone-15-Pro" "com.apple.CoreSimulator.SimRuntime.iOS-17-4"

# Headless запуск
xcrun simctl boot "iPhone 15 Pro" --arch arm64
xcrun simctl shutdown "iPhone 15 Pro"

# Параллельный запуск (bash)
for i in {1..4}; do
  xcrun simctl boot "iPhone 15 Pro"-$i &
done
wait
```

GitLab CI job для UI-тестов:

```yaml
ui_tests:
  stage: test
  tags:
    - tart-runner
  variables:
    SIMULATOR_NAME: "iPhone 15 Pro"
    XCODE_VERSION: "15.3"
  script:
    - xcrun simctl boot "$SIMULATOR_NAME" || true
    - xcrun simctl erase "$SIMULATOR_NAME"
    - xcodebuild test -workspace MyApp.xcworkspace -scheme MyAppUITests -destination "platform=iOS Simulator,name=$SIMULATOR_NAME" -resultBundlePath TestResults
  artifacts:
    paths:
      - TestResults/
    when: always
```

### 3. Android эмуляторы в CI

```bash
# Создание headless AVD
$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager "system-images;android-34;google_apis;x86_64"

# Конфигурация AVD
echo "hw.gpu.mode=swiftshader_indirect" >> ~/.android/avd/Pixel_6_API_34.avd/config.ini
echo "hw.gpu.enabled=yes" >> ~/.android/avd/Pixel_6_API_34.avd/config.ini

# Headless запуск
$ANDROID_HOME/emulator/emulator -avd Pixel_6_API_34 -no-window -no-audio -gpu swiftshader_indirect -no-boot-anim -accel on &
```

GitLab CI job:

```yaml
android_ui_tests:
  stage: test
  tags:
    - macos-runner
  variables:
    ANDROID_HOME: "/usr/local/lib/android/sdk"
    EMU_NAME: "Pixel_6_API_34"
  before_script:
    - echo "no" | $ANDROID_HOME/tools/bin/sdkmanager "system-images;android-34;google_apis;x86_64" || true
    - echo "hw.gpu.mode=swiftshader_indirect" >> ~/.android/avd/$EMU_NAME.avd/config.ini
  script:
    - $ANDROID_HOME/emulator/emulator -avd $EMU_NAME -no-window -no-audio -gpu swiftshader_indirect -no-boot-anim &
    - adb wait-for-device
    - ./gradlew connectedAndroidTest
```

### 4. Disk cleanup automation

launchd plist (`~/Library/LaunchAgents/com.ci.cleanup.plist`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ci.cleanup</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/usr/local/bin/ci-cleanup.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>3600</integer>
    <key>StandardOutPath</key>
    <string>/tmp/ci-cleanup.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/ci-cleanup.err</string>
</dict>
</plist>
```

Скрипт очистки (`/usr/local/bin/ci-cleanup.sh`):

```bash
#!/bin/bash
set -euo pipefail

# DerivedData (старше 24 часов)
find ~/Library/Developer/Xcode/DerivedData -type d -mtime +1 -exec rm -rf {} + 2>/dev/null || true

# Xcode кэши
rm -rf ~/Library/Caches/com.apple.dt.Xcode/*

# SPM кэш (оставляем последний)
find ~/Library/Caches/org.swift.swiftpm -type d -mtime +7 -exec rm -rf {} + 2>/dev/null || true

# CocoaPods
rm -rf ~/Library/Caches/CocoaPods/*

# Simulator данные
xcrun simctl shutdown all 2>/dev/null || true
xcrun simctl erase all 2>/dev/null || true

# Логи (опционально)
find ~/Library/Logs -type f -mtime +3 -delete 2>/dev/null || true
```

GitLab CI пре-/пост-джоба:

```yaml
stages:
  - prepare
  - test
  - cleanup

cache_cleanup:
  stage: cleanup
  script:
    - rm -rf ~/Library/Developer/Xcode/DerivedData/*
    - rm -rf ~/Library/Caches/CocoaPods/*
    - rm -rf ~/Library/Caches/org.swift.swiftpm/*
  when: always
  tags:
    - macos-runner
```

### 5. Monitoring runners

```bash
# Установка node_exporter (Homebrew)
brew install prometheus/node-exporter/node-exporter

# Запуск через launchd
brew services start node_exporter

# Проверка метрик
curl -s http://localhost:9100/metrics | grep -E "node_disk_|node_memory_|node_cpu_"

# Disk usage alert
df -h / | awk 'NR==2 {print $5}' | grep -qE '9[0-9]%' && echo "ALERT: Disk >90%" || true
```

Prometheus alert rules (фрагмент):

```yaml
groups:
  - name: runner_alerts
    rules:
      - alert: RunnerDiskSpaceHigh
        expr: 100 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"} * 100) > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Runner {{ $labels.instance }} disk > 85%"

      - alert: RunnerMemoryHigh
        expr: node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes * 100 < 10
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "Runner {{ $labels.instance }} memory < 10%"
```

### 6. Cost optimization

Расчет стоимости macOS-раннеров:

```bash
#!/bin/bash
# cost-calc.sh — оценка затрат на 1 месяц

echo "=== Входные параметры ==="
read -p "Количество раннеров: " runners
read -p "Среднее время джоба (мин): " job_minutes
read -p "Price per runner (USD/мес): " price_per_runner

total_minutes=$((runners * job_minutes * 22 * 5))  # 22 рабочих дня, 5 джобов/день
total_hours=$((total_minutes / 60))
echo "Всего часов работы: $total_hours"

echo "=== Вариант A: Dedicated hardware (Mac mini M2) ==="
cost_dedicated=$((runners * price_per_runner))
echo "Стоимость $runners раннеров: \$$cost_dedicated/мес"

echo "=== Вариант B: Virtualized (Tart на $runners хостах) ==="
echo "Плотность: 4 ВМ/хост"
hosts=$(( (runners + 3) / 4 ))
cost_virt=$((hosts * price_per_runner * 2))  # 2x на хост
echo "Нужно хостов: $hosts, стоимость: \$$cost_virt/мес"
```

Стратегии оптимизации:
- **Job duration budget:** установите SLA на длительность джоба (например, 15 минут). Джобы, превышающие бюджет, не попадают в основной квот-пул.
- **Cache warming:** кэшируйте DerivedData, Pods, Gradle между джобами на уровне ВМ.
- **Pre-warmed pool:** держите 2–4 ВМ с предзагруженными симуляторами для быстрых PR-проверок.
- **Nightly batch:** для ночных билдов используйте пул с пониженными hardware требованиями или deferred execution.

---

## Операции и команды

### Верификация окружения runner'а

| Команда | Назначение | Ожидаемый результат |
|---|---|---|
| `xcrun simctl list devices` | Доступные симуляторы | Перечень устройств с статусом `Booted`/`Shutdown` |
| `xcrun simctl runtime list` | Установленные Xcode runtimes | Список runtime версий с путями |
| `adb devices` | Подключенные Android-устройства | Список device IDs с статусом `device` |
| `brew list --versions` | Установленные пакеты | Версии Homebrew-пакетов |
| `xcodebuild -version` | Версия Xcode | `Xcode 16.x`, `Build version ...` |
| `systemctl status gitlab-runner` / `launchctl list \| grep run` | Статус runner-сервиса | `active (running)` |
| `tart list` | Список ВМ Tart | Таблица с именем, ОС, статусом |
| `tart info <vm>` | Информация о ВМ | ОЗУ, CPU, disk, networking |
| `security find-identity -p codesigning` | Сертификаты в Keychain | Строки вида `1) XXXXXXXX "Apple Distribution: ..."` |
| `df -h /` | Использование диска | Процент заполнения root раздела |
| `vm_stat` | Память macOS | `Pages free`, `Pages active`, `Pages inactive` |

### Управление golden image

```bash
# Экспорт шаблона
tart export my-macos-runner --output /artifacts/golden-image.tar.gz --compression 6

# Валидация образа после создания
tart run my-macos-runner --net none -- /bin/bash -c "xcodebuild -version && fastlane --version"
```

### Очистка окружения runner'а

```bash
# Очистка DerivedData
rm -rf ~/Library/Developer/Xcode/DerivedData/*

# Очистка Xcode кэшей
rm -rf ~/Library/Caches/com.apple.dt.Xcode/*

# Очистка SPM кэша
rm -rf ~/Library/Caches/org.swift.swiftpm/*

# Очистка CocoaPods
rm -rf ~/Library/Caches/CocoaPods/*

# Очистка симуляторов
xcrun simctl shutdown all 2>/dev/null || true
xcrun simctl erase all 2>/dev/null || true

# Очистка Android кэшей
rm -rf ~/.gradle/caches/*
rm -rf ~/.android/avd/*.avd/cache/*
```

---

## Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
|---|---|---|---|
| **Runner offline (GitLab)** | Сервис раннера не запущен или устарел | `launchctl list \| grep run` / `systemctl status gitlab-runner` | Перезапустить сервис, обновить бинарник |
| **Disk full on runner** | DerivedData, кэши или логи заполнили диск | `df -h /` | Очистка через cleanup-скрипт, расширение диска, alert на свободное место |
| **Simulator boot loop** | Поврежденный runtime, конфликт версий | `xcrun simctl list devices unavailable` | Удалить проблемный симулятор: `xcrun simctl delete <UDID>`, переустановить runtime |
| **Xcode build timeout** | Зависший симулятор или нехватка ресурсов | `ps aux \| grep -E "xcodebuild\|simulator"` | Убить зависшие процессы, увеличить RAM, использовать `--parallel` |
| **"Operation not permitted"** | TCC в macOS блокирует доступ терминала | Проверить Full Disk Access для runner-аккаунта | Добавить `gitlab-runner`/терминал в Full Disk Access |
| **Runner застрял в Pending** | Нет раннеров с нужными тегами | Проверить теги в CI-конфигурации | Добавить теги на runner, проверить `limit` в конфигурации |
| **Android emulator freeze** | Эмулятор завис на boot screen | `adb devices` — нет `device` | Убить процесс эмулятора, пересоздать AVD, проверить KVM/HAXM |
| **Thermal throttling** | Перегрев Mac mini/Mac Studio | `powermetrics --samplers smc` | Улучшить вентиляцию, снизить параллелизм, перезапустить |
| **Noisy neighbor (shared runner)** | Джоб потребляет избыточно ресурсы | `top`/`htop` во время выполнения джоба | Перейти на dedicated runner, установить cgroups/limit |
| **Runner image drift** | Golden image устарел, зависимости изменились | Сравнить версии пакетов с эталоном | Пересобрать golden image, версионировать шаблоны |
| **Tart VM не стартует** | Поврежденный образ, нехватка ресурсов | `tart list` — статус `failed` | Удалить и пересоздать ВМ, проверить disk space |
| **xcrun: error: unable to find utility** | Xcode Command Line Tools не установлены | `xcode-select -p` | Переустановить CLT: `sudo xcode-select --install` |
| **Runner heartbeat lost** | Runner не отправляет heartbeat в CI platform | GitLab Runner `concurrent` = 0, сеть недоступна | Проверить сеть, перезапустить runner service, проверить license/registration token |

---

## Наблюдаемость пайплайна

**Метрики runner'а:**
- **Runner Availability** — процент времени, когда runner доступен для джобов. SLO: > 99%.
- **Runner Job Queue P95** — 95-й перцентиль времени ожидания job в очереди. SLO: < 5 минут.
- **Runner MTTR** — время от падения runner'а до восстановления. Target: < 15 минут для macOS, < 5 минут для Linux.
- **Runner Flake Rate** — процент джобов, проваленных из-за состояния runner'а, а не кода. Target: < 1%.
- **Runner Disk Usage** — процент заполнения диска. Alert: > 85%.
- **Runner Temperature (macOS)** — температура CPU/GPU. Alert: > 95°C.
- **Runner Job Duration P95** — 95-й перцентиль длительности джоба. Spike указывает на деградацию железа.
- **Runner Capacity Headroom** — (свободные slots / общее количество slots) * 100%. Target: > 20%.

**Логирование:**
- Логируйте каждый job start/stop с runner ID, job ID, duration, exit code.
- Архивируйте runner system logs (unified log on macOS, journald on Linux) для каждого джоба.
- Сохраняйте golden image build manifest: дата создания, версии пакетов, Xcode version, checksum образа.
- Не храните секреты в runner logs — маскируйте переменные окружения.

**Alerting:**
- Срабатывание при Runner Availability < 99%.
- Срабатывание при Runner Job Queue P95 > 5 минут.
- Срабатывание при Runner Flake Rate > 1%.
- Срабатывание при Runner Disk Usage > 85%.
- Срабатывание при Runner Temperature > 95°C (macOS).
- Срабатывание при Runner Capacity Headroom < 20%.
- Срабатывание при длительном отсутствии heartbeat от runner'а (> 5 минут).

---

## Best Practices

- **Golden Image Versioning:** Храните golden image с semantic version (`golden-image-v1.2.3`) и manifest с checksum. Пересоздавайте раз в 1–2 недели или при изменении ключевых зависимостей.
- **Ephemeral runners для PR:** PR-валидация на одноразовых ВМ; ночные и релизные — на статичном пуле с persistent кэшем.
- **Disk alerts:** мониторинг свободного места на golden image и runner'ах. Threshold: 85% warning, 95% critical.
- **Simulator naming convention:** используйте predictable naming (`AppName-iOS17.4-iPhone15Pro`) для автоматического поиска.
- **Concurrency limits:** ограничьте параллельные джобы на раннере через GitLab Runner `limit` или внешний queue manager. Concurrent limit для симуляторов: 2–4 на ядро M-серии.
- **Backup golden images:** храните экспортированные `.tar.gz` шаблоны в self-hosted artifact storage (NFS, MinIO, локальный NAS) с versioning. Восстановление после сбоя — минуты вместо часов.
- **Log retention:** храните логи только последних 3–7 джобов на раннере, остальные экспортируйте в self-hosted хранилище.
- **Thermal management:** на Mac mini/Mac Studio установите порог по температуре. При превышении — приоритизируйте cold jobs или перезапуск.
- **Network hygiene:** runner'ы не должны иметь лишнего outbound доступа. Разрешите только Apple Developer Portal, TestFlight, Google APIs.
- **Secrets hygiene:** сертификаты и credentials должны поступать через Vault или CI variables, не фиксироваться в golden image.
- **Isolation:** для iOS подписи используйте ephemeral keychain. Для Android — отдельные keystore на джобу.
- **Cleanup hooks:** всегда добавляйте post-job cleanup: `xcrun simctl shutdown all`, `rm -rf DerivedData`, `adb emu kill`.
- **Runbook'и:** для каждого типичного сбоя (падение симулятора, исчерпание диска, зависание джоба) должно быть пошаговое руководство.
- **Capacity planning:** поддерживайте headroom 20–30% для пиковых нагрузок. Мониторьте trend очереди, а не текущее значение.

---

## См. также

- [index.md](./index.md) — обзор Mobile CI/CD архитектуры, общие определения runners
- [ios-ci-cd.md](./ios-ci-cd.md) — подпись iOS, управление симуляторами, cleanup
- [android-ci-cd.md](./android-ci-cd.md) — подпись Android, Linux-раннеры, эмуляторы
