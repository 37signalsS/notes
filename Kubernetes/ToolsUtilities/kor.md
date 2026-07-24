# Kor — поиск неиспользуемых ресурсов Kubernetes

## Определение

**`kor`** — CLI-инструмент на Go для обнаружения и удаления неиспользуемых (orphaned) ресурсов в кластере Kubernetes. Помогает поддерживать чистоту конфигурации, оптимизировать потребление ресурсов и сокращать затраты, выявляя объекты, которые не связаны с активными рабочими нагрузками.

## Основные концепции

### Поддерживаемые типы ресурсов

Инструмент сканирует кластер на наличие следующих неиспользуемых ресурсов:

| Тип ресурса | Описание |
| :--- | :--- |
| **ConfigMaps** | Конфигурационные данные, не используемые подами |
| **Secrets** | Секреты, не смонтированные в подах и не используемые как переменные окружения |
| **Services** | Сервисы без активных endpoint-ов |
| **Deployments** | Деплойменты без активных подов |
| **StatefulSets** | StatefulSets без активных подов |
| **DaemonSets** | DaemonSets без активных подов |
| **ReplicaSets** | ReplicaSets с 0 реплик и без владельцев |
| **Pods** | Поды, находящиеся в статусе **CrashLoopBackOff** (новый функционал) |
| **Jobs** | Завершенные или "осиротевшие" задания |
| **Roles / ClusterRoles** | RBAC-роли без соответствующих привязок (RoleBindings) |
| **RoleBindings / ClusterRoleBindings** | Привязки без соответствующих ролей или субъектов |
| **ServiceAccounts** | Учетные записи без привязок и не используемые подами |
| **HPA** | Horizontal Pod Autoscaler без целевых объектов или с отсутствующими метриками |
| **Ingress** | Ingress без соответствующих бэкенд-сервисов |
| **PVC** | PersistentVolumeClaims, не привязанные к подам |
| **PV** | PersistentVolumes, не привязанные к PVC (статус Available или Released) |
| **StorageClasses** | Классы хранения, не используемые ни одним PV или PVC |
| **PriorityClasses** | Классы приоритета, не назначенные ни одному поду |
| **PDB** | PodDisruptionBudgets без целевых подов |
| **NetworkPolicies** | Сетевые политики, не связанные с существующими подами |
| **CRDs** | Custom Resource Definitions без созданных экземпляров |

### Ключевые особенности

- **CrashLoopBackOff Detection:** автоматическое выявление подов, застрявших в цикле перезагрузки, что часто указывает на мусорные или некорректно настроенные ресурсы.
- **Масштабируемость:** проверка всех (all-namespaces) или конкретных пространств имен.
- **Prometheus Integration:** возможность развертывания в виде Deployment/CronJob для экспорта метрик неиспользуемых ресурсов, что позволяет создавать алерты и дашборды в Grafana.
- **KorPro (SaaS):** расширенная версия для управления несколькими кластерами, анализа потенциальной экономии (Cost Analysis) и оценки состояния ресурсов (Health Scores) через веб-интерфейс.
- **Безопасность (Dry-run):** по умолчанию инструмент только выводит список. Удаление происходит только при явном указании флага `--delete`.

### Установка

**Через Go (рекомендуется для актуальной версии):**

```bash
go install github.com/yonahd/kor@latest
```

**Через Homebrew (macOS/Linux):**

```bash
brew install kor
```

**Через krew (как плагин kubectl):**

```bash
kubectl krew install kor
```

**Через Helm (для мониторинга внутри кластера):**

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

**Сканирование всех поддерживаемых типов во всех пространствах имен:**

```bash
kor all
```

**Сканирование конкретных категорий:**

```bash
# Только конфигурации и секреты
kor configmap secret

# Сетевые ресурсы и сервисные аккаунты
kor service serviceaccount ingress hpa
```

**Фильтрация по пространству имен:**

