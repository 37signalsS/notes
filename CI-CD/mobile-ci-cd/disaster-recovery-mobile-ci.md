# Disaster Recovery для Mobile CI/CD

## Определения

**Disaster Recovery (DR)** — процесс восстановления инфраструктуры и данных после катастрофических сбоев (потеря.macOS-раннера, повреждение Keychain-сервиса, потеря Match-репозитория).

**RTO (Recovery Time Objective)** — максимальное допустимое время восстановления. Для Mobile CI/CD: < 2 часа.

**RPO (Recovery Point Objective)** — максимальная допустимая потеря данных. Для Mobile CI/CD: < 1 часа (последний бэкап).

**Runbook** — пошаговая инструкция для восстановления после определенного типа сбоя.

---

## Базовые концепции

### Компоненты Mobile CI/CD, требующие DR

| Компонент | RTO | RPO | Критичность |
|:---|:---|:---|:---|
| **macOS-раннеры** | 2 часа | 0 (stateless) | Высокая |
| **Match-репозиторий** | 1 час | 1 часа | Критическая |
| **Keychain-сервис** | 1 час | 0 (ephemeral) | Критическая |
| **CI/CD конфигурация** | 15 минут | 0 (Git) | Средняя |
| **Fastlane конфигурация** | 15 минут | 0 (Git) | Средняя |
| **Секреты (API Keys)** | 30 минут | 0 (Secrets) | Критическая |

### Типы сбоев

| Тип | Пример | Влияние |
|:---|:---|:---|
| **Hardware Failure** | Mac-раннер сломался | Нет сборок |
| **Software Corruption** | Keychain поврежден | Нет подписи |
| **Data Loss** | Match-репозиторий потерян | Нет сертификатов |
| **Network Outage** | GitLab недоступен | Нет деплоев |
| **Security Breach** | API Keys скомпрометированы | Полная остановка |

---

## Практическая реализация

### 1. Backup Match-репозитория

**Автоматический бэкап:**
```bash
#!/bin/bash
# backup_match_repo.sh

MATCH_REPO="git@github.com:company/match-repo.git"
BACKUP_REPO="git@github.com:company/match-backup.git"
BACKUP_DIR="/tmp/match-backup-$(date +%Y%m%d)"

# Клонирование основного репозитория
git clone "$MATCH_REPO" "$BACKUP_DIR"

# Push в backup репозиторий
cd "$BACKUP_DIR"
git remote add backup "$BACKUP_REPO"
git push backup main

# Очистка
rm -rf "$BACKUP_DIR"

echo "Backup completed: $(date)"
```

**Cron job (ежедневный бэкап):**
```bash
# /etc/crontab
0 2 * * * /path/to/backup_match_repo.sh >> /var/log/match-backup.log 2>&1
```

### 2. Backup Keychain-сервиса

**Fastlane Keychain Backup:**
```ruby
# fastlane/actions/backup_keychain.rb
module Fastlane
  module Actions
    class BackupKeychain < Action
      def self.run(params)
        keychain_name = params[:keychain_name]
        backup_path = params[:backup_path]
        
        # Экспорт keychain
        system("security export -k #{keychain_name} -t pkcs12 -o #{backup_path}/keychain_$(date +%Y%m%d).p12 -P ''")
        
        # Шифрование backup
        system("gpg --symmetric --cipher-algo AES256 #{backup_path}/keychain_$(date +%Y%m%d).p12")
        
        UI.success("Keychain backup created: #{backup_path}")
      end

      def self.available_options
        [
          FastlaneCore::ConfigItem.new(key: :keychain_name, description: "Keychain name"),
          FastlaneCore::ConfigItem.new(key: :backup_path, description: "Backup directory")
        ]
      end
    end
  end
end
```

### 3. Recovery Procedures

**Runbook: macOS-раннер сломался**

```bash
# 1. Проверка статуса раннера
gitlab-runner verify

# 2. Регистрация нового раннера
gitlab-runner register \
  --url "https://gitlab.company.com" \
  --token "$RUNNER_TOKEN" \
  --executor "shell" \
  --tag-list "ios,macos" \
  --description "Mac Mini M2 - $(hostname)"

# 3. Установка зависимостей
xcode-select --install
brew install fastlane

# 4. Верификация
gitlab-runner verify
xcodebuild -version
fastlane --version
```

**Runbook: Match-репозиторий потерян**

```bash
# 1. Восстановление из backup
git clone "git@github.com:company/match-backup.git" /tmp/match-recovery

# 2. Переименование в основной репозиторий
cd /tmp/match-recovery
git remote rename origin backup
git remote add origin "git@github.com:company/match-repo.git"
git push origin main

# 3. Проверка
fastlane match appstore --readonly

# 4. Очистка
rm -rf /tmp/match-recovery
```

