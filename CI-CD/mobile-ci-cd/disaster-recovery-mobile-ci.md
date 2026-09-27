# Disaster Recovery для Mobile CI/CD

## Определения

**Disaster Recovery (DR)** — процесс восстановления инфраструктуры и данных после катастрофических сбоев: потеря macOS-раннера, повреждение Keychain-сервиса, потеря Match-репозитория, недоступность GitLab Runner или компрометация секретов.

**RTO (Recovery Time Objective)** — максимальное допустимое время восстановления сервиса. Для Mobile CI/CD: < 2 часа на macOS-раннер, < 1 часа на Match-репозиторий и Keychain, < 30 минут на секреты.

**RPO (Recovery Point Objective)** — максимальная допустимая потеря данных. Для Mobile CI/CD: 0 для Git-конфигурации и CI/CD-пайплайнов, < 1 часа для Match-репозитория и бэкапов ключей, 0 для ephemeral Keychain.

**Runbook** — пошаговая инструкция для дежурного инженера, описывающая действия при определенном типе сбоя без дополнительных объяснений.

**Backup** — копия критически важных данных, созданная для восстановления при потере или повреждении оригинала.

**Restore** — процесс возврата системы из резервной копии в рабочее состояние.

**Ephemeral Keychain** — временная связка ключей, создаваемая внутри джобы CI для безопасного хранения сертификатов. Автоматически удаляется после завершения сборки.

**MTTR (Mean Time To Recover)** — среднее время восстановления после инцидента. Для Mobile CI/CD включает время регистрации нового раннера, восстановления сертификатов и перезапуска пайплайна.

**MTTA (Mean Time To Acknowledge)** — среднее время между срабатыванием алерта и принятием инцидента дежурным инженером.

**Error Budget (DR)** — допустимый объем простоев или пропущенных бэкапов в течение месяца. При исчерпании бюджета — фокус на улучшение DR-процедур вместо новых фич.

**Blameless Postmortem** — разбор инцидента без персональной ответственности, фокусирующийся на системных причинах и action items.

---

## Базовые концепции

### Компоненты Mobile CI/CD, требующие DR

| Компонент | RTO | RPO | Критичность | Тип бэкапа |
|:---|:---|:---|:---|:---|
| **macOS-раннеры** | 2 часа | 0 (stateless) | Высокая | Нет (восстанавливаются из образа) |
| **Match-репозиторий** | 1 час | < 1 часа | Критическая | Git mirror + cron |
| **Keychain-сервис** | 1 час | 0 (ephemeral) | Критическая | PKCS#12 + GPG |
| **CI/CD конфигурация** | 15 минут | 0 (Git) | Средняя | Git + mirror |
| **Fastlane конфигурация** | 15 минут | 0 (Git) | Средняя | Git + mirror |
| **Секреты (API Keys, MATCH_PASSWORD)** | 30 минут | 0 | Критическая | Encrypted backup |
| **Artifacts (IPA, APK, dSYM)** | 4 часа | < 24 часа | Средняя | Offsite storage |
| **Provisioning Profiles** | 1 час | 0 (из Match) | Высокая | Match repo |

### Типы сбоев

| Тип | Пример | Влияние | RTO | MTTR impact |
|:---|:---|:---|:---|:---|
| **Hardware Failure** | Mac-раннер сломался, диск вышел из строя | Нет сборок, задержка релизов | 2 часа | SEV2 |
| **Software Corruption** | Keychain поврежден, certificates не читаются | Нет подписи, блокировка пайплайна | 1 час | SEV1 |
| **Data Loss** | Match-репозиторий потерян, git push force | Нет сертификатов, ручное управление профилями | 1 час | SEV1 |
| **Network Outage** | GitLab недоступен, VPN упал | Нет деплоев, нет доступа к коду | 30 минут | SEV2 |
| **Security Breach** | API Keys скомпрометированы, сертификаты украдены | Полная остановка, необходимость rotation | 4 часа | SEV1 |
| **Supply Chain Compromise** | Зависимость с CVE, скомпрометированная библиотека | Безопасный релиз заблокирован | 2 часа | SEV2 |

