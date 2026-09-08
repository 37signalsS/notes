# Внешний доступ в Bare-metal — NodePort, Nginx и dnsmasq

> [!WARNING]
> **Внимание (2026):** Решение с внешним Nginx-прокси и NodePort устарело и **не рекомендуется** для новых проектов. Используйте [MetalLB](../metallb.md) (L2/BGP) или [Gateway API](../gateway_api/migration.md) (Envoy Gateway, Traefik v3). Данное руководство сохранено для поддержки legacy-инфраструктур и понимания архитектурных решений.

---

## Предварительные требования

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **Kubernetes** | 1.25+ | Кластер с включенным `kube-proxy` (режим iptables или nftables). |
| **Внешний сервер (Nginx)** | 1.24+ (или Angie) | Reverse-proxy,.terminate TLS, терминирующий TLS и балансирующий трафик по NodePort. |
| **DNS-сервер (dnsmasq)** | 2.89+ | Резолвинг доменных имён кластера на IP внешнего прокси. |
| **Keepalived** | 2.2+ | (Опционально) Организация VIP (Virtual IP) между двумя узлами прокси для отказоустойчивости. |
| **Firewall** | — | Открытые порты 80, 443 на внешнем прокси; порты 30000–32767 между прокси и узлами кластера. |

> **Важно:** Убедитесь, что `kube-proxy` работает на каждом узле кластера. Проверка: `kubectl get pods -n kube-system -l k8s-app=kube-proxy`.

---

## Определения

**NodePort** — тип Service в Kubernetes, открывающий статический порт (диапазон 30000–32767) на всех узлах кластера. Трафик, поступающий на этот порт, перенаправляется на соответствующие поды через ClusterIP сервиса.

**dnsmasq** — легкий DNS-сервер и DHCP-сервер, используемый в Bare-metal средах для централизованного управления локальными доменными именами и резолвинга запросов к внешним прокси-серверам.

**Внешний Nginx-прокси** — сервер, находящийся за пределами кластера Kubernetes, который принимает клиентский трафик на стандартных портах (80/443) и балансирует его между IP-адресами узлов кластера на специфические порты `NodePort`.

## Базовые концепции

В Bare-metal инсталляциях отсутствие нативного `LoadBalancer` (как в AWS/GCP) требует альтернативных подходов. Метод с внешним прокси и DNS является надежной альтернативой [MetalLB](../metallb.md) в случаях, когда сетевая инфраструктура ограничивает использование L2 (ARP/NDP) или BGP.

### Архитектура решения в 2026 году

1.  **Клиент:** обращается к домену (например, `api.k8s.local`).
2.  **DNS (dnsmasq):** резолвит имя в IP-адрес внешнего прокси (VIP или адрес конкретного узла).
3.  **Nginx Proxy:** терминирует TLS, применяет правила безопасности (WAF) и пересылает трафик на `NodePort` узлов кластера.
4.  **Data Plane (K8s):** Ingress-контроллер (например, Traefik v3) или реализация Gateway API принимает трафик и направляет его в целевой Pod.

### Сохранение IP-адреса клиента

Для передачи реального IP-адреса клиента (Client IP) через слои проксирования необходимо:
-   **X-Forwarded-For:** стандартный метод передачи заголовков в HTTP.
-   **Proxy Protocol (L4):** рекомендуется использовать, если Nginx работает в режиме `stream` или за ним стоит другой балансировщик, требующий сохранения данных о соединении на уровне TCP.
-   **`externalTrafficPolicy: Local`:** установка этого параметра в Service `NodePort` отключает SNAT внутри кластера, позволяя Ingress-контроллеру видеть IP прокси-сервера (или клиента, если используется Proxy Protocol).

