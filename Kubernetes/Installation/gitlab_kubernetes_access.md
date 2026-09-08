# Методы доступа к GitLab в Kubernetes

Руководство по настройке внешнего доступа к веб-интерфейсу и Git-сервисам GitLab при развертывании в кластерах Kubernetes. Охватывает HTTP/HTTPS, SSH, Container Registry, GitLab Pages и агентную интеграцию.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Ingress** | Ресурс Kubernetes, управляющий HTTP/HTTPS доступом к сервисам через правила маршрутизации (L7). Определяет домены, пути и бэкенды. |
| **Ingress Controller** | Реализация Ingress (nginx, traefik, HAProxy, Envoy). Работает как Pod в кластере и обрабатывает входящий HTTP/HTTPS трафик, применяя правила из ресурсов Ingress. |
| **Gateway API** | Современный стандарт (GA с Kubernetes 1.29) для управления трафиком, заменяющий Ingress. Используется в Helm-чартах GitLab 17.x+ через Envoy Gateway. Поддерживает delegate-модель, TCP/UDP и более гибкую RBAC. |
| **LoadBalancer** | Тип Service, запрашивающий внешний IP. В bare-metal среде реализуется через MetalLB. В облаке — через cloud-provider. |
| **NodePort** | Тип Service, открывающий доступ к подам через статический порт на каждом узле кластера (30000–32767). Самый простой способ для тестов и малых сред. |
| **MetalLB** | Решение для балансировки нагрузки в bare-metal Kubernetes-кластерах, предоставляющее внешние IP-адреса из заранее определённых пулов. См. [Настройка MetalLB](../Networking/metallb.md). |
| **Cert-Manager** | Контроллер для автоматического выпуска, обновления и отзыва TLS-сертификатов (Let's Encrypt, внутренние CA). Интегрируется с Ingress через аннотации. |
| **GitLab Agent for Kubernetes (KAS)** | Агент для защищённой bidirectional-связи GitLab с кластером через gRPC-туннель. Основной метод интеграции CI/CD с Kubernetes (GitLab 16.0+). Подробнее см. [Интеграция GitLab CI с Kubernetes](../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md). |
| **SSH-доступ** | Доступ через порт 22 (или альтернативный) для операций `git clone/push` по протоколу SSH. В Kubernetes требует специальной настройки из-за конфликта с SSH узлов. |
| **ExternalDNS** | Инструмент для автоматического создания DNS-записей на основе Ingress/Service. Работает с локальными DNS-серверами (CoreDNS, PowerDNS, RFC2136) и облачными провайдерами. |
| **NetworkPolicy** | Объект Kubernetes, ограничивающий сетевой трафик между подами. Используется для изоляции пространств имён GitLab и ограничения доступа к сервисам. |

---

## Основные концепции

### Протоколы и порты

Для полноценной работы GitLab требуется настройка доступа по двум основным протоколам:
1.  **HTTP/HTTPS (Порты 80, 443):** Веб-интерфейс, API, Container Registry, KAS (Kubernetes Agent Server), Webhooks.
2.  **SSH (Порт 22):** Операции с репозиториями. В Kubernetes порт 22 часто занят системным SSH узлов, что требует использования альтернативных портов (например, 2222) или выделенных IP.

| Сервис | Протокол | Порт по умолчанию | Назначение |
| :--- | :--- | :--- | :--- |
| GitLab Webservice | HTTP/HTTPS | 80, 443 | Веб-интерфейс и REST API |
| Container Registry | HTTPS | 443 (тот же Ingress) | Хранение Docker-образов |
| GitLab Pages | HTTP/HTTPS | 80, 443 | Статические сайты проектов |
| GitLab SSH | TCP | 22 или 2222 | Git clone/push/fetch |
| KAS (Agent Server) | gRPC | 443 (через Ingress) | Связь с GitLab Agent |
| Webhooks | HTTP/S | 80, 443 | Уведомления от внешних систем |

### Архитектура трафика

В современных инсталляциях GitLab Helm Chart трафик проходит через следующие уровни:
`Клиент → Внешний Балансировщик (L4) → Ingress/Gateway Controller (L7) → GitLab Webservice (Puma)`.

- **Встроенный Ingress:** По умолчанию чарт устанавливает `ingress-nginx`. Контроллер работает как Deployment и обрабатывает правила Ingress для всех сервисов GitLab.
- **Gateway API:** Начиная с версии чарта 8.0 (GitLab 17.0), введена экспериментальная поддержка Gateway API через Envoy Gateway. В версии 17.5+ — рекомендуется для production. Gateway API поддерживает delegate-модель (перенаправление трафика между контроллерами) и нативную TCP/UDP маршрутизацию.
- **Переход с Ingress на Gateway API:** При миграции чарт поддерживает параллельную работу обоих контроллеров. Рекомендуется поэтапный переход: сначала Gateway API для новых сервисов, затем миграция существующих.

### Ingress — детали конфигурации

Ingress в GitLab управляется через параметры Helm-чарта и аннотации. Ключевые аспекты:

| Параметр | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `global.ingress.configureCertmanager` | Автоматическая интеграция с cert-manager | `true` для production |
| `global.ingress.class` | Класс Ingress-контроллера | Указывать при нескольких контроллерах |
| `nginx-ingress.controller.service.type` | Тип Service для контроллера | `LoadBalancer` (production), `NodePort` (тесты) |
| `nginx-ingress.controller.replicaCount` | Количество реплик контроллера | 2+ для HA |
| `nginx-ingress.controller.resources` | Ресурсы контроллера | Зависит от нагрузки |

**Аннотации для Ingress:**

```yaml
# Пример аннотаций для Ingress-правил GitLab
annotations:
  nginx.ingress.kubernetes.io/proxy-body-size: "0"  # Без ограничения размера загрузки
  nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
  nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
  nginx.ingress.kubernetes.io/ssl-redirect: "true"
  nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
```

### NetworkPolicy — изоляция и безопасность

Для ограничения сетевого трафика к GitLab-сервисам рекомендуется применять NetworkPolicy:

```yaml
# Изоляция namespace gitlab от внешних подов
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: gitlab-allow-ingress-only
  namespace: gitlab
spec:
  podSelector: {}
  policyTypes:
    - Ingress
  ingress:
    - from:
        # Разрешить трафик только от Ingress-контроллера
        - namespaceSelector:
            matchLabels:
              app.kubernetes.io/name: ingress-nginx
      ports:
        - protocol: TCP
          port: 80
        - protocol: TCP
          port: 443
```

**Порядок приоритета NetworkPolicy:**
1. По умолчанию все трафики разрешены (если нет NetworkPolicy).
2. Как только применяется хотя бы один NetworkPolicy с `policyTypes: [Ingress]`, все входящие трафики блокируются, кроме явно разрешённых.
3. NetworkPolicy аддитивны — каждое новое правило добавляется к существующим.

### Аутентификация и доступ

GitLab поддерживает несколько методов аутентификации для доступа из Kubernetes:

| Метод | Описание | Безопасность |
| :--- | :--- | :--- |
| **OAuth2/OIDC** | Внешний провайдер идентичности (Keycloak, Dex, GitLab SAML) | Высокая — централизованное управление |
| **Personal Access Tokens** | Токены для API-доступа | Средняя — требует ротации |
| **Deploy Tokens** | Токены для CI/CD (read-only registry/repository) | Высокая — минимальные привилегии |
| **SSH Keys** | Ключи для git clone/push | Высокая — аутентификация по ключу |
| **GitLab Agent (KAS)** | gRPC-туннель для CI/CD | Высокая — mTLS, без KUBECONFIG |

### Сертификаты — три сценария

| Сценарий | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Self-signed** | Генерируется встроенным cert-manager | Тесты, разработка |
| **Let's Encrypt** | Бесплатные сертификаты от Let's Encrypt | Production с публичным DNS |
| **Custom CA** | Сертификаты от внутреннего CA | Корпоративные среды, закрытые сети |

---

## Практические сценарии

### 1. MetalLB для bare-metal кластеров

Если кластер развернут на собственных серверах, используйте MetalLB для реализации типа `LoadBalancer`.

**Установка MetalLB:**

```bash
# Применение манифестов MetalLB
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.14.9/config/manifests/metallb-native.yaml

# Ожидание готовности
kubectl wait --namespace metallb-system \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/name=metallb \
  --timeout=300s
```

**Настройка пула IP-адресов:**

```yaml
# metallb-pool.yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: gitlab-pool
  namespace: metallb-system
spec:
  addresses:
    - 192.168.1.50-192.168.1.60  # Пул IP для GitLab-сервисов
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: gitlab-l2
  namespace: metallb-system
spec:
  ipAddressPools:
    - gitlab-pool
```

```bash
kubectl apply -f metallb-pool.yaml
```

**Установка GitLab с выделенным IP:**

```bash
# Установка с привязкой к конкретному IP из пула MetalLB
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  --set nginx-ingress.controller.service.type=LoadBalancer \
  --set nginx-ingress.controller.service.loadBalancerIP=192.168.1.50 \
  --set global.hosts.domain=gitlab.local \
  --set global.hosts.gitlab.name=gitlab.gitlab.local
```

**Проверка:**

```bash
# Ожидание назначения внешнего IP
kubectl get svc -n gitlab -w
# → gitlab-nginx-ingress-controller   LoadBalancer   192.168.1.50   ...

# Проверка доступности
curl -k https://192.168.1.50
```

### 2. NodePort — простой доступ без балансировщика

Для тестов и минимальных сред NodePort — самый быстрый способ. Не требует MetalLB или облачного провайдера.

**Настройка в values.yaml:**

```yaml
nginx-ingress:
  controller:
    service:
      type: NodePort
      nodePorts:
        http: 30080
        https: 30443
```

**Установка:**

```bash
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  --set nginx-ingress.controller.service.type=NodePort \
  --set nginx-ingress.controller.service.nodePorts.http=30080 \
  --set nginx-ingress.controller.service.nodePorts.https=30443
```

**Доступ:**

```bash
# Через IP любого узла кластера
curl -k https://<any-node-ip>:30443

# Или через localhost (если kubectl на одном из узлов)
curl -k https://localhost:30443
```

**Ограничения NodePort:**
- Порты в диапазоне 30000–32767 (ограничение Kubernetes).
- Нет автоматического переключения при отказе узла (клиент должен знать IP всех узлов).
- Не подходит для production с высокой нагрузкой.

### 3. Настройка SSH-доступа

Существует три способа проброса SSH-трафика:

#### 3.1. Тип Service: LoadBalancer

Самый простой способ для production с выделенными IP. Создаётся отдельный L4 балансировщик для порта 22.

```yaml
# ssh-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: gitlab-shell
  namespace: gitlab
spec:
  type: LoadBalancer
  ports:
    - name: ssh
      port: 22
      targetPort: 2222
      protocol: TCP
  selector:
    app: webservice
    release: gitlab
```

#### 3.2. TCP Ingress (Nginx)

Проксирование порта 22 через Ingress-контроллер. Требует добавления порта в `ConfigMap` контроллера.

```bash
# Добавление TCP-порта в ConfigMap
kubectl edit configmap -n gitlab gitlab-nginx-ingress-controller

# Добавить в data:
# 2222: "gitlab/gitlab-shell:2222"
```

#### 3.3. Альтернативный порт (2222)

Использование порта 2222 для избежания конфликтов с SSH узлов. Рекомендуется для bare-metal.

**Настройка альтернативного порта в GitLab:**

```yaml
global:
  shell:
    port: 2222
```

**Проверка:**

```bash
# Клонирование через альтернативный порт
git clone ssh://git@gitlab.example.com:2222/group/project.git
```

### 4. Автоматизация SSL с Cert-Manager

#### 4.1. Let's Encrypt (Production)

GitLab чарт может автоматически устанавливать `cert-manager` или использовать существующий.

```yaml
# values.yaml для Let's Encrypt
global:
  hosts:
    domain: example.com
    gitlab:
      name: gitlab.example.com
      https: true
  ingress:
    configureCertmanager: true
    tls:
      enabled: true
certmanager:
  install: true
certmanager-issuer:
  email: admin@example.com
  install: true
```

```bash
# Установка с cert-manager
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  --values values.yaml
```

#### 4.2. Custom CA (Корпоративная среда)

```yaml
# Создание ClusterIssuer для внутреннего CA
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: internal-ca
spec:
  ca:
    secretName: internal-ca-keypair
---
# Создание сертификата
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: gitlab-tls
  namespace: gitlab
spec:
  secretName: gitlab-tls-secret
  issuerRef:
    name: internal-ca
    kind: ClusterIssuer
  dnsNames:
    - gitlab.example.com
    - registry.example.com
    - pages.example.com
```

#### 4.3. Self-signed (Тесты)

```yaml
global:
  hosts:
    domain: gitlab.local
    gitlab:
      name: gitlab.gitlab.local
      https: false  # Отключение SSL для тестов
  ingress:
    configureCertmanager: false
```

### 5. Настройка DNS

#### 5.1. Локальный DNS (bare-metal)

Для bare-metal кластеров без облачного DNS используйте CoreDNS, PowerDNS или简单的 `/etc/hosts`.

**Split-horizon DNS (рекомендуется):**

```bash
# Внутренний DNS возвращает приватный IP
# Внешний DNS — публичный IP (если есть)
# Настройка зависит от DNS-сервера

# Пример CoreDNS (ConfigMap)
# gitlab.example.com → 192.168.1.50 (внутренний)
# registry.example.com → 192.168.1.50
# pages.example.com → 192.168.1.50
```

**Минимальный /etc/hosts (для тестов):**

```bash
# Добавить на все рабочие станции
echo "192.168.1.50 gitlab.example.com registry.example.com pages.example.com" | sudo tee -a /etc/hosts
```

#### 5.2. ExternalDNS с PowerDNS/RFC2136

Для автоматического создания DNS-записей в локальной среде:

```yaml
# values.yaml для ExternalDNS с PowerDNS
external-dns:
  enabled: true
  provider: pdns
  pdns:
    apiUrl: http://pdns.example.com:8081
    apiKey: YOUR_PDNS_API_KEY
  domainFilters:
    - example.com
  policy: upsert-only
```

### 6. Доступ к Container Registry

Container Registry по умолчанию доступен через тот же Ingress, что и GitLab, но на отдельном домене.

```yaml
# values.yaml
global:
  registry:
    enabled: true
    host: registry.example.com
    https: true
```

**Проверка доступа:**

```bash
# Вход в Registry
docker login registry.example.com
# → Username: <your-username>
# → Password: <personal-access-token>

# Пуш образа
docker tag myimage:latest registry.example.com/mygroup/myproject/myimage:latest
docker push registry.example.com/mygroup/myproject/myimage:latest
```

**Сертификаты для Registry:**

```bash
# Если используется самоподписанный сертификат — добавить в доверенные
sudo mkdir -p /etc/docker/certs.d/registry.example.com
sudo cp ca.crt /etc/docker/certs.d/registry.example.com/ca.crt
```

### 7. Доступ к GitLab Pages

GitLab Pages требует wildcard-записи в DNS и often выделенного IP.

```yaml
# values.yaml
global:
  pages:
    enabled: true
    host: pages.example.com
    https: true
    # Если Pages на отдельном IP:
    # ip: 192.168.1.51
```

**DNS-запись:**

```bash
# Wildcard-запись для Pages
*.pages.example.com → 192.168.1.50 (или выделенный IP)
```

**Включение Pages в проекте:**

```yaml
# .gitlab-ci.yml
pages:
  stage: deploy
  script:
    - mkdir public
    - cp -r site/* public/
  artifacts:
    paths:
      - public
```

### 8. GitLab Agent for Kubernetes (CI/CD Tunnel)

Для интеграции CI/CD с кластером Kubernetes используется GitLab Agent — рекомендуемый метод. Устанавливается через Helm и обеспечивает защищённый gRPC-туннель.

**Установка агента:**

```bash
# Добавление репозитория
helm repo add gitlab https://charts.gitlab.com/
helm repo update

# Установка агента
helm install gitlab-agent gitlab/gitlab-agent \
  --namespace gitlab-agent \
  --create-namespace \
  --set config.token=<agent-registration-token>
```

**Конфигурация агента:**

```yaml
# .gitlab/agents/my-cluster/config.yaml
gitlab_access:
  project: my-group/my-project
  agents:
    my-cluster:
      logs:
        enabled: true
      terminal:
        enabled: true
      resources:
        limits:
          cpu: "0.5"
          memory: "256Mi"
```

Подробнее см. [Интеграция GitLab CI с Kubernetes](../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md).

### 9. Production Hardening

#### 9.1. Rate Limiting (Nginx Ingress)

```yaml
nginx-ingress:
  controller:
    config:
      limit-req-status-code: "429"
      limit-connections: "100"
    annotations:
      nginx.ingress.kubernetes.io/limit-rps: "50"
      nginx.ingress.kubernetes.io/limit-burst-multiplier: "5"
```

#### 9.2. NetworkPolicy для GitLab Namespace

```yaml
# gitlab-network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: gitlab-allow-incoming
  namespace: gitlab
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        # Разрешить от Ingress-контроллера
        - namespaceSelector:
            matchLabels:
              app.kubernetes.io/name: ingress-nginx
      ports:
        - port: 80
        - port: 443
  egress:
    # Разрешить DNS
    - to: []
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    # Разрешить HTTPS (для Let's Encrypt, Webhooks)
    - to: []
      ports:
        - port: 443
          protocol: TCP
```

#### 9.3. Ресурсы для компонентов GitLab

```yaml
# Минимальные ресурсы для production
gitlab:
  webservice:
    resources:
      requests:
        cpu: "500m"
        memory: "2Gi"
      limits:
        cpu: "2"
        memory: "4Gi"
  sidekiq:
    resources:
      requests:
        cpu: "500m"
        memory: "2Gi"
      limits:
        cpu: "2"
        memory: "4Gi"
  gitaly:
    resources:
      requests:
        cpu: "100m"
        memory: "512Mi"
      limits:
        cpu: "1"
        memory: "2Gi"
```

#### 9.4. Мониторинг здоровья

```bash
# Проверка всех подов GitLab
kubectl get pods -n gitlab -l release=gitlab

# Проверка статуса Helm-релиза
helm status gitlab -n gitlab

# Просмотр логов Webservice
kubectl logs -n gitlab -l app=webservice -f --tail=100

# Проверка Ingress-правил
kubectl get ingress -n gitlab
kubectl describe ingress -n gitlab
```

---

## Решение проблем

### Типичные ошибки и их решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **LoadBalancer в статусе Pending** | Отсутствие контроллера балансировщика (MetalLB, cloud-provider) | Проверьте статус MetalLB: `kubectl get pods -n metallb-system`. Для bare-metal установите [MetalLB](../Networking/metallb.md). |
| **502 Bad Gateway** | GitLab Webservice (Puma) не загрузился или упал | `kubectl get pods -l app=webservice` — проверьте статус. Просмотрите логи: `kubectl logs <pod-name>`. Увеличьте ресурсы или время readinessProbe. |
| **504 Gateway Timeout** | Webservice перегружен или завис | Проверьте потребление CPU/RAM подов. Увеличьте `proxy-read-timeout` в аннотациях Ingress. |
| **SSL: "Certificate Signed by Unknown Authority"** | Самоподписанные сертификаты | Установите `global.hosts.https: false` для тестов или настройте `ClusterIssuer` в cert-manager. |
| **SSH: "Connection refused"** | Порт 22 не проброшен или занят | Используйте порт 2222: `global.shell.port: 2222`. Проверьте Service для shell: `kubectl get svc -l app=shell`. |
| **Registry: "unauthorized"** | Текущий токен GitLab не имеет доступа к registry | Создайте Personal Access Token с `read_registry`/`write_registry` scopes. |
| **Ingress не создаёт правила** | Неверный `global.hosts.domain` или `ingress.class` | Проверьте `kubectl get ingress -n gitlab`. Убедитесь, что контроллер работает в том же namespace. |
| **cert-manager: "Challenge failed"** | DNS не резолвит домен или порт 80 недоступен для HTTP-01 | Проверьте DNS: `dig gitlab.example.com`. Убедитесь, что Ingress доступен из интернета для Let's Encrypt. |
| **Gateway API: "no matched GatewayClass"** | Не установлен Gateway API контроллер (Envoy Gateway) | Установите Envoy Gateway или включите встроенный: `gateway.enabled: true`. |
| **GitLab Pages: 404** | Wildcard DNS не настроен или Pages отключены | Проверьте `*.pages.example.com` DNS-запись. Убедитесь, что `global.pages.enabled: true`. |

### Диагностический чек-лист

```bash
# 1. Статус Helm-релиза
helm status gitlab -n gitlab

# 2. Все поды GitLab
kubectl get pods -n gitlab

# 3. Все сервисы
kubectl get svc -n gitlab

# 4. Ingress-правила
kubectl get ingress -n gitlab -o yaml

# 5. NetworkPolicy (если есть)
kubectl get networkpolicy -n gitlab

# 6. Сертификаты
kubectl get certificates -n gitlab
kubectl describe certificate -n gitlab

# 7. Lоги Webservice
kubectl logs -n gitlab -l app=webservice --tail=50

# 8. Состояние MetalLB (bare-metal)
kubectl get ipaddresspool -n metallb-system
kubectl get l2advertisement -n metallb-system

# 9. Проверка DNS
nslookup gitlab.example.com
nslookup registry.example.com
```

### Восстановление после сбоя

```bash
# Перезапуск всех компонентов GitLab
kubectl rollout restart deployment -n gitlab

# Откат Helm-релиза на предыдущую версию
helm rollback gitlab <revision> -n gitlab

# Полная переустановка (с сохранением данных)
helm uninstall gitlab -n gitlab
# PersistentVolume остаются — данные не удалятся
helm install gitlab gitlab/gitlab -n gitlab --values values.yaml
```

---

## Дополнительная информация

### Совместимость (Август 2026)

| Компонент | Минимальная версия | Рекомендуемая |
| :--- | :--- | :--- |
| **Kubernetes** | 1.24 | 1.29+ |
| **Helm** | 3.9.4 | 3.14+ |
| **GitLab Helm Chart** | 7.x | 8.x (GitLab 17.x+) |
| **cert-manager** | 1.13 | 1.15+ |
| **MetalLB** | 0.13 | 0.14+ |
| **Gateway API** | 1.0 | 1.1+ |

### Лучшие практики

- **Используйте Gateway API** для новых установок GitLab 17.x+ — он提供更多功能 по сравнению с Ingress.
- **NetworkPolicy** — применяйте к namespace `gitlab` для ограничения трафика.
- **cert-manager** — автоматизируйте SSL через Let's Encrypt (production) или внутренний CA (корпоративная среда).
- **Rate Limiting** — настраивайте `limit-rps` и `limit-connections` для защиты от DDoS.
- **Ресурсы** — всегда задавайте `requests` и `limits` для подов GitLab (webservice, sidekiq, gitaly).
- **Резервное копирование** — регулярно создавайте снимки PostgreSQL и Gitaly данных.
- **Мониторинг** — настройте алерты на unavailable pods, certificate expiration, PVC usage.

### Дополнительные ссылки

- [Установка GitLab через Helm](./gitlab_kubernetes_helm_installation.md)
- [Типы сервисов Kubernetes](../Networking/Service/service_types_summary.md)
- [Настройка MetalLB](../Networking/metallb.md)

---

## См. также

- [Установка GitLab через Helm](./gitlab_kubernetes_helm_installation.md)
- [Устранение проблем с GitLab в Kubernetes](./gitlab_installation_troubleshooting.md)
- [Интеграция GitLab CI с Kubernetes](../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md)