### DR Strategy для Mobile CI/CD

```
┌───────────────────────────────────────────────────────────────────┐
│              Mobile CI/CD DR Strategy Matrix                       │
│                                                                   │
│  Tier 0 (Critical):   Match repo, Keychain, Secrets              │
│    RTO: < 1 hour       RPO: < 1 hour                             │
│    Strategy: Warm Standby (daily backup + tested restore)        │
│                                                                   │
│  Tier 1 (High):       macOS-раннеры, CI config                  │
│    RTO: < 2 hours      RPO: 0 (stateless / Git)                 │
│    Strategy: Cold Standby (Golden Image + Git mirror)            │
│                                                                   │
│  Tier 2 (Medium):     Artifacts, logs, reports                   │
│    RTO: < 4 hours      RPO: < 24 hours                          │
│    Strategy: Backup & Restore (offsite storage)                  │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

### SRE-подход к Mobile CI/CD DR

**Принципы:**

- **MTTR как KPI:** Измеряйте время от инцидента до полного восстановления. Для mobile учитывайте не только техническое восстановление, но и время повторного запуска пайплайнов.
- **Error Budget для DR:** Договоритесь о допустимом количестве пропущенных бэкапов или простоев DR-инфраструктуры. При исчерпании бюджета — фокус на улучшение DR-процедур.
- **Toil Reduction:** Автоматизируйте проверку актуальности бэкапов, тестирование восстановления, уведомление команд. Ручной weekly check каждого бэкапа — это toil.
- **Observability:** Каждый инцидент DR должен иметь полный trace: alert → triage → recovery → verification → postmortem.
- **On-call Rotation:** DR-инциденты должны приходить дежурному инженеру с четкими runbooks, а не в общий канал.

---

## Практические сценарии

### 1. Backup Match-репозитория

```bash
#!/bin/bash
# backup_match_repo.sh
# Автоматический бэкап Match-репозитория

MATCH_REPO="git@gitlab.com:company/match-repo.git"
BACKUP_REPO="git@gitlab.com:company/match-backup.git"
BACKUP_DIR="/tmp/match-backup-$(date +%Y%m%d-%H%M%S)"
LOG_FILE="/var/log/match-backup.log"

# Клонирование основного репозитория (shallow clone для скорости)
git clone --depth 1 "$MATCH_REPO" "$BACKUP_DIR" 2>> "$LOG_FILE"

if [ $? -ne 0 ]; then
  echo "ERROR: Failed to clone match repo" >> "$LOG_FILE"
  exit 1
fi

cd "$BACKUP_DIR"

# Push в backup репозиторий
git remote add backup "$BACKUP_REPO"
git push backup main 2>> "$LOG_FILE"

if [ $? -ne 0 ]; then
  echo "ERROR: Failed to push to backup repo" >> "$LOG_FILE"
  exit 1
fi

# Очистка
rm -rf "$BACKUP_DIR"

echo "Backup completed: $(date)" >> "$LOG_FILE"
```

**Cron job (ежедневный бэкап):**
```bash
# /etc/crontab
0 2 * * * /path/to/backup_match_repo.sh >> /var/log/match-backup.log 2>&1
# → Ежедневно в 02:00
```

**Проверка актуальности бэкапа:**
```bash
# Проверка последнего коммита в backup репозитории
git ls-remote git@gitlab.com:company/match-backup.git main | cut -f1
git ls-remote git@gitlab.com:company/match-repo.git main | cut -f1

