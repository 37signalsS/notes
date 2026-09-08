# Безопасность Prometheus Operator

## Определения

**Безопасность Prometheus Operator** — многоуровневая система защиты стека мониторинга в Kubernetes, охватывающая весь жизненный цикл данных: от безопасного хранения секретов и контроля доступа к API до шифрования трафика между компонентами и аутентификации пользователей. В современной экосистеме (2025–2026 гг.) включает в себя поддержку Prometheus 3.0 с обновлёнными протоколами Remote Write 2.0 и механизмами валидации имён.

---

## Основные концепции

### Эшелонированная защита (Defense in Depth)

Безопасность оператора строится на интеграции нативных механизмов Kubernetes и специфических настроек Custom Resources:

| Уровень | Механизм | Назначение | Источник |
|:---|:---|:---|:---|
| **Управление секретами** | Kubernetes Secrets, External Secrets (ESO) | Безопасное хранение токенов, паролей и ключей с автоматической ротацией. | [secrets_best_practices.md](./secrets_best_practices.md) |
| **Контроль доступа** | RBAC, ServiceAccounts | Авторизация запросов Prometheus к K8s API; использование `status` subresource для гранулярных прав. | [access_control.md](./access_control.md) |
| **Сетевая изоляция** | NetworkPolicy, eBPF (Cilium) | Ограничение L3/L4/L7 доступа к портам компонентов мониторинга. | [access_control.md](./access_control.md) |
| **Валидация ресурсов** | Admission Webhooks | Проверка корректности CRD (ServiceMonitor, PrometheusRule) перед применением; защита от SSRF. | Настоящий файл |
| **Безопасность подов** | SecurityContext, Pod Security Standards | Ограничение привилегий контейнеров (Non-root, Read-only FS). | Настоящий файл |
| **Инфраструктурный TLS** | `spec.web.tlsConfig`, cert-manager | Шифрование Web UI и API (Prometheus, Alertmanager). | Настоящий файл |
| **Аутентификация** | Basic Auth, OAuth2 Proxy, IAP | Идентификация пользователей; защита нового UI Prometheus 3.0. | [Web Authentication](../../Kube_Prometheus_Stack_Helm/practical_scenarios/web_authentication.md) |

---

## Практические сценарии

### Настройка безопасности подов (Pod Security)

Рекомендуется использовать максимально строгие настройки `securityContext` для минимизации вектора атаки в случае компрометации контейнера.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 2000
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: prometheus
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
        readOnlyRootFilesystem: true
```

### Аутентификация и защита веб-интерфейсов

#### Встроенная авторизация и TLS (Prometheus 3.0)

Начиная с версии Operator v0.80+, настройка TLS и авторизации выполняется через блок `spec.web`. Важно учитывать новый флаг валидации имен при переходе на Prometheus 3.x.

```yaml
spec:
  web:
    tlsConfig:
      cert:
        secret: {name: prometheus-server-tls, key: tls.crt}
      keySecret:
        name: prometheus-server-tls, key: tls.key
    webConfig:
      basicAuth:
        username: {name: prometheus-auth, key: username}
        password: {name: prometheus-auth, key: password}
```

> **Важно:** Prometheus 3.0 поддерживает UTF-8 в именах метрик. Если ваши системы не готовы к этому, используйте флаг `--name-validation-scheme=legacy` в аргументах оператора для admission webhook.

#### Защита нового UI через OAuth2-proxy

Так как Prometheus не имеет встроенной поддержки OIDC/SAML, для корпоративных сред рекомендуется использовать OAuth2-proxy в качестве sidecar или на уровне Ingress.

### Безопасность Admission Webhooks и SSRF

Оператор v0.80+ вводит строгую валидацию `tokenUrl` для OAuth2, чтобы предотвратить Server-Side Request Forgery (SSRF).

1.  **Проверка Webhook:** Убедитесь, что `ValidatingWebhookConfiguration` активен. Это предотвращает создание некорректных ресурсов, которые могут вызвать отказ в обслуживании (DoS) мониторинга.
2.  **Granular RBAC:** Используйте `status` subresource. Это позволяет автоматизированным системам обновлять статус мониторинга, не имея прав на изменение логики сбора метрик.

### Защита Alertmanager

Alertmanager требует защиты не только API, но и внутреннего Gossip-трафика (порт 9094), используемого в HA-кластерах.

```yaml
kind: Alertmanager
spec:
  replicas: 3
  clusterTLS: # Защита трафика между репликами (Gossip)
    cert:
      secret: {name: am-cluster-tls, key: tls.crt}
    keySecret: {name: am-cluster-tls, key: tls.key}
  web:
    tlsConfig: # Защита веб-интерфейса и API
      cert:
        secret: {name: am-web-tls, key: tls.crt}
      keySecret: {name: am-web-tls, key: tls.key}
```

---

## Дополнительная информация

Безопасность Prometheus Operator является динамической областью. Для реализации специфических мер следуйте профильным руководствам:

- **[Контроль доступа](./access_control.md)** — глубокая настройка RBAC, NetworkPolicy и защита Admission Webhook.
- **[Управление секретами](./secrets_best_practices.md)** — ротация, ESO и интеграция с Vault.
- **[Web Authentication](../../Kube_Prometheus_Stack_Helm/practical_scenarios/web_authentication.md)** — реализация SSO, OAuth2-proxy и защита Grafana.
- **[High Availability](../high_availability.md)** — влияние отказоустойчивости на безопасность и Gossip-протокол.
