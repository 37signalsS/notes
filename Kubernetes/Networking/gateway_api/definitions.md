# Gateway API — Определения и концепции

## Определения

**Gateway API** — унифицированный стандарт Kubernetes для управления сетевым трафиком (L4 и L7). Это эволюционное развитие Ingress, объединяющее управление внешним доступом (North-South) и мессервисным взаимодействием (East-West/Service Mesh) в рамках единой объектной модели. Стандарт полностью базируется на Custom Resource Definitions (CRD). Gateway API разрабатывается под управлением Kubernetes SIG-Network и является частью экосистемы CNCF.

**Gateway API Controller** — программный компонент (например, Envoy Gateway, Istio, Traefik, Cilium), который отслеживает ресурсы Gateway API и транслирует их в конфигурацию для Data Plane (прокси-серверов). Контроллер реализует бизнес-логику обработки CRD, управление жизненным циклом ресурсов и взаимодействие с внешней инфраструктурой (выделение IP-адресов, настройка балансировщиков).

**Control Plane** — компонент архитектуры Gateway API, отвечающий за управление конфигурацией, обработку CRD и взаимодействие с Kubernetes API Server. Control Plane читает ресурсы Gateway API, валидирует их и генерирует конфигурацию для Data Plane.

**Data Plane** — компонент архитектуры Gateway API, непосредственно обрабатывающий сетевой трафик. Data Plane состоит из прокси-серверов (Envoy, NGINX, Traefik), которые получают конфигурацию от Control Plane и выполняют маршрутизацию, балансировку, терминацию TLS.

**GAMMA (Gateway API for Mesh Management and Administration)** — инициатива внутри Gateway API, определяющая стандарты для Service Mesh. Она позволяет использовать те же ресурсы (например, `HTTPRoute`) для управления трафиком внутри кластера, привязывая их непосредственно к `Service` (режим East-West). GAMMA расширяет применение Gateway API за пределы входящего трафика, обеспечивая единый подход к управлению сетью.

**Direct Pod Targeting** — механизм, при котором контроллер направляет трафик напрямую на IP-адреса подов (Endpoints), минуя виртуальный IP сервиса (ClusterIP) и `kube-proxy`. Это снижает задержки (eliminates extra hop), позволяет реализовать сложные алгоритмы балансировки на стороне прокси (Least Requests, Ring Hash) и обеспечивает точечную маршрутизацию к конкретным подам.

**Status Conditions** — механизм обратной связи в Gateway API, предоставляющий информацию о состоянии ресурса через поле `status.conditions`. Каждое условие содержит тип (type), статус (status: True/False/Unknown) и причину (reason). Основные условия: `Accepted`, `Programmed`, `ResolvedRefs`.

**Версионирование спецификации** — Gateway API использует систему каналов для управления стабильностью функций:
- **Standard Channel (GA):** стабильные функции, гарантированно поддерживаемые всеми совместимыми контроллерами. Примеры: `HTTPRoute` (v1), `GatewayClass` (v1), `TCPRoute` (v1), `UDPRoute` (v1).
- **Experimental Channel:** новые функции, находящиеся в стадии тестирования. Могут изменяться или удаляться. Для включения требуется установка CRD с флагом `experimentalChannel: true`. Примеры: `GRPCRoute` (v1), `BackendTLSPolicy` (v1alpha3), `ListenerSet` (v1).

## Базовые концепции

### Архитектура Gateway API

Gateway API реализует классическую архитектуру разделения на плоскости управления и данных:

**Control Plane:**
- Взаимодействует с Kubernetes API Server для отслеживания ресурсов Gateway API
- Валидирует конфигурацию и проверяет зависимости (ReferenceGrant)
- Генерирует конфигурацию для Data Plane в формате, специфичном для контроллера
- Обновляет `status.conditions` ресурсов для отражения текущего состояния
- Может быть реализован как под (Deployment) в кластере или как внешний сервис

