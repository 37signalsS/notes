# Kor — поиск неиспользуемых ресурсов Kubernetes

## Определение

**`kor`** — CLI-инструмент на Go для обнаружения и удаления неиспользуемых (orphaned) ресурсов в кластере Kubernetes. Помогает поддерживать чистоту конфигурации, оптимизировать потребление ресурсов и сокращать затраты, выявляя объекты, которые не связаны с активными рабочими нагрузками.

Официальный репозиторий: [github.com/yonahd/kor](https://github.com/yonahd/kor)

**Актуальная версия:** v0.6.8.

---

## Основные концепции

### Принцип работы

Kor подключается к кластеру через kubeconfig и анализирует связи между ресурсами по их метаданным. Инструмент проверяет, какие ConfigMap смонтированы в подах, какие Service имеют активные Endpoints, какие Secret используются как переменные окружения, и так далее. Результатом является структурированный отчёт с указанием типа ресурса, namespace и имени — без конструктивных изменений кластера (по умолчанию).

Анализ связей выполняется за счёт перекрёстных ссылок между ресурсами:
- **ConfigMap / Secret** — проверяется монтирование в подах и использование как `env`/`envFrom`
- **Service** — проверяется наличие активных Endpoints
- **Deployment / StatefulSet / DaemonSet** — проверяется количество активных подов
- **PVC / PV** — проверяется привязка к подам
- **RBAC (Roles, Bindings, ServiceAccounts)** — проверяется существование соответствующих привязок
- **HPA** — проверяется наличие целевого объекта и доступность метрик

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
| **Pods** | Поды, находящиеся в статусе **CrashLoopBackOff** |
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
| **VolumeAttachments** | Вложения томов, не связанные с активными узлами или подами |
| **CRDs** | Custom Resource Definitions без созданных экземпляров |
| **Finalizers** | Ресурсы с ожидающими удаления finalizers |

### Ключевые особенности

- **Обнаружение CrashLoopBackOff:** автоматическое выявление подов, застрявших в цикле перезагрузки, что часто указывает на мусорные или некорректно настроенные ресурсы.
- **Масштабируемость:** проверка всех (all-namespaces) или конкретных пространств имен.
- **Интеграция с Prometheus:** возможность развертывания в виде Deployment/CronJob для экспорта метрик неиспользуемых ресурсов, что позволяет создавать алерты и дашборды в Grafana.
- **Метка исключения:** поддержка специальной метки `kor/used=true` для защиты ресурсов от обнаружения и удаления.
- **Причины (reason):** при использовании флага `--show-reason` инструмент указывает, почему конкретный ресурс считается неиспользуемым.
- **Безопасный режим (Dry-run):** по умолчанию инструмент только выводит список. Удаление происходит только при явном указании флага `--delete`.
- **Мультиконтекст:** поддержка флага `--context` для работы с конкретным контекстом кластера из kubeconfig.

### Метрики Prometheus

При развёртывании как Deployment (експортёр метрик) или через подкоманду `exporter` kor предоставляет следующие метрики:

| Метрика | Описание |
| :--- | :--- |
| `kor_unused_resources` | Количество неиспользуемых ресурсов по типу и namespace |
| `kor_total_unused_resources` | Общее количество неиспользуемых ресурсов в кластере |

Метрики доступны на порту `9000` по пути `/metrics`. Это позволяет интегрировать кор с Prometheus и строить алерты в Grafana, например: алерт при превышении порога неиспользуемых ConfigMap или Secret.

---

## Практические сценарии

### Установка

#### Бинарный файл (рекомендуется для стабильной версии)

Скачайте бинарный файл для вашей ОС со страницы [releases](https://github.com/yonahd/kor/releases) и добавьте в `PATH`:

```bash
# Linux x86_64
curl -L https://github.com/yonahd/kor/releases/download/v0.6.8/kor_linux_amd64 -o /usr/local/bin/kor
chmod +x /usr/local/bin/kor

# Linux ARM64
curl -L https://github.com/yonahd/kor/releases/download/v0.6.8/kor_linux_arm64 -o /usr/local/bin/kor
chmod +x /usr/local/bin/kor
```

#### Go (актуальная версия из main-ветки)

```bash
go install github.com/yonahd/kor@latest
```

#### Homebrew (macOS/Linux)

```bash
brew install kor
```

#### kubectl krew (плагин)

```bash
kubectl krew install kor
```

#### Windows

```powershell
# Chocolatey
choco install kor

# winget
winget install yonahd.kor
```

#### Сборка из исходников

```bash
git clone https://github.com/yonahd/kor.git
cd kor
go build main.go
# Бинарный файл появится в текущей директории; переместите в PATH
sudo mv main /usr/local/bin/kor
```

#### Docker (без установки на хост)

```bash
# Запуск с использованием локального kubeconfig
docker run --rm -i -v "$HOME/.kube/config:/root/.kube/config" yonahdissen/kor all

# Запуск с указанием контекста
docker run --rm -i -v "$HOME/.kube/config:/root/.kube/config" yonahdissen/kor all --context my-cluster
```

### Проверка установки

```bash
kor version
# → kor version v0.6.8
```

### Базовые команды

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

# RBAC-ресурсы
kor role clusterrole rolebinding clusterrolebinding

# Тома и хранилище
kor pvc pv storageclass
```

**С указанием причины (why this resource is unused):**

```bash
kor all --show-reason
```

**Вывод с группировкой по namespace:**

```bash
kor all --group-by=namespace
```

**Вывод с группировкой по типу ресурса:**

```bash
kor all --group-by=resource
```

### Фильтрация по пространству имен

```bash
# В конкретном namespace
kor all -n production

# Исключая системные пространства имен
kor all --exclude-namespaces=kube-system,kube-public,kube-node-lease
```

### Указание контекста кластера

```bash
# Использование конкретного контекста из kubeconfig
kor all --context my-cluster

# Просмотр доступных контекстов
kubectl config get-contexts
```

### Вывод в форматах для автоматизации

```bash
# Табличный вывод (по умолчанию)
kor all --output table

# JSON для обработки через jq
kor all --output json

# YAML для декларативного анализа
kor all --output yaml
```

**Пример фильтрации JSON через jq (поиск ConfigMap в production):**

```bash
kor all --output json | jq '.[] | select(.namespace == "production" and .type == "ConfigMap")'
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

**Исключение через метки в манифесте (рекомендуется):**

Добавление этой метки заставляет `kor` полностью игнорировать ресурс:

```yaml
metadata:
  labels:
    kor/used: "true"
```

**Исключение по имени:**

```bash
kor configmap --exclude-resources=my-safe-config,another-one
```

**Исключение по произвольным меткам (labels):**

```bash
kor all --exclude-labels="maintenance=true,critical=yes"
```

### Использование в кластере (In-Cluster)

Kor можно развернуть непосредственно в кластере как Deployment (для экспортёра метрик Prometheus) или как CronJob (для периодических проверок).

#### Deployment (экспортёр метрик)

```bash
helm upgrade -i kor kor/kor \
    --namespace kor \
    --create-namespace \
    --set deployment.enabled=true \
    --set serviceMonitor.enabled=true  # если установлен Prometheus Operator
```

#### CronJob (периодическая проверка)

```bash
helm upgrade -i kor kor/kor \
    --namespace kor \
    --create-namespace \
    --set cronJob.enabled=true \
    --set cronJob.schedule="0 3 * * *" \
    --set slackWebhookUrl="https://hooks.slack.com/services/XXX"  # опционально
```

**Пример манифеста CronJob без Helm:**

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: kor-audit
  namespace: kor
spec:
  schedule: "0 3 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: kor
          containers:
            - name: kor
              image: yonahdissen/kor:latest
              command: ["kor", "all", "--output", "json", "--exclude-namespaces=kube-system,kube-public"]
          restartPolicy: OnFailure
```

### Использование в CI/CD

**GitHub Actions (еженедельная проверка):**

```yaml
name: K8s Resource Audit
on:
  schedule:
    - cron: '0 0 * * 1'
  workflow_dispatch:
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - name: Install Kor
        run: go install github.com/yonahd/kor@latest
      - name: Scan Cluster
        env:
          KUBECONFIG: ${{ secrets.KUBECONFIG }}
        run: |
          kor all --exclude-namespaces=kube-system,kube-public --output json > kor-report.json
          # Проверка: если есть неиспользуемые ресурсы — вывод предупреждения
          UNUSED_COUNT=$(jq '. | length' kor-report.json)
          if [ "$UNUSED_COUNT" -gt 0 ]; then
            echo "::warning::Found $UNUSED_COUNT unused resources"
            jq -r '.[] | "\(.type): \(.name) in \(.namespace)"' kor-report.json
          fi
      - name: Upload Report
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: kor-report
          path: kor-report.json
```

**GitLab CI (еженедельный аудит):**

```yaml
kor-audit:
  stage: audit
  image: golang:latest
  script:
    - go install github.com/yonahd/kor@latest
    - kor all --exclude-namespaces=kube-system,kube-public --output json > kor-report.json
    - |
      UNUSED_COUNT=$(jq '. | length' kor-report.json)
      echo "Found $UNUSED_COUNT unused resources"
      jq -r '.[] | "  - \(.type): \(.name) (\(.namespace))"' kor-report.json
  artifacts:
    paths:
      - kor-report.json
    expire_in: 30 days
  only:
    - schedules
```

### Автоматизация очистки (Bash + Cron)

**Скрипт для регулярного аудита и логгирования:**

```bash
#!/bin/bash
# /usr/local/bin/kor-audit.sh

LOG_FILE="/var/log/kor-audit.log"
EXCLUDE_NS="kube-system,kube-public,kube-node-lease"
REPORT_DIR="/var/log/kor-reports"
DATE=$(date +%F)

mkdir -p "$REPORT_DIR"

echo "=== Kor audit started: $(date) ===" >> "$LOG_FILE"

# Сохранение отчета в JSON для истории
kor all --exclude-namespaces="$EXCLUDE_NS" --output json > "$REPORT_DIR/kor-report-$DATE.json"

# Вывод в лог в табличном виде
kor all --exclude-namespaces="$EXCLUDE_NS" >> "$LOG_FILE" 2>&1

# Очистка отчётов старше 30 дней
find "$REPORT_DIR" -name "kor-report-*.json" -mtime +30 -delete 2>/dev/null

echo "=== Kor audit finished: $(date) ===" >> "$LOG_FILE"
```

**Cron job (ежедневно в 03:00):**

```bash
0 3 * * * /usr/local/bin/kor-audit.sh
```

---

## Дополнительная информация

### Полный список подкоманд

| Подкоманда | Описание |
| :--- | :--- |
| `all` | Все неиспользуемые ресурсы для указанного namespace или всех |
| `configmap` | Неиспользуемые ConfigMaps |
| `secret` | Неиспользуемые Secrets |
| `service` | Неиспользуемые Services |
| `serviceaccount` | Неиспользуемые ServiceAccounts |
| `deployment` | Неиспользуемые Deployments |
| `statefulset` | Неиспользуемые StatefulSets |
| `daemonset` | Неиспользуемые DaemonSets |
| `replicaset` | Неиспользуемые ReplicaSets |
| `pod` | Неиспользуемые Pods (CrashLoopBackOff и др.) |
| `job` | Неиспользуемые Jobs |
| `role` | Неиспользуемые Roles |
| `clusterrole` | Неиспользуемые ClusterRoles |
| `rolebinding` | Неиспользуемые RoleBindings |
| `clusterrolebinding` | Неиспользуемые ClusterRoleBindings |
| `hpa` | Неиспользуемые HPAs |
| `ingress` | Неиспользуемые Ingress |
| `pvc` | Неиспользуемые PersistentVolumeClaims |
| `pv` | Неиспользуемые PersistentVolumes |
| `storageclass` | Неиспользуемые StorageClasses |
| `priorityclass` | Неиспользуемые PriorityClasses |
| `pdb` | Неиспользуемые PodDisruptionBudgets |
| `networkpolicy` | Неиспользуемые NetworkPolicies |
| `crd` | Неиспользуемые Custom Resource Definitions |
| `volumeattachment` | Неиспользуемые VolumeAttachments |
| `finalizer` | Ресурсы с ожидающими удаления finalizers |
| `exporter` | Экспорт метрик Prometheus |
| `version` | Печать версии kor |

### Полный список флагов

| Флаг | Описание |
| :--- | :--- |
| `--delete` | Удалить неиспользуемые ресурсы (вместо только вывода) |
| `--no-interactive` | Отключить интерактивное подтверждение при `--delete` |
| `--output` | Формат вывода: `table`, `json`, `yaml` |
| `--exclude-namespaces` | Исключить namespace через запятую |
| `--exclude-resources` | Исключить конкретные ресурсы по имени через запятую |
| `--exclude-labels` | Исключить ресурсы по меткам (ключ=значение через запятую) |
| `--namespace` / `-n` | Ограничить сканирование конкретным namespace |
| `--context` | Использовать конкретный контекст из kubeconfig |
| `--group-by` | Группировка результатов: `namespace` или `resource` |
| `--show-reason` | Показать причину, по которой ресурс считается неиспользуемым |

### Требования к среде

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Kubernetes | 1.20+ | Проверено на версиях до 1.32 |
| kubectl | 1.20+ | Необходим для аутентификации в кластере |
| Go | 1.21+ | Требуется для установки через `go install` |

### Ограничения и риски

- **Динамическое использование:** некоторые секреты могут запрашиваться приложением через API напрямую (без монтирования), что `kor` может ошибочно пометить как неиспользуемые.
- **Внешние зависимости:** ресурсы могут использоваться внешними инструментами (например, внешними Ingress-контроллерами или скриптами автоматизации вне K8s).
- **Sidecar-контейнеры:** ресурсы, внедряемые через вебхуки (например, Istio sidecars), могут не всегда корректно учитываться при проверке зависимостей.
- **Сетевые политики:** NetworkPolicy помечается как неиспользуемая, если она не ссылается на конкретные поды через селекторы, даже если политика применяется ко всем подам в namespace (через пустой `podSelector`).
- **CRDs с вебхуками:** CRD может использоваться вебхуком admission-контроллера, что kor не учитывает при анализе.

### Типичные ошибки и их решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `error: unable to connect to cluster` | kubeconfig не настроен или кластер недоступен | Проверьте `kubectl cluster-info`; убедитесь, что kubeconfig указан верно |
| `error: no such host` | DNS не резолвит API-сервер | Проверьте сетевую конфигурацию и DNS |
| `panic: runtime error` | Некорректная версия кор / баг | Используйте актуальную версию; проверьте [issues](https://github.com/yonahd/kor/issues) |
| Ложные срабатывания на ConfigMap | ConfigMap используется через API напрямую (без монтирования) | Добавьте метку `kor/used: "true"` для защиты |
| Ложные срабатывания на Service | Service используется внешним Ingress-контроллером | Добавьте метку `kor/used: "true"` |

### Лучшие практики

1. **Dry-run First:** никогда не используйте `--delete` в первом запуске на новом кластере.
2. **Whitelist-подход:** всегда исключайте системные пространства имен (`kube-system`, `kube-public`).
3. **Метки для защиты:** используйте специальную метку `kor/used=true` или флаг `--exclude-labels` для пометки ресурсов, которые должны существовать "про запас" или для редких задач.
4. **Мониторинг:** используйте Helm-чарт для развертывания экспортера и визуализации "мусора" в Grafana.
5. **Бекап:** перед массовым удалением экспортируйте список ресурсов в JSON или YAML.
6. **Регулярность:** настройте CronJob (еженедельно или ежедневно) для автоматического аудита.
7. **Интеграция с GitOps:** сохраняйте отчёты в артефакты CI/CD для отслеживания динамики.
8. **Исключение CRDs с вебхуками:** добавляйте метку `kor/used: "true"` для CRD, которые используются admission-контроллерами.

### Смотрите также

- [ConfigMap](../Base/ConfigMap/pod_usage.md) — использование конфигураций.
- [Управление секретами](../Security/application_secrets_management.md) — безопасность данных.
- [GitHub: yonahd/kor](https://github.com/yonahd/kor) — исходный код и обновления.
- [KorPro](https://korpro.io) — веб-платформа для управления ресурсами.
