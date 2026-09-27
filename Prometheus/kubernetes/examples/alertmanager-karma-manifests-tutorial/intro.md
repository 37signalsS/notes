# Alertmanager + Karma в Kubernetes: Введение

## Определения

**Alertmanager + Karma в Kubernetes** — практическое руководство по развёртыванию стека управления оповещениями (Alertmanager + Karma) в кластере Kubernetes с использованием стандартных манифестов (StatefulSet, Deployment, ConfigMap, Secret, Service, Ingress). В отличие от автоматизированного развёртывания через Helm-чарты или Оператор, данный подход предоставляет полный контроль над каждым ресурсом и наглядно демонстрирует паттерны безопасного управления конфигурациями и секретами. Подход совместим с GitOps-процессами: все манифесты являются декларативными и могут храниться в репозитории.

> **См. также:** [Alertmanager — общий обзор](../../../alertmanager.md), [Дашборд Karma](../../../karma_dashboard.md).

---

## Основные концепции

### Ключевые особенности подхода

| Особенность | Описание |
| :--- | :--- |
| **StatefulSet для Alertmanager** | Обеспечивает стабильный сетевой идентификатор (например, `alertmanager-0`) и поддержку постоянного хранилища через `volumeClaimTemplates` для сохранения состояния silences и базы данных уведомлений. |
| **Управление секретами** | Рассматривается два подхода: классический с `init-container` (шаблонизация конфига) и современный нативный (Alertmanager 0.27+), позволяющий использовать `${ENV_VAR}` непосредственно в `alertmanager.yml`. |
| **Декларативные шаблоны** | Использование ConfigMap для хранения `alertmanager.yml` и Go-templates (`.tmpl`) позволяет версионировать логику уведомлений отдельно от манифестов инфраструктуры. |
| **Интеграция с Telegram** | Использование встроенного `telegram_configs` (v0.24+) для прямой отправки уведомлений, что упрощает архитектуру и исключает необходимость в `alertmanager-bot`. |
| **Karma как агрегатор** | Развёртывание Karma в режиме агрегатора позволяет объединять алерты из нескольких независимых инстансов Alertmanager (например, из разных кластеров) в едином интерфейсе. |

### Архитектура решения