# Должны совпадать
```

### 2. Backup Keychain-сервиса

```ruby
# fastlane/actions/backup_keychain.rb
module Fastlane
  module Actions
    class BackupKeychain < Action
      def self.run(params)
        keychain_name = params[:keychain_name]
        backup_path = params[:backup_path]
        password = params[:password]
        
        # Создание директории для бэкапа
        FileUtils.mkdir_p(backup_path)
        
        # Экспорт keychain в PKCS#12
        export_cmd = "security export -k #{keychain_name} -t pkcs12 -o #{backup_path}/keychain_#{Time.now.strftime('%Y%m%d-%H%M%S')}.p12 -P '#{password}'"
        
        unless system(export_cmd)
          UI.error("Failed to export keychain")
          return false
        end
        
        # Шифрование backup через GPG
        backup_file = Dir.glob("#{backup_path}/keychain_*.p12").max_by { |f| File.mtime(f) }
        gpg_cmd = "gpg --symmetric --cipher-algo AES256 --output #{backup_file}.gpg #{backup_file}"
        
        unless system(gpg_cmd)
          UI.error("Failed to encrypt keychain backup")
          return false
        end
        
        # Удаление незашифрованного файла
        FileUtils.rm(backup_file)
        
        # Очистка старых бэкапов (> 30 дней)
        Dir.glob("#{backup_path}/keychain_*.p12.gpg").each do |file|
          if File.mtime(file) < (Time.now - 30 * 24 * 60 * 60)
            FileUtils.rm(file)
          end
        end
        
        UI.success("Keychain backup created and encrypted: #{backup_path}")
        true
      end

      def self.available_options
        [
          FastlaneCore::ConfigItem.new(key: :keychain_name, description: "Keychain name"),
          FastlaneCore::ConfigItem.new(key: :backup_path, description: "Backup directory"),
          FastlaneCore::ConfigItem.new(key: :password, description: "Keychain password", sensitive: true)
        ]
      end
    end
  end
end
```

### 3. Recovery Procedures

**Runbook: macOS-раннер сломался**

```bash
#!/bin/bash
# recover_runner.sh

echo "=== Recovery: macOS Runner ==="

# 1. Проверка статуса раннера
echo "Step 1: Checking runner status..."
gitlab-runner verify
# → Verifying runner... is alive

# 2. Удаление неработающего раннера (если нужно)
echo "Step 2: Removing broken runner..."
gitlab-runner unregister --token "$RUNNER_TOKEN"

# 3. Регистрация нового раннера
echo "Step 3: Registering new runner..."
gitlab-runner register \
  --url "https://gitlab.company.com" \
  --token "$RUNNER_TOKEN" \
  --executor "shell" \
  --tag-list "ios,macos" \
  --description "Mac Mini M2 - $(hostname)"

# → Runner registered successfully

# 4. Установка зависимостей
echo "Step 4: Installing dependencies..."
xcode-select --install
brew install fastlane

# 5. Настройка Keychain
echo "Step 5: Setting up keychain..."
security create-keychain -p "$KEYCHAIN_PASSWORD" ci_build.keychain
security set-keychain-settings -lut 21600 ci_build.keychain
security unlock-keychain -p "$KEYCHAIN_PASSWORD" ci_build.keychain
security import /path/to/certificates.p12 \
  -k ci_build.keychain \
  -P "$CERT_PASSWORD" \
  -T /usr/bin/codesign \
  -T /usr/bin/security

# 6. Верификация
echo "Step 6: Verification..."
gitlab-runner verify
xcodebuild -version
fastlane --version
security find-identity -v -p codesigning ci_build.keychain
# → 1) XXXXXXXX "Apple Distribution: Company (TEAMID)"

echo "=== Recovery completed ==="
```

**Runbook: Match-репозиторий потерян**

```bash
#!/bin/bash
# recover_match_repo.sh

echo "=== Recovery: Match Repository ==="

# 1. Восстановление из backup
echo "Step 1: Cloning from backup..."
git clone "git@gitlab.com:company/match-backup.git" /tmp/match-recovery

# 2. Переименование в основной репозиторий
echo "Step 2: Restoring to main repo..."
cd /tmp/match-recovery
git remote rename origin backup
git remote add origin "git@gitlab.com:company/match-repo.git"
git push origin main

# → main -> main

# 3. Проверка
echo "Step 3: Verification..."
fastlane match appstore --readonly
# → [✔] All certificates and profiles are up to date

# 4. Очистка
rm -rf /tmp/match-recovery

