# Kyverno: Движок политик для Kubernetes

## Определения

**Kyverno** — открытый policy-движок для Kubernetes (<https://kyverno.io/>), позволяющий управлять политиками с помощью YAML-манифестов. Предназначен для автоматизации безопасности, обеспечения соответствия требованиям и внедрения лучших практик непосредственно в кластере Kubernetes.

**Ключевые особенности**:
- **YAML-политики**: Не требуется изучение новых языков (в отличие от OPA/Rego)
- **Admission Controller**: Валидация и мутация во время деплоя
- **Генерация ресурсов**: Автоматическое создание ресурсов по шаблону
- **Отчетность**: Policy Reports в стандарте WG Policy K8s
- **Внекластерное использование**: CLI для проверки манифестов в CI/CD

---

## Basic Concepts

### Архитектура работы

```
┌─────────────┐     ┌──────────────────────┐     ┌─────────────┐
│  Manifest   │────▶│  Admission Webhooks  │────▶│   etcd      │
│  (YAML)     │     │  (Kyverno)           │     │  (Storage)  │
└─────────────┘     └──────────────────────┘     └─────────────┘
                           │
                           ├─ Mutating Webhook (изменение)
                           │
                           └─ Validating Webhook (проверка)
```

### Компоненты Kyverno

| Компонент | Назначение |
|-----------|------------|
| **Admission Controller** | Обработка mutating и validating webhook-запросов |
| **Background Controller** | Фоновое сканирование существующих ресурсов |
| **Cleanup Controller** | Удаление ресурсов по расписанию |
| **Reports Controller** | Генерация Policy Reports |

### Сравнение с аналогами

| Инструмент | Когда работает | Язык | SSoT |
|------------|----------------|------|------|
| **Kyverno** | Admission (во время деплоя) | YAML | Этот файл |
| **[OPA Gatekeeper](../rbac/limitations_opa.md)** | Admission | Rego | limitations_opa.md |
| **[kubesec](../kubesec.md)** | До деплоя (статический) | YAML | kubesec.md |
| **[Falco](../../Security/Tools/falco.md)** | Runtime (после деплоя) | Rules | falco.md |
| **[PSA](../pod_security_context.md)** | Admission | Labels | pod_security_context.md |

---

## Practical Scenarios

### Основные сценарии использования

1. **Валидация безопасности**: Требование securityContext, запрет privileged-контейнеров
2. **Мутация ресурсов**: Автоматическое добавление securityContext, imagePullSecrets
3. **Генерация ресурсов**: Создание NetworkPolicy, Secret для новых namespace
4. **Соответствие стандартам**: PCI DSS, GDPR, CIS Benchmark через политики
5. **Очистка ресурсов**: Удаление старых Pod, завершенных Jobs
6. **Проверка подписей**: Верификация образов через Sigstore/Cosign

### Примеры политик

#### Требование non-root пользователя

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-run-as-non-root
spec:
  validationFailureAction: Enforce
  rules:
    - name: run-as-non-root
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "Container must run as non-root"
        pattern:
          spec:
            securityContext:
              runAsNonRoot: true
```

#### Запрет HostPath volumes

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: deny-host-path
spec:
  validationFailureAction: Enforce
  rules:
    - name: deny-host-path
      match:
        resources:
          kinds:
            - Pod
      deny:
        conditions:
          - key: "{{ request.object.spec.volumes[*].hostPath }}"
            operator: AnyNotIn
            value: ["", null]
        message: "HostPath volumes are forbidden"
```

---

## Additional Information

### Документация по темам

| Файл | Описание |
|------|----------|
| [Основные концепции](./kyverno/concepts.md) | Как работает Kyverno, архитектура, сравнение с другими инструментами |
| [Типы правил](./kyverno/rules.md) | generate, mutate, validate, verifyImages — детальное описание |
| [Написание политик](./kyverno/policies.md) | Структура политик, Match/Exclude, примеры |
| [Практические сценарии](./kyverno/scenarios.md) | Реальные случаи использования |
| [Установка](./kyverno/install.md) | Установка через Helm, проверка, troubleshooting |
| [Интеграция с Argo CD](./kyverno/argo-cd.md) | Конфликты и решения для совместного использования |
| [Отчеты](./kyverno/reports.md) | Policy Reports, структура, метрики Prometheus |
| [Background Scans](./kyverno/background.md) | Фоновое сканирование для аудита |
| [Policy Reporter](./kyverno/reporter.md) | Web UI, уведомления, dashboard |
| [Дополнительная информация](./kyverno/additional.md) | Aggregated Cluster Roles, миграция с PSP |

### Связанные темы в проекте

- **[Pod Security Context](./pod_security_context.md)** — PSS/PSA для контроля безопасности подов
- **[RBAC](./rbac/rbac_overview.md)** — управление доступом в Kubernetes
- **[NetworkPolicy](./network_policies.md)** — сетевая изоляция
- **[Sigstore](../../Security/Tools/sigstore.md)** — подписывание образов
- **[Supply Chain Security](../../Security/Supply_Chain_Security/artifact_signing.md)** — безопасность цепочки поставок
- **[Falco](../../Security/Tools/falco.md)** — runtime-мониторинг

### Официальные ресурсы

- **Документация**: <https://kyverno.io/docs/>
- **GitHub**: <https://github.com/kyverno/kyverno>
- **Policy Catalog**: <https://github.com/kyverno/policies>
- **Slack**: <https://kubernetes.slack.com/channels/kyverno>
