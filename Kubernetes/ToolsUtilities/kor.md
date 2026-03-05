# kor

## 1. Определения

**`kor`** — это инструмент командной строки (CLI) на Go для обнаружения и удаления неиспользуемых ресурсов в кластере Kubernetes. Он помогает поддерживать чистоту в кластере и сокращать затраты, выявляя ресурсы, не связанные с активными рабочими нагрузками.

## 2. Основные концепции

### Поддерживаемые типы ресурсов

kor обнаруживает неиспользуемые ресурсы следующих типов:

| Тип ресурса | Описание |
| :--- | :--- |
| **ConfigMaps** | Конфигурационные данные, не используемые подами |
| **Secrets** | Секреты, не смонтированные в подах |
| **Services** | Сервисы без активных endpoint'ов |
| **Deployments** | Деплойменты без подов (редко) |
| **StatefulSets** | StatefulSets без подов |
| **DaemonSets** | DaemonSets без активных подов |
| **Roles/ClusterRoles** | RBAC-роли без привязок |
| **RoleBindings/ClusterRoleBindings** | Привязки без соответствующих ролей |
| **ServiceAccounts** | Учётные записи без привязок |
| **HPA** | Horizontal Pod Autoscaler без целевых объектов |
| **Ingress** | Ingress без соответствующих сервисов |
| **PVC** | PersistentVolumeClaims без привязанных PV |
| **CRDs** | Custom Resource Definitions без экземпляров |

### Ключевые особенности

- **Широкий охват:** Поддерживает 20+ типов ресурсов Kubernetes
- **Мульти-namespace:** Проверка всех namespace'ов или выборочных
- **Интеграция с CI/CD:** Возвращает ненулевой код выхода при обнаружении неиспользуемых ресурсов
- **JSON-вывод:** Поддержка формата JSON для программной обработки
- **Dry-run:** Безопасный предварительный просмотр перед удалением
- **Исключения:** Поддержка списков исключений через флаги или конфиг

### Установка

**Через Go (рекомендуется):**

```bash
go install github.com/yonahd/kor/cmd/kor@latest
```

**Через Homebrew (macOS/Linux):**

```bash
brew install kor
```

**Бинарный файл:**

```bash
# Загрузка для Linux amd64
curl -LO https://github.com/yonahd/kor/releases/latest/download/kor_linux_amd64.tar.gz
tar -xzf kor_linux_amd64.tar.gz
sudo mv kor /usr/local/bin/
chmod +x /usr/local/bin/kor
```

**Docker:**

```bash
docker run --rm -v ~/.kube:/root/.kube ghcr.io/yonahd/kor --all
```

## 3. Практические сценарии

### 3.1. Поиск неиспользуемых ресурсов

**Все типы ресурсов во всех namespace'ах:**

```bash
kor --all
```

**Конкретные типы ресурсов:**

```bash
# ConfigMaps и Secrets
kor configmap secret

# Services и ServiceAccounts
kor service serviceaccount
```

**В конкретном namespace:**

```bash
kor --all -n default
kor configmap -n kube-system
```

**С выводом в JSON:**

```bash
kor --all -o json
```

### 3.2. Удаление неиспользуемых ресурсов

**⚠️ Внимание:** Перед удалением всегда выполняйте dry-run!

**Dry-run (предварительный просмотр):**

```bash
kor --all --delete --dry-run
```

**Фактическое удаление:**

```bash
# Удаление всех найденных неиспользуемых ресурсов
kor --all --delete

# Удаление конкретных типов
kor configmap secret --delete
```

**Удаление с подтверждением:**

```bash
# Интерактивное подтверждение (если поддерживается версией)
kor --all --delete --interactive
```

### 3.3. Исключение ресурсов

**Исключение namespace'ов:**

```bash
# Исключение системных namespace'ов
kor --all --exclude-namespaces=kube-system,kube-public,kube-node-lease
```

**Исключение конкретных ресурсов по имени:**

```bash
# Исключение ConfigMap по имени
kor configmap --exclude-namespaces=kube-system --exclude-resources=my-important-config
```

**Исключение через лейблы:**

```bash
# Исключение ресурсов с определённым лейблом
kor --all --exclude-labels=protected=true
```

### 3.4. Интеграция с CI/CD

**GitLab CI пример:**

```yaml
check-unused-resources:
  image: ghcr.io/yonahd/kor:latest
  stage: test
  script:
    - echo "Checking for unused Kubernetes resources..."
    - kor --all --exclude-namespaces=kube-system,kube-public
  allow_failure: true  # Не блокировать пайплайн, только предупреждение
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"  # Запуск по расписанию
```

**GitHub Actions пример:**

```yaml
name: Check Unused Resources
on:
  schedule:
    - cron: '0 2 * * 1'  # Каждый понедельник в 02:00
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install kor
        run: |
          curl -LO https://github.com/yonahd/kor/releases/latest/download/kor_linux_amd64.tar.gz
          tar -xzf kor_linux_amd64.tar.gz
          sudo mv kor /usr/local/bin/
      - name: Check unused resources
        run: |
          kor --all --exclude-namespaces=kube-system,kube-public,kube-node-lease
        continue-on-error: true
```

### 3.5. Автоматическая очистка (cron)

**Скрипт для регулярной очистки:**

```bash
#!/bin/bash
# /usr/local/bin/kor-cleanup.sh

LOG_FILE="/var/log/kor-cleanup.log"
EXCLUDE_NS="kube-system,kube-public,kube-node-lease"

echo "=== Kor cleanup started at $(date) ===" >> $LOG_FILE

# Dry-run для логирования
kor --all --exclude-namespaces=$EXCLUDE_NS --delete --dry-run >> $LOG_FILE 2>&1

# Фактическое удаление (раскомментировать для production)
# kor --all --exclude-namespaces=$EXCLUDE_NS --delete >> $LOG_FILE 2>&1

echo "=== Kor cleanup finished at $(date) ===" >> $LOG_FILE
```

**Cron job (еженедельно):**

```bash
# Добавление в crontab
0 3 * * 0 /usr/local/bin/kor-cleanup.sh
```

## 4. Дополнительная информация

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Kubernetes | 1.20+ | Проверено до 1.32 |
| kubectl | 1.20+ | Требуется для доступа к кластеру |
| Go | 1.21+ | Для сборки из исходников |

### Ограничения

- **Не удаляет ресурсы по умолчанию:** Требуется явный флаг `--delete`
- **Ложные срабатывания:** Некоторые ресурсы могут использоваться операторами или внешними системами
- **Не проверяет вложенные зависимости:** Например, Secret может использоваться Init Container

### Лучшие практики

1. **Всегда выполняйте dry-run** перед фактическим удалением
2. **Исключайте системные namespace'ы** (`kube-system`, `kube-public`)
3. **Настройте исключения** для критических ресурсов через лейблы
4. **Запускайте регулярно** по расписанию для поддержания чистоты
5. **Интегрируйте с уведомлениями** (Slack, email) для отчётов

### Связанные документы

- **[ConfigMap](../Base/ConfigMap/pod_usage.md)** — использование ConfigMap в подах
- **[Secrets](../Security/application_secrets_management.md)** — управление секретами
- **[RBAC](../Security/rbac/rbac_overview.md)** — роли и привязки

### Репозиторий и документация

- [GitHub: yonahd/kor](https://github.com/yonahd/kor)
- [Документация kor](https://github.com/yonahd/kor#readme)