> **Подробнее:** Механика прохождения трафика через `kube-proxy` (iptables/nftables/IPVS), SNAT и conntrack описаны в [NodePort — тип Service](../Service/service_type_nodeport.md#механика-прохождения-трафика).

### Когда использовать эту архитектуру

| Ситуация | Рекомендация |
| :--- | :--- |
| MetalLB не поддерживается (старое сетевое оборудование без L2/BGP) | ✅ Внешний Nginx прокси |
| Нужен доступ по стандартным портам 80/443 без NodePort | ✅ Внешний Nginx прокси |
| Кластер уже использует MetalLB | ❌ Используйте MetalLB |
| Есть поддержка Gateway API | ❌ Используйте Gateway API (Envoy Gateway, Traefik) |
| Нужна L7-балансировка на внешнем уровне | ✅ Внешний Nginx прокси |

### Decision Tree: выбор метода внешнего доступа

```
Нужен внешний доступ в bare-metal кластер?
├── Да
│   ├── MetalLB поддерживается сетевым оборудованием?
│   │   ├── Да → Используйте MetalLB (L2 или BGP)
│   │   └── Нет → Используйте внешний Nginx прокси (данное руководство)
│   └── Gateway API доступен и поддерживается?
│       └── Да → Рассмотрите Envoy Gateway / Traefik v3 с MetalLB
└── Нет → Внутренняя маршрутизация через ClusterIP
```

## Практические сценарии

### Шаг 1 — Настройка DNS (dnsmasq)

Создайте конфигурацию для управления локальной зоной кластера.

```bash
# /etc/dnsmasq.d/kubernetes.conf
address=/k8s.local/192.168.1.100  # Направляем всю зону на IP прокси
```

```bash
sudo systemctl restart dnsmasq
# → Job for dnsmasq.service started.

dig +short myapp.k8s.local @localhost
# → 192.168.1.100
```

### Шаг 2 — Конфигурация Nginx как шлюза

В 2026 году рекомендуется использовать **Angie** или современные сборки **Nginx** с поддержкой динамических апстримов. Ниже приведен пример классической конфигурации.

#### Базовая конфигурация (HTTP)

```nginx
# /etc/nginx/conf.d/k8s_gateway.conf

upstream k8s_nodes_http {
    # Рекомендуется указывать все worker-узлы для отказоустойчивости
    server 192.168.1.10:32080 max_fails=3 fail_timeout=10s;
    server 192.168.1.11:32080 max_fails=3 fail_timeout=10s;
    keepalive 64;
}

server {
    listen 80;
    server_name .k8s.local;

    # Защита от сканеров и ботов
    server_tokens off;

    # Ограничение размера тела запроса (защита от атак)
    client_max_body_size 50m;
    client_body_buffer_size 128k;

    # Логирование
    access_log /var/log/nginx/k8s_access.log;
    error_log /var/log/nginx/k8s_error.log warn;

    location / {
        proxy_pass http://k8s_nodes_http;
        proxy_http_version 1.1;

        # Передача метаданных клиента
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Поддержка WebSockets
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Таймауты (рекомендуемые значения)
        proxy_connect_timeout 10s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;

        # Буферизация
        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
    }

    # Health-check эндпоинт
    location /healthz {
        access_log off;
        return 200 "OK\n";
        add_header Content-Type text/plain;
    }

    # Rate limiting (защита от DDoS)
    # Определите zone в http {} контексте:
    #   limit_req_zone $binary_remote_addr zone=k8s:10m rate=100r/s;
    location / {
        limit_req zone=k8s burst=50 nodelay;
        limit_req_status 429;

        proxy_pass http://k8s_nodes_http;
        # ... (остальные директивы как выше)
    }
}
```

#### Конфигурация HTTPS (рекомендуется)

Для терминации TLS на внешнем Nginx создайте отдельный `server` блок:

```nginx
# /etc/nginx/conf.d/k8s_gateway_tls.conf

upstream k8s_nodes_https {
    server 192.168.1.10:32443 max_fails=3 fail_timeout=10s;
    server 192.168.1.11:32443 max_fails=3 fail_timeout=10s;
    keepalive 64;
}

# Redirect HTTP → HTTPS
server {
    listen 80;
    server_name .k8s.local;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name .k8s.local;

    # TLS сертификаты
    ssl_certificate     /etc/nginx/ssl/k8s.crt;
    ssl_certificate_key /etc/nginx/ssl/k8s.key;

    # Безопасные настройки TLS
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header X-XSS-Protection "1; mode=block" always;

    location / {
        proxy_pass http://k8s_nodes_https;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_connect_timeout 10s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

#### Валидация и перезагрузка

```bash
# Проверка синтаксиса конфигурации
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Перезагрузка без даунтайма
sudo systemctl reload nginx
# → Применение конфигурации без разрыва соединений

# Проверка, что Nginx слушает нужные порты
sudo ss -tlnp | grep nginx
# → LISTEN  0  128  0.0.0.0:80    0.0.0.0:*  users:(("nginx",pid=1234,fd=6))
# → LISTEN  0  128  0.0.0.0:443   0.0.0.0:*  users:(("nginx",pid=1234,fd=7))
```

### Шаг 3 — Настройка ресурсов в Kubernetes

Для корректной работы шлюза необходимо настроить Ingress-контроллер или шлюз Gateway API.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: ingress-controller
  namespace: ingress-system
spec:
  type: NodePort
  externalTrafficPolicy: Local  # Сохраняет Client IP
  ports:
    - name: http
      port: 80
      targetPort: 80
      nodePort: 32080
    - name: https
      port: 443
      targetPort: 443
      nodePort: 32443
  selector:
    app: ingress-controller
```

**Проверка после применения манифестов:**

```bash
kubectl apply -f service-ingress.yaml

# Проверка, что сервис создан и получил NodePort
kubectl get svc ingress-controller -n ingress-system
# → NAME                TYPE       CLUSTER-IP     EXTERNAL-IP   PORT(S)                      AGE
# → ingress-controller  NodePort   10.96.x.x     <none>        80:32080/TCP,443:32443/TCP   2m

# Проверка, что поды запущены и готовы
kubectl get pods -n ingress-system -o wide
# → NAME                     READY   STATUS    RESTARTS   AGE   IP           NODE
# → ingress-controller-abc   1/1     Running   0          3m    10.244.x.x   worker-1

# Проверка, что трафик проходит через внешний прокси
curl -i http://192.168.1.100/myapp -H "Host: myapp.k8s.local"
# → HTTP/1.1 200 OK
# → Server: nginx
```

**Важные замечания:**
- `externalTrafficPolicy: Local` — **обязательно** для сохранения IP-адреса клиента и предотвращения лишних hop'ов между узлами.
- Если контроллер работает как DaemonSet с `hostNetwork: true`, `NodePort` Service может не использоваться — трафик идет напрямую на IP узла.

---

### Шаг 4 — Настройка отказоустойчивости (Keepalived)

Для исключения единственной точки отказа (SPOF) на внешнем прокси используйте **Keepalived** с плавающим IP (VIP) между двумя узлами.

**Установка на обоих узлах прокси:**

```bash
# Debian/Ubuntu
sudo apt install keepalived -y

# RHEL/CentOS
sudo dnf install keepalived -y
```

**Конфигурация Keepalived ( master узел):**

```bash
# /etc/keepalived/keepalived.conf
vrrp_script check_nginx {
    script "/usr/bin/curl -s -o /dev/null http://localhost/healthz"
    interval 2
    weight -20
    fall 3
    rise 2
}

vrrp_instance VI_1 {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 101
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass k8s_secret
    }

    virtual_ipaddress {
        192.168.1.100/24
    }

    track_script {
        check_nginx
    }

    notify_master "/bin/systemctl restart nginx"
    notify_backup "/bin/systemctl stop nginx"
}
```

**Конфигурация Keepalived (backup узел):**

```bash
vrrp_instance VI_1 {
    state BACKUP
    interface eth0
    virtual_router_id 51
    priority 100
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass k8s_secret
    }

    virtual_ipaddress {
        192.168.1.100/24
    }

    track_script {
        check_nginx
    }
}
```

**Включение и проверка:**

```bash
sudo systemctl enable --now keepalived

# Проверка, что VIP назначен
ip addr show eth0 | grep 192.168.1.100
# → inet 192.168.1.100/24 scope global secondary eth0

# Тест failover: остановите nginx на master узле
sudo systemctl stop nginx
# → Через 4-6 секунд VIP должен переключиться на backup узел
```

---

### Шаг 5 — Настройка Firewall

Откройте необходимые порты для работы архитектуры:

```bash
# На внешнем прокси (Nginx + Keepalived)
# HTTP/HTTPS — для клиентов
sudo firewall-cmd --permanent --add-port=80/tcp
sudo firewall-cmd --permanent --add-port=443/tcp
# VRRP — для Keepalived (multicast)
sudo firewall-cmd --permanent --add-protocol=vrrp
# Health checks от LB
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.1.0/24" port port="80" protocol="tcp" accept'
sudo firewall-cmd --reload

# На узлах кластера (NodePort)
# NodePort диапазон — для внешнего прокси
sudo firewall-cmd --permanent --add-port=30000-32767/tcp
sudo firewall-cmd --reload
```

**Проверка:**

```bash
# С внешнего прокси до узлов кластера
nc -zv 192.168.1.10 32080
# → Connection to 192.168.1.10 32080 port [tcp/*] succeeded!

# С клиента до VIP
curl -v http://192.168.1.100/healthz
# → < HTTP/1.1 200 OK
```

## Дополнительная информация

### Автоматизация и масштабирование

-   **Динамический Upstream:** Ручное обновление списка узлов в `nginx.conf` при расширении кластера подвержено ошибкам. Рекомендуется использовать скрипты, опрашивающие API Kubernetes (`kubectl get nodes -o json`), или специализированные модули (например, `consul-template` или `nginx-upsync-module`).
-   **Отказоустойчивость шлюза:** Чтобы прокси-сервер не стал единой точкой отказа (SPOF), используйте **Keepalived** для организации плавающего IP (VIP) между двумя идентичными узлами Nginx (см. Шаг 4).
-   **Безопасность:**
    -   Терминируйте SSL/TLS на внешнем Nginx для централизованного управления сертификатами.
    -   Используйте `ModSecurity` или `Coraza` для защиты приложений внутри кластера от атак на уровне L7.
    -   Настройте rate limiting (`limit_req_zone`) для защиты от DDoS.
    -   Отключите отображение версии Nginx: `server_tokens off`.

### Мониторинг внешнего прокси

```bash
# Проверка активных соединений Nginx
curl -s http://localhost/nginx_status
# → Active connections: 256
# → server accepts handled requests
# →  16630948 16630948 31070465
# → Reading: 0 Writing: 5 Waiting: 251

# Проверка состояния Keepalived
sudo systemctl status keepalived
# → active (running) — VIP назначен на этом узле

# Проверка, что VIP доступен с клиента
ping -c 3 192.168.1.100
# → 64 bytes from 192.168.1.100: icmp_seq=1 ttl=64 time=0.5 ms

# Мониторинг NodePort с узлов кластера
kubectl logs -n ingress-system -l app=ingress-controller --tail=50
```

**Пример Prometheus-метрики для Nginx (через nginx-exporter):**

```bash
# Установка nginx-prometheus-exporter
docker run -d --name nginx-exporter \
  -p 9113:9113 \
  nginx/nginx-prometheus-exporter:latest \
  -nginx.scrape-uri=http://localhost/nginx_status

# Метрики: nginx_connections_active, nginx_http_requests_total
```

### Устранение неполадок

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Клиент не может подключиться к VIP** | Keepalived не запущен или VRRP заблокирован firewall | `sudo systemctl status keepalived` — проверьте состояние. Убедитесь, что порт VRRP (112/Proto) открыт: `sudo firewall-cmd --list-protocols`. |
| **502 Bad Gateway от внешнего Nginx** | NodePort недоступен или узел кластера не работает | `nc -zv 192.168.1.10 32080` — проверьте доступность NodePort. `kubectl get nodes` — проверьте состояние узлов. |
| **504 Gateway Timeout** | Под не готов или таймаут на проксировании | `kubectl get pods -o wide` — проверьте READY-столбец. Увеличьте `proxy_read_timeout` в Nginx. |
| **TTL/DNS не резолвится** | dnsmasq не запущен или неверная конфигурация | `sudo systemctl status dnsmasq` — проверьте состояние. `dig +short myapp.k8s.local @localhost` — проверьте резолв. |
| **Client IP не сохраняется** | `externalTrafficPolicy` установлена в `Cluster` | Измените Service: `kubectl patch svc ingress-controller -p '{"spec":{"externalTrafficPolicy":"Local"}}'`. |
| **VIP «плавает» между узлами** | Проблема с multicast или `virtual_router_id` | Убедитесь, что `virtual_router_id` одинаков на обоих узлах. Проверьте: `sudo tcpdump -i eth0 vrrp`. |
| **TLS: certificate error** | Сертификат истёк или неверный CN/SAN | `openssl x509 -in /etc/nginx/ssl/k8s.crt -text -noout` — проверьте дату и SAN. Обновите сертификат. |

**Диагностические команды:**

```bash
# Логи Nginx (последние ошибки)
sudo tail -f /var/log/nginx/k8s_error.log

# Проверка правил conntrack (высокое использование conntrack — бутылочное горлышко)
sudo conntrack -S
# → cpu=0 found=123456 invalid=789 lost=0 insert=0 insert_failed=0

# Проверка IPVS (если kube-proxy в режиме IPVS)
sudo ipvsadm -Ln
# → TCP  10.96.x.x:80 rr
#   -> 10.244.x.x:80    Masq    1      0          0
```

> **Подробнее:** Типичные проблемы с `kube-proxy` (iptables/nftables/IPVS) и `conntrack` описаны в [NodePort](../Service/service_type_nodeport.md#влияние-на-conntrack-connection-tracking) и [CNI и kube-proxy](../Network/cni_kube_proxy_roles.md).

### См. также

-   **[MetalLB](../metallb.md)** — автоматизация LoadBalancer в Bare-metal (рекомендуемое решение).
-   **[NodePort](../Service/service_type_nodeport.md)** — механика работы, `externalTrafficPolicy`, conntrack.
-   **[CNI и kube-proxy](../Network/cni_kube_proxy_roles.md)** — роли CNI и kube-proxy, режимы (iptables/nftables/IPVS).
-   **[Gateway API — миграция](../gateway_api/migration.md)** — современный стандарт управления трафиком.
-   **[Ingress — обзор](./overview.md)** — архитектура, аннотации, мониторинг.