echo "=== Recovery completed ==="
```

**Runbook: Keychain-сервис поврежден**

```bash
#!/bin/bash
# recover_keychain.sh

echo "=== Recovery: Keychain Service ==="

KEYCHAIN_NAME="ci_build.keychain"
KEYCHAIN_PASSWORD="$KEYCHAIN_PASSWORD"

# 1. Удаление поврежденного keychain
echo "Step 1: Removing corrupted keychain..."
security delete-keychain "$KEYCHAIN_NAME" 2>/dev/null || true

# 2. Создание нового keychain
echo "Step 2: Creating new keychain..."
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_NAME"
security set-keychain-settings -lut 21600 "$KEYCHAIN_NAME"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_NAME"

# 3. Импорт сертификатов из backup
echo "Step 3: Importing certificates from backup..."
BACKUP_CERTS="/path/to/backup/certificates.p12"

if [ ! -f "$BACKUP_CERTS" ]; then
  echo "ERROR: Backup certificates not found at $BACKUP_CERTS"
  exit 1
fi

security import "$BACKUP_CERTS" \
  -k "$KEYCHAIN_NAME" \
  -P "$CERT_PASSWORD" \
  -T /usr/bin/codesign \
  -T /usr/bin/security

# 4. Настройка ACL
echo "Step 4: Setting up ACL..."
security set-key-partition-list -S apple-tool:,apple:,codesign: \
  -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_NAME"

# 5. Проверка
echo "Step 5: Verification..."
security find-identity -v -p codesigning "$KEYCHAIN_NAME"
# → 1) XXXXXXXX "Apple Distribution: Company (TEAMID)"

echo "=== Recovery completed ==="
```

### 4. Fastlane Recovery Actions

```ruby
# fastlane/actions/recover_ci_environment.rb
module Fastlane
  module Actions
    class RecoverCIEnvironment < Action
      def self.run(params)
        results = {
          keychain: recover_keychain,
          match: recover_match,
          dependencies: verify_dependencies
        }
        
        if results.values.all?
          UI.success("CI environment recovered successfully")
          true
        else
          UI.error("CI environment recovery failed")
          results.each do |component, status|
            UI.message("#{component}: #{status ? 'OK' : 'FAILED'}")
          end
          false
        end
      end

      def self.recover_keychain
        keychain_name = "ci_build.keychain"
        
        unless system("security find-identity -v -p codesigning -s #{keychain_name}")
          UI.important("Keychain not found, recovering...")
          
          # Создание нового keychain
          system("security create-keychain -p '' #{keychain_name}")
          system("security set-keychain-settings -lut 21600 #{keychain_name}")
          system("security unlock-keychain -p '' #{keychain_name}")
          
          # Импорт сертификатов
          system("security import /path/to/backup/certificates.p12 -k #{keychain_name} -P '' -T /usr/bin/codesign")
          
          UI.success("Keychain recovered")
          true
        else
          UI.message("Keychain OK")
          true
        end
      end

      def self.recover_match
        unless system("fastlane match appstore --readonly")
          UI.important("Match not working, recovering...")
          
          # Восстановление из backup
          system("git clone git@gitlab.com:company/match-backup.git /tmp/match-recovery")
          system("cd /tmp/match-recovery && git push origin main")
          system("rm -rf /tmp/match-recovery")
          
          # Проверка
          system("fastlane match appstore --readonly")
        else
          UI.message("Match OK")
          true
        end
      end

      def self.verify_dependencies
        if system("bundle check")
          UI.message("Dependencies OK")
          true
        else
          UI.important("Dependencies not installed, running bundle install...")
          system("bundle install")
        end
      end
    end
  end
