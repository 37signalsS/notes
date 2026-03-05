# Установка Cert-manager

## Способы установки

| Способ | Преимущества | Недостатки | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Helm** | Управление версиями, values, откат | Требует Helm | **Рекомендуется** |
| **kubectl apply** | Простота, нет зависимостей | Ручное обновление, нет values | Быстрый старт, CI/CD |
| **Operator (OLM)** | Интеграция с OpenShift | Требует OLM | OpenShift-кластеры |

---

## Предварительные требования

1. **Kubernetes:** Минимум версия 1.22 (для cert-manager 1.13+)
2. **kubectl:** Настроен на целевой кластер
3. **Helm:** Версия 3+ (для Helm-установки)
4. **Gateway API CRD:** Опционально, если требуется интеграция

---

## Установка через Helm (рекомендуемый способ)

### Шаг 1: Добавление репозитория Jetstack

```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update
```

### Шаг 2: Установка CRD Gateway API (опционально)

> **Важно:** Если планируется использование Gateway API, установите CRD **до** cert-manager.

```bash
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.0.0/standard-install.yaml
```

### Шаг 3: Установка cert-manager

```bash
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.15.0 \
  --set installCRDs=true
```

**Параметры:**

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| `installCRDs` | Устанавливать и управлять CRD | `false` |
| `extraArgs` | Дополнительные флаги контроллера | `[]` |
| `replicaCount` | Количество реплик | `1` |
| `podDisruptionBudget` | PDB для high-availability | `enabled: false` |

### Шаг 4: Проверка установки

```bash
kubectl get deployments -n cert-manager
kubectl get pods -n cert-manager
kubectl get crds | grep cert-manager.io
```

**Ожидаемый вывод:**
```
NAME                      READY   UP-TO-DATE   AVAILABLE   AGE
cert-manager              1/1     1            1           2m
cert-manager-cainjector   1/1     1            1           2m
cert-manager-webhook      1/1     1            1           2m
```

---

## Установка через kubectl apply

### Команда установки

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.15.0/cert-manager.yaml
```

### Проверка

```bash
kubectl wait --for=condition=Available deployment/cert-manager -n cert-manager --timeout=120s
kubectl wait --for=condition=Available deployment/cert-manager-cainjector -n cert-manager --timeout=120s
kubectl wait --for=condition=Available deployment/cert-manager-webhook -n cert-manager --timeout=120s
```

---

## Специальные конфигурации

### Включение Gateway API

```bash
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --set installCRDs=true \
  --set "extraArgs={--enable-gateway-api=true}"
```

### Включение garbage collection для Secret

```bash
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --set installCRDs=true \
  --set "extraArgs={--enable-certificate-owner-ref=true}"
```

> **Предупреждение:** При удалении `Certificate` будет удалён соответствующий `Secret`. Используйте с осторожностью в production.

### High Availability (HA)

```bash
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --set installCRDs=true \
  --set replicaCount=3 \
  --set podDisruptionBudget.enabled=true \
  --set podDisruptionBudget.minAvailable=2
```

---

## Обновление cert-manager

### Helm

```bash
# Проверка доступных версий
helm search repo jetstack/cert-manager --versions

# Обновление
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --version v1.15.0
```

### kubectl apply

```bash
# Удаление старой версии
kubectl delete -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.2/cert-manager.yaml

# Установка новой
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.15.0/cert-manager.yaml
```

---

## Удаление

### Helm

```bash
helm uninstall cert-manager -n cert-manager
# CRD не удаляются автоматически
kubectl delete crds \
  certificaterequests.cert-manager.io \
  certificates.cert-manager.io \
  challenges.acme.cert-manager.io \
  clusterissuers.cert-manager.io \
  issuers.cert-manager.io \
  orders.acme.cert-manager.io
```

### kubectl

```bash
kubectl delete -f https://github.com/cert-manager/cert-manager/releases/download/v1.15.0/cert-manager.yaml
```

---

## Диагностика проблем

### Проверка логов

```bash
kubectl logs -n cert-manager -l app=cert-manager
kubectl logs -n cert-manager -l app=webhook
kubectl logs -n cert-manager -l app=cainjector
```

### Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Webhook timeout | Проблемы с сетью или ресурсами | Проверить `cert-manager-webhook` deployment |
| CRD not found | CRD не установлены | `--set installCRDs=true` или установить вручную |
| Gateway API not enabled | Флаг не указан | Добавить `--enable-gateway-api=true` |
| Certificate pending | ACME-challenge не прошёл | Проверить доступность HTTP/DNS |

---

## Актуальные версии (март 2026)

| Версия | Мин. K8s | Статус | EOL |
| :--- | :--- | :--- | :--- |
| **1.15.x** | 1.23 | **Текущая** | — |
| 1.14.x | 1.23 | Поддерживается | — |
| 1.13.x | 1.22 | Поддерживается | — |
| <1.12 | <1.22 | **Устарели** | Да |

**Источники:**
- [Официальная документация](https://cert-manager.io/docs/installation/)
- [GitHub Releases](https://github.com/cert-manager/cert-manager/releases)
- [Helm Chart](https://artifacthub.io/packages/helm/cert-manager/cert-manager)

---

*SSoT для установки cert-manager. Последняя проверка актуальности: март 2026.*
