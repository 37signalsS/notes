# Внешний доступ в Bare-metal — NodePort, Nginx и dnsmasq

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

    # Интеграция WAF (опционально, например Coraza)
    # waf on;

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
    }
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
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
  externalTrafficPolicy: Local
  ports:
    - name: http
      port: 80
      targetPort: 80
      nodePort: 32080
  selector:
    app: ingress-controller
```

## Дополнительная информация

### Автоматизация и масштабирование

-   **Динамический Upstream:** Ручное обновление списка узлов в `nginx.conf` при расширении кластера подвержено ошибкам. Рекомендуется использовать скрипты, опрашивающие API Kubernetes (`kubectl get nodes -o json`), или специализированные модули (например, `consul-template` или `nginx-upsync-module`).
-   **Отказоустойчивость шлюза:** Чтобы прокси-сервер не стал единой точкой отказа (SPOF), используйте **Keepalived** для организации плавающего IP (VIP) между двумя идентичными узлами Nginx.
-   **Безопасность:**
    -   Терминируйте SSL/TLS на внешнем Nginx для централизованного управления сертификатами.
    -   Используйте `ModSecurity` или `Coraza` для защиты приложений внутри кластера от атак на уровне L7.

### См. также

-   **[Обзор MetalLB](../metallb.md)** — автоматизация LoadBalancer в Bare-metal.
-   **[NodePort в деталях](../Service/service_type_nodeport.md)** — механика работы и ограничения портов.
-   **[Gateway API — миграция](../gateway_api/migration.md)** — современный стандарт управления трафиком.