```text
┌─────────────────────────────────────────────────────────────┐
│                        Kubernetes                           │
│                                                             │
│  ┌─────────────────────────┐      ┌──────────────────────┐  │
│  │  Alertmanager           │      │  Karma               │  │
│  │  (StatefulSet)          │      │  (Deployment)        │  │
│  │  • Native Env Var / Init│<─────│  • ConfigMap (YAML)  │  │
│  │  • ConfigMap (Templates)│      │  • Stateless Pod     │  │
│  │  • PVC (Data Storage)   │      │  • Service           │  │
│  │  • Service (Port 9093)  │      └──────────────────────┘  │
│  └─────────────────────────┘                                │
│               ▲                                             │
│               │ (Alerts)                                    │
│  ┌─────────────────────────┐      ┌──────────────────────┐  │
│  │  Prometheus             │      │  Ingress Controller  │  │
│  │  (Внешний или в кластере)──────▶  • alertmanager.local│  │
│  └─────────────────────────┘      │  • karma.local        │  │
│                                   └──────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Принципы работы компонентов

**StatefulSet и Gossip-протокол.** Alertmanager использует gossip-протокол (порт `9094`) для синхронизации состояния silences и дедупликации алертов между репликами. Для работы этого протокола требуется стабильный DNS-имя каждого пода (например, `alertmanager-0`, `alertmanager-1`), которое обеспечивает StatefulSet. Headless Service (`alertmanager-mesh`) используется для внутреннего обнаружения пиров кластера.

**Персистентное хранилище.** В Alertmanager хранятся silences (замалчивания) и журнал отправленных уведомлений. PersistentVolumeClaim гарантирует, что при перезапуске пода или его перепланировании на другой узел данные не теряются. По умолчанию данные хранятся 120 часов (`--data.retention=120h`).

**Karma как единый интерфейс (Single Pane of Glass).** Karma опрашивает один или несколько инстансов Alertmanager с заданным интервалом (по умолчанию 1 минута) и агрегирует алерты в единый UI. При получении идентичных алертов из разных источников Karma объединяет их в одну карточку, добавляя бейджи с именами источников. Это устраняет необходимость переключения между интерфейсами разных кластеров.

**Нативная подстановка переменных.** Начиная с Alertmanager v0.27, вместо инициализации контейнера с `envsubst` можно использовать флаг `--config.expand-external-variables` и синтаксис `${VARIABLE_NAME}` прямо в `alertmanager.yml`. Значения переменных пробрасываются через `env.valueFrom.secretKeyRef`, что упрощает манифесты и уменьшает время старта пода.

### Требования к окружению

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| **Kubernetes** | 1.30+ | Рекомендуется для стабильной работы SidecarContainers и актуальных версий API. |
| **Alertmanager** | 0.27+ | Обязательна для использования нативной подстановки переменных окружения. |
| **Karma** | 0.131+ | Актуальная версия с поддержкой Vite и React 19. |
| **kubectl** | Актуальная | Доступ к кластеру с правами администратора в namespace `monitoring`. |
| **StorageClass** | Любая поддерживаемая | Необходима для динамического provisioning PersistentVolume через `volumeClaimTemplates`. |
| **Ingress Controller** | Любой (nginx, traefik) | Требуется для публикации интерфейсов Alertmanager и Karma. |

---

## Практические сценарии

### Порядок применения манифестов

Для корректной работы зависимостей рекомендуется следующая последовательность:

| Шаг | Ресурс | Файл | Назначение |
| :--- | :--- | :--- | :--- |
| 1 | Namespace | — | Создание namespace `monitoring` (если отсутствует). |
| 2 | Secrets | [secrets.md](./secrets.md) | Токены SMTP и Telegram — создаются первыми для внедрения в поды. |
| 3 | ServiceAccount + RBAC | [intro.md](./intro.md#rbac-и-безопасность) | Минимальные привилегии для Alertmanager и Karma. |
| 4 | ConfigMap (config) | [alertmanager-config.md](./alertmanager-config.md) | Конфигурация `alertmanager.yml` с плейсхолдерами или переменными. |
| 5 | ConfigMap (templates) | [alertmanager-templates.md](./alertmanager-templates.md) | Файлы шаблонов уведомлений для кастомизации вывода. |
| 6 | Service (Headless) | [services.md](./services.md) | Headless Service `alertmanager-mesh` для кластеризации. |
| 7 | StatefulSet | [alertmanager-statefulset.md](./alertmanager-statefulset.md) | Развёртывание основного инстанса Alertmanager с PVC. |
| 8 | ConfigMap (karma) | [karma-config.md](./karma-config.md) | Настройки подключения Karma к API Alertmanager, OIDC, ACL. |
| 9 | Deployment (karma) | [karma-deployment.md](./karma-deployment.md) | Развёртывание веб-интерфейса Karma. |
| 10 | Service + Ingress | [services.md](./services.md) | Настройка сетевой доступности компонентов. |
| 11 | ServiceMonitor | [karma-deployment.md](./karma-deployment.md#мониторинг-karma-через-servicemonitor) | Сбор метрик Karma в Prometheus. |
| 12 | PDB | [karma-deployment.md](./karma-deployment.md#pdb-для-karma) | Защита Karma от одновременного удаления всех реплик. |
| 13 | HPA (опционально) | [karma-deployment.md](./karma-deployment.md#horizontalpodautoscaler-для-karma) | Автоматическое масштабирование при росте нагрузки. |

### Предварительные требования

```bash
# 1. Создание namespace
kubectl create namespace monitoring

