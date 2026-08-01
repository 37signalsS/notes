# Безопасность Prometheus Operator

## Определения

**Безопасность Prometheus Operator** — многоуровневая система защиты стека мониторинга, охватывающая весь жизненный цикл данных: от безопасного хранения секретов и контроля доступа к Kubernetes API до шифрования трафика между компонентами и аутентификации пользователей.

---

## Основные концепции

### Эшелонированная защита (Defense in Depth)

Безопасность оператора строится на пяти ключевых уровнях:

| Уровень | Механизм | Назначение | SSoT |
|:---|:---|:---|:---|
| **Управление секретами** | Kubernetes Secrets, External Secrets | Безопасное хранение токенов, паролей и ключей. | [secrets_best_practices.md](./secrets_best_practices.md) |
| **Контроль доступа** | RBAC, ServiceAccounts | Авторизация запросов Prometheus к Kubernetes API. | [access_control.md](./access_control.md) |
| **Сетевая изоляция** | NetworkPolicy | Ограничение L3/L4 доступа к портам компонентов. | [access_control.md](./access_control.md) |
| **Инфраструктурный TLS** | `spec.web.tlsConfig`, cert-manager | Шифрование Web UI и API (Prometheus, Alertmanager). | Настоящий файл |
| **Аутентификация** | Basic Auth, OAuth2 Proxy | Идентификация пользователей и систем. | [Web Authentication](../Kube_Prometheus_Stack_Helm/practical_scenarios/web_authentication.md) |

---

## Практические сценарии

### Аутентификация и защита веб-интерфейсов

#### Встроенная авторизация (Built-in Auth)

С версии Prometheus 2.48+ и в Prometheus 3.x поддерживается встроенная Basic Auth. Начиная с Operator v0.80+, настройка TLS и авторизации выполняется через блок `spec.web`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
spec:
  web:
    tlsConfig:
      cert:
        secret:
          name: prometheus-server-tls
          key: tls.crt
      keySecret:
        name: prometheus-server-tls
        key: tls.key
    webConfig:
      basicAuth:
        username:
          name: prometheus-auth
          key: username
        password:
          name: prometheus-auth
          key: password
```

#### Защита Alertmanager

Аналогично Prometheus, Alertmanager поддерживает TLS для API и веб-интерфейса, а также шифрование внутреннего Gossip-трафика (порт 9094):

```yaml
kind: Alertmanager
spec:
  replicas: 3
  clusterTLS: # Защита трафика между репликами
    cert:
      secret: {name: am-cluster-tls, key: tls.crt}
    keySecret:
      name: am-cluster-tls
      key: tls.key
  web:
    tlsConfig: # Защита веб-интерфейса
      cert:
        secret: {name: am-web-tls, key: tls.crt}
      keySecret:
        name: am-web-tls
        key: tls.key
```

### Автоматизация TLS с cert-manager

Стандартным подходом в 2026 году является использование `cert-manager` для автоматической генерации и ротации сертификатов:

1.  **Создание Certificate:**
    ```yaml
    apiVersion: cert-manager.io/v1
    kind: Certificate
    metadata:
      name: prometheus-server-tls
    spec:
      secretName: prometheus-server-tls
      dnsNames: ["prometheus.monitoring.svc.cluster.local"]
      issuerRef:
        name: internal-ca
        kind: ClusterIssuer
    ```
2.  **Привязка к CRD:** Оператор обнаружит секрет и автоматически настроит `--web.config.file`.

### Безопасный скрейпинг (Secure Scrape)

Для сбора метрик с защищенных эндпоинтов используйте mTLS, OAuth2 или `proxyConfig`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: secure-app
spec:
  endpoints:
    - port: https
      scheme: https
      oauth2:
        clientId:
          secret: {name: auth-creds, key: id}
        clientSecret:
          name: auth-creds
          key: secret
        tokenUrl: https://keycloak.corp/token
      proxyConfig: # Использование прокси для выхода из изолированных сегментов
        proxyUrl: http://squid.corp:3128
      tlsConfig:
        ca:
          secret: {name: app-ca, key: ca.crt}
        insecureSkipVerify: false
```

---

## Дополнительная информация

Безопасность Prometheus Operator является динамической областью. Для реализации специфических мер следуйте специализированным SSoT-руководствам:

- **[Контроль доступа](./access_control.md)** — глубокая настройка RBAC и NetworkPolicy.
- **[Управление секретами](./secrets_best_practices.md)** — ротация и внешние хранилища.
- **[Web Authentication](../Kube_Prometheus_Stack_Helm/practical_scenarios/web_authentication.md)** — реализация SSO и OAuth2-proxy.
- **[High Availability](../high_availability.md)** — влияние отказоустойчивости на безопасность.
- **[Reliability Scores](../../../GEMINI.md)** — методология оценки достоверности (Score: 10).