**Data Plane:**
- Принимает и обрабатывает сетевой трафик согласно конфигурации от Control Plane
- Выполняет маршрутизацию (L4/L7), балансировку нагрузки, терминацию TLS
- Поддерживает горячую перезагрузку конфигурации без разрыва соединений
- Обеспечивает метрики и логи для мониторинга

**Взаимодействие компонентов:**
```
Клиент -> Data Plane (прокси) -> Backend (Pod)
                ^
                |
        Control Plane (контроллер)
                |
        Kubernetes API Server
```

### Ролевая модель управления

Спецификация ориентирована на разделение ответственности между тремя ролями, что позволяет масштабировать управление сетью в крупных организациях и эффективно решать проблему мультиарендности (multi-tenancy):

- **Администраторы инфраструктуры:** управляют `GatewayClass`. Определяют политики безопасности, типы доступных контроллеров (NGINX, Envoy, Traefik) и глобальные параметры провайдера. Создают `Gateway` с общими слушателями и настраивают `ListenerSet` для делегирования портов командам.
- **Операторы кластера:** управляют ресурсами `Gateway`. Отвечают за сетевые точки входа, выделение IP-адресов, портов и общие настройки TLS-терминации. Благодаря разделению ресурсов, операторы могут ограничивать доступ разработчиков к общим слушателям портов, предотвращая конфликты конфигураций.
- **Разработчики приложений:** управляют ресурсами маршрутизации (`HTTPRoute`, `GRPCRoute`, `TCPRoute`). Настраивают логику своих приложений (пути, заголовки, веса), не затрагивая общую инфраструктуру шлюзов. Каждый разработчик работает в своём пространстве имён со своими объектами `Route`, что исключает ситуацию, когда команды "наступают друг другу на пятки", редактируя один общий файл Ingress.

**Пример распределения ответственности:**
| Роль | Ресурсы | Действия |
| :--- | :--- | :--- |
| Администратор | GatewayClass, Gateway (общие) | Установка контроллера, определение классов шлюзов, настройка глобального TLS |
| Оператор | Gateway (командные) | Выделение IP, настройка слушателей, управление сертификатами |
| Разработчик | HTTPRoute, GRPCRoute | Настройка маршрутов, канареечные релизы, A/B-тестирование |

### Сравнение с Ingress (Legacy)

К середине 2026 года Gateway API полностью заменил Ingress в промышленной эксплуатации. Основная причина перехода — решение проблемы **"ада аннотаций" (Annotation Hell)**, когда для настройки базовых функций (Canary, CORS, Rewrite) приходилось использовать десятки несовместимых между собой аннотаций, привязанных к конкретному контроллеру.

| Характеристика | Ingress (Legacy) | Gateway API (Standard) |
| :--- | :--- | :--- |
| **Область применения** | Только North-South (входящий) | North-South и East-West (GAMMA) |
| **Ролевая модель** | Монолитный ресурс `Ingress` | Разделение на `GatewayClass`, `Gateway`, `Route` |
| **Расширяемость** | Хаотичные аннотации (Annotation Hell) | Типизированные фильтры и Policy Attachment |
| **Переносимость** | Привязана к вендору (Nginx/Traefik) | Унифицированный стандарт для всех контроллеров |
| **Безопасность** | Дублирование секретов в namespaces | `ReferenceGrant` (безопасные кросс-ссылки) |
| **Масштабируемость** | Лимиты слушателей в одном объекте | Изоляция ресурсов по ролям и неймспейсам |
| **Протоколы** | Преимущественно HTTP/HTTPS | Нативная поддержка gRPC, TLS, TCP, UDP |
| **Производительность** | Балансировка через Service VIP | Direct Pod Targeting (напрямую на поды) |

### Типы трафика

1. **North-South (Входящий):** Трафик от внешних клиентов к сервисам внутри кластера. Цепочка: `Gateway` -> `HTTPRoute` -> `Service` -> `Pod`.
2. **East-West (Мессервисный):** Взаимодействие между подами внутри кластера. В рамках спецификации GAMMA трафик управляется через `HTTPRoute` с `parentRef`, указывающим на целевой `Service`.

### Безопасность