end
```

### 5. DR Testing

**GitLab CI:**
```yaml
dr_test:
  stage: .pre
  image: ruby:3.2
  tags:
    - macos
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      when: always
    - when: manual
  script:
    - |
      ./scripts/backup_match_repo.sh
      # Проверка: последний коммит в backup должен совпадать с основным
      BACKUP_COMMIT=$(git ls-remote git@gitlab.com:company/match-backup.git main | cut -f1)
      MAIN_COMMIT=$(git ls-remote git@gitlab.com:company/match-repo.git main | cut -f1)
      if [ "$BACKUP_COMMIT" != "$MAIN_COMMIT" ]; then
        echo "ERROR: Backup is outdated"
        exit 1
      fi
      echo "Match backup OK"
    - |
      # Проверка наличия свежего бэкапа keychain
      LATEST_BACKUP=$(ls -t /path/to/backups/keychain_*.p12.gpg 2>/dev/null | head -1)
      if [ -z "$LATEST_BACKUP" ]; then
        echo "ERROR: No keychain backup found"
        exit 1
      fi
      BACKUP_AGE=$(( ($(date +%s) - $(stat -f %m "$LATEST_BACKUP")) / 86400 ))
      if [ $BACKUP_AGE -gt 1 ]; then
        echo "ERROR: Keychain backup is $BACKUP_AGE days old"
        exit 1
      fi
      echo "Keychain backup OK (age: $BACKUP_AGE days)"
    - |
      # Тест восстановления без фактического изменения
      git clone --depth 1 git@gitlab.com:company/match-backup.git /tmp/match-recovery-test
      cd /tmp/match-recovery-test
      git log --oneline -5
      rm -rf /tmp/match-recovery-test
      echo "Recovery dry run OK"
    - |
      cat > dr-report.md << EOF
      # DR Test Report
      **Date:** $(date)
      **Status:** PASSED

      ## Tests
      - Match backup: PASSED
      - Keychain backup: PASSED
      - Recovery dry run: PASSED

      ## Next Test
      $(date -d "+1 month" +%Y-%m-%d)
      EOF
  artifacts:
    paths:
      - dr-report.md
    expire_in: 1 week
```

### 6. Full DR Drill (Quarterly)

```bash
#!/bin/bash
# dr_drill.sh - Полное учение по DR

set -e

echo "=== DR Drill Started: $(date) ==="

# Phase 1: Pre-drill checks
echo "Phase 1: Pre-drill checks"
./scripts/verify_backups.sh
./scripts/verify_runner_health.sh

# Phase 2: Simulate failure
echo "Phase 2: Simulating runner failure"
gitlab-runner stop
sleep 5

# Phase 3: Recovery
echo "Phase 3: Recovery"
./scripts/recover_runner.sh

# Phase 4: Verification
echo "Phase 4: Verification"
gitlab-runner verify
xcodebuild -version
fastlane --version

# Phase 5: Smoke test
echo "Phase 5: Smoke test"
cd /path/to/mobile-app
fastlane beta --skip_tests

echo "=== DR Drill Completed: $(date) ==="
echo "MTTR: $(($(date +%s) - START_TIME)) seconds"
```

---

## Операции и команды

### Backup Commands

```bash
# Match-репозиторий: ручной бэкап
git clone --depth 1 git@gitlab.com:company/match-repo.git /tmp/match-backup
cd /tmp/match-backup && git remote add backup git@gitlab.com:company/match-backup.git
git push backup main && rm -rf /tmp/match-backup

# Keychain: экспорт и шифрование
security export -k ci_build.keychain -t pkcs12 -o /backups/keychain.p12 -P "$KEYCHAIN_PASSWORD"
gpg --symmetric --cipher-algo AES256 /backups/keychain.p12
# → /backups/keychain.p12.gpg

# CI/CD конфигурация: Git bundle
git bundle create ci-config-$(date +%Y%m%d).bundle --all
# → ci-config-20260926.bundle

# Проверка актуальности бэкапа
git ls-remote git@gitlab.com:company/match-backup.git main | cut -f1
git ls-remote git@gitlab.com:company/match-repo.git main | cut -f1
```

### Recovery Commands

```bash
# Восстановление Match-репозитория
git clone git@gitlab.com:company/match-backup.git /tmp/match-recovery
cd /tmp/match-recovery && git remote rename origin backup
git remote add origin git@gitlab.com:company/match-repo.git
git push origin main

