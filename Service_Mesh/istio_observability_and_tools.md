# Наблюдаемость в Istio: Kiali и федерация идентификации

## Определения

**Наблюдаемость (Observability)** в контексте Istio обеспечивается набором инструментов для визуализации топологии, мониторинга трафика и анализа состояния mesh-сети.

**Kiali** — консоль управления и веб-интерфейс для Istio. Позволяет визуализировать структуру сервисов, отслеживать потоки трафика в реальном времени и выявлять ошибки конфигурации.

**Dex** — федеративный провайдер идентификации с поддержкой OIDC (OpenID Connect). Используется для организации безопасного доступа к Kiali через внешние источники (LDAP, GitHub, SAML), заменяя небезопасный анонимный режим.

---

## Основные концепции

### Зависимости и интеграции

Для полноценной работы Kiali требуется наличие следующих компонентов в кластере:

| Компонент | Статус | Назначение |
| :--- | :--- | :--- |
| **Prometheus** | **Обязателен** | Источник метрик для построения графиков и индикации состояния. |
| **Istio** | **Обязателен** | Целевая Mesh-система для анализа. |
| **Grafana** | Рекомендуется | Переход к детальным дашбордам для глубокого анализа. |
| **Jaeger / Tempo** | Опционально | Просмотр распределенных трассировок (Distributed Tracing). |

### Визуальные индикаторы Kiali

Интерфейс Kiali использует цветовую и символьную кодировку для отображения состояния сети:

- **Цвета линий:** отражают здоровье трафика (зеленый — успех, красный — ошибки > 5%, оранжевый — предупреждения).
- **Иконки замков:** подтверждают наличие активного mTLS (Mutual TLS — взаимная проверка подлинности TLS) соединения.
- **Типы трафика:** в режиме Ambient Mesh синие линии обозначают L4-трафик (Ztunnel), а зеленые — L7 (Waypoint Proxy).
- **Аналитика:** встроенный движок валидации подсвечивает некорректные или конфликтующие ресурсы Istio (например, дублирующиеся VirtualService).

### Стратегии аутентификации

| Стратегия | Применение | Безопасность |
| :--- | :--- | :--- |
| **`anonymous`** | Локальная разработка. | Низкая (доступ без пароля). |
| **`openid`** | Интеграция с Dex / Keycloak (OIDC). | **Высокая** (Enterprise стандарт). |
| **`token`** | Использование токенов ServiceAccount Kubernetes. | Средняя (для администраторов). |

---

## Практические сценарии

### Организация безопасного доступа к Kiali через Dex

Сценарий включает настройку TLS-сертификатов, публикацию через Gateway API и интеграцию Kiali с Dex по протоколу OIDC.

#### 1. Подготовка сетевой инфраструктуры

Создание TLS-сертификата (через `cert-manager`) и шлюза:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: observability-gateway
  namespace: istio-system
spec:
  gatewayClassName: istio
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: kiali-tls-secret
```

#### 2. Настройка Dex (Identity Provider)

Конфигурация Dex для работы с Kiali (статические пользователи для примера):

```yaml
# Фрагмент конфигурации dex-config.yaml
issuer: https://dex.local
staticClients:
- id: kiali
  redirectURIs:
  - 'https://kiali.local/api/auth/login/oidc/callback'
  name: 'Kiali Console'
  secret: "secret-value"
```

#### 3. Конфигурация Kiali для работы с OIDC

Настройка стратегии доступа в Helm values:

```yaml
auth:
  strategy: openid
  openid:
    client_id: kiali
    issuer_uri: https://dex.local
    username_claim: email
external_services:
  prometheus:
    url: "http://prometheus-server.monitoring.svc.cluster.local:80"
```

Применение настроек:

```bash
helm upgrade --install kiali-server kiali/kiali-server -f values.yaml -n istio-system
# → Release "kiali-server" has been upgraded. Happy Helming!
```

---

## Дополнительная информация

### Возможности Kiali v2.x

- **Поддержка Ambient Mesh:** полное отображение архитектуры без sidecar-контейнеров.
- **Gateway API:** визуализация цепочек `Gateway` -> `HTTPRoute` -> `Service`.
- **Health Validation:** автоматическая проверка конфигураций на соответствие лучшим практикам безопасности.
- **Multi-cluster:** возможность агрегации данных из нескольких кластеров Kubernetes в единой панели.

### Рекомендации по эксплуатации

1. **Безопасность:** никогда не используйте стратегию `anonymous` вне локальных окружений.
2. **Метрики:** убедитесь, что в Prometheus настроен сбор данных (scrape) с портов Envoy (обычно 15020).
3. **Ресурсы:** Kiali требует ресурсов пропорционально размеру mesh-сети (количеству подов и сервисов). Для больших кластеров рекомендуется увеличивать лимиты памяти.

### См. также

- [Основные концепции Service Mesh](./service_mesh_concepts.md)
- [Архитектура Istio и режим Ambient](./istio_architecture.md)
- [Централизованная аутентификация в Keycloak](../Security/Tools/keycloak_overview.md)

Документация: [Kiali Docs](https://kiali.io/docs/), [Dex Documentation](https://dexidp.io/docs/).