Gateway API предоставляет многоуровневую модель безопасности для защиты трафика и управления доступом:

**Терминация TLS:**
- Gateway API поддерживает нативную терминацию TLS на уровне `Gateway` (listener)
- Сертификаты хранятся в Kubernetes Secrets (тип `kubernetes.io/tls`)
- Поддерживаются режимы: Terminate (терминация на шлюзе) и Passthrough (сквозное шифрование)

**mTLS (Mutual TLS):**
- Взаимная аутентификация между клиентом и шлюзом
- Сертификаты клиентов проверяются через CA-_bundle в конфигурации Gateway
- Используется для строгого контроля доступа к API

**ReferenceGrant:**
- Ресурс, разрешающий кросс-namespace ссылки на секреты (TLS-сертификаты) и сервисы
- Владелец ресурса явно указывает, какие объекты и из каких namespace могут ссылаться на его ресурсы
- Заменяет небезопасную практику копирования секретов между namespace

**BackendTLSPolicy:**
- Политика для безопасного соединения между шлюзом и бэкендом (Service)
- Определяет CA-сертификат для проверки сертификата бэкенда
- Позволяет использовать mTLS для East-West трафика

**Политики безопасности (Policy Attachment):**
- Расширяемый механизм для настройки Rate Limiting, CORS, Authentication
- Реализуется через специализированные ресурсы (RateLimitPolicy, и др.)
- Детальное описание: [Провайдер-специфичная конфигурация](./provider_specific_config.md)

## Мониторинг и наблюдаемость

Gateway API предоставляет расширенные возможности для мониторинга сетевой инфраструктуры:

**Метрики:**
- Стандартные метрики в формате Prometheus: `gatewayapi_gateway_status`, `gatewayapi_httproute_status`
- Время ответа, количество запросов, ошибки по кодам HTTP
- Специфичные метрики контроллеров (зависят от реализации)

**Логирование:**
- Структурированные логи контроллера для диагностики проблем
- Access logs прокси-серверов (настраиваются через политики)
- Аудит изменений ресурсов Gateway API

**Трассировка:**
- Поддержка distributed tracing (OpenTelemetry, Jaeger)
- Распространение trace context через заголовки запросов
- Интеграция с Service Mesh для end-to-end трассировки

**Инструменты диагностики:**
- `gwctl` — официальная CLI-утилита для управления и диагностики Gateway API
- Дашборды Grafana для визуализации метрик
- Алерты на основе статусов ресурсов

## Практические сценарии

### Выбор реализации (2026)

Выбор контроллера зависит от архитектурных требований:

- **Envoy Gateway:** Официальное решение CNCF, рекомендуемый стандарт для большинства сред.
- **Cilium:** Оптимально для сред с высокими требованиями к производительности (использование eBPF).
- **Istio Gateway Controller:** Рекомендуется при использовании Istio Service Mesh для глубокой интеграции с mTLS.
- **Traefik (v3.3+):** Простота настройки и нативная поддержка Gateway API v1.2+.
- **NGINX Gateway Fabric:** Стабильность NGINX в современной обертке Gateway API.

Сравнение популярных решений: [Envoy Gateway](./envoy_gateway.md), [Traefik](./traefik.md), [KGateway](./kgateway.md), [NGINX Gateway Fabric](./nginx_gateway_fabric.md).

### Диагностика: Метод Status Conditions

Gateway API предоставляет детализированную обратную связь через поле `status.conditions`. Это основной инструмент отладки конфигурации:
- **Accepted:** Ресурс синтаксически корректен и принят контроллером.
- **Programmed:** (только для Gateway) Инфраструктура шлюза успешно настроена в Data Plane.
- **ResolvedRefs:** Все ссылки на зависимости (сервисы, секреты) найдены и валидны (учитывая `ReferenceGrant`).

```bash
# Проверка состояния всех ресурсов Gateway API в кластере
kubectl get gateway,httproute,gatewayclass,referencegrant -A
```

### Диагностика проблем: Пошаговый алгоритм

При возникновении проблем с Gateway API конфигурацией следуйте алгоритму:

1. **Проверка GatewayClass:**
```bash
kubectl get gatewayclass -o yaml
```
Убедитесь, что `status.conditions[].type=Accepted` имеет статус `True`. Если `False` — проверьте логи контроллера.

2. **Проверка Gateway:**
```bash
kubectl get gateway <name> -n <namespace> -o yaml | grep -A 20 "status:"
```
- `Accepted: True` — конфигурация валидна
- `Programmed: True` — Data Plane успешно сконфигурирован
- `Programmed: False` — проверьте логи контроллера и состояние Data Plane

3. **Проверка HTTPRoute/GRPCRoute:**
```bash
kubectl get httproute <name> -n <namespace> -o yaml | grep -A 20 "status:"
```
- `Accepted: True` — маршрут валиден
- `ResolvedRefs: True` — все зависимости найдены
- `ResolvedRefs: False` — проверьте наличие ReferenceGrant для кросс-namespace ссылок

4. **Проверка логов контроллера:**
```bash
kubectl logs -n <controller-namespace> -l app=<controller-name> --tail=100
```

### Проверка безопасности: Аудит конфигурации

Регулярный аудит безопасности Gateway API конфигурации:

```bash
# 1. Проверка наличия TLS на всех Gateway
kubectl get gateway -A -o json | jq '.items[].spec.listeners[] | select(.tls == null) | {gateway: .name, port: .port}'

# 2. Проверка ReferenceGrant (выявить отсутствие где нужно)
kubectl get httproute -A -o json | jq '.items[].spec.rules[].backendRefs[] | select(.namespace != null)'

# 3. Проверка BackendTLSPolicy
kubectl get backendtlspolicy -A

# 4. Аудит прав доступа к GatewayClass
kubectl auth can-i create gatewayclass --all-namespaces
```

### Использование gwctl для диагностики

`gwctl` — официальная CLI-утилита для управления Gateway API:

```bash
# Установка gwctl
kubectl krew install gwctl

# Просмотр всех Gateway с их статусом
gwctl get gateways -A

# Детальная информация о конкретном Gateway
gwctl describe gateway <name> -n <namespace>

# Просмотр HTTPRoute и их связей
gwctl get httproutes -A

# Экспорт конфигурации для анализа
gwctl export gateways -A > gateways-backup.yaml
```

## Troubleshooting

### Типичные ошибки и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Gateway` в статусе `Accepted: False` | Неверное имя GatewayClass или класс не существует | Проверить `gatewayClassName` в Gateway и наличие GatewayClass |
| `Gateway` в статусе `Programmed: False` | Ошибка конфигурации Data Plane | Проверить логи контроллера, состояние прокси-серверов |
| `HTTPRoute` в статусе `ResolvedRefs: False` | Отсутствует ReferenceGrant для кросс-namespace ссылок | Создать ReferenceGrant в namespace целевого ресурса |
| `Conflicted: True` на ListenerSet | Пересечение портов или хостов с другим ListenerSet | Проверить `allowedListeners` в Gateway и уникальность портов |
| `InvalidParameter` в BackendTLSPolicy | Неверная ссылка на CA-сертификат | Проверить наличие Secret с CA и корректность `targetRef` |
| Трафик не маршрутизируется | Неверный parentRef в Route | Проверить имя Gateway и namespace в `parentRef` |

### Диагностика проблем с сертификатами

```bash
# Проверка статуса сертификатов
kubectl get gateway <name> -n <namespace> -o jsonpath='{.status.listeners[*].conditions[?(@.type=="ResolvedRefs")]}'

# Проверка наличия TLS-секретов
kubectl get secrets -n <namespace> -o json | jq '.items[] | select(.type == "kubernetes.io/tls") | .metadata.name'

# Проверка ReferenceGrant для секретов
kubectl get referencegrant -A
```

### Диагностика проблем с маршрутизацией