# Восстановление Keychain
security delete-keychain ci_build.keychain
security create-keychain -p "$KEYCHAIN_PASSWORD" ci_build.keychain
security unlock-keychain -p "$KEYCHAIN_PASSWORD" ci_build.keychain
security import /backups/keychain.p12.gpg -k ci_build.keychain -P "$CERT_PASSWORD"
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" ci_build.keychain

# Проверка после восстановления
fastlane match appstore --readonly
security find-identity -v -p codesigning ci_build.keychain
```

### Health Check Commands

```bash
# Проверка раннера
gitlab-runner verify
# → Verifying runner... is alive

# Проверка Keychain
security find-identity -v -p codesigning ci_build.keychain
# → 1) XXXXXXXX "Apple Distribution: Company (TEAMID)"

# Проверка Match
fastlane match appstore --readonly
# → [✔] All certificates and profiles are up to date

# Проверка Xcode
xcodebuild -version
# → Xcode 15.0
# → Build version 15A240d

# Проверка Fastlane
fastlane --version
# → fastlane 2.220.0
```

### DR Drill Commands

```bash
# Запуск полного учения
./scripts/dr_drill.sh

# Dry-run восстановления
git clone --depth 1 git@gitlab.com:company/match-backup.git /tmp/dr-test
cd /tmp/dr-test && git log --oneline -5 && rm -rf /tmp/dr-test

