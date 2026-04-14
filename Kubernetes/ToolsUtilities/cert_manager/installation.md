# Установка Cert-manager

## Definitions

**Установка cert-manager** — процесс развёртывания Kubernetes-контроллера для автоматизации управления TLS-сертификатами. Официальная документация: [cert-manager.io/docs](https://cert-manager.io/docs/installation/).

**Связанные темы:**

- Определения и CRD: [definitions.md](./definitions.md)
- Обновление и мониторинг: [Administration/operations.md](./Administration/operations.md)
- Troubleshooting: [Administration/troubleshooting.md](./Administration/troubleshooting.md)
- Garbage collection: [Administration/index.md](./Administration/index.md)

---

## Basic Concepts

### Способы установки

| Способ | Преимущества | Недостатки | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Helm** | Управление версиями, values, откат | Требует Helm | **Рекомендуется** |
| **kubectl apply** | Простота, нет зависимостей | Ручное обновление, нет values | Быстрый старт, CI/CD |
| **Operator (OLM)** | Интеграция с OpenShift | Требует OLM | OpenShift-кластеры |

### Предварительные требования

| Требование | Минимум | Примечание |
| :--- | :--- | :--- |
| **Kubernetes** | 1.25 (для cert-manager 1.20+) | Проверить: `kubectl version` |
| **kubectl** | Настроен на целевой кластер | Контекст: `kubectl config current-context` |
| **Helm** | 3+ | Проверить: `helm version` |
| **Gateway API CRD** | Опционально | Установить **до** cert-manager, если требуется |

### Ключевые компоненты cert-manager

| Компонент | Назначение |
| :--- | :--- |
| **cert-manager** | Основной контроллер, управление Certificate |
| **cert-manager-cainjector** | Инжекция CA в Secret для admission webhooks |
| **cert-manager-webhook** | Валидация и мутация ресурсов cert-manager |

---

## Practical Scenarios

### Сценарий 1: Установка через Helm (рекомендуемый)

#### Шаг 1: Добавление репозитория

```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update
```

#### Шаг 2: Установка Gateway API CRD (опционально)

> **Важно:** Если планируется использование Gateway API, установите CRD **до** cert-manager.

```bash
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.0.0/standard-install.yaml
```

#### Шаг 3: Установка cert-manager

```bash
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.20.0 \
  --set installCRDs=true
```

#### Шаг 4: Проверка установки

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

### Сценарий 2: Установка через kubectl apply

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.20.0/cert-manager.yaml
```

**Проверка готовности:**

```bash
kubectl wait --for=condition=Available deployment/cert-manager \
  -n cert-manager --timeout=120s
kubectl wait --for=condition=Available deployment/cert-manager-cainjector \
  -n cert-manager --timeout=120s
kubectl wait --for=condition=Available deployment/cert-manager-webhook \
  -n cert-manager --timeout=120s
```

### Сценарий 3: Специальные конфигурации

#### Включение Gateway API

```bash
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --set installCRDs=true \
  --set "extraArgs={--enable-gateway-api=true}"
```

#### Garbage collection для Secret

Автоматическое удаление Secret при удалении Certificate:

```bash
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --set installCRDs=true \
  --set "extraArgs={--enable-certificate-owner-ref=true}"
```

Подробные сценарии: [Administration: garbage collection](./Administration/index.md).

#### High Availability (HA)

```bash
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --set installCRDs=true \
  --set replicaCount=3 \
  --set podDisruptionBudget.enabled=true \
  --set podDisruptionBudget.minAvailable=2
```

### Сценарий 4: Обновление cert-manager

> **Полное руководство:** [Administration/operations.md](./Administration/operations.md#обновление-cert-manager)

**Краткая процедура:**

```bash
# Проверка доступных версий
helm search repo jetstack/cert-manager --versions

# Обновление (без пропуска минорных версий)
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --version v1.20.0 \
  --reuse-values
```

> **Важно:** При переходе между минорными версиями обновляйте CRD отдельно. Пропуск минорных версий не рекомендуется.

### Сценарий 5: Удаление cert-manager

#### Helm

```bash
helm uninstall cert-manager -n cert-manager
# CRD не удаляются автоматически — удалить вручную:
kubectl delete crds \
  certificaterequests.cert-manager.io \
  certificates.cert-manager.io \
  challenges.acme.cert-manager.io \
  clusterissuers.cert-manager.io \
  issuers.cert-manager.io \
  orders.acme.cert-manager.io
```

#### kubectl

```bash
kubectl delete -f https://github.com/cert-manager/cert-manager/releases/download/v1.20.0/cert-manager.yaml
```

---

## Additional Information

### Параметры Helm

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| `installCRDs` | Устанавливать и управлять CRD | `false` |
| `extraArgs` | Дополнительные флаги контроллера | `[]` |
| `replicaCount` | Количество реплик | `1` |
| `podDisruptionBudget.enabled` | PDB для high-availability | `false` |

### Актуальные версии

| Версия | Мин. K8s | Статус |
| :--- | :--- | :--- |
| **1.20.x** | 1.25 | **Текущая** |
| 1.19.x | 1.25 | Поддерживается |
| 1.18.x | 1.24 | Поддерживается |
| <1.17 | <1.24 | **Устарели** |

> **Проверка актуальности:** [endoflife.date/cert-manager](https://endoflife.date/cert-manager) · [GitHub Releases](https://github.com/cert-manager/cert-manager/releases)

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| Helm-установка | **10** | Официальная документация cert-manager.io |
| kubectl apply | **10** | Стандартный способ из release notes |
| Gateway API | **9** | Подтверждено в релизах 1.13+ |
| HA-конфигурация | **9** | Best practices cert-manager |
