# kor

## Определения

**`kor`** — CLI-инструмент на Go для обнаружения и удаления неиспользуемых ресурсов в кластере Kubernetes. Помогает поддерживать чистоту кластера и сокращать затраты, выявляя ресурсы, не связанные с активными рабочими нагрузками.

## Основные концепции

### Поддерживаемые типы ресурсов

kor обнаруживает неиспользуемые ресурсы следующих типов:

| Тип ресурса | Описание |
| :--- | :--- |
| **ConfigMaps** | Конфигурационные данные, не используемые подами |
| **Secrets** | Секреты, не смонтированные в подах |
| **Services** | Сервисы без активных endpoint'ов |
| **Deployments** | Деплойменты без подов |
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

- **Широкий охват:** 20+ типов ресурсов Kubernetes
- **Мульти-namespace:** проверка всех или выбранных namespace'ов
- **CI/CD-интеграция:** ненулевой код выхода при обнаружении неиспользуемых ресурсов
- **Форматы вывода:** `table` (по умолчанию), `json`, `yaml`
- **Helm-установка:** запуск как CronJob или Deployment с метриками Prometheus
- **Исключения:** фильтрация по namespace'ам через флаги

### Установка

**Через Go:**

```bash
go install github.com/yonahd/kor@latest
```

**Через Homebrew (macOS/Linux):**

```bash
brew install kor
```

**Через krew:**

```bash
kubectl krew install kor
```

**Через Helm (CronJob/Deployment с метриками):**

```bash
helm repo add kor https://yonahd.github.io/kor
helm upgrade -i kor kor/kor -n kor --create-namespace
```

**Docker:**

```bash
docker run --rm -i yonahdissen/kor
```

## Практические сценарии

### Поиск неиспользуемых ресурсов

**Все типы ресурсов во всех namespace'ах:**

```bash
kor all
```

**Конкретные типы ресурсов (подкоманды):**

```bash
# ConfigMaps и Secrets
kor configmap secret

# Services и ServiceAccounts
kor service serviceaccount
```

**В конкретном namespace:**

```bash
kor all -n default
kor configmap -n kube-system
```

**С выводом в JSON:**

```bash
kor all -o json
```

### Удаление неиспользуемых ресурсов

**⚠️ Внимание:** перед удалением всегда запускайте без `--delete` для просмотра.

**Предварительный просмотр (без удаления):**

```bash
kor all --exclude-namespaces=kube-system,kube-public,kube-node-lease
```

**Удаление с интерактивным подтверждением (по умолчанию):**

```bash
kor all --delete
```

**Удаление без интерактивного подтверждения:**

```bash
kor all --delete --no-interactive
```

**Удаление конкретных типов:**

```bash
kor configmap secret --delete --no-interactive
```

### Исключение ресурсов

**Исключение namespace'ов:**

```bash
kor all --exclude-namespaces=kube-system,kube-public,kube-node-lease
```

**Исключение конкретных ресурсов по имени:**

```bash
kor configmap --exclude-namespaces=kube-system --exclude-resources=my-important-config
```

### Интеграция с CI/CD

**GitLab CI:**

```yaml
check-unused-resources:
  image: yonahdissen/kor:latest
  stage: test
  script:
    - kor all --exclude-namespaces=kube-system,kube-public
  allow_failure: true
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

**GitHub Actions:**

```yaml
name: Check Unused Resources
on:
  schedule:
    - cron: '0 2 * * 1'
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - name: Install kor
        run: |
          go install github.com/yonahd/kor@latest
      - name: Check unused resources
        run: |
          kor all --exclude-namespaces=kube-system,kube-public,kube-node-lease
        continue-on-error: true
```

### Автоматическая очистка (cron)

**Скрипт для регулярной очистки:**

```bash
#!/bin/bash
# /usr/local/bin/kor-cleanup.sh

LOG_FILE="/var/log/kor-cleanup.log"
EXCLUDE_NS="kube-system,kube-public,kube-node-lease"

echo "=== Kor cleanup started at $(date) ===" >> $LOG_FILE

# Просмотр (без удаления)
kor all --exclude-namespaces=$EXCLUDE_NS -o json >> $LOG_FILE 2>&1

# Фактическое удаление (раскомментировать для production)
# kor all --exclude-namespaces=$EXCLUDE_NS --delete --no-interactive >> $LOG_FILE 2>&1

echo "=== Kor cleanup finished at $(date) ===" >> $LOG_FILE
```

**Cron job (еженедельно):**

```bash
0 3 * * 0 /usr/local/bin/kor-cleanup.sh
```

## Дополнительная информация

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Kubernetes | 1.20+ | Проверено до 1.32 |
| kubectl | 1.20+ | Требуется для доступа к кластеру |
| Go | 1.21+ | Для сборки из исходников |

### Ограничения

- **Не удаляет ресурсы по умолчанию:** требуется явный флаг `--delete`
- **Ложные срабатывания:** некоторые ресурсы могут использоваться операторами или внешними системами
- **Не проверяет вложенные зависимости:** Secret может использоваться Init Container

### Лучшие практики

1. Всегда запускать без `--delete` перед фактическим удалением
2. Исключать системные namespace'ы (`kube-system`, `kube-public`)
3. Настраивать исключения для критических ресурсов
4. Запускать регулярно по расписанию для поддержания чистоты
5. Интегрировать с уведомлениями (Slack, email) для отчётов

### Смотрите также

- [ConfigMap](../Base/ConfigMap/pod_usage.md) — использование ConfigMap в подах.
- [Secrets](../Security/application_secrets_management.md) — управление секретами.
- [Официальный репозиторий GitHub: yonahd/kor](https://github.com/yonahd/kor) — исходный код и документация.