```bash
# В конкретном namespace
kor all -n production

# Исключая системные пространства имен
kor all --exclude-namespaces=kube-system,kube-public,kube-node-lease
```

**Вывод в форматах для автоматизации:**

```bash
# Табличный вывод (по умолчанию)
kor all --output table

# JSON для обработки через jq
kor all --output json
```

### Удаление ресурсов

**Внимание:** всегда делайте запуск без `--delete` для аудита перед очисткой.

**Удаление с подтверждением (интерактивно):**

```bash
kor all --delete
```

**Удаление без подтверждения (для скриптов):**

```bash
kor all --delete --no-interactive
```

**Точечное удаление по типам:**

```bash
kor configmap secret --delete --no-interactive -n dev
```

### Исключение ресурсов

**Исключение по имени:**

```bash
kor configmap --exclude-resources=my-safe-config,another-one
```

**Исключение по меткам (labels):**

```bash
kor all --exclude-labels="maintenance=true,critical=yes"
```

### Интеграция с CI/CD

**GitHub Actions (еженедельная проверка):**

```yaml
name: K8s Resource Audit
on:
  schedule:
    - cron: '0 0 * * 1' # Каждый понедельник в полночь
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - name: Install Kor
        run: go install github.com/yonahd/kor@latest
      - name: Scan Cluster
        run: |
          kor all --exclude-namespaces=kube-system,kube-public --output json
        continue-on-error: true
```

### Автоматизация очистки (Bash + Cron)

**Скрипт для регулярного аудита и логгирования:**

```bash
#!/bin/bash
# /usr/local/bin/kor-audit.sh

LOG_FILE="/var/log/kor-audit.log"
EXCLUDE_NS="kube-system,kube-public,kube-node-lease"

echo "=== Kor audit started: $(date) ===" >> $LOG_FILE

# Сохранение отчета в JSON для истории
kor all --exclude-namespaces=$EXCLUDE_NS --output json > "/var/log/kor-report-$(date +%F).json"

# Вывод в лог в табличном виде
kor all --exclude-namespaces=$EXCLUDE_NS >> $LOG_FILE 2>&1

echo "=== Kor audit finished: $(date) ===" >> $LOG_FILE
```

**Cron job (ежедневно в 03:00):**

```bash
0 3 * * * /usr/local/bin/kor-audit.sh
```

## Дополнительная информация

### Требования к среде

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Kubernetes | 1.20+ | Проверено на версиях до 1.32 |
| kubectl | 1.20+ | Необходим для аутентификации в кластере |
| Go | 1.21+ | Требуется для установки через go install |

### Ограничения и риски

- **Динамическое использование:** некоторые секреты могут запрашиваться приложением через API напрямую (без монтирования), что `kor` может ошибочно пометить как неиспользуемые.
- **Внешние зависимости:** ресурсы могут использоваться внешними инструментами (например, внешними Ingress-контроллерами или скриптами автоматизации вне K8s).
- **Sidecar-контейнеры:** ресурсы, внедряемые через вебхуки (например, Istio sidecars), могут не всегда корректно учитываться при проверке зависимостей.

### Лучшие практики

1. **Dry-run First:** никогда не используйте `--delete` в первом запуске на новом кластере.
2. **Whitelist-подход:** всегда исключайте системные пространства имен (`kube-system`, `kube-public`).
3. **Метки для защиты:** используйте `--exclude-labels` для пометки ресурсов, которые должны существовать "про запас" или для редких задач.
4. **Мониторинг:** используйте Helm-чарт для развертывания экспортера и визуализации "мусора" в Grafana.
5. **Бекап:** перед массовым удалением экспортируйте список ресурсов в JSON.

### Смотрите также

- [ConfigMap](../Base/ConfigMap/pod_usage.md) — использование конфигураций.
- [Управление секретами](../Security/application_secrets_management.md) — безопасность данных.
- [GitHub: yonahd/kor](https://github.com/yonahd/kor) — исходный код и обновления.
- [KorPro](https://korpro.io) — веб-платформа для управления ресурсами.