# Проверка актуальности бэкапов
./scripts/verify_backups.sh
```

---

## Устранение проблем

| Ошибка | Причина | Решение | MTTR impact |
|:---|:---|:---|:---|
| **Runner не регистрируется** | Неверный токен, URL, или раннер уже существует | Проверьте токен в GitLab, удалите старый раннер через UI, повторите регистрацию | 30 минут |
| **Match-репозиторий устарел** | Бэкап не запускался, cron упал, credentials истекли | Проверьте `/var/log/match-backup.log`, исправьте cron, запустите бэкап вручную | 1 час |
| **Keychain не читается** | Сертификат истек, Keychain заблокирован, неправильный пароль | Проверьте `security find-identity`, разблокируйте Keychain, обновите сертификат | 1 час |
| **Code signing failed** | Сертификат не найден, provisioning profile не соответствует, Keychain не unlocked | Проверьте `setup_ci_keychain` в Fastfile, убедитесь что сертификат импортирован | 30 минут |
| **Fastlane match failed** | Нет доступа к репозиторию, MATCH_PASSWORD неверный, профиль истек | Проверьте переменные окружения, обновите Match: `fastlane match appstore --force_for_new_devices` | 1 час |
| **Бэкап не создается** | Cron не работает, скрипт упал, нет прав на запись | Проверьте `/etc/crontab`, логи скрипта, права на директорию бэкапа | 15 минут |
| **GitLab недоступен** | Network outage, VPN упал, DNS не резолвится | Проверьте сеть, используйте зеркало репозитория, альтернативный VPN | 30 минут |
| **Секреты скомпрометированы** | Утечка в логах, compromised runner, украден ноутбук | Rotate все секреты, проведите аудит доступа, проверьте логи на утечку | 4 часа |
| **GPG decryption failed** | Неверный пароль, поврежденный файл бэкапа | Проверьте пароль, проверьте целостность файла (`gpg --verify`), используйте backup GPG ключ | 1 час |
| **Provisioning Profile не найден** | Профиль истек, не добавлен в Match, Bundle ID не совпадает | Проверьте срок действия в App Store Connect, обновите через Match | 30 минут |
| **Xcode build failed после DR** | Неправильная версия Xcode, отсутствуют зависимости, Keychain не настроен | Проверьте `xcode-select --install`, `bundle install`, `setup_ci_keychain` | 1 час |
| **Artifacts потеряны** | Нет offsite бэкапа, storage переполнен, файлы удалены | Восстановите из GitLab CI artifacts или пересоберите | 4 часа |

---

## Рекомендации

### Best Practices

- **Automated Backups:** Настройте автоматические бэкапы Match-репозитория и Keychain. Cron должен проверять успешность выполнения.
- **Regular Testing:** Проводите DR-учения ежемесячно (dry-run) и quarterly (full drill). Измеряйте MTTR и сравнивайте с RTO.
- **Documentation:** Документируйте все процедуры восстановления в runbooks. Runbook должен быть понятен дежурному инженеру без дополнительных объяснений.
- **Immutable Backups:** Храните бэкапы Keychain в зашифрованном виде (GPG). Используйте append-only политику для Git-репозиториев бэкапов.
- **Redundancy:** Используйте резервные раннеры. Для Tier 0 компонентов (Match, Keychain) — warm standby с ежедневным бэкапом.
- **Error Budget для DR:** Установите лимит пропущенных бэкапов в месяц. При исчерпании — freeze на новые фичи до устранения проблем.
- **Secrets Rotation:** Периодически ротируйте секреты, особенно после инцидентов безопасности. Используйте short-lived credentials где возможно.
- **Observability:** Настройте алерты на устаревание бэкапов, недоступность раннеров, ошибки восстановления.

### Edge Cases и ограничения

1. **Match-репозиторий как single point of failure:** Если Match-репозиторий потерян и бэкап недоступен — требуется повторная выдача всех сертификатов через App Store Connect и Google Play Console. Это занимает часы.
2. **Keychain password loss:** Если пароль Keychain утерян — все сертификаты становятся недоступными. Требуется повторная выдача сертификатов.
3. **Runner hardware failure:** macOS-раннеры требуют физического доступа для ремонта. Имейте hot-swap раннер или виртуальную среду (Tart/Orka).
4. **Ephemeral Keychain limitations:** Keychain создается внутри джобы и удаляется после. Если джоба падает — Keychain теряется, но сертификаты остаются в Match.
5. **GPG key loss:** Если GPG-ключ для расшифровки бэкапов утерян — бэкапы становятся бесполезными. Храните GPG-ключ в нескольких местах (paper key, secure storage).
6. **GitLab outage:** Если Git-хостинг недоступен — нет доступа к коду, конфигурации и Match-репозиторию. Имейте локальную копию или зеркало.
7. **Simultaneous failures:** Если раннер и Match-репозиторий выходят из строя одновременно — восстанавливайте приоритетно Match, затем раннер.
8. **Certificates expiration:** Сертификаты подписи имеют срок действия (1 год). Настройте алерты за 30/7/1 день до истечения.

### Мониторинг и Observability

**Ключевые метрики:**
- **Backup Freshness:** возраст последнего успешного бэкапа (Match, Keychain)
- **Backup Success Rate:** % успешных бэкапов за месяц
- **MTTR DR:** время от инцидента до восстановления
- **DR Drill Frequency:** частота проведения учений
- **Runner Availability:** % времени доступности macOS-раннеров

**Alert Rules:**
```yaml
groups:
  - name: dr_alerts
    rules:
      - alert: MatchBackupTooOld
        expr: dr_match_backup_age_hours > 24
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Match backup older than 24 hours"
      
      - alert: KeychainBackupTooOld
        expr: dr_keychain_backup_age_hours > 1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Keychain backup older than 1 hour"
      
      - alert: RunnerDown
        expr: dr_runner_available == 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "macOS runner is unavailable"
```

**Quality Gates:**
- Все бэкапы должны быть актуальными: Match < 24 часа, Keychain < 24 часа
- DR-учения должны проводиться ежемесячно
- Все runbooks должны быть актуальными (< 180 дней с последнего обновления)

---

## Дополнительная информация

- **[Mobile CI/CD Overview](./index.md)** — архитектура пайплайнов, macOS-раннеры, SRE-подход.
- **[Incident Response для мобильных приложений](./incident-response-mobile.md)** — процедуры реагирования на инциденты, MTTR, postmortem.
- **[Security Scanning в Mobile CI/CD](./security-scanning-mobile.md)** — защита секретов, code signing verification.