# 2. Проверка наличия StorageClass
kubectl get storageclass

# 3. Проверка наличия Ingress Controller
kubectl get pods -n ingress-nginx
# или
kubectl get pods -n traefik
```

### RBAC и безопасность

Для соблюдения принципа минимальных привилегий создайте отдельный ServiceAccount для Alertmanager и Karma. В простых сценариях (отсутствие `PodSecurityPolicy` или `PodSecurity admission`) поды могут запускаться под `default` ServiceAccount, но для production-сред это не рекомендуется.

```yaml
# alertmanager-serviceaccount.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: alertmanager
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: alertmanager
  namespace: monitoring
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get", "list"]
    resourceNames: ["alertmanager-secret"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: alertmanager
  namespace: monitoring
subjects:
  - kind: ServiceAccount
    name: alertmanager
    namespace: monitoring
roleRef:
  kind: Role
  name: alertmanager
  apiGroup: rbac.authorization.k8s.io
---
# karma-serviceaccount.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: karma
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: karma-configmap-reader
  namespace: monitoring
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list"]
    resourceNames: ["karma-config"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: karma-configmap-reader
  namespace: monitoring
subjects:
  - kind: ServiceAccount
    name: karma
    namespace: monitoring
roleRef:
  kind: Role
  name: karma-configmap-reader
  apiGroup: rbac.authorization.k8s.io
```

> **Примечание:** Karma не требует доступа к Secrets (в отличие от Alertmanager), так как OIDC-секреты передаются через ENV-переменные, а не через API Kubernetes. Role ограничивает доступ только чтением ConfigMap `karma-config`.

### Сетевые политики (NetworkPolicy)

В production-средах рекомендуется ограничить сетевой доступ к подам Alertmanager и Karma. Пример политики, разрешающей трафик только от Ingress-контроллера и внутренних сервисов namespace `monitoring`:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-ingress-and-monitoring
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/part-of: alertmanager-karma
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
      ports:
        - protocol: TCP
          port: 9093
        - protocol: TCP
          port: 8080
    - from:
        - podSelector:
            matchLabels:
              app: alertmanager
      ports:
        - protocol: TCP
          port: 9093
```

### Валидация работоспособности

#### 1. Проверка состояния подов

```bash
# Alertmanager: все реплики должны быть Ready
kubectl get pods -n monitoring -l app=alertmanager
# → alertmanager-0   1/1     Running   0          2m
# → alertmanager-1   1/1     Running   0          2m
# → alertmanager-2   1/1     Running   0          2m

# Karma: под должен быть Ready
kubectl get pods -n monitoring -l app=karma
# → karma-xxxxxx   1/1     Running   0          1m
```

#### 2. Проверка кластеризации Alertmanager

```bash
# Проверка сбора метрик кластера
kubectl exec -n monitoring alertmanager-0 -c alertmanager -- \
  curl -s http://localhost:9093/-/healthy
# → OK

# Проверка API кластеризации
kubectl exec -n monitoring alertmanager-0 -c alertmanager -- \
  curl -s http://localhost:9093/api/v2/status | jq .
```

#### 3. Проверка конфигурации через amtool

```bash
kubectl exec -n monitoring alertmanager-0 -c alertmanager -- \
  amtool check-config /etc/alertmanager/alertmanager.yml
# → Checking /etc/alertmanager/alertmanager.yml
# → SUCCESS
```

#### 4. Проверка UI

1.  **Alertmanager UI:** Убедитесь, что интерфейс доступен по адресу `https://alertmanager.example.com`. Проверьте вкладку "Status" на наличие ошибок загрузки конфига.
2.  **Karma UI:** Откройте `https://karma.example.com`. В нижней части экрана должен отображаться статус подключения к Alertmanager "Kubernetes Cluster: OK".

#### 5. Тестирование оповещений

```bash
# Отправка тестового алерта через API
curl -XPOST http://alertmanager.example.com/api/v1/alerts -d '[{
  "labels": {"alertname": "TestAlert", "severity": "critical"},
  "annotations": {"summary": "Тестовое оповещение"}
}]'

# Проверка появления алерта в UI Karma
# Ожидаемый результат: карточка алерта отображается в списке
```

### Устранение неисправностей

| Симптом | Возможная причина | Метод диагностики и решение |
| :--- | :--- | :--- |
| Alertmanager pod в состоянии `CrashLoopBackOff` | Ошибка синтаксиса в `alertmanager.yml` | `kubectl logs -n monitoring alertmanager-0 -c alertmanager` — исправить YAML и повторно применить ConfigMap. |
| Кнопка "Silence" в Karma неактивна | `proxy: false` или неверный `uri` в `config.yaml` Karma | Проверить `karma-config.yaml`: `proxy: true` и доступность `uri` из пода Karma. |
| Алерты не доставляются | Неверные учетные данные в Secret или недоступность SMTP/Telegram API | `kubectl exec -n monitoring alertmanager-0 -c alertmanager -- env | grep -E 'SMTP\|TELEGRAM'` — проверить переменные; проверить сетевое подключение (`nslookup`, `curl`). |
| Повторные алерты (дубли) | Разрыв связи между репликами Alertmanager (порт 9094) или отсутствие Headless Service | `kubectl get endpoints alertmanager-mesh -n monitoring` — должен отображаться IP всех реплик. |
| Karma не видит алерты | Ошибка в `alertmanager.servers.uri` или сетевые политики | `kubectl exec -n monitoring <karma-pod> -- curl -s http://alertmanager.monitoring.svc.cluster.local:9093/api/v2/alerts` — проверить доступность изнутри. |
| `amtool check-config` возвращает ошибку | Неподдерживаемая директива или неверный формат матчеров | Проверить версию Alertmanager (`kubectl exec ... -- alertmanager --version`) и синтаксис matchers (`severity=~"critical|warning"`). |

### PodDisruptionBudget (Production)

Для защиты от voluntary disruptions (например, `kubectl drain`) при обслуживании узлов:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: alertmanager-pdb
  namespace: monitoring
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: alertmanager
```

### Очистка ресурсов

```bash
# Удаление всех ресурсов tutorial (в обратном порядке применения)
kubectl delete -f karma-hpa.yaml            # если создавали
kubectl delete -f karma-pdb.yaml
kubectl delete -f karma-servicemonitor.yaml  # если создавали
kubectl delete -f karma-deployment.yaml
kubectl delete -f karma-config.yaml
kubectl delete -f services.yaml
kubectl delete -f alertmanager-statefulset.yaml
kubectl delete -f alertmanager-templates.yaml
kubectl delete -f alertmanager-config.yaml
kubectl delete -f alertmanager-secret.yaml
kubectl delete -f karma-serviceaccount.yaml
kubectl delete -f alertmanager-serviceaccount.yaml

# Проверка удаления
kubectl get all -n monitoring
kubectl get pvc -n monitoring
```

---

## Дополнительная информация

Данное руководство ориентировано на изучение внутреннего устройства ресурсов Kubernetes. Для промышленной эксплуатации в масштабных средах рекомендуется рассматривать:

- **[kube-prometheus-stack](../../Kube_Prometheus_Stack_Helm/overview.md)** — стандарт де-факто для автоматизированного развёртывания стека через Helm.
- **[Prometheus Operator — Alertmanager](../../operator/crd/alertmanager.md)** — управление жизненным циклом через Custom Resources (CRD).
- **[Высокая доступность Alertmanager](../../alertmanager.md#кластеризация-и-ha)** — настройка Mesh-кластера для исключения единой точки отказа.
- **[Сетевые политики Kubernetes](../../../../Kubernetes/Networking/Network/network_policy.md)** — SSoT по ограничению сетевого доступа между подами.