```bash
# Проверка всех HTTPRoute и их статусов
kubectl get httproute -A -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,GATEWAY:.spec.parentRefs[0].name,ACCEPTED:.status.parents[0].conditions[?(@.type=="Accepted")].status,RESOLVED:.status.parents[0].conditions[?(@.type=="ResolvedRefs")].status'

# Проверка логов прокси-сервера для конкретного маршрута
kubectl logs -n <namespace> -l app=<proxy-label> --tail=100 | grep <route-name>
```

## Best Practices

### Организация конфигурации

1. **Используйте отдельные Gateway для разных сред:**
   - production-gateway, staging-gateway, dev-gateway
   - Изолирует трафик и упрощает управление

2. **Применяйте принцип наимших привилегий:**
   - Разработчики управляют только Route в своих namespace
   - Операторы управляют Gateway и сертификатами
   - Администраторы управляют GatewayClass

3. **Используйте ReferenceGrant осмотрительно:**
   - Создавайте только необходимые разрешения
   - Регулярно аудитируйте существующие ReferenceGrant
   - Удаляйте неиспользуемые разрешения

### Безопасность

1. **Всегда используйте TLS:**
   - Настройте терминацию TLS на Gateway
   - Используйте cert-manager для автоматизации сертификатов
   - Включите HSTS через политики

2. **Защищайте East-West трафик:**
   - Используйте BackendTLSPolicy для mTLS к бэкендам
   - Применяйте Network Policies для ограничения доступа на уровне подов

3. **Аудит и мониторинг:**
   - Настройте алерты на изменения статусов Gateway API ресурсов
   - Логируйте все изменения конфигурации
   - Используйте RBAC для контроля доступа к ресурсам

### Производительность

1. **Используйте Direct Pod Targeting:**
   - Снижает задержки за счет устранения лишнего хопа через kube-proxy
   - Позволяет применять продвинутые алгоритмы балансировки

2. **Оптимизируйте количество ресурсов:**
   - Группируйте маршруты в один HTTPRoute где возможно
   - Используйте ListenerSet для масштабирования слушателей
   - Избегайте избыточных Gateway

3. **Кэширование и сжатие:**
   - Настройте кэширование статических ресурсов через политики
   - Включите gzip/brotli сжатие для HTTP-трафика

## Дополнительная информация

**Актуальность:** Проект `kubernetes/ingress-nginx` официально перешёл в статус **End of Life (EOL)** 24 марта 2026 года. Использование классического Ingress в новых проектах запрещено политиками безопасности; существующие инсталляции должны быть мигрированы.

**Версионирование:** Актуальная версия Gateway API — v1.6.x (Standard Channel). Для получения новых функций (GRPCRoute, BackendTLSPolicy, ListenerSet) используйте Experimental Channel.

**Связанные ресурсы и руководства:**

- [Ресурсы (CRD)](./resources.md) — детальное описание иерархии объектов.
- [Базовые сценарии](./practical_basic.md) — практические примеры настройки.
- [Миграция с Ingress](./migration.md) — пошаговое руководство по переходу.
- [Маршрутизация L4](./layer4_routing.md) — работа с TCP и UDP (TCPRoute).
- [Провайдер-специфичная конфигурация](./provider_specific_config.md) — механизмы Policy Attachment.
- [Расширенная маршрутизация](./routing_features.md) — фильтры, CORS, Rewrite.
- [NGINX Gateway Fabric](./nginx_gateway_fabric.md) — установка и настройка реализации от NGINX.
- [Мониторинг и наблюдаемость](./monitoring.md) — Prometheus, Grafana, алертинг, OpenTelemetry.
- [Высокая доступность](./high_availability.md) — PDB, HA, disaster recovery.
- [GitOps и CI/CD](./gitops_cicd.md) — ArgoCD, Flux, валидация манифестов.
- [Безопасность](./security_policies.md) — NetworkPolicy, RBAC, Kyverno, OPA Gatekeeper.
- [Глубокая диагностика](./troubleshooting_deep_dive.md) — Envoy admin, packet capture, troubleshooting.

Официальная спецификация: [Gateway API Documentation](https://gateway-api.sigs.k8s.io/).

Обзор устаревшего механизма: [Ingress: Обзор](../Ingress/overview.md).