**Runbook: Keychain-сервис поврежден**

```bash
# 1. Удаление поврежденного keychain
security delete-keychain ci_build.keychain

# 2. Создание нового keychain
security create-keychain -p "$KEYCHAIN_PASSWORD" ci_build.keychain
security set-keychain-settings -lut 21600 ci_build.keychain
security unlock-keychain -p "$KEYCHAIN_PASSWORD" ci_build.keychain

# 3. Импорт сертификатов из backup
security import /path/to/backup/certificates.p12 \
  -k ci_build.keychain \
  -P "" \
  -T /usr/bin/codesign \
  -T /usr/bin/security

# 4. Настройка ACL
security set-key-partition-list -S apple-tool:,apple:,codesign: \
  -s -k "$KEYCHAIN_PASSWORD" ci_build.keychain

# 5. Проверка
security find-identity -v -p codesigning ci_build.keychain
```

### 4. Fastlane Recovery Actions

**Полное восстановление окружения:**
```ruby
# fastlane/actions/recover_ci_environment.rb
module Fastlane
  module Actions
    class RecoverCIEnvironment < Action
      def self.run(params)
        # 1. Проверка и восстановление keychain
        unless system("security find-identity -v -p codesigning")
          UI.important("Keychain not found, recovering...")
          Actions.create_keychain
        end
        
        # 2. Проверка и восстановление Match
        unless system("fastlane match appstore --readonly")
          UI.important("Match not working, recovering...")
          Actions.recover_match
        end
        
        # 3. Проверка зависимостей
        unless system("bundle check")
          UI.important("Dependencies not installed...")
          system("bundle install")
        end
        
        UI.success("CI environment recovered successfully")
      end

      def self.create_keychain
        system("security create-keychain -p '' ci_build.keychain")
        system("security unlock-keychain -p '' ci_build.keychain")
      end

      def self.recover_match
        # Восстановление из backup
        system("git clone git@github.com:company/match-backup.git /tmp/match-recovery")
        system("cd /tmp/match-recovery && git push origin main")
        system("rm -rf /tmp/match-recovery")
      end
    end
  end
end
```

### 5. DR Testing

**Регулярные учения:**
```yaml
# .github/workflows/dr-test.yml
name: DR Test

on:
  schedule:
    - cron: '0 0 1 * *'  # Ежемесячно

jobs:
  dr_test:
    runs-on: macos-14
    steps:
      - name: Backup Test
        run: |
          # Тест бэкапа match-репозитория
          ./scripts/backup_match_repo.sh
      
      - name: Recovery Test
        run: |
          # Тест восстановления
          ./scripts/test_recovery.sh
      
      - name: Cleanup
        run: |
          # Очистка после теста
          ./scripts/cleanup_dr_test.sh
      
      - name: Report
        if: always()
        run: |
          # Генерация отчета
          ./scripts/generate_dr_report.sh
```

---

## Дополнительная информация

### Best Practices

1. **Automated Backups:** Настройте автоматические бэкапы всех критических компонентов.
2. **Regular Testing:** Проводите DR-учения ежемесячно.
3. **Documentation:** Документируйте все процедуры восстановления.
4. **Monitoring:** Отслеживайте здоровье всех компонентов.
5. **Redundancy:** Используйте резервные раннеры и хранилища.

### Cost Considerations

| Компонент | Стоимость бэкапа | Стоимость восстановления |
|:---|:---|:---|
| **macOS-раннер** | $0 (open-source) | $0.08-0.12/min (GitHub-hosted) |
| **Match-репозиторий** | $0 (Git) | Время разработчика |
| **Keychain** | $0 (local) | Время разработчика |
| **Секреты** | $0 (Secrets) | $0 ( Secrets management) |

### Automation Scripts

**Полный набор скриптов для DR:**
```bash
#!/bin/bash
# dr_scripts.sh

# Бэкап
backup_all() {
  ./backup_match_repo.sh
  ./backup_keychain.sh
  ./backup_secrets.sh
}

# Восстановление
recover_all() {
  ./recover_match_repo.sh
  ./recover_keychain.sh
  ./recover_secrets.sh
}

# Тестирование
test_recovery() {
  ./test_match_recovery.sh
  ./test_keychain_recovery.sh
  ./test_secrets_recovery.sh
}

case "$1" in
  backup) backup_all ;;
  recover) recover_all ;;
  test) test_recovery ;;
  *) echo "Usage: $0 {backup|recover|test}" ;;
esac
```

### См. также:
*   **[Mobile CI/CD Overview](./index.md)**
*   **[Incident Response](./incident-response-mobile.md)**
*   **[Security Scanning](./security-scanning-mobile.md)**
*   **[Feature Flags](./feature-flags-mobile.md)**
